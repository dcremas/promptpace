"""SQLite persistence for finished sessions."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.models import Analysis, InputEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    client_id   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    prompt_id   TEXT NOT NULL,
    text        TEXT NOT NULL,
    events_json TEXT NOT NULL,
    overall_wpm REAL,
    burst_wpm   REAL,
    pause_share REAL NOT NULL,
    backspaces_per_100_keys REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_client ON sessions (client_id, id DESC);
CREATE TABLE IF NOT EXISTS dictionary (
    client_id  TEXT NOT NULL,
    word       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (client_id, word)
) WITHOUT ROWID;
"""


@dataclass(slots=True, frozen=True)
class StoredSession:
    id: int
    created_at: str
    prompt_id: str
    text: str
    events: list[InputEvent]


@dataclass(slots=True, frozen=True)
class SessionRow:
    id: int
    created_at: str
    prompt_id: str
    text: str
    overall_wpm: float | None
    burst_wpm: float | None
    pause_share: float
    backspaces_per_100_keys: float


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(
        self,
        client_id: str,
        prompt_id: str,
        text: str,
        events: list[InputEvent],
        analysis: Analysis,
    ) -> tuple[int, str]:
        s = analysis.summary
        events_json = json.dumps([e.model_dump(mode="json") for e in events])
        with self._connect() as db:
            row = db.execute(
                """INSERT INTO sessions (client_id, prompt_id, text, events_json, overall_wpm,
                       burst_wpm, pause_share, backspaces_per_100_keys)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   RETURNING id, created_at""",
                (
                    client_id,
                    prompt_id,
                    text,
                    events_json,
                    s.overall_wpm,
                    s.burst_wpm,
                    s.pause_share,
                    s.backspaces_per_100_keys,
                ),
            ).fetchone()
        return row["id"], row["created_at"]

    def get(self, client_id: str, session_id: int) -> StoredSession | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id, created_at, prompt_id, text, events_json FROM sessions "
                "WHERE id = ? AND client_id = ?",
                (session_id, client_id),
            ).fetchone()
        if row is None:
            return None
        events = [InputEvent.model_validate(e) for e in json.loads(row["events_json"])]
        return StoredSession(row["id"], row["created_at"], row["prompt_id"], row["text"], events)

    def recent(self, client_id: str, limit: int = 20) -> list[SessionRow]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, created_at, prompt_id, text, overall_wpm, burst_wpm, pause_share, "
                "backspaces_per_100_keys FROM sessions WHERE client_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (client_id, limit),
            ).fetchall()
        return [SessionRow(**dict(r)) for r in rows]

    def delete(self, client_id: str, session_id: int) -> bool:
        with self._connect() as db:
            cur = db.execute(
                "DELETE FROM sessions WHERE id = ? AND client_id = ?", (session_id, client_id)
            )
        return cur.rowcount > 0

    def words(self, client_id: str) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT word FROM dictionary WHERE client_id = ? ORDER BY word", (client_id,)
            ).fetchall()
        return [r["word"] for r in rows]

    def add_word(self, client_id: str, word: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO dictionary (client_id, word) VALUES (?, ?)",
                (client_id, word.lower()),
            )

    def remove_word(self, client_id: str, word: str) -> bool:
        with self._connect() as db:
            cur = db.execute(
                "DELETE FROM dictionary WHERE client_id = ? AND word = ?",
                (client_id, word.lower()),
            )
        return cur.rowcount > 0
