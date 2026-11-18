"""0.8.0 : santé des tâches de fond et copie de la base dans /health (socle 0.9.0)."""
from __future__ import annotations

import time

import pytest

from app import main, maison

from .test_passage import client, monde  # noqa: F401 (fixtures)


def _sante(c, **kw):
    """/health, en laissant à la boucle de copie le temps de lire son état de départ (tâche lancée au démarrage)."""
    for _ in range(50):
        j = c.get("/health", **kw).json()
        if j["copie_base"] and j["copie_base"]["bases"] == ["transhumance.db"]:
            return j
        time.sleep(0.02)
    return j


def test_health_porte_la_sante_des_taches_et_la_copie(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MAISON_JETON", "jeton-commun-essai")
    j = _sante(client)
    assert j["ok"] is True and j["version"] == main.__version__                  # rien d'existant ne change
    assert j["version_socle"] == "0.9.1"
    taches = {t["nom"]: t for t in j["taches"]}
    assert {"passage-auto", "lot", "inventaire", "copie-des-bases"} <= set(taches)
    assert taches["passage-auto"]["type"] == "reguliere" and taches["passage-auto"]["periode_s"] == 60
    assert taches["lot"]["type"] == "demande" and taches["inventaire"]["type"] == "demande"
    assert taches["copie-des-bases"]["periode_s"] == 86400
    assert j["copie_base"]["bases"] == ["transhumance.db"] and j["copie_base"]["le"] is None   # pas encore de nuit
    assert all("message" not in t for t in j["taches"])                          # sans jeton : pas de message
    avec = client.get("/health", headers={"Authorization": "Bearer jeton-commun-essai"}).json()
    assert all("message" in t for t in avec["taches"])
    assert all("message" not in t for t in client.get("/health", headers={"Authorization": "Bearer faux"}).json()["taches"])
    t = client.monde[0]
    assert client.post("/api/connexion", json={"mot_de_passe": t.cfg.password}).status_code == 200
    assert all("message" in t for t in client.get("/health").json()["taches"])  # session valide


class _Fin(BaseException):
    """Arrête la boucle automatique après un tour (elle tourne sans fin)."""


class _Horloge:
    """Remplace le module time dans main : le premier sommeil passe, le deuxième arrête la boucle."""
    def __init__(self):
        self.n = 0

    def sleep(self, _s):
        self.n += 1
        if self.n > 1:
            raise _Fin


class _FauxPassage:
    def __init__(self, choix=None, rate_choix=False, erreur_lot=None):
        self.choix, self.rate_choix, self.erreur_lot = choix, rate_choix, erreur_lot
        self.tache = {"en_cours": False, "erreur": None}
        self.passes = []

    def demande_suivante(self):
        if self.rate_choix:
            raise RuntimeError("base illisible")
        return self.choix

    def migrer(self, dossiers=None):
        self.passes.append(dossiers)
        self.tache["erreur"] = self.erreur_lot            # comme le vrai : l'erreur reste dans la tâche


def _un_tour(monkeypatch, faux):
    taches = maison.Taches()
    monkeypatch.setattr(maison, "TACHES", taches)
    taches.declarer("passage-auto", periode_s=60)
    taches.declarer("lot", type="demande")
    monkeypatch.setitem(main.ETAT, "t", faux)
    monkeypatch.setattr(main, "time", _Horloge())
    with pytest.raises(_Fin):
        main._boucle_auto()
    return {e["nom"]: e for e in taches.etat(avec_messages=True)}


def test_un_tour_rate_met_la_boucle_en_retard(monkeypatch):
    etat = _un_tour(monkeypatch, _FauxPassage(rate_choix=True))
    assert etat["passage-auto"]["etat"] == "en_retard" and etat["passage-auto"]["derniere_reussite"] is None
    assert etat["passage-auto"]["message"] == "RuntimeError: base illisible"
    assert etat["lot"]["etat"] == "jamais"


def test_un_lot_interrompu_passe_en_erreur_sans_bloquer_la_boucle(monkeypatch):
    faux = _FauxPassage(choix="Pellicule/2020/inventé", erreur_lot="Immich injoignable")
    etat = _un_tour(monkeypatch, faux)
    assert faux.passes == [["Pellicule/2020/inventé"]]
    assert etat["passage-auto"]["etat"] == "ok"                       # le choix a marché : la boucle vit
    assert etat["lot"]["etat"] == "erreur" and "Immich injoignable" in etat["lot"]["message"]
    faux.erreur_lot = None
    etat = _un_tour(monkeypatch, faux)
    assert etat["lot"]["etat"] == "ok"
