"""On-disk LLM response cache (plan.md section 3.2).

Key: sha256 over (role, model, prompt_version, system, user, temperature). One sqlite file under
backend/data/cache/ (gitignored). Turned on with LLM_CACHE=1 and off by default, so live play always
samples fresh while self-play can replay for free. The mock provider never reads or writes it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
DEFAULT_CACHE_PATH = CACHE_DIR / "llm_responses.sqlite3"


def cache_key(
    role: str, model: str, prompt_version: int | None, system: str, user: str, temperature: float
) -> str:
    payload = json.dumps([role, model, prompt_version, system, user, float(temperature)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path: Path = DEFAULT_CACHE_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS responses ("
                " key TEXT PRIMARY KEY, role TEXT NOT NULL, model TEXT NOT NULL, prompt_version INTEGER,"
                " response TEXT NOT NULL, created_at REAL NOT NULL)"
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # One short-lived connection per operation: commits on success and never holds the file open
        # (Windows refuses to delete a sqlite file with a live connection).
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT response FROM responses WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, response: str, *, role: str, model: str, prompt_version: int | None) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?)",
                (key, role, model, prompt_version, response, time.time()),
            )

    def count(self) -> int:
        with self._db() as db:
            return int(db.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def clear(self) -> None:
        with self._db() as db:
            db.execute("DELETE FROM responses")
