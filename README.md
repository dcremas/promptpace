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
- **PostgreSQL** (its own `promptpace` database) via **psycopg 3** with a connection pool.
  The schema is created and migrated automatically at startup
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
  storage.py   PostgreSQL persistence and schema migrations
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
.venv/bin/pip install -r requirements.txt pytest httpx2 ruff
.venv/bin/uvicorn app.main:app --reload
```

It needs a local PostgreSQL with two databases, one for the app and a scratch one the tests wipe:

```bash
createdb promptpace
createdb promptpace_test
```

The tables are created on first start. Point elsewhere with `PROMPTPACE_DATABASE_URL` and
`PROMPTPACE_TEST_DATABASE_URL` (the tests refuse any database whose name doesn't end in `_test`).

Open http://127.0.0.1:8000. Interactive API docs are at `/api/docs`.

```bash
uv run pytest          # or .venv/bin/pytest
uv run ruff check .
```

## Deploy to EC2 behind nginx

These steps match the production box: **Amazon Linux 2023**, nginx running as `nginx` with sites
in `/etc/nginx/conf.d/`, PostgreSQL 16 on the same machine, and certbot.

**1. Create a service user and copy the code**

```bash
# on the server
sudo useradd --system --home-dir /opt/promptpace --shell /sbin/nologin promptpace
sudo mkdir -p /opt/promptpace && sudo chown ec2-user /opt/promptpace

# from your machine
rsync -av --exclude .venv --exclude /data --exclude __pycache__ --exclude .git \
  --exclude .pytest_cache --exclude .ruff_cache --exclude .DS_Store ./ awsvm:/opt/promptpace/
```

**2. Install Python 3.14 and dependencies with uv**

Keep uv's Python inside `/opt/promptpace` so the sandboxed service can read it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /opt/promptpace
UV_PYTHON_INSTALL_DIR=/opt/promptpace/.python ~/.local/bin/uv sync --no-dev --python 3.14
```

The code stays owned by `ec2-user` (so later rsyncs work) and world-readable; the service only
reads it. The one secret, the database password, lives in `/etc/promptpace` (step 3).

**3. Create its database and connection file**

The app has its own role and database. The server's `pg_hba.conf` requires a password for
every local role except `postgres`, so the role gets a random password that lives only in a
root-owned env file (the same pattern as `/etc/recipes/recipes.env`):

```bash
sudo -u postgres createuser promptpace
sudo -u postgres createdb --owner promptpace promptpace

PW=$(openssl rand -hex 24)     # hex, so it needs no URL escaping
printf "ALTER ROLE promptpace PASSWORD '%s';\n" "$PW" | sudo -u postgres psql -X -q
sudo install -d -m 0750 -o root -g promptpace /etc/promptpace
printf 'PROMPTPACE_DATABASE_URL=postgresql://promptpace:%s@/promptpace?host=/var/run/postgresql\n' "$PW" \
  | sudo tee /etc/promptpace/promptpace.env >/dev/null
sudo chown root:promptpace /etc/promptpace/promptpace.env
sudo chmod 0640 /etc/promptpace/promptpace.env
unset PW
```

`deploy/promptpace.env.example` shows the file's format. The app creates its tables on first
start. The nightly `pg-backup` job dumps every database, so `promptpace` is backed up with no
extra setup.

**4. Start the app with systemd**

```bash
sudo cp deploy/promptpace.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now promptpace
systemctl status promptpace          # should be "active (running)"
sudo curl -s --unix-socket /run/promptpace/uvicorn.sock http://x/healthz
```

The health check prints `{"status":"ok"}`, or returns 503 if the app can't reach Postgres
(`journalctl -u promptpace -n 50` shows why).

**5. Point nginx at it**

```bash
sudo certbot certonly --webroot -w /var/www/letsencrypt -d typing.dustincremascoli.com
sudo cp deploy/nginx.conf /etc/nginx/conf.d/promptpace.conf
sudo nginx -t && sudo systemctl reload nginx
```

`deploy/nginx.conf` already contains the HTTPS server block, so on a fresh box get the
certificate first. That needs a port-80 server answering `/.well-known/acme-challenge/` from
`/var/www/letsencrypt`, which is how every site on this box is set up. The live certificate was
issued with `certbot --nginx` and renews automatically via `certbot-renew.timer`.

Add a DNS record for `typing.dustincremascoli.com` pointing at the server before running
certbot. The security group already allows 80/443 for the other sites.

The service sets `PROMPTPACE_SECURE_COOKIES=1`, which marks the history cookie as HTTPS-only.
If you run over plain HTTP for a while, remove that line from the unit file or history won't
persist between page loads.

**Updating later:** rsync the code again, run `uv sync --no-dev`, then
`sudo systemctl restart promptpace`. Schema changes apply themselves on start.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PROMPTPACE_DATABASE_URL` | `postgresql:///promptpace` | libpq URL of the app database |
| `PROMPTPACE_TEST_DATABASE_URL` | `postgresql:///promptpace_test` | database the tests wipe (name must end in `_test`) |
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
