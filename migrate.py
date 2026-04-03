#!/usr/bin/env python3
"""
One-time migration: reads all existing .md files from Books/ and Articles/
and inserts them into highlights.db.

Safe to re-run — existing records (matched by slug) are skipped.
Run setup_db.py first if highlights.db does not yet exist.

Usage:
    python3 migrate.py
"""

from datetime import datetime, timezone
from pathlib import Path

import db
from highlights import load_all

BASE_DIR = Path(__file__).parent


def migrate() -> None:
    sources = load_all(BASE_DIR)
    if not sources:
        print("[migrate] No .md files found — nothing to migrate.")
        return

    conn = db.get_db_connection()
    now = datetime.now(timezone.utc).isoformat()

    sources_inserted = 0
    sources_skipped = 0
    highlights_inserted = 0

    try:
        for source in sources:
            # Try to insert the source; skip if slug already exists
            existing = conn.execute(
                "SELECT id FROM sources WHERE slug = ?", (source.slug,)
            ).fetchone()

            if existing:
                sources_skipped += 1
                continue

            cur = conn.execute(
                """INSERT INTO sources
                       (slug, title, author, source_type, cover_url, source_url,
                        asin, readwise_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source.slug,
                    source.title,
                    source.author,
                    source.source_type,
                    source.cover_image,
                    source.url,
                    source.asin,
                    None,           # readwise_id — backfilled by sync.py
                    now,
                    now,
                ),
            )
            source_id = cur.lastrowid
            sources_inserted += 1

            for position, highlight in enumerate(source.highlights):
                tags_str = ",".join(highlight.tags)
                fav = 1 if highlight.is_favorite else 0
                conn.execute(
                    """INSERT INTO highlights
                           (source_id, text, note, is_favorite, readwise_id,
                            readwise_url, location, highlighted_at, tags, position)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_id,
                        highlight.text,
                        highlight.note,
                        fav,
                        None,           # readwise_id — backfilled by sync.py
                        highlight.link,
                        None,           # location not available from .md
                        None,           # highlighted_at not available from .md
                        tags_str,
                        position,
                    ),
                )
                highlights_inserted += 1

            print(f"  [migrate] {source.title} — {len(source.highlights)} highlights")

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"\n[migrate] Done. "
        f"{sources_inserted} sources inserted, "
        f"{sources_skipped} skipped (already in DB), "
        f"{highlights_inserted} highlights inserted."
    )
    if sources_inserted > 0:
        print(
            "[migrate] Next step: run `python3 sync.py --full` to fetch from "
            "Readwise and backfill readwise_id on all migrated records."
        )


if __name__ == "__main__":
    migrate()
