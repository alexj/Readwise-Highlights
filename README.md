# Highlights

A local web app for browsing and searching your Readwise highlights — Kindle books and saved articles in one place.

## Running the App

```bash
cd Highlights
source .venv/bin/activate
python3 app.py
```

Then open [http://localhost:5001](http://localhost:5001).

On first launch, all highlight files are parsed and loaded. With ~250 sources this takes a second or two. Restart the app to pick up any newly added files.

## What It Does

**Browse** (`/`) — All books and articles in a grid with cover images. Filter by type using the tabs at the top.

**Source view** (`/source/<title>`) — All highlights from a single book or article. Favorites (tagged `#favorite` in Readwise) are visually distinguished.

**Search** (`/search`) — Full-text search across every highlight. Results link back to the source.

## Your Highlight Files

Highlights live in two folders and are sourced from Readwise exports:

- `Books/` — Kindle book highlights (~221 files)
- `Articles/` — Web article highlights (~30 files)

Each file is a markdown export from Readwise. Drop new exports into the appropriate folder and restart the app.

## Dependencies

- Python 3
- Flask (only dependency — installed in `.venv/`)
