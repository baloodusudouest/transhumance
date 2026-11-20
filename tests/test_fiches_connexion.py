"""Fiches « Connexion » communes (contrat 3, socle 0.11.0) : forme de /api/maison/services, accès par session ou
ANNEAU_CLE seulement (jamais MAISON_JETON), « Vérifier » d'un service pas relié n'essaie rien, copies non retouchées
du module commun et de l'interface commune."""
from pathlib import Path

from app import maison
from app.config import APPLI
from tests.test_passage import MDP, monde, sans_variables_de_la_maison  # noqa: F401 — fixtures partagées
from tests.test_reglages import client, connecter  # noqa: F401 — fixtures partagées

RACINE = Path(__file__).resolve().parent.parent
CLE = "cle-anneau-de-test-1234567890"
IDS = ["immich", "immich-ml"]
CHAMPS = {"id", "nom", "genre", "cible", "etat", "lit", "ecrit", "reglage", "detail", "verifie_le", "guide",
          "derniere_ecriture", "gestes"}


def test_forme_du_contrat_3(client):
    connecter(client)
    r = client.get("/api/maison/services")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    corps = r.json()
    assert corps["contrat"] == 3 and corps["appli"] == APPLI and corps["simule"] is False
    assert [s["id"] for s in corps["services"]] == IDS
    for s in corps["services"]:
        assert set(s) == CHAMPS and s["lit"] and s["ecrit"] and s["etat"] in maison.ETATS_SERVICE
        assert len(s["gestes"]) <= 1
        if s["etat"] == "pas_relie":
            assert s["reglage"]


def test_acces_session_ou_cle_anneau(client, monkeypatch):
    assert client.get("/api/maison/services").status_code == 401
    monkeypatch.setenv("MAISON_JETON", "jeton-commun-de-test-12345")
    entete = {"Authorization": "Bearer jeton-commun-de-test-12345"}
    assert client.get("/api/maison/services", headers=entete).status_code == 401
    monkeypatch.setenv("ANNEAU_CLE", CLE)
    assert client.get("/api/maison/services", headers={"Authorization": f"Bearer {CLE}"}).status_code == 200
    assert client.get("/api/maison/services", headers={"Authorization": "Bearer mauvaise"}).status_code == 401


def test_verifier_inconnu_et_pas_relie(client):
    connecter(client)
    assert client.post("/api/maison/services/inconnu/verifier").status_code == 404
    for s in client.get("/api/maison/services").json()["services"]:
        if s["etat"] == "pas_relie":
            apres = client.post(f"/api/maison/services/{s['id']}/verifier").json()
            assert apres["etat"] == "pas_relie" and apres["verifie_le"] is None


def test_copies_communes_non_retouchees():
    assert maison.CONTRAT == 3 and maison.VERSION_SOCLE == "0.11.0"
    assert maison.empreinte_calculee() == maison.empreinte_ecrite()
    for nom in maison.FICHIERS_INTERFACE:
        ecrite, calculee = maison.empreinte_interface(RACINE / "frontend" / "src" / "lib" / "services" / nom)
        assert ecrite and ecrite == calculee, nom


# ---------------------------------------------------------------- propre à Transhumance (0.9.0)

def test_verifier_immich_et_pc_sans_rien_ecrire(client, monkeypatch):
    """Vérifier lit la version et la place d'Immich, puis les réglages de reconnaissance et un /ping par adresse :
    rien n'est écrit dans Immich, même en lecture seule. Le voyant du PC n'est vert que s'il travaille."""
    from app.passage import Transhumance
    im = client.monde[1]
    client.monde[0].cfg.lecture_seule = True
    avant = list(im.ecrits)
    connecter(client)
    fiches = {s["id"]: s for s in client.get("/api/maison/services").json()["services"]}
    assert fiches["immich"]["etat"] == "relie" and fiches["immich-ml"]["etat"] == "relie"
    assert fiches["immich"]["gestes"] == [] and fiches["immich-ml"]["guide"]["allumer"]
    assert "pas encore lues" in fiches["immich-ml"]["guide"]["reglages"][0]["valeur"]
    s = client.post("/api/maison/services/immich/verifier").json()
    assert s["etat"] == "repond" and s["detail"].startswith("Version 3.4.1 · ") and s["verifie_le"]
    monkeypatch.setattr(Transhumance, "_repond", staticmethod(lambda u: "pc-invente" not in u))   # PC éteint
    s = client.post("/api/maison/services/immich-ml/verifier").json()
    assert s["etat"] == "ne_repond_pas" and s["detail"].startswith("Le NAS fait la reconnaissance")
    reglages = {r["nom"]: r["valeur"] for r in s["guide"]["reglages"]}
    assert reglages["1. PC"].endswith("ne répond pas") and reglages["2. NAS"].endswith("c'est lui qui travaille")
    assert "Lecture du texte (OCR)" in reglages
    assert im.ecrits == avant


def test_la_lecture_de_l_ecran_migrer_sert_d_essai_au_pc(client, monkeypatch):
    from app.passage import Transhumance
    monkeypatch.setattr(Transhumance, "_repond", staticmethod(lambda u: True))
    connecter(client)
    assert client.get("/api/reconnaissance").json()["sur_pc"]
    pc = next(s for s in client.get("/api/maison/services").json()["services"] if s["id"] == "immich-ml")
    assert pc["etat"] == "repond" and pc["detail"].startswith("Le PC fait la reconnaissance")
