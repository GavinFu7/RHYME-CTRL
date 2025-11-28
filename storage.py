import os
import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "rhyme_highlighter.db")


def _get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """            CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            audio_filename TEXT,
            lyrics TEXT,
            threshold REAL,
            entries_json TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def new_session_id() -> str:
    return str(uuid.uuid4())


def save_track(
    session_id: str,
    mode: str,
    audio_filename: str,
    lyrics: str,
    threshold: float,
    entries: List[Dict[str, Any]],
):
    payload = {"entries": entries}
    entries_json = json.dumps(payload, ensure_ascii=False)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """            INSERT INTO tracks (
            session_id,
            mode,
            audio_filename,
            lyrics,
            threshold,
            entries_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            mode,
            audio_filename,
            lyrics,
            float(threshold),
            entries_json,
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
        ),
    )
    conn.commit()
    conn.close()


def list_tracks(limit: int = 20):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """            SELECT id, session_id, mode, audio_filename, threshold, created_at
        FROM tracks
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def load_track(track_id: int):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    data = dict(row)
    try:
        payload = json.loads(data.get("entries_json") or "{}")
        data["entries"] = payload.get("entries", [])
    except Exception:
        data["entries"] = []
    return data
