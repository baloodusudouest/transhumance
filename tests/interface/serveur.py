"""Transhumance de démonstration pour les tests d'écran : faux Immich, dossier de photos inventé.

    python -m tests.interface.serveur <dossier> <port>     (mot de passe : « essai-essai »)"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import uvicorn

from app import main, maison
from app.base import Base
from app.config import Config
from app.passage import Transhumance
from tests.faux_immich import CLE, RACINE, FauxImmich


def main_() -> None:
    racine, port = Path(sys.argv[1]), int(sys.argv[2])
    photos = racine / "photos"
    im = FauxImmich(photos)
    arbre = {"Pellicule/2019/2019-08-12 Vendanges": 4, "Pellicule/2019/2019-12-25": 2, "Pellicule/2020/2020-05-01 Fête au jardin": 3,
             "Albums/Voyages/Italie 2019": 3, "Pense bete/Travaux": 2, "Scans/Boîte 1": 2}
    for dossier, n in arbre.items():
        for i in range(n):
            p = photos / dossier / f"IMG_{i:04d}.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"{dossier} {i}".encode() * 400)
            ident = im.externe(p.relative_to(photos).as_posix())
            im.visage(ident, "pers-a", 100, ("normal", "timide", "manuel")[i % 3])
    (photos / "Pellicule/2019/2019-08-12 Vendanges/inconnu.jpg").write_bytes(b"x" * 100)
    cfg = Config(password="essai-essai", immich_url="http://immich", immich_cle=CLE, photos=photos, racine_immich=RACINE,
                 data=racine / "data", static=Path(__file__).resolve().parents[2] / "app" / "static",
                 attente_connexion=False, attente_files=0.2)
    t = Transhumance(cfg, Base(cfg.data / "t.db"), im.transport())
    t.changer_reglages({"exclus": ["Scans"]})                       # 0.7.0 : réglage de l'appli
    main.ETAT.update(cfg=cfg, t=t)
    # 0.7.0 : faux Anneau — l'annuaire (adresse d'Immich) et deux sauvegardes des réglages
    main.ANNUAIRE = maison.Annuaire(jeton="essai", lire=lambda: [{"nom": "Immich", "locale": "http://immich.exemple"}])
    sauvegardes = {"2026-11-15": {"exclus": ["Scans"], "auto_demandes": False},
                   "2026-11-14": {"exclus": ["Scans", "Pense bete"], "auto_demandes": False}}

    def anneau(adresse, jeton):
        if "?le=" not in adresse:
            return {"dates": sorted(sauvegardes, reverse=True)}
        le = adresse.rsplit("?le=", 1)[1]
        return {"le": le, "version": "0.7.0", "reglages": sauvegardes[le]}
    vrai = maison.lire_sauvegarde
    maison.lire_sauvegarde = lambda appli, le="": vrai(appli, le, lire=anneau)
    (racine / "pret").write_text("ok")
    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main_()
