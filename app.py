from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for

from highlights import Source, author_slug, load_all, parse_authors
import similarity as sim

app = Flask(__name__)
app.jinja_env.filters["author_slug"] = author_slug
BASE_DIR = Path(__file__).parent

_sources: list[Source] | None = None
_index: sim.SimilarityIndex = sim.SimilarityIndex()
_index_stats: dict = {}
_index_lock = threading.Lock()


def get_sources() -> list[Source]:
    global _sources
    if _sources is None:
        print("[app] Loading highlight sources...")
        _sources = load_all(BASE_DIR)
        total = sum(len(s.highlights) for s in _sources)
        print(f"[app] Loaded {len(_sources)} sources, {total} highlights")
    return _sources


def get_index() -> sim.SimilarityIndex:
    return _index


def _rebuild_index_bg(sources: list[Source]) -> None:
    """Build the similarity index in a background thread."""
    global _index, _index_stats
    with _index_lock:
        index, stats = sim.build_index(sources)
        _index = index
        _index_stats = stats


@app.before_request
def _ensure_index() -> None:
    """Start index build on first request (non-blocking)."""
    global _index
    if sim.IS_AVAILABLE and not _index.is_ready and not _index_lock.locked():
        sources = get_sources()
        t = threading.Thread(target=_rebuild_index_bg, args=(sources,), daemon=True)
        t.start()


@app.template_filter("datetimeformat")
def datetimeformat(ts: float | None, fmt: str = "%b %d, %Y at %I:%M %p") -> str:
    if ts is None:
        return "never"
    return datetime.fromtimestamp(ts).strftime(fmt)


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


@app.route("/source/<slug>")
def source_view(slug: str):
    all_sources = get_sources()
    source = next((s for s in all_sources if s.slug == slug), None)
    if source is None:
        abort(404)

    idx = get_index()
    related_map: dict[int, list[sim.RelatedHighlight]] = {}
    if idx.is_ready:
        for i in range(len(source.highlights)):
            related_map[i] = idx.find_related(source.slug, i, n=3)

    return render_template("source.html", source=source, related_map=related_map)


@app.route("/highlight/<slug>/<int:highlight_index>")
def highlight_view(slug: str, highlight_index: int):
    all_sources = get_sources()
    source = next((s for s in all_sources if s.slug == slug), None)
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
    return render_template(
        "settings.html",
        sim_available=sim.IS_AVAILABLE,
        index_ready=idx.is_ready,
        index_stats=_index_stats,
        source_count=len(all_sources),
        total_highlights=total_highlights,
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    global _sources
    # Reload sources from disk
    print("[app] Refreshing sources and rebuilding index...")
    _sources = load_all(BASE_DIR)
    if sim.IS_AVAILABLE:
        t = threading.Thread(target=_rebuild_index_bg, args=(_sources,), daemon=True)
        t.start()
    return redirect(url_for("settings"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
