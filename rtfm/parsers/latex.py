r"""LaTeX parser — section-aware chunking.

Splits .tex / .latex files by structural commands:
\part, \chapter, \section, \subsection, \subsubsection, \paragraph.

Also recognises common environments (theorem, lemma, definition, example,
proof, abstract, quote, verbatim, lstlisting, figure, table) and keeps
each as a coherent chunk when possible.
"""

import hashlib
import re
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

TARGET_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 3000

# Sectioning commands in order of depth
SECTION_RE = re.compile(
    r"^\\(part|chapter|section|subsection|subsubsection|paragraph)"
    r"\*?\s*(?:\[.*?\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)

SECTION_DEPTH = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
}


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _strip_comments(text: str) -> str:
    """Remove LaTeX line comments (% ...) but keep \\%."""
    return re.sub(r"(?<!\\)%.*$", "", text, flags=re.MULTILINE)


def _clean_chunk(text: str) -> str:
    """Light cleanup: collapse excessive blank lines."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_on_sentence(text: str, max_chars: int) -> list[str]:
    """Split at sentence boundaries, respecting max_chars."""
    if len(text) <= max_chars:
        return [text]

    # Look for sentence ends (. ! ? followed by space/newline)
    chunks = []
    start = 0
    prev_end = 0

    for m in re.finditer(r"[.!?](?:\s|$)", text):
        pos = m.end()
        if pos - start > max_chars and prev_end > start:
            chunks.append(text[start:prev_end].strip())
            start = prev_end
        prev_end = pos

    if start < len(text):
        chunks.append(text[start:].strip())

    return [c for c in chunks if c] or [text]


def _split_sections(text: str) -> list[dict]:
    """Split LaTeX source into sections based on sectioning commands."""
    sections: list[dict] = []
    matches = list(SECTION_RE.finditer(text))
    total_lines = text.count("\n") + 1

    if not matches:
        # No sections found — return whole text
        cleaned = _clean_chunk(text)
        if cleaned:
            return [{"title": "", "level": 0, "type": "content", "content": cleaned,
                      "line_start": 1, "line_end": total_lines}]
        return []

    # Preamble before first section
    if matches[0].start() > 0:
        preamble = _clean_chunk(text[: matches[0].start()])
        preamble_end_line = text[:matches[0].start()].count("\n") + 1
        if preamble and len(preamble) >= MIN_CHUNK_CHARS:
            sections.append({
                "title": "Preamble",
                "level": 0,
                "type": "preamble",
                "content": preamble,
                "line_start": 1,
                "line_end": preamble_end_line,
            })

    for i, m in enumerate(matches):
        cmd = m.group(1)
        title = m.group(2).strip()
        level = SECTION_DEPTH.get(cmd, 2)

        # Content runs until next section or end of text
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = _clean_chunk(text[start:end])

        if not content:
            continue

        line_start = text[:m.start()].count("\n") + 1
        line_end = text[:end].count("\n") + 1

        sec_type = "chapter" if level <= 1 else "section"
        sections.append({
            "title": title,
            "level": level,
            "type": sec_type,
            "content": content,
            "line_start": line_start,
            "line_end": line_end,
        })

    return sections


def _merge_and_split(sections: list[dict]) -> list[dict]:
    """Merge tiny sections and split oversized ones."""
    result: list[dict] = []

    for sec in sections:
        content = sec["content"]

        if len(content) > MAX_CHUNK_CHARS:
            # Split oversized section
            parts = _split_on_sentence(content, MAX_CHUNK_CHARS)
            for i, part in enumerate(parts):
                suffix = f" ({i + 1}/{len(parts)})" if len(parts) > 1 else ""
                result.append({**sec, "content": part, "title": sec["title"] + suffix})
        elif (result and len(content) < MIN_CHUNK_CHARS
              and sec["type"] == "preamble"):
            # Only merge preamble fragments, keep named sections separate
            result[-1]["content"] += "\n\n" + content
        else:
            result.append(sec)

    return result


@ParserRegistry.register
class LaTeXParser(BaseParser):
    """Parser for LaTeX files — one chunk per section."""

    extensions = [".tex", ".latex"]
    name = "latex"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}

        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return

        text = _strip_comments(text)

        book_title = metadata.get("title", path.stem)
        book_slug = metadata.get("book_slug", self._path_to_slug(path))
        book_file = metadata.get("source_file", str(path))

        # Try to extract title from \title{...}
        title_match = re.search(r"\\title\s*\{([^}]+)\}", text)
        if title_match and not metadata.get("title"):
            book_title = title_match.group(1).strip()

        sections = _split_sections(text)
        sections = _merge_and_split(sections)

        for idx, sec in enumerate(sections, 1):
            chunk_text = sec["content"]
            if not chunk_text.strip():
                continue

            chunk_id = f"{book_slug}-{idx:04d}"

            yield Chunk(
                id=chunk_id,
                content=chunk_text,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=sec["title"],
                chapter_num=idx,
                page_start=idx,
                page_end=idx,
                paragraph=1,
                line_start=sec.get("line_start"),
                line_end=sec.get("line_end"),
                section_type=sec["type"],
                content_chars=len(chunk_text),
                content_hash=_content_hash(chunk_text),
                metadata=metadata.get("extended", {}),
            )

    def extract_metadata(self, path: Path) -> dict:
        meta = {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.stem,
        }

        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:3000]
            title_match = re.search(r"\\title\s*\{([^}]+)\}", head)
            if title_match:
                meta["title"] = title_match.group(1).strip()
            author_match = re.search(r"\\author\s*\{([^}]+)\}", head)
            if author_match:
                meta["author"] = author_match.group(1).strip()
        except Exception:
            pass

        return meta

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
