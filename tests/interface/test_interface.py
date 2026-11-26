"""Tests d'écran de Transhumance (PC) contre un faux Immich : le parcours entier, jusqu'au clic."""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def monde(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    dossier = tmp_path_factory.mktemp("ui")
    proc = subprocess.Popen([sys.executable, "-m", "tests.interface.serveur", str(dossier), str(port)], cwd=RACINE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            if urllib.request.urlopen(base + "/health", timeout=1).status == 200:
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("Transhumance de démonstration n'a pas démarré.")
    yield base, dossier / "photos"
    proc.terminate()


@pytest.fixture(scope="module")
def page(monde):
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("CHROME") or None)   # CHROME : navigateur déjà installé
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.set_default_timeout(10000)
        erreurs = []
        pg.on("pageerror", lambda e: erreurs.append(str(e)))
        pg.goto(monde[0])
        pg.get_by_label(re.compile("Mot de passe")).fill("essai-essai")
        pg.get_by_role("button", name="Se connecter").click()
        pg.get_by_role("heading", level=1, name="Migrer").wait_for()
        yield pg
        assert not erreurs, erreurs
        b.close()


def ligne(page, nom):
    return page.locator(".ligne", has=page.get_by_role("checkbox", name="Cocher " + nom, exact=True))


def test_1_l_arbre_propose_les_albums(page):
    page.get_by_role("button", name="Relire Immich et le dossier").click()
    page.locator("#message", has_text="relus").wait_for()
    for nom in ("Pellicule", "2019"):
        page.get_by_role("button", name="Déplier " + nom, exact=True).click()
    assert page.get_by_label("Album pour 2019-08-12 Vendanges").input_value() == "2019-08-12 Vendanges"
    assert page.get_by_label("Album pour 2019-12-25").input_value() == ""              # dossier qui n'est qu'une date
    assert page.get_by_role("checkbox", name="Cocher Scans", exact=True).is_disabled()  # jamais migré
    assert "1 inconnu(s) d'Immich" in ligne(page, "2019").inner_text()


def test_2_cocher_une_annee_et_la_faire_passer(page):
    # 0.1.2 : cocher un seul sous-dossier barre la case de ses parents d'un trait
    page.get_by_role("checkbox", name="Cocher 2019-12-25", exact=True).check()
    parent = page.get_by_role("checkbox", name="Cocher 2019", exact=True)
    page.wait_for_function("el => el.indeterminate", arg=parent.element_handle())
    assert "1 sous-dossier(s) cochés sur 2" in ligne(page, "2019").inner_text()
    assert page.get_by_role("checkbox", name="Cocher Pellicule", exact=True).evaluate("el => el.indeterminate")
    parent.click()                                                   # cliquer une case barrée coche tout le dossier
    page.wait_for_function("el => el.checked && !el.indeterminate", arg=parent.element_handle())
    parent.click()                                                   # 0.9.4 : une case pleine se vide d'un clic
    # le navigateur décoche la case tout de suite : on attend la réponse du serveur, vue sur la case enfant
    enfant = page.get_by_role("checkbox", name="Cocher 2019-12-25", exact=True)
    page.wait_for_function("el => !el.checked", arg=enfant.element_handle())
    page.wait_for_function("el => !el.checked && !el.indeterminate", arg=parent.element_handle())
    page.get_by_role("checkbox", name="Cocher 2019-12-25", exact=True).check()   # « tout décocher » vide une case barrée
    page.wait_for_function("el => el.indeterminate", arg=parent.element_handle())
    page.get_by_role("button", name="Tout décocher dans 2019", exact=True).click()
    page.wait_for_function("el => !el.checked && !el.indeterminate", arg=parent.element_handle())
    parent.click()
    passer = page.get_by_role("button", name=re.compile(r"Faire passer les dossiers cochés \(2\)"))
    passer.wait_for()
    page.get_by_label("Album pour 2019-08-12 Vendanges").fill("Vendanges 2019")
    page.get_by_label("Album pour 2019-08-12 Vendanges").blur()
    passer.click()
    page.locator("#tache", has_text="Lot passé").wait_for(timeout=30000)
    assert "6 copiées et contrôlées" in ligne(page, "2019").inner_text()


def test_3_le_bilan_puis_le_clic(page, monde):
    photos = monde[1]
    ligne(page, "2019").get_by_role("button", name="Bilan").click()
    phrase = page.locator("#phrase-bilan").inner_text()
    assert "6 fichiers" in phrase and "6 retrouvés identiques" in phrase and "1 qu'Immich ne connaît pas" in phrase
    bilan = page.get_by_role("region", name="Bilan")
    assert "recréées à la main" in bilan.inner_text()
    assert bilan.get_by_role("link").first.get_attribute("href").startswith("http://immich.exemple/photos/")
    supprimer = bilan.get_by_role("button", name=re.compile("Supprimer les 6 originaux"))
    assert supprimer.is_disabled()                                   # tant que la case n'est pas cochée
    assert len(list((photos / "Pellicule/2019").rglob("IMG_*.jpg"))) == 6
    bilan.get_by_role("checkbox").check()
    supprimer.click()
    page.locator("#message", has_text="6 original(aux) supprimé(s)").wait_for()
    assert list((photos / "Pellicule/2019").rglob("IMG_*.jpg")) == []
    assert (photos / "Pellicule/2019/2019-08-12 Vendanges/inconnu.jpg").is_file()        # l'inconnu d'Immich reste
    assert len(list((photos / "Pellicule/2020").rglob("IMG_*.jpg"))) == 3                # l'autre année n'a pas bougé
    assert "6 originaux supprimés" in ligne(page, "2019").inner_text()
    # 0.1.7 : le bilan dit « Terminé » ; les sous-dossiers finis quittent l'arbre, un lien les remontre
    assert page.locator("#phrase-bilan").inner_text().startswith("Terminé")
    page.locator("#termine").wait_for()
    assert not page.get_by_role("checkbox", name="Cocher 2019-12-25", exact=True).count()
    page.locator("#finis").get_by_role("button", name="Afficher").click()
    page.get_by_role("checkbox", name="Cocher 2019-12-25", exact=True).wait_for()


def test_4_la_reconnaissance_dit_qui_travaille(page):
    """0.9.0 : la ligne courte reste dans Migrer ; le détail (adresses, files) est dans la fiche « PC de calcul »
    de l'écran Connexion commun, après Vérifier (guide, Réglages lus)."""
    assert "reconnaissance" in page.locator("#reconnaissance-courte").inner_text().lower()
    page.get_by_role("link", name="Connexion").click()
    page.get_by_role("heading", level=1, name="Connexion").wait_for()
    fiche = page.get_by_role("article", name="PC de calcul (reconnaissance d'Immich)")
    fiche.get_by_role("button", name="Vérifier").click()
    fiche.get_by_text("Ne répond pas", exact=True).wait_for()               # adresses inventées : personne ne répond
    texte = fiche.inner_text()
    assert "1. PC" in texte and "2. NAS" in texte and "Lecture du texte (OCR)" in texte
    assert "ne répond pas" in texte and "Allumer normalement" in texte
    immich = page.get_by_role("article", name="Immich", exact=True)
    assert "Ne mets pas Immich à jour pendant la migration." in immich.inner_text()
    immich.get_by_role("button", name="Vérifier").click()
    immich.get_by_text(re.compile(r"Version 3\.4\.1 · ")).wait_for()


def test_5_reglages_journal_version_deconnexion(page):
    """0.5.0 (format commun) : Réglages porte l'écriture, le journal, la version et la déconnexion ; Connexion ne garde que les services.
    0.9.0 : le dossier des photos passe dans Réglages (ce n'est pas un service)."""
    page.get_by_role("link", name="Réglages").click()
    page.get_by_role("heading", level=1, name="Réglages").wait_for()
    page.get_by_role("region", name="Journal").wait_for()
    assert page.get_by_text(re.compile(r"^Transhumance \d+\.\d+\.\d+$")).count() == 1
    assert page.get_by_role("button", name="Se déconnecter").count() == 1
    page.get_by_role("region", name="Dossier des photos").get_by_text("écriture possible", exact=False).wait_for()   # 0.9.0
    page.get_by_role("link", name="Connexion").click()
    page.get_by_role("article", name="Immich", exact=True).wait_for()
    assert page.get_by_role("region", name="Dossier des photos").count() == 0
    assert page.get_by_role("region", name="Journal").count() == 0 and page.get_by_role("button", name="Se déconnecter").count() == 0


def test_5b_reglages_puis_restaurer(page):
    """0.7.0 : les réglages d'usage se changent dans Réglages ; Restaurer montre les différences puis les applique."""
    page.get_by_role("link", name="Réglages").click()
    bloc = page.get_by_role("region", name="Réglages", exact=True)
    champ = bloc.get_by_label("Dossiers jamais migrés")
    champ.wait_for()
    assert champ.input_value() == "Scans"
    champ.fill("Scans\nAlbums")
    bloc.get_by_role("button", name="Enregistrer").click()
    bloc.get_by_text("Réglages enregistrés.").wait_for()
    page.get_by_role("region", name="Journal").get_by_text("Réglage changé : exclus").first.wait_for()
    r = page.get_by_role("region", name="Restaurer")
    r.get_by_role("button", name="Voir les sauvegardes").click()
    diff = r.get_by_role("list", name="Différences")
    diff.wait_for()                                                      # 2026-11-15 : Scans, au lieu de Scans, Albums
    assert "Scans, Albums → Scans" in diff.inner_text()
    r.get_by_label("Sauvegarde du").select_option("2026-11-14")
    r.get_by_text("Scans, Albums → Scans, Pense bete").wait_for()
    r.get_by_role("button", name="Restaurer ces réglages").click()
    r.get_by_text("Réglages du 2026-11-14 restaurés.").wait_for()
    assert champ.input_value() == "Scans\nPense bete"
    page.get_by_role("link", name="Migrer").click()
    page.get_by_role("heading", level=1, name="Migrer").wait_for()
    page.get_by_role("checkbox", name="Cocher Pense bete", exact=True).wait_for()
    assert page.get_by_role("checkbox", name="Cocher Pense bete", exact=True).is_disabled()   # exclu tout de suite
    page.get_by_role("link", name="Réglages").click()                    # remettre comme avant pour la suite
    bloc.get_by_label("Dossiers jamais migrés").fill("Scans")
    bloc.get_by_role("button", name="Enregistrer").click()
    bloc.get_by_text("Réglages enregistrés.").wait_for()


def test_6_sur_iphone_la_pilule_en_bas(page, monde):
    if True:                                                                        # même navigateur, contexte d'iPhone
        c = page.context.browser.new_context(viewport={"width": 390, "height": 664}, device_scale_factor=3, is_mobile=True, has_touch=True)
        pg = c.new_page()
        pg.set_default_timeout(10000)
        erreurs = []
        pg.on("pageerror", lambda e: erreurs.append(str(e)))
        pg.goto(monde[0])
        pg.get_by_label(re.compile("Mot de passe")).fill("essai-essai")
        pg.get_by_role("button", name="Se connecter").click()
        pg.get_by_role("heading", level=1, name="Migrer").wait_for()
        nav = pg.get_by_role("navigation", name="Sections").bounding_box()
        hauteur = pg.viewport_size["height"]
        assert nav["y"] > hauteur * 0.8 and nav["height"] < 70                       # pilule flottante en bas
        assert pg.get_by_role("navigation", name="Sections").get_by_role("link").count() == 3
        for nom in ("Migrer", "Connexion", "Réglages"):
            pg.get_by_role("link", name=nom).click()
            pg.get_by_role("heading", level=1, name=nom).wait_for()
            assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), nom   # rien ne déborde
        # 0.7.0 : la tuile Restaurer, ouverte, ne déborde pas non plus
        r = pg.get_by_role("region", name="Restaurer")
        r.get_by_role("button", name="Voir les sauvegardes").click()
        r.get_by_label("Sauvegarde du").select_option("2026-11-14")
        r.get_by_role("list", name="Différences").wait_for()
        assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        assert not erreurs, erreurs
        c.close()


def test_7_une_vieille_video_passe_en_mp4(page, monde):
    """0.10.0 : un WMV nommé .wma, inconnu d'Immich : lu, mis en MP4 par l'encodeur, envoyé, prouvé."""
    photos = monde[1]
    if not (photos / "Videos/Anciennes/VID_20040101_120000.wma").is_file():
        pytest.skip("ffmpeg absent")
    page.get_by_role("link", name="Migrer").click()
    page.get_by_role("heading", level=1, name="Migrer").wait_for()
    page.get_by_role("button", name="Relire Immich et le dossier").click()
    page.locator("#message", has_text="relus").wait_for()
    page.get_by_role("checkbox", name="Cocher Videos", exact=True).check()
    passer = page.get_by_role("button", name=re.compile(r"Faire passer les dossiers cochés \(1\)"))
    passer.click()
    page.locator("#tache", has_text="mise en MP4").wait_for(timeout=30000)
    page.locator("#encodage").wait_for(timeout=15000)
    page.get_by_role("button", name="Déplier Videos", exact=True).click()
    page.wait_for_function("() => document.body.innerText.includes('vidéos en MP4, à envoyer')", timeout=30000)
    passer.click()
    page.wait_for_function("() => { const t = document.querySelector('#tache')?.innerText || ''; "
                           "return t.includes('Lot passé') && !t.includes('mise en MP4') }", timeout=30000)
    ligne(page, "Anciennes").get_by_role("button", name="Bilan").click()
    videos = page.get_by_role("list", name="Vidéos")
    page.get_by_text(re.compile(r"Vidéos restantes \(1\)")).click()
    assert "copiée et prouvée" in videos.inner_text() and "réencodage" in videos.inner_text()
    assert "date du nom" in videos.inner_text()
    bilan = page.get_by_role("region", name="Bilan")
    assert "vont au sas" in bilan.inner_text()
    bilan.get_by_role("checkbox").check()
    bilan.get_by_role("button", name=re.compile("Supprimer les 1 originaux")).click()
    page.locator("#message", has_text="1 original(aux) supprimé(s)").wait_for()
    assert not (photos / "Videos/Anciennes/VID_20040101_120000.wma").exists()
    assert list((photos / "#recycle/transhumance-sas").rglob("*.wma"))

