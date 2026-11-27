"""Le passage d'une photo de la bibliothèque externe au stockage d'Immich, et tout ce qui l'entoure.

Ordre voulu (dossier, § 2) : lire l'ancienne → envoyer → contrôler la copie → reporter → visages →
bilan. L'ancienne photo et son fichier ne sont retirés que par `supprimer`, sur un clic, et
seulement pour les photos prouvées copiées. Un fichier qu'Immich ne connaît pas n'est jamais touché."""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import httpx

from . import maison, video
from .base import Base, maintenant
from .config import Config
from .immich import LectureSeule, ErreurImmich, Immich, empreinte

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
    "refuse": ("Immich a refusé ce fichier à l'envoi (fichier abîmé ou format refusé) : il reste dans le dossier, "
               "jamais supprimé, et n'empêche pas de supprimer les autres.", True),
    "copie_absente": ("Immich n'a plus la copie.", True),
    "date": ("La date de la copie n'est pas celle de l'ancienne photo.", False),
    "visage": ("Des personnes nommées sur l'ancienne photo ne le sont pas sur la copie.", False),
    "album": ("La copie n'est pas dans tous les albums de l'ancienne photo.", False),
    "tag": ("Un tag de l'ancienne photo n'a pas pu être reporté sur la copie : Immich le refuse.", False),
    "description": ("La description ou la note de l'ancienne photo n'a pas pu être reportée sur la copie.", False),
    # 0.10.0 : vidéos mises en MP4 (remux ou réencodage) — la copie ne peut plus être identique à l'original
    "pas_video": ("Ce fichier n'a pas d'image (un vrai son, ou un fichier illisible) : il reste dans le dossier, jamais "
                  "touché, et n'empêche pas de supprimer les autres.", True),
    "encodage": ("La vidéo n'a pas pu être mise en MP4 après trois essais : elle reste dans le dossier, jamais supprimée, "
                 "et n'empêche pas de supprimer les autres.", True),
    "duree": ("La vidéo mise en MP4 n'a pas la même durée que l'original (plus d'une seconde d'écart).", True),
    "son": ("La vidéo mise en MP4 a perdu une piste de son.", True),
    "images": ("La vidéo mise en MP4 n'a pas le même nombre d'images que l'original (plus de 1 % d'écart).", True),
    "definition": ("La vidéo mise en MP4 n'a pas la même définition que l'original.", True),
    "illisible": ("La vidéo mise en MP4 ne se lit pas jusqu'au bout, ou Immich n'en a pas fait de vignette.", True),
    "fidelite": ("Des images de la vidéo mise en MP4 ne ressemblent pas assez à l'original.", True),
    "grossi": ("La vidéo réencodée est plus lourde que l'original, même en qualité plus légère.", False),
    # 0.10.1 : constaté le 27/11/2026 — des originaux vidéo retirés à la main étaient comptés « supprimés » sans rien au sas
    "original_absent": ("Au moment de supprimer, le fichier d'origine n'était plus dans le dossier (retiré à la main ?) : "
                        "rien n'a été supprimé ni mis au sas. La copie est dans Immich ; accepter pour clore.", False),
}


# 0.9.6 : écarts d'un fichier qui reste dans le dossier sans bloquer les autres (comme un fichier qu'Immich ne connaît
# pas) : jamais supprimé (bloquant ci-dessus), mais le dossier reste supprimable pour ses photos prêtes.
RESTENT = {"refuse", "pas_video", "encodage"}      # 0.10.0 : + fichier sans image, vidéo qui n'a pas pu être mise en MP4
RESTENT_SQL = "(" + ",".join("'" + json.dumps([e]) + "'" for e in sorted(RESTENT)) + ")"
TRANSFORMEES = ("remux", "encode")                  # 0.10.0 : voies où la copie est un MP4 fabriqué, pas l'original
PC_ABSENT_S = 600                                   # le PC n'a pas fait signe depuis 10 min : le NAS peut encoder
BAIL_S = 600                                        # une vidéo prise sans signe de vie depuis 10 min revient dans la file
ESSAIS = 3


def reste_seulement(l) -> bool:
    """Vrai pour une photo en écart dont tous les écarts la font seulement rester dans le dossier (refusée par Immich)."""
    ecarts = set(json.loads(l["ecarts"] or "[]"))
    return l["etat"] == "ecart" and bool(ecarts) and ecarts <= RESTENT


def _age(iso: str | None) -> float:
    """Secondes écoulées depuis une date ISO (infini si absente ou illisible)."""
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


class Refus(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


# 0.7.0 : réglages d'usage. « exclus » est gardé dans reglages.json (maison.Reglages, repris une fois de la variable
# de la stack) ; « auto_demandes » reste dans la table reglages de la base, où il était depuis la 0.4.0.
REGLAGES_DEFAUTS = {"exclus": []}
REGLAGES_VARIABLES = {"exclus": "TRANSHUMANCE_EXCLUS"}      # lue au premier démarrage seulement, puis plus jamais


class Transhumance:
    def __init__(self, cfg: Config, base: Base, transport=None):
        self.cfg, self.base, self._transport = cfg, base, transport
        self.tache: dict = {"en_cours": False, "message": "", "fait": 0, "total": 0, "erreur": None, "origine": None, "dossiers": 0}
        # 0.9.3 : un seul lot à la fois. Avant, un passage automatique pouvait démarrer pendant « Faire passer » (ou
        # l'inverse) : deux lots tournaient ensemble sur le même compteur. migrer() le prend ou le reçoit, et le rend.
        self.verrou_lot = threading.Lock()
        self.suppression: dict = {"en_cours": False, "dossier": "", "fait": 0, "total": 0, "etape": ""}
        self.reglages = maison.Reglages(cfg.data / "reglages.json", REGLAGES_DEFAUTS, REGLAGES_VARIABLES)
        # 0.10.0 : la file des vidéos ; la puce vidéo du NAS (essayée au démarrage par main, ou posée par les tests)
        self.verrou_file = threading.Lock()
        self.materiel_nas: dict = {"ok": False, "mode": "vaapi", "pilote": None, "raison": "Pas encore essayée."}
        self.encodage_nas: dict | None = None
        for k in self.reglages.repris:                     # la valeur n'est pas écrite : des noms de dossiers
            self.base.noter(f"Réglage repris de la stack : {k}", {"variable": REGLAGES_VARIABLES[k]})

    # ------------------------------------------------------------ 0.7.0 : réglages d'usage (écran Réglages)
    def exclus(self) -> list[str]:
        return list(self.reglages.get("exclus"))

    def reglages_tout(self) -> dict:
        return {"exclus": self.exclus(), "auto_demandes": self.auto_demandes()}

    def changer_reglages(self, valeurs: dict, par: str = "Réglage changé") -> dict:
        """Vérifie toutes les valeurs avant d'en écrire une (ValueError, message clair) ; une ligne au journal par
        réglage changé. Ne touche ni Immich ni le dossier des photos : permis aussi en lecture seule."""
        if not isinstance(valeurs, dict):
            raise ValueError("Réglages attendus sous forme d'objet.")
        inconnues = sorted(set(valeurs) - {"exclus", "auto_demandes"})
        if inconnues:
            raise ValueError("Réglage inconnu : " + ", ".join(inconnues) + ".")
        propres: dict = {}
        if "exclus" in valeurs:
            v = valeurs["exclus"]
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError("exclus : une liste de noms de dossiers est attendue.")
            noms = []
            for x in (" ".join(x.split()) for x in v):
                if not x:
                    continue
                if "/" in x or x in (".", ".."):
                    raise ValueError(f"exclus : « {x} » n'est pas un dossier de premier niveau (un nom, sans /).")
                if x not in noms:
                    noms.append(x)
            propres["exclus"] = noms
        if "auto_demandes" in valeurs:
            if not isinstance(valeurs["auto_demandes"], bool):
                raise ValueError("auto_demandes : oui ou non (true / false) est attendu.")
            propres["auto_demandes"] = valeurs["auto_demandes"]
        avant = self.reglages_tout()
        if "exclus" in propres:
            self.reglages.changer({"exclus": propres["exclus"]})
        if "auto_demandes" in propres:
            self.base.ecrire("auto_demandes", propres["auto_demandes"])
        for k, v in propres.items():
            if avant[k] != v:
                self.base.noter(f"{par} : {k}")
        return self.reglages_tout()

    def immich(self) -> Immich:
        return Immich(self.cfg.immich_url, self.cfg.immich_cle, self.cfg.lecture_seule, self._transport)

    # 0.1.5 : qui fait la reconnaissance (visages, recherche, texte) — le NAS ou le PC ?
    FILES_RECONNAISSANCE = (("faceDetection", "Détection des visages"), ("facialRecognition", "Reconnaissance des personnes"),
                            ("smartSearch", "Recherche intelligente"), ("ocr", "Lecture du texte (OCR)"),
                            ("duplicateDetection", "Détection des doublons"))

    @staticmethod
    def _repond(adresse: str) -> bool:
        """Le service de reconnaissance à cette adresse répond-il ? (Même question que celle d'Immich.)"""
        try:
            return httpx.get(adresse.rstrip("/") + "/ping", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def reconnaissance(self, repond=None) -> dict:
        """Lecture seule. Immich essaie ses adresses dans l'ordre : la première qui répond travaille."""
        repond = repond or self._repond
        im = self.immich()
        try:
            reglages = im.reglages_reconnaissance()
            files = im.files()
        except ErreurImmich as exc:
            return {"lisible": False, "raison": str(exc), "adresses": [], "files": []}
        finally:
            im.fermer()
        lignes = [{"nom": nom, **files[cle]} for cle, nom in self.FILES_RECONNAISSANCE if cle in files]
        if reglages is None:
            return {"lisible": False, "files": lignes, "adresses": [],
                    "raison": "La clé d'API de Transhumance n'a pas le droit de lire les réglages d'Immich (permission « systemConfig.read », clé d'un compte administrateur)."}
        adresses = []
        for u in reglages.get("urls") or ([reglages["url"]] if reglages.get("url") else []):
            hote = (httpx.URL(u).host or "").lower()
            adresses.append({"adresse": u, "nas": "immich" in hote and "machine" in hote, "repond": repond(u)})
        utilisee = next((i for i, a in enumerate(adresses) if a["repond"]), None)
        return {"lisible": True, "active": bool(reglages.get("enabled", True)), "adresses": adresses, "utilisee": utilisee,
                "sur_pc": utilisee is not None and not adresses[utilisee]["nas"], "files": lignes}

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
            # 0.10.0 : une vidéo inconnue qu'Immich vient de lire (pas encore envoyée par nous) laisse la place à la sienne
            pas_parties = {l["rel"]: l["ancien_id"] for l in self.base.tous(
                "SELECT rel, ancien_id FROM photos WHERE origine = 'inconnu' AND nouveau_id IS NULL AND etat IN ('vue', 'a_encoder', 'ecart')")}
            # Relecture du 26/11/2026 : un fichier déjà passé par nous (copie dans Immich) qu'Immich lit après coup — vidéo
            # inconnue envoyée, ou original remis du sas — n'est pas une nouvelle photo : rien n'est recréé (pas de doublon)
            deja_passes = {l["rel"] for l in self.base.tous("SELECT rel FROM photos WHERE nouveau_id IS NOT NULL")}
            vues, neuves, ignorees = set(), [], 0
            animees = {}
            for a in im.photos_externes(biblio["id"]):
                rel = self._rel(a.get("originalPath", ""))
                if rel is None:
                    continue
                vues.add(a["id"])
                if a.get("livePhotoVideoId"):
                    animees[a["livePhotoVideoId"]] = a["id"]
                if a["id"] not in connues and rel in deja_passes:
                    ignorees += 1
                    continue
                if a["id"] not in connues:
                    if rel in pas_parties:
                        self.base.executer("DELETE FROM photos WHERE ancien_id = ?", (pas_parties[rel],))
                        self.base.executer("DELETE FROM encodages WHERE ancien_id = ?", (pas_parties[rel],))
                    taille = int((a.get("exifInfo") or {}).get("fileSizeInByte") or 0)
                    neuves.append((a["id"], rel, str(PurePosixPath(rel).parent), a.get("type", "IMAGE"), taille,
                                   int(a.get("visibility") == "hidden"), maintenant()))
            self.base.plusieurs("INSERT OR IGNORE INTO photos(ancien_id, rel, dossier, type, taille, cachee, le) VALUES (?,?,?,?,?,?,?)", neuves)
            for partie in animees:
                self.base.executer("UPDATE photos SET cachee = 1 WHERE ancien_id = ?", (partie,))
            self.base.ecrire("bibliotheque", biblio["id"])
        finally:
            im.fermer()
        if ignorees:
            log.info("%s entrée(s) d'Immich sur des fichiers déjà passés : ignorées", ignorees)
        # L'inventaire d'Immich est acquis dès ici : le parcours du dossier, plus long, vient après
        self.base.ecrire("inventaire", {"le": maintenant(), "photos": len(vues), "nouvelles": len(neuves), "inconnus": None})
        # Fichiers du dossier qu'Immich ne connaît pas : comptés par dossier, jamais touchés.
        # 0.1.1 : parcours tolérant (un dossier illisible est sauté) et qui n'entre pas dans les
        # dossiers techniques du NAS (@eaDir contient plusieurs vignettes par photo).
        connus = {l["rel"] for l in self.base.tous("SELECT rel FROM photos")}
        inconnus: dict[str, int] = {}
        liste: list[tuple[str, str]] = []
        videos: list[tuple] = []                          # 0.10.0 : vidéos qu'Immich ne connaît pas, à faire passer aussi
        racine = str(self.cfg.photos)
        sas = os.path.realpath(self.cfg.dossier_sas)
        for dossier, sous, fichiers in os.walk(racine, onerror=lambda e: log.warning("Dossier illisible, sauté : %s", e.filename)):
            sous[:] = [d for d in sous if d not in IGNORES and not d.startswith(".")
                       and os.path.realpath(os.path.join(dossier, d)) != sas]
            rel_dossier = os.path.relpath(dossier, racine).replace(os.sep, "/")
            for nom in fichiers:
                if nom.startswith(".") or nom.lower().endswith(ACCOMPAGNEMENTS) or nom in ("Thumbs.db", "desktop.ini"):
                    continue
                rel = nom if rel_dossier == "." else f"{rel_dossier}/{nom}"
                if rel not in connus and nom.lower().endswith(video.EXTENSIONS):
                    try:
                        taille = os.path.getsize(os.path.join(dossier, nom))
                    except OSError:
                        taille = 0
                    videos.append((self.id_inconnu(rel), rel, rel_dossier, "VIDEO", taille, 0, maintenant(), "inconnu"))
                    continue
                if rel not in connus:
                    inconnus[rel_dossier] = inconnus.get(rel_dossier, 0) + 1
                    liste.append((rel, rel_dossier))
        self.base.plusieurs("INSERT OR IGNORE INTO photos(ancien_id, rel, dossier, type, taille, cachee, le, origine) "
                            "VALUES (?,?,?,?,?,?,?,?)", videos)
        self.base.executer("DELETE FROM inconnus")
        self.base.plusieurs("INSERT OR IGNORE INTO inconnus(rel, dossier) VALUES (?,?)", liste)
        self.base.executer("UPDATE dossiers SET inconnus = 0")
        for d, n in inconnus.items():
            self.base.executer("INSERT INTO dossiers(chemin, inconnus) VALUES (?,?) ON CONFLICT(chemin) DO UPDATE SET inconnus = excluded.inconnus", (d, n))
        self.base.ecrire("inventaire", {"le": maintenant(), "photos": len(vues), "nouvelles": len(neuves),
                                        "inconnus": sum(inconnus.values())})
        self.base.noter("Inventaire relu", {"photos": len(vues), "nouvelles": len(neuves), "videos_inconnues": len(videos),
                                            "deja_passees_ignorees": ignorees})
        return self.base.lire("inventaire")

    @staticmethod
    def id_inconnu(rel: str) -> str:
        """0.10.0 : identifiant d'une vidéo qu'Immich ne connaît pas (la ligne porte origine = « inconnu »)."""
        return "inconnu-" + hashlib.sha1(rel.encode()).hexdigest()[:20]

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
        """Cocher un dossier coche tout ce qu'il contient (sauf les dossiers exclus et les dossiers finis) ; le décocher
        décoche tout ce qu'il contient.
        0.9.4 : plus de « souvenir » (0.1.3) : décocher un dossier plein rendait l'ancien choix partiel, et une case
        restait barrée au lieu de se vider (vu le 21/11/2026 sur la Pellicule). « vider » est gardé pour l'écran : même effet."""
        finis = self._finis()
        dessous = [d for d in self._descendance(chemin) if not self._exclu(d) and d not in finis]
        self.base.executer("DELETE FROM reglages WHERE cle LIKE 'souvenir:%'")       # restes des versions d'avant
        # 0.9.3 : une seule écriture pour toute la branche (avant : une par dossier, plusieurs secondes sur la Pellicule)
        self.base.plusieurs("INSERT INTO dossiers(chemin, coche) VALUES (?,?) ON CONFLICT(chemin) DO UPDATE SET coche = excluded.coche",
                            [(d, int(coche)) for d in dessous])

    def _finis(self) -> set[str]:
        """0.9.4 : dossiers dont tous les originaux sont supprimés. Ils n'ont plus de case : ni cochés, ni comptés."""
        # 0.9.6 : un fichier refusé par Immich qui reste dans le dossier ne l'empêche pas d'être fini
        return {l["dossier"] for l in self.base.tous(
            "SELECT dossier FROM photos GROUP BY dossier "
            f"HAVING SUM(etat != 'supprimee' AND NOT (etat = 'ecart' AND ecarts IN {RESTENT_SQL})) = 0 "
            "AND SUM(etat = 'supprimee') > 0")}

    def _exclu(self, dossier: str) -> bool:
        return PurePosixPath(dossier).parts[:1] in [(x,) for x in self.exclus()]

    def _descendance(self, chemin: str) -> list[str]:
        tous = {l["dossier"] for l in self.base.tous("SELECT DISTINCT dossier FROM photos")}
        if chemin in (".", ""):
            return sorted(tous)
        return sorted(d for d in tous if d == chemin or d.startswith(chemin + "/")) or [chemin]

    # ------------------------------------------------------------ demandes venues d'une autre appli (0.3.0)
    def demander(self, chemin_immich: str, de: str) -> dict:
        """Une autre appli (Millésime) signale qu'un dossier est prêt à passer. Transhumance le note et le montre :
        il ne coche rien et ne lance rien. Le chemin est celui qu'Immich voit ; il doit être sous la bibliothèque externe."""
        racine = self.cfg.racine_immich + "/"
        chemin_immich = (chemin_immich or "").rstrip("/")
        if not (chemin_immich + "/").startswith(racine):
            raise Refus("Ce dossier n'est pas dans la bibliothèque externe que Transhumance fait passer.", 404)
        chemin = chemin_immich[len(racine):]
        if not self.base.un("SELECT 1 FROM photos WHERE dossier = ? LIMIT 1", (chemin,)):
            raise Refus("Dossier inconnu de Transhumance : relis Immich et le dossier, puis redemande.", 404)
        if self._exclu(chemin):
            raise Refus("Ce dossier fait partie de ceux qui ne sont jamais migrés.", 409)
        demandes = self.base.lire("demandes", {})
        demandes[chemin] = {"de": str(de or "une autre appli")[:40], "le": maintenant()}
        self.base.ecrire("demandes", demandes)
        self.base.noter("Passage demandé", {"dossier": chemin, "de": demandes[chemin]["de"]})
        return {"ok": True, "dossier": chemin}

    # ------------------------------------------------------------ 0.4.0 : passage automatique des demandes
    def auto_demandes(self) -> bool:
        return bool(self.base.lire("auto_demandes", False))

    def regler_auto(self, oui: bool) -> None:
        self.exiger_ecriture()
        self.base.ecrire("auto_demandes", bool(oui))
        self.base.noter("Passage automatique des demandes " + ("activé" if oui else "coupé"))

    def passer_demande_suivante(self) -> str | None:
        """Si le réglage est activé et qu'aucun lot ne tourne : fait passer la plus ancienne demande (envoi et
        contrôle, comme « Migrer »). Les originaux ne sont jamais supprimés ici : cela reste un clic, après le bilan.
        Rend le dossier passé, ou None. Une demande impossible (place) est marquée et n'est pas retentée."""
        chemin = self.demande_suivante()
        if chemin:
            self.migrer([chemin], origine="Millésime")
        return chemin

    def demande_suivante(self) -> str | None:
        """0.8.0 : la première moitié de passer_demande_suivante (le choix, rapide), séparée du passage (long) pour
        que la boucle automatique et le lot soient suivis à part dans /health. Rend le dossier à faire passer, ou None."""
        if not self.auto_demandes() or self.tache.get("en_cours") or self.cfg.lecture_seule:
            return None
        demandes = self.base.lire("demandes", {})
        restent = {l["dossier"] for l in self.base.tous("SELECT DISTINCT dossier FROM photos WHERE etat IN ('vue', 'envoyee')")}
        # 0.9.3 : une demande ne part que si son dossier est coché ; sinon elle attend, avec sa pastille
        coches = set(self.a_migrer())
        for chemin, d in sorted(demandes.items(), key=lambda x: x[1].get("le", "")):
            if d.get("erreur") or chemin not in restent or self._exclu(chemin) or chemin not in coches:
                continue
            place = self.verifier_place([chemin])
            if not place["possible"]:
                d["erreur"] = "Pas assez de place libre dans le stockage d'Immich : à faire passer à la main."
                self.base.ecrire("demandes", demandes)
                self.base.noter("Passage automatique impossible", {"dossier": chemin, "raison": "place"})
                continue
            self.base.noter("Passage automatique", {"dossier": chemin, "de": d.get("de")})
            return chemin
        return None

    def oublier_demande(self, chemin: str) -> None:
        demandes = self.base.lire("demandes", {})
        if demandes.pop(chemin, None) is not None:
            self.base.ecrire("demandes", demandes)

    def arbre(self) -> dict:
        """L'arborescence : un nœud par dossier, avec ses comptes (les siens et ceux de ses enfants)."""
        # 0.1.7 : un dossier dont tous les originaux sont supprimés est fini, il ne reste pas coché
        self.base.executer("UPDATE dossiers SET coche = 0 WHERE coche = 1 AND chemin IN "
                           "(SELECT dossier FROM photos GROUP BY dossier HAVING SUM(etat != 'supprimee') = 0)")
        reglages = {l["chemin"]: l for l in self.base.tous("SELECT * FROM dossiers")}
        finis = self._finis()
        # 0.3.0 : une demande tombe d'elle-même quand le dossier n'a plus rien à envoyer
        demandes = self.base.lire("demandes", {})
        restent = {l["dossier"] for l in self.base.tous("SELECT DISTINCT dossier FROM photos WHERE etat = 'vue'")}
        if any(d not in restent for d in demandes):
            demandes = {d: v for d, v in demandes.items() if d in restent}
            self.base.ecrire("demandes", demandes)
        noeuds: dict[str, dict] = {}

        def noeud(chemin: str) -> dict:
            if chemin not in noeuds:
                r = reglages.get(chemin)
                noeuds[chemin] = {"chemin": chemin, "nom": PurePosixPath(chemin).name or "Photos", "enfants": [],
                                  "photos": 0, "videos": 0, "poids": 0, "etats": {}, "ici": 0,
                                  # 0.9.7 : ce qui est encore dans le dossier du NAS (tout sauf les originaux supprimés)
                                  "restants": 0, "poids_restant": 0,
                                  "inconnus": r["inconnus"] if r else 0, "coche": bool(r and r["coche"]),
                                  "exclu": self._exclu(chemin), "propose": self.album_propose(chemin),
                                  "album": self.album_de(chemin), "demande": demandes.get(chemin)}
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
                if l["etat"] != "supprimee":
                    p["restants"] += l["n"]
                    p["poids_restant"] += l["poids"] or 0
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
            # 0.9.4 : un dossier fini n'est plus compté (il était compté mais toujours décoché : la case du parent
            # ne pouvait jamais être pleine et restait barrée)
            if not n["ici"] or n["exclu"] or chemin in finis:
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
        for n in noeuds.values():
            n["enfants"].sort(key=str.casefold)
        return {"racine": ".", "noeuds": noeuds, "inventaire": self.base.lire("inventaire"),
                "tache": self.tache, "lecture_seule": self.cfg.lecture_seule, "immich_adresse": "",   # 0.7.0 : rempli par main (annuaire)
                "auto_demandes": self.auto_demandes()}

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

    @staticmethod
    def _accompagnement_propre(fichier: Path) -> Path | None:
        """0.7.1 : « IMG_1.jpg.xmp » est à ce fichier ; « IMG_1.xmp » seulement si aucun autre « IMG_1.* » n'est à côté."""
        propre = fichier.with_name(fichier.name + ".xmp")
        if propre.is_file():
            return propre
        commun = fichier.with_suffix(".xmp")
        if commun.is_file():
            freres = [f for f in fichier.parent.glob(glob.escape(fichier.stem) + ".*")
                      if f != fichier and f.suffix.lower() != ".xmp" and not f.name.endswith(".xmp")]
            if not freres:
                return commun
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

    def _instantane_inconnu(self, l) -> dict:
        """0.10.0 : une vidéo qu'Immich ne connaît pas n'a rien à reporter, sauf sa date (trouvée à la préparation)."""
        m = json.loads(l["mesures"] or "{}")
        return {"id": None, "chemin": l["rel"], "type": "VIDEO", "empreinte": None, "date": m.get("date"),
                "source_date": m.get("source_date"), "fuseau": None, "latitude": None, "longitude": None,
                "description": "", "note": None, "favori": False, "visibilite": None, "animee": None,
                "duree": m.get("duree"), "tags": [], "albums": [], "visages": []}

    def _envoyer(self, im: Immich, l, album_id: str | None, nouveaux: dict[str, str]) -> None:
        fichier = self._fichier(l["rel"])
        if not fichier.is_file():
            self._etat(l["ancien_id"], "ecart", ecarts=["introuvable"])
            return
        # 0.10.0 : une vidéo mise en MP4 part sous la forme de son MP4 ; l'original reste le témoin du contrôle
        envoi = self._produit(l) if l["voie"] in TRANSFORMEES else fichier
        if envoi is None or not envoi.is_file():
            self.base.executer("UPDATE photos SET etat = 'a_encoder', produit = NULL WHERE ancien_id = ?", (l["ancien_id"],))
            self.base.executer("UPDATE encodages SET etat = 'attente', par = NULL WHERE ancien_id = ?", (l["ancien_id"],))
            return
        inst = self._instantane_inconnu(l) if l["origine"] == "inconnu" else self._instantane(im, l["ancien_id"])
        somme = empreinte(envoi)
        video_animee = nouveaux.get(inst["animee"]) if inst.get("animee") else None
        nouveau, deja = im.envoyer(envoi, self._accompagnement(fichier), video_animee, inst.get("visibilite"))
        nouveaux[l["ancien_id"]] = nouveau
        self.base.executer("UPDATE photos SET etat = 'envoyee', nouveau_id = ?, empreinte = ?, deja_la = ?, instantane = ?, le = ? "
                           "WHERE ancien_id = ?", (nouveau, somme, int(deja), json.dumps(inst, ensure_ascii=False), maintenant(), l["ancien_id"]))
        self.base.noter("Photo envoyée", {"ancien": l["ancien_id"], "nouveau": nouveau, "deja_la": deja})
        if l["cachee"]:
            return                                       # partie vidéo d'une photo animée : rien d'autre à reporter
        if l["origine"] != "inconnu":                    # 0.10.0 : une vidéo inconnue d'Immich n'a pas d'ancienne entrée
            im.reporter(l["ancien_id"], nouveau)
        if album_id:
            im.ajouter_album(album_id, [nouveau])
        # 0.2.1 : un tag ou une description qu'Immich refuse n'arrête plus le lot. Le contrôle les reprend
        # (Immich a alors fini de lire la photo), et en fait un écart s'il refuse encore.
        try:
            for t in inst["tags"]:
                im.etiqueter(t["id"], [nouveau])
            corrections = {k: v for k, v in (("description", inst["description"]), ("rating", inst["note"])) if v}
            if corrections:
                im.corriger(nouveau, corrections)
        except ErreurImmich as exc:
            self.base.noter("Report à reprendre au contrôle", {"nouveau": nouveau, "raison": str(exc)})

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
                    try:
                        im.reaffecter_visage(n["id"], v["personne"])
                        issue["reaffecte"] += 1
                    except LectureSeule:
                        raise
                    except ErreurImmich as exc:              # 0.1.6 : un refus ne coupe plus le lot, la photo part en écart
                        log.warning("Visage non rattaché sur %s : %s", nouveau, exc)
                        issue["perdu"] += 1
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
        if l["voie"] in TRANSFORMEES and "empreinte" not in ecarts:
            ecarts += self._prouver_video(l, copie)
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
            manquants = voulus - {a["id"] for a in im.albums_de(l["nouveau_id"])} if voulus else set()
            if manquants:
                # 0.2.1 : un lot interrompu a pu laisser la copie hors d'un album ; on l'y remet avant de juger
                try:
                    for album in manquants:
                        im.ajouter_album(album, [l["nouveau_id"]])
                except ErreurImmich:
                    pass
                if not voulus <= {a["id"] for a in im.albums_de(l["nouveau_id"])}:
                    ecarts.append("album")
            ecarts += self._finir_reports(im, inst, l["nouveau_id"], copie)
            inst["chemin_final"] = copie.get("originalPath")
            self.base.executer("UPDATE photos SET instantane = ? WHERE ancien_id = ?", (json.dumps(inst, ensure_ascii=False), l["ancien_id"]))
        self._etat(l["ancien_id"], "ecart" if ecarts else "prete", ecarts)

    def _finir_reports(self, im: Immich, inst: dict, nouveau: str, copie: dict) -> list[str]:
        """Tags, description, note et favori : ce qui manque à la copie est reporté maintenant (un lot interrompu,
        ou un refus d'Immich à l'envoi, a pu en laisser). Rend les écarts qui restent."""
        ecarts = []
        portes = {t["id"] for t in copie.get("tags") or []}
        for t in inst.get("tags") or []:
            if t["id"] not in portes:
                try:
                    im.etiqueter(t["id"], [nouveau])
                except ErreurImmich as exc:
                    self.base.noter("Tag refusé par Immich", {"nouveau": nouveau, "tag": t.get("nom"), "raison": str(exc)})
                    ecarts.append("tag")
                    break
        exif = copie.get("exifInfo") or {}
        champs = {}
        if inst.get("description") and (exif.get("description") or "") != inst["description"]:
            champs["description"] = inst["description"]
        if inst.get("note") and exif.get("rating") != inst["note"]:
            champs["rating"] = inst["note"]
        if inst.get("favori") and not copie.get("isFavorite"):
            champs["isFavorite"] = True
        if champs:
            try:
                im.corriger(nouveau, champs)
            except ErreurImmich as exc:
                self.base.noter("Description refusée par Immich", {"nouveau": nouveau, "raison": str(exc)})
                ecarts.append("description")
        return ecarts

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
        # 0.9.3 : exactement les dossiers que l'arbre compte comme cochés (au moins une photo visible), ni plus ni moins
        coches = [l["chemin"] for l in self.base.tous(
            "SELECT chemin FROM dossiers WHERE coche = 1 AND chemin IN (SELECT DISTINCT dossier FROM photos WHERE cachee = 0) ORDER BY chemin")]
        finis = self._finis()
        return [d for d in coches if not self._exclu(d) and d not in finis]

    def verifier_place(self, dossiers: list[str]) -> dict:
        besoin = sum((self.base.un("SELECT COALESCE(SUM(taille),0) s FROM photos WHERE dossier = ? AND etat IN ('vue', 'a_encoder', 'encodee')", (d,))["s"]) for d in dossiers)
        im = self.immich()
        try:
            libre = im.place_libre()
        finally:
            im.fermer()
        return {"besoin": besoin, "libre": libre, "possible": besoin <= libre * self.cfg.marge_place}

    def migrer(self, dossiers: list[str] | None = None, origine: str | None = None, verrou_pris: bool = False) -> None:
        """Fait passer les dossiers cochés (ou ceux donnés : passage automatique d'une demande). Rejouable : une
        photo déjà envoyée n'est pas renvoyée.
        0.9.3 : un seul lot à la fois (verrou_lot). verrou_pris : l'appelant l'a déjà pris (route /api/migrer, boucle
        automatique) et le passe ici ; il est rendu à la fin dans tous les cas."""
        if not verrou_pris and not self.verrou_lot.acquire(blocking=False):
            raise Refus("Un lot est déjà en cours.", 409)
        try:
            self._migrer(dossiers, origine)
        finally:
            self.verrou_lot.release()

    def _migrer(self, dossiers: list[str] | None, origine: str | None) -> None:
        self.exiger_ecriture()
        dossiers = dossiers or self.a_migrer()
        if not dossiers:
            raise Refus("Aucun dossier coché.")
        try:                                           # 0.10.0 : chaque vidéo restante reçoit sa voie (ffprobe)
            self.preparer_videos(dossiers)
        except (ErreurImmich, Refus, OSError) as exc:   # relecture : l'erreur se voit à l'écran, le lot ne part pas
            self.tache.update(erreur=str(exc), en_cours=False)
            log.warning("Préparation des vidéos interrompue : %s", exc)
            return
        place = self.verifier_place(dossiers)
        if not place["possible"]:
            raise Refus("Pas assez de place libre pour ce lot : coche moins de dossiers, ou supprime d'abord les originaux d'un lot déjà contrôlé.")
        total = sum(self.base.un("SELECT COUNT(*) n FROM photos WHERE dossier = ? AND etat IN ('vue','encodee','envoyee')", (d,))["n"] for d in dossiers)
        avant = f"Demandé par {origine} : " if origine else ""          # 0.9.3 : l'écran dit qui a lancé le lot
        self.tache.update(en_cours=True, fait=0, total=total, erreur=None, message=avant + "Envoi…", origine=origine, dossiers=len(dossiers))
        self.base.noter("Lot lancé", {"dossiers": len(dossiers), "par": origine or "Faire passer"})
        im = self.immich()
        try:
            albums: dict[str, str] = {}
            for d in dossiers:
                nom = self.album_de(d)
                album_id = albums.setdefault(nom, im.album(nom)) if nom else None
                nouveaux: dict[str, str] = {}
                # Les parties vidéo des photos animées d'abord : la photo s'y rattache à l'envoi
                for l in self.base.tous("SELECT * FROM photos WHERE dossier = ? AND etat IN ('vue', 'encodee') ORDER BY cachee DESC, rel", (d,)):
                    self.tache["message"] = f"{avant}Envoi de {d}"
                    try:     # 0.7.3 : un fichier refusé par Immich ne bloque plus tout le lot à chaque relance
                        self._envoyer(im, l, album_id, nouveaux)
                    except ErreurImmich as exc:
                        msg = str(exc)
                        if "a refusé" not in msg or "(401)" in msg or "(403)" in msg:
                            raise                   # Immich injoignable ou clé refusée : le lot s'arrête, comme avant
                        log.warning("Fichier refusé par Immich : %s (%s)", l["rel"], exc)
                        self._etat(l["ancien_id"], "ecart", ecarts=["refuse"])
                        if (produit := self._produit(l)) is not None:    # le MP4 refusé ne sert plus
                            shutil.rmtree(produit.parent, ignore_errors=True)
                    self.tache["fait"] += 1
            self._attendre_files(im)
            # 0.1.4 : le compteur repart pour le contrôle, qui est la partie la plus longue
            self.tache.update(fait=0, total=sum(self.base.un("SELECT COUNT(*) n FROM photos WHERE dossier = ? AND etat = 'envoyee'", (d,))["n"] for d in dossiers))
            for d in dossiers:
                for l in self.base.tous("SELECT * FROM photos WHERE dossier = ? AND etat = 'envoyee' ORDER BY rel", (d,)):
                    self.tache["message"] = f"{avant}Contrôle de {d}"
                    self._controler(im, l)
                    self.tache["fait"] += 1
            self.exporter()
            self.base.noter("Lot passé", {"dossiers": len(dossiers)})
            file = sum(self.base.un("SELECT COUNT(*) n FROM photos WHERE dossier = ? AND etat = 'a_encoder'", (d,))["n"] for d in dossiers)
            self.tache["message"] = f"{avant}Lot passé : lis le bilan." + (
                f" {file} vidéo(s) attendent leur mise en MP4 : elles partiront toutes seules, puis seront contrôlées." if file else "")
        except (ErreurImmich, Refus, OSError) as exc:
            self.tache["erreur"] = str(exc)
            log.warning("Lot interrompu : %s", exc)
        finally:
            im.fermer()
            self.tache["en_cours"] = False

    # ================================================================ 0.10.0 : les vidéos restantes
    def _lancees(self) -> set[str]:
        return set(self.base.lire("videos_lancees", []))

    def preparer_videos(self, dossiers: list[str]) -> int:
        """Lit chaque vidéo restante des dossiers du lot (ffprobe) et lui donne sa voie : remux ou encode (elle entre dans
        la file), tel_quel (elle part comme une photo), pas_video (elle reste, jamais touchée). Une vidéo refusée par
        Immich (écart « refuse ») est reprise. Les Live Photos (parties cachées) ne sont jamais séparées de leur photo.
        Rend le nombre de vidéos lues."""
        lus = 0
        lancees = self._lancees()
        im = None
        try:
            for d in dossiers:
                lignes = self.base.tous("SELECT * FROM photos WHERE dossier = ? AND type = 'VIDEO' AND cachee = 0 AND voie IS NULL "
                                        "AND (etat = 'vue' OR (etat = 'ecart' AND ecarts = ?))", (d, json.dumps(["refuse"])))
                if not lignes:
                    continue
                if not video.outils():                    # relecture : jamais d'envoi silencieux sans ffmpeg
                    raise Refus("ffmpeg manque dans l'image : les vidéos de ce lot ne peuvent pas être lues. Rien n'est parti.")
                lancees.add(d)
                for l in lignes:
                    fichier = self._fichier(l["rel"])
                    if not fichier.is_file():
                        self._etat(l["ancien_id"], "ecart", ["introuvable"])
                        continue
                    try:                                   # relecture : une vidéo illisible ne bloque pas les autres
                        m = video.mesures(video.sonder(fichier))
                        st = fichier.stat()
                    except (video.ErreurVideo, OSError) as exc:
                        log.warning("Vidéo illisible, laissée en place : %s (%s)", l["rel"], exc)
                        self.base.executer("UPDATE photos SET voie = 'pas_video' WHERE ancien_id = ?", (l["ancien_id"],))
                        self._etat(l["ancien_id"], "ecart", ["pas_video"])
                        continue
                    v = video.voie(m)
                    if l["origine"] == "inconnu":
                        date, source = video.date_trouvee(l["rel"], m, self.cfg.pellicule, st.st_mtime)
                    else:                                  # la date vérifiée par Julien dans Immich l'emporte
                        im = im or self.immich()
                        exif = (im.photo(l["ancien_id"]) or {}).get("exifInfo") or {}
                        date, source = exif.get("dateTimeOriginal") or m.get("creation"), "immich"
                        if not date:
                            date, source = video.date_trouvee(l["rel"], m, self.cfg.pellicule, st.st_mtime)
                    m.update(date=date, source_date=source, orig_taille=st.st_size, orig_mtime=st.st_mtime_ns,
                             extension=fichier.suffix.lower())
                    self.base.executer("UPDATE photos SET voie = ?, mesures = ?, taille = ? WHERE ancien_id = ?",
                                       (v, json.dumps(m, ensure_ascii=False), st.st_size, l["ancien_id"]))
                    if v == "pas_video":
                        self._etat(l["ancien_id"], "ecart", ["pas_video"])
                    elif v == "tel_quel":
                        self._etat(l["ancien_id"], "vue")
                    else:
                        self._etat(l["ancien_id"], "a_encoder")
                        self.base.executer("INSERT INTO encodages(ancien_id) VALUES (?) ON CONFLICT(ancien_id) DO UPDATE SET "
                                           "etat = 'attente', par = NULL, essais = 0, erreur = NULL", (l["ancien_id"],))
                    self.base.noter("Vidéo lue", {"ancien": l["ancien_id"], "voie": v, "codec": m.get("codec"), "date": source})
                    lus += 1
        finally:
            if im:
                im.fermer()
        self.base.ecrire("videos_lancees", sorted(lancees))
        return lus

    def _produit(self, l) -> Path | None:
        if not l["produit"]:
            return None
        chemin = (self.cfg.encodes / l["produit"]).resolve()
        return chemin if self.cfg.encodes.resolve() in chemin.parents else None

    def _prouver_video(self, l, copie: dict) -> list[str]:
        """La copie d'Immich a l'empreinte de notre MP4 (déjà vérifié) : la preuve se fait sur ce MP4, contre l'original.
        Ajoute la vignette d'Immich (elle prouve qu'Immich sait lire la vidéo)."""
        m = json.loads(l["mesures"] or "{}")
        produit, fichier = self._produit(l), self._fichier(l["rel"])
        # relecture : la preuve porte sur les octets mêmes qu'Immich a reçus
        if produit is None or not produit.is_file() or not fichier.is_file() or empreinte(produit) != l["empreinte"]:
            return ["illisible"]
        ecarts, mc = video.prouver(fichier, produit, m)
        if not copie.get("thumbhash") and "illisible" not in ecarts:
            ecarts.append("illisible")
        if (m.get("produit") or {}).get("grossi"):
            ecarts.append("grossi")
        m["copie"] = mc
        self.base.executer("UPDATE photos SET mesures = ? WHERE ancien_id = ?", (json.dumps(m, ensure_ascii=False), l["ancien_id"]))
        return ecarts

    # ------------------------------------------------------------ la file (PC et NAS)
    def pc_vu(self, machine: str = "") -> None:
        self.base.ecrire("pc_vu", {"le": maintenant(), "machine": str(machine or "")[:60]})

    def pc_actif(self) -> bool:
        vu = self.base.lire("pc_vu")
        return bool(vu) and _age(vu["le"]) < PC_ABSENT_S

    def _rendre_perimes(self) -> None:
        for e in self.base.tous("SELECT * FROM encodages WHERE etat = 'pris'"):
            if _age(e["vu_le"] or e["pris_le"]) > BAIL_S:
                self.base.executer("UPDATE encodages SET etat = 'attente', par = NULL, machine = NULL, avance = NULL WHERE id = ?", (e["id"],))
                self.base.noter("Vidéo rendue à la file (plus de signe de vie)", {"encodage": e["id"], "par": e["par"]})

    def prendre(self, par: str, machine: str = "", voies: tuple[str, ...] = TRANSFORMEES) -> dict | None:
        """La prochaine vidéo à mettre en MP4 : son dossier doit être coché et lancé (« Faire passer »). None sinon.
        Il faut deux fois sa taille de place libre dans le dossier de données."""
        if self.cfg.lecture_seule or not voies:
            return None
        coches = set(self.a_migrer()) & self._lancees()
        if not coches:
            return None
        with self.verrou_file:
            self._rendre_perimes()
            marques = ",".join("?" * len(voies))
            for l in self.base.tous(f"SELECT e.id, p.* FROM encodages e JOIN photos p ON p.ancien_id = e.ancien_id "
                                    f"WHERE e.etat = 'attente' AND p.etat = 'a_encoder' AND p.voie IN ({marques}) ORDER BY e.id", voies):
                if l["dossier"] not in coches:
                    continue
                self.cfg.encodes.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(self.cfg.encodes).free < 2 * (l["taille"] or 0):
                    log.info("Vidéo laissée en attente (pas assez de place dans le dossier de données) : %s", l["rel"])
                    continue                               # relecture : la suivante, plus petite, peut passer
                self.base.executer("UPDATE encodages SET etat = 'pris', par = ?, machine = ?, pris_le = ?, vu_le = ?, avance = 0 WHERE id = ?",
                                   (par, str(machine or "")[:60], maintenant(), maintenant(), l["id"]))
                fichier = self._fichier(l["rel"])
                try:
                    voisins = {f.name for f in fichier.parent.iterdir()}
                except OSError:
                    voisins = set()
                m = json.loads(l["mesures"] or "{}")
                return {"id": l["id"], "ancien": l["ancien_id"], "voie": l["voie"], "nom": fichier.name,
                        "nom_mp4": video.nom_mp4(l["rel"], voisins), "taille": l["taille"], "mesures": m, "date": m.get("date")}
        return None

    def _encodage(self, ident: int, par: str | None = None):
        e = self.base.un("SELECT * FROM encodages WHERE id = ?", (ident,))
        if e is None or e["etat"] != "pris" or (par and e["par"] != par):
            raise Refus("Cette vidéo n'est plus à toi : elle a été rendue à la file.", 409)
        return e

    def fichier_a_encoder(self, ident: int, par: str = "pc") -> Path:
        e = self._encodage(ident, par)
        l = self.base.un("SELECT rel FROM photos WHERE ancien_id = ?", (e["ancien_id"],))
        return self._fichier(l["rel"])

    def vie(self, ident: int, avance: float | None = None, par: str = "pc") -> bool:
        """Signe de vie de celui qui encode. Faux : la vidéo lui a été reprise (il peut s'arrêter)."""
        e = self.base.un("SELECT * FROM encodages WHERE id = ?", (ident,))
        if e is None or e["etat"] != "pris" or e["par"] != par:
            return False
        self.base.executer("UPDATE encodages SET vu_le = ?, avance = ? WHERE id = ?",
                           (maintenant(), max(0.0, min(1.0, float(avance or 0))), ident))
        return True

    def chemin_produit(self, ident: int, nom: str, par: str = "pc") -> Path:
        """Relecture : un dossier par vidéo ET par machine, pour que le PC et le NAS n'écrivent jamais au même fichier."""
        propre = re.sub(r"[\\/\x00]", "_", nom or "video.mp4")[:180]
        if not propre.lower().endswith(".mp4"):
            propre += ".mp4"
        return self.cfg.encodes / f"{int(ident)}-{'nas' if par == 'nas' else 'pc'}" / propre

    def finir(self, ident: int, produit: Path, info: dict | None = None, par: str | None = None) -> None:
        """Le MP4 est là : la vidéo attend son envoi (prochain lot, ou envoi automatique)."""
        e = self._encodage(ident, par)
        m = video.mesures(video.sonder(produit))
        if not m.get("video"):
            produit.unlink(missing_ok=True)
            raise Refus("Le MP4 reçu ne se lit pas comme une vidéo.", 422)
        l = self.base.un("SELECT mesures FROM photos WHERE ancien_id = ?", (e["ancien_id"],))
        mo = json.loads(l["mesures"] or "{}")
        mo["produit"] = {"taille": produit.stat().st_size, "codec": m.get("codec"), "par": e["par"], "machine": e["machine"],
                         "le": maintenant(), **{k: v for k, v in (info or {}).items() if k in ("grossi", "leger", "materiel")}}
        video.dater(produit, mo.get("date"))              # relecture : la date du MP4 du PC ne passe pas par HTTP
        rel = produit.resolve().relative_to(self.cfg.encodes.resolve()).as_posix()
        self.base.executer("UPDATE photos SET etat = 'encodee', produit = ?, mesures = ? WHERE ancien_id = ?",
                           (rel, json.dumps(mo, ensure_ascii=False), e["ancien_id"]))
        self.base.executer("UPDATE encodages SET etat = 'fait', avance = 1, erreur = NULL WHERE id = ?", (ident,))
        self.base.noter("Vidéo mise en MP4", {"ancien": e["ancien_id"], "par": e["par"], "taille": mo["produit"]["taille"]})

    def echouer(self, ident: int, message: str, par: str | None = None) -> None:
        e = self._encodage(ident, par)
        essais = e["essais"] + 1
        if essais >= ESSAIS:
            self.base.executer("UPDATE encodages SET etat = 'erreur', essais = ?, erreur = ? WHERE id = ?", (essais, message[:400], ident))
            self._etat(e["ancien_id"], "ecart", ["encodage"])
        else:
            self.base.executer("UPDATE encodages SET etat = 'attente', par = NULL, essais = ?, erreur = ? WHERE id = ?",
                               (essais, message[:400], ident))
        self.base.noter("Mise en MP4 ratée", {"ancien": e["ancien_id"], "essai": essais, "erreur": message[:200]})
        shutil.rmtree(self.chemin_produit(ident, "x", e["par"]).parent, ignore_errors=True)

    def encodeur_nas_tour(self) -> bool:
        """Un tour de l'encodeur du NAS : les remux toujours (pas besoin du PC) ; les réencodages seulement si le PC n'a
        pas fait signe depuis 10 min et que la puce vidéo du NAS a réussi son essai. Rend vrai s'il a travaillé."""
        voies = ("remux", "encode") if self.materiel_nas.get("ok") and not self.pc_actif() else ("remux",)
        job = self.prendre("nas", "NAS", voies)
        if not job:
            return False
        self.encodage_nas = {"fichier": job["nom"], "voie": job["voie"]}
        fini = threading.Event()

        def signes_de_vie():                              # relecture : sans eux, une longue vidéo serait rendue au PC
            while not fini.wait(60):
                self.vie(job["id"], None, "nas")
        threading.Thread(target=signes_de_vie, daemon=True).start()
        try:
            entree = self.fichier_a_encoder(job["id"], "nas")
            sortie = self.chemin_produit(job["id"], job["nom_mp4"], "nas")
            info = video.mettre_en_mp4(job["voie"], entree, sortie, job["mesures"], job["date"],
                                       self.materiel_nas.get("mode", "vaapi"), doux=True, suffixe="part-nas")
            info["materiel"] = "aucun (remux)" if job["voie"] == "remux" else self.materiel_nas.get("mode", "vaapi")
            self.finir(job["id"], sortie, info, "nas")
        except (video.ErreurVideo, OSError, Refus) as exc:
            try:
                self.echouer(job["id"], str(exc), "nas")
            except Refus:
                pass
        finally:
            fini.set()
            self.encodage_nas = None
        return True

    def dossiers_a_envoyer(self) -> list[str]:
        """Dossiers cochés et lancés qui ont des vidéos mises en MP4 prêtes à partir (envoi automatique)."""
        coches = set(self.a_migrer()) & self._lancees()
        prets = {l["dossier"] for l in self.base.tous("SELECT DISTINCT dossier FROM photos WHERE etat = 'encodee'")}
        return sorted(coches & prets)

    def etat_encodage(self) -> dict:
        vu = self.base.lire("pc_vu")
        file = {l["etat"]: l["n"] for l in self.base.tous("SELECT etat, COUNT(*) n FROM encodages GROUP BY etat")}
        en_cours = [{"fichier": PurePosixPath(l["rel"]).name, "par": l["par"], "machine": l["machine"], "avance": l["avance"],
                     "voie": l["voie"]}
                    for l in self.base.tous("SELECT e.par, e.machine, e.avance, p.rel, p.voie FROM encodages e "
                                            "JOIN photos p ON p.ancien_id = e.ancien_id WHERE e.etat = 'pris' ORDER BY e.id")]
        return {"pc": {"vu_le": vu and vu["le"], "machine": vu and vu["machine"], "actif": self.pc_actif()},
                "nas": {k: self.materiel_nas.get(k) for k in ("ok", "pilote", "raison")},
                "file": {"attente": file.get("attente", 0), "pris": file.get("pris", 0), "faits": file.get("fait", 0),
                         "erreurs": file.get("erreur", 0)},
                "a_envoyer": self.base.un("SELECT COUNT(*) n FROM photos WHERE etat = 'encodee'")["n"],
                "en_cours": en_cours, "outils": video.outils()}

    # ------------------------------------------------------------ le sas des originaux vidéo (30 jours)
    def _vers_sas(self, l, fichier: Path) -> str:
        """Déplace l'original (et son .xmp) dans le sas daté. Rend le chemin relatif au sas."""
        rel = f"{datetime.now(timezone.utc).date().isoformat()}/{l['rel']}"
        cible = self.cfg.dossier_sas / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        if cible.exists():
            rel = f"{datetime.now(timezone.utc).date().isoformat()}/{l['rel']}.{int(time.time())}"
            cible = self.cfg.dossier_sas / rel
        accompagnement = self._accompagnement_propre(fichier) if not l["deja_la"] else None
        shutil.move(str(fichier), str(cible))
        if accompagnement:
            shutil.move(str(accompagnement), str(cible.parent / accompagnement.name))
        return rel

    def remettre(self, ancien: str) -> dict:
        """Remet un original vidéo du sas à sa place. La copie reste dans Immich ; la vidéo revient « copiée et
        contrôlée » (un nouveau clic la renverra au sas)."""
        self.exiger_ecriture()
        l = self.base.un("SELECT * FROM photos WHERE ancien_id = ?", (ancien,))
        if l is None or l["etat"] != "supprimee" or not l["sas"]:
            raise Refus("Cette vidéo n'est pas dans le sas.", 404)
        source = (self.cfg.dossier_sas / l["sas"]).resolve()
        cible = self._fichier(l["rel"])
        if self.cfg.dossier_sas.resolve() not in source.parents or not source.is_file():
            raise Refus("L'original n'est plus dans le sas.", 404)
        if cible.exists():
            raise Refus("Un fichier porte déjà ce nom à sa place d'origine : rien n'est déplacé.", 409)
        cible.parent.mkdir(parents=True, exist_ok=True)
        xmp = self._accompagnement_propre(source)          # seulement le sien
        shutil.move(str(source), str(cible))
        if xmp and not (cible.parent / xmp.name).exists():
            shutil.move(str(xmp), str(cible.parent / xmp.name))
        inst = json.loads(l["instantane"] or "{}")
        inst["ancien_retire"] = True                      # l'ancienne entrée d'Immich est déjà retirée
        self.base.executer("UPDATE photos SET etat = 'prete', sas = NULL, sas_le = NULL, instantane = ? WHERE ancien_id = ?",
                           (json.dumps(inst, ensure_ascii=False), ancien))
        self.base.noter("Original remis du sas", {"ancien": ancien})
        return {"ok": True}

    def vider_sas(self, maintenant_: datetime | None = None) -> int:
        """Efface les originaux entrés dans le sas il y a plus de 30 jours. Rend le nombre effacé."""
        if self.cfg.lecture_seule:                         # relecture : la lecture seule ne supprime rien, le sas non plus
            return 0
        limite = (maintenant_ or datetime.now(timezone.utc)) - timedelta(days=self.cfg.jours_sas)
        effaces = 0
        dus = [l for l in self.base.tous("SELECT ancien_id, nouveau_id, empreinte, sas, sas_le FROM photos "
                                         "WHERE etat = 'supprimee' AND sas IS NOT NULL")
               if datetime.fromisoformat(l["sas_le"]) <= limite]
        if not dus:
            return 0
        im = self.immich()
        try:
            for l in dus:
                # Relecture : dernière preuve avant d'effacer pour de bon — la copie est toujours dans Immich, intacte
                copie = im.photo(l["nouveau_id"]) if l["nouveau_id"] else None
                if copie is None or copie.get("checksum") != l["empreinte"] or copie.get("isTrashed") \
                        or copie.get("libraryId") or copie.get("isOffline"):
                    self.base.noter("Sas : original gardé, la copie n'est plus bonne dans Immich", {"ancien": l["ancien_id"]})
                    continue
                effaces += self._effacer_du_sas(l)
        finally:
            im.fermer()
        if effaces:
            for d in sorted((p for p in self.cfg.dossier_sas.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                try:
                    d.rmdir()                              # seulement les dossiers vides
                except OSError:
                    pass
            self.base.noter("Sas vidé", {"effaces": effaces})
        return effaces

    def _effacer_du_sas(self, l) -> int:
        f = (self.cfg.dossier_sas / l["sas"]).resolve()
        if self.cfg.dossier_sas.resolve() in f.parents:
            accompagnement = self._accompagnement_propre(f) if f.is_file() else None   # seulement le sien
            f.unlink(missing_ok=True)
            if accompagnement:
                accompagnement.unlink(missing_ok=True)
        self.base.executer("UPDATE photos SET sas = NULL WHERE ancien_id = ?", (l["ancien_id"],))
        return 1

    # ================================================================ bilan, suppression, retour arrière
    def _photos_sous(self, chemin: str) -> list:
        if chemin in (".", ""):
            return self.base.tous("SELECT * FROM photos ORDER BY rel")
        # 0.7.1 : préfixe exact ; « LIKE » prenait « _ » pour un joker et ignorait la casse (Voyage_2019 ⊃ Voyage 2019)
        prefixe = chemin + "/"
        return self.base.tous("SELECT * FROM photos WHERE dossier = ? OR substr(dossier, 1, ?) = ? ORDER BY rel",
                              (chemin, len(prefixe), prefixe))

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
                               "phrase": ECARTS[e][0], "bloquant": ECARTS[e][1], "accepte": bool(l["accepte"]), "personnes": perdus,
                               "reste": e in RESTENT})   # 0.9.6 : reste dans le dossier sans bloquer la suppression
        inconnus = sum(r["inconnus"] for r in self.base.tous("SELECT chemin, inconnus FROM dossiers")
                       if chemin in (".", "") or r["chemin"] == chemin or r["chemin"].startswith(chemin + "/"))
        # 0.7.1 : la partie vidéo d'une photo animée (cachée) compte aussi : son écart bloque la suppression
        # 0.9.6 : un fichier refusé par Immich reste dans le dossier et ne bloque plus les autres (constaté le 23/11/2026)
        refuses = [l for l in visibles if reste_seulement(l)]
        en_attente = [l for l in photos if l["etat"] == "ecart" and not reste_seulement(l)
                      and (not l["accepte"] or any(ECARTS[e][1] for e in json.loads(l["ecarts"])))]
        pretes = [l for l in visibles if l["etat"] == "prete" or (l["etat"] == "ecart" and l["accepte"] and not any(ECARTS[e][1] for e in json.loads(l["ecarts"])))]
        supprimes = etats.get("supprimee", 0)
        termine = bool(visibles) and supprimes > 0 and supprimes + len(refuses) == len(visibles)
        file = etats.get("a_encoder", 0) + etats.get("encodee", 0)
        return {
            "videos": self._videos_du_bilan(photos), "sas": self._sas_du_bilan(photos), "en_file": file,
            "termine": termine, "supprimes": supprimes,
            "chemin": chemin, "fichiers": len(visibles), "etats": etats, "deja_la": deja, "visages": visages, "ecarts": ecarts,
            "inconnus": inconnus, "a_supprimer": len(pretes), "refuses": len(refuses),
            "fichiers_inconnus": [l["rel"] for l in (self.base.tous("SELECT rel FROM inconnus ORDER BY rel LIMIT 300") if chemin in (".", "")
                                  else self.base.tous("SELECT rel FROM inconnus WHERE dossier = ? OR substr(dossier, 1, ?) = ? ORDER BY rel LIMIT 300",
                                                      (chemin, len(chemin) + 1, chemin + "/")))],
            "supprimable": bool(pretes) and not en_attente and not etats.get("vue") and not etats.get("envoyee") and not file,
            "phrase": f"Terminé : les {supprimes} photos et vidéos de ce dossier sont dans le stockage d'Immich, et leurs originaux sont supprimés."
                      + (f" {len(refuses)} fichier(s) laissé(s) dans le dossier (refusés par Immich, sans image ou impossibles à mettre en MP4)." if refuses else "")
                      + (f" {inconnus} fichier(s) qu'Immich ne connaît pas sont restés dans le dossier." if inconnus else "")
                      if termine else
                      f"{len(visibles)} fichiers dans ce dossier ; {len(pretes) + supprimes} retrouvés identiques dans Immich"
                      + (f" (dont {supprimes} aux originaux déjà supprimés)" if supprimes else "") + " ; "
                      f"{len(en_attente)} avec un écart à régler ; "
                      + (f"{len(refuses)} laissé(s) dans le dossier (refusés par Immich, sans image ou impossibles à mettre en MP4 ; ils ne bloquent pas les autres) ; " if refuses else "")
                      + (f"{file} vidéo(s) en cours de mise en MP4 ; " if file else "")
                      + (f"{etats['envoyee']} envoyés, pas encore contrôlés ; " if etats.get("envoyee") else "")
                      + f"{etats.get('vue', 0)} pas encore envoyés ; "
                      f"{inconnus} qu'Immich ne connaît pas (ils resteront dans le dossier).",
            "echantillon": [{"nouveau": l["nouveau_id"], "fichier": l["rel"]} for l in pretes[:: max(1, len(pretes) // 5)][:5]],
        }

    def _videos_du_bilan(self, photos) -> list[dict]:
        """0.10.0 : les vidéos restantes du dossier : voie, avant → après, date trouvée, avancement."""
        file = {l["ancien_id"]: l for l in self.base.tous("SELECT * FROM encodages")}
        sortie = []
        for l in photos:
            if not l["voie"]:
                continue
            m = json.loads(l["mesures"] or "{}")
            e = file.get(l["ancien_id"])
            sortie.append({"ancien": l["ancien_id"], "fichier": l["rel"], "voie": l["voie"], "etat": l["etat"], "origine": l["origine"],
                           "avant": {"codec": m.get("codec"), "taille": m.get("orig_taille"), "duree": m.get("duree"),
                                     "largeur": m.get("largeur"), "hauteur": m.get("hauteur"), "extension": m.get("extension")},
                           "apres": m.get("produit"), "ssim": (m.get("copie") or {}).get("ssim"),
                           "date": m.get("date"), "source_date": m.get("source_date"),
                           "file": {"etat": e["etat"], "par": e["par"], "avance": e["avance"], "essais": e["essais"],
                                    "erreur": e["erreur"]} if e else None,
                           "ecarts": json.loads(l["ecarts"] or "[]")})
        return sortie[:300]

    def _sas_du_bilan(self, photos) -> dict:
        dedans = [l for l in photos if l["sas"] and l["etat"] == "supprimee"]
        lignes = []
        for l in dedans[:300]:
            efface = datetime.fromisoformat(l["sas_le"]) + timedelta(days=self.cfg.jours_sas)
            lignes.append({"ancien": l["ancien_id"], "fichier": l["rel"], "le": l["sas_le"], "efface_le": efface.isoformat(timespec="seconds"),
                           "taille": l["taille"]})
        return {"nombre": len(dedans), "poids": sum(l["taille"] or 0 for l in dedans), "jours": self.cfg.jours_sas, "lignes": lignes}

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
        if self.suppression["en_cours"]:
            raise Refus("Une suppression est déjà en cours : attends sa fin.", 409)
        b = self.bilan(chemin)
        if not b["supprimable"]:
            raise Refus("Ce dossier n'est pas prêt : des photos ne sont pas passées, ou un écart n'est pas réglé.", 409)
        im = self.immich()
        faits, retires, gardes = 0, [], 0

        def eligible(l) -> bool:
            bloquant = any(ECARTS[e][1] for e in json.loads(l["ecarts"]))
            return l["etat"] == "prete" or (l["etat"] == "ecart" and bool(l["accepte"]) and not bloquant)

        a_faire = [l for l in self._photos_sous(chemin) if eligible(l)]
        # 0.1.8 : l'avancement, lu par l'écran pendant que le clic travaille
        self.suppression = {"en_cours": True, "dossier": chemin, "fait": 0, "total": len(a_faire), "etape": "fichiers"}
        try:
            for l in a_faire:
                self.suppression["fait"] += 1
                copie = im.photo(l["nouveau_id"]) if l["nouveau_id"] else None
                fichier = self._fichier(l["rel"])
                # Dernière preuve, au moment de supprimer : la copie existe et le fichier n'a pas changé depuis l'envoi
                # 0.7.1 : la copie doit être dans le stockage d'Immich (pas la bibliothèque externe) et différente de l'ancienne
                # 0.10.0 : pour une vidéo mise en MP4, la copie a l'empreinte du MP4 ; l'original n'a pas changé si sa
                # taille et sa date de modification sont celles lues à la préparation
                if copie is None or copie.get("checksum") != l["empreinte"] or copie.get("isTrashed") \
                        or copie.get("libraryId") or copie.get("isOffline") or l["nouveau_id"] == l["ancien_id"] \
                        or (fichier.is_file() and not self._original_inchange(l, fichier)):
                    self._etat(l["ancien_id"], "ecart", ["copie_absente" if copie is None else "empreinte"])
                    gardes += 1
                    continue
                # 0.10.1 : original absent au moment du clic : jamais compté « supprimé » en silence ; un écart à accepter
                # (après acceptation, le clic suivant clôt la ligne sans rien toucher)
                if not fichier.is_file():
                    deja_vu = l["etat"] == "ecart" and bool(l["accepte"]) and "original_absent" in json.loads(l["ecarts"] or "[]")
                    if not deja_vu:
                        self._etat(l["ancien_id"], "ecart", ["original_absent"])
                        self.base.executer("UPDATE photos SET accepte = 0 WHERE ancien_id = ?", (l["ancien_id"],))
                        self.base.noter("Original absent au moment de supprimer", {"ancien": l["ancien_id"], "fichier": l["rel"]})
                        gardes += 1
                        continue
                inst = json.loads(l["instantane"] or "{}")
                if l["type"] == "VIDEO":
                    # 0.10.0 : un original vidéo part dans le sas (30 jours), pas à la poubelle — relecture : toute vidéo,
                    # même passée avant la 0.10.0 ou partie vidéo d'une Live Photo
                    if fichier.is_file():
                        place = self._vers_sas(l, fichier)
                        self.base.executer("UPDATE photos SET sas = ?, sas_le = ? WHERE ancien_id = ?", (place, maintenant(), l["ancien_id"]))
                    produit = self._produit(l)
                    if produit is not None:
                        shutil.rmtree(produit.parent, ignore_errors=True)
                elif fichier.is_file():
                    accompagnement = self._accompagnement_propre(fichier) if not l["deja_la"] else None
                    fichier.unlink()
                    if accompagnement:       # 0.7.1 : seulement s'il est à ce fichier seul et qu'Immich l'a reçu
                        accompagnement.unlink()
                if l["origine"] != "inconnu" and not inst.get("ancien_retire"):
                    retires.append(l["ancien_id"])
                self._etat(l["ancien_id"], "supprimee")
                faits += 1
        finally:
            # 0.7.1 : le retrait des anciennes photos d'Immich se fait même si la boucle s'est arrêtée en route
            if retires:
                self.suppression["etape"] = "immich"
                try:
                    im.retirer(retires)
                except ErreurImmich as exc:
                    self.base.noter("Retrait d'Immich à refaire", {"dossier": chemin, "photos": retires, "erreur": str(exc)[:300]})
            self.suppression = {**self.suppression, "en_cours": False}
            im.fermer()
            self.base.noter("Originaux supprimés", {"dossier": chemin, "supprimes": faits, "gardes": gardes})
            self.exporter()
        return {"supprimes": faits, "gardes": gardes, "bilan": self.bilan(chemin)}

    def _original_inchange(self, l, fichier: Path) -> bool:
        if l["voie"] in TRANSFORMEES:
            m = json.loads(l["mesures"] or "{}")
            st = fichier.stat()
            return st.st_size == m.get("orig_taille") and st.st_mtime_ns == m.get("orig_mtime")
        return empreinte(fichier) == l["empreinte"]

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
