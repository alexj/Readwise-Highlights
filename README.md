# Highlights

A personal web app for browsing and searching your Readwise highlights — Kindle books and saved articles in one place, synced directly from the Readwise API.

## Features

**Browse** (`/`) — All books and articles in a grid with cover images. Filter by type. Click a title to see its highlights; click an author name to see everything by that author.

**Source view** (`/source/...`) — All highlights from a single book or article. Favorites are visually distinguished. Each highlight has a `(View)` link to Readwise. The title icon links to Amazon (books) or the original article URL.

**Author view** (`/author/...`) — All works and highlights by a given author. Co-authored works link to the other authors.

**Search** (`/search`) — Searches across highlight text, titles, and author names.

**Related highlights** — Semantically similar highlights shown inline on source pages and on a dedicated highlight page. Requires optional ML dependencies (see below).

---

## Setup

### Prerequisites

- Python 3.11+
- A [Readwise](https://readwise.io) account and API token — get yours at https://readwise.io/access_token

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
READWISE_API_KEY=your_token_here
ADMIN_SECRET=a_long_random_string
```

- `READWISE_API_KEY` — your Readwise API token (required for sync)
- `ADMIN_SECRET` — protects the `/sync` and `/refresh` endpoints; choose any long random string (e.g. `openssl rand -hex 32`)

The app will refuse to start if `ADMIN_SECRET` is not set.

### 3. Create the database

```bash
python3 setup_db.py
```

### 4. Sync your highlights

```bash
python3 sync.py --full
```

This fetches all your highlights from Readwise. On a large library (~250 books) it takes 30–60 seconds.

### 5. Run the app

```bash
python3 app.py
```

Open [http://localhost:5001](http://localhost:5001).

---

## Keeping highlights up to date

### Manual sync

```bash
source .venv/bin/activate
python3 sync.py          # incremental — only fetches changes since last sync
python3 sync.py --full   # full fetch — re-fetches everything
```

### Via the Settings page

Open `/settings` in the app and click **Sync from Readwise**. The page shows sync state (idle / running / done).

### Automatic sync via cron

```
0 */6 * * * cd /path/to/Highlights && .venv/bin/python3 sync.py >> sync.log 2>&1
```

---

## Optional: Related highlights (ML)

Semantically similar highlights are found using a local sentence-transformers model (no API key needed, runs fully offline).

```bash
pip install -r requirements-ml.txt
# Restart the app — the index builds in the background on first request
```

The model (`all-MiniLM-L6-v2`, ~90MB) is downloaded once and cached locally.

---

## Migrating from Readwise .md exports

If you have an existing `Books/` and `Articles/` directory from a Readwise markdown export:

```bash
python3 setup_db.py    # create schema
python3 migrate.py     # load .md files into DB
python3 sync.py --full # backfill Readwise IDs and fetch any new content
```

The `.md` files remain on disk as a backup but are no longer read by the app.

---

## Production deployment

### Run with gunicorn (not the dev server)

```bash
pip install gunicorn
gunicorn -w 1 -b 127.0.0.1:5001 app:app
```

Use systemd or supervisor to keep gunicorn running.

### Enable HTTP Basic Auth

Add to your `.env`:

```
BASIC_AUTH_USERNAME=yourname
BASIC_AUTH_PASSWORD=a_strong_password
```

When set, every page requires these credentials before loading. This is the recommended way to protect the app when hosted publicly — it gates the settings page (which contains the admin secret) behind a password.

Leave both blank (or omit them) for local development.

### Reverse proxy with SSL

Point nginx or Apache at `127.0.0.1:5001`. Example nginx config:

```nginx
server {
    listen 443 ssl;
    server_name highlights.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/highlights.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/highlights.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
    }
}
```

### File permissions

```bash
chmod 600 .env
chmod 600 highlights.db
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework |
| `python-dotenv` | Loads `.env` file |
| `requests` | Readwise API calls |
| `sentence-transformers` | Related highlights — optional, `requirements-ml.txt` |

---

## Data

All highlights are stored in `highlights.db` (SQLite, gitignored). The database is created by `setup_db.py` and populated by `sync.py`.

Sensitive files that should never be committed: `.env`, `highlights.db`. Both are in `.gitignore`.
