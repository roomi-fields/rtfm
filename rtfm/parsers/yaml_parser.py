"""YAML parser — chunk by top-level key.

Each top-level key (or group of small keys) becomes a chunk.
Preserves the YAML structure so the indexed content is readable.
Multi-document YAML (---) is supported.
"""

import hashlib
import re
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

TARGET_CHUNK_CHARS = 800
MIN_CHUNK_CHARS = 100
MAX_CHUNK_CHARS = 2000


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _split_top_level_keys(text: str) -> list[dict]:
    """Split YAML into blocks, one per top-level key.

    A top-level key is a line that starts with a non-space character and
    contains a colon.  Everything indented below it belongs to the same block.
    """
    blocks: list[dict] = []
    current_key: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip()

        # Detect top-level key: starts at column 0, contains ':'
        if stripped and not stripped[0].isspace() and ":" in stripped:
            # Save previous block
            if current_lines:
                content = "".join(current_lines).strip()
                if content:
                    blocks.append({"key": current_key or "root", "content": content})

            current_key = stripped.split(":")[0].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last block
    if current_lines:
        content = "".join(current_lines).strip()
        if content:
            blocks.append({"key": current_key or "root", "content": content})

    return blocks


def _merge_small_blocks(blocks: list[dict]) -> list[dict]:
    """Merge consecutive small blocks into larger chunks."""
    if not blocks:
        return []

    merged: list[dict] = []
    buf_keys: list[str] = []
    buf_content: list[str] = []
    buf_len = 0

    for b in blocks:
        content = b["content"]

        if buf_len + len(content) > TARGET_CHUNK_CHARS and buf_content:
            merged.append({
                "key": ", ".join(buf_keys),
                "content": "\n\n".join(buf_content),
            })
            buf_keys = []
            buf_content = []
            buf_len = 0

        buf_keys.append(b["key"])
        buf_content.append(content)
        buf_len += len(content)

    if buf_content:
        # Merge tiny remainder with previous
        if merged and buf_len < MIN_CHUNK_CHARS:
            merged[-1]["content"] += "\n\n" + "\n\n".join(buf_content)
            merged[-1]["key"] += ", " + ", ".join(buf_keys)
        else:
            merged.append({
                "key": ", ".join(buf_keys),
                "content": "\n\n".join(buf_content),
            })

    # Split oversized blocks
    final: list[dict] = []
    for b in merged:
        if len(b["content"]) <= MAX_CHUNK_CHARS:
            final.append(b)
        else:
            text = b["content"]
            part = 1
            while len(text) > MAX_CHUNK_CHARS:
                cut = text.rfind("\n", 0, MAX_CHUNK_CHARS)
                if cut < MIN_CHUNK_CHARS:
                    cut = MAX_CHUNK_CHARS
                final.append({
                    "key": f"{b['key']} (part {part})",
                    "content": text[:cut].rstrip(),
                })
                text = text[cut:].lstrip("\n")
                part += 1
            if text.strip():
                final.append({
                    "key": f"{b['key']} (part {part})" if part > 1 else b["key"],
                    "content": text,
                })

    return final


@ParserRegistry.register
class YAMLParser(BaseParser):
    """Parser for YAML files — one chunk per top-level key."""

    extensions = [".yaml", ".yml"]
    name = "yaml"

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

        # Handle multi-document YAML: split on --- but keep first doc marker
        docs = re.split(r"^---\s*$", text, flags=re.MULTILINE)
        docs = [d.strip() for d in docs if d.strip()]

        all_blocks: list[dict] = []
        for doc in docs:
            blocks = _split_top_level_keys(doc)
            all_blocks.extend(blocks)

        chunks = _merge_small_blocks(all_blocks)

        for idx, block in enumerate(chunks, 1):
            chunk_text = block["content"]
            if not chunk_text.strip():
                continue

            chunk_id = f"{book_slug}-{idx:04d}"

            yield Chunk(
                id=chunk_id,
                content=chunk_text,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=block["key"],
                chapter_num=idx,
                page_start=1,
                page_end=1,
                paragraph=1,
                content_chars=len(chunk_text),
                content_hash=_content_hash(chunk_text),
                metadata=metadata.get("extended", {}),
            )

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
