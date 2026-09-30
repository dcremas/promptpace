"""PostgreSQL persistence for finished sessions and per-browser dictionaries."""

from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.models import Analysis, InputEvent

# Schema changes, applied in order and recorded in schema_migrations. Never edit an entry that has
# shipped; append a new one instead.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE sessions (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        client_id   text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now(),
        prompt_id   text NOT NULL,
        text        text NOT NULL,
        events      jsonb NOT NULL,
        overall_wpm double precision,
        burst_wpm   double precision,
        pause_share double precision NOT NULL,
        backspaces_per_100_keys double precision NOT NULL
    );
    CREATE INDEX ix_sessions_client ON sessions (client_id, id DESC);
    CREATE TABLE dictionary (
        client_id  text NOT NULL,
        word       text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (client_id, word)
    );
    """,
)

# Arbitrary key for pg_advisory_xact_lock, so two workers starting at once can't both migrate.
_MIGRATION_LOCK = 7_265_310_416


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


def _iso(ts: datetime) -> str:
    """The API's timestamp format: UTC, second precision, trailing Z."""
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, url: str) -> None:
        self.url = url
        self.pool = ConnectionPool(
            url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
            # Replace connections that died (e.g. Postgres restarted) before handing them out.
            check=ConnectionPool.check_connection,
            name="promptpace",
        )

    def init(self) -> None:
        """Open the pool and bring the schema up to date."""
        self.pool.open(wait=True, timeout=10)
        with self.pool.connection() as db, db.transaction():
            db.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            row = db.execute(
                "SELECT coalesce(max(version), 0) AS v FROM schema_migrations"
            ).fetchone()
            for version, sql in enumerate(MIGRATIONS[row["v"] :], start=row["v"] + 1):
                db.execute(sql)
                db.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))

    def close(self) -> None:
        self.pool.close()

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=2) as db:
                db.execute("SELECT 1")
        except Exception:
            return False
        return True

    def add(
        self,
        client_id: str,
        prompt_id: str,
        text: str,
        events: list[InputEvent],
        analysis: Analysis,
    ) -> tuple[int, str]:
        s = analysis.summary
        with self.pool.connection() as db:
            row = db.execute(
                """INSERT INTO sessions (client_id, prompt_id, text, events, overall_wpm,
                       burst_wpm, pause_share, backspaces_per_100_keys)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, created_at""",
                (
                    client_id,
                    prompt_id,
                    text,
                    Jsonb([e.model_dump(mode="json") for e in events]),
                    s.overall_wpm,
                    s.burst_wpm,
                    s.pause_share,
                    s.backspaces_per_100_keys,
                ),
            ).fetchone()
        return row["id"], _iso(row["created_at"])

    def get(self, client_id: str, session_id: int) -> StoredSession | None:
        with self.pool.connection() as db:
            row = db.execute(
                "SELECT id, created_at, prompt_id, text, events FROM sessions "
                "WHERE id = %s AND client_id = %s",
                (session_id, client_id),
            ).fetchone()
        if row is None:
            return None
        events = [InputEvent.model_validate(e) for e in row["events"]]
        return StoredSession(
            row["id"], _iso(row["created_at"]), row["prompt_id"], row["text"], events
        )

    def recent(self, client_id: str, limit: int = 20) -> list[SessionRow]:
        with self.pool.connection() as db:
            rows = db.execute(
                "SELECT id, created_at, prompt_id, text, overall_wpm, burst_wpm, pause_share, "
                "backspaces_per_100_keys FROM sessions WHERE client_id = %s "
                "ORDER BY id DESC LIMIT %s",
                (client_id, limit),
            ).fetchall()
        return [SessionRow(**(r | {"created_at": _iso(r["created_at"])})) for r in rows]

    def delete(self, client_id: str, session_id: int) -> bool:
        with self.pool.connection() as db:
            cur = db.execute(
                "DELETE FROM sessions WHERE id = %s AND client_id = %s", (session_id, client_id)
            )
            return cur.rowcount > 0

    def words(self, client_id: str) -> list[str]:
        with self.pool.connection() as db:
            rows = db.execute(
                "SELECT word FROM dictionary WHERE client_id = %s ORDER BY word", (client_id,)
            ).fetchall()
        return [r["word"] for r in rows]

    def add_word(self, client_id: str, word: str) -> None:
        with self.pool.connection() as db:
            db.execute(
                "INSERT INTO dictionary (client_id, word) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (client_id, word.lower()),
            )

    def remove_word(self, client_id: str, word: str) -> bool:
        with self.pool.connection() as db:
            cur = db.execute(
                "DELETE FROM dictionary WHERE client_id = %s AND word = %s",
                (client_id, word.lower()),
            )
            return cur.rowcount > 0
