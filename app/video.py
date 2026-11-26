"""0.10.0 : les vidéos restantes. Lire une vidéo (ffprobe), choisir sa voie, la mettre en MP4, prouver la copie.

Partagé par Transhumance (NAS) et l'encodeur du PC (`app/encodeur.py`, image `:encodeur`) : aucun accès à la base ni à
Immich ici, seulement ffmpeg et ffprobe.

Trois voies (décision du 26/11/2026, après le conseil) :
- « remux »     : vidéo H.264 8 bits → enveloppe MP4 sans toucher l'image (son copié s'il est AAC ou MP3, sinon AAC) ;
- « tel_quel »  : HDR, 10 bits, Dolby Vision ou HEVC → envoyé sans transformation, prouvé par empreinte ;
- « encode »    : tout le reste (WMV, souvent mal nommé .wma, MPEG-4 Part 2, MJPEG…) → H.264 qualité quasi identique.
Un fichier sans image (un vrai son .wma) ou illisible n'est jamais transformé : « pas_video »."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

# Extensions regardées parmi les fichiers qu'Immich ne connaît pas ; « .wma » : souvent une vidéo WMV mal nommée
EXTENSIONS = (".wma", ".wmv", ".asf", ".mov", ".mp4", ".m4v", ".avi", ".3gp", ".mpg", ".mpeg", ".mts", ".m2ts", ".mkv")
REMUX_VIDEO = ("h264",)
REMUX_SON_COPIE = ("aac", "mp3")
TEL_QUEL_VIDEO = ("hevc",)
HDR_TRANSFERTS = ("smpte2084", "arib-std-b67")
PLAFOND = 1.5                     # MP4 réencodé plus lourd que 1,5 × l'original : nouvel essai plus léger
CRF, CRF_LEGER = 18, 22           # processeur (libx264)
QP, QP_LEGER = 20, 24             # puce vidéo Intel (h264_vaapi)
SSIM_MIN = 0.95                   # fidélité : ressemblance minimale de chaque image comparée
POINTS_SSIM = (0.1, 0.3, 0.5, 0.7, 0.9)
RENDU = "/dev/dri/renderD128"


class ErreurVideo(Exception):
    pass


def outils() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _lancer(cmd: list[str], delai: float | None = None, doux: bool = False) -> subprocess.CompletedProcess:
    if doux and shutil.which("nice"):
        cmd = ["nice", "-n", "19", *cmd]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=delai, check=False)
    except FileNotFoundError as exc:
        raise ErreurVideo("ffmpeg n'est pas installé.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErreurVideo("ffmpeg n'a pas fini dans le délai.") from exc


# ================================================================ lire
def sonder(fichier: Path) -> dict | None:
    """ffprobe en JSON ; None si le fichier n'est pas lisible comme média."""
    r = _lancer(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(fichier)], 120)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return None


def _nombre(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _rotation(flux: dict) -> int:
    for d in flux.get("side_data_list") or []:
        if "rotation" in d:
            return int(round(_nombre(d["rotation"]))) % 360
    return int(round(_nombre((flux.get("tags") or {}).get("rotate")))) % 360


def mesures(sonde: dict | None) -> dict:
    """Ce qu'on retient d'une vidéo : de quoi choisir sa voie et la comparer à sa copie."""
    if not sonde:
        return {"video": False}
    flux = sonde.get("streams") or []
    images = [f for f in flux if f.get("codec_type") == "video" and not (f.get("disposition") or {}).get("attached_pic")]
    sons = [f for f in flux if f.get("codec_type") == "audio"]
    fmt = sonde.get("format") or {}
    duree = _nombre(fmt.get("duration")) or max((_nombre(f.get("duration")) for f in images + sons), default=0.0)
    if not images or duree <= 0:
        return {"video": False, "sons": len(sons), "duree": duree}
    v = images[0]
    rot = _rotation(v)
    l, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if rot in (90, 270):
        l, h = h, l                                        # définition telle qu'on la voit
    pix = str(v.get("pix_fmt") or "")
    return {
        "video": True, "duree": round(duree, 3), "debut": _nombre(fmt.get("start_time")),
        "codec": str(v.get("codec_name") or ""), "profil": str(v.get("profile") or ""), "pix_fmt": pix,
        "dix_bits": bool(re.search(r"(p10|p12|10le|10be|12le|12be)", pix)),
        "hdr": str(v.get("color_transfer") or "") in HDR_TRANSFERTS
               or any("dovi" in json.dumps(d).lower() or "dolby" in json.dumps(d).lower() for d in v.get("side_data_list") or []),
        "largeur": l, "hauteur": h, "rotation": rot,
        "entrelace": str(v.get("field_order") or "progressive") not in ("progressive", "unknown", ""),
        "cadence": str(v.get("avg_frame_rate") or v.get("r_frame_rate") or ""),
        "sons": len(sons), "codec_son": str(sons[0].get("codec_name") or "") if sons else "",
        "format": str(fmt.get("format_name") or ""),
        "creation": _date_balise(fmt.get("tags") or {}) or _date_balise(v.get("tags") or {}),
    }


def voie(m: dict) -> str:
    if not m.get("video"):
        return "pas_video"
    if m.get("hdr") or m.get("dix_bits") or m.get("codec") in TEL_QUEL_VIDEO:
        return "tel_quel"
    if m.get("codec") in REMUX_VIDEO:
        return "remux"
    return "encode"


# ================================================================ date
_BALISES = ("com.apple.quicktime.creationdate", "creation_time", "date", "WM/EncodingTime", "DateTimeOriginal")


def _iso(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _date_balise(tags: dict) -> str | None:
    bas = {k.lower(): v for k, v in tags.items()}
    for cle in _BALISES:
        v = bas.get(cle.lower())
        if not v:
            continue
        texte = str(v).strip().replace("Z", "+00:00")
        for essai in (texte, texte[:19]):
            try:
                d = datetime.fromisoformat(essai.replace(" ", "T", 1) if "T" not in essai else essai)
            except ValueError:
                continue
            if 1980 <= d.year <= datetime.now().year + 1:
                return _iso(d)
    return None


_NOM = (re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])(?:[ _T-]?([01]\d|2[0-3])[-_.h:]?([0-5]\d)[-_.m:]?([0-5]\d))?(?!\d)"),)
_JOUR = re.compile(r"^((?:19|20)\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])")
_ANNEE = re.compile(r"^((?:19|20)\d{2})$")


def date_trouvee(rel: str, m: dict, pellicule: str = "Pellicule", mtime: float | None = None) -> tuple[str | None, str]:
    """Date d'une vidéo qu'Immich ne connaît pas : balise de la vidéo, puis nom du fichier, puis dossier, puis (relecture
    du 26/11/2026) la date de modification du fichier, pour ne jamais tomber au jour de la migration.
    Rend (date ISO ou None, source) : « video », « nom », « dossier », « annee » (approchée), « fichier » ou « aucune »."""
    if m.get("creation"):
        return m["creation"], "video"
    nom = PurePosixPath(rel).stem
    for motif in _NOM:
        if (x := motif.search(nom)):
            a, mo, j, hh, mi, ss = x.groups()
            try:
                return _iso(datetime(int(a), int(mo), int(j), int(hh or 12), int(mi or 0), int(ss or 0))), "nom"
            except ValueError:
                pass
    parties = PurePosixPath(rel).parent.parts
    for p in reversed(parties):
        if (x := _JOUR.match(p)):
            try:
                return _iso(datetime(int(x[1]), int(x[2]), int(x[3]), 12)), "dossier"
            except ValueError:
                pass
    for p in reversed(parties):
        if _ANNEE.match(p):
            return _iso(datetime(int(p), 7, 1, 12)), "annee"
    if mtime:
        return _iso(datetime.fromtimestamp(mtime, timezone.utc)), "fichier"
    return None, "aucune"


# ================================================================ mettre en MP4
def nom_mp4(rel: str, pris: set[str] | None = None) -> str:
    """« VID_0001.wma » → « VID_0001.mp4 » ; « VID_0001 (transhumance).mp4 » si ce nom est déjà pris."""
    stem = PurePosixPath(rel).stem
    nom = f"{stem}.mp4"
    if pris and nom.casefold() in {p.casefold() for p in pris} and PurePosixPath(rel).suffix.lower() != ".mp4":
        nom = f"{stem} (transhumance).mp4"
    return nom


def _filtres(m: dict, materiel: str) -> list[str]:
    f = []
    if m.get("entrelace"):
        f.append("yadif")
    f.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")          # H.264 en 4:2:0 veut des côtés pairs
    if materiel == "vaapi":
        f += ["format=nv12", "hwupload"]
    else:
        f.append("format=yuv420p")
    return f


def commande(voie_: str, entree: Path, sortie: Path, m: dict, date: str | None, materiel: str = "cpu",
             leger: bool = False, fils: str = "0") -> list[str]:
    """La commande ffmpeg d'une voie « remux » ou « encode ». materiel : « cpu » (libx264) ou « vaapi » (puce Intel)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"]
    if voie_ == "encode" and materiel == "vaapi":
        cmd += ["-vaapi_device", RENDU]
    cmd += ["-i", str(entree), "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "0", "-dn", "-sn"]
    if voie_ == "remux":
        cmd += ["-c:v", "copy"]
    elif materiel == "vaapi":
        cmd += ["-vf", ",".join(_filtres(m, materiel)), "-c:v", "h264_vaapi", "-rc_mode", "CQP",
                "-qp", str(QP_LEGER if leger else QP), "-fps_mode", "passthrough"]
    else:
        cmd += ["-vf", ",".join(_filtres(m, materiel)), "-c:v", "libx264", "-preset", "slow",
                "-crf", str(CRF_LEGER if leger else CRF), "-fps_mode", "passthrough", "-threads", fils]
    if m.get("sons"):
        cmd += ["-c:a", "copy"] if m.get("codec_son") in REMUX_SON_COPIE else ["-c:a", "aac", "-b:a", "192k"]
    if date:
        cmd += ["-metadata", f"creation_time={date}", "-metadata", f"com.apple.quicktime.creationdate={date}"]
    cmd += ["-movflags", "+faststart+use_metadata_tags", "-f", "mp4", str(sortie)]
    return cmd


def mettre_en_mp4(voie_: str, entree: Path, sortie: Path, m: dict, date: str | None, materiel: str = "cpu",
                  fils: str = "0", doux: bool = False, suffixe: str = "part") -> dict:
    """Fabrique le MP4 dans un fichier temporaire, puis le renomme. Rend {"grossi": bool, "leger": bool, "taille"}.
    Plafond : un réencodé plus lourd que 1,5 × l'original est refait plus léger ; encore trop lourd, il est gardé
    (la preuve décide de la suppression) et marqué « grossi »."""
    sortie.parent.mkdir(parents=True, exist_ok=True)
    temp = sortie.with_name(f"{sortie.name}.{suffixe}-{os.getpid()}")
    origine = entree.stat().st_size
    leger = False
    for essai in (False, True):
        leger = essai
        r = _lancer(commande(voie_, entree, temp, m, date, materiel, leger, fils), None, doux)
        if r.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
            temp.unlink(missing_ok=True)
            raise ErreurVideo("ffmpeg a échoué : " + (r.stderr or "").strip()[-400:])
        if voie_ == "remux" or temp.stat().st_size <= PLAFOND * origine:
            break
    dater(temp, date)
    os.replace(temp, sortie)
    taille = sortie.stat().st_size
    return {"taille": taille, "leger": leger, "grossi": voie_ == "encode" and taille > PLAFOND * origine}


def dater(fichier: Path, date: str | None) -> None:
    """Immich lit fileCreatedAt sur la date du fichier envoyé : on la pose (aussi à l'arrivée d'un MP4 du PC)."""
    if not date:
        return
    try:
        horo = datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp()
        os.utime(fichier, (horo, horo))
    except (ValueError, OSError):
        pass


def essai_vaapi() -> dict:
    """La puce vidéo Intel du NAS sait-elle encoder ? Un vrai encodage de 2 s sur une mire, pilote iHD puis i965."""
    if not Path(RENDU).exists():
        return {"ok": False, "pilote": None, "raison": f"{RENDU} absent : la puce vidéo du NAS n'est pas donnée au conteneur."}
    if not outils():
        return {"ok": False, "pilote": None, "raison": "ffmpeg absent de l'image."}
    derniere = ""
    for pilote in ("iHD", "i965"):
        env = {**os.environ, "LIBVA_DRIVER_NAME": pilote}
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-vaapi_device", RENDU, "-f", "lavfi", "-i",
               "testsrc2=size=640x360:rate=25", "-t", "2", "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi",
               "-rc_mode", "CQP", "-qp", str(QP), "-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            derniere = str(exc)
            continue
        if r.returncode == 0:
            os.environ["LIBVA_DRIVER_NAME"] = pilote
            return {"ok": True, "pilote": pilote, "raison": ""}
        derniere = (r.stderr or "").strip()[-200:]
    return {"ok": False, "pilote": None, "raison": "La puce vidéo refuse l'encodage : " + derniere}


# ================================================================ prouver
def images_comptees(fichier: Path) -> int:
    r = _lancer(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                 "stream=nb_read_frames", "-of", "csv=p=0", str(fichier)], None, True)
    try:
        return int((r.stdout or "").strip().split(",")[0])
    except ValueError:
        return 0


def decode_entier(fichier: Path) -> bool:
    """Toute la vidéo se décode sans une erreur."""
    r = _lancer(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(fichier), "-map", "0:v:0", "-map", "0:a?",
                 "-f", "null", "-"], None, True)
    return r.returncode == 0 and not (r.stderr or "").strip()


def ressemblance(original: Path, copie: Path, mo: dict, mc: dict) -> float:
    """La plus petite ressemblance (SSIM) entre l'original et la copie, sur 5 images prises à 10, 30, 50, 70 et 90 % de
    la vidéo. Les deux vidéos sont lues en entier côte à côte, remises à zéro au début (un WMV ou un MP4 ne commencent
    pas toujours à 0) : les images comparées sont bien les mêmes. 0 si la comparaison n'a pas pu se faire."""
    l, h = mo["largeur"] - mo["largeur"] % 2, mo["hauteur"] - mo["hauteur"] % 2
    with tempfile.TemporaryDirectory() as d:
        stats = Path(d) / "ssim.txt"
        prep = f"scale={l}:{h},format=yuv420p,setsar=1,setpts=PTS-STARTPTS"
        avant = "yadif," if mo.get("entrelace") and not mc.get("entrelace") else ""   # la copie a été désentrelacée
        filtre = f"[0:v]{avant}{prep}[a];[1:v]{prep}[b];[a][b]ssim=stats_file={stats.as_posix()}"
        r = _lancer(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(original), "-i", str(copie),
                     "-lavfi", filtre, "-f", "null", "-"], None, True)
        if r.returncode != 0 or not stats.is_file():
            return 0.0
        valeurs = [float(x.group(1)) for x in re.finditer(r"All:([0-9.]+)", stats.read_text())]
    if not valeurs:
        return 0.0
    return round(min(valeurs[min(len(valeurs) - 1, int(p * len(valeurs)))] for p in POINTS_SSIM), 4)


def prouver(original: Path, copie: Path, mo: dict) -> tuple[list[str], dict]:
    """Contrôles d'une vidéo mise en MP4 (remux ou encode) contre son original. Rend (écarts, mesures de la copie).
    Écarts bloquants : duree, son, images, definition, illisible, fidelite."""
    mc = mesures(sonder(copie))
    if not mc.get("video"):
        return ["illisible"], mc
    ecarts = []
    if abs(mc["duree"] - mo["duree"]) > 1.0:
        ecarts.append("duree")
    if mc.get("sons", 0) < mo.get("sons", 0):
        ecarts.append("son")
    if abs(mc["largeur"] - mo["largeur"]) > 1 or abs(mc["hauteur"] - mo["hauteur"]) > 1:
        ecarts.append("definition")
    no, nc = images_comptees(original), images_comptees(copie)
    mc["images"], mc["images_origine"] = nc, no
    if not no or not nc or abs(nc - no) > max(1, 0.01 * no):
        ecarts.append("images")
    if not decode_entier(copie):
        ecarts.append("illisible")
    if "duree" not in ecarts and "illisible" not in ecarts:
        mc["ssim"] = ressemblance(original, copie, mo, mc)
        if mc["ssim"] < SSIM_MIN:
            ecarts.append("fidelite")
    return ecarts, mc
