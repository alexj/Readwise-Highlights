from __future__ import annotations

import base64
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, g, redirect, render_template, request, url_for

import db
from highlights import author_slug
import similarity as sim

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)
app.jinja_env.filters["author_slug"] = author_slug

# ---------------------------------------------------------------------------
# Config & startup checks
# ---------------------------------------------------------------------------

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()
if not ADMIN_SECRET:
    raise RuntimeError(
        "ADMIN_SECRET is not set. Add it to your .env file before starting the app."
    )

# Optional HTTP Basic Auth — enabled when both vars are set in .env.
# Leave blank for local dev; set both for public hosting.
BASIC_AUTH_USERNAME = os.environ.get("BASIC_AUTH_USERNAME", "").strip()
BASIC_AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "").strip()
_BASIC_AUTH_ENABLED = bool(BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD)

# ---------------------------------------------------------------------------
# DB lifecycle
# ---------------------------------------------------------------------------

@app.before_request
def _open_db() -> None:
    g.db = db.get_db_connection()


@app.teardown_request
def _close_db(e=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ---------------------------------------------------------------------------
# HTTP Basic Auth (optional — enabled when BASIC_AUTH_USERNAME/PASSWORD are set)
# ---------------------------------------------------------------------------

@app.before_request
def _basic_auth() -> Response | None:
    if not _BASIC_AUTH_ENABLED:
        return None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
            if username == BASIC_AUTH_USERNAME and password == BASIC_AUTH_PASSWORD:
                return None
        except Exception:
            pass
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Highlights"'},
    )


# ---------------------------------------------------------------------------
# Source cache & similarity index
# ---------------------------------------------------------------------------

_sources: list | None = None
_sources_lock = threading.Lock()

_index: sim.SimilarityIndex = sim.SimilarityIndex()
_index_stats: dict = {}
_index_lock = threading.Lock()

# Sync state: 'idle' | 'running' | 'done' | 'error'
_sync_state: str = "idle"
_sync_error: str = ""


def get_sources() -> list:
    global _sources
    if _sources is None:
        with _sources_lock:
            if _sources is None:
                print("[app] Loading sources from DB...")
                _sources = db.get_all_sources(g.db)
                total = sum(len(s.highlights) for s in _sources)
                print(f"[app] Loaded {len(_sources)} sources, {total} highlights")
    return _sources


def _invalidate_sources() -> None:
    global _sources
    with _sources_lock:
        _sources = None


def get_index() -> sim.SimilarityIndex:
    return _index


def _rebuild_index_bg(sources: list) -> None:
    global _index, _index_stats
    with _index_lock:
        index, stats = sim.build_index(sources)
        _index = index
        _index_stats = stats


@app.before_request
def _ensure_index() -> None:
    global _index
    if sim.IS_AVAILABLE and not _index.is_ready and not _index_lock.locked():
        sources = get_sources()
        t = threading.Thread(target=_rebuild_index_bg, args=(sources,), daemon=True)
        t.start()


# ---------------------------------------------------------------------------
# Admin guard
# ---------------------------------------------------------------------------

def _check_admin() -> bool:
    """Return True if the request carries the correct admin secret."""
    # Accept secret from form field, JSON body, or X-Admin-Secret header
    secret = (
        request.form.get("admin_secret")
        or (request.get_json(silent=True) or {}).get("admin_secret")
        or request.headers.get("X-Admin-Secret", "")
    )
    return secret == ADMIN_SECRET


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

@app.template_filter("datetimeformat")
def datetimeformat(ts: float | None, fmt: str = "%b %d, %Y at %I:%M %p") -> str:
    if ts is None:
        return "never"
    return datetime.fromtimestamp(ts).strftime(fmt)


@app.template_filter("isoformat_to_display")
def isoformat_to_display(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%b %d, %Y at %I:%M %p")
    except (ValueError, TypeError):
        return iso


# ---------------------------------------------------------------------------
# Routes — read
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    all_sources = get_sources()
    filter_type = request.args.get("type", "all")

    if filter_type == "books":
        sources = [s for s in all_sources if s.source_type == "book"]
    elif filter_type == "articles":
        sources = [s for s in all_sources if s.source_type == "article"]
    else:
        sources = all_sources
        filter_type = "all"

    counts = {
        "all": len(all_sources),
        "books": sum(1 for s in all_sources if s.source_type == "book"),
        "articles": sum(1 for s in all_sources if s.source_type == "article"),
    }

    return render_template("index.html", sources=sources, filter_type=filter_type, counts=counts)


@app.route("/source/<path:slug>")
def source_view(slug: str):
    source = db.get_source_by_slug(slug, g.db)
    if source is None:
        abort(404)

    idx = get_index()
    related_map: dict[int, list[sim.RelatedHighlight]] = {}
    if idx.is_ready:
        for i in range(len(source.highlights)):
            related_map[i] = idx.find_related(source.slug, i, n=3)

    return render_template("source.html", source=source, related_map=related_map)


@app.route("/highlight/<path:slug>/<int:highlight_index>")
def highlight_view(slug: str, highlight_index: int):
    source = db.get_source_by_slug(slug, g.db)
    if source is None:
        abort(404)
    if highlight_index < 0 or highlight_index >= len(source.highlights):
        abort(404)

    highlight = source.highlights[highlight_index]

    idx = get_index()
    related: list[sim.RelatedHighlight] = []
    if idx.is_ready:
        related = idx.find_related(source.slug, highlight_index, n=15)

    return render_template(
        "highlight.html",
        source=source,
        highlight=highlight,
        highlight_index=highlight_index,
        related=related,
    )


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    results = []

    if query:
        query_lower = query.lower()
        for source in get_sources():
            source_matches = (
                query_lower in source.title.lower()
                or query_lower in source.author.lower()
            )
            for highlight in source.highlights:
                if source_matches or query_lower in highlight.text.lower():
                    results.append({"source": source, "highlight": highlight})

    return render_template("search.html", results=results, query=query)


@app.route("/author/<slug>")
def author_view(slug: str):
    all_sources = get_sources()

    author_name = None
    sources = []
    for source in all_sources:
        for name in source.parsed_authors:
            if author_slug(name) == slug:
                if author_name is None:
                    author_name = name
                sources.append(source)
                break

    if author_name is None:
        abort(404)

    total_highlights = sum(len(s.highlights) for s in sources)
    return render_template(
        "author.html",
        author=author_name,
        sources=sources,
        total_highlights=total_highlights,
    )


@app.route("/settings")
def settings():
    all_sources = get_sources()
    total_highlights = sum(len(s.highlights) for s in all_sources)
    idx = get_index()
    last_synced_at = db.get_last_synced_at(g.db)
    return render_template(
        "settings.html",
        sim_available=sim.IS_AVAILABLE,
        index_ready=idx.is_ready,
        index_stats=_index_stats,
        source_count=len(all_sources),
        total_highlights=total_highlights,
        sync_state=_sync_state,
        sync_error=_sync_error,
        last_synced_at=last_synced_at,
        admin_secret=ADMIN_SECRET,
    )


# ---------------------------------------------------------------------------
# Routes — write (admin-guarded)
# ---------------------------------------------------------------------------

@app.route("/sync/status")
def sync_status():
    """Lightweight polling endpoint — returns current sync state as JSON."""
    from flask import jsonify
    last_synced_at = db.get_last_synced_at(g.db)
    return jsonify(state=_sync_state, error=_sync_error, last_synced_at=last_synced_at)


@app.route("/sync", methods=["POST"])
def sync():
    global _sync_state, _sync_error

    if not _check_admin():
        abort(403)

    if _sync_state == "running":
        from flask import jsonify
        return jsonify(state="running"), 202

    full = request.form.get("full", "false").lower() == "true"

    def _run():
        global _sync_state, _sync_error
        _sync_state = "running"
        _sync_error = ""
        try:
            from sync import run_sync
            run_sync(full=full)
            _invalidate_sources()
            # Rebuild similarity index with fresh data
            if sim.IS_AVAILABLE:
                sources = db.get_all_sources()
                t = threading.Thread(target=_rebuild_index_bg, args=(sources,), daemon=True)
                t.start()
            _sync_state = "done"
        except Exception as exc:
            _sync_state = "error"
            _sync_error = str(exc)
            print(f"[app] Sync error: {exc}")

    threading.Thread(target=_run, daemon=True).start()

    from flask import jsonify
    return jsonify(state="started"), 202


@app.route("/refresh", methods=["POST"])
def refresh():
    """Reload sources from DB and rebuild the similarity index."""
    if not _check_admin():
        abort(403)

    _invalidate_sources()
    sources = get_sources()
    if sim.IS_AVAILABLE:
        t = threading.Thread(target=_rebuild_index_bg, args=(sources,), daemon=True)
        t.start()
    return redirect(url_for("settings"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
