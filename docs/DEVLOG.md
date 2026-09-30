# PromptPace development log

## Current status (as of 2026-09-30, end of session 1)

- **Works locally and fully tested**: 46 automated tests pass, ruff is clean, and the app was
  checked in Chrome (light, dark, and 390 px phone width).
- **Not yet deployed to EC2.** The deploy files are written, but nothing has been run on the
  server. See "Deploy checklist" below.
- **Git**: the repo was initialized at the end of session 1 with everything committed on `main`.
  There is no remote yet.
- **uv is not installed on this Mac.** Development used a plain venv (`.venv`). `uv.lock` doesn't
  exist yet; running `uv sync` once will create it (then commit it).
- The local dev DB (`data/promptpace.db`, gitignored) was reset to empty at the end of the session.

### How to resume

```bash
cd ~/projects/typing
.venv/bin/uvicorn app.main:app --reload     # open http://127.0.0.1:8000
.venv/bin/pytest                            # expect 46 passed
```

If the venv is ever lost: `python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
pytest httpx2 ruff`.

---

## Origin

The owner asked for a web app, built with the most up-to-date Python libraries and runtime, that
could eventually run on their nginx server on an AWS EC2 VM. The spec came from an earlier
Claude.ai conversation. Paraphrased: a small page gives you a prompt-writing task, such as "Ask an
AI to help you plan a kitchen remodel", lets you write your response, and reports your overall
WPM, your burst speed while actively typing, how much time you spent pausing to think, and how
often you backspaced.

Follow-up request: add spell-checking "like typing.com" does.

## Session 1, part 1: core app

Built:
- FastAPI backend, SQLite history, and a vanilla-JS frontend.
- Four headline metrics, plus peak burst, pause-length bands, and time before the first keystroke.
- A typing-rhythm SVG chart: WPM columns per time bucket, pauses shaded, a deletion lane, hover
  tooltips, and a table view.
- Plain-language insights, including an estimate of time saved at +20 WPM burst speed.
- Per-browser history via an anonymous cookie.
- A pause-threshold selector that re-analyzes the stored events on the server.
- nginx and systemd deploy files, and a README.

Bugs found in browser testing and fixed:
1. The results section showed before any typing, because `.results{display:grid}` overrode
   `[hidden]`.
2. Typing could be wiped if the task fetch finished after the user started typing. Fixed by
   disabling the textarea until the task loads.
3. "9 presss". `plural()` now accepts an irregular plural.
4. The chart's "WPM" axis label collided with the "100" tick.
5. At 390 px the page was 767 px wide: grid items took the history table's min-content width.
   Fixed with `minmax(0,1fr)`.
6. "13 s" wrapped between the number and the unit. Now uses a non-breaking space.

## Session 1, part 2: spell-checking and accuracy

Built:
- `app/spelling.py`, which adds spelling accuracy and net WPM.
- A "Review your writing" panel: highlighted text, an issue list with suggestions, and "Add to
  dictionary".
- A per-browser dictionary (table and API) that re-scores open and past sessions.
- A Spelling column in History.
- Mechanics checks: repeated word, lowercase "i", lowercase sentence start, missing space after
  punctuation. These are shown but not scored.
- Browser spell-check is turned off in the textarea while typing.

Verified in the browser: a planted-error kitchen-remodel prompt had all 8 mistakes caught (4
spelling, 4 mechanics), with zero false positives on "Dmitri", "Houzz", "countertops",
"backsplash", "$25,000", and "step-by-step". Add and remove in the dictionary updated the score
(93.2% → 94.9% → 93.2%) and the History row, without scrolling the page.

## Key decisions and why

| Decision | Why | Alternatives rejected |
|---|---|---|
| FastAPI + Pydantic v2 on Python 3.14 | Current, typed, fast; schemas double as API docs | Litestar (smaller ecosystem), Django (heavy for this) |
| uvicorn behind nginx on a unix socket | Standard, reliable with nginx; no open port | Granian (newer, less proven with this setup) |
| Metrics computed server-side in pure functions | Re-analysis at any threshold; testable; the "Python" part is real | JS-only metrics |
| Record `input` events, not `keydown` | Correct for word-delete, selection replace, IME, autocorrect, paste | keydown, which miscounts those |
| SQLite (stdlib) | Zero ops on a single VM | Postgres (overkill) |
| Anonymous cookie, no accounts | Private history without sign-up | Auth (not requested) |
| symspellpy, `prefix_length=5` | Best suggestions (29/30 top-1 in a trial), 0.2 ms/word, 44 MB | pyspellchecker (136 ms/word, worse ranking); LanguageTool (Java, ~1 GB RAM) |
| Supplemental word list over the pyspellchecker vocabulary | The extra 80k words were obscure (would let typos pass) and still missed modern words | Union of both dictionaries |
| Count only words with a close suggestion | Unmatched words are usually jargon or names; keeps the score fair | Flag every unknown word |
| Mechanics issues shown but not scored | People write prompts casually; don't penalize style | Folding them into accuracy |
| Browser spell-check off while typing | Matches typing-test convention; the score reflects the user | Leaving squiggles on (a one-attribute revert in index.html) |

## Spell-checker evaluation data (for tuning later)

A trial with 30 common typos and about 200 words of clean prompt text:
- symspell d=2, prefix 7: 142 MB, 1.74 s load, 29/30 top-1
- symspell d=2, prefix 5: 44 MB, 0.73 s load, 29/30 top-1 ← chosen
- symspell d=1, prefix 7: 69 MB, 0.53 s load, 26/30 top-1
- Before the supplemental list, both libraries falsely flagged async, backsplash, copays,
  countertops, hardcoded, and Postgres.
- "calender" is not flagged because it's a real word (a pressing machine). Real-word errors are
  out of scope.

## Known limitations

- **Real-word errors** (form/from, their/there, then/than) aren't caught. That needs a grammar
  engine.
- Misspelled **names mid-sentence** aren't flagged (proper-noun skip).
- **English only.**
- A capitalized unknown word at the start of a sentence is checked (for example, "Kubernetes is…"
  could be listed as unknown). It's never counted unless a close suggestion exists.
- Sentence-case checking ignores line starts (so lists aren't flagged), which means a real
  sentence after a line break isn't checked either.
- The history list recomputes spelling accuracy for 20 sessions on every load. That's fine at this
  scale; cache it if history grows.
- Each browser has its own history. Clearing cookies loses access to the sessions (the rows stay
  in the DB).
- Per-bucket WPM in the chart is jagged by nature (1–2 s buckets).
- Live typing at human speed through the Chrome automation tool couldn't be tested (it types
  instantly, and background tabs throttle timers). **A real manual session is still worth doing.**

## Next-step ideas (roughly by value)

1. **Deploy to EC2** (checklist below) and do a real manual typing session there.
2. `uv sync` locally to create and commit `uv.lock`.
3. Trends view: overall, burst, and accuracy over the last N sessions (a line chart; follow the
   dataviz skill).
4. A custom-task option ("write your own prompt") and more tasks in `app/prompts.py`.
5. Optional LanguageTool integration for real grammar, only if the EC2 instance has RAM to spare.
   Put it behind a feature flag and call it from `spelling.py`.
6. Export history as CSV.
7. An optional "live mistakes" mode that highlights errors while typing (would need an
   overlay-based editor, not a plain textarea).
8. Optional accounts, if history needs to follow a person across devices.

## Deploy checklist (EC2 + nginx)

Full commands are in README.md, "Deploy to EC2 behind nginx".

- [ ] Find out the server OS (Ubuntu vs Amazon Linux 2023). The README has notes for both;
      Amazon Linux needs `Group=nginx` and inline proxy headers.
- [ ] Choose a domain or subdomain and set `server_name` in `deploy/nginx.conf`.
- [ ] Create the `promptpace` system user and `/opt/promptpace`; rsync the code (exclude .venv
      and /data, with the leading slash, or `app/data/` gets skipped too).
- [ ] Install uv and run `UV_PYTHON_INSTALL_DIR=/opt/promptpace/.python uv sync --no-dev
      --python 3.14`.
- [ ] Install and start `deploy/promptpace.service`. It runs 2 uvicorn workers on
      `/run/promptpace/uvicorn.sock`, and the DB is at `/var/lib/promptpace/promptpace.db`.
- [ ] Install the nginx site, run `nginx -t`, and reload.
- [ ] Open ports 80/443 in the security group; run `certbot --nginx -d <domain>`.
- [ ] Keep `PROMPTPACE_SECURE_COOKIES=1` only once HTTPS works (otherwise history won't persist).
- [ ] Memory budget: about 44 MB for the dictionary plus about 40 MB base per worker, so roughly
      170 MB for 2 workers. Fine on a t3.micro (1 GB).

## Environment snapshot (versions verified working)

- macOS (Darwin 25.6), zsh, Python 3.14.7 (pyenv), Node available (used only for `node --check`)
- fastapi 0.142.2 · starlette 1.7.0 · pydantic 2.13.5 · uvicorn 0.54.0 (uvloop 0.22.1,
  httptools 0.8.0, watchfiles 1.3.0, websockets 17.1) · symspellpy 6.10.0
- Dev tools: pytest 9.1.1 · httpx2 2.13.1 · ruff 0.16.9
- The venv also has the `fastapi[standard]` extras (fastapi-cli etc.) from the first install. They
  aren't required.
