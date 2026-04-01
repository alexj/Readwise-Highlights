"""
Parses Readwise-exported markdown highlight files into structured Python objects.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Highlight:
    text: str
    link: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Source:
    title: str
    author: str
    source_type: str  # 'book' or 'article'
    cover_image: Optional[str]
    url: Optional[str]
    highlights: list[Highlight]
    filepath: Path

    @property
    def slug(self) -> str:
        return self.filepath.stem


# Matches the Readwise link at the end of a highlight line:
# ([View Highlight](https://...)) or ([Location 303](https://...))
_LINK_PATTERN = re.compile(r'\s*\(\[(?:View Highlight|Location \d+)\]\((https?://[^\)]+)\)\)\s*$')


def parse_file(filepath: Path) -> Source:
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
                highlights.append(Highlight(text=raw, link=link, tags=tags))

        j += 1

    return Source(
        title=title,
        author=author,
        source_type=source_type,
        cover_image=cover_image,
        url=url,
        highlights=highlights,
        filepath=filepath,
    )


def load_all(base_dir: Path) -> list[Source]:
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
