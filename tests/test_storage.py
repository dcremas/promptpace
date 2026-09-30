import re

from app.metrics import analyze
from app.models import EventKind, InputEvent
from tests.conftest import fresh_store, wipe


def test_migrations_are_idempotent_and_recorded():
    store = fresh_store()
    store.init()
    store.init()  # a second worker starting up must be a no-op
    with store.pool.connection() as db:
        versions = [r["version"] for r in db.execute("SELECT version FROM schema_migrations")]
    store.close()
    assert versions == list(range(1, len(versions) + 1))


def test_session_roundtrip_keeps_events_and_api_timestamp_format():
    store = fresh_store()
    store.init()
    wipe(store)
    events = [
        InputEvent(t=1000.5, kind=EventKind.TYPE, added=1),
        InputEvent(t=1200, kind=EventKind.PASTE, added=12),
        InputEvent(t=1500, kind=EventKind.DELETE, removed=1),
    ]
    sid, created = store.add("c" * 32, "p", "hello", events, analyze(events, "hello"))
    got = store.get("c" * 32, sid)
    other = store.get("d" * 32, sid)  # another browser can't read it
    store.close()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", created)
    assert got.created_at == created
    assert got.events == events
    assert other is None
