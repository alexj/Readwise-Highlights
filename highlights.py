"""
Parses Readwise-exported markdown highlight files into structured Python objects.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode


@dataclass
class Highlight:
    text: str
    link: str                                    # "View" / Kindle location URL
    tags: list[str] = field(default_factory=list)
    note: str = ""
    is_favorite: bool = False
    readwise_id: Optional[int] = None


@dataclass
class Source:
    title: str
    author: str
    source_type: str                             # 'book' or 'article'
    slug: str
    highlights: list[Highlight]
    cover_image: Optional[str] = None
    url: Optional[str] = None                   # article source URL
    asin: Optional[str] = None                  # Amazon ASIN (from API)
    filepath: Optional[Path] = None             # set only when loaded from .md files


    @property
    def parsed_authors(self) -> list[str]:
        return parse_authors(self.author)

    @property
    def external_url(self) -> Optional[str]:
        """
        Best available external URL for this source. Mirrors the tiered logic
        from feed-parser/readwise.py build_book_url(), minus the Google Books
        HTTP call (not appropriate at parse time).

        Articles: source URL → DuckDuckGo search
        Books:    stored ASIN → ASIN from Kindle links → Amazon keyword search
        """
        if self.source_type == "article":
            if self.url:
                return self.url
            params = {"q": f"{self.author} {self.title}"}
            return "https://duckduckgo.com/?" + urlencode(params)

        # Books: use stored ASIN first (populated from API)
        if self.asin:
            return f"https://www.amazon.com/dp/{self.asin}/"

        # Fallback: extract ASIN from any Kindle highlight link
        for h in self.highlights:
            m = _ASIN_RE.search(h.link)
            if m:
                return f"https://www.amazon.com/dp/{m.group(1)}/"

        # Fallback: Amazon keyword search
        params = {"field-keywords": f"{self.author} {self.title}"}
        return (
            "https://www.amazon.com/s/ref=nb_sb_noss?url=search-alias%3Ddigital-text&"
            + urlencode(params)
        )


# Matches any Readwise/Kindle link at the end of a highlight line:
# ([View Highlight](https://...)) or ([Location 303](https://...)) etc.
_LINK_PATTERN = re.compile(r'\s*\(\[(?:[^\]]+)\]\((https?://[^\)]+)\)\)\s*$')

# Extracts Amazon ASIN from a Readwise to_kindle URL
_ASIN_RE = re.compile(r'[?&]asin=([A-Z0-9]+)', re.IGNORECASE)

# Strips parenthetical role descriptors like (Foreword), (Translator), (Editor)
_ROLE_RE = re.compile(r'\s*\([^)]+\)')


def parse_authors(author_string: str) -> list[str]:
    """
    Split a combined author string into individual author names.

    Handles these formats (all found in the actual data):
      - "Barack Obama"
      - "Bob Woodward and Robert Costa"
      - "Roger Fisher, William L. Ury, Bruce Patton"
      - "Jake Knapp, John Zeratsky, and Braden Kowitz"
      - "Adam Rutherford, Siddhartha Mukherjee (Foreword)"
      - "Jocko Willink , Leif Babin"  (stray whitespace)
    """
    # Normalize ", and " → " and " so the subsequent split is clean
    text = re.sub(r',\s+and\s+', ' and ', author_string, flags=re.IGNORECASE)
    # Split on " and "
    parts = re.split(r'\s+and\s+', text, flags=re.IGNORECASE)
    # Split each part on "," and flatten
    names = []
    for part in parts:
        names.extend(part.split(','))
    # Strip whitespace and parenthetical roles; drop empty results
    result = []
    for name in names:
        cleaned = _ROLE_RE.sub('', name).strip()
        if cleaned:
            result.append(cleaned)
    return result


def author_slug(name: str) -> str:
    """Convert an author name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def parse_file(filepath: Path) -> "Source":
    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines()

    title = ""
    author = ""
    source_type = "article"
    cover_image = None
    url = None
    highlights = []

    i = 0

    # Title (H1)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Author (H3)
    for j in range(i + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("### ") and stripped != "### Highlights":
            author = stripped[4:].strip()
            i = j
            break

    # Type tag + URL + cover image (scan until ### Highlights)
    for j in range(i + 1, len(lines)):
        line = lines[j].strip()

        if line == "### Highlights":
            i = j
            break
        elif "#Highlights/books#" in line:
            source_type = "book"
        elif "#Highlights/articles#" in line:
            source_type = "article"
        elif line.startswith("- URL:"):
            url = line[len("- URL:"):].strip()
        elif line.startswith("https://") and not cover_image:
            cover_image = line

    # Highlights (everything after ### Highlights)
    j = i + 1
    while j < len(lines):
        line = lines[j]

        if line.startswith("- ") and not line.startswith("- URL:"):
            raw = line[2:].strip()
            link = ""

            match = _LINK_PATTERN.search(raw)
            if match:
                link = match.group(1)
                raw = raw[: match.start()].strip()

            # Strip surrounding quotes added by Readwise for article highlights
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1].strip()

            # Check for tags on the very next line
            tags = []
            if j + 1 < len(lines) and "**Tags:**" in lines[j + 1]:
                tags = re.findall(r"#(\w+)", lines[j + 1])

            if raw:
                highlights.append(Highlight(
                    text=raw,
                    link=link,
                    tags=tags,
                    is_favorite="favorite" in tags,
                ))

        j += 1

    return Source(
        title=title,
        author=author,
        source_type=source_type,
        slug=filepath.stem,
        highlights=highlights,
        cover_image=cover_image,
        url=url,
        filepath=filepath,
    )


def load_all(base_dir: Path) -> list["Source"]:
    sources = []
    for subdir in ("Articles", "Books"):
        dir_path = base_dir / subdir
        if not dir_path.exists():
            continue
        for filepath in sorted(dir_path.glob("*.md")):
            try:
                source = parse_file(filepath)
                if source.title:
                    sources.append(source)
            except Exception as exc:
                print(f"[highlights] Error parsing {filepath.name}: {exc}")

    sources.sort(key=lambda s: s.title.lower())
    return sources
