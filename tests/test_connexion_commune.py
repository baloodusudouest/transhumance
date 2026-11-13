"""La connexion commune : le cookie posé par l'Anneau ouvre l'appli si le mot de passe est le même."""
import hashlib
import hmac
import time

from app.auth import COMMUN, Sessions

MDP = "essai-essai-essai"


def cookie(mot_de_passe, expire):
    cle = hashlib.sha256(b"maison-session|" + mot_de_passe.encode()).digest()
    return f"{expire}.{hmac.new(cle, str(expire).encode(), hashlib.sha256).hexdigest()}"


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
