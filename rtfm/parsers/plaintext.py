"""Plain-text / source-code parser for rtfm.

Handles any text-based file that does not have a specialised parser
(source code, config files, plain .txt, etc.).

Chunking strategy: split at line boundaries aiming for ~500 chars per chunk.
"""

import hashlib
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

TARGET_CHUNK_CHARS = 500
MIN_CHUNK_CHARS = 100
MAX_CHUNK_CHARS = 1200


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _chunk_lines(text: str) -> list[str]:
    """Split *text* into chunks of ~TARGET_CHUNK_CHARS respecting line boundaries."""
    lines = text.split("\n")
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for the newline
        if buf and buf_len + line_len > TARGET_CHUNK_CHARS:
            chunk_text = "\n".join(buf)
            if len(chunk_text) > MAX_CHUNK_CHARS:
                # Force-split oversized buffer
                while len(chunk_text) > MAX_CHUNK_CHARS:
                    chunks.append(chunk_text[:MAX_CHUNK_CHARS])
                    chunk_text = chunk_text[MAX_CHUNK_CHARS:]
                if chunk_text.strip():
                    buf = [chunk_text]
                    buf_len = len(chunk_text)
                else:
                    buf = []
                    buf_len = 0
            else:
                chunks.append(chunk_text)
                buf = []
                buf_len = 0
        buf.append(line)
        buf_len += line_len

    # Flush remaining buffer
    if buf:
        remainder = "\n".join(buf)
        if chunks and len(remainder) < MIN_CHUNK_CHARS:
            chunks[-1] += "\n" + remainder
        else:
            chunks.append(remainder)

    return [c for c in chunks if c.strip()]


@ParserRegistry.register
class PlainTextParser(BaseParser):
    """Parser for plain text and source-code files."""

    extensions = [
        # Code (no dedicated parser yet)
        ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java",
        ".css", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
        ".swift", ".kt", ".r", ".sql", ".lua", ".pl", ".scala",
        # Plain text and config
        ".txt", ".cfg", ".toml",
    ]
    name = "plaintext"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}

        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return

        book_title = metadata.get("title", path.name)
        book_slug = metadata.get("book_slug", self._path_to_slug(path))
        book_file = metadata.get("source_file", str(path))

        chunks = _chunk_lines(text)

        char_pos = 0
        for idx, chunk_text in enumerate(chunks, 1):
            page = max(1, (char_pos // 2500) + 1)
            chunk_id = f"{book_slug}-{idx:04d}"

            yield Chunk(
                id=chunk_id,
                content=chunk_text,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=path.name,
                chapter_num=idx,
                page_start=page,
                page_end=page,
                paragraph=1,
                content_chars=len(chunk_text),
                content_hash=_content_hash(chunk_text),
                metadata=metadata.get("extended", {}),
            )
            char_pos += len(chunk_text)

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        """Convert a file path to a URL-friendly slug."""
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
