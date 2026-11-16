"""Réglages lus dans l'environnement du conteneur. Aucune valeur personnelle dans le code.

0.7.0 : les réglages d'usage (dossiers jamais migrés, passage automatique) ne sont plus ici : ils se règlent dans
l'écran Réglages (`Transhumance.reglages`, fichier `reglages.json` du dossier de données). TRANSHUMANCE_EXCLUS n'est
lue qu'une fois, au premier démarrage, pour reprendre la valeur de la stack."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import maison

APPLI = "transhumance"
VRAI = maison.VRAI                 # 0.6.0 : valeurs « oui » du module commun (oui, 1, true, yes, vrai)


@dataclass
class Config:
    password: str
    immich_url: str
    immich_cle: str
    photos: Path                      # le dossier des photos, monté dans le conteneur
    racine_immich: str                # le même dossier, tel qu'Immich le voit (chemin des photos externes)
    data: Path
    static: Path
    pellicule: str = "Pellicule"      # dossier de premier niveau rangé année / évènement
    albums: str = "Albums"            # dossier de premier niveau dont le nom ne préfixe pas l'album
    lecture_seule: bool = False
    lecture_seule_origine: str = ""   # 0.6.0 : « appli » (TRANSHUMANCE_LECTURE_SEULE), « maison » (MAISON_LECTURE_SEULE) ou « »
    attente_connexion: bool = True
    attente_files: float = 5.0        # secondes entre deux regards sur les files d'Immich
    delai_files: float = 3600.0       # attente maximale des files pour un dossier
    marge_place: float = 0.8          # part de la place libre qu'un lot peut occuper
    extra: dict = field(default_factory=dict)


def charger() -> Config:
    e = os.environ.get
    # 0.7.0 : MAISON_PASSWORD seul (l'ancien TRANSHUMANCE_PASSWORD n'est plus lu)
    mdp = maison.mot_de_passe()
    if len(mdp) < 12:
        raise SystemExit("MAISON_PASSWORD est absent ou trop court (12 caractères au moins) : Transhumance ne démarre pas.")
    manquantes = [n for n in ("TRANSHUMANCE_IMMICH_CLE", "TRANSHUMANCE_RACINE_IMMICH") if not e(n)]
    if manquantes:
        raise SystemExit("Variables absentes : " + ", ".join(manquantes) + ". Transhumance ne démarre pas.")
    return Config(
        password=mdp,
        immich_url=e("TRANSHUMANCE_IMMICH_URL", "http://immich_server:2283").rstrip("/"),
        immich_cle=e("TRANSHUMANCE_IMMICH_CLE"),
        photos=Path(e("TRANSHUMANCE_PHOTOS", "/photos")),
        racine_immich=e("TRANSHUMANCE_RACINE_IMMICH").rstrip("/"),
        data=Path(e("TRANSHUMANCE_DATA", "/data")),
        static=Path(__file__).parent / "static",
        pellicule=e("TRANSHUMANCE_PELLICULE", "Pellicule"),
        albums=e("TRANSHUMANCE_ALBUMS", "Albums"),
        # 0.6.0 : MAISON_LECTURE_SEULE pour toute la maison ; TRANSHUMANCE_LECTURE_SEULE (« oui » ou « non ») l'emporte
        lecture_seule=maison.lecture_seule("TRANSHUMANCE_LECTURE_SEULE"),
        lecture_seule_origine=maison.origine_lecture_seule("TRANSHUMANCE_LECTURE_SEULE"),
    )
