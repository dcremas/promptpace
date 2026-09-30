"""One-time import of sessions and dictionaries from the old SQLite store into Postgres.

    .venv/bin/python -m scripts.import_sqlite data/promptpace.db

Uses PROMPTPACE_DATABASE_URL (default postgresql:///promptpace). Keeps each row's browser id and
timestamp, so History carries over. Refuses to run if the Postgres sessions table isn't empty,
so running it twice can't duplicate anything.
"""

import json
import sqlite3
import sys
from pathlib import Path

from psycopg.types.json import Jsonb

from app.main import DATABASE_URL
from app.storage import Store


def main(sqlite_path: Path) -> None:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    store = Store(DATABASE_URL)
    store.init()
    with store.pool.connection() as db:
        if db.execute("SELECT count(*) AS n FROM sessions").fetchone()["n"]:
            sys.exit("Postgres already has sessions; not importing.")
        sessions = src.execute("SELECT * FROM sessions ORDER BY id").fetchall()
        for r in sessions:
            db.execute(
                """INSERT INTO sessions (client_id, created_at, prompt_id, text, events,
                       overall_wpm, burst_wpm, pause_share, backspaces_per_100_keys)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    r["client_id"],
                    r["created_at"],
                    r["prompt_id"],
                    r["text"],
                    Jsonb(json.loads(r["events_json"])),
                    r["overall_wpm"],
                    r["burst_wpm"],
                    r["pause_share"],
                    r["backspaces_per_100_keys"],
                ),
            )
        words = src.execute("SELECT client_id, word, created_at FROM dictionary").fetchall()
        for w in words:
            db.execute(
                "INSERT INTO dictionary (client_id, word, created_at) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (w["client_id"], w["word"], w["created_at"]),
            )
    store.close()
    print(f"Imported {len(sessions)} sessions and {len(words)} dictionary words.")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/promptpace.db"))
