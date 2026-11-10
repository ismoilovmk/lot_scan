"""SQLite: какие лоты уже просмотрены и отправлены, чтобы не слать их повторно."""
from __future__ import annotations

import sqlite3
from datetime import datetime


class Storage:
    def __init__(self, path: str = "lots.db", clock=datetime.now):
        self.clock = clock  # время первого просмотра лота; бот передаёт ташкентское
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
        self.conn.execute("CREATE TABLE IF NOT EXISTS notes (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
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
            (source, lot_id, self.clock().isoformat(timespec="seconds"), int(sent), title[:300], fingerprint,
             deadline),
        )
        self.conn.commit()

    def day_counts(self, day: str) -> tuple[int, int]:
        """Сколько лотов впервые просмотрено за день (ГГГГ-ММ-ДД) и сколько из них отправлено."""
        seen, sent = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(matched), 0) FROM lots WHERE first_seen LIKE ?", (day + "%",)
        ).fetchone()
        return seen, sent

    def note(self, name: str) -> str:
        """Заметка бота самому себе между проходами. Пусто — такой ещё нет."""
        row = self.conn.execute("SELECT value FROM notes WHERE name = ?", (name,)).fetchone()
        return row[0] if row else ""

    def write_note(self, name: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO notes (name, value) VALUES (?, ?)", (name, value))
        self.conn.commit()

    def adopt_vocabulary(self, signature: str) -> bool:
        """Если слова или регионы изменились, забывает неотправленные лоты, чтобы проверить их заново.

        Отправленные остаются: повторно они не уйдут. True — словарь изменился.
        """
        if self.note("vocabulary") == signature:
            return False
        self.conn.execute("DELETE FROM lots WHERE matched = 0")
        self.write_note("vocabulary", signature)   # одна запись на оба шага: сбой посередине ничего не меняет
        return True

    def close(self) -> None:
        self.conn.close()
