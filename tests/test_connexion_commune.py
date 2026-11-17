"""La connexion commune : le cookie posé par l'Anneau ouvre l'appli si le mot de passe est le même."""
import hashlib
import hmac
import time

from app.auth import COMMUN, Sessions

MDP = "essai-essai-essai"


def cookie(mot_de_passe, expire, generation=0):
    cle = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), b"maison-session|", 200_000)   # contrat commun depuis le 17/11/2026
    corps = f"{generation}.{expire}"            # « génération.expiration.signature » depuis le 18/11/2026
    return f"{corps}.{hmac.new(cle, corps.encode(), hashlib.sha256).hexdigest()}"


def test_le_cookie_commun_ouvre_l_appli():
    s = Sessions("essai", MDP)
    dans_une_heure = int(time.time()) + 3600
    assert s.connecte({COMMUN: cookie(MDP, dans_une_heure)})
    assert s.connecte({COMMUN: s.creer_commun()})
    assert not s.connecte({})
    assert not s.connecte({COMMUN: cookie("un-autre-mot-de-passe", dans_une_heure)})       # autre mot de passe : refusé
    assert not s.connecte({COMMUN: cookie(MDP, int(time.time()) - 5)})                     # périmé : refusé
    assert not s.connecte({COMMUN: cookie(MDP, dans_une_heure).replace(str(dans_une_heure), str(dans_une_heure + 9))})
    for faux in ("", ".", "abc", "123", "123.", ".abc", "1.2.3"):
        assert not s.connecte({COMMUN: faux})


def test_se_deconnecter_dans_l_anneau_revoque_le_cookie_commun(monkeypatch):
    """Audit du 17/11/2026 : la génération commune tenue par l'Anneau change, les cookies communs d'avant ne valent plus."""
    from app import maison
    s = Sessions("essai", MDP)
    dans_une_heure = int(time.time()) + 3600
    monkeypatch.setattr(maison, "generation_commune", lambda: 3)
    assert s.connecte({COMMUN: cookie(MDP, dans_une_heure, 3)})
    assert not s.connecte({COMMUN: cookie(MDP, dans_une_heure, 2)})                        # d'avant la déconnexion
    assert not s.connecte({COMMUN: cookie(MDP, dans_une_heure, 2).replace("2.", "3.", 1)})  # génération retouchée
    assert s.connecte({COMMUN: s.creer_commun()})                                           # nouveau cookie : génération 3
    monkeypatch.setattr(maison, "generation_commune", lambda: None)                         # Anneau injoignable
    assert s.connecte({COMMUN: cookie(MDP, dans_une_heure, 2)})
