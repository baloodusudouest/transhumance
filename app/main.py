"""Transhumance : interface et adresses. Une seule porte : le mot de passe commun.

Routes : /health (publique), /api/session, /api/connexion, /api/deconnexion, puis l'arbre, le lot,
le bilan, la suppression et le retour arrière ; 0.7.0 : /api/reglages, /api/restaurer, /externe/sauvegarde.
0.10.0 : /api/encodage, /api/sas/remettre, et la porte de l'encodeur du PC /calcul/… (jeton TRANSHUMANCE_JETON_CALCUL)."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import threading
import re
import time
import urllib.error
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__, maison, video
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
    maison.TACHES.declarer(TACHE_ENCODEUR, periode_s=ENCODEUR_S, type="reguliere")
    # 0.4.0 : le passage automatique des dossiers demandés par Millésime (s'il est activé dans l'appli)
    if ETAT.get("boucle_auto", True):
        threading.Thread(target=_boucle_auto, daemon=True, name="auto").start()
    # 0.10.0 : l'encodeur du NAS (remux toujours ; réencodage par la puce vidéo Intel quand le PC est absent) et le sas
    if ETAT.get("encodeur_nas", True):
        threading.Thread(target=_boucle_encodeur, daemon=True, name="encodeur-nas").start()
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
TACHE_ENCODEUR = "encodeur-nas"    # 0.10.0 : met en MP4 les vidéos de la file que le PC ne prend pas ; vide le sas
ENCODEUR_S = 20
SAS_S = 3600                       # le sas est regardé une fois par heure


class _LotInterrompu(Exception):
    """0.8.0 : le lot s'est arrêté en route (erreur déjà notée par migrer dans la tâche, montrée à l'écran)."""


def _lot_suivi(dossiers: list[str] | None = None, origine: str | None = None, verrou_pris: bool = False) -> None:
    """Un lot, suivi dans /health. migrer garde pour lui l'erreur d'un lot interrompu (dans t().tache["erreur"]) :
    elle est relancée ici pour que le tour compte comme raté. 0.9.3 : le verrou du lot, pris par l'appelant, est passé
    à migrer qui le rend ; s'il n'a pas pu y arriver, il est rendu ici."""
    remis = False                                     # dès que migrer est appelé, c'est lui qui rend le verrou
    try:
        with maison.TACHES.tour(TACHE_LOT):
            remis = True
            t().migrer(dossiers, origine=origine, verrou_pris=verrou_pris)
            if t().tache.get("erreur"):
                raise _LotInterrompu(t().tache["erreur"])
    finally:
        if verrou_pris and not remis:
            t().verrou_lot.release()


def _boucle_auto() -> None:
    while True:
        time.sleep(AUTO_S)
        try:
            # 0.8.0 : le choix (rapide) est le tour de la boucle ; le passage (long) est suivi à part, comme un lot :
            # un passage de plusieurs heures ne fait pas croire à une boucle bloquée
            # 0.9.3 : la boucle prend le verrou du lot avant de choisir : si « Faire passer » tourne, elle attend le
            # tour suivant, et un clic pendant qu'elle choisit est refusé (409) au lieu de lancer un second lot
            tr = ETAT["t"]
            if not tr.verrou_lot.acquire(blocking=False):
                continue
            try:
                with maison.TACHES.tour(TACHE_AUTO):
                    chemin = tr.demande_suivante()
            except BaseException:
                tr.verrou_lot.release()
                raise
            if chemin:
                _lot_suivi([chemin], origine="Millésime", verrou_pris=True)
                continue
            # 0.10.0 : les vidéos mises en MP4 partent toutes seules (dossiers cochés et lancés par « Faire passer »)
            try:
                prets = tr.dossiers_a_envoyer() if not tr.tache.get("en_cours") else []
            except BaseException:
                tr.verrou_lot.release()
                raise
            if not prets:
                tr.verrou_lot.release()
                continue
            _lot_suivi(prets, origine="l'encodage des vidéos", verrou_pris=True)
        except _LotInterrompu:
            pass                  # comme avant : l'erreur est dans la tâche, montrée à l'écran, et déjà au journal
        except Exception as exc:  # noqa: BLE001 — l'erreur est dans la tâche, montrée à l'écran
            log.warning("Passage automatique interrompu : %s", exc)


def _boucle_encodeur() -> None:
    """0.10.0 : essai de la puce vidéo du NAS au démarrage, puis un tour toutes les 20 s (enchaîné tant qu'il y a du
    travail) ; le sas est vidé une fois par heure."""
    tr = ETAT["t"]
    tr.materiel_nas = {**video.essai_vaapi(), "mode": "vaapi"}
    tr.base.noter("Puce vidéo du NAS essayée", {"ok": tr.materiel_nas["ok"], "pilote": tr.materiel_nas.get("pilote")})
    dernier_sas = 0.0
    while True:
        try:
            with maison.TACHES.tour(TACHE_ENCODEUR):
                if time.monotonic() - dernier_sas > SAS_S:
                    dernier_sas = time.monotonic()
                    tr.vider_sas()
                travaille = tr.encodeur_nas_tour()
        except Exception as exc:  # noqa: BLE001 — suivi dans /health, au journal ; la boucle continue
            log.warning("Encodeur du NAS : %s", exc)
            travaille = False
        if not travaille:
            time.sleep(ENCODEUR_S)


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
    if chemin.startswith("/calcul/"):
        # 0.10.0 : l'encodeur du PC (comme le calculateur de Millésime). Jeton propre à Transhumance ; absent : fermé.
        attendu = os.environ.get("TRANSHUMANCE_JETON_CALCUL", "")
        if not attendu:
            return JSONResponse({"detail": "Adresse fermée."}, status_code=404)
        propose = maison.jeton_propose(request.headers)
        if not propose or not hmac.compare_digest(propose.encode(), attendu.encode()):
            return JSONResponse({"detail": "Jeton manquant ou invalide."}, status_code=401)
    if chemin.startswith("/api/"):
        libre = chemin == "/api/session" or (chemin == "/api/connexion" and request.method == "POST")
        s = ETAT["sessions"]
        if not libre and not s.connecte(request.cookies):
            return JSONResponse({"detail": "Connexion nécessaire."}, status_code=401)
    reponse = await appel(request)
    if chemin.startswith(("/api/", "/externe/", "/calcul/")):
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
    """Réglages : journal et dossier des photos. 0.10.0 : la partie « immich » (annoncée en 0.9.0) est retirée ;
    l'état d'Immich est dans l'écran Connexion (/api/maison/services)."""
    cfg = ETAT["cfg"]
    # 0.7.1 : plus de fichier d'essai écrit dans le dossier des photos (même en lecture seule) : on demande au système
    inscriptible = cfg.photos.is_dir() and os.access(cfg.photos, os.W_OK | os.X_OK)
    return {"dossier": {"lisible": cfg.photos.is_dir(), "inscriptible": inscriptible,
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


def _essai_encodeur():
    e = t().etat_encodage()
    pc = e["pc"]
    if not os.environ.get("TRANSHUMANCE_JETON_CALCUL"):
        return False, "TRANSHUMANCE_JETON_CALCUL n'est pas posé : la porte de l'encodeur est fermée."
    if pc["actif"]:
        return True, f"Le PC ({pc['machine'] or 'sans nom'}) est là · {e['file']['attente']} vidéo(s) en attente."
    nas = "la puce vidéo du NAS encode à sa place" if e["nas"]["ok"] else "le NAS ne peut pas réencoder : les vidéos attendent le PC"
    return False, ("Le PC n'a jamais fait signe" if not pc["vu_le"] else f"Le PC n'a pas fait signe depuis le {pc['vu_le'][:16].replace('T', ' ')}") + f" ; {nas}."


def _guide_encodeur() -> dict:
    e = t().etat_encodage()
    return {
        "reglages": [
            {"nom": "Porte de l'encodeur", "valeur": "ouverte (jeton posé)" if os.environ.get("TRANSHUMANCE_JETON_CALCUL") else "fermée : TRANSHUMANCE_JETON_CALCUL absent"},
            {"nom": "PC", "valeur": (f"{e['pc']['machine'] or 'sans nom'}, vu le {e['pc']['vu_le']}" if e["pc"]["vu_le"] else "jamais vu")},
            {"nom": "Puce vidéo du NAS", "valeur": (f"prête (pilote {e['nas']['pilote']})" if e["nas"]["ok"] else (e["nas"]["raison"] or "pas prête"))},
            {"nom": "File", "valeur": f"{e['file']['attente']} en attente · {e['file']['pris']} en cours · {e['file']['faits']} faites · {e['file']['erreurs']} en erreur"},
        ],
        "allumer": [
            "Allumer le PC et ouvrir Docker Desktop : le conteneur transhumance_encodeur redémarre tout seul "
            "(restart: unless-stopped, fichier pc/encodeur.yml du dépôt) et demande une vidéo toutes les minutes.",
            "PC éteint : la puce vidéo Intel du NAS réencode à sa place, si elle a réussi son essai ; sinon les vidéos "
            "attendent le PC. Les changements d'enveloppe (remux) se font toujours sur le NAS.",
            "Après la migration : « docker compose -f encodeur.yml down » sur le PC.",
        ],
        "pannes": [
            {"signe": "« Le PC n'a jamais fait signe » ou « pas fait signe depuis… »",
             "faire": ["Docker Desktop est-il ouvert, le conteneur transhumance_encodeur lancé ?",
                       "Sa fin de journal dit s'il joint Transhumance (adresse TRANSHUMANCE_URL du .env) et si le jeton est accepté."],
             "commandes": ["docker ps --filter name=transhumance_encodeur", "docker logs --tail 30 transhumance_encodeur"]},
            {"signe": "« Jeton manquant ou invalide » dans le journal de l'encodeur",
             "faire": ["Le TRANSHUMANCE_JETON_CALCUL du .env du PC doit être celui de la stack homelab (Portainer)."],
             "commandes": []},
            {"signe": "« Le NAS ne peut pas réencoder »",
             "faire": ["Le conteneur transhumance n'a pas la puce vidéo (/dev/dri) : ligne « devices » de la stack, et "
                       "pilote i915 chargé sur le NAS (tâche planifiée au démarrage, voir le coffre). Sans elle, seuls "
                       "les changements d'enveloppe se font sur le NAS."],
             "commandes": []},
        ],
        "une_fois": [
            {"texte": "Copier pc/encodeur.yml et pc/encodeur.env.exemple (dépôt transhumance) dans un dossier du PC (par "
                      "exemple C:\transhumance), renommer l'exemple en .env et le compléter (adresse de Transhumance, "
                      "jeton de la stack), puis, avec Docker Desktop ouvert :",
             "commande": "docker compose -f encodeur.yml up -d"},
        ],
        "terminal": "Les commandes se tapent dans PowerShell sur le PC (menu Démarrer › PowerShell).",
        "note": "La carte graphique AMD n'est pas visible depuis Docker Desktop : le PC encode avec son processeur. "
                "Ce guide n'a jamais été essayé sur la vraie installation.",
    }


SERVICES.ajouter(
    "encodeur-pc", "Encodeur du PC (vidéos)",
    lit="L'encodeur du PC vient chercher les vidéos à réencoder (WMV, anciens formats), une à la fois, et renvoie un MP4.",
    ecrit="Rien chez lui : le MP4 est rangé dans le dossier de données de Transhumance, puis envoyé à Immich par Transhumance.",
    regle=lambda: bool(os.environ.get("TRANSHUMANCE_JETON_CALCUL")),
    reglage="TRANSHUMANCE_JETON_CALCUL",
    essai=_essai_encodeur, guide=_guide_encodeur)
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
    if t().tache["en_cours"] or t().verrou_lot.locked():
        # 0.9.3 : un lot lit ses dossiers et leurs albums au départ ; les changer pendant qu'il tourne n'aurait aucun effet
        raise HTTPException(409, "Un lot est en cours : les cases et les albums se changent quand il est fini.")
    t().regler_dossier(chemin, album=corps.get("album"), coche=corps.get("coche"), defaut=bool(corps.get("defaut")), vider=bool(corps.get("vider")))
    return arbre_vu(request)


@app.get("/api/lot")
def lot():
    dossiers = t().a_migrer()
    return {"dossiers": dossiers, **(t().verifier_place(dossiers) if dossiers else {"besoin": 0, "libre": 0, "possible": True})}


@app.post("/api/migrer")
def migrer(corps: dict | None = Body(None)):
    """Lance le passage des dossiers cochés, en tâche de fond. Aucune suppression.
    0.9.3 : l'écran redonne la liste des dossiers qu'il montrait (« dossiers ») ; si les cases ont changé depuis
    (écran périmé, case en cours d'enregistrement), rien ne part (409). Le lot fait passer exactement cette liste."""
    tr = t()
    tr.exiger_ecriture()
    vus = (corps or {}).get("dossiers")
    if not isinstance(vus, list) or not all(isinstance(d, str) for d in vus):
        raise HTTPException(422, "La liste des dossiers affichés manque : recharge la page.")
    if tr.tache["en_cours"] or not tr.verrou_lot.acquire(blocking=False):
        raise HTTPException(409, "Un lot est déjà en cours.")
    try:
        dossiers = tr.a_migrer()
        if not dossiers:
            raise HTTPException(422, "Aucun dossier coché.")
        if sorted(vus) != dossiers:
            raise HTTPException(409, "Les cases ont changé depuis l'affichage : relis la liste avant de faire passer.")
        if not tr.verifier_place(dossiers)["possible"]:
            raise HTTPException(409, "Pas assez de place libre pour ce lot.")
    except BaseException:
        tr.verrou_lot.release()
        raise
    tr.tache.update(en_cours=True, erreur=None, message="Démarrage…", fait=0, total=0, origine=None, dossiers=len(dossiers))

    def faire():
        try:
            _lot_suivi(dossiers, verrou_pris=True)   # 0.8.0 : suivi dans /health ; 0.9.3 : la liste vérifiée, figée
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


# ---------------------------------------------------------------- 0.10.0 : vidéos (écran) et encodeur du PC (jeton)

@app.get("/api/encodage")
def encodage():
    return t().etat_encodage()


@app.post("/api/sas/remettre")
def remettre(corps: dict = Body(...)):
    return t().remettre(str(corps.get("ancien", "")))


@app.post("/calcul/signal")
def calcul_signal(corps: dict | None = Body(None)):
    t().pc_vu((corps or {}).get("machine", ""))
    return {"ok": True}


@app.post("/calcul/prendre")
def calcul_prendre(corps: dict | None = Body(None)):
    """Le PC demande une vidéo à réencoder (jamais les remux, faits sur le NAS). 204 : rien à faire."""
    tr = t()
    tr.pc_vu((corps or {}).get("machine", ""))
    job = tr.prendre("pc", (corps or {}).get("machine", ""), ("encode",))
    return job if job else Response(status_code=204)


@app.get("/calcul/fichier/{ident}")
def calcul_fichier(ident: int):
    f = t().fichier_a_encoder(ident, "pc")
    if not f.is_file():
        raise HTTPException(404, "L'original n'est plus dans le dossier.")
    return FileResponse(f, media_type="application/octet-stream", filename=f.name)


@app.post("/calcul/vie/{ident}")
def calcul_vie(ident: int, corps: dict | None = Body(None)):
    t().pc_vu((corps or {}).get("machine", ""))
    return {"continuer": t().vie(ident, (corps or {}).get("avance"), "pc")}


@app.post("/calcul/rendre/{ident}")
async def calcul_rendre(ident: int, request: Request, nom: str = "video.mp4", grossi: bool = False, leger: bool = False):
    """Le MP4 arrive en flux dans le corps ; écrit à côté (.part), puis renommé et vérifié."""
    tr = t()
    tr._encodage(ident, "pc")
    cible = tr.chemin_produit(ident, nom)
    cible.parent.mkdir(parents=True, exist_ok=True)
    temp = cible.with_name(cible.name + ".part")
    try:
        with temp.open("wb") as f:
            async for bloc in request.stream():
                f.write(bloc)
        os.replace(temp, cible)
    finally:
        temp.unlink(missing_ok=True)
    tr.pc_vu()
    await asyncio.to_thread(tr.finir, ident, cible, {"grossi": grossi, "leger": leger, "materiel": "processeur du PC"}, "pc")
    return {"ok": True}


@app.post("/calcul/erreur/{ident}")
def calcul_erreur(ident: int, corps: dict | None = Body(None)):
    t().echouer(ident, str((corps or {}).get("message", "erreur sans message"))[:400], "pc")
    return {"ok": True}


@app.get("/{chemin:path}")
def interface(chemin: str):
    if chemin.startswith(("api/", "calcul/")):
        raise HTTPException(404, "Adresse inconnue.")
    statique = ETAT["cfg"].static
    fichier = (statique / chemin).resolve() if chemin else None
    if fichier and fichier.is_file() and statique.resolve() in fichier.parents:
        return FileResponse(fichier)
    index = statique / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Interface non compilée."}, status_code=404)
