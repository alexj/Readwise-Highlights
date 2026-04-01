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

**Browse** (`/`) — All books and articles in a grid with cover images. Filter by type using the tabs at the top. Click a title to see its highlights; click an author name to see everything by that author.

**Source view** (`/source/...`) — All highlights from a single book or article. Favorites (tagged `#favorite` in Readwise) are visually distinguished. Each highlight has a `(View)` link back to Readwise or Kindle. The icon next to the title links to the book on Amazon or the original article URL.

**Author view** (`/author/...`) — All works and highlights by a given author. Co-authored works show links to the other authors. Author names are clickable in every view.

**Search** (`/search`) — Searches across highlight text, titles, and author names. Searching an author's name returns all their highlights.

## Your Highlight Files

Highlights live in two folders, sourced from Readwise exports:

- `Books/` — Kindle book highlights (~221 files)
- `Articles/` — Web article highlights (~30 files)

Drop new exports into the appropriate folder and restart the app.

## Dependencies

- Python 3
- Flask (only dependency — installed in `.venv/`)
