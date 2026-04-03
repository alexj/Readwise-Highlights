#!/usr/bin/env python3
"""
Readwise API sync — fetches highlights and upserts them into highlights.db.

Callable two ways:

  CLI (for cron or manual runs):
      python3 sync.py           # incremental — only fetch since last_synced_at
      python3 sync.py --full    # full fetch — ignore last_synced_at

  From Flask (app.py):
      from sync import run_sync
      run_sync(full=False)

Requires READWISE_API_KEY in environment (or .env file).
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

import db

load_dotenv(Path(__file__).parent / ".env")

READWISE_API_BASE = "https://readwise.io/api/v2"
PAGE_SIZE = 1000


# ---------------------------------------------------------------------------
# Slug generation for new sources
# ---------------------------------------------------------------------------

def _make_slug(title: str) -> str:
    """
    Generate a slug from a source title.

    Readwise exports .md files named by title (e.g. "Dune.md"), so the slug
    for new API sources is just the title itself. This ensures sync.py matches
    migrated records by slug when readwise_id hasn't been set yet.
    """
    return title.strip()


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def _fetch_all_books(api_key: str, updated_after: str | None) -> list[dict]:
    """
    Fetch all books/articles from the Readwise export endpoint, following
    pagination until exhausted.

    Args:
        api_key: Readwise API token.
        updated_after: ISO timestamp string, or None for a full fetch.

    Returns:
        List of book dicts (each containing a 'highlights' list).
    """
    headers = {"Authorization": f"Token {api_key}"}
    params: dict = {"pageSize": PAGE_SIZE}
    if updated_after:
        params["updatedAfter"] = updated_after

    results = []
    base_url = f"{READWISE_API_BASE}/export/"

    while True:
        response = requests.get(base_url, headers=headers, params=params, timeout=60)
        if response.status_code != 200:
            raise RuntimeError(
                f"Readwise API error {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        results.extend(data.get("results", []))
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
        # Cursor is a token, not a URL — pass as pageCursor on subsequent requests
        params = {"pageCursor": cursor}

    return results


# ---------------------------------------------------------------------------
# Main sync logic
# ---------------------------------------------------------------------------

def run_sync(full: bool = False) -> dict:
    """
    Fetch highlights from Readwise and upsert into highlights.db.

    Args:
        full: If True, ignore last_synced_at and fetch everything.

    Returns:
        Summary dict with keys: sources_added, sources_updated, highlights_added,
        highlights_updated, last_synced_at.

    Raises:
        RuntimeError: If READWISE_API_KEY is not set.
    """
    api_key = os.environ.get("READWISE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "READWISE_API_KEY is not set. Add it to your .env file or environment."
        )

    conn = db.get_db_connection()

    try:
        # Determine fetch window
        updated_after: str | None = None
        if not full:
            updated_after = db.get_last_synced_at(conn)

        if updated_after:
            print(f"[sync] Incremental fetch — changes since {updated_after}")
        else:
            print("[sync] Full fetch — retrieving all highlights from Readwise")

        books = _fetch_all_books(api_key, updated_after)
        print(f"[sync] API returned {len(books)} source(s)")

        sources_added = 0
        sources_updated = 0
        highlights_added = 0
        highlights_updated = 0

        for book in books:
            source_type = book.get("category", "books")
            # Readwise categories: 'books', 'articles', 'tweets', 'podcasts', etc.
            # Map to our two types; treat everything non-article as a book.
            if source_type == "articles":
                source_type = "article"
            else:
                source_type = "book"

            title = (book.get("readable_title") or book.get("title") or "").strip()
            if not title:
                continue

            slug = _make_slug(title)
            author = (book.get("author") or "Unknown Author").strip()
            cover_url = book.get("cover_image_url") or None
            source_url = book.get("source_url") or book.get("unique_url") or None
            asin = book.get("asin") or None
            readwise_id = book.get("user_book_id")

            # Improve cover image resolution (same logic as feed-parser)
            if cover_url:
                cover_url = (
                    cover_url
                    .replace("SY160.jpg", "SY1600.jpg")
                    .replace("SL200_.jpg", "SL2000_.jpg")
                )

            source_id, was_migrated_match = db.upsert_source(
                slug=slug,
                title=title,
                author=author,
                source_type=source_type,
                cover_url=cover_url,
                source_url=source_url,
                asin=asin,
                readwise_id=readwise_id,
                conn=conn,
            )

            api_highlights = book.get("highlights", [])

            if was_migrated_match:
                # First time this migrated source is matched to the API — replace
                # the .md-sourced highlights with authoritative API data.
                deleted = db.delete_highlights_for_source(source_id, conn)
                print(
                    f"  [sync] '{title}' — migration match, replaced {deleted} old highlight(s)"
                )
                sources_updated += 1
            else:
                # Count as added vs updated based on whether source was brand new
                # (upsert_source handles the distinction internally; we track via
                # whether the row existed before — simplest proxy: check if any
                # highlights exist for this source_id yet)
                existing_count = conn.execute(
                    "SELECT COUNT(*) FROM highlights WHERE source_id = ?", (source_id,)
                ).fetchone()[0]
                if existing_count == 0 and api_highlights:
                    sources_added += 1
                else:
                    sources_updated += 1

            for position, hl in enumerate(api_highlights):
                text = (hl.get("text") or "").strip()
                if not text:
                    continue

                note = (hl.get("note") or "").strip()
                is_favorite = bool(hl.get("is_favorite", False))
                hl_readwise_id = hl.get("id")
                readwise_url = hl.get("url") or hl.get("readwise_url") or ""
                location = hl.get("location")
                highlighted_at = hl.get("highlighted_at")

                # Tags: list of {id, name} dicts from API
                raw_tags = hl.get("tags") or []
                tags = [t["name"] for t in raw_tags if isinstance(t, dict) and t.get("name")]

                # Check if this highlight already exists (for add/update counting)
                existing_hl = None
                if hl_readwise_id:
                    existing_hl = conn.execute(
                        "SELECT id FROM highlights WHERE readwise_id = ?", (hl_readwise_id,)
                    ).fetchone()

                db.upsert_highlight(
                    source_id=source_id,
                    text=text,
                    note=note,
                    is_favorite=is_favorite,
                    readwise_id=hl_readwise_id,
                    readwise_url=readwise_url,
                    location=location,
                    highlighted_at=highlighted_at,
                    tags=tags,
                    position=position,
                    conn=conn,
                )

                if existing_hl or was_migrated_match:
                    highlights_updated += 1
                else:
                    highlights_added += 1

        # Record successful sync time
        synced_at = datetime.now(timezone.utc).isoformat()
        db.set_last_synced_at(synced_at, conn)
        conn.commit()

        summary = {
            "sources_added": sources_added,
            "sources_updated": sources_updated,
            "highlights_added": highlights_added,
            "highlights_updated": highlights_updated,
            "last_synced_at": synced_at,
        }

        print(
            f"[sync] Complete — "
            f"{sources_added} source(s) added, {sources_updated} updated | "
            f"{highlights_added} highlight(s) added, {highlights_updated} updated"
        )
        return summary

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync highlights from Readwise API")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore last_synced_at and fetch all highlights",
    )
    args = parser.parse_args()

    try:
        run_sync(full=args.full)
    except RuntimeError as e:
        print(f"[sync] Error: {e}", file=sys.stderr)
        sys.exit(1)
