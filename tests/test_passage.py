"""Transhumance contre un faux Immich et un dossier de photos inventé.

Le test qui compte le plus : ce que « Supprimer » supprime, et ce qu'il ne supprime jamais."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.base import Base
from app.config import Config
from app.passage import Refus, Transhumance

from .faux_immich import CLE, RACINE, FauxImmich

MDP = "mot-de-passe-essai"


def poser(dossier, rel, contenu=None):
    p = dossier / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu if contenu is not None else ("photo " + rel).encode() * 50)
    return rel


@pytest.fixture()
def monde(tmp_path):
    photos = tmp_path / "photos"
    im = FauxImmich(photos)
    fichiers = {
        "fete1": poser(photos, "Pellicule/2020/2020-05-01 Fête au jardin/IMG_0001.jpg"),
        "fete2": poser(photos, "Pellicule/2020/2020-05-01 Fête au jardin/IMG_0002.jpg"),
        "jour": poser(photos, "Pellicule/2020/2020-06-10/IMG_0003.jpg"),
        "italie": poser(photos, "Albums/Voyages/Italie 2019/DSC_1.jpg"),
        "pense": poser(photos, "Pense bete/Travaux/note.jpg"),
        "scan": poser(photos, "Scans/Boîte 1/scan1.jpg"),
        "anim_photo": poser(photos, "Pellicule/2021/2021-01-01 Neige/IMG_0100.heic"),
        "anim_video": poser(photos, "Pellicule/2021/2021-01-01 Neige/IMG_0100.mov"),
    }
    poser(photos, "Pellicule/2020/2020-05-01 Fête au jardin/pas-dans-immich.jpg")       # inconnu d'Immich
    poser(photos, "Pellicule/2020/2020-05-01 Fête au jardin/IMG_0001.jpg.xmp", b"<x/>")
    ids = {k: im.externe(rel) for k, rel in fichiers.items()}
    im.photos[ids["anim_photo"]]["livePhotoVideoId"] = ids["anim_video"]
    im.photos[ids["anim_video"]]["visibility"] = "hidden"
    im.visage(ids["fete1"], "pers-a", 100)                      # reconnue seule
    im.visage(ids["fete1"], "pers-b", 500, "timide")            # détectée mais pas rattachée
    im.visage(ids["fete2"], "pers-a", 100, "manuel")            # posée à la main : la détection ne la retrouve pas
    im.visage(ids["fete2"], None, 600)                          # visage sans nom : rien à garder
    im.albums["alb-vieux"] = {"nom": "Ancien album", "ids": {ids["fete1"]}}
    im.photos[ids["fete1"]]["tags"] = [{"id": "tag-1", "value": "Famille"}]
    im.photos[ids["fete2"]]["exifInfo"]["dateTimeOriginal"] = "2020-05-02T09:00:00.000Z"   # date corrigée dans Immich
    im.photos[ids["fete2"]]["exifInfo"]["description"] = "Sous le tilleul"
    cfg = Config(password=MDP, immich_url="http://immich", immich_cle=CLE, photos=photos, racine_immich=RACINE,
                 data=tmp_path / "data", static=tmp_path / "static", exclus=("Scans",), attente_connexion=False, attente_files=0)
    t = Transhumance(cfg, Base(cfg.data / "t.db"), im.transport())
    t.inventaire()
    return t, im, ids, photos


def etats(t):
    return {l["rel"].rsplit("/", 1)[-1]: l["etat"] for l in t.base.tous("SELECT rel, etat FROM photos")}


def test_inventaire_et_arbre(monde):
    t, im, ids, photos = monde
    a = t.arbre()
    n = a["noeuds"]
    assert a["inventaire"]["photos"] == 8 and a["inventaire"]["inconnus"] == 1
    assert n["."]["photos"] == 7 and n["."]["videos"] == 0            # la partie vidéo d'une photo animée n'est pas comptée à part
    assert n["Pellicule/2020"]["photos"] == 3 and n["Pellicule/2020"]["inconnus"] == 1
    assert n["Pellicule"]["enfants"] == ["Pellicule/2020", "Pellicule/2021"]
    assert n["Scans"]["exclu"] and not n["Albums"]["exclu"]
    assert im.ecrits == []                                             # l'inventaire n'écrit rien dans Immich


def test_noms_d_albums_proposes(monde):
    t = monde[0]
    assert t.album_propose("Pellicule/2020/2020-05-01 Fête au jardin") == "2020-05-01 Fête au jardin"
    assert t.album_propose("Pellicule/2020/2020-06-10") is None        # un dossier qui n'est qu'une date : pas d'album
    assert t.album_propose("Pellicule/2020") is None
    assert t.album_propose("Albums/Voyages/Italie 2019") == "Voyages – Italie 2019"
    assert t.album_propose("Pense bete/Travaux") == "Pense bete – Travaux"
    t.regler_dossier("Albums/Voyages/Italie 2019", album="Italie")
    assert t.album_de("Albums/Voyages/Italie 2019") == "Italie"
    t.regler_dossier("Albums/Voyages/Italie 2019", album="")           # vidé à l'écran : pas d'album
    assert t.album_de("Albums/Voyages/Italie 2019") is None
    t.regler_dossier("Albums/Voyages/Italie 2019", defaut=True)
    assert t.album_de("Albums/Voyages/Italie 2019") == "Voyages – Italie 2019"


def test_la_case_d_un_parent_dit_tout_partiel_ou_rien(monde):
    t, im, ids, photos = monde
    n = t.arbre()["noeuds"]
    assert {n[c]["selection"] for c in n} == {"rien"}
    t.regler_dossier("Pellicule/2020/2020-06-10", coche=True)
    n = t.arbre()["noeuds"]
    assert n["Pellicule/2020/2020-06-10"]["selection"] == "tout"
    assert n["Pellicule/2020"]["selection"] == n["Pellicule"]["selection"] == n["."]["selection"] == "partiel"
    assert (n["Pellicule/2020"]["coches"], n["Pellicule/2020"]["a_cocher"]) == (1, 2)
    assert n["Albums"]["selection"] == "rien" and n["Scans"]["a_cocher"] == 0          # exclu : rien à cocher
    t.regler_dossier("Pellicule/2020", coche=True)
    n = t.arbre()["noeuds"]
    assert n["Pellicule/2020"]["selection"] == "tout" and n["Pellicule"]["selection"] == "partiel"
    t.regler_dossier(".", coche=True)
    assert t.arbre()["noeuds"]["."]["selection"] == "tout"                              # tout, sauf l'exclu
    # Fichiers inconnus : comptés une fois, à chaque niveau, et listés dans le bilan
    (photos / "orphelin.jpg").write_bytes(b"x")
    t.inventaire()
    n = t.arbre()["noeuds"]
    assert n["."]["inconnus"] == 2 and n["Pellicule"]["inconnus"] == 1 and n["Albums"]["inconnus"] == 0
    assert t.bilan(".")["fichiers_inconnus"] == ["Pellicule/2020/2020-05-01 Fête au jardin/pas-dans-immich.jpg", "orphelin.jpg"]
    assert t.bilan("Pellicule/2020")["fichiers_inconnus"] == ["Pellicule/2020/2020-05-01 Fête au jardin/pas-dans-immich.jpg"]


def test_cocher_un_parent_coche_ses_enfants_sauf_les_exclus(monde):
    t = monde[0]
    t.regler_dossier(".", coche=True)
    assert "Scans/Boîte 1" not in t.a_migrer() and "Pellicule/2020/2020-06-10" in t.a_migrer()
    t.regler_dossier("Pellicule/2020", coche=False)
    assert not [d for d in t.a_migrer() if d.startswith("Pellicule/2020")]
    assert "Pellicule/2021/2021-01-01 Neige" in t.a_migrer()


def test_decocher_un_parent_rend_le_choix_d_avant(monde):
    t = monde[0]
    seul = "Pellicule/2020/2020-06-10"
    t.regler_dossier(seul, coche=True)
    t.regler_dossier("Pellicule", coche=True)                       # case barrée → tout
    assert t.arbre()["noeuds"]["Pellicule"]["souvenir"] == 1
    t.regler_dossier("Pellicule", coche=False)                      # décocher : on retrouve le seul dossier choisi
    assert t.a_migrer() == [seul] and "souvenir" not in t.arbre()["noeuds"]["Pellicule"]
    t.regler_dossier("Pellicule", coche=False, vider=True)          # « tout décocher »
    assert t.a_migrer() == []
    t.regler_dossier("Pellicule", coche=True)                       # depuis rien : pas de souvenir
    t.regler_dossier("Pellicule", coche=False)
    assert t.a_migrer() == []
    # Un clic sur un sous-dossier périme le souvenir du parent
    t.regler_dossier(seul, coche=True)
    t.regler_dossier("Pellicule", coche=True)
    t.regler_dossier("Pellicule/2021", coche=False)
    t.regler_dossier("Pellicule/2021", coche=True)
    t.regler_dossier("Pellicule", coche=False)
    assert t.a_migrer() == []


def test_un_rattachement_refuse_ne_coupe_pas_le_lot(monde):
    """0.1.6 : Immich refuse de rattacher un visage → la photo part en écart, les autres passent, on peut relancer."""
    t, im, ids, photos = monde
    im.personnes_refusees.add("pers-b")
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    assert t.tache["erreur"] is None                                   # le lot va au bout
    e = etats(t)
    assert e["IMG_0001.jpg"] == "ecart" and e["IMG_0002.jpg"] == e["IMG_0003.jpg"] == "prete"
    b = t.bilan("Pellicule/2020")
    assert b["visages"]["perdu"] == 1 and not b["supprimable"]         # rien n'est supprimable tant que l'écart est là
    assert any(m == "PUT" and c == "/faces/pers-b" for m, c in im.ecrits)   # l'adresse porte la personne, comme dans Immich


def test_le_passage_garde_personnes_albums_tags_dates(monde):
    t, im, ids, photos = monde
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    assert t.tache["erreur"] is None and not t.tache["en_cours"]
    e = etats(t)
    assert e["IMG_0001.jpg"] == e["IMG_0002.jpg"] == e["IMG_0003.jpg"] == "prete" and e["DSC_1.jpg"] == "vue"
    neuf = {l["rel"].rsplit("/", 1)[-1]: l["nouveau_id"] for l in t.base.tous("SELECT rel, nouveau_id FROM photos")}
    n1, n2 = neuf["IMG_0001.jpg"], neuf["IMG_0002.jpg"]
    # Personnes : les mêmes identifiants, par les trois chemins (seule, réaffectée, recréée)
    assert {f["person"]["id"] for f in im.visages[n1]} == {"pers-a", "pers-b"}
    assert {(f.get("person") or {}).get("id") for f in im.visages[n2]} == {"pers-a", None} or \
           {(f.get("person") or {}).get("id") for f in im.visages[n2]} == {"pers-a"}
    b = t.bilan("Pellicule/2020")
    assert b["visages"] == {"seul": 1, "reaffecte": 1, "recree": 1, "perdu": 0} and b["ecarts"] == []
    # Albums : celui du dossier (créé), l'ancien (reporté) ; le dossier qui n'est qu'une date n'en a pas
    album = next(a for a in im.albums.values() if a["nom"] == "2020-05-01 Fête au jardin")
    assert album["ids"] == {n1, n2} and n1 in im.albums["alb-vieux"]["ids"]
    assert not any(neuf["IMG_0003.jpg"] in a["ids"] for a in im.albums.values())
    # Tag, description, date corrigée dans Immich
    assert n1 in im.tags["tag-1"]
    assert im.photos[n2]["exifInfo"]["description"] == "Sous le tilleul"
    assert im.photos[n2]["exifInfo"]["dateTimeOriginal"].startswith("2020-05-02T09:00:00")
    # Rien n'a été supprimé : ni fichier, ni ancienne photo
    assert all((photos / l["rel"]).is_file() for l in t.base.tous("SELECT rel FROM photos"))
    assert set(ids.values()) <= set(im.photos)
    assert ("DELETE", "/assets") not in im.ecrits
    # La correspondance est écrite hors de l'appli
    lignes = (t.cfg.data / "correspondance.csv").read_text(encoding="utf-8").splitlines()
    assert lignes[0].startswith("ancien_id;nouveau_id") and len(lignes) == 4
    assert "Personne inventée" not in str([dict(l) for l in t.base.tous("SELECT * FROM journal")])   # aucun nom au journal


def test_rejouer_ne_renvoie_rien(monde):
    t, im, ids, photos = monde
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    envois = im.ecrits.count(("POST", "/assets"))
    t.migrer()
    assert im.ecrits.count(("POST", "/assets")) == envois


def test_photo_animee(monde):
    t, im, ids, photos = monde
    t.regler_dossier("Pellicule/2021", coche=True)
    t.migrer()
    l = {x["rel"].rsplit(".", 1)[-1]: x for x in t.base.tous("SELECT * FROM photos WHERE dossier LIKE 'Pellicule/2021%'")}
    assert l["heic"]["etat"] == l["mov"]["etat"] == "prete"
    assert im.photos[l["heic"]["nouveau_id"]]["livePhotoVideoId"] == l["mov"]["nouveau_id"]   # la paire est reformée
    assert t.bilan("Pellicule/2021")["fichiers"] == 1


def test_supprimer_ne_supprime_que_ce_qui_est_prouve(monde):
    """Ce test fige ce que le clic fait. À ne modifier qu'en connaissance de cause."""
    t, im, ids, photos = monde
    dossier = photos / "Pellicule/2020/2020-05-01 Fête au jardin"
    with pytest.raises(Refus):                                         # rien n'est passé : rien à supprimer
        t.supprimer("Pellicule/2020")
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    b = t.bilan("Pellicule/2020")
    assert b["supprimable"] and b["a_supprimer"] == 3 and b["inconnus"] == 1 and len(b["echantillon"]) == 3
    assert "3 fichiers" in b["phrase"] and "1 qu'Immich ne connaît pas" in b["phrase"]
    assert t.suppression == {"en_cours": False, "dossier": "", "fait": 0, "total": 0, "etape": ""}
    r = t.supprimer("Pellicule/2020")
    assert r == {"supprimes": 3, "gardes": 0, "bilan": r["bilan"]}
    # 0.1.8 : l'avancement a été tenu jusqu'au bout, puis rendu
    assert t.suppression == {"en_cours": False, "dossier": "Pellicule/2020", "fait": 3, "total": 3, "etape": "immich"}
    # Les originaux passés sont partis, avec leur fichier d'accompagnement
    assert not (dossier / "IMG_0001.jpg").exists() and not (dossier / "IMG_0001.jpg.xmp").exists()
    assert not (photos / "Pellicule/2020/2020-06-10/IMG_0003.jpg").exists()
    # Le fichier qu'Immich ne connaissait pas est toujours là, et son dossier aussi
    assert (dossier / "pas-dans-immich.jpg").is_file()
    # Hors du dossier demandé : rien n'a bougé
    assert (photos / "Albums/Voyages/Italie 2019/DSC_1.jpg").is_file() and (photos / "Scans/Boîte 1/scan1.jpg").is_file()
    # Dans Immich : les anciennes photos du dossier sont retirées, les copies sont là, les autres anciennes aussi
    assert ids["fete1"] not in im.photos and ids["fete2"] not in im.photos and ids["italie"] in im.photos
    neufs = [l["nouveau_id"] for l in t.base.tous("SELECT nouveau_id FROM photos WHERE etat = 'supprimee'")]
    assert len(neufs) == 3 and all(n in im.photos for n in neufs)
    assert {f["person"]["id"] for f in im.visages[neufs[0]] if f.get("person")} <= {"pers-a", "pers-b"}
    with pytest.raises(Refus):                                         # une seconde fois : plus rien à faire
        t.supprimer("Pellicule/2020")
    # 0.1.7 : le bilan dit que c'est fini, et le dossier ne reste pas coché
    b = t.bilan("Pellicule/2020")
    assert b["termine"] and b["supprimes"] == 3 and not b["supprimable"] and b["phrase"].startswith("Terminé")
    assert "1 fichier(s) qu'Immich ne connaît pas" in b["phrase"]
    t.arbre()
    assert t.a_migrer() == []


def test_une_copie_abimee_bloque_la_suppression(monde):
    t, im, ids, photos = monde
    im.abimer.add("DSC_1.jpg")
    t.regler_dossier("Albums", coche=True)
    t.migrer()
    b = t.bilan("Albums")
    assert not b["supprimable"] and b["ecarts"][0]["sorte"] == "empreinte" and b["ecarts"][0]["bloquant"]
    with pytest.raises(Refus, match="ne s'accepte pas"):
        t.accepter(ids["italie"])
    with pytest.raises(Refus):
        t.supprimer("Albums")
    assert (photos / "Albums/Voyages/Italie 2019/DSC_1.jpg").is_file() and ids["italie"] in im.photos


def test_fichier_change_ou_copie_disparue_entre_le_bilan_et_le_clic(monde):
    t, im, ids, photos = monde
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    neuf = {l["rel"].rsplit("/", 1)[-1]: l["nouveau_id"] for l in t.base.tous("SELECT rel, nouveau_id FROM photos")}
    (photos / "Pellicule/2020/2020-06-10/IMG_0003.jpg").write_bytes(b"retouchee depuis")      # l'original a changé
    del im.photos[neuf["IMG_0002.jpg"]]                                                         # la copie a disparu d'Immich
    r = t.supprimer("Pellicule/2020")
    assert r["supprimes"] == 1 and r["gardes"] == 2
    assert (photos / "Pellicule/2020/2020-06-10/IMG_0003.jpg").is_file()
    assert (photos / "Pellicule/2020/2020-05-01 Fête au jardin/IMG_0002.jpg").is_file() and ids["fete2"] in im.photos


def test_un_visage_perdu_demande_un_accord(monde, monkeypatch):
    t, im, ids, photos = monde
    from app import immich as client

    def refus(self, *a, **k):
        raise client.ErreurImmich("Immich a refusé la création d'un visage (400).")
    monkeypatch.setattr(client.Immich, "creer_visage", refus)
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    b = t.bilan("Pellicule/2020")
    assert not b["supprimable"] and b["visages"]["perdu"] == 1
    e = b["ecarts"][0]
    assert e["sorte"] == "visage" and not e["bloquant"] and e["personnes"] == ["Personne inventée"]
    t.accepter(e["ancien"])
    assert t.bilan("Pellicule/2020")["supprimable"] and t.supprimer("Pellicule/2020")["supprimes"] == 3


def test_defaire_tant_que_les_originaux_sont_la(monde):
    t, im, ids, photos = monde
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    assert t.defaire("Pellicule/2020")["copies_retirees"] == 3
    assert set(etats(t).values()) == {"vue"}
    assert sorted(im.photos) == sorted(ids.values())                   # Immich est revenu à son état de départ
    assert all((photos / l["rel"]).is_file() for l in t.base.tous("SELECT rel FROM photos"))


def test_pas_assez_de_place(monde):
    t, im, ids, photos = monde
    im.libre = 100
    t.regler_dossier("Pellicule/2020", coche=True)
    assert not t.verifier_place(t.a_migrer())["possible"]
    with pytest.raises(Refus, match="place"):
        t.migrer()
    assert ("POST", "/assets") not in im.ecrits


def test_lecture_seule_n_envoie_rien_et_ne_supprime_rien(monde):
    t, im, ids, photos = monde
    t.regler_dossier("Pellicule/2020", coche=True)
    t.migrer()
    avant = list(im.ecrits)
    t.cfg.lecture_seule = True
    for geste in (t.migrer, lambda: t.supprimer("Pellicule/2020"), lambda: t.defaire("Pellicule/2020")):
        with pytest.raises(Refus, match="lecture seule"):
            geste()
    from app.immich import LectureSeule
    im2 = t.immich()
    for ecriture in (lambda: im2.retirer(["x"]), lambda: im2.envoyer(photos / "Pense bete/Travaux/note.jpg"),
                     lambda: im2.reaffecter_visage("v", "p"), lambda: im2.ajouter_album("a", ["x"])):
        with pytest.raises(LectureSeule):                              # refusé une seconde fois, au plus près d'Immich
            ecriture()
    assert im.ecrits == avant and (photos / "Pellicule/2020/2020-06-10/IMG_0003.jpg").is_file()
    t.inventaire()                                                     # lire reste permis


# ---------------------------------------------------------------- par l'API

@pytest.fixture()
def client(monde):
    t, im, ids, photos = monde
    main.ETAT.clear()
    main.ETAT.update(cfg=t.cfg, t=t)
    with TestClient(main.app) as c:
        c.monde = monde
        yield c
    main.ETAT.clear()


def test_la_reconnaissance_dit_qui_travaille(monde):
    t, im = monde[0], monde[1]
    avant = list(im.ecrits)
    r = t.reconnaissance(repond=lambda u: True)
    assert r["lisible"] and r["active"] and r["utilisee"] == 0 and r["sur_pc"]
    assert [a["nas"] for a in r["adresses"]] == [False, True]
    assert {"nom": "Lecture du texte (OCR)", "attente": 99, "en_cours": 1} in r["files"]
    r = t.reconnaissance(repond=lambda u: "pc-invente" not in u)                # PC éteint : Immich retombe sur le NAS
    assert r["utilisee"] == 1 and not r["sur_pc"]
    r = t.reconnaissance(repond=lambda u: False)
    assert r["utilisee"] is None and not r["sur_pc"]
    im.reconnaissance = None                                                    # clé sans le droit de lire les réglages
    r = t.reconnaissance(repond=lambda u: True)
    assert not r["lisible"] and "systemConfig.read" in r["raison"] and r["files"]
    assert im.ecrits == avant                                                   # rien n'est écrit dans Immich


def test_tout_est_ferme_sans_session(client):
    for chemin in ("/api/arbre", "/api/bilan", "/api/connexions", "/api/lot", "/api/reconnaissance", "/api/suppression"):
        assert client.get(chemin).status_code == 401, chemin
    for chemin in ("/api/inventaire", "/api/dossier", "/api/migrer", "/api/supprimer", "/api/defaire", "/api/accepter"):
        assert client.post(chemin, json={}).status_code == 401, chemin
    assert client.get("/api/connexion").status_code == 401
    assert client.get("/health").json()["ok"] and client.post("/api/connexion", json={"mot_de_passe": "non"}).status_code == 401


def test_parcours_par_l_api(client):
    import time
    t, im, ids, photos = client.monde
    assert client.post("/api/connexion", json={"mot_de_passe": MDP}).status_code == 200
    assert client.post("/api/migrer").status_code == 422                      # rien de coché
    a = client.post("/api/dossier", json={"chemin": "Pense bete", "coche": True}).json()
    assert a["noeuds"]["Pense bete/Travaux"]["coche"] and a["noeuds"]["Pense bete/Travaux"]["album"] == "Pense bete – Travaux"
    client.post("/api/dossier", json={"chemin": "Pense bete/Travaux", "album": "Travaux maison"})
    assert client.get("/api/lot").json()["possible"]
    assert client.post("/api/migrer").status_code == 200
    for _ in range(100):
        if not client.get("/api/arbre").json()["tache"]["en_cours"]:
            break
        time.sleep(0.05)
    b = client.get("/api/bilan", params={"chemin": "Pense bete"}).json()
    assert b["supprimable"] and b["a_supprimer"] == 1
    assert any(x["nom"] == "Travaux maison" for x in im.albums.values())
    # Un clic sur un écran périmé (mauvais nombre) ne supprime rien
    assert client.post("/api/supprimer", json={"chemin": "Pense bete", "nombre": 5}).status_code == 409
    assert (photos / "Pense bete/Travaux/note.jpg").is_file()
    r = client.post("/api/supprimer", json={"chemin": "Pense bete", "nombre": 1}).json()
    assert r["supprimes"] == 1 and not (photos / "Pense bete/Travaux/note.jpg").exists()
    c = client.get("/api/connexions").json()
    assert c["immich"]["version"] == "3.4.1" and c["dossier"]["inscriptible"] and c["dossier"]["exclus"] == ["Scans"]
    assert client.get("/api/bilan", params={"chemin": "../.."}).json()["fichiers"] == 0
