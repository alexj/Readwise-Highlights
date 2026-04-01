from pathlib import Path

from flask import Flask, abort, render_template, request

from highlights import Source, load_all

app = Flask(__name__)
BASE_DIR = Path(__file__).parent

_sources: list[Source] | None = None


def get_sources() -> list[Source]:
    global _sources
    if _sources is None:
        print("[app] Loading highlight sources...")
        _sources = load_all(BASE_DIR)
        total_highlights = sum(len(s.highlights) for s in _sources)
        print(f"[app] Loaded {len(_sources)} sources, {total_highlights} highlights")
    return _sources


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
    return render_template("source.html", source=source)


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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
