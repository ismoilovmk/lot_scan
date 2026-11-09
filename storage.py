"""SQLite: какие лоты уже просмотрены и отправлены, чтобы не слать их повторно."""
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
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(lots)")}
        for column in ("fingerprint", "deadline"):  # базы прошлых версий этих колонок не имели
            if column not in columns:
                self.conn.execute(f"ALTER TABLE lots ADD COLUMN {column} TEXT")
        self.conn.execute("CREATE INDEX IF NOT EXISTS lots_fingerprint ON lots (fingerprint)")
        self.conn.commit()

    def is_seen(self, source: str, lot_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM lots WHERE source = ? AND lot_id = ?", (source, lot_id)
        ).fetchone()
        return row is not None

    def is_duplicate(self, fingerprint: str, now: str) -> bool:
        """Такой же лот уже отправлен и его срок ещё не вышел."""
        if not fingerprint:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM lots WHERE fingerprint = ? AND matched = 1 AND (deadline = '' OR deadline >= ?) LIMIT 1",
            (fingerprint, now),
        ).fetchone()
        return row is not None

    def mark(self, source: str, lot_id: str, sent: bool, title: str = "", fingerprint: str = "",
             deadline: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO lots (source, lot_id, first_seen, matched, title, fingerprint, deadline) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source, lot_id, datetime.now().isoformat(timespec="seconds"), int(sent), title[:300], fingerprint,
             deadline),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
