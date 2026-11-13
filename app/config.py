"""Réglages lus dans l'environnement du conteneur. Aucune valeur personnelle dans le code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APPLI = "transhumance"
VRAI = ("oui", "1", "true", "yes")


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
    exclus: tuple[str, ...] = ()      # dossiers de premier niveau à ne jamais migrer
    immich_adresse: str = ""          # adresse d'Immich dans le navigateur, pour ouvrir une photo du bilan
    lecture_seule: bool = False
    attente_connexion: bool = True
    attente_files: float = 5.0        # secondes entre deux regards sur les files d'Immich
    delai_files: float = 3600.0       # attente maximale des files pour un dossier
    marge_place: float = 0.8          # part de la place libre qu'un lot peut occuper
    jeton_millesime: str = ""         # 0.3.0 : jeton de Millésime pour /externe/demandes ; vide : adresse fermée
    extra: dict = field(default_factory=dict)


def charger() -> Config:
    e = os.environ.get
    manquantes = [n for n in ("TRANSHUMANCE_PASSWORD", "TRANSHUMANCE_IMMICH_CLE", "TRANSHUMANCE_RACINE_IMMICH") if not e(n)]
    if manquantes:
        raise SystemExit("Variables absentes : " + ", ".join(manquantes) + ". Transhumance ne démarre pas.")
    return Config(
        password=e("TRANSHUMANCE_PASSWORD"),
        immich_url=e("TRANSHUMANCE_IMMICH_URL", "http://immich_server:2283").rstrip("/"),
        immich_cle=e("TRANSHUMANCE_IMMICH_CLE"),
        photos=Path(e("TRANSHUMANCE_PHOTOS", "/photos")),
        racine_immich=e("TRANSHUMANCE_RACINE_IMMICH").rstrip("/"),
        data=Path(e("TRANSHUMANCE_DATA", "/data")),
        static=Path(__file__).parent / "static",
        pellicule=e("TRANSHUMANCE_PELLICULE", "Pellicule"),
        albums=e("TRANSHUMANCE_ALBUMS", "Albums"),
        exclus=tuple(x.strip() for x in e("TRANSHUMANCE_EXCLUS", "").split("|") if x.strip()),
        immich_adresse=e("TRANSHUMANCE_IMMICH_ADRESSE", "").rstrip("/"),
        lecture_seule=e("TRANSHUMANCE_LECTURE_SEULE", "").strip().lower() in VRAI,
        jeton_millesime=e("TRANSHUMANCE_JETON_MILLESIME", "").strip(),
    )
