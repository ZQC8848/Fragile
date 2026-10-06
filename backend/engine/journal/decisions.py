"""JSONL logs per session (docs/backend-design.md section 10).

    data/logs/<session>/decisions.jsonl   one line per DM decision (all three scorers' scores)
    data/logs/<session>/events.jsonl      performer I/O, player inputs, commands, generated beats
    data/logs/<session>/session.json      written at end: tension curve, ending, counts
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from engine.state.schema import REPO_ROOT

LOGS_DIR = REPO_ROOT / "backend" / "data" / "logs"


class SessionLogger:
    def __init__(self, session_id: str, root: Path = LOGS_DIR):
        self.session_id = session_id
        self.dir = root / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._decisions = self.dir / "decisions.jsonl"
        self._events = self.dir / "events.jsonl"

    def reset(self) -> None:
        """A (re)started session starts a fresh log; earlier runs under the same id are discarded."""
        for p in (self._decisions, self._events, self.dir / "session.json"):
            if p.exists():
                p.unlink()

    def decision(self, record: dict[str, Any]) -> None:
        self._append(self._decisions, record)

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        self._append(self._events, {"kind": kind, "wall_t": time.time(), **payload})

    def finish(self, summary: dict[str, Any]) -> None:
        (self.dir / "session.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    def read_decisions(self) -> list[dict[str, Any]]:
        if not self._decisions.exists():
            return []
        out = []
        for line in self._decisions.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class AnnotationStore:
    """Pairwise preferences, one JSONL file (docs/backend-design.md section 11)."""

    def __init__(self, path: Path | None = None):
        self.path = path or (REPO_ROOT / "backend" / "data" / "annotations" / "pairwise.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, record: dict[str, Any]) -> None:
        record = {"wall_t": time.time(), **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())
