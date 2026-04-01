# Highlights

## Project Overview

**Purpose**: Explore Kindle and web article highlights from Readwise exports. Browse, search, and discover connections between highlights across books and articles.

**Status**: Active Development

**Tech Stack**: Python, Flask, Vanilla JS, Open Props CSS

## Quick Start

```bash
cd Highlights
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
# Open http://localhost:5001
```

## Architecture & Structure

```
Highlights/
├── Articles/              # Article highlight files (Readwise export, ~30 files)
├── Books/                 # Book highlight files (Readwise export, ~221 files)
├── app.py                 # Flask app — routes and entry point
├── highlights.py          # Parses markdown files into structured Python objects
├── templates/             # Jinja2 HTML templates
│   ├── base.html          # Site shell: nav, Open Props, layout
│   ├── index.html         # Home: browse all sources with filter tabs
│   ├── source.html        # Single book/article view with all its highlights
│   └── search.html        # Full-text search results
├── static/
│   ├── css/styles.css     # All styles, semantic classes, Open Props variables
│   └── js/main.js         # Minimal JS for interactivity
├── requirements.txt
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
- Highlights end with `([View Highlight](...))` for articles, `([Location N](...))` for books
- Some highlights have a `**Tags:** #favorite` line immediately after
- Cover images are lines starting with `https://` after the tag line

## Key Features

### Implemented
- Browse all sources (books + articles) with filter tabs
- Individual source page showing all highlights
- Full-text search across all highlight text

### TODO: Author View
A page listing all works and highlights by a given author. Requirements:
- Route: `/author/<slug>` (slug = author name, URL-encoded or kebab-cased)
- Shows all sources by that author, each with their highlights
- Author names should be clickable links in all views (source header, index cards, search results) to reach this page

### Planned: Related Highlights
The "connect related highlights" feature should show semantically similar highlights from other sources alongside each highlight. Approach options (decide when building):

1. **Simple / no-dependency**: TF-IDF keyword matching (`sklearn` only)
2. **Semantic / local**: `sentence-transformers` with a small model like `all-MiniLM-L6-v2` — runs fully offline, no API key, best quality
3. **Via Claude API**: Send highlight text to Claude for analysis — good for on-demand use

The `highlights.py` module is the right place to add this logic once we decide on the approach.

## Development Guidelines

### Stack Rules
- **No React, no TypeScript, no build tools** — vanilla JS only
- Flask for all server-side logic (already acceptable for simple apps per Python standards)
- Open Props CDN for spacing/shadows/variables
- Semantic BEM-style class names, no utility classes (per CSS standards)
- Reload sources on startup; no database — flat files are the source of truth

### Templates
- Extend `base.html` for all pages
- Use Jinja2 template inheritance
- Keep templates clean — move logic to `app.py` or `highlights.py`

### Data Loading
- Sources are loaded once at startup via `get_sources()` in `app.py`
- Restart Flask to pick up new highlight files
- The `Source` and `Highlight` dataclasses in `highlights.py` are the canonical data model

### Adding Features
- New routes go in `app.py`
- New parsing logic goes in `highlights.py`
- Don't add new dependencies without thinking it through first

## Known Issues & Gotchas

- Some highlight files may have slightly inconsistent formatting — the parser is defensive but may miss edge cases; check the console for parse errors on startup
- Cover image URLs are just raw `https://` lines in the file; not all sources have them
- The Readwise link format differs between articles (readwise.io/read/) and books (readwise.io/to_kindle)

## Project-Specific Context

### Source Counts (as of setup)
- Books: ~221 files
- Articles: ~30 files
- Total highlights: varies per source, some books have 20+ highlights

### Data Source
All files exported from Readwise. New exports can be dropped into `Articles/` or `Books/` and will be picked up on next Flask restart.

---

**Last Updated**: 2026-04-01
**Maintained By**: Alex Jones
