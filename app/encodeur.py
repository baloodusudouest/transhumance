"""0.10.0 : l'encodeur du PC (image ghcr.io/baloodusudouest/transhumance:encodeur, fichier pc/encodeur.yml).

Comme le calculateur de Millésime : il demande du travail à Transhumance (NAS) toutes les minutes, réencode une vidéo
avec le processeur du PC (la carte AMD n'est pas visible depuis Docker Desktop), renvoie le MP4, et recommence.
Il ne voit ni Immich ni le dossier des photos : seulement la porte /calcul de Transhumance, avec son jeton.

Variables : TRANSHUMANCE_URL, TRANSHUMANCE_JETON_CALCUL, MACHINE (nom du PC), THREADS (« auto » ou un nombre),
VEILLE_S (attente sans travail, 60 s), TRAVAIL (dossier de travail, /travail)."""
from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import httpx

from . import video

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s encodeur: %(message)s")
log = logging.getLogger("encodeur")
VIE_S = 60


class Encodeur:
    def __init__(self, url: str, jeton: str, machine: str = "", travail: Path = Path("/travail"), fils: str = "0",
                 transport: httpx.BaseTransport | None = None):
        self.machine = machine
        self.travail = travail
        self.fils = fils
        self.client = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {jeton}"},
                                   timeout=httpx.Timeout(3600, connect=15), transport=transport)

    def tour(self) -> bool:
        """Une vidéo, du début à la fin. Rend vrai s'il y en avait une."""
        r = self.client.post("/calcul/prendre", json={"machine": self.machine})
        if r.status_code == 204:
            return False
        r.raise_for_status()
        job = r.json()
        dossier = self.travail / str(job["id"])
        shutil.rmtree(dossier, ignore_errors=True)
        dossier.mkdir(parents=True, exist_ok=True)
        fini = threading.Event()

        def signes_de_vie():
            while not fini.wait(VIE_S):
                try:
                    self.client.post(f"/calcul/vie/{job['id']}", json={"machine": self.machine, "avance": None})
                except httpx.HTTPError:
                    pass

        veille = threading.Thread(target=signes_de_vie, daemon=True)
        veille.start()
        try:
            entree = dossier / ("original" + Path(job["nom"]).suffix)
            with self.client.stream("GET", f"/calcul/fichier/{job['id']}") as flux:
                flux.raise_for_status()
                with entree.open("wb") as f:
                    for bloc in flux.iter_bytes(1 << 20):
                        f.write(bloc)
            log.info("Réencodage de %s (%s Mo)", job["nom"], round(entree.stat().st_size / 1e6, 1))
            sortie = dossier / job["nom_mp4"]
            info = video.mettre_en_mp4("encode", entree, sortie, job["mesures"], job.get("date"), "cpu", self.fils)
            with sortie.open("rb") as f:
                r = self.client.post(f"/calcul/rendre/{job['id']}", content=iter(lambda: f.read(1 << 20), b""),
                                     params={"nom": job["nom_mp4"], "grossi": str(info["grossi"]).lower(),
                                             "leger": str(info["leger"]).lower()},
                                     headers={"Content-Type": "application/octet-stream"})
            r.raise_for_status()
            log.info("Rendu : %s", job["nom_mp4"])
        except video.ErreurVideo as exc:
            # Seul un échec de ffmpeg compte comme un essai raté (3 essais, puis la vidéo reste dans le dossier)
            log.warning("Échec sur %s : %s", job.get("nom"), exc)
            try:
                self.client.post(f"/calcul/erreur/{job['id']}", json={"message": str(exc)[:400]})
            except httpx.HTTPError:
                pass
        except (OSError, httpx.HTTPError) as exc:
            # Coupure réseau, disque : pas un essai raté ; sans signe de vie, la vidéo revient seule dans la file (10 min)
            log.warning("Interrompu sur %s : %s", job.get("nom"), exc)
        finally:
            fini.set()
            shutil.rmtree(dossier, ignore_errors=True)
        return True


def main() -> None:
    url, jeton = os.environ.get("TRANSHUMANCE_URL", ""), os.environ.get("TRANSHUMANCE_JETON_CALCUL", "")
    if not url or not jeton:
        sys.exit("TRANSHUMANCE_URL et TRANSHUMANCE_JETON_CALCUL sont obligatoires (fichier .env à côté de encodeur.yml).")
    if not video.outils():
        sys.exit("ffmpeg est absent de l'image.")
    fils = os.environ.get("THREADS", "auto")
    e = Encodeur(url, jeton, os.environ.get("MACHINE", ""), Path(os.environ.get("TRAVAIL", "/travail")),
                 "0" if fils == "auto" else fils)
    veille = int(os.environ.get("VEILLE_S", "60"))
    log.info("Encodeur prêt : %s", url)
    while True:
        try:
            if e.tour():
                continue
        except httpx.HTTPStatusError as exc:
            log.warning("Transhumance a répondu %s : %s", exc.response.status_code, exc.response.text[:200])
        except httpx.HTTPError as exc:
            log.warning("Transhumance injoignable (%s) : nouvel essai dans %s s", exc.__class__.__name__, veille)
        time.sleep(veille)


if __name__ == "__main__":
    main()
