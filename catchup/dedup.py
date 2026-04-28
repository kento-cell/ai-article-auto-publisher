"""SQLite-backed dedup so the same item never gets sent twice.

Uses a single table keyed by (source, item_id). Items older than 30
days are purged on each open to keep the file small.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "catchup.db"
_PURGE_AFTER_DAYS = 30


class Dedup:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notified (
                source TEXT NOT NULL,
                item_id TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (source, item_id)
            )
            """
        )
        self._conn.commit()
        self._purge_old()

    def _purge_old(self) -> None:
        cutoff = (
            datetime.now(timezone.utc).replace(microsecond=0)
            - _timedelta(days=_PURGE_AFTER_DAYS)
        ).isoformat()
        self._conn.execute(
            "DELETE FROM notified WHERE notified_at < ?", (cutoff,)
        )
        self._conn.commit()

    def filter_new(self, items: list[dict]) -> list[dict]:
        """Return only items not already in the notified table."""
        if not items:
            return []
        cur = self._conn.cursor()
        new: list[dict] = []
        for it in items:
            cur.execute(
                "SELECT 1 FROM notified WHERE source=? AND item_id=? LIMIT 1",
                (it["source"], it["item_id"]),
            )
            if cur.fetchone() is None:
                new.append(it)
        return new

    def mark_sent(self, items: Iterable[dict]) -> None:
        """Persist that these items were just sent."""
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        rows = [(it["source"], it["item_id"], now) for it in items]
        self._conn.executemany(
            "INSERT OR REPLACE INTO notified (source, item_id, notified_at) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _timedelta(days: int):
    from datetime import timedelta
    return timedelta(days=days)
