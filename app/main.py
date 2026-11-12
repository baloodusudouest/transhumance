"""Transhumance : interface et adresses. Une seule porte : le mot de passe commun.

Routes : /health (publique), /api/session, /api/connexion, /api/deconnexion, puis l'arbre, le lot,
le bilan, la suppression et le retour arrière."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .auth import DUREE, Sessions
from .base import Base
from .config import APPLI, charger
from .immich import ErreurImmich
from .passage import Refus, Transhumance

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
ETAT: dict = {}


@asynccontextmanager
async def cycle(app: FastAPI):
    cfg = ETAT.get("cfg") or charger()
    ETAT.setdefault("cfg", cfg)
    ETAT.setdefault("t", Transhumance(cfg, Base(cfg.data / "transhumance.db"), ETAT.get("transport")))
    ETAT.setdefault("sessions", Sessions(APPLI, cfg.password))
    yield


app = FastAPI(title=APPLI, version=__version__, lifespan=cycle, docs_url=None, redoc_url=None)


def t() -> Transhumance:
    return ETAT["t"]


@app.middleware("http")
async def garde(request: Request, appel):
    chemin = request.url.path
    if chemin.startswith("/api/"):
        libre = chemin == "/api/session" or (chemin == "/api/connexion" and request.method == "POST")
        s = ETAT["sessions"]
        if not libre and not s.valide(request.cookies.get(s.cookie)):
            return JSONResponse({"detail": "Connexion nécessaire."}, status_code=401)
    reponse = await appel(request)
    if chemin.startswith("/api/"):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.exception_handler(Refus)
async def _refus(_: Request, exc: Refus):
    return JSONResponse({"detail": str(exc)}, status_code=exc.code)


@app.exception_handler(ErreurImmich)
async def _immich(_: Request, exc: ErreurImmich):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.get("/health")
def sante():
    return {"ok": True, "version": __version__}


@app.get("/api/session")
def session(request: Request):
    s = ETAT["sessions"]
    return {"connecte": s.valide(request.cookies.get(s.cookie)), "version": __version__,
            "lecture_seule": ETAT["cfg"].lecture_seule}


@app.post("/api/connexion")
async def connexion(corps: dict = Body(...)):
    s = ETAT["sessions"]
    if ETAT["cfg"].attente_connexion:
        await asyncio.sleep(s.attente())
    if not s.verifier_mot_de_passe(str(corps.get("mot_de_passe", ""))):
        raise HTTPException(401, "Mot de passe incorrect.")
    r = JSONResponse({"ok": True})
    r.set_cookie(s.cookie, s.creer(), max_age=DUREE, httponly=True, samesite="strict")
    return r


@app.post("/api/deconnexion")
def deconnexion():
    s = ETAT["sessions"]
    s.generation += 1
    r = JSONResponse({"ok": True})
    r.delete_cookie(s.cookie)
    return r


# ---------------------------------------------------------------- lecture

@app.get("/api/arbre")
def arbre():
    return t().arbre()


@app.post("/api/inventaire")
def inventaire():
    """Relit Immich et le dossier des photos. N'écrit rien dans Immich ni dans le dossier."""
    t().inventaire()
    return t().arbre()


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
    essai = cfg.photos / ".transhumance-essai"
    try:
        essai.write_text("ok")
        essai.unlink()
        inscriptible = True
    except OSError:
        inscriptible = False
    return {"immich": immich, "dossier": {"lisible": cfg.photos.is_dir(), "inscriptible": inscriptible,
                                          "exclus": list(cfg.exclus)},
            "version": __version__, "lecture_seule": cfg.lecture_seule,
            "journal": [dict(l) for l in t().base.tous("SELECT le, quoi, detail FROM journal ORDER BY id DESC LIMIT 60")]}


# ---------------------------------------------------------------- gestes

@app.post("/api/dossier")
def regler_dossier(corps: dict = Body(...)):
    chemin = str(corps.get("chemin", ""))
    if not chemin:
        raise HTTPException(422, "Dossier manquant.")
    t().regler_dossier(chemin, album=corps.get("album"), coche=corps.get("coche"), defaut=bool(corps.get("defaut")), vider=bool(corps.get("vider")))
    return t().arbre()


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
