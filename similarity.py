"""
Semantic similarity index for Highlights app.

Optional dependency: sentence-transformers (pip install -r requirements-ml.txt).
If not installed, IS_AVAILABLE is False and all functions degrade gracefully.
"""

from __future__ import annotations

import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from highlights import Highlight, Source

try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    IS_AVAILABLE = True
except ImportError:
    IS_AVAILABLE = False

MODEL_NAME = "all-MiniLM-L6-v2"
CACHE_PATH = Path(__file__).parent / ".embeddings_cache.pkl"

_model: "SentenceTransformer | None" = None


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        print(f"[similarity] Loading model {MODEL_NAME}...")
        _model = SentenceTransformer(MODEL_NAME)
        print("[similarity] Model loaded.")
    return _model


@dataclass
class RelatedHighlight:
    source: "Source"
    highlight: "Highlight"
    highlight_index: int
    score: float


class SimilarityIndex:
    """Holds a flat list of all (source, highlight) pairs plus a normalized embedding matrix."""

    def __init__(self) -> None:
        # Each entry: (source_slug, highlight_index, source, highlight)
        self._entries: list[tuple[str, int, "Source", "Highlight"]] = []
        # Maps (source_slug, highlight_index) -> row index in embedding matrix
        self._lookup: dict[tuple[str, int], int] = {}
        self._embeddings: "np.ndarray | None" = None
        self.built_at: float | None = None

    def build(
        self,
        entries: list[tuple[str, int, "Source", "Highlight"]],
        embeddings: "np.ndarray",
        built_at: float,
    ) -> None:
        self._entries = entries
        self._embeddings = embeddings
        self.built_at = built_at
        self._lookup = {
            (slug, idx): row for row, (slug, idx, _, _) in enumerate(entries)
        }

    @property
    def is_ready(self) -> bool:
        return self._embeddings is not None and len(self._entries) > 0

    @property
    def total_highlights(self) -> int:
        return len(self._entries)

    def find_related(
        self, source_slug: str, highlight_index: int, n: int = 10
    ) -> list[RelatedHighlight]:
        if not self.is_ready:
            return []

        key = (source_slug, highlight_index)
        row = self._lookup.get(key)
        if row is None:
            return []

        query = self._embeddings[row]
        scores = self._embeddings @ query  # cosine sim (embeddings are normalized)
        scores[row] = -1.0  # exclude self

        top_rows = scores.argsort()[::-1][:n]
        results = []
        for r in top_rows:
            if scores[r] <= 0:
                break
            slug, idx, source, highlight = self._entries[r]
            results.append(
                RelatedHighlight(
                    source=source,
                    highlight=highlight,
                    highlight_index=idx,
                    score=float(scores[r]),
                )
            )
        return results


def build_index(sources: list["Source"]) -> tuple[SimilarityIndex, dict]:
    """
    Build (or incrementally update) the similarity index.

    Uses a per-source cache keyed by (slug, mtime, highlight_count).
    Only recomputes embeddings for sources that have changed.

    Returns (index, stats) where stats contains:
      - updated: list of slugs that were recomputed
      - cached_count: number of highlights loaded from cache
      - total_highlights: total highlights indexed
      - built_at: unix timestamp
    """
    if not IS_AVAILABLE:
        return SimilarityIndex(), {}

    model = _get_model()

    # Load existing cache
    cache: dict[str, dict] = {}
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "rb") as f:
                cache = pickle.load(f)
        except Exception as e:
            print(f"[similarity] Cache load failed, rebuilding: {e}")
            cache = {}

    entries: list[tuple[str, int, "Source", "Highlight"]] = []
    all_embeddings: list["np.ndarray"] = []
    updated: list[str] = []
    cached_count = 0

    for source in sources:
        slug = source.slug
        try:
            mtime = source.filepath.stat().st_mtime if source.filepath else 0.0
        except OSError:
            mtime = 0.0
        cache_key = (slug, mtime, len(source.highlights))

        cached = cache.get(slug)
        if cached and cached.get("key") == cache_key:
            # Use cached embeddings for this source
            for idx, highlight in enumerate(source.highlights):
                emb = cached["embeddings"][idx]
                entries.append((slug, idx, source, highlight))
                all_embeddings.append(emb)
            cached_count += len(source.highlights)
        else:
            # Recompute
            texts = [h.text for h in source.highlights]
            if not texts:
                continue
            embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            cache[slug] = {"key": cache_key, "embeddings": embeddings}
            for idx, highlight in enumerate(source.highlights):
                entries.append((slug, idx, source, highlight))
                all_embeddings.append(embeddings[idx])
            updated.append(slug)

    # Prune stale slugs from cache
    active_slugs = {s.slug for s in sources}
    stale = [k for k in cache if k not in active_slugs]
    for k in stale:
        del cache[k]

    # Save updated cache
    try:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"[similarity] Cache save failed: {e}")

    built_at = time.time()
    index = SimilarityIndex()
    if entries:
        matrix = np.vstack(all_embeddings)
        index.build(entries, matrix, built_at)

    stats = {
        "updated": updated,
        "cached_count": cached_count,
        "total_highlights": len(entries),
        "built_at": built_at,
    }
    print(
        f"[similarity] Index built: {len(entries)} highlights "
        f"({len(updated)} sources recomputed, {cached_count} from cache)"
    )
    return index, stats
