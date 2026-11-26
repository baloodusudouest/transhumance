"""0.10.0 : les vidéos restantes (.wma qui sont des WMV, .mov, .mp4) mises en MP4, prouvées, puis l'original au sas.

Vraies petites vidéos fabriquées par ffmpeg (test sauté sans ffmpeg). Faux Immich comme ailleurs."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main, video
from app.base import Base
from app.config import Config
from app.encodeur import Encodeur
from app.passage import Transhumance

from .faux_immich import CLE, RACINE, FauxImmich
from .test_passage import MDP, MAISON

pytestmark = pytest.mark.skipif(not video.outils(), reason="ffmpeg absent")
JETON = "jeton-encodeur-essai"
FETE = "Pellicule/2005/2005-06-12 Mer"
NEIGE = "Pellicule/2006/2006-01-01 Neige"


@pytest.fixture(autouse=True)
def sans_variables(monkeypatch):
    for nom in (*MAISON, "TRANSHUMANCE_JETON_CALCUL"):
        monkeypatch.delenv(nom, raising=False)


def fabriquer(chemin, *options, duree=2):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-f", "lavfi",
                    "-i", "sine=frequency=440", "-t", str(duree), *options, str(chemin)], check=True)


@pytest.fixture()
def monde_videos(tmp_path):
    photos = tmp_path / "photos"
    fabriquer(photos / FETE / "VID_20050612_143000.wma", "-c:v", "wmv2", "-c:a", "wmav2", "-f", "asf")   # un WMV mal nommé
    fabriquer(photos / FETE / "clip.mov", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le")  # H.264 : remux
    (photos / FETE).mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine", "-t", "1", "-c:a", "wmav2", "-f", "asf",
                    str(photos / FETE / "son.wma")], check=True)                                        # un vrai son
    (photos / FETE / "note.txt").write_text("pas une vidéo")
    fabriquer(photos / NEIGE / "ancien.mp4", "-c:v", "mpeg4", "-c:a", "aac")                             # connue d'Immich
    im = FauxImmich(photos)
    ancien = im.externe(f"{NEIGE}/ancien.mp4", date="2006-01-01T15:00:00.000Z")
    im.visage(ancien, "pers-a", 100)
    im.albums["alb-hiver"] = {"nom": "Hiver", "ids": {ancien}}
    cfg = Config(password=MDP, immich_url="http://immich", immich_cle=CLE, photos=photos, racine_immich=RACINE,
                 data=tmp_path / "data", static=tmp_path / "static", attente_connexion=False, attente_files=0)
    t = Transhumance(cfg, Base(cfg.data / "t.db"), im.transport())
    t.materiel_nas = {"ok": True, "mode": "cpu", "pilote": "essai", "raison": ""}   # les tests encodent au processeur
    t.inventaire()
    return t, im, ancien, photos


def ligne(t, nom):
    return next(l for l in t.base.tous("SELECT * FROM photos") if l["rel"].endswith("/" + nom))


def encoder_tout(t):
    while t.encodeur_nas_tour():
        pass


def test_inventaire_garde_les_videos_inconnues(monde_videos):
    t, im, ancien, photos = monde_videos
    lignes = {l["rel"].rsplit("/", 1)[-1]: l for l in t.base.tous("SELECT * FROM photos")}
    assert {"VID_20050612_143000.wma", "clip.mov", "son.wma", "ancien.mp4"} <= set(lignes)
    assert lignes["clip.mov"]["origine"] == "inconnu" and lignes["ancien.mp4"]["origine"] == "externe"
    # Le fichier qui n'est pas une vidéo reste un inconnu d'Immich, jamais touché
    assert [l["rel"] for l in t.base.tous("SELECT rel FROM inconnus")] == [f"{FETE}/note.txt"]


def test_voies():
    assert video.voie({"video": False}) == "pas_video"
    assert video.voie({"video": True, "codec": "h264", "pix_fmt": "yuv420p"}) == "remux"
    assert video.voie({"video": True, "codec": "hevc"}) == "tel_quel"
    assert video.voie({"video": True, "codec": "h264", "dix_bits": True}) == "tel_quel"      # 10 bits : jamais aplati
    assert video.voie({"video": True, "codec": "h264", "hdr": True}) == "tel_quel"
    assert video.voie({"video": True, "codec": "wmv2"}) == "encode"
    assert video.nom_mp4("a/VID_1.wma", {"VID_1.mp4"}) == "VID_1 (transhumance).mp4"
    assert video.nom_mp4("a/VID_1.wma", {"autre.mp4"}) == "VID_1.mp4"


def test_date_trouvee():
    assert video.date_trouvee("P/2005/x/VID_20050612_143000.wma", {})[1] == "nom"
    assert video.date_trouvee("Pellicule/2005/2005-06-12 Mer/clip.mov", {}) == ("2005-06-12T12:00:00Z", "dossier")
    assert video.date_trouvee("Pellicule/2005/Divers/clip.mov", {}) == ("2005-07-01T12:00:00Z", "annee")
    assert video.date_trouvee("x/clip.mov", {"creation": "2004-01-02T03:04:05Z"}) == ("2004-01-02T03:04:05Z", "video")


def test_rien_ne_part_sans_etre_coche(monde_videos):
    t, im, ancien, photos = monde_videos
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    t.regler_dossier(FETE, coche=False)
    assert t.prendre("pc", "PC", ("encode",)) is None                 # décoché : la vidéo attend
    t.regler_dossier(FETE, coche=True)
    assert t.prendre("pc", "PC", ("encode",))["nom"] == "VID_20050612_143000.wma"


def test_passage_complet_des_videos(monde_videos):
    t, im, ancien, photos = monde_videos
    t.regler_dossier("Pellicule", coche=True)
    t.migrer()
    assert ligne(t, "VID_20050612_143000.wma")["voie"] == "encode" and ligne(t, "VID_20050612_143000.wma")["etat"] == "a_encoder"
    assert ligne(t, "clip.mov")["voie"] == "remux" and ligne(t, "ancien.mp4")["voie"] == "encode"
    assert ligne(t, "son.wma")["etat"] == "ecart" and json.loads(ligne(t, "son.wma")["ecarts"]) == ["pas_video"]
    assert "attendent leur mise en MP4" in t.tache["message"]
    assert not t.bilan("Pellicule")["supprimable"]                    # des vidéos sont dans la file
    encoder_tout(t)
    assert {ligne(t, n)["etat"] for n in ("VID_20050612_143000.wma", "clip.mov", "ancien.mp4")} == {"encodee"}
    assert sorted(t.dossiers_a_envoyer()) == [FETE, NEIGE]
    t.migrer(t.dossiers_a_envoyer(), origine="l'encodage des vidéos")
    for n in ("VID_20050612_143000.wma", "clip.mov", "ancien.mp4"):
        l = ligne(t, n)
        assert l["etat"] == "prete", (n, l["ecarts"])
        assert json.loads(l["mesures"])["copie"]["ssim"] >= video.SSIM_MIN
    copies = {p["originalFileName"]: p for p in im.photos.values() if not p.get("libraryId")}
    assert {"VID_20050612_143000.mp4", "clip.mp4", "ancien.mp4"} <= set(copies)
    # La copie de la vidéo connue d'Immich garde personne, album et date vérifiée
    neuf = ligne(t, "ancien.mp4")["nouveau_id"]
    assert "pers-a" in {(v.get("person") or {}).get("id") for v in im.visages[neuf]}
    assert neuf in im.albums["alb-hiver"]["ids"]
    assert im.photos[neuf]["exifInfo"]["dateTimeOriginal"].startswith("2006-01-01T15:00")
    # La vidéo inconnue reçoit la date trouvée dans son nom
    assert im.photos[ligne(t, "VID_20050612_143000.wma")["nouveau_id"]]["exifInfo"]["dateTimeOriginal"].startswith("2005-06-12T14:30")
    b = t.bilan("Pellicule")
    assert b["supprimable"] and b["a_supprimer"] == 3 and len(b["videos"]) == 4
    # Le clic : les originaux vidéo vont au sas ; le son reste ; l'ancienne entrée d'Immich est retirée
    r = t.supprimer("Pellicule")
    assert r["supprimes"] == 3
    assert not (photos / FETE / "VID_20050612_143000.wma").exists() and (photos / FETE / "son.wma").is_file()
    sas = t.cfg.dossier_sas
    assert len([p for p in sas.rglob("*") if p.is_file()]) == 3
    assert ancien not in im.photos and not any(t.cfg.encodes.rglob("*.mp4"))
    assert t.bilan("Pellicule")["sas"]["nombre"] == 3 and t.bilan("Pellicule")["termine"]
    # Remettre une vidéo du sas
    t.remettre(ligne(t, "clip.mov")["ancien_id"])
    assert (photos / FETE / "clip.mov").is_file() and ligne(t, "clip.mov")["etat"] == "prete"
    # Le sas se vide seul après 30 jours (et pas avant)
    assert t.vider_sas() == 0
    assert t.vider_sas(datetime.now(timezone.utc) + timedelta(days=31)) == 2
    assert not [p for p in sas.rglob("*") if p.is_file()]
    # Redonner au sas la vidéo remise : l'ancienne entrée n'est pas retirée une seconde fois (elle n'a pas d'ancienne)
    assert t.supprimer(FETE)["supprimes"] == 1


def test_le_nas_laisse_les_reencodages_au_pc_present(monde_videos):
    t, im, ancien, photos = monde_videos
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    t.pc_vu("BUREAU")
    encoder_tout(t)
    assert ligne(t, "clip.mov")["etat"] == "encodee"                 # le remux se fait sur le NAS
    assert ligne(t, "VID_20050612_143000.wma")["etat"] == "a_encoder"  # le réencodage attend le PC
    t.materiel_nas = {"ok": False, "mode": "vaapi", "raison": "absente"}
    t.base.ecrire("pc_vu", {"le": "2000-01-01T00:00:00+00:00", "machine": "BUREAU"})
    assert not t.encodeur_nas_tour()                                 # PC absent, puce absente : il attend


def test_une_copie_trop_courte_bloque_la_suppression(monde_videos, tmp_path):
    t, im, ancien, photos = monde_videos
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    job = t.prendre("pc", "PC", ("encode",))
    court = tmp_path / "court.mp4"
    fabriquer(court, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", duree=1)
    sortie = t.chemin_produit(job["id"], job["nom_mp4"])
    sortie.parent.mkdir(parents=True)
    shutil.copy(court, sortie)
    t.finir(job["id"], sortie, {}, "pc")
    t.migrer([FETE])
    l = ligne(t, "VID_20050612_143000.wma")
    assert l["etat"] == "ecart" and {"duree", "images"} <= set(json.loads(l["ecarts"]))
    b = t.bilan(FETE)
    assert any(e["sorte"] == "duree" and e["bloquant"] for e in b["ecarts"])
    with pytest.raises(Exception):
        t.accepter(l["ancien_id"])
    assert (photos / FETE / "VID_20050612_143000.wma").is_file()


def test_sans_vignette_dans_immich_c_est_un_ecart(monde_videos):
    t, im, ancien, photos = monde_videos
    im.sans_vignette.add("clip.mp4")
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    encoder_tout(t)
    t.migrer([FETE])
    assert "illisible" in json.loads(ligne(t, "clip.mov")["ecarts"])


def test_trois_echecs_laissent_la_video_sans_bloquer(monde_videos):
    t, im, ancien, photos = monde_videos
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    for _ in range(3):
        job = t.prendre("pc", "PC", ("encode",))
        t.echouer(job["id"], "essai raté", "pc")
    l = ligne(t, "VID_20050612_143000.wma")
    assert l["etat"] == "ecart" and json.loads(l["ecarts"]) == ["encodage"]
    assert t.prendre("pc", "PC", ("encode",)) is None


# ---------------------------------------------------------------- la porte du PC et l'encodeur
@pytest.fixture()
def client_videos(monde_videos, monkeypatch):
    t, im, ancien, photos = monde_videos
    main.ETAT.clear()
    main.ETAT.update(cfg=t.cfg, t=t, boucle_auto=False, encodeur_nas=False)
    with TestClient(main.app) as c:
        c.monde = monde_videos
        yield c
    main.ETAT.clear()


def test_porte_du_pc_fermee_sans_jeton(client_videos, monkeypatch):
    assert client_videos.post("/calcul/prendre", json={}).status_code == 404
    monkeypatch.setenv("TRANSHUMANCE_JETON_CALCUL", JETON)
    assert client_videos.post("/calcul/prendre", json={}).status_code == 401
    assert client_videos.post("/calcul/prendre", json={}, headers={"Authorization": "Bearer faux"}).status_code == 401
    assert client_videos.post("/calcul/prendre", json={}, headers={"Authorization": f"Bearer {JETON}"}).status_code == 204


def test_l_encodeur_du_pc_par_la_porte(client_videos, monkeypatch, tmp_path):
    t, im, ancien, photos = client_videos.monde
    monkeypatch.setenv("TRANSHUMANCE_JETON_CALCUL", JETON)
    assert client_videos.post("/api/connexion", json={"mot_de_passe": MDP}).status_code == 200
    t.regler_dossier(NEIGE, coche=True)
    t.migrer()
    enc = Encodeur("http://testserver", JETON, "BUREAU", tmp_path / "travail", transport=client_videos._transport)
    assert enc.tour() is True
    assert ligne(t, "ancien.mp4")["etat"] == "encodee"
    assert json.loads(ligne(t, "ancien.mp4")["mesures"])["produit"]["par"] == "pc"
    assert enc.tour() is False                                       # plus rien à faire
    e = client_videos.get("/api/encodage").json()
    assert e["pc"]["actif"] and e["pc"]["machine"] == "BUREAU" and e["a_envoyer"] == 1
    assert not any((tmp_path / "travail").rglob("*.*"))              # le dossier de travail est vidé


def test_une_video_reprise_au_pc_n_est_plus_a_lui(client_videos, monkeypatch):
    t, im, ancien, photos = client_videos.monde
    monkeypatch.setenv("TRANSHUMANCE_JETON_CALCUL", JETON)
    t.regler_dossier(NEIGE, coche=True)
    t.migrer()
    h = {"Authorization": f"Bearer {JETON}"}
    job = client_videos.post("/calcul/prendre", json={"machine": "BUREAU"}, headers=h).json()
    t.base.executer("UPDATE encodages SET vu_le = '2000-01-01T00:00:00+00:00' WHERE id = ?", (job["id"],))
    t._rendre_perimes()
    assert client_videos.post(f"/calcul/vie/{job['id']}", json={}, headers=h).json() == {"continuer": False}
    assert client_videos.get(f"/calcul/fichier/{job['id']}", headers=h).status_code == 409


def test_vieille_base_mise_a_jour(tmp_path):
    """Une base de la 0.9.7 reçoit les nouvelles colonnes et la file, sans rien perdre."""
    import sqlite3
    chemin = tmp_path / "v.db"
    c = sqlite3.connect(chemin)
    c.executescript("CREATE TABLE photos (ancien_id TEXT PRIMARY KEY, rel TEXT NOT NULL, dossier TEXT NOT NULL, type TEXT NOT NULL, "
                    "taille INTEGER NOT NULL DEFAULT 0, cachee INTEGER NOT NULL DEFAULT 0, etat TEXT NOT NULL DEFAULT 'vue', "
                    "nouveau_id TEXT, empreinte TEXT, deja_la INTEGER NOT NULL DEFAULT 0, instantane TEXT, "
                    "ecarts TEXT NOT NULL DEFAULT '[]', accepte INTEGER NOT NULL DEFAULT 0, le TEXT);"
                    "INSERT INTO photos(ancien_id, rel, dossier, type) VALUES ('a', 'x/y.jpg', 'x', 'IMAGE');")
    c.close()
    b = Base(chemin)
    l = b.un("SELECT * FROM photos")
    assert l["origine"] == "externe" and l["voie"] is None and b.tous("SELECT * FROM encodages") == []


# ---------------------------------------------------------------- relecture indépendante du 26/11/2026
def _jusqu_au_sas(t):
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    encoder_tout(t)
    t.migrer([FETE])
    assert t.supprimer(FETE)["supprimes"] == 2


def test_le_sas_garde_l_original_si_la_copie_a_disparu(monde_videos):
    t, im, ancien, photos = monde_videos
    _jusqu_au_sas(t)
    plus_tard = datetime.now(timezone.utc) + timedelta(days=31)
    im.photos.pop(ligne(t, "clip.mov")["nouveau_id"])                 # copie retirée d'Immich pendant les 30 jours
    assert t.vider_sas(plus_tard) == 1                                # seul l'autre original est effacé
    assert ligne(t, "clip.mov")["sas"] and (t.cfg.dossier_sas / ligne(t, "clip.mov")["sas"]).is_file()


def test_le_sas_ne_s_efface_pas_en_lecture_seule(monde_videos):
    import dataclasses
    t, im, ancien, photos = monde_videos
    _jusqu_au_sas(t)
    t.cfg = dataclasses.replace(t.cfg, lecture_seule=True)
    assert t.vider_sas(datetime.now(timezone.utc) + timedelta(days=31)) == 0
    assert len([p for p in t.cfg.dossier_sas.rglob("*") if p.is_file()]) == 2


def test_la_preuve_porte_sur_les_octets_envoyes(monde_videos):
    t, im, ancien, photos = monde_videos
    t.regler_dossier(FETE, coche=True)
    t.migrer()
    encoder_tout(t)
    vrai = t._controler

    def changer_puis_controler(im_, l):                               # le MP4 change après l'envoi
        if l["voie"] == "remux":
            produit = t._produit(l)
            produit.write_bytes(produit.read_bytes() + b"\0")
        return vrai(im_, l)
    t._controler = changer_puis_controler
    t.migrer([FETE])
    assert "illisible" in json.loads(ligne(t, "clip.mov")["ecarts"])


def test_relire_apres_coup_ne_cree_pas_de_doublon(monde_videos):
    t, im, ancien, photos = monde_videos
    _jusqu_au_sas(t)
    t.remettre(ligne(t, "clip.mov")["ancien_id"])
    im.externe(f"{FETE}/clip.mov")                                    # Immich relit l'original remis
    t.inventaire()
    assert len([l for l in t.base.tous("SELECT rel FROM photos") if l["rel"].endswith("/clip.mov")]) == 1


def test_date_de_repli_du_fichier():
    assert video.date_trouvee("x/sans_date.wmv", {}, mtime=1104537600.0) == ("2005-01-01T00:00:00Z", "fichier")


def test_une_video_d_avant_la_0_10_part_aussi_au_sas(monde_videos):
    """Une vidéo passée sans voie (0.9.x, ou partie de Live Photo) va au sas comme les autres."""
    t, im, ancien, photos = monde_videos
    t.regler_dossier(NEIGE, coche=True)
    t.base.executer("UPDATE photos SET voie = 'tel_quel' WHERE rel LIKE '%ancien.mp4'")   # écarte la préparation
    t.migrer([NEIGE])
    t.base.executer("UPDATE photos SET voie = NULL WHERE rel LIKE '%ancien.mp4'")         # comme une ligne de la 0.9.x
    assert t.supprimer(NEIGE)["supprimes"] == 1
    assert list(t.cfg.dossier_sas.rglob("ancien.mp4"))
