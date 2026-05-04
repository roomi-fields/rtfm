"""Jupyter notebook parser — chunk by markdown headings + cells.

A `.ipynb` is JSON internally. We walk the cells in order, use markdown
heading cells as section breaks, and emit one chunk per logical section.
Cell *outputs* are dropped (often huge, low signal — base64 images,
matplotlib reprs, full DataFrames, …); cell *source* is kept.

Each chunk contains the markdown text and any following code cells, so
the agent sees both the narration and the code in context.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

TARGET_CHUNK_CHARS = 1500
MAX_CHUNK_CHARS = 4000
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _cell_source(cell: dict) -> str:
    src = cell.get("source", "")
    if isinstance(src, list):
        src = "".join(src)
    return src.rstrip()


def _format_cell(cell: dict) -> str:
    """Render a cell as markdown text (code cells get fenced)."""
    src = _cell_source(cell)
    if not src:
        return ""
    ctype = cell.get("cell_type", "")
    if ctype == "code":
        lang = "python"  # ipynb default; we don't introspect kernel
        return f"```{lang}\n{src}\n```"
    if ctype == "raw":
        return src
    # markdown / unknown — passthrough
    return src


def _first_heading(text: str) -> Optional[str]:
    m = HEADING_RE.search(text)
    if m:
        return m.group(2).strip()
    return None


@ParserRegistry.register
class JupyterParser(BaseParser):
    """Parser for Jupyter `.ipynb` files."""

    extensions = [".ipynb"]
    name = "jupyter"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}

        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            return

        cells = data.get("cells")
        if not isinstance(cells, list):
            return

        book_title = metadata.get("title", path.stem)
        book_slug = metadata.get("book_slug", self._path_to_slug(path))
        book_file = metadata.get("source_file", str(path))
        ext_meta = metadata.get("extended", {})

        # Group cells into sections delimited by top-level markdown headings.
        sections: list[dict] = []
        current_title: Optional[str] = None
        current_pieces: list[str] = []

        def _flush() -> None:
            if current_pieces:
                content = "\n\n".join(p for p in current_pieces if p).strip()
                if content:
                    sections.append({
                        "title": current_title or "(intro)",
                        "content": content,
                    })

        for cell in cells:
            if not isinstance(cell, dict):
                continue
            ctype = cell.get("cell_type", "")
            src = _cell_source(cell)
            if not src:
                continue

            # Markdown heading at the start of a cell → new section.
            if ctype == "markdown":
                heading = _first_heading(src)
                if heading and (current_pieces or current_title is not None):
                    _flush()
                    current_title = heading
                    current_pieces = [src]
                    continue
                if heading and current_title is None:
                    current_title = heading

            current_pieces.append(_format_cell(cell))

        _flush()

        # Split oversized sections (long markdown narration + many code cells).
        chunks_data: list[dict] = []
        for sec in sections:
            text = sec["content"]
            if len(text) <= MAX_CHUNK_CHARS:
                chunks_data.append(sec)
                continue
            part = 1
            buf = text
            while len(buf) > MAX_CHUNK_CHARS:
                cut = buf.rfind("\n\n", 0, MAX_CHUNK_CHARS)
                if cut < 200:
                    cut = MAX_CHUNK_CHARS
                chunks_data.append({
                    "title": f"{sec['title']} (part {part})",
                    "content": buf[:cut].rstrip(),
                })
                buf = buf[cut:].lstrip("\n")
                part += 1
            if buf.strip():
                chunks_data.append({
                    "title": f"{sec['title']} (part {part})" if part > 1 else sec["title"],
                    "content": buf,
                })

        for idx, sec in enumerate(chunks_data, 1):
            content = sec["content"]
            yield Chunk(
                id=f"{book_slug}-{idx:04d}",
                content=content,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=sec["title"],
                chapter_num=idx,
                page_start=1,
                page_end=1,
                paragraph=1,
                content_chars=len(content),
                content_hash=_content_hash(content),
                metadata=ext_meta,
            )

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.stem,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
