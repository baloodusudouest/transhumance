"""Tests d'écran de Transhumance (PC) contre un faux Immich : le parcours entier, jusqu'au clic."""
from __future__ import annotations

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
        b = p.chromium.launch()
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
    page.get_by_role("checkbox", name="Cocher 2019", exact=True).check()
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
