"""Le passage d'une photo de la bibliothèque externe au stockage d'Immich, et tout ce qui l'entoure.

Ordre voulu (dossier, § 2) : lire l'ancienne → envoyer → contrôler la copie → reporter → visages →
bilan. L'ancienne photo et son fichier ne sont retirés que par `supprimer`, sur un clic, et
seulement pour les photos prouvées copiées. Un fichier qu'Immich ne connaît pas n'est jamais touché."""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from pathlib import Path, PurePosixPath

from .base import Base, maintenant
from .config import Config
from .immich import ErreurImmich, Immich, empreinte

log = logging.getLogger("transhumance")
FILES = ("metadataExtraction", "sidecar", "thumbnailGeneration", "faceDetection", "facialRecognition",
         "storageTemplateMigration")
DATE_SEULE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IGNORES = ("@eaDir", "#recycle", "#snapshot", ".stversions", ".stfolder")
ACCOMPAGNEMENTS = (".xmp",)
# Écarts : ce qu'on perd, dit en clair. « bloquant » : jamais acceptable, la photo n'est pas supprimée.
ECARTS = {
    "empreinte": ("La copie rangée par Immich n'est pas identique au fichier d'origine.", True),
    "introuvable": ("Le fichier d'origine n'est plus dans le dossier.", True),
    "copie_absente": ("Immich n'a plus la copie.", True),
    "date": ("La date de la copie n'est pas celle de l'ancienne photo.", False),
    "visage": ("Des personnes nommées sur l'ancienne photo ne le sont pas sur la copie.", False),
    "album": ("La copie n'est pas dans tous les albums de l'ancienne photo.", False),
}


class Refus(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


class Transhumance:
    def __init__(self, cfg: Config, base: Base, transport=None):
        self.cfg, self.base, self._transport = cfg, base, transport
        self.tache: dict = {"en_cours": False, "message": "", "fait": 0, "total": 0, "erreur": None}

    def immich(self) -> Immich:
        return Immich(self.cfg.immich_url, self.cfg.immich_cle, self.cfg.lecture_seule, self._transport)

    def exiger_ecriture(self) -> None:
        if self.cfg.lecture_seule:
            raise Refus("Mode lecture seule : Transhumance n'envoie rien et ne supprime rien.", 409)

    # ================================================================ inventaire
    def _rel(self, chemin_immich: str) -> str | None:
        racine = self.cfg.racine_immich + "/"
        return chemin_immich[len(racine):] if chemin_immich.startswith(racine) else None

    def inventaire(self) -> dict:
        """Relit la bibliothèque externe et le dossier des photos. N'écrit rien ailleurs que chez soi."""
        im = self.immich()
        try:
            biblio = next((b for b in im.bibliotheques()
                           if any(p.rstrip("/") == self.cfg.racine_immich for p in b.get("importPaths", []))), None)
            if biblio is None:
                raise Refus("Aucune bibliothèque externe d'Immich ne pointe sur le dossier indiqué (TRANSHUMANCE_RACINE_IMMICH).")
            connues = {l["ancien_id"] for l in self.base.tous("SELECT ancien_id FROM photos")}
            vues, neuves = set(), []
            animees = {}
            for a in im.photos_externes(biblio["id"]):
                rel = self._rel(a.get("originalPath", ""))
                if rel is None:
                    continue
                vues.add(a["id"])
                if a.get("livePhotoVideoId"):
                    animees[a["livePhotoVideoId"]] = a["id"]
                if a["id"] not in connues:
                    taille = int((a.get("exifInfo") or {}).get("fileSizeInByte") or 0)
                    neuves.append((a["id"], rel, str(PurePosixPath(rel).parent), a.get("type", "IMAGE"), taille,
                                   int(a.get("visibility") == "hidden"), maintenant()))
            self.base.plusieurs("INSERT OR IGNORE INTO photos(ancien_id, rel, dossier, type, taille, cachee, le) VALUES (?,?,?,?,?,?,?)", neuves)
            for video in animees:
                self.base.executer("UPDATE photos SET cachee = 1 WHERE ancien_id = ?", (video,))
            self.base.ecrire("bibliotheque", biblio["id"])
        finally:
            im.fermer()
        # L'inventaire d'Immich est acquis dès ici : le parcours du dossier, plus long, vient après
        self.base.ecrire("inventaire", {"le": maintenant(), "photos": len(vues), "nouvelles": len(neuves), "inconnus": None})
        # Fichiers du dossier qu'Immich ne connaît pas : comptés par dossier, jamais touchés.
        # 0.1.1 : parcours tolérant (un dossier illisible est sauté) et qui n'entre pas dans les
        # dossiers techniques du NAS (@eaDir contient plusieurs vignettes par photo).
        connus = {l["rel"] for l in self.base.tous("SELECT rel FROM photos")}
        inconnus: dict[str, int] = {}
        liste: list[tuple[str, str]] = []
        racine = str(self.cfg.photos)
        for dossier, sous, fichiers in os.walk(racine, onerror=lambda e: log.warning("Dossier illisible, sauté : %s", e.filename)):
            sous[:] = [d for d in sous if d not in IGNORES and not d.startswith(".")]
            rel_dossier = os.path.relpath(dossier, racine).replace(os.sep, "/")
            for nom in fichiers:
                if nom.startswith(".") or nom.lower().endswith(ACCOMPAGNEMENTS) or nom in ("Thumbs.db", "desktop.ini"):
                    continue
                rel = nom if rel_dossier == "." else f"{rel_dossier}/{nom}"
                if rel not in connus:
                    inconnus[rel_dossier] = inconnus.get(rel_dossier, 0) + 1
                    liste.append((rel, rel_dossier))
        self.base.executer("DELETE FROM inconnus")
        self.base.plusieurs("INSERT OR IGNORE INTO inconnus(rel, dossier) VALUES (?,?)", liste)
        self.base.executer("UPDATE dossiers SET inconnus = 0")
        for d, n in inconnus.items():
            self.base.executer("INSERT INTO dossiers(chemin, inconnus) VALUES (?,?) ON CONFLICT(chemin) DO UPDATE SET inconnus = excluded.inconnus", (d, n))
        self.base.ecrire("inventaire", {"le": maintenant(), "photos": len(vues), "nouvelles": len(neuves),
                                        "inconnus": sum(inconnus.values())})
        self.base.noter("Inventaire relu", {"photos": len(vues), "nouvelles": len(neuves)})
        return self.base.lire("inventaire")

    # ================================================================ arbre et albums
    def album_propose(self, dossier: str) -> str | None:
        """Pellicule/année/évènement → « évènement » (rien si le dossier n'est qu'une date) ;
        Albums/a/b → « a – b » ; autre dossier de premier niveau → son nom en tête."""
        parties = PurePosixPath(dossier).parts
        if not parties or parties == (".",):
            return None
        if parties[0] == self.cfg.pellicule:
            reste = parties[2:]
            if not reste or DATE_SEULE.match(reste[0]) and len(reste) == 1:
                return None
            return " – ".join(reste)
        if parties[0] == self.cfg.albums:
            return " – ".join(parties[1:]) or None
        return " – ".join(parties)

    def album_de(self, dossier: str) -> str | None:
        l = self.base.un("SELECT album FROM dossiers WHERE chemin = ?", (dossier,))
        if l is not None and l["album"] is not None:
            return l["album"] or None            # chaîne vide : « pas d'album », choisi à l'écran
        return self.album_propose(dossier)

    def regler_dossier(self, chemin: str, album: str | None = None, coche: bool | None = None, defaut: bool = False, vider: bool = False) -> None:
        self.base.executer("INSERT OR IGNORE INTO dossiers(chemin) VALUES (?)", (chemin,))
        if defaut:
            self.base.executer("UPDATE dossiers SET album = NULL WHERE chemin = ?", (chemin,))
        elif album is not None:
            self.base.executer("UPDATE dossiers SET album = ? WHERE chemin = ?", (" ".join(album.split())[:120], chemin))
        if coche is not None:
            self._cocher(chemin, bool(coche), vider)

    def _cocher(self, chemin: str, coche: bool, vider: bool = False) -> None:
        """Cocher un dossier coche tout ce qu'il contient (sauf les dossiers exclus).
        0.1.3 : si une partie seulement était cochée, on s'en souvient — décocher le dossier
        rend alors ce choix au lieu de tout décocher. « vider » décoche tout, sans souvenir."""
        dessous = [d for d in self._descendance(chemin) if not self._exclu(d)]
        avant = {l["chemin"] for l in self.base.tous("SELECT chemin FROM dossiers WHERE coche = 1")} & set(dessous)
        cle = "souvenir:" + chemin
        souvenir = [d for d in (self.base.lire(cle) or []) if d in dessous]
        # Un clic ailleurs dans la même branche périme les souvenirs des dossiers au-dessus et en dessous
        for l in self.base.tous("SELECT cle FROM reglages WHERE cle LIKE 'souvenir:%'"):
            autre = l["cle"][len("souvenir:"):]
            if autre != chemin and (autre in (".", "") or chemin in (".", "") or autre.startswith(chemin + "/") or chemin.startswith(autre + "/")):
                self.base.executer("DELETE FROM reglages WHERE cle = ?", (l["cle"],))
        if coche:
            choisis = set(dessous)
            if avant and len(avant) < len(dessous):
                self.base.ecrire(cle, sorted(avant))
        else:
            rendre = not vider and souvenir and len(avant) == len(dessous)
            choisis = set(souvenir) if rendre else set()
            self.base.executer("DELETE FROM reglages WHERE cle = ?", (cle,))
        for d in dessous:
            self.base.executer("INSERT INTO dossiers(chemin, coche) VALUES (?,?) ON CONFLICT(chemin) DO UPDATE SET coche = excluded.coche", (d, int(d in choisis)))

    def _exclu(self, dossier: str) -> bool:
        return PurePosixPath(dossier).parts[:1] in [(x,) for x in self.cfg.exclus]

    def _descendance(self, chemin: str) -> list[str]:
        tous = {l["dossier"] for l in self.base.tous("SELECT DISTINCT dossier FROM photos")}
        if chemin in (".", ""):
            return sorted(tous)
        return sorted(d for d in tous if d == chemin or d.startswith(chemin + "/")) or [chemin]

    def arbre(self) -> dict:
        """L'arborescence : un nœud par dossier, avec ses comptes (les siens et ceux de ses enfants)."""
        reglages = {l["chemin"]: l for l in self.base.tous("SELECT * FROM dossiers")}
        noeuds: dict[str, dict] = {}

        def noeud(chemin: str) -> dict:
            if chemin not in noeuds:
                r = reglages.get(chemin)
                noeuds[chemin] = {"chemin": chemin, "nom": PurePosixPath(chemin).name or "Photos", "enfants": [],
                                  "photos": 0, "videos": 0, "poids": 0, "etats": {}, "ici": 0,
                                  "inconnus": r["inconnus"] if r else 0, "coche": bool(r and r["coche"]),
                                  "exclu": self._exclu(chemin), "propose": self.album_propose(chemin),
                                  "album": self.album_de(chemin)}
                if chemin not in (".", ""):
                    parent = str(PurePosixPath(chemin).parent)
                    noeud(parent)["enfants"].append(chemin)
            return noeuds[chemin]

        for l in self.base.tous("SELECT dossier, type, etat, COUNT(*) n, SUM(taille) poids FROM photos WHERE cachee = 0 "
                                "GROUP BY dossier, type, etat"):
            n = noeud(l["dossier"])
            n["ici"] += l["n"]
            c = l["dossier"]
            while True:                                  # les comptes remontent jusqu'à la racine
                p = noeud(c)
                p["videos" if l["type"] == "VIDEO" else "photos"] += l["n"]
                p["poids"] += l["poids"] or 0
                p["etats"][l["etat"]] = p["etats"].get(l["etat"], 0) + l["n"]
                if c in (".", ""):
                    break
                c = str(PurePosixPath(c).parent)
        # Fichiers inconnus d'Immich : le nombre de chaque dossier remonte à ses parents, une seule fois
        for n in noeuds.values():
            n["inconnus"] = 0
        for chemin, r in reglages.items():
            if not r["inconnus"]:
                continue
            c = chemin
            while True:
                if c in noeuds:
                    noeuds[c]["inconnus"] += r["inconnus"]
                if c in (".", ""):
                    break
                c = str(PurePosixPath(c).parent)
        # 0.1.2 : la case d'un dossier dit ce qui est coché en dessous — tout, une partie, ou rien
        for n in noeuds.values():
            n["a_cocher"], n["coches"] = 0, 0
        for chemin, n in noeuds.items():
            if not n["ici"] or n["exclu"]:
                continue
            c = chemin
            while True:
                noeuds[c]["a_cocher"] += 1
                noeuds[c]["coches"] += int(n["coche"])
                if c in (".", ""):
                    break
                c = str(PurePosixPath(c).parent)
        for n in noeuds.values():
            n["selection"] = "rien" if not n["coches"] else "tout" if n["coches"] == n["a_cocher"] else "partiel"
        for l in self.base.tous("SELECT cle, valeur FROM reglages WHERE cle LIKE 'souvenir:%'"):
            n = noeuds.get(l["cle"][len("souvenir:"):])
            if n and n["selection"] == "tout":
                n["souvenir"] = len(json.loads(l["valeur"]))       # décocher rendra ce choix
        for n in noeuds.values():
            n["enfants"].sort(key=str.casefold)
        return {"racine": ".", "noeuds": noeuds, "inventaire": self.base.lire("inventaire"),
                "tache": self.tache, "lecture_seule": self.cfg.lecture_seule, "immich_adresse": self.cfg.immich_adresse}

    # ================================================================ le passage
    def _fichier(self, rel: str) -> Path:
        chemin = (self.cfg.photos / rel).resolve()
        if self.cfg.photos.resolve() not in chemin.parents:
            raise Refus("Chemin hors du dossier des photos.")
        return chemin

    @staticmethod
    def _accompagnement(fichier: Path) -> Path | None:
        for candidat in (fichier.with_name(fichier.name + ".xmp"), fichier.with_suffix(".xmp")):
            if candidat.is_file():
                return candidat
        return None

    def _instantane(self, im: Immich, ancien: str) -> dict:
        """Tout ce que l'ancienne photo portait : c'est ce qu'on ne retrouverait dans aucune sauvegarde de fichiers."""
        a = im.photo(ancien) or {}
        exif = a.get("exifInfo") or {}
        return {
            "id": ancien, "chemin": a.get("originalPath"), "type": a.get("type"), "empreinte": a.get("checksum"),
            "date": exif.get("dateTimeOriginal") or a.get("fileCreatedAt"), "fuseau": exif.get("timeZone"),
            "latitude": exif.get("latitude"), "longitude": exif.get("longitude"),
            "description": exif.get("description") or "", "note": exif.get("rating"),
            "favori": bool(a.get("isFavorite")), "visibilite": a.get("visibility"),
            "animee": a.get("livePhotoVideoId"), "duree": a.get("duration"),
            "tags": [{"id": t["id"], "nom": t.get("value") or t.get("name")} for t in a.get("tags") or []],
            "albums": [{"id": x["id"], "nom": x.get("albumName")} for x in im.albums_de(ancien)],
            "visages": [{"personne": (v.get("person") or {}).get("id"), "nom": (v.get("person") or {}).get("name"),
                         **{k: v.get(k) for k in ("boundingBoxX1", "boundingBoxY1", "boundingBoxX2", "boundingBoxY2",
                                                  "imageWidth", "imageHeight", "sourceType")}}
                        for v in im.visages(ancien)],
        }

    def _envoyer(self, im: Immich, l, album_id: str | None, nouveaux: dict[str, str]) -> None:
        fichier = self._fichier(l["rel"])
        if not fichier.is_file():
            self._etat(l["ancien_id"], "ecart", ecarts=["introuvable"])
            return
        inst = self._instantane(im, l["ancien_id"])
        somme = empreinte(fichier)
        video = nouveaux.get(inst["animee"]) if inst.get("animee") else None
        nouveau, deja = im.envoyer(fichier, self._accompagnement(fichier), video, inst.get("visibilite"))
        nouveaux[l["ancien_id"]] = nouveau
        self.base.executer("UPDATE photos SET etat = 'envoyee', nouveau_id = ?, empreinte = ?, deja_la = ?, instantane = ?, le = ? "
                           "WHERE ancien_id = ?", (nouveau, somme, int(deja), json.dumps(inst, ensure_ascii=False), maintenant(), l["ancien_id"]))
        self.base.noter("Photo envoyée", {"ancien": l["ancien_id"], "nouveau": nouveau, "deja_la": deja})
        if l["cachee"]:
            return                                       # partie vidéo d'une photo animée : rien d'autre à reporter
        im.reporter(l["ancien_id"], nouveau)
        if album_id:
            im.ajouter_album(album_id, [nouveau])
        for t in inst["tags"]:
            im.etiqueter(t["id"], [nouveau])
        corrections = {k: v for k, v in (("description", inst["description"]), ("rating", inst["note"])) if v}
        if corrections:
            im.corriger(nouveau, corrections)

    def _etat(self, ancien: str, etat: str, ecarts: list[str] | None = None) -> None:
        self.base.executer("UPDATE photos SET etat = ?, ecarts = ?, le = ? WHERE ancien_id = ?",
                           (etat, json.dumps(ecarts or []), maintenant(), ancien))

    @staticmethod
    def _cadre(v: dict) -> tuple[float, float, float, float] | None:
        l, h = v.get("imageWidth") or 0, v.get("imageHeight") or 0
        if not l or not h:
            return None
        x1, x2 = sorted((v["boundingBoxX1"] / l, v["boundingBoxX2"] / l))
        y1, y2 = sorted((v["boundingBoxY1"] / h, v["boundingBoxY2"] / h))
        return x1, y1, x2, y2

    @classmethod
    def _recouvrement(cls, a: dict, b: dict) -> float:
        ca, cb = cls._cadre(a), cls._cadre(b)
        if not ca or not cb:
            return 0.0
        ix = max(0.0, min(ca[2], cb[2]) - max(ca[0], cb[0]))
        iy = max(0.0, min(ca[3], cb[3]) - max(ca[1], cb[1]))
        union = (ca[2] - ca[0]) * (ca[3] - ca[1]) + (cb[2] - cb[0]) * (cb[3] - cb[1]) - ix * iy
        return ix * iy / union if union > 0 else 0.0

    def _visages(self, im: Immich, inst: dict, nouveau: str) -> dict:
        """Chaque visage nommé de l'ancienne photo doit l'être sur la copie, à la même personne."""
        issue = {"seul": 0, "reaffecte": 0, "recree": 0, "perdu": 0}
        neufs = im.visages(nouveau)
        pris: set[str] = set()
        for v in inst["visages"]:
            if not v.get("personne"):
                continue
            candidats = sorted(((self._recouvrement(v, n), n) for n in neufs if n["id"] not in pris), key=lambda x: -x[0])
            if candidats and candidats[0][0] >= 0.4:
                n = candidats[0][1]
                pris.add(n["id"])
                if (n.get("person") or {}).get("id") == v["personne"]:
                    issue["seul"] += 1
                else:
                    im.reaffecter_visage(n["id"], v["personne"])
                    issue["reaffecte"] += 1
            else:
                try:
                    im.creer_visage(nouveau, v["personne"], v)
                    issue["recree"] += 1
                except ErreurImmich:
                    issue["perdu"] += 1
        return issue

    def _controler(self, im: Immich, l) -> None:
        """Contrôle de la copie, puis visages. Fixe l'état : prête, ou écart (avec la liste)."""
        inst = json.loads(l["instantane"] or "{}")
        copie = im.photo(l["nouveau_id"])
        if copie is None:
            self._etat(l["ancien_id"], "ecart", ["copie_absente"])
            return
        ecarts = []
        if copie.get("checksum") != l["empreinte"]:
            ecarts.append("empreinte")
        if not l["cachee"]:
            exif = copie.get("exifInfo") or {}
            date = exif.get("dateTimeOriginal") or copie.get("fileCreatedAt")
            if inst.get("date") and (date or "")[:19] != inst["date"][:19]:
                # La date avait été corrigée dans Immich : on la reporte, puis on relit
                champs = {"dateTimeOriginal": inst["date"]}
                if inst.get("latitude") is not None and exif.get("latitude") is None:
                    champs.update(latitude=inst["latitude"], longitude=inst["longitude"])
                im.corriger(l["nouveau_id"], champs)
                relue = (im.photo(l["nouveau_id"]) or {}).get("exifInfo") or {}
                if (relue.get("dateTimeOriginal") or "")[:19] != inst["date"][:19]:
                    ecarts.append("date")
            issue = self._visages(im, inst, l["nouveau_id"])
            inst["issue_visages"] = issue
            if issue["perdu"]:
                ecarts.append("visage")
            else:
                attendues = {v["personne"] for v in inst["visages"] if v.get("personne")}
                presentes = {(v.get("person") or {}).get("id") for v in im.visages(l["nouveau_id"])}
                if not attendues <= presentes:
                    ecarts.append("visage")
            voulus = {a["id"] for a in inst["albums"]}
            if voulus and not voulus <= {a["id"] for a in im.albums_de(l["nouveau_id"])}:
                ecarts.append("album")
            inst["chemin_final"] = copie.get("originalPath")
            self.base.executer("UPDATE photos SET instantane = ? WHERE ancien_id = ?", (json.dumps(inst, ensure_ascii=False), l["ancien_id"]))
        self._etat(l["ancien_id"], "ecart" if ecarts else "prete", ecarts)

    def _attendre_files(self, im: Immich) -> None:
        debut, calme = time.monotonic(), 0
        while time.monotonic() - debut < self.cfg.delai_files:
            calme = calme + 1 if im.files_occupees(FILES) == 0 else 0
            if calme >= 2:                               # deux regards à vide de suite : Immich a fini
                return
            self.tache["message"] = "Immich range les photos et reconnaît les visages…"
            time.sleep(self.cfg.attente_files)
        raise Refus("Immich n'a pas fini son travail dans le délai : relance « Migrer » plus tard, rien n'est perdu.")

    def a_migrer(self) -> list[str]:
        coches = [l["chemin"] for l in self.base.tous("SELECT chemin FROM dossiers WHERE coche = 1 ORDER BY chemin")]
        return [d for d in coches if not self._exclu(d)]

    def verifier_place(self, dossiers: list[str]) -> dict:
        besoin = sum((self.base.un("SELECT COALESCE(SUM(taille),0) s FROM photos WHERE dossier = ? AND etat = 'vue'", (d,))["s"]) for d in dossiers)
        im = self.immich()
        try:
            libre = im.place_libre()
        finally:
            im.fermer()
        return {"besoin": besoin, "libre": libre, "possible": besoin <= libre * self.cfg.marge_place}

    def migrer(self) -> None:
        """Fait passer les dossiers cochés. Rejouable : une photo déjà envoyée n'est pas renvoyée."""
        self.exiger_ecriture()
        dossiers = self.a_migrer()
        if not dossiers:
            raise Refus("Aucun dossier coché.")
        place = self.verifier_place(dossiers)
        if not place["possible"]:
            raise Refus("Pas assez de place libre pour ce lot : coche moins de dossiers, ou supprime d'abord les originaux d'un lot déjà contrôlé.")
        total = sum(self.base.un("SELECT COUNT(*) n FROM photos WHERE dossier = ? AND etat IN ('vue','envoyee')", (d,))["n"] for d in dossiers)
        self.tache.update(en_cours=True, fait=0, total=total, erreur=None, message="Envoi…")
        im = self.immich()
        try:
            albums: dict[str, str] = {}
            for d in dossiers:
                nom = self.album_de(d)
                album_id = albums.setdefault(nom, im.album(nom)) if nom else None
                nouveaux: dict[str, str] = {}
                # Les parties vidéo des photos animées d'abord : la photo s'y rattache à l'envoi
                for l in self.base.tous("SELECT * FROM photos WHERE dossier = ? AND etat = 'vue' ORDER BY cachee DESC, rel", (d,)):
                    self.tache["message"] = f"Envoi de {d}"
                    self._envoyer(im, l, album_id, nouveaux)
                    self.tache["fait"] += 1
            self._attendre_files(im)
            for d in dossiers:
                for l in self.base.tous("SELECT * FROM photos WHERE dossier = ? AND etat = 'envoyee' ORDER BY rel", (d,)):
                    self.tache["message"] = f"Contrôle de {d}"
                    self._controler(im, l)
            self.exporter()
            self.base.noter("Lot passé", {"dossiers": len(dossiers)})
            self.tache["message"] = "Lot passé : lis le bilan."
        except (ErreurImmich, Refus, OSError) as exc:
            self.tache["erreur"] = str(exc)
            log.warning("Lot interrompu : %s", exc)
        finally:
            im.fermer()
            self.tache["en_cours"] = False

    # ================================================================ bilan, suppression, retour arrière
    def _photos_sous(self, chemin: str) -> list:
        if chemin in (".", ""):
            return self.base.tous("SELECT * FROM photos ORDER BY rel")
        return self.base.tous("SELECT * FROM photos WHERE dossier = ? OR dossier LIKE ? ORDER BY rel", (chemin, chemin.replace("%", "") + "/%"))

    def bilan(self, chemin: str) -> dict:
        photos = self._photos_sous(chemin)
        visibles = [l for l in photos if not l["cachee"]]
        etats: dict[str, int] = {}
        visages = {"seul": 0, "reaffecte": 0, "recree": 0, "perdu": 0}
        ecarts, deja = [], 0
        for l in visibles:
            etats[l["etat"]] = etats.get(l["etat"], 0) + 1
            deja += l["deja_la"]
            inst = json.loads(l["instantane"] or "{}")
            for k, v in (inst.get("issue_visages") or {}).items():
                visages[k] += v
            for e in json.loads(l["ecarts"]):
                perdus = sorted({v.get("nom") or "une personne sans nom" for v in inst.get("visages", []) if v.get("personne")}) if e == "visage" else []
                ecarts.append({"ancien": l["ancien_id"], "nouveau": l["nouveau_id"], "fichier": l["rel"], "sorte": e,
                               "phrase": ECARTS[e][0], "bloquant": ECARTS[e][1], "accepte": bool(l["accepte"]), "personnes": perdus})
        inconnus = sum(r["inconnus"] for r in self.base.tous("SELECT chemin, inconnus FROM dossiers")
                       if chemin in (".", "") or r["chemin"] == chemin or r["chemin"].startswith(chemin + "/"))
        en_attente = [l for l in visibles if l["etat"] == "ecart" and (not l["accepte"] or any(ECARTS[e][1] for e in json.loads(l["ecarts"])))]
        pretes = [l for l in visibles if l["etat"] == "prete" or (l["etat"] == "ecart" and l["accepte"] and not any(ECARTS[e][1] for e in json.loads(l["ecarts"])))]
        return {
            "chemin": chemin, "fichiers": len(visibles), "etats": etats, "deja_la": deja, "visages": visages, "ecarts": ecarts,
            "inconnus": inconnus, "a_supprimer": len(pretes),
            "fichiers_inconnus": [l["rel"] for l in (self.base.tous("SELECT rel FROM inconnus ORDER BY rel LIMIT 300") if chemin in (".", "")
                                  else self.base.tous("SELECT rel FROM inconnus WHERE dossier = ? OR dossier LIKE ? ORDER BY rel LIMIT 300",
                                                      (chemin, chemin.replace("%", "") + "/%")))],
            "supprimable": bool(pretes) and not en_attente and not etats.get("vue") and not etats.get("envoyee"),
            "phrase": f"{len(visibles)} fichiers dans ce dossier ; {len(pretes) + etats.get('supprimee', 0)} retrouvés identiques dans Immich ; "
                      f"{len(en_attente)} avec un écart à régler ; {etats.get('vue', 0) + etats.get('envoyee', 0)} pas encore passés ; "
                      f"{inconnus} qu'Immich ne connaît pas (ils resteront dans le dossier).",
            "echantillon": [{"nouveau": l["nouveau_id"], "fichier": l["rel"]} for l in pretes[:: max(1, len(pretes) // 5)][:5]],
        }

    def accepter(self, ancien: str, oui: bool = True) -> None:
        l = self.base.un("SELECT ecarts FROM photos WHERE ancien_id = ?", (ancien,))
        if l is None:
            raise Refus("Photo inconnue.", 404)
        if oui and any(ECARTS[e][1] for e in json.loads(l["ecarts"])):
            raise Refus("Cet écart ne s'accepte pas : la copie n'est pas sûre, l'original reste en place.")
        self.base.executer("UPDATE photos SET accepte = ? WHERE ancien_id = ?", (int(oui), ancien))

    def supprimer(self, chemin: str) -> dict:
        """Le clic qui ne se rattrape pas. Pour chaque photo prête : la copie est relue dans Immich
        (présente, même empreinte), puis le fichier d'origine est supprimé, puis l'ancienne photo est
        retirée d'Immich. Tout le reste — écarts non acceptés, fichiers inconnus d'Immich — reste en place."""
        self.exiger_ecriture()
        if self.tache["en_cours"]:
            raise Refus("Un lot est en cours : attends sa fin.", 409)
        b = self.bilan(chemin)
        if not b["supprimable"]:
            raise Refus("Ce dossier n'est pas prêt : des photos ne sont pas passées, ou un écart n'est pas réglé.", 409)
        im = self.immich()
        faits, retires, gardes = 0, [], 0
        try:
            for l in self._photos_sous(chemin):
                bloquant = any(ECARTS[e][1] for e in json.loads(l["ecarts"]))
                if not (l["etat"] == "prete" or (l["etat"] == "ecart" and l["accepte"] and not bloquant)):
                    continue
                copie = im.photo(l["nouveau_id"]) if l["nouveau_id"] else None
                fichier = self._fichier(l["rel"])
                # Dernière preuve, au moment de supprimer : la copie existe et le fichier n'a pas changé depuis l'envoi
                if copie is None or copie.get("checksum") != l["empreinte"] or copie.get("isTrashed") \
                        or (fichier.is_file() and empreinte(fichier) != l["empreinte"]):
                    self._etat(l["ancien_id"], "ecart", ["copie_absente" if copie is None else "empreinte"])
                    gardes += 1
                    continue
                if fichier.is_file():
                    accompagnement = self._accompagnement(fichier)
                    fichier.unlink()
                    if accompagnement:
                        accompagnement.unlink()
                retires.append(l["ancien_id"])
                self._etat(l["ancien_id"], "supprimee")
                faits += 1
            if retires:
                im.retirer(retires)
        finally:
            im.fermer()
            self.base.noter("Originaux supprimés", {"dossier": chemin, "supprimes": faits, "gardes": gardes})
            self.exporter()
        return {"supprimes": faits, "gardes": gardes, "bilan": self.bilan(chemin)}

    def defaire(self, chemin: str) -> dict:
        """Retour arrière tant que les originaux sont là : les copies sont retirées d'Immich, les photos
        reviennent à « à migrer ». Une copie qu'Immich avait déjà avant nous n'est pas retirée."""
        self.exiger_ecriture()
        if self.tache["en_cours"]:
            raise Refus("Un lot est en cours : attends sa fin.", 409)
        lignes = [l for l in self._photos_sous(chemin) if l["etat"] in ("envoyee", "prete", "ecart")]
        a_retirer = [l["nouveau_id"] for l in lignes if l["nouveau_id"] and not l["deja_la"] and self._fichier(l["rel"]).is_file()]
        im = self.immich()
        try:
            if a_retirer:
                im.retirer(a_retirer)
        finally:
            im.fermer()
        for l in lignes:
            if self._fichier(l["rel"]).is_file():
                self.base.executer("UPDATE photos SET etat = 'vue', nouveau_id = NULL, ecarts = '[]', accepte = 0, deja_la = 0 WHERE ancien_id = ?", (l["ancien_id"],))
        self.base.noter("Dossier défait", {"dossier": chemin, "copies_retirees": len(a_retirer)})
        return {"copies_retirees": len(a_retirer)}

    def exporter(self) -> None:
        """Le seul livrable durable : la correspondance ancien → nouvel identifiant, et ce que portait
        chaque ancienne photo. Écrits dans le dossier de données, à garder après le retrait de l'appli."""
        self.cfg.data.mkdir(parents=True, exist_ok=True)
        lignes = self.base.tous("SELECT * FROM photos WHERE nouveau_id IS NOT NULL ORDER BY rel")
        with (self.cfg.data / "correspondance.csv").open("w", newline="", encoding="utf-8") as f:
            ecrit = csv.writer(f, delimiter=";")
            ecrit.writerow(["ancien_id", "nouveau_id", "chemin_origine", "chemin_final", "empreinte", "etat", "le"])
            for l in lignes:
                inst = json.loads(l["instantane"] or "{}")
                ecrit.writerow([l["ancien_id"], l["nouveau_id"], l["rel"], inst.get("chemin_final") or "", l["empreinte"], l["etat"], l["le"]])
        with (self.cfg.data / "instantanes.jsonl").open("w", encoding="utf-8") as f:
            for l in lignes:
                f.write((l["instantane"] or "{}") + "\n")
