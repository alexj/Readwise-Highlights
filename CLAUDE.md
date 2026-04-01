# Highlights

## Project Overview

**Purpose**: Explore Kindle and web article highlights from Readwise exports. Browse, search, and discover connections between highlights across books and articles.

**Status**: Active Development

**Tech Stack**: Python, Flask, Vanilla JS, Open Props CSS

## Quick Start

```bash
cd Highlights
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
# Open http://localhost:5001
```

## Architecture & Structure

```
Highlights/
├── Articles/              # Article highlight files (Readwise export, ~30 files)
├── Books/                 # Book highlight files (Readwise export, ~221 files)
├── app.py                 # Flask app — routes and entry point
├── highlights.py          # Parses markdown files; data model; author utilities
├── similarity.py          # Semantic similarity index (optional, sentence-transformers)
├── templates/             # Jinja2 HTML templates
│   ├── base.html          # Site shell: nav, Open Props, layout
│   ├── index.html         # Home: browse all sources with filter tabs
│   ├── source.html        # Single book/article with all highlights + inline related
│   ├── author.html        # All works and highlights by one author
│   ├── search.html        # Full-text search results
│   ├── highlight.html     # Single highlight with 15 related highlights
│   └── settings.html      # Settings: index stats, refresh button
├── static/
│   ├── css/styles.css     # All styles, semantic classes, Open Props variables
│   └── js/main.js         # Minimal JS for interactivity
├── requirements.txt       # Flask only
├── requirements-ml.txt    # Flask + sentence-transformers (for related highlights)
└── .gitignore
```

## Data Format

Highlight files are markdown exports from Readwise. Each `.md` file follows this structure:

```
# Title

### Author Name
#Highlights/books# (or #Highlights/articles#)


https://cover-image-url.jpg

### Highlights

- "Quote text here." ([View Highlight](https://read.readwise.io/read/...))
- Another quote ([Location 303](https://readwise.io/to_kindle?...))
    - **Tags:** #favorite
```

Key parsing notes:
- Type is determined by `#Highlights/books#` vs `#Highlights/articles#` tag
- Articles have a `- URL: https://...` line before the cover image
- Highlights end with `([View Highlight](...))` for articles, `([Location N](...))` for books — the link is stripped from the text and stored separately; rendered as `(View)` inline
- Some highlights have a `**Tags:** #favorite` line immediately after
- Cover images are lines starting with `https://` after the tag line

## Key Features

### Implemented

**Browse** (`/`) — Grid of all sources with cover images, filter tabs (All / Books / Articles). Each card links to the source view; clicking an author name goes to the author view.

**Source view** (`/source/<slug>`) — All highlights from one book or article. Favorites highlighted. Title has an external link icon: Amazon for books (ASIN extracted from Kindle links, falls back to keyword search), original URL for articles.

**Author view** (`/author/<slug>`) — All works and highlights by a single author. Co-authored works show "with [co-author]" links. Author names are clickable in all views (index, source header, search results).

**Search** (`/search`) — Full-text search across highlight text, source titles, and author names. Results link to source and author views.

### Implemented: Related Highlights
Semantically similar highlights shown inline (3) on source view and on a dedicated highlight page (15). Uses `sentence-transformers` with `all-MiniLM-L6-v2` model (offline, no API key).

- `similarity.py` — `SimilarityIndex` class, `build_index()` with per-source incremental caching
- Cache stored in `.embeddings_cache.pkl` (gitignored) — keyed by (slug, mtime, highlight count)
- `IS_AVAILABLE` flag — graceful degradation if `sentence-transformers` not installed
- Install: `pip install -r requirements-ml.txt`; restart app; index builds in background on first request
- Refresh via Settings page (`/settings`) — reloads sources and rebuilds index incrementally

## Development Guidelines

### Stack Rules
- **No React, no TypeScript, no build tools** — vanilla JS only
- Flask for all server-side logic
- Open Props CDN for spacing/shadows/variables
- Semantic BEM-style class names, no utility classes (per CSS standards)
- Sources loaded once at startup; no database — flat files are the source of truth

### Key Modules

**`highlights.py`** — everything data-related:
- `Highlight` and `Source` dataclasses
- `Source.parsed_authors` — splits combined author strings into individual names; handles `and`, `,`, `, and`, parenthetical roles like `(Foreword)`, stray whitespace
- `Source.external_url` — Amazon dp URL (via ASIN from Kindle links) for books, original URL for articles; falls back to keyword search. Mirrors `build_book_url()` logic from `feed-parser/readwise.py`
- `parse_authors(string)` — the splitting function, importable
- `author_slug(name)` — converts author name to URL-safe slug; registered as a Jinja2 filter in `app.py`
- `load_all(base_dir)` — loads and sorts all sources from `Articles/` and `Books/`

**`app.py`** — routes only; no business logic:
- `/` — browse with type filter
- `/source/<slug>` — single source view; passes `related_map` (dict of highlight index → top 3 related)
- `/highlight/<slug>/<int:index>` — dedicated highlight view with 15 related highlights
- `/author/<slug>` — author view; matches sources via `author_slug()` against each source's `parsed_authors`
- `/search` — searches highlight text + source title + author name
- `/settings` — index stats, library counts, refresh button
- `/refresh` (POST) — reloads sources from disk and triggers background index rebuild

**`similarity.py`** — semantic similarity (optional):
- `IS_AVAILABLE` — True if `sentence-transformers` + `numpy` importable
- `SimilarityIndex.find_related(slug, index, n)` — returns top-n `RelatedHighlight` objects
- `build_index(sources)` — per-source incremental caching via `.embeddings_cache.pkl`
- Index builds in background thread on first request; `_index_lock` prevents duplicate builds

### Templates
- Extend `base.html` for all pages
- `author_slug` is available as a Jinja2 filter: `{{ name | author_slug }}`
- Index cards use CSS stretched-link pattern: `.source-card__title-link::after` covers the card; `.source-card__author` sits above it with `position: relative; z-index: 1`

### Adding Features
- New routes go in `app.py`
- New parsing/data logic goes in `highlights.py`
- Don't add new dependencies without thinking it through first

## Known Issues & Gotchas

- Some highlight files may have inconsistent formatting — the parser is defensive; check the console on startup for parse errors
- Author strings with publisher names as co-authors (e.g. `Ramez Naam and ARGH! Oxford`) are treated as separate authors — Readwise metadata quirk, not worth special-casing
- Cover image URLs are raw `https://` lines in the markdown; not all sources have them
- 2 books have no ASIN in their Kindle links and fall back to Amazon keyword search

## Project-Specific Context

### Source Counts (as of setup)
- Books: ~221 files, Articles: ~30 files, ~2005 total highlights, ~232 individual authors

### Data Source
All files exported from Readwise. Drop new exports into `Articles/` or `Books/` and restart the app.

---

**Last Updated**: 2026-04-01 (related highlights feature added)
**Maintained By**: Alex Jones
