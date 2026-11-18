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
    ETAT.setdefault("sessions", Sessions(APPLI, cfg.password))
    # 0.4.0 : le passage automatique des dossiers demandés par Millésime (s'il est activé dans l'appli)
    if ETAT.get("boucle_auto", True):
        threading.Thread(target=_boucle_auto, daemon=True, name="auto").start()
    yield


def _boucle_auto() -> None:
    while True:
        time.sleep(60)
        try:
            ETAT["t"].passer_demande_suivante()
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
def sante():
    return {"ok": True, "version": __version__}


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
    t().inventaire()
    return arbre_vu(request)


@app.get("/api/bilan")
def bilan(chemin: str = "."):
    return t().bilan(chemin)


@app.get("/api/reconnaissance")
def reconnaissance():
    """0.1.5 : Immich fait-il travailler le PC ? Lecture seule, relue toutes les dix secondes par l'écran."""
    return t().reconnaissance()


@app.get("/api/connexions")
def connexions():
    cfg = ETAT["cfg"]
    im = t().immich()
    try:
        immich = {"ok": True, "version": im.version(), "place_libre": im.place_libre()}
    except ErreurImmich as exc:
        immich = {"ok": False, "erreur": str(exc)}
    finally:
        im.fermer()
    # 0.7.1 : plus de fichier d'essai écrit dans le dossier des photos (même en lecture seule) : on demande au système
    inscriptible = cfg.photos.is_dir() and os.access(cfg.photos, os.W_OK | os.X_OK)
    return {"immich": immich, "dossier": {"lisible": cfg.photos.is_dir(), "inscriptible": inscriptible,
                                          "exclus": t().exclus()},
            "version": __version__, "lecture_seule": cfg.lecture_seule, "lecture_seule_origine": cfg.lecture_seule_origine,
            "journal": [dict(l) for l in t().base.tous("SELECT le, quoi, detail FROM journal ORDER BY id DESC LIMIT 60")]}


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
            tr.migrer()
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
