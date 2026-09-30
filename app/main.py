"""PromptPace: a typing-rhythm coach for prompt writing."""

import os
import random
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import spelling
from app.metrics import analyze
from app.models import Prompt, SessionIn, SessionListItem, SessionOut
from app.prompts import PROMPTS
from app.storage import Store

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_DB = Path(__file__).parent.parent / "data" / "promptpace.db"
DB_PATH = Path(os.environ.get("PROMPTPACE_DB", DEFAULT_DB))
SECURE_COOKIES = os.environ.get("PROMPTPACE_SECURE_COOKIES", "0") == "1"
COOKIE = "pp_cid"
COOKIE_RE = re.compile(r"^[0-9a-f]{32}$")

store = Store(DB_PATH)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    spelling.warm()
    yield


app = FastAPI(
    title="PromptPace",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def client_id(request: Request, response: Response) -> str:
    """Anonymous per-browser id, so each visitor sees only their own history."""
    cid = request.cookies.get(COOKIE, "")
    if not COOKIE_RE.match(cid):
        cid = uuid.uuid4().hex
        response.set_cookie(
            COOKIE,
            cid,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="lax",
            secure=SECURE_COOKIES,
        )
    return cid


ClientId = Annotated[str, Depends(client_id)]
Threshold = Annotated[int, Query(ge=500, le=10_000)]
Word = Annotated[str, PathParam(pattern=r"^[A-Za-z][A-Za-z'’-]{0,39}$")]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/prompts")
def list_prompts() -> list[Prompt]:
    return list(PROMPTS.values())


@app.get("/api/prompts/random")
def random_prompt(exclude: str | None = None) -> Prompt:
    choices = [p for p in PROMPTS.values() if p.id != exclude]
    return random.choice(choices)


def _prompt(prompt_id: str) -> Prompt:
    if (prompt := PROMPTS.get(prompt_id)) is None:
        raise HTTPException(422, f"Unknown prompt {prompt_id!r}")
    return prompt


@app.post("/api/sessions", status_code=201)
def create_session(body: SessionIn, cid: ClientId) -> SessionOut:
    prompt = _prompt(body.prompt_id)
    analysis = analyze(body.events, body.text, body.pause_threshold_ms, store.words(cid))
    session_id, created_at = store.add(cid, prompt.id, body.text, body.events, analysis)
    return SessionOut(
        id=session_id, created_at=created_at, prompt=prompt, text=body.text, analysis=analysis
    )


@app.get("/api/sessions")
def list_sessions(cid: ClientId) -> list[SessionListItem]:
    items = []
    words = store.words(cid)
    for row in store.recent(cid):
        prompt = PROMPTS.get(row.prompt_id)
        items.append(
            SessionListItem(
                id=row.id,
                created_at=row.created_at,
                prompt_category=prompt.category if prompt else "Retired",
                prompt_text=prompt.text if prompt else row.prompt_id,
                overall_wpm=row.overall_wpm,
                burst_wpm=row.burst_wpm,
                pause_share=row.pause_share,
                backspaces_per_100_keys=row.backspaces_per_100_keys,
                spelling_accuracy=spelling.check(row.text, words).spelling_accuracy,
            )
        )
    return items


@app.get("/api/sessions/{session_id}")
def get_session(session_id: int, cid: ClientId, pause_threshold_ms: Threshold = 2000) -> SessionOut:
    """Fetch a past session, re-analyzed at the requested pause threshold."""
    if (s := store.get(cid, session_id)) is None:
        raise HTTPException(404, "Session not found")
    prompt = PROMPTS.get(s.prompt_id) or Prompt(
        id=s.prompt_id, category="Retired", text=s.prompt_id
    )
    return SessionOut(
        id=s.id,
        created_at=s.created_at,
        prompt=prompt,
        text=s.text,
        analysis=analyze(s.events, s.text, pause_threshold_ms, store.words(cid)),
    )


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, cid: ClientId) -> None:
    if not store.delete(cid, session_id):
        raise HTTPException(404, "Session not found")


@app.get("/api/dictionary")
def list_words(cid: ClientId) -> list[str]:
    """Words this browser has added, which are never flagged as misspelled."""
    return store.words(cid)


@app.put("/api/dictionary/{word}", status_code=204)
def add_word(word: Word, cid: ClientId) -> None:
    store.add_word(cid, word)


@app.delete("/api/dictionary/{word}", status_code=204)
def remove_word(word: Word, cid: ClientId) -> None:
    if not store.remove_word(cid, word):
        raise HTTPException(404, "Word not in dictionary")
