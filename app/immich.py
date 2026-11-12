"""Ce que Transhumance demande à Immich (API de la 3.4). Tout passe par ici.

Chaque écriture commence par `self._garde()` : en lecture seule, rien ne part."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx


class ErreurImmich(Exception):
    pass


class LectureSeule(ErreurImmich):
    def __init__(self):
        super().__init__("Mode lecture seule : rien n'est écrit dans Immich.")


def empreinte(chemin: Path) -> str:
    """SHA-1 du fichier, écrit comme Immich l'écrit (base64)."""
    h = hashlib.sha1()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return base64.b64encode(h.digest()).decode()


def _iso(horodatage: float) -> str:
    return datetime.fromtimestamp(horodatage, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Immich:
    def __init__(self, url: str, cle: str, lecture_seule: bool = False, transport: httpx.BaseTransport | None = None):
        self.lecture_seule = lecture_seule
        self.client = httpx.Client(base_url=url + "/api", headers={"x-api-key": cle, "Accept": "application/json"},
                                   timeout=httpx.Timeout(600, connect=10), transport=transport)

    def fermer(self) -> None:
        self.client.close()

    def _garde(self) -> None:
        if self.lecture_seule:
            raise LectureSeule()

    def _appel(self, methode: str, chemin: str, quoi: str, **kw):
        try:
            r = self.client.request(methode, chemin, **kw)
        except httpx.HTTPError as exc:
            raise ErreurImmich(f"Immich injoignable pendant {quoi} ({exc.__class__.__name__}).") from exc
        if r.status_code >= 400:
            raise ErreurImmich(f"Immich a refusé {quoi} ({r.status_code}).")
        return r.json() if r.content else None

    # ------------------------------------------------------------ lecture
    def version(self) -> str:
        v = self._appel("GET", "/server/version", "la lecture de la version")
        return f"{v['major']}.{v['minor']}.{v['patch']}"

    def place_libre(self) -> int:
        return int(self._appel("GET", "/server/storage", "la lecture de la place")["diskAvailableRaw"])

    def bibliotheques(self) -> list[dict]:
        return self._appel("GET", "/libraries", "la lecture des bibliothèques")

    def photos_externes(self, bibliotheque: str):
        """Toutes les photos d'une bibliothèque externe, page par page (visibles, archivées, masquées)."""
        page = 1
        while page:
            r = self._appel("POST", "/search/metadata", "la lecture des photos",
                            json={"libraryId": bibliotheque, "size": 1000, "page": page, "withExif": True})
            yield from r["assets"]["items"]
            suite = r["assets"].get("nextPage")
            page = int(suite) if suite else 0

    def photo(self, ident: str) -> dict | None:
        try:
            r = self.client.get(f"/assets/{ident}")
        except httpx.HTTPError as exc:
            raise ErreurImmich(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code in (400, 404):
            return None
        if r.status_code >= 400:
            raise ErreurImmich(f"Immich a refusé la lecture d'une photo ({r.status_code}).")
        return r.json()

    def visages(self, ident: str) -> list[dict]:
        return self._appel("GET", "/faces", "la lecture des visages", params={"id": ident})

    def albums(self) -> list[dict]:
        return self._appel("GET", "/albums", "la lecture des albums")

    def albums_de(self, ident: str) -> list[dict]:
        return self._appel("GET", "/albums", "la lecture des albums d'une photo", params={"assetId": ident})

    def reglages_reconnaissance(self) -> dict | None:
        """Réglages « machine learning » d'Immich (adresses essayées dans l'ordre). None si la clé n'a pas le droit de les lire."""
        try:
            r = self.client.get("/system-config")
        except httpx.HTTPError as exc:
            raise ErreurImmich(f"Immich injoignable pendant la lecture de ses réglages ({exc.__class__.__name__}).") from exc
        if r.status_code in (401, 403):
            return None
        if r.status_code >= 400:
            raise ErreurImmich(f"Immich a refusé la lecture de ses réglages ({r.status_code}).")
        return (r.json() or {}).get("machineLearning") or {}

    def files(self) -> dict[str, dict]:
        """Ce qui attend et ce qui tourne, file par file."""
        sortie = {}
        for q in self._appel("GET", "/queues", "la lecture des files"):
            s_ = q.get("statistics") or {}
            sortie[q.get("name")] = {"attente": int(s_.get("waiting", 0)) + int(s_.get("delayed", 0)), "en_cours": int(s_.get("active", 0))}
        return sortie

    def files_occupees(self, noms: tuple[str, ...]) -> int:
        """Nombre de tâches en attente ou en cours dans les files qui comptent pour une photo neuve."""
        total = 0
        for q in self._appel("GET", "/queues", "la lecture des files"):
            if q.get("name") in noms:
                s = q.get("statistics") or {}
                total += int(s.get("waiting", 0)) + int(s.get("active", 0)) + int(s.get("delayed", 0))
        return total

    # ------------------------------------------------------------ écriture
    def envoyer(self, fichier: Path, accompagnement: Path | None = None, video_animee: str | None = None,
                visibilite: str | None = None) -> tuple[str, bool]:
        """Envoie le fichier d'origine. Renvoie (identifiant, déjà_là)."""
        self._garde()
        etat = fichier.stat()
        champs = {"fileCreatedAt": _iso(etat.st_mtime), "fileModifiedAt": _iso(etat.st_mtime)}
        if video_animee:
            champs["livePhotoVideoId"] = video_animee
        if visibilite and visibilite != "timeline":
            champs["visibility"] = visibilite
        with fichier.open("rb") as f:
            pieces = {"assetData": (fichier.name, f, "application/octet-stream")}
            suite = None
            if accompagnement is not None:
                suite = accompagnement.open("rb")
                pieces["sidecarData"] = (accompagnement.name, suite, "application/xml")
            try:
                r = self._appel("POST", "/assets", "l'envoi d'une photo", data=champs, files=pieces,
                                headers={"x-immich-checksum": hashlib.sha1(fichier.read_bytes()).hexdigest()}
                                if etat.st_size < 64 * 1024 * 1024 else None)
            finally:
                if suite:
                    suite.close()
        return r["id"], r.get("status") == "duplicate"

    def reporter(self, ancienne: str, nouvelle: str) -> None:
        """Albums, favori, pile et liens partagés de l'ancienne photo vers la nouvelle."""
        self._garde()
        self._appel("PUT", "/assets/copy", "le report des albums",
                    json={"sourceId": ancienne, "targetId": nouvelle, "albums": True, "favorite": True,
                          "stack": True, "sharedLinks": True, "sidecar": False})

    def corriger(self, ident: str, champs: dict) -> None:
        self._garde()
        self._appel("PUT", f"/assets/{ident}", "la correction d'une photo", json=champs)

    def album(self, nom: str) -> str:
        """L'album de ce nom (le premier trouvé), créé s'il n'existe pas."""
        for a in self.albums():
            if a.get("albumName") == nom:
                return a["id"]
        self._garde()
        return self._appel("POST", "/albums", "la création d'un album", json={"albumName": nom})["id"]

    def ajouter_album(self, album: str, ids: list[str]) -> None:
        self._garde()
        self._appel("PUT", f"/albums/{album}/assets", "l'ajout à l'album", json={"ids": ids})

    def etiqueter(self, tag: str, ids: list[str]) -> None:
        self._garde()
        self._appel("PUT", f"/tags/{tag}/assets", "le report d'un tag", json={"ids": ids})

    def reaffecter_visage(self, visage: str, personne: str) -> None:
        self._garde()
        self._appel("PUT", f"/faces/{visage}", "le rattachement d'un visage", json={"id": personne})

    def creer_visage(self, photo: str, personne: str, v: dict) -> None:
        self._garde()
        x1, y1, x2, y2 = v["boundingBoxX1"], v["boundingBoxY1"], v["boundingBoxX2"], v["boundingBoxY2"]
        self._appel("POST", "/faces", "la création d'un visage",
                    json={"assetId": photo, "personId": personne, "imageWidth": v["imageWidth"], "imageHeight": v["imageHeight"],
                          "x": min(x1, x2), "y": min(y1, y2), "width": abs(x2 - x1), "height": abs(y2 - y1)})

    def retirer(self, ids: list[str]) -> None:
        """Retire définitivement des photos d'Immich (sans passer par sa corbeille)."""
        self._garde()
        for i in range(0, len(ids), 500):
            self._appel("DELETE", "/assets", "le retrait de photos", json={"ids": ids[i:i + 500], "force": True})
