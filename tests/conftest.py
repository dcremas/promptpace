import os

import psycopg

from app.storage import Store

# A scratch database the tests may wipe. Create it once with: createdb promptpace_test
TEST_DATABASE_URL = os.environ.get("PROMPTPACE_TEST_DATABASE_URL", "postgresql:///promptpace_test")


def fresh_store() -> Store:
    """A Store on the test database, refusing any database not named *_test."""
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        name = conn.info.dbname
    if not name.endswith("_test"):
        raise RuntimeError(f"Refusing to run tests against {name!r}: the name must end in _test")
    return Store(TEST_DATABASE_URL)


def wipe(store: Store) -> None:
    with store.pool.connection() as db:
        db.execute("TRUNCATE sessions, dictionary RESTART IDENTITY")
