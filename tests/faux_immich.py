"""Faux Immich pour les tests : une bibliothèque externe sur un dossier, un stockage, des visages,
des albums, des files. Il se comporte comme le dossier suppose qu'Immich se comporte — l'essai sur le
vrai Immich reste nécessaire.

Reconnaissance simulée : à l'envoi, la copie reçoit les visages détectables de l'ancienne photo de
même empreinte ; ils sont rattachés seuls à la même personne, sauf ceux marqués « timide » (détectés
mais non rattachés) et « manuel » (non détectés du tout)."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx

CLE = "cle-essai"
RACINE = "/externe"


class FauxImmich:
    def __init__(self, dossier: Path):
        self.dossier = dossier
        self.photos: dict[str, dict] = {}      # id → photo
        self.visages: dict[str, list[dict]] = {}
        self.albums: dict[str, dict] = {}
        self.tags: dict[str, set] = {}
        self.ecrits: list[tuple[str, str]] = []
        self.files_restantes = 0
        self.libre = 10 ** 12
        self.n = 0
        self.abimer: set[str] = set()
        self.personnes_refusees: set[str] = set()   # personnes dont Immich refuse le rattachement
        self.reconnaissance: dict | None = {"enabled": True, "urls": ["http://pc-invente:3003", "http://immich-machine-learning:3003"]}          # noms de fichiers dont la copie sera abîmée au rangement

    def _id(self, prefixe: str) -> str:
        self.n += 1
        return f"{prefixe}-{self.n:04d}"

    def externe(self, rel: str, date: str = "2020-05-01T10:00:00.000Z", **plus) -> str:
        """Déclare un fichier du dossier comme photo de la bibliothèque externe."""
        ident = self._id("ext")
        contenu = (self.dossier / rel).read_bytes()
        self.photos[ident] = {"id": ident, "libraryId": "lib-1", "originalPath": f"{RACINE}/{rel}", "originalFileName": Path(rel).name,
                              "type": "VIDEO" if rel.lower().endswith((".mov", ".mp4")) else "IMAGE",
                              "checksum": base64.b64encode(hashlib.sha1(b"chemin:" + rel.encode()).digest()).decode(),
                              "fileCreatedAt": date, "isFavorite": False, "visibility": "timeline", "livePhotoVideoId": None,
                              "isTrashed": False, "tags": [],
                              "exifInfo": {"dateTimeOriginal": date, "fileSizeInByte": len(contenu), "description": "", "rating": None,
                                           "latitude": None, "longitude": None, "timeZone": "Europe/Paris"}, **plus}
        self.visages[ident] = []
        return ident

    def visage(self, photo: str, personne: str | None, x: int = 100, sorte: str = "normal", nom: str = "Personne inventée") -> None:
        self.visages[photo].append({"id": self._id("vis"), "person": {"id": personne, "name": nom} if personne else None,
                                    "boundingBoxX1": x, "boundingBoxY1": 100, "boundingBoxX2": x + 200, "boundingBoxY2": 300,
                                    "imageWidth": 1000, "imageHeight": 1000, "sourceType": "manual" if sorte == "manuel" else "machine-learning",
                                    "_sorte": sorte})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def _json(self, r: httpx.Request) -> dict:
        return json.loads(r.content) if r.content else {}

    def __call__(self, r: httpx.Request) -> httpx.Response:
        chemin, m = r.url.path.removeprefix("/api"), r.method
        if r.headers.get("x-api-key") != CLE:
            return httpx.Response(401)
        if m != "GET" and chemin != "/search/metadata":
            self.ecrits.append((m, chemin))
        if chemin == "/server/version":
            return httpx.Response(200, json={"major": 3, "minor": 4, "patch": 1})
        if chemin == "/server/storage":
            return httpx.Response(200, json={"diskAvailableRaw": self.libre})
        if chemin == "/libraries":
            return httpx.Response(200, json=[{"id": "lib-1", "name": "Externe", "importPaths": [RACINE]}])
        if chemin == "/system-config":
            return httpx.Response(200, json={"machineLearning": self.reconnaissance}) if self.reconnaissance is not None else httpx.Response(403)
        if chemin == "/queues":
            reste, self.files_restantes = self.files_restantes, max(0, self.files_restantes - 1)
            return httpx.Response(200, json=[{"name": "faceDetection", "statistics": {"waiting": reste, "active": 0}},
                                             {"name": "ocr", "statistics": {"waiting": 99, "active": 1}}])
        if chemin == "/search/metadata":
            corps = self._json(r)
            tous = [p for p in self.photos.values() if p.get("libraryId") == corps.get("libraryId")]
            page, taille = corps.get("page", 1), 2          # pages de 2 : la pagination est exercée
            morceau = tous[(page - 1) * taille: page * taille]
            return httpx.Response(200, json={"assets": {"items": morceau, "nextPage": str(page + 1) if page * taille < len(tous) else None}})
        if chemin == "/faces" and m == "GET":
            return httpx.Response(200, json=[{k: v for k, v in f.items() if not k.startswith("_")} for f in self.visages.get(r.url.params["id"], [])])
        if chemin == "/faces" and m == "POST":
            c = self._json(r)
            self.visages[c["assetId"]].append({"id": self._id("vis"), "person": {"id": c["personId"], "name": ""},
                                               "boundingBoxX1": c["x"], "boundingBoxY1": c["y"], "boundingBoxX2": c["x"] + c["width"],
                                               "boundingBoxY2": c["y"] + c["height"], "imageWidth": c["imageWidth"], "imageHeight": c["imageHeight"],
                                               "sourceType": "manual"})
            return httpx.Response(201, json={})
        if (mm := re.fullmatch(r"/faces/([^/]+)", chemin)) and m == "PUT":
            # Comme le vrai Immich : l'adresse porte la personne, le corps porte le visage
            personne, visage = mm.group(1), self._json(r)["id"]
            connues = {f["person"]["id"] for liste in self.visages.values() for f in liste if f.get("person")}
            cibles = [f for liste in self.visages.values() for f in liste if f["id"] == visage]
            if personne not in connues or not cibles or personne in self.personnes_refusees:
                return httpx.Response(400, json={"message": "Bad Request"})
            for f in cibles:
                f["person"] = {"id": personne, "name": ""}
            return httpx.Response(200, json={})
        if chemin == "/assets" and m == "POST":
            return self._envoi(r)
        if chemin == "/assets" and m == "DELETE":
            for ident in self._json(r)["ids"]:
                self.photos.pop(ident, None)
                self.visages.pop(ident, None)
                for a in self.albums.values():
                    a["ids"].discard(ident)
            return httpx.Response(204)
        if chemin == "/assets/copy":
            c = self._json(r)
            for a in self.albums.values():
                if c["sourceId"] in a["ids"]:
                    a["ids"].add(c["targetId"])
            self.photos[c["targetId"]]["isFavorite"] = self.photos[c["sourceId"]]["isFavorite"]
            return httpx.Response(204)
        if (mm := re.fullmatch(r"/assets/([^/]+)", chemin)):
            p = self.photos.get(mm.group(1))
            if p is None:
                return httpx.Response(404)
            if m == "PUT":
                c = self._json(r)
                for k in ("dateTimeOriginal", "description", "rating", "latitude", "longitude"):
                    if k in c:
                        p["exifInfo"][k] = c[k]
                return httpx.Response(200, json=p)
            return httpx.Response(200, json=p)
        if chemin == "/albums" and m == "GET":
            ident = r.url.params.get("assetId")
            return httpx.Response(200, json=[{"id": k, "albumName": a["nom"]} for k, a in self.albums.items() if not ident or ident in a["ids"]])
        if chemin == "/albums" and m == "POST":
            ident = self._id("alb")
            self.albums[ident] = {"nom": self._json(r)["albumName"], "ids": set()}
            return httpx.Response(201, json={"id": ident})
        if (mm := re.fullmatch(r"/albums/([^/]+)/assets", chemin)):
            self.albums[mm.group(1)]["ids"].update(self._json(r)["ids"])
            return httpx.Response(200, json=[])
        if (mm := re.fullmatch(r"/tags/([^/]+)/assets", chemin)):
            self.tags.setdefault(mm.group(1), set()).update(self._json(r)["ids"])
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    def _envoi(self, r: httpx.Request) -> httpx.Response:
        corps = r.content
        nom = re.search(rb'name="assetData"; filename="([^"]+)"', corps).group(1).decode()
        contenu = corps.split(b'name="assetData"', 1)[1].split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0]
        champ = lambda k: (m.group(1).decode() if (m := re.search(rb'name="' + k.encode() + rb'"\r\n\r\n([^\r]*)', corps)) else None)  # noqa: E731
        somme = base64.b64encode(hashlib.sha1(contenu).digest()).decode()
        for p in self.photos.values():
            if not p.get("libraryId") and p["checksum"] == somme:
                return httpx.Response(200, json={"id": p["id"], "status": "duplicate"})
        ident = self._id("neuf")
        if nom in self.abimer:
            somme = base64.b64encode(hashlib.sha1(contenu + b"x").digest()).decode()
        self.photos[ident] = {"id": ident, "libraryId": None, "originalPath": f"/data/library/{nom}", "originalFileName": nom,
                              "type": "VIDEO" if nom.lower().endswith((".mov", ".mp4")) else "IMAGE", "checksum": somme,
                              "fileCreatedAt": champ("fileCreatedAt"), "isFavorite": False, "visibility": champ("visibility") or "timeline",
                              "livePhotoVideoId": champ("livePhotoVideoId"), "isTrashed": False, "tags": [],
                              "exifInfo": {"dateTimeOriginal": "2020-05-01T10:00:00.000Z", "fileSizeInByte": len(contenu), "description": "",
                                           "rating": None, "latitude": None, "longitude": None}}
        # Reconnaissance : mêmes visages que l'ancienne photo au même contenu
        self.visages[ident] = []
        for ancien, p in list(self.photos.items()):
            if p.get("libraryId") and (self.dossier / p["originalPath"].removeprefix(RACINE + "/")).is_file() \
                    and (self.dossier / p["originalPath"].removeprefix(RACINE + "/")).read_bytes() == contenu:
                for f in self.visages.get(ancien, []):
                    if f.get("_sorte") == "manuel":
                        continue
                    self.visages[ident].append({**{k: v for k, v in f.items() if not k.startswith("_")}, "id": self._id("vis"),
                                                "person": None if f.get("_sorte") == "timide" else f["person"]})
                break
        self.files_restantes = 2
        return httpx.Response(201, json={"id": ident, "status": "created"})
