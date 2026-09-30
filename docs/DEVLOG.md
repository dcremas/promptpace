# PromptPace development log

## Current status (as of 2026-09-30, end of session 2)

- **Live** at https://typing.dustincremascoli.com on the EC2 box (systemd `promptpace`, 2 uvicorn
  workers on a unix socket, PostgreSQL `promptpace` database, Let's Encrypt HTTPS). See
  "Deploy checklist" below for what was done on the server.
- **Tests**: 50 pass (needs local Postgres), ruff and `node --check` are clean.
- **Git**: `main` is pushed to the public repo github.com/dcremas/promptpace. Keep host IPs, key
  paths and passwords out of it.
- **Footer row is eight links** (Main site, Data Viz, SQL Explorer, Weather API, Football SQL,
  Play Explorer, PromptPace, Recipes), matching `ec2-nginx/prosite_flask/content.py` SITES. Merged,
  pushed and deployed on every estate site (2026-09-30).
- The local dev DB is Postgres `promptpace` (Homebrew); `data/promptpace.db` is the old SQLite
  file and can be deleted.

### How to resume

```bash
cd ~/projects/typing
.venv/bin/uvicorn app.main:app --reload     # open http://127.0.0.1:8000
.venv/bin/pytest                            # expect 50 passed
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
| PostgreSQL, own `promptpace` database (was SQLite until 2026-09-30) | The owner already runs and backs up Postgres on the VM for their other sites; one database to operate, and the data can be queried alongside the other apps | Keeping SQLite plus a separate backup job |
| psycopg 3 pool + numbered migrations in storage.py, run under an advisory lock | Two workers start at once; no ORM or Alembic needed for three tables | SQLAlchemy + Alembic (heavy for this) |
| Anonymous cookie, no accounts | Private history without sign-up | Auth (not requested) |
| symspellpy, `prefix_length=5` | Best suggestions (29/30 top-1 in a trial), 0.2 ms/word, 44 MB | pyspellchecker (136 ms/word, worse ranking); LanguageTool (Java, ~1 GB RAM) |
| Supplemental word list over the pyspellchecker vocabulary | The extra 80k words were obscure (would let typos pass) and still missed modern words | Union of both dictionaries |
| Count only words with a close suggestion | Unmatched words are usually jargon or names; keeps the score fair | Flag every unknown word |
| Mechanics issues shown but not scored | People write prompts casually; don't penalize style | Folding them into accuracy |
| Enter finishes a test; Shift+Enter is a newline (⌘/Ctrl+Enter also works) | Matches AI chat boxes; reaching for the mouse broke flow. Timing already ends at the last edit, so the click never counted | ⌘/Ctrl+Enter only (hint on the button was easy to miss) |
| Content-hashed asset URLs, index sent `no-cache`, `/static/` cached 1 year | Browsers heuristically cached styles.css with no revalidation, so a refresh paired new HTML with old CSS | Short `expires` (still stale for up to an hour after a deploy) |
| Footer and header byline mirror the other dustincremascoli.com sites | The owner wants every property to read as one portfolio | A one-off credit line |
| No footer link to /api/docs | Production CSP blocks Swagger UI's CDN scripts, so the page would render blank | Loosening CSP for one page |
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

- [x] Server OS: Amazon Linux 2023 (checked over `ssh awsvm` on 2026-09-30). nginx user `nginx`,
      sites in /etc/nginx/conf.d/, no proxy_params, certbot installed. Postgres 16.15.
- [x] Domain: typing.dustincremascoli.com (needs a DNS record before certbot).
- [x] Role `promptpace` and database `promptpace` (owner promptpace, UTF8, C) created by the owner.
- [x] Backups: the box's nightly `pg-backup` (03:18 UTC, to S3) dumps every database and all roles.
- [x] README steps 1-3 run on 2026-09-30: system user `promptpace` (uid 983), code in
      /opt/promptpace (owned by ec2-user), uv 0.12.21 + Python 3.14.7 venv, role password set,
      /etc/promptpace/promptpace.env (root:promptpace 0640). Verified: the service user connects
      over the socket and can create tables. pg_hba.conf needs scram for local roles, hence the
      password. uv.lock came from that server sync.
- [x] Service installed and running (2026-09-30): 2 workers, ~212 MB total (box has 3.8 GB),
      migration 1 applied once, save/history/re-analyze/delete verified over the socket.
- [x] nginx site at /etc/nginx/conf.d/promptpace.conf; `nginx -t` passed; reloaded. www/recipes/
      sql/api returned 200 before and after. DNS already resolves typing. to the box.
- [x] Certificate preflight (2026-09-30): own A record at GoDaddy (no wildcard), no AAAA, no CAA;
      port 80 public; shared webroot /var/www/letsencrypt location added (matches the other
      sites) and verified from outside; `certbot certonly --webroot --dry-run` succeeded;
      certbot-renew.timer active.
- [x] HTTPS live (2026-09-30): Let's Encrypt cert (issuer YE2) valid to 2026-12-29, renewed by
      certbot-renew.timer (`certbot renew --dry-run` passed). deploy/nginx.conf is now the exact
      live file: port-80 block (acme webroot + 301), 443 block with http2 + HSTS like the other
      sites. Backups of the earlier versions sit next to it in conf.d as *.bak-* (not loaded).
      Browser check over HTTPS: session saved, History survived a reload, deleted; prod DB empty. Until then HTTP works but History
      doesn't persist, because the cookie is `Secure`.
- [x] `GRANT promptpace TO dustincremascoli` (2026-09-30), so the owner's pgAdmin login has full
      access. The app owns its tables (it creates them via migrations), unlike recipes/weatherdata,
      where dustincremascoli owns the tables and grants the app role access.
- [x] `REVOKE CONNECT ON DATABASE promptpace FROM PUBLIC` (2026-09-30). Only promptpace,
      dustincremascoli (via membership) and postgres can connect; a probe role was refused.
      Network audit the same day: 5432 closed from the internet; SG allows 5432 only from the
      awk/ghcnh ETL Lambda SGs; nftables only from 172.31.0.0/16; pg_hba allows non-local logins
      only for awk_etl and ghcnh_etl over SSL; SSH key-only with fail2ban.
- [x] Add PromptPace to the "Everything here" footer and nav on the other dustincremascoli.com
      sites (2026-09-30). The row is now eight links on every copy (`ec2-nginx/check-footer-nav.sh`
      reports all 7 agree; the typing and pbp copies are outside it). Merged to `main` and pushed
      in typing, prosite_flask, recipes_flask, restapi_flask, weather-sql-explorer, weblog_flask
      and pbp; ec2-nginx `main` is local only (no remote).
- [x] **Footer change deployed** (2026-09-30) to all seven apps: typing, prosite (`--with-viz`),
      recipes, restapi, sql-explorer, the analytics dashboard, and pbp (explorer + /plays/).
      Previewed first with `rsync -nc` (only the footer files changed; nothing deleted). Verified
      afterwards: www., recipes., api./docs, typing. and pbp./plays/ all render the eight links,
      the Streamlit/Bokeh copies on the box carry them, and all 13 services are active.
      Unrelated finding: the weather-mcp selftest is 60/61, failing "every table carries a
      description" (a warehouse table without a COMMENT; the deploy didn't touch mcp_server).

## Environment snapshot (versions verified working)

- macOS (Darwin 25.6), zsh, Python 3.14.7 (pyenv), Node available (used only for `node --check`)
- PostgreSQL 18.6 (Homebrew) locally, databases `promptpace` and `promptpace_test`
- psycopg 3.3.6 (binary, libpq 18) · psycopg-pool 3.3.3
- fastapi 0.142.2 · starlette 1.7.0 · pydantic 2.13.5 · uvicorn 0.54.0 (uvloop 0.22.1,
  httptools 0.8.0, watchfiles 1.3.0, websockets 17.1) · symspellpy 6.10.0
- Dev tools: pytest 9.1.1 · httpx2 2.13.1 · ruff 0.16.9
- The venv also has the `fastapi[standard]` extras (fastapi-cli etc.) from the first install. They
  aren't required.
