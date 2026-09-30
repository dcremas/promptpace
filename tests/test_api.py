import pytest
from fastapi.testclient import TestClient

from app import main
from tests.conftest import fresh_store, wipe


@pytest.fixture
def client(monkeypatch):
    store = fresh_store()
    monkeypatch.setattr(main, "store", store)
    # The app's lifespan opens (and at exit closes) the store; wipe it once it's open.
    with TestClient(main.app) as c:
        wipe(store)
        yield c


def body(prompt_id: str, n: int = 120) -> dict:
    return {
        "prompt_id": prompt_id,
        "text": "x" * n,
        "events": [{"t": 1000 + i * 180, "kind": "type", "added": 1} for i in range(n)],
    }


def test_index_and_static(client):
    assert "PromptPace" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}


def test_index_versions_assets_and_is_never_stale(client):
    res = client.get("/")
    assert res.headers["cache-control"] == "no-cache"
    for name in main.VERSIONED_ASSETS:
        assert f"static/{name}?v=" in res.text
        assert f'static/{name}"' not in res.text
    # Monitors and link previews send HEAD.
    assert client.head("/").status_code == 200
    assert client.head("/healthz").status_code == 200


def test_random_prompt_respects_exclude(client):
    first = client.get("/api/prompts/random").json()
    for _ in range(10):
        assert client.get(f"/api/prompts/random?exclude={first['id']}").json()["id"] != first["id"]


def test_prompt_ids_are_unique(client):
    prompts = client.get("/api/prompts").json()
    assert len({p["id"] for p in prompts}) == len(prompts) > 20


def test_session_roundtrip_and_reanalysis(client):
    prompt = client.get("/api/prompts/random").json()
    res = client.post("/api/sessions", json=body(prompt["id"]))
    assert res.status_code == 201
    created = res.json()
    assert created["analysis"]["summary"]["burst_wpm"] == pytest.approx(66.7, abs=0.1)
    assert "pp_cid" in res.cookies

    history = client.get("/api/sessions").json()
    assert [h["id"] for h in history] == [created["id"]]

    again = client.get(f"/api/sessions/{created['id']}?pause_threshold_ms=5000").json()
    assert again["analysis"]["pause_threshold_ms"] == 5000

    assert client.delete(f"/api/sessions/{created['id']}").status_code == 204
    assert client.get("/api/sessions").json() == []


def test_history_is_private_per_browser(client):
    prompt = client.get("/api/prompts/random").json()
    created = client.post("/api/sessions", json=body(prompt["id"])).json()
    client.cookies.clear()
    assert client.get("/api/sessions").json() == []
    assert client.get(f"/api/sessions/{created['id']}").status_code == 404


def test_rejects_bad_input(client):
    assert client.post("/api/sessions", json=body("nope")).status_code == 422
    prompt = client.get("/api/prompts/random").json()
    empty = {"prompt_id": prompt["id"], "text": "", "events": []}
    assert client.post("/api/sessions", json=empty).status_code == 422


def test_dictionary_changes_rescore_a_session(client):
    prompt = client.get("/api/prompts/random").json()
    text = "Ask the dispatchr service to list open itmes for the team today."
    events = [{"t": 1000 + i * 180, "kind": "type", "added": 1} for i in range(len(text))]
    created = client.post(
        "/api/sessions", json={"prompt_id": prompt["id"], "text": text, "events": events}
    ).json()
    acc = created["analysis"]["accuracy"]
    assert acc["misspelled"] == 2
    assert {i["text"] for i in acc["issues"]} == {"dispatchr", "itmes"}
    assert client.get("/api/sessions").json()[0]["spelling_accuracy"] < 1

    assert client.put("/api/dictionary/Dispatchr").status_code == 204
    assert client.put("/api/dictionary/dispatchr").status_code == 204  # idempotent
    assert client.get("/api/dictionary").json() == ["dispatchr"]
    again = client.get(f"/api/sessions/{created['id']}").json()["analysis"]["accuracy"]
    assert [i["text"] for i in again["issues"]] == ["itmes"]

    assert client.delete("/api/dictionary/dispatchr").status_code == 204
    assert client.delete("/api/dictionary/dispatchr").status_code == 404
    assert client.get("/api/dictionary").json() == []


def test_dictionary_rejects_non_words(client):
    assert client.put("/api/dictionary/rm%20-rf").status_code == 422
    assert client.put("/api/dictionary/" + "a" * 60).status_code == 422
