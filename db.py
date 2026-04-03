"""
Database access layer for highlights.db.

Two connection modes:
  - Flask request context: use get_db() / close_db() registered via app.teardown_request
  - Standalone scripts (sync.py, migrate.py): use get_db_connection() directly
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from highlights import Highlight, Source

DB_PATH = Path(__file__).parent / "highlights.db"


def _normalize_title(title: str) -> str:
    """
    Normalize a title for fuzzy slug matching.

    Handles differences between .md filenames (which strip special characters)
    and API titles (which keep full punctuation and may include author/publication
    suffixes).
    """
    s = title.lower().strip()
    # Normalize smart/curly quotes to straight
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    # Strip trailing publication/author suffixes (e.g. "| GQ", "- POLITICO", "by Author")
    s = re.sub(r"\s*[|\-\u2013\u2014]\s*\S.*$", "", s)
    s = re.sub(r"\s+by\s+\S.*$", "", s)
    # Remove parenthetical content: (AI & Robotics)
    s = re.sub(r"\s*\([^)]*\)", "", s)
    # Remove characters stripped from filenames
    s = s.replace(":", "").replace("*", "").replace("?", "").replace("/", "")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    """Open and return a direct connection. Caller is responsible for closing."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    """
    Return a per-request DB connection stored on Flask's g object.
    Register close_db with app.teardown_request.
    """
    from flask import g
    if "db" not in g:
        g.db = get_db_connection()
    return g.db


def close_db(e=None):
    """Teardown handler — close the per-request connection."""
    from flask import g
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Row → dataclass converters
# ---------------------------------------------------------------------------

def _highlight_from_row(row: sqlite3.Row) -> Highlight:
    tags = [t for t in (row["tags"] or "").split(",") if t]
    is_favorite = bool(row["is_favorite"])
    # Keep template-compatible: 'favorite' in highlight.tags must work
    if is_favorite and "favorite" not in tags:
        tags.append("favorite")
    return Highlight(
        text=row["text"],
        link=row["readwise_url"] or "",
        tags=tags,
        note=row["note"] or "",
        is_favorite=is_favorite,
        readwise_id=row["readwise_id"],
    )


def _source_from_row(row: sqlite3.Row, highlights: list[Highlight]) -> Source:
    return Source(
        title=row["title"],
        author=row["author"],
        source_type=row["source_type"],
        slug=row["slug"],
        highlights=highlights,
        cover_image=row["cover_url"],
        url=row["source_url"],
        asin=row["asin"],
    )


# ---------------------------------------------------------------------------
# Read queries
# ---------------------------------------------------------------------------

def get_all_sources(conn: Optional[sqlite3.Connection] = None) -> list[Source]:
    """Return all sources with their highlights, sorted by title."""
    _close = False
    if conn is None:
        conn = get_db_connection()
        _close = True
    try:
        source_rows = conn.execute(
            "SELECT * FROM sources ORDER BY title COLLATE NOCASE"
        ).fetchall()

        highlight_rows = conn.execute(
            "SELECT * FROM highlights ORDER BY source_id, position"
        ).fetchall()

        # Group highlights by source_id
        from collections import defaultdict
        hl_by_source: dict[int, list] = defaultdict(list)
        for row in highlight_rows:
            hl_by_source[row["source_id"]].append(row)

        return [
            _source_from_row(row, [_highlight_from_row(h) for h in hl_by_source[row["id"]]])
            for row in source_rows
        ]
    finally:
        if _close:
            conn.close()


def get_source_by_slug(slug: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Source]:
    """Return a single source by slug, with its highlights."""
    _close = False
    if conn is None:
        conn = get_db_connection()
        _close = True
    try:
        row = conn.execute("SELECT * FROM sources WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return None
        highlight_rows = conn.execute(
            "SELECT * FROM highlights WHERE source_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
        return _source_from_row(row, [_highlight_from_row(h) for h in highlight_rows])
    finally:
        if _close:
            conn.close()


def get_last_synced_at(conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """Return the ISO timestamp of the last successful sync, or None."""
    _close = False
    if conn is None:
        conn = get_db_connection()
        _close = True
    try:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'last_synced_at'"
        ).fetchone()
        return row["value"] if row else None
    finally:
        if _close:
            conn.close()


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def set_last_synced_at(ts: str, conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('last_synced_at', ?)",
        (ts,),
    )


def upsert_source(
    *,
    slug: str,
    title: str,
    author: str,
    source_type: str,
    cover_url: Optional[str],
    source_url: Optional[str],
    asin: Optional[str],
    readwise_id: Optional[int],
    conn: sqlite3.Connection,
) -> tuple[int, bool]:
    """
    Insert or update a source row.

    Returns (source_id, was_migrated_match) where was_migrated_match is True
    when we matched an existing slug-only (null readwise_id) record and are
    setting its readwise_id for the first time. Callers should replace that
    source's highlights with fresh API data in this case.
    """
    now = datetime.now(timezone.utc).isoformat()
    was_migrated_match = False

    # 1. Match by readwise_id (fast path for subsequent syncs)
    if readwise_id is not None:
        row = conn.execute(
            "SELECT id FROM sources WHERE readwise_id = ?", (readwise_id,)
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE sources
                   SET title=?, author=?, source_type=?, cover_url=?,
                       source_url=?, asin=?, updated_at=?
                   WHERE id=?""",
                (title, author, source_type, cover_url, source_url, asin, now, row["id"]),
            )
            return row["id"], False

    # 2. Match by exact slug (migrated record without a readwise_id)
    row = conn.execute("SELECT id, readwise_id FROM sources WHERE slug = ?", (slug,)).fetchone()
    if row:
        was_migrated_match = row["readwise_id"] is None
        conn.execute(
            """UPDATE sources
               SET readwise_id=?, title=?, author=?, source_type=?, cover_url=?,
                   source_url=?, asin=?, updated_at=?
               WHERE id=?""",
            (readwise_id, title, author, source_type, cover_url, source_url, asin, now, row["id"]),
        )
        return row["id"], was_migrated_match

    # 2b. Fuzzy match — handles punctuation differences between API titles and
    # .md filenames (colons stripped, smart quotes, asterisks, publication suffixes, etc.)
    normalized = _normalize_title(title)
    candidates = conn.execute(
        "SELECT id, slug, readwise_id FROM sources WHERE readwise_id IS NULL"
    ).fetchall()
    for candidate in candidates:
        candidate_norm = _normalize_title(candidate["slug"])
        # Exact normalized match, or one title is contained within the other
        # (handles "Helsinki Bus Station Theory" ⊂ "This Column...: Helsinki Bus Station Theory")
        match = (
            candidate_norm == normalized
            or (len(candidate_norm) >= 10 and candidate_norm in normalized)
            or (len(normalized) >= 10 and normalized in candidate_norm)
        )
        if match:
            conn.execute(
                """UPDATE sources
                   SET readwise_id=?, title=?, author=?, source_type=?, cover_url=?,
                       source_url=?, asin=?, updated_at=?
                   WHERE id=?""",
                (readwise_id, title, author, source_type, cover_url, source_url, asin,
                 now, candidate["id"]),
            )
            return candidate["id"], True  # was_migrated_match = True

    # 3. New record
    cur = conn.execute(
        """INSERT INTO sources
               (slug, title, author, source_type, cover_url, source_url, asin,
                readwise_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (slug, title, author, source_type, cover_url, source_url, asin,
         readwise_id, now, now),
    )
    return cur.lastrowid, False


def upsert_highlight(
    *,
    source_id: int,
    text: str,
    note: str,
    is_favorite: bool,
    readwise_id: Optional[int],
    readwise_url: str,
    location: Optional[int],
    highlighted_at: Optional[str],
    tags: list[str],
    position: int,
    conn: sqlite3.Connection,
) -> None:
    """Insert or update a highlight row, matching on readwise_id."""
    tags_str = ",".join(t for t in tags if t)
    fav = 1 if is_favorite else 0

    if readwise_id is not None:
        conn.execute(
            """INSERT INTO highlights
                   (source_id, text, note, is_favorite, readwise_id, readwise_url,
                    location, highlighted_at, tags, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(readwise_id) DO UPDATE SET
                   text=excluded.text,
                   note=excluded.note,
                   is_favorite=excluded.is_favorite,
                   readwise_url=excluded.readwise_url,
                   tags=excluded.tags,
                   position=excluded.position""",
            (source_id, text, note, fav, readwise_id, readwise_url,
             location, highlighted_at, tags_str, position),
        )
    else:
        # No readwise_id (migrated from .md) — insert only, no update
        conn.execute(
            """INSERT OR IGNORE INTO highlights
                   (source_id, text, note, is_favorite, readwise_url,
                    location, highlighted_at, tags, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_id, text, note, fav, readwise_url,
             location, highlighted_at, tags_str, position),
        )


def delete_highlights_for_source(source_id: int, conn: sqlite3.Connection) -> int:
    """Delete all highlights for a source. Returns number of rows deleted."""
    cur = conn.execute("DELETE FROM highlights WHERE source_id = ?", (source_id,))
    return cur.rowcount
