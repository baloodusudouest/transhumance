"""Mémoire de Transhumance (SQLite) : où en est chaque photo, ce que portait l'ancienne, le journal."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    ancien_id   TEXT PRIMARY KEY,
    rel         TEXT NOT NULL,          -- chemin sous le dossier des photos
    dossier     TEXT NOT NULL,          -- dossier (chemin relatif) qui la contient
    type        TEXT NOT NULL,          -- IMAGE ou VIDEO
    taille      INTEGER NOT NULL DEFAULT 0,
    cachee      INTEGER NOT NULL DEFAULT 0,   -- partie vidéo d'une photo animée
    etat        TEXT NOT NULL DEFAULT 'vue',  -- vue | envoyee | prete | ecart | supprimee
    nouveau_id  TEXT,
    empreinte   TEXT,
    deja_la     INTEGER NOT NULL DEFAULT 0,   -- Immich avait déjà ce fichier dans son stockage
    instantane  TEXT,                   -- tout ce que portait l'ancienne photo (JSON)
    ecarts      TEXT NOT NULL DEFAULT '[]',
    accepte     INTEGER NOT NULL DEFAULT 0,
    le          TEXT
);
CREATE INDEX IF NOT EXISTS photos_dossier ON photos(dossier);
CREATE TABLE IF NOT EXISTS dossiers (chemin TEXT PRIMARY KEY, album TEXT, coche INTEGER NOT NULL DEFAULT 0, inconnus INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS inconnus (rel TEXT PRIMARY KEY, dossier TEXT NOT NULL);   -- fichiers du dossier qu'Immich ne connaît pas
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, le TEXT NOT NULL, quoi TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS reglages (cle TEXT PRIMARY KEY, valeur TEXT);
"""


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base:
    def __init__(self, chemin: Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(chemin, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.executescript(SCHEMA)
        self._verrou = threading.RLock()

    def tous(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._verrou:
            return self._c.execute(sql, args).fetchall()

    def un(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._verrou:
            return self._c.execute(sql, args).fetchone()

    def executer(self, sql: str, args: tuple = ()) -> None:
        with self._verrou:
            self._c.execute(sql, args)

    def plusieurs(self, sql: str, lignes: list[tuple]) -> None:
        with self._verrou:
            self._c.execute("BEGIN")
            self._c.executemany(sql, lignes)
            self._c.execute("COMMIT")

    def noter(self, quoi: str, detail: dict | None = None) -> None:
        """Journal : jamais de nom de personne, des identifiants et des chemins seulement."""
        self.executer("INSERT INTO journal(le, quoi, detail) VALUES (?,?,?)",
                      (maintenant(), quoi, json.dumps(detail, ensure_ascii=False) if detail else None))

    def lire(self, cle: str, defaut=None):
        l = self.un("SELECT valeur FROM reglages WHERE cle = ?", (cle,))
        return json.loads(l["valeur"]) if l else defaut

    def ecrire(self, cle: str, valeur) -> None:
        self.executer("INSERT INTO reglages(cle, valeur) VALUES (?,?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                      (cle, json.dumps(valeur, ensure_ascii=False)))
