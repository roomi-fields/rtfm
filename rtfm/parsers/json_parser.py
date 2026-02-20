"""JSON parser — chunk by top-level key or array element.

For objects: each top-level key becomes a chunk (small keys are merged).
For arrays: elements are grouped into chunks of ~TARGET_CHUNK_CHARS.
The JSON is re-serialised with indentation so the indexed content is readable.
"""

import hashlib
import json
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

TARGET_CHUNK_CHARS = 800
MIN_CHUNK_CHARS = 100
MAX_CHUNK_CHARS = 2000


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _chunks_from_object(data: dict) -> list[dict]:
    """Split a JSON object into chunks, one per top-level key."""
    blocks: list[dict] = []

    for key, value in data.items():
        serialised = json.dumps({key: value}, indent=2, ensure_ascii=False, default=str)
        blocks.append({"key": key, "content": serialised})

    return _merge_small_blocks(blocks)


def _chunks_from_array(data: list) -> list[dict]:
    """Group array elements into chunks."""
    blocks: list[dict] = []
    buf: list = []
    buf_len = 0

    for i, item in enumerate(data):
        serialised = json.dumps(item, indent=2, ensure_ascii=False, default=str)

        if buf and buf_len + len(serialised) > TARGET_CHUNK_CHARS:
            content = json.dumps(buf, indent=2, ensure_ascii=False, default=str)
            blocks.append({
                "key": f"items [{i - len(buf)}-{i - 1}]",
                "content": content,
            })
            buf = []
            buf_len = 0

        buf.append(item)
        buf_len += len(serialised)

    if buf:
        total = len(data)
        start = total - len(buf)
        content = json.dumps(buf, indent=2, ensure_ascii=False, default=str)
        if blocks and len(content) < MIN_CHUNK_CHARS:
            blocks[-1]["content"] += "\n" + content
        else:
            blocks.append({
                "key": f"items [{start}-{total - 1}]",
                "content": content,
            })

    return blocks


def _merge_small_blocks(blocks: list[dict]) -> list[dict]:
    """Merge consecutive small blocks."""
    if not blocks:
        return []

    merged: list[dict] = []
    buf_keys: list[str] = []
    buf_content: list[str] = []
    buf_len = 0

    for b in blocks:
        if buf_len + len(b["content"]) > TARGET_CHUNK_CHARS and buf_content:
            merged.append({
                "key": ", ".join(buf_keys),
                "content": "\n".join(buf_content),
            })
            buf_keys = []
            buf_content = []
            buf_len = 0

        buf_keys.append(b["key"])
        buf_content.append(b["content"])
        buf_len += len(b["content"])

    if buf_content:
        if merged and buf_len < MIN_CHUNK_CHARS:
            merged[-1]["content"] += "\n" + "\n".join(buf_content)
            merged[-1]["key"] += ", " + ", ".join(buf_keys)
        else:
            merged.append({
                "key": ", ".join(buf_keys),
                "content": "\n".join(buf_content),
            })

    # Split oversized
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
class JSONParser(BaseParser):
    """Parser for JSON files — one chunk per top-level key or element group."""

    extensions = [".json"]
    name = "json"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}

        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return  # skip unparseable JSON

        book_title = metadata.get("title", path.name)
        book_slug = metadata.get("book_slug", self._path_to_slug(path))
        book_file = metadata.get("source_file", str(path))

        if isinstance(data, dict):
            blocks = _chunks_from_object(data)
        elif isinstance(data, list):
            blocks = _chunks_from_array(data)
        else:
            # Scalar value — single chunk
            blocks = [{"key": "value", "content": json.dumps(data, indent=2, default=str)}]

        for idx, block in enumerate(blocks, 1):
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
