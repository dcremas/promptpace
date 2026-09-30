# PromptPace

A small web app that gives you a prompt-writing task (for example, *"Ask an AI to help you plan a
kitchen remodel"*), records the timing of every edit while you write, and reports:

| Metric | How it's measured |
|---|---|
| **Overall WPM** | Final text length ÷ 5, over the time from your first keystroke to your last |
| **Burst speed** | Characters typed during *active* stretches ÷ 5, over active time only. A gap shorter than the pause threshold (2 s by default) counts as active |
| **Time paused to think** | Total of all gaps at or above the threshold, with count, longest pause, share of writing time, and a breakdown by length |
| **Backspacing** | Delete presses per 100 keystrokes, plus the share of typed characters you removed |
| **Spelling accuracy** | Share of checked words in your final text that are spelled correctly |
| **Net WPM** | Like a typing test: overall WPM minus one word per misspelling left in the final text |

After each session, **Review your writing** highlights misspellings (with suggestions) and a few
mechanics issues: repeated words ("the the"), a lowercase "i", sentences that start lowercase, and
a missing space after punctuation. Only misspellings count against accuracy. **Add to dictionary**
stops a word being flagged in that browser, and re-scores past sessions too.

It also shows a typing-rhythm chart (speed over time, pauses shaded, deletions marked), gives
plain-language takeaways ("if you typed 20 WPM faster, you'd save N seconds"), and keeps a
per-browser history. You can change the pause threshold after a session and the server
re-analyzes the stored keystrokes. Thinking time before the first keystroke is reported
separately, and pasted text is left out of the speed numbers.

## Stack

- **Python 3.14** (3.13+ supported), **FastAPI** + **Pydantic v2**, served by **uvicorn**
- **symspellpy** for spell-checking (Symmetric Delete algorithm, 83k-word frequency dictionary,
  about 44 MB of memory per worker)
- **SQLite** (stdlib, WAL mode) for session history. No database server needed
- Plain HTML/CSS/JS frontend (no build step, no CDN), with the chart drawn as inline SVG
- **uv** for dependencies, **ruff** for lint/format, **pytest** for tests

```
app/
  main.py      routes, anonymous per-browser cookie
  metrics.py   the analysis: pure functions over the recorded events
  models.py    request/response schemas
  prompts.py   the task bank (edit to add your own)
  spelling.py  spell-check and mechanics rules
  data/extra_words.txt  modern words the base dictionary lacks (async, onboarding, emoji, ...)
  storage.py   SQLite persistence
  static/      index.html, styles.css, app.js
deploy/        nginx site + systemd unit
tests/
```

## Run locally

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Or with plain pip:

```bash
python3.14 -m venv .venv
.venv/bin/pip install fastapi pydantic "uvicorn[standard]" symspellpy pytest httpx2 ruff
.venv/bin/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Interactive API docs are at `/api/docs`.

```bash
uv run pytest          # or .venv/bin/pytest
uv run ruff check .
```

## Deploy to EC2 behind nginx

These steps assume Ubuntu with nginx already installed. Notes for Amazon Linux are below.

**1. Create a service user and copy the code**

```bash
# on the server
sudo useradd --system --home /opt/promptpace --shell /usr/sbin/nologin promptpace
sudo mkdir -p /opt/promptpace && sudo chown $USER /opt/promptpace

# from your machine
rsync -av --exclude .venv --exclude /data --exclude '__pycache__' ./ ubuntu@YOUR_EC2:/opt/promptpace/
```

**2. Install Python 3.14 and dependencies with uv**

Keep uv's Python inside `/opt/promptpace` so the sandboxed service can read it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /opt/promptpace
UV_PYTHON_INSTALL_DIR=/opt/promptpace/.python ~/.local/bin/uv sync --no-dev --python 3.14
sudo chown -R promptpace:www-data /opt/promptpace
```

**3. Start the app with systemd**

```bash
sudo cp deploy/promptpace.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now promptpace
systemctl status promptpace          # should be "active (running)"
```

uvicorn listens on the unix socket `/run/promptpace/uvicorn.sock`. The database lives at
`/var/lib/promptpace/promptpace.db`.

**4. Point nginx at it**

Edit `server_name` in `deploy/nginx.conf`, then:

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/promptpace
sudo ln -s /etc/nginx/sites-available/promptpace /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d typing.example.com   # HTTPS (recommended)
```

Make sure the EC2 security group allows inbound 80/443.

The service sets `PROMPTPACE_SECURE_COOKIES=1`, which marks the history cookie as HTTPS-only.
If you run over plain HTTP for a while, remove that line from the unit file or history won't
persist between page loads.

**Updating later:** rsync the code again, run `uv sync --no-dev`, then
`sudo systemctl restart promptpace`.

**Amazon Linux 2023:** nginx runs as `nginx` (not `www-data`) and there is no
`sites-available` or `proxy_params`. Set `Group=nginx` in the unit file, put the site in
`/etc/nginx/conf.d/promptpace.conf`, and replace each `include /etc/nginx/proxy_params;` with:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PROMPTPACE_DB` | `./data/promptpace.db` | SQLite file path |
| `PROMPTPACE_SECURE_COOKIES` | `0` | `1` marks the history cookie as HTTPS-only |

## How spell-checking works

The final text is checked when you press **Finish**. Browser spell-check is turned off in the text
box while you type, as on typing-test sites, so the score reflects your own spelling. To keep false
positives rare, the checker:

- skips URLs, email addresses, file names and paths, `inline code`, and fenced code blocks
- skips acronyms (API, SQL), camelCase and mixed-case words (iPhone, JavaScript), identifiers with
  digits or underscores, and capitalized words mid-sentence (usually names, such as Dmitri or Houzz)
- accepts contractions (don't, I'm, we'd), possessives, and regular plurals
- counts a word as misspelled only when the dictionary has a close suggestion (up to two edits).
  Words with no close match are listed as "not in dictionary" but not counted

If a word your team uses a lot keeps getting flagged, add it to `app/data/extra_words.txt` for
everyone, or use **Add to dictionary** for yourself.

Grammar checking is limited to the simple rules above. For full grammar checking you could run
[LanguageTool](https://languagetool.org/) as a separate service, but it needs Java and about 1 GB
of RAM, which is a lot for a small EC2 instance.

## How the recording works

The browser listens to the text box's `input` events (not raw key presses), so it measures what
actually changed. That means word-deletes, selection replacement, autocorrect, and IME input
are all counted correctly. Each edit is sent as `{t, kind, added, removed}`, where `t` is
milliseconds since the task appeared. Nothing is sent until you press **Finish**. Sessions are
tied to an anonymous random cookie, not to an account.
