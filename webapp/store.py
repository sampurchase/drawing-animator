"""Where everything is kept: files in folders plus a small SQLite index.

    <data>/db.sqlite
    <data>/drawings/<id>/photo.<ext>, layers.npz, cutout.png, thumb.png
    <data>/backgrounds/<id>/image.jpg, thumb.jpg
    <data>/music/<id>/track.<ext>
    <data>/renders/<id>/video.mp4, poster.jpg   (partial.mp4 while being made)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

ID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_NAME = 60
KINDS = ("drawings", "backgrounds", "music", "renders")


def clean_name(name: str | None) -> str:
    """Tidy a name typed by a child: no control characters, single spaces, not too long."""
    name = re.sub(r"[\x00-\x1f\x7f]", " ", name if isinstance(name, str) else "")
    return re.sub(r"\s+", " ", name).strip()[:MAX_NAME]


def now() -> str:
    # microseconds so two things made in the same second still sort in the order they were made
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, data_dir: str):
        self.root = os.path.abspath(data_dir)
        for k in KINDS:
            os.makedirs(os.path.join(self.root, k), exist_ok=True)
        self.drawings_dir = os.path.join(self.root, "drawings")
        self.db_path = os.path.join(self.root, "db.sqlite")
        with closing(self._db()) as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS drawings (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, template TEXT NOT NULL,
                version INTEGER NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS backgrounds (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS music (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, bpm REAL NOT NULL, duration REAL NOT NULL,
                ext TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS renders (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                error TEXT NOT NULL DEFAULT '', request TEXT NOT NULL, drawing_names TEXT NOT NULL,
                created TEXT NOT NULL, started TEXT, finished TEXT, seconds_taken REAL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    # ---------------------------------------------------------- plumbing
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _all(self, sql: str, args=()) -> list[dict]:
        with closing(self._db()) as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def _one(self, sql: str, args=()) -> dict:
        rows = self._all(sql, args)
        if not rows:
            raise KeyError(args[0] if args else "")
        return rows[0]

    def _write(self, sql: str, args=()) -> None:
        with closing(self._db()) as db, db:
            db.execute(sql, args)

    @staticmethod
    def _check(item_id: str) -> str:
        if not isinstance(item_id, str) or not ID_RE.match(item_id):
            raise KeyError(item_id)
        return item_id

    # ---------------------------------------------------------- ids and paths
    def new_id(self, kind: str) -> str:
        parent = os.path.join(self.root, kind)
        while True:
            i = secrets.token_hex(6)
            if not os.path.exists(os.path.join(parent, i)):
                return i

    def folder(self, kind: str, item_id: str) -> str:
        return os.path.join(self.root, kind, self._check(item_id))

    def drawing_dir(self, i: str) -> str:
        return self.folder("drawings", i)

    def layers_path(self, i: str) -> str:
        return os.path.join(self.drawing_dir(i), "layers.npz")

    def background_path(self, i: str) -> str:
        return os.path.join(self.folder("backgrounds", i), "image.jpg")

    def music_path(self, i: str) -> str:
        return os.path.join(self.folder("music", i), "track" + self.get_music(i)["ext"])

    def video_path(self, i: str) -> str:
        return os.path.join(self.folder("renders", i), "video.mp4")

    # ---------------------------------------------------------- meta flags
    def get_meta(self, key: str):
        rows = self._all("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        self._write("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # ---------------------------------------------------------- drawings
    def add(self, drawing_id: str, name: str, template: str, version: int) -> dict:
        self._write("INSERT INTO drawings (id, name, template, version, created) VALUES (?,?,?,?,?)",
                    (drawing_id, clean_name(name), template, version, now()))
        return self.get(drawing_id)

    def get(self, drawing_id: str) -> dict:
        return self._one("SELECT * FROM drawings WHERE id = ?", (self._check(drawing_id),))

    def list(self) -> list[dict]:
        return self._all("SELECT * FROM drawings ORDER BY created DESC, rowid DESC")

    def rename(self, drawing_id: str, name: str) -> dict:
        self.get(drawing_id)
        self._write("UPDATE drawings SET name = ? WHERE id = ?", (clean_name(name), drawing_id))
        return self.get(drawing_id)

    def delete(self, drawing_id: str) -> None:
        self.get(drawing_id)
        self._write("DELETE FROM drawings WHERE id = ?", (drawing_id,))
        shutil.rmtree(self.drawing_dir(drawing_id), ignore_errors=True)

    # ---------------------------------------------------------- backgrounds
    def add_background(self, i: str, name: str) -> dict:
        self._write("INSERT INTO backgrounds (id, name, created) VALUES (?,?,?)", (i, clean_name(name), now()))
        return self.get_background(i)

    def get_background(self, i: str) -> dict:
        return self._one("SELECT * FROM backgrounds WHERE id = ?", (self._check(i),))

    def list_backgrounds(self) -> list[dict]:
        return self._all("SELECT * FROM backgrounds ORDER BY created DESC, rowid DESC")

    def delete_background(self, i: str) -> None:
        self.get_background(i)
        self._write("DELETE FROM backgrounds WHERE id = ?", (i,))
        shutil.rmtree(self.folder("backgrounds", i), ignore_errors=True)

    # ---------------------------------------------------------- music
    def add_music(self, i: str, name: str, bpm: float, duration: float, ext: str) -> dict:
        self._write("INSERT INTO music (id, name, bpm, duration, ext, created) VALUES (?,?,?,?,?,?)",
                    (i, clean_name(name), bpm, duration, ext, now()))
        return self.get_music(i)

    def get_music(self, i: str) -> dict:
        return self._one("SELECT * FROM music WHERE id = ?", (self._check(i),))

    def list_music(self) -> list[dict]:
        return self._all("SELECT * FROM music ORDER BY created DESC, rowid DESC")

    def delete_music(self, i: str) -> None:
        self.get_music(i)
        self._write("DELETE FROM music WHERE id = ?", (i,))
        shutil.rmtree(self.folder("music", i), ignore_errors=True)

    # ---------------------------------------------------------- renders
    @staticmethod
    def _render(row: dict) -> dict:
        row["request"] = json.loads(row["request"])
        row["drawing_names"] = json.loads(row["drawing_names"])
        return row

    def add_render(self, i: str, name: str, request: dict, drawing_names: list[str]) -> dict:
        self._write("INSERT INTO renders (id, name, request, drawing_names, created) VALUES (?,?,?,?,?)",
                    (i, clean_name(name), json.dumps(request), json.dumps(drawing_names), now()))
        return self.get_render(i)

    def get_render(self, i: str) -> dict:
        return self._render(self._one("SELECT * FROM renders WHERE id = ?", (self._check(i),)))

    def list_renders(self) -> list[dict]:
        return [self._render(r) for r in self._all("SELECT * FROM renders ORDER BY created DESC, rowid DESC")]

    def update_render(self, i: str, **fields) -> None:
        allowed = {"status", "error", "started", "finished", "seconds_taken", "name"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("bad render fields")
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._write(f"UPDATE renders SET {cols} WHERE id = ?", (*fields.values(), self._check(i)))

    def delete_render(self, i: str) -> None:
        self.get_render(i)
        self._write("DELETE FROM renders WHERE id = ?", (i,))
        shutil.rmtree(self.folder("renders", i), ignore_errors=True)
