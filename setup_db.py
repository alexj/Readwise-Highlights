#!/usr/bin/env python3
"""
Creates the highlights.db SQLite database schema.
Safe to re-run — all statements use CREATE IF NOT EXISTS.

Usage:
    python3 setup_db.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "highlights.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    author      TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('book', 'article')),
    cover_url   TEXT,
    source_url  TEXT,
    asin        TEXT,
    readwise_id INTEGER UNIQUE,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS highlights (
    id             INTEGER PRIMARY KEY,
    source_id      INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    text           TEXT NOT NULL,
    note           TEXT NOT NULL DEFAULT '',
    is_favorite    INTEGER NOT NULL DEFAULT 0,
    readwise_id    INTEGER UNIQUE,
    readwise_url   TEXT NOT NULL DEFAULT '',
    location       INTEGER,
    highlighted_at TEXT,
    tags           TEXT NOT NULL DEFAULT '',
    position       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_slug        ON sources(slug);
CREATE INDEX IF NOT EXISTS idx_sources_readwise_id ON sources(readwise_id);
CREATE INDEX IF NOT EXISTS idx_highlights_source   ON highlights(source_id, position);
CREATE INDEX IF NOT EXISTS idx_highlights_rwid     ON highlights(readwise_id);
"""


def setup():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print(f"[setup_db] Database ready at {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    setup()
