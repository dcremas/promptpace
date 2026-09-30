# PromptPace: guide for Claude Code sessions

A typing-rhythm coach for **writing prompts to an AI**. The app shows a task ("Ask an AI to help
you plan a kitchen remodel"), records the timing of every edit in a text box, and reports overall
WPM, burst WPM, time paused to think, backspacing, spelling accuracy, and net WPM. The target is
the owner's own **nginx server on an AWS EC2 VM**.

**Start here when resuming:** read `docs/DEVLOG.md`. It has the build history, the reasons behind
each decision, what was tested, known limitations, and the prioritized next steps.

## Commands

```bash
# Local dev (a venv already exists at .venv with Python 3.14.7; uv is NOT installed on this Mac)
.venv/bin/uvicorn app.main:app --reload            # http://127.0.0.1:8000, API docs at /api/docs
.venv/bin/pytest                                   # 46 tests, ~2 s
.venv/bin/ruff check . && .venv/bin/ruff format .  # lint + format (line length 100)
node --check app/static/app.js                     # syntax-check the frontend (no build step)

# With uv (what the README and EC2 deploy use)
uv sync && uv run uvicorn app.main:app --reload
```

Before calling any change done, run pytest, ruff check, ruff format --check, and node --check.

## Layout

```
app/main.py          FastAPI routes; anonymous per-browser cookie `pp_cid` (dependency `client_id`)
app/metrics.py       analyze(events, text, threshold_ms, user_words) -> Analysis. Pure functions,
                     so stored sessions can be re-analyzed at any pause threshold
app/spelling.py      check(text, user_words, writing_seconds) -> Accuracy. symspellpy + skip rules
                     + mechanics rules (repeated word, lowercase i, sentence case, missing space)
app/models.py        all Pydantic request/response schemas
app/prompts.py       task bank (_TASKS dict by category; ids are slugs made from the text)
app/storage.py       SQLite (stdlib sqlite3, WAL). Tables: sessions, dictionary
app/data/extra_words.txt   modern words the base dictionary lacks (plurals are automatic)
app/static/          index.html, styles.css, app.js (vanilla ES module, no framework, no CDN)
deploy/              nginx.conf (site), promptpace.service (systemd, unix socket)
tests/               test_metrics.py, test_spelling.py, test_api.py
```

## API

| Method & path | Purpose |
|---|---|
| GET `/api/prompts`, GET `/api/prompts/random?exclude=<id>` | task bank |
| POST `/api/sessions` | body `{prompt_id, text, events[], pause_threshold_ms}` → 201 SessionOut |
| GET `/api/sessions` | this browser's last 20 sessions (spelling accuracy recomputed live) |
| GET `/api/sessions/{id}?pause_threshold_ms=` | re-analyze a stored session |
| DELETE `/api/sessions/{id}` | delete |
| GET `/api/dictionary`, PUT/DELETE `/api/dictionary/{word}` | per-browser dictionary |
| GET `/healthz` | health check |

An event is `{t, kind: "type"|"delete"|"paste", added, removed}`, where `t` is ms since the task
was shown.

## Metric definitions (keep these consistent everywhere)

- A word is 5 characters.
- **Overall WPM** = final text length / 5, over first keystroke → last keystroke.
- **Burst WPM** = characters typed during gaps below the pause threshold / 5, over active time only.
- **Pause** = a gap between edits at or above the threshold (default 2000 ms; UI offers 1–5 s).
- **Backspaces / 100 keys** = delete events / (type + delete events) × 100.
- **Spelling accuracy** = (checked words − misspelled) / checked words.
- **Net WPM** = (final chars / 5 − misspellings) / writing minutes.
- Time before the first keystroke is reported separately and excluded from every speed.
- Pastes (and undo/redo insertions) never count as typing.

## Conventions and gotchas

- **Frontend URLs are relative** (`api/...`, `static/...`) so the app works at a domain root or
  under an nginx sub-path. Keep it that way.
- **Issue offsets are UTF-16 code units** (what JS `String.slice` uses), converted in
  `spelling._utf16`. Emoji would break highlighting without this.
- CSS: `[hidden] { display: none !important; }` exists because `.results { display: grid }`
  otherwise overrides the hidden attribute. Grid containers use `grid-template-columns:
  minmax(0, 1fr)` so wide tables can't force horizontal page scroll on phones.
- Color tokens live on `:root` with dark-mode overrides in both `@media (prefers-color-scheme)`
  and `:root[data-theme="dark"]`. Chart colors come from the dataviz skill's validated palette
  (series-1 blue #2a78d6 / dark #3987e5, series-2 orange #eb6834 / dark #d95926).
- The textarea has `spellcheck="false"` on purpose, as on typing-test sites. The textarea stays
  `disabled` until a task has loaded, so a user can't type before the timer's zero point exists.
- The spell checker is tuned for **few false positives**. Only words with a suggestion within 2
  edits count as misspelled. Mid-sentence capitalized words (names) are skipped. When adding
  rules, add a case to `CLEAN_PROMPTS` in tests/test_spelling.py so accidental flags get caught.
- symspellpy uses `prefix_length=5` (44 MB instead of 142 MB per worker, same accuracy). It loads
  once in the FastAPI lifespan (`spelling.warm()`, about 0.7 s).
- The Starlette TestClient wants `httpx2`, which is installed; plain `httpx` gives a deprecation
  warning.
- The shell is **zsh**, which doesn't word-split unquoted variables (`$cfg` stays one argument).
- Browser testing with Claude in Chrome: its `type` action enters about 30 characters in 12 ms,
  and background tabs throttle `setTimeout`, so neither produces realistic timing. To test
  metrics, POST a synthesized event log with computed timestamps to `/api/sessions` from the page,
  then open the session from History.
