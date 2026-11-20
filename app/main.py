"""Transhumance : interface et adresses. Une seule porte : le mot de passe commun.

Routes : /health (publique), /api/session, /api/connexion, /api/deconnexion, puis l'arbre, le lot,
le bilan, la suppression et le retour arrière ; 0.7.0 : /api/reglages, /api/restaurer, /externe/sauvegarde."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import re
import time
import urllib.error
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, maison
from .auth import COMMUN, DUREE, Sessions, en_https
from .base import Base
from .config import APPLI, charger
from .immich import ErreurImmich
from .passage import Refus, Transhumance

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
ETAT: dict = {}
log = logging.getLogger("transhumance")


@asynccontextmanager
async def cycle(app: FastAPI):
    cfg = ETAT.get("cfg") or charger()
    ETAT.setdefault("cfg", cfg)
    ETAT.setdefault("t", Transhumance(cfg, Base(cfg.data / "transhumance.db"), ETAT.get("transport")))
    # M32 (audit du 17/11/2026) : la génération des sessions est relue dans /data ; une déconnexion vaut après un redémarrage
    ETAT.setdefault("sessions", Sessions(APPLI, cfg.password, _lire_generation(cfg.data)))
    # 0.8.0 : santé des tâches de fond (socle 0.9.0) — chaque boucle se déclare, chaque tour est suivi dans /health
    maison.TACHES.declarer(TACHE_AUTO, periode_s=AUTO_S, type="reguliere")
    maison.TACHES.declarer(TACHE_LOT, type="demande")
    maison.TACHES.declarer(TACHE_INVENTAIRE, type="demande")
    # 0.4.0 : le passage automatique des dossiers demandés par Millésime (s'il est activé dans l'appli)
    if ETAT.get("boucle_auto", True):
        threading.Thread(target=_boucle_auto, daemon=True, name="auto").start()
    # 0.8.0 : copie cohérente de la base chaque nuit (heure de Paris), dans <données>/copies
    copie = asyncio.create_task(maison.planifier_copie(APPLI, [cfg.data / "transhumance.db"], cfg.data / "copies",
                                                       maison.HEURES_COPIE[APPLI]))
    yield
    copie.cancel()


def _fichier_generation(data: Path) -> Path:
    return data / "session_generation"


def _lire_generation(data: Path) -> int:
    try:
        return int(_fichier_generation(data).read_text().strip())
    except (OSError, ValueError):
        return 0


# 0.8.0 : noms des tâches suivies dans /health (taches, socle 0.9.0)
TACHE_AUTO = "passage-auto"        # la boucle qui regarde chaque minute s'il y a une demande de Millésime à faire passer
TACHE_LOT = "lot"                  # un passage (envoi et contrôle) : « Migrer » ou une demande passée toute seule
TACHE_INVENTAIRE = "inventaire"    # « Relire » : Immich et le dossier des photos
AUTO_S = 60                        # période de la boucle automatique (secondes)


class _LotInterrompu(Exception):
    """0.8.0 : le lot s'est arrêté en route (erreur déjà notée par migrer dans la tâche, montrée à l'écran)."""


def _lot_suivi(dossiers: list[str] | None = None) -> None:
    """Un lot, suivi dans /health. migrer garde pour lui l'erreur d'un lot interrompu (dans t().tache["erreur"]) :
    elle est relancée ici pour que le tour compte comme raté. Rien d'autre ne change."""
    with maison.TACHES.tour(TACHE_LOT):
        t().migrer(dossiers)
        if t().tache.get("erreur"):
            raise _LotInterrompu(t().tache["erreur"])


def _boucle_auto() -> None:
    while True:
        time.sleep(AUTO_S)
        try:
            # 0.8.0 : le choix (rapide) est le tour de la boucle ; le passage (long) est suivi à part, comme un lot :
            # un passage de plusieurs heures ne fait pas croire à une boucle bloquée
            with maison.TACHES.tour(TACHE_AUTO):
                chemin = ETAT["t"].demande_suivante()
            if chemin:
                _lot_suivi([chemin])
        except _LotInterrompu:
            pass                  # comme avant : l'erreur est dans la tâche, montrée à l'écran, et déjà au journal
        except Exception as exc:  # noqa: BLE001 — l'erreur est dans la tâche, montrée à l'écran
            log.warning("Passage automatique interrompu : %s", exc)


app = FastAPI(title=APPLI, version=__version__, lifespan=cycle, docs_url=None, redoc_url=None)


def t() -> Transhumance:
    return ETAT["t"]


@app.middleware("http")
async def garde(request: Request, appel):
    chemin = request.url.path
    if chemin.startswith("/externe/"):
        # Portes des autres applis de la maison : /externe/demandes (Millésime, 0.3.0) et /externe/sauvegarde
        # (l'Anneau, 0.7.0). 0.7.0 : jeton commun seul (MAISON_JETON, MAISON_JETON_ANCIEN), comparé en temps constant ;
        # l'ancien jeton de Millésime n'est plus lu. Aucun jeton commun posé : porte fermée (404). La session n'est
        # pas demandée ici.
        acceptes = maison.jetons()
        if not acceptes:
            return JSONResponse({"detail": "Adresse fermée."}, status_code=404)
        if not maison.jeton_valide(maison.jeton_propose(request.headers), acceptes):
            return JSONResponse({"detail": "Jeton manquant ou invalide."}, status_code=401)
    if chemin.startswith("/api/"):
        libre = chemin == "/api/session" or (chemin == "/api/connexion" and request.method == "POST")
        s = ETAT["sessions"]
        if not libre and not s.connecte(request.cookies):
            return JSONResponse({"detail": "Connexion nécessaire."}, status_code=401)
    reponse = await appel(request)
    if chemin.startswith(("/api/", "/externe/")):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.exception_handler(Refus)
async def _refus(_: Request, exc: Refus):
    return JSONResponse({"detail": str(exc)}, status_code=exc.code)


@app.exception_handler(ErreurImmich)
async def _immich(_: Request, exc: ErreurImmich):
    return JSONResponse({"detail": str(exc)}, status_code=502)


ANNUAIRE = maison.Annuaire()


def immich_adresse(request: Request) -> str:
    """Adresse d'Immich pour le navigateur (liens du bilan), lue dans l'Anneau (tuile « Immich », privée si la page
    vient de Tailscale). 0.7.0 : plus de variable de repli (TRANSHUMANCE_IMMICH_ADRESSE retirée) ; Anneau injoignable
    et rien en mémoire : pas de lien, le bilan reste lisible."""
    return ANNUAIRE.adresse("Immich", prive=maison.est_prive(request.headers.get("host", "")))


def arbre_vu(request: Request) -> dict:
    """L'arbre, avec l'adresse d'Immich vue par ce navigateur."""
    return {**t().arbre(), "immich_adresse": immich_adresse(request)}


@app.get("/health")
def sante(request: Request):
    # 0.8.0 : + version_socle, taches, copie_base (socle 0.9.0) ; messages d'erreur seulement avec le jeton commun
    # ou une session valide
    return {"ok": True, "version": __version__,
            **maison.sante(request, jeton_commun=maison.jetons(), session_ok=ETAT["sessions"].connecte(request.cookies))}


@app.get("/api/session")
def session(request: Request):
    s = ETAT["sessions"]
    return {"connecte": s.connecte(request.cookies), "version": __version__,
            "lecture_seule": ETAT["cfg"].lecture_seule, "lecture_seule_origine": ETAT["cfg"].lecture_seule_origine}


@app.post("/api/connexion")
async def connexion(request: Request, corps: dict = Body(...)):
    s = ETAT["sessions"]
    if ETAT["cfg"].attente_connexion:
        await asyncio.sleep(s.attente())
    if not s.verifier_mot_de_passe(str(corps.get("mot_de_passe", ""))):
        raise HTTPException(401, "Mot de passe incorrect.")
    r = JSONResponse({"ok": True})
    r.set_cookie(s.cookie, s.creer(), max_age=DUREE, httponly=True, samesite="strict", secure=en_https(request))
    return r


@app.post("/api/deconnexion")
def deconnexion():
    s = ETAT["sessions"]
    s.generation += 1
    try:
        _fichier_generation(ETAT["cfg"].data).write_text(str(s.generation))   # M32 : gardée pour le prochain démarrage
    except OSError as exc:
        log.warning("Génération des sessions non gardée : %s", exc)
    r = JSONResponse({"ok": True})
    r.delete_cookie(s.cookie)
    r.delete_cookie(COMMUN)      # « Se déconnecter » ferme aussi la connexion commune
    return r


# ---------------------------------------------------------------- lecture

@app.get("/api/arbre")
def arbre(request: Request):
    return arbre_vu(request)


@app.post("/api/inventaire")
def inventaire(request: Request):
    """Relit Immich et le dossier des photos. N'écrit rien dans Immich ni dans le dossier."""
    with maison.TACHES.tour(TACHE_INVENTAIRE):       # 0.8.0 : suivi dans /health (tâche à la demande)
        t().inventaire()
    return arbre_vu(request)


@app.get("/api/bilan")
def bilan(chemin: str = "."):
    return t().bilan(chemin)


@app.get("/api/reconnaissance")
def reconnaissance():
    """0.1.5 : Immich fait-il travailler le PC ? Lecture seule, relue toutes les dix secondes par l'écran Migrer.
    0.9.0 : la lecture sert aussi d'essai à la fiche « PC de calcul » (et nourrit son guide)."""
    r = t().reconnaissance()
    _noter_reconnaissance(r)
    return r


@app.get("/api/connexions")
def connexions():
    """0.9.0 : l'écran Connexion lit /api/maison/services. Cette route reste pour Réglages (journal, dossier des
    photos) ; sa partie « immich » n'est plus lue par l'interface : à retirer en 0.10.0."""
    cfg = ETAT["cfg"]
    im = t().immich()
    try:
        immich = {"ok": True, "version": im.version(), "place_libre": im.place_libre()}
        SERVICES.noter("immich", True, _phrase_immich(immich["version"], immich["place_libre"]))
    except ErreurImmich as exc:
        immich = {"ok": False, "erreur": str(exc)}
        SERVICES.noter("immich", False, str(exc))
    finally:
        im.fermer()
    # 0.7.1 : plus de fichier d'essai écrit dans le dossier des photos (même en lecture seule) : on demande au système
    inscriptible = cfg.photos.is_dir() and os.access(cfg.photos, os.W_OK | os.X_OK)
    return {"immich": immich, "dossier": {"lisible": cfg.photos.is_dir(), "inscriptible": inscriptible,
                                          "exclus": t().exclus()},
            "version": __version__, "lecture_seule": cfg.lecture_seule, "lecture_seule_origine": cfg.lecture_seule_origine,
            "journal": [dict(l) for l in t().base.tous("SELECT le, quoi, detail FROM journal ORDER BY id DESC LIMIT 60")]}


# ================================================================ fiches « Connexion » (0.9.0, contrat 3, socle 0.11.0)
# GET /api/maison/services et POST /api/maison/services/{id}/verifier (session ou ANNEAU_CLE) : écran commun
# $lib/services/Services.svelte, et fiche « État » de l'Anneau. Deux services : Immich, et le PC de calcul vu par la
# reconnaissance d'Immich. Essais légers, en lecture seule : la version et la place libre d'Immich ; ses réglages de
# reconnaissance, ses files et un /ping de chaque adresse déclarée (ne réveille pas le PC). Le dossier des photos
# n'est pas un service : il est montré dans Réglages.

def _poids(octets: int) -> str:
    """Comme poids() de l'interface (format.js) : « 1,2 Go »."""
    if not octets:
        return "0"
    if octets < 1024 ** 2:
        return f"{max(1, round(octets / 1024))} ko"
    if octets < 1024 ** 3:
        return f"{octets / 1024 ** 2:.0f} Mo"
    return f"{octets / 1024 ** 3:.1f} Go".replace(".", ",")


def _phrase_immich(version: str, place: int) -> str:
    return f"Version {version} · {_poids(place)} libres."


def _essai_immich():
    im = t().immich()
    try:
        return True, _phrase_immich(im.version(), im.place_libre())
    finally:
        im.fermer()


def _verdict(r: dict | None) -> str:
    """Même phrase que l'écran (Reconnaissance.svelte)."""
    if not r:
        return "Pas encore lu."
    if not r.get("lisible"):
        return "Réglages d'Immich illisibles"
    if not r.get("active"):
        return "Reconnaissance désactivée dans Immich"
    if r.get("utilisee") is None:
        return "Aucun service de reconnaissance ne répond"
    return ("Le PC fait la reconnaissance" if r.get("sur_pc")
            else "Le NAS fait la reconnaissance (le PC ne répond pas ou n'est pas déclaré)")


def _resultat_reconnaissance(r: dict) -> tuple[bool, str]:
    """Le voyant est vert seulement si le PC travaille (comme le point de l'ancien écran)."""
    reste = sum(f.get("attente", 0) + f.get("en_cours", 0) for f in r.get("files") or [])
    phrase = _verdict(r) + (f" · {reste} tâche(s) de reconnaissance en attente" if r.get("files") else "")
    if r.get("lisible") is False and r.get("raison"):
        phrase += " : " + r["raison"]
    return bool(r.get("lisible") and r.get("active") and r.get("sur_pc")), phrase


def _noter_reconnaissance(r: dict) -> None:
    ETAT["reconnaissance"] = r
    SERVICES.noter("immich-ml", *_resultat_reconnaissance(r))


def _essai_pc():
    r = t().reconnaissance()
    ETAT["reconnaissance"] = r
    return _resultat_reconnaissance(r)


def _guide_pc() -> dict:
    """Guide de la fiche « PC de calcul » : la dernière lecture (aucun appel ici : le GET n'essaie rien), puis la
    marche à suivre. Rien de propre à la maison dans le code : les adresses viennent des réglages d'Immich."""
    r = ETAT.get("reconnaissance")
    reglages = []
    if not r:
        reglages.append({"nom": "Adresses de reconnaissance", "valeur": "pas encore lues : Vérifier"})
    elif not r.get("lisible"):
        reglages.append({"nom": "Réglages d'Immich", "valeur": r.get("raison") or "illisibles"})
    else:
        reglages.append({"nom": "Reconnaissance dans Immich", "valeur": "activée" if r.get("active") else "désactivée"})
        for i, a in enumerate(r.get("adresses") or []):
            etat = (("répond : c'est lui qui travaille" if i == r.get("utilisee") else "répond, en secours")
                    if a.get("repond") else "ne répond pas")
            reglages.append({"nom": f"{i + 1}. {'NAS' if a.get('nas') else 'PC'}", "valeur": f"{a.get('adresse')} · {etat}"})
        if not r.get("adresses"):
            reglages.append({"nom": "Adresses de reconnaissance", "valeur": "aucune déclarée dans Immich"})
    for f in (r or {}).get("files") or []:
        reglages.append({"nom": f["nom"], "valeur": (f"{f['en_cours']} en cours · " if f.get("en_cours") else "")
                                                    + f"{f.get('attente', 0)} en attente"})
    return {
        "reglages": reglages,
        "allumer": [
            "Allumer le PC (ou le sortir de veille) et ouvrir Docker Desktop : le conteneur immich_ml_pc redémarre "
            "tout seul (restart: unless-stopped, fichier pc/immich-ml.yml du dépôt).",
            "Attendre une dizaine de secondes, puis Vérifier : « Le PC fait la reconnaissance ». Le premier travail "
            "télécharge les modèles une fois (volume model-cache).",
            "PC éteint : rien à faire. Immich retombe tout seul sur l'adresse suivante (le NAS), plus lent.",
            "Après la migration : « docker compose -f immich-ml.yml down » sur le PC, puis retirer l'adresse du PC "
            "dans Immich.",
        ],
        "pannes": [
            {"signe": "« Le NAS fait la reconnaissance (le PC ne répond pas ou n'est pas déclaré) »",
             "faire": ["Le PC est-il allumé et sorti de veille ? Docker Desktop est-il ouvert, le conteneur "
                       "immich_ml_pc lancé (première commande) ?",
                       "Depuis un téléphone sur le Wi-Fi de la maison, ouvrir l'adresse du PC (Réglages lus, plus haut) "
                       "suivie de /ping : la page doit répondre « pong ».",
                       "Rien ne s'affiche : comparer l'adresse du PC (deuxième commande) à celle déclarée dans Immich ; "
                       "si elle a changé, la corriger dans Immich ou réserver l'adresse dans la box. Puis vérifier que "
                       "le port répond sur le PC lui-même (troisième commande, TcpTestSucceeded : True) ; si oui, "
                       "c'est le pare-feu de Windows (voir « Installation »).",
                       "Aucune adresse « PC » dans Réglages lus : elle n'est pas déclarée dans Immich (voir « Installation »)."],
             "commandes": ["docker ps --filter name=immich_ml_pc", "ipconfig | findstr IPv4",
                           "Test-NetConnection -ComputerName localhost -Port 3003"]},
            {"signe": "Le conteneur immich_ml_pc s'arrête tout seul",
             "faire": ["La fin de son journal dit pourquoi (version, modèles, mémoire…). La version doit être celle "
                       "du serveur Immich (même valeur que IMMICH_VERSION sur le NAS)."],
             "commandes": ["docker logs --tail 30 immich_ml_pc"]},
            {"signe": "« Réglages d'Immich illisibles »",
             "faire": ["La clé d'API de Transhumance n'a pas le droit de lire les réglages d'Immich : permission "
                       "« systemConfig.read », clé d'un compte administrateur (TRANSHUMANCE_IMMICH_CLE)."],
             "commandes": []},
            {"signe": "« Reconnaissance désactivée dans Immich »",
             "faire": ["Dans Immich : Administration › Paramètres › Apprentissage automatique, réactiver."],
             "commandes": []},
            {"signe": "« Aucun service de reconnaissance ne répond »",
             "faire": ["Ni le PC ni le NAS ne répondent : vérifier aussi le conteneur immich-machine-learning dans "
                       "Portainer (stack homelab)."],
             "commandes": []},
        ],
        "une_fois": [
            {"texte": "Copier pc/immich-ml.yml (dépôt transhumance) dans un dossier du PC (par exemple C:\\immich-ml), "
                      "puis, dans ce dossier, avec Docker Desktop ouvert :",
             "commande": "docker compose -f immich-ml.yml up -d"},
            {"texte": "Dans Immich : Administration › Paramètres › Apprentissage automatique › « Ajouter une URL » "
                      "http://<adresse du PC>:3003, et la glisser AU-DESSUS de l'adresse déjà présente. Immich "
                      "essaie les adresses dans l'ordre : PC éteint, il retombe tout seul sur le NAS.",
             "commande": ""},
            {"texte": "Ce service n'a aucune protection : port 3003 ouvert au seul réseau local (PowerShell "
                      "administrateur) :",
             "commande": "New-NetFirewallRule -DisplayName \"Immich reconnaissance\" -Direction Inbound -Protocol TCP "
                         "-LocalPort 3003 -RemoteAddress LocalSubnet -Action Allow"},
            {"texte": "L'adresse du PC fixée dans la box (bail réservé), sinon elle peut changer et Immich ne la "
                      "trouve plus.", "commande": ""},
        ],
        "terminal": "Les commandes se tapent dans PowerShell sur le PC (menu Démarrer › PowerShell).",
        "note": "Transhumance ne change rien aux réglages d'Immich. Carte graphique NVIDIA : voir l'en-tête de "
                "pc/immich-ml.yml. Ce guide n'a jamais été essayé sur la vraie installation.",
    }


SERVICES = maison.Services(APPLI)
SERVICES.ajouter(
    "immich", "Immich",
    lit="Transhumance y lit la bibliothèque externe.",
    ecrit="Transhumance y envoie les copies, y reporte albums, tags et visages, puis en retire les anciennes photos. "
          "Ne mets pas Immich à jour pendant la migration.",
    regle=lambda: bool(ETAT.get("cfg") and ETAT["cfg"].immich_cle),
    reglage="TRANSHUMANCE_IMMICH_URL et TRANSHUMANCE_IMMICH_CLE",
    essai=_essai_immich)
SERVICES.ajouter(
    "immich-ml", "PC de calcul (reconnaissance d'Immich)",
    lit="Qui fait la reconnaissance d'Immich (visages, recherche, texte) — le PC ou le NAS ? Immich essaie ces "
        "adresses dans l'ordre et prend la première qui répond. Transhumance leur pose la même question toutes les "
        "dix secondes : elle ne voit pas chaque calcul, mais si le PC répond en premier, c'est lui qu'Immich utilise.",
    ecrit="Rien. Elle ne change rien aux réglages d'Immich.",
    regle=lambda: bool(ETAT.get("cfg") and ETAT["cfg"].immich_cle),
    reglage="TRANSHUMANCE_IMMICH_CLE",
    essai=_essai_pc, guide=_guide_pc)
# Monté APRÈS la garde : le dernier middleware ajouté passe en premier.
maison.monter_services(app, SERVICES, lambda r: "sessions" in ETAT and ETAT["sessions"].connecte(r.cookies))


# ---------------------------------------------------------------- réglages d'usage (0.7.0)

APPLI_ID = "transhumance"            # nom du dépôt : nom de l'appli dans les sauvegardes de l'Anneau
# Clés qui ne sortent jamais de l'appli, même si un jour elles entraient dans les réglages : la clé d'Immich, les
# adresses et chemins de la stack, le mot de passe. (maison.est_secret écarte en plus tout nom qui ressemble à un secret.)
EXCLUS_SAUVEGARDE = ("immich_cle", "immich_url", "racine_immich", "photos", "data", "password", "mot_de_passe")
JOUR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.get("/api/reglages")
def lire_reglages():
    return t().reglages_tout()


@app.put("/api/reglages")
def changer_reglages(corps: dict = Body(...)):
    """Change les réglages d'usage. Valeur de mauvais type : 400, rien n'est changé. Permis en lecture seule : ni
    Immich ni le dossier des photos ne sont touchés."""
    try:
        return t().changer_reglages(corps)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/externe/sauvegarde")
def sauvegarde():
    """L'Anneau collecte les réglages chaque nuit (jeton commun). Réglages et version seulement : ni variable, ni
    chemin, ni secret."""
    return maison.sauvegarde(APPLI_ID, __version__, t().reglages_tout(), exclus=EXCLUS_SAUVEGARDE)


def _chez_l_anneau(le: str = "") -> dict:
    """Lit les sauvegardes chez l'Anneau ; message clair s'il ne répond pas ou n'a rien."""
    try:
        return maison.lire_sauvegarde(APPLI_ID, le)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, "L'Anneau n'a pas de sauvegarde de Transhumance" + (f" du {le}." if le else " pour l'instant.")) from exc
        raise HTTPException(503, f"L'Anneau a répondu {exc.code} : sauvegardes illisibles pour l'instant.") from exc
    except Exception as exc:  # noqa: BLE001 — Anneau injoignable, réponse illisible : message, jamais d'erreur de page
        raise HTTPException(503, f"L'Anneau est injoignable ({exc.__class__.__name__}) : réessaie plus tard.") from exc


def _sauvegarde_du(le: str) -> dict:
    if not JOUR.match(le or ""):
        raise HTTPException(400, "Date attendue sous la forme AAAA-MM-JJ.")
    sauves = _chez_l_anneau(le)
    if not isinstance(sauves, dict) or not isinstance(sauves.get("reglages"), dict):
        raise HTTPException(404, f"L'Anneau n'a pas de réglages de Transhumance du {le}.")
    return sauves


@app.get("/api/restaurer")
def restaurer_voir(le: str = ""):
    """Sans « le » : les dates des sauvegardes. Avec « le » : ce qui changerait (actuel → sauvegardé)."""
    if not le:
        dates = (_chez_l_anneau() or {}).get("dates") or []
        if not dates:
            raise HTTPException(404, "L'Anneau n'a pas de sauvegarde de Transhumance pour l'instant.")
        return {"dates": dates}
    sauves = _sauvegarde_du(le)
    return {"le": le, "version": sauves.get("version", ""),
            "differences": maison.differences(t().reglages_tout(), sauves["reglages"], EXCLUS_SAUVEGARDE)}


@app.post("/api/restaurer")
def restaurer(corps: dict = Body(...)):
    """Applique les différences d'une sauvegarde (réglages seulement). Permis en lecture seule."""
    le = str(corps.get("le", ""))
    sauves = _sauvegarde_du(le)
    diff = maison.differences(t().reglages_tout(), sauves["reglages"], EXCLUS_SAUVEGARDE)
    if not diff:
        raise HTTPException(404, f"Rien à restaurer : les réglages sont déjà ceux du {le}.")
    try:
        return t().changer_reglages({d["cle"]: d["sauve"] for d in diff}, par=f"Réglage restauré (sauvegarde du {le})")
    except ValueError as exc:
        raise HTTPException(400, f"La sauvegarde du {le} contient une valeur illisible : {exc}") from exc


# ---------------------------------------------------------------- demandes des autres applis (jeton)

@app.post("/externe/demandes")
def demande(corps: dict = Body(...)):
    """Millésime signale qu'un dossier est daté et prêt à passer. Rien n'est coché ni lancé."""
    return t().demander(str(corps.get("dossier", "")), str(corps.get("de", "")))


# ---------------------------------------------------------------- gestes

@app.post("/api/auto-demandes")
def auto_demandes(request: Request, corps: dict = Body(...)):
    """0.4.0 : faire passer tout seul les dossiers demandés par Millésime (envoi et contrôle ; jamais la suppression)."""
    t().regler_auto(bool(corps.get("oui")))
    return arbre_vu(request)


@app.post("/api/demande/oublier")
def oublier_demande(request: Request, corps: dict = Body(...)):
    t().oublier_demande(str(corps.get("chemin", "")))
    return arbre_vu(request)


@app.post("/api/dossier")
def regler_dossier(request: Request, corps: dict = Body(...)):
    chemin = str(corps.get("chemin", ""))
    if not chemin:
        raise HTTPException(422, "Dossier manquant.")
    t().regler_dossier(chemin, album=corps.get("album"), coche=corps.get("coche"), defaut=bool(corps.get("defaut")), vider=bool(corps.get("vider")))
    return arbre_vu(request)


@app.get("/api/lot")
def lot():
    dossiers = t().a_migrer()
    return {"dossiers": dossiers, **(t().verifier_place(dossiers) if dossiers else {"besoin": 0, "libre": 0, "possible": True})}


@app.post("/api/migrer")
def migrer():
    """Lance le passage des dossiers cochés, en tâche de fond. Aucune suppression."""
    tr = t()
    tr.exiger_ecriture()
    if tr.tache["en_cours"]:
        raise HTTPException(409, "Un lot est déjà en cours.")
    dossiers = tr.a_migrer()
    if not dossiers:
        raise HTTPException(422, "Aucun dossier coché.")
    if not tr.verifier_place(dossiers)["possible"]:
        raise HTTPException(409, "Pas assez de place libre pour ce lot.")
    tr.tache.update(en_cours=True, erreur=None, message="Démarrage…", fait=0, total=0)

    def faire():
        try:
            _lot_suivi()                     # 0.8.0 : suivi dans /health (tâche à la demande « lot »)
        except _LotInterrompu:
            pass                             # comme avant : l'erreur est déjà dans tr.tache, montrée à l'écran
        except Exception as exc:  # noqa: BLE001 — l'erreur est montrée à l'écran
            tr.tache.update(en_cours=False, erreur=str(exc))
    threading.Thread(target=faire, daemon=True, name="lot").start()
    return tr.tache


@app.post("/api/accepter")
def accepter(corps: dict = Body(...)):
    t().accepter(str(corps.get("ancien", "")), bool(corps.get("oui", True)))
    return {"ok": True}


@app.post("/api/supprimer")
def supprimer(corps: dict = Body(...)):
    """Supprime les originaux prouvés copiés sous ce dossier. Le nombre attendu doit être redonné :
    un clic sur un écran périmé ne supprime rien."""
    chemin = str(corps.get("chemin", ""))
    tr = t()
    tr.exiger_ecriture()
    attendu = tr.bilan(chemin)["a_supprimer"]
    if not chemin or corps.get("nombre") != attendu:
        raise HTTPException(409, "Le bilan a changé depuis l'affichage : relis-le avant de supprimer.")
    return tr.supprimer(chemin)


@app.get("/api/suppression")
def suppression():
    """0.1.8 : où en est la suppression en cours (lu chaque seconde par l'écran). Ne lit pas la base."""
    return t().suppression


@app.post("/api/defaire")
def defaire(corps: dict = Body(...)):
    return t().defaire(str(corps.get("chemin", "")))


@app.get("/{chemin:path}")
def interface(chemin: str):
    if chemin.startswith("api/"):
        raise HTTPException(404, "Adresse inconnue.")
    statique = ETAT["cfg"].static
    fichier = (statique / chemin).resolve() if chemin else None
    if fichier and fichier.is_file() and statique.resolve() in fichier.parents:
        return FileResponse(fichier)
    index = statique / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Interface non compilée."}, status_code=404)
