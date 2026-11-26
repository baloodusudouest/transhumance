"""0.7.0 : réglages d'usage dans l'appli, sauvegarde chez l'Anneau et restauration. Sans réseau : le faux Anneau
passe par un monkeypatch de maison.lire_sauvegarde (argument lire=)."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app import main, maison
from app.base import Base
from app.passage import Transhumance

from .test_passage import MDP, monde, sans_variables_de_la_maison  # noqa: F401 — fixtures partagées


def nouvelle(cfg, transport=None):
    return Transhumance(cfg, Base(cfg.data / "t.db"), transport)


def journal(t):
    return [l["quoi"] for l in t.base.tous("SELECT quoi FROM journal ORDER BY id")]


# ---------------------------------------------------------------- reprise depuis la stack, une seule fois

def test_reprise_de_la_variable_au_premier_demarrage_puis_ignoree(monde, monkeypatch, tmp_path):
    import dataclasses
    t0 = monde[0]
    cfg = dataclasses.replace(t0.cfg, data=tmp_path / "neuf")
    monkeypatch.setenv("TRANSHUMANCE_EXCLUS", "Scans | Pense bete")              # l'ancienne forme, séparée par |
    t = nouvelle(cfg)
    assert t.reglages.repris == ["exclus"] and t.exclus() == ["Scans", "Pense bete"]
    assert "Réglage repris de la stack : exclus" in journal(t)
    assert json.loads((cfg.data / "reglages.json").read_text())["exclus"] == ["Scans", "Pense bete"]
    monkeypatch.setenv("TRANSHUMANCE_EXCLUS", "Autre")                           # second démarrage : variable ignorée
    t2 = nouvelle(cfg)
    assert t2.reglages.repris == [] and t2.exclus() == ["Scans", "Pense bete"]
    assert journal(t2).count("Réglage repris de la stack : exclus") == 1
    monkeypatch.delenv("TRANSHUMANCE_EXCLUS")
    t3 = nouvelle(dataclasses.replace(cfg, data=tmp_path / "vide"))              # sans variable : défaut (rien d'exclu)
    assert t3.exclus() == [] and t3.reglages.repris == []


def test_les_exclus_du_reglage_comptent_tout_de_suite(monde):
    t = monde[0]
    assert t.arbre()["noeuds"]["Scans"]["exclu"]
    t.changer_reglages({"exclus": ["Pense bete"]})
    n = t.arbre()["noeuds"]
    assert not n["Scans"]["exclu"] and n["Pense bete"]["exclu"] and n["Pense bete/Travaux"]["exclu"]
    t.regler_dossier(".", coche=True)
    assert not any(d.startswith("Pense bete") for d in t.a_migrer())


# ---------------------------------------------------------------- écran Réglages

@pytest.fixture()
def client(monde):
    t, im, ids, photos = monde
    main.ETAT.clear()
    main.ETAT.update(cfg=t.cfg, t=t, encodeur_nas=False)
    with TestClient(main.app) as c:
        c.monde = monde
        yield c
    main.ETAT.clear()


def connecter(client):
    assert client.post("/api/connexion", json={"mot_de_passe": MDP}).status_code == 200


def test_reglages_par_l_api(client):
    t = client.monde[0]
    for methode, chemin in (("get", "/api/reglages"), ("put", "/api/reglages"), ("get", "/api/restaurer"),
                            ("post", "/api/restaurer")):
        r = getattr(client, methode)(chemin, **({} if methode == "get" else {"json": {}}))
        assert r.status_code == 401, chemin                                       # session demandée
    connecter(client)
    assert client.get("/api/reglages").json() == {"exclus": ["Scans"], "auto_demandes": False}
    r = client.put("/api/reglages", json={"exclus": ["Scans", " Pense  bete ", "", "Scans"], "auto_demandes": True})
    assert r.status_code == 200 and r.json() == {"exclus": ["Scans", "Pense bete"], "auto_demandes": True}
    assert t.auto_demandes() and t.exclus() == ["Scans", "Pense bete"]
    assert {"Réglage changé : exclus", "Réglage changé : auto_demandes"} <= set(journal(t))
    assert client.get("/api/connexions").json()["dossier"]["exclus"] == ["Scans", "Pense bete"]
    for mauvais in ({"exclus": "Scans"}, {"exclus": [1]}, {"exclus": ["Pellicule/2020"]}, {"exclus": [".."]},
                    {"auto_demandes": "oui"}, {"auto_demandes": 1}, {"inconnu": 1},
                    {"exclus": ["Albums"], "auto_demandes": "non"}):
        r = client.put("/api/reglages", json=mauvais)
        assert r.status_code == 400 and r.json()["detail"], mauvais               # message clair
    assert client.get("/api/reglages").json() == {"exclus": ["Scans", "Pense bete"], "auto_demandes": True}  # rien changé


def test_reglages_changeables_en_lecture_seule_sans_rien_ecrire_chez_immich(client):
    import dataclasses
    t, im = client.monde[0], client.monde[1]
    t.cfg = main.ETAT["cfg"] = dataclasses.replace(t.cfg, lecture_seule=True, lecture_seule_origine="appli")
    connecter(client)
    avant = list(im.ecrits)
    assert client.put("/api/reglages", json={"exclus": []}).status_code == 200
    assert im.ecrits == avant


# ---------------------------------------------------------------- GET /externe/sauvegarde (l'Anneau)

def test_sauvegarde_seulement_avec_le_jeton_commun(client, monkeypatch):
    t = client.monde[0]
    assert client.get("/externe/sauvegarde").status_code == 404                  # aucun jeton posé : fermée
    monkeypatch.setenv("TRANSHUMANCE_JETON_MILLESIME", "ancien")
    assert client.get("/externe/sauvegarde", headers={"Authorization": "Bearer ancien"}).status_code == 404
    monkeypatch.setenv("MAISON_JETON", "jeton-commun")
    assert client.get("/externe/sauvegarde").status_code == 401
    assert client.get("/externe/sauvegarde", headers={"Authorization": "Bearer ancien"}).status_code == 401
    connecter(client)
    assert client.get("/externe/sauvegarde").status_code == 401                  # une session n'ouvre pas cette porte
    r = client.get("/externe/sauvegarde", headers={"Authorization": "Bearer jeton-commun"})
    assert r.status_code == 200
    s = r.json()
    assert s["contrat"] == 1 and s["appli"] == "transhumance" and s["version"] == main.__version__
    assert s["reglages"] == {"exclus": ["Scans"], "auto_demandes": False}
    texte = r.text
    for interdit in ("jeton-commun", MDP, t.cfg.immich_cle, t.cfg.racine_immich, str(t.cfg.photos), str(t.cfg.data)):
        assert interdit not in texte, interdit
    sante = client.get("/health").json()                                         # 0.8.0 : + santé des tâches
    assert {k: sante[k] for k in ("ok", "version")} == {"ok": True, "version": main.__version__}   # inchangé
    assert set(sante) == {"ok", "version", "version_socle", "taches", "copie_base"}


def test_sauvegarde_n_emporte_ni_secret_ni_cle_exclue(client, monkeypatch):
    t = client.monde[0]
    monkeypatch.setenv("MAISON_JETON", "jeton-commun")
    vrai = t.reglages_tout
    monkeypatch.setattr(t, "reglages_tout", lambda: {**vrai(), "immich_cle": "cle", "racine_immich": "/r",
                                                     "photos": "/p", "password": "x", "jeton_ha": "y"})
    s = client.get("/externe/sauvegarde", headers={"Authorization": "Bearer jeton-commun"}).json()
    assert set(s["reglages"]) == {"exclus", "auto_demandes"}
    assert all(not maison.est_secret(k) for k in s["reglages"])


# ---------------------------------------------------------------- Restaurer

class FauxAnneau:
    def __init__(self, sauvegardes: dict | None = None, panne: Exception | None = None):
        self.sauvegardes = sauvegardes or {}
        self.panne = panne
        self.vus: list[tuple[str, str]] = []

    def lire(self, adresse, jeton):
        self.vus.append((adresse, jeton))
        if self.panne:
            raise self.panne
        if "?le=" not in adresse:
            return {"dates": sorted(self.sauvegardes, reverse=True)}
        le = adresse.rsplit("?le=", 1)[1]
        if le not in self.sauvegardes:
            raise urllib.error.HTTPError(adresse, 404, "absent", {}, io.BytesIO(b""))
        return {"le": le, "version": "0.7.0", "reglages": self.sauvegardes[le]}


LIRE_SAUVEGARDE = maison.lire_sauvegarde                    # le vrai, gardé avant tout monkeypatch


def brancher(monkeypatch, anneau):
    monkeypatch.setattr(maison, "lire_sauvegarde", lambda appli, le="": LIRE_SAUVEGARDE(appli, le, lire=anneau.lire))


def test_restaurer_liste_differences_et_application(client, monkeypatch):
    t = client.monde[0]
    monkeypatch.setenv("MAISON_JETON", "jeton-commun")
    anneau = FauxAnneau({"2026-11-14": {"exclus": ["Scans", "Pense bete"], "auto_demandes": True, "inconnue": 3,
                                        "immich_cle": "jamais"},
                         "2026-11-15": {"exclus": ["Scans"], "auto_demandes": False}})
    brancher(monkeypatch, anneau)
    connecter(client)
    assert client.get("/api/restaurer").json() == {"dates": ["2026-11-15", "2026-11-14"]}
    assert anneau.vus[0] == ("http://anneau:8094/externe/sauvegardes/transhumance", "jeton-commun")
    v = client.get("/api/restaurer", params={"le": "2026-11-14"}).json()
    assert v["le"] == "2026-11-14" and v["version"] == "0.7.0"
    assert v["differences"] == [{"cle": "auto_demandes", "actuel": False, "sauve": True},
                                {"cle": "exclus", "actuel": ["Scans"], "sauve": ["Scans", "Pense bete"]}]
    assert client.get("/api/restaurer", params={"le": "2026-11-15"}).json()["differences"] == []
    assert client.post("/api/restaurer", json={"le": "2026-11-15"}).status_code == 404       # rien à restaurer
    r = client.post("/api/restaurer", json={"le": "2026-11-14"})
    assert r.status_code == 200 and r.json() == {"exclus": ["Scans", "Pense bete"], "auto_demandes": True}
    assert "Réglage restauré (sauvegarde du 2026-11-14) : exclus" in journal(t)
    assert client.get("/api/restaurer", params={"le": "2026-11-13"}).status_code == 404       # date sans sauvegarde
    assert client.get("/api/restaurer", params={"le": "hier"}).status_code == 400


def test_restaurer_permis_en_lecture_seule(client, monkeypatch):
    import dataclasses
    t, im = client.monde[0], client.monde[1]
    t.cfg = main.ETAT["cfg"] = dataclasses.replace(t.cfg, lecture_seule=True, lecture_seule_origine="maison")
    brancher(monkeypatch, FauxAnneau({"2026-11-14": {"exclus": []}}))
    connecter(client)
    avant = list(im.ecrits)
    assert client.post("/api/restaurer", json={"le": "2026-11-14"}).json()["exclus"] == []
    assert im.ecrits == avant


def test_restaurer_anneau_injoignable_ou_vide(client, monkeypatch):
    connecter(client)
    brancher(monkeypatch, FauxAnneau(panne=OSError("pas d'Anneau")))
    for r in (client.get("/api/restaurer"), client.get("/api/restaurer", params={"le": "2026-11-14"}),
              client.post("/api/restaurer", json={"le": "2026-11-14"})):
        assert r.status_code == 503 and "injoignable" in r.json()["detail"]
    brancher(monkeypatch, FauxAnneau({}))
    r = client.get("/api/restaurer")
    assert r.status_code == 404 and "pas de sauvegarde" in r.json()["detail"]
    assert client.get("/api/reglages").json() == {"exclus": ["Scans"], "auto_demandes": False}    # rien n'a bougé
