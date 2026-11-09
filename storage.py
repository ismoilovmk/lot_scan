"""SQLite: какие лоты уже просмотрены, чтобы не слать их повторно."""
from __future__ import annotations

import sqlite3
from datetime import datetime


class Storage:
    def __init__(self, path: str = "lots.db"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS lots (
                   source TEXT NOT NULL,
                   lot_id TEXT NOT NULL,
                   first_seen TEXT NOT NULL,
                   matched INTEGER NOT NULL,
                   title TEXT,
                   PRIMARY KEY (source, lot_id)
               )"""
        )
        self.conn.commit()

    def is_seen(self, source: str, lot_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM lots WHERE source = ? AND lot_id = ?", (source, lot_id)
        ).fetchone()
        return row is not None

    def mark(self, source: str, lot_id: str, matched: bool, title: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO lots (source, lot_id, first_seen, matched, title) VALUES (?, ?, ?, ?, ?)",
            (source, lot_id, datetime.now().isoformat(timespec="seconds"), int(matched), title[:300]),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
