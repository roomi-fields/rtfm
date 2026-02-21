"""Shell script parser — function-aware chunking.

Splits .sh / .bash / .zsh files by function definitions.
Code outside functions is grouped into a "global" chunk.
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

# Match bash function definitions:
#   function foo { ... }
#   foo() { ... }
FUNC_DEF_RE = re.compile(
    r"^(?:function\s+(\w[\w-]*)|(\w[\w-]*)\s*\(\s*\))\s*\{?\s*$",
    re.MULTILINE,
)


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _find_function_end(lines: list[str], start: int) -> int:
    """Find the closing brace of a function starting at *start*.

    Counts brace nesting.  Returns the index of the closing brace line.
    If no closing brace is found, returns len(lines) - 1.
    """
    depth = 0
    for i in range(start, len(lines)):
        line = lines[i]
        # Count braces (ignore braces in strings/comments for simplicity)
        depth += line.count("{") - line.count("}")
        if depth <= 0 and i > start:
            return i
    return len(lines) - 1


def _extract_blocks(text: str) -> list[dict]:
    """Split shell script into function blocks + global code."""
    lines = text.splitlines(keepends=True)
    blocks: list[dict] = []
    used_lines: set[int] = set()

    # Find all functions
    for m in FUNC_DEF_RE.finditer(text):
        func_name = m.group(1) or m.group(2)

        # Find which line this match starts on
        line_start = text[:m.start()].count("\n")
        line_end = _find_function_end(lines, line_start)

        func_text = "".join(lines[line_start:line_end + 1]).strip()
        if func_text:
            blocks.append({
                "label": f"function {func_name}",
                "content": func_text,
                "lineno": line_start + 1,
                "end_lineno": line_end + 1,
            })
            used_lines.update(range(line_start, line_end + 1))

    # Collect global code (lines not inside any function)
    global_lines: list[str] = []
    for i, line in enumerate(lines):
        if i not in used_lines:
            global_lines.append(line)

    global_text = "".join(global_lines).strip()
    if global_text:
        # Insert global block at the beginning
        blocks.insert(0, {
            "label": "global",
            "content": global_text,
            "lineno": 1,
            "end_lineno": len(lines),
        })

    # Sort by line number
    blocks.sort(key=lambda b: b["lineno"])

    # Split oversized blocks
    final: list[dict] = []
    for b in blocks:
        if len(b["content"]) <= MAX_CHUNK_CHARS:
            final.append(b)
        else:
            text = b["content"]
            end_line = b.get("end_lineno", b["lineno"])
            part = 1
            while len(text) > MAX_CHUNK_CHARS:
                cut = text.rfind("\n", 0, MAX_CHUNK_CHARS)
                if cut < MIN_CHUNK_CHARS:
                    cut = MAX_CHUNK_CHARS
                final.append({
                    "label": b["label"],
                    "content": text[:cut].rstrip(),
                    "lineno": b["lineno"],
                    "end_lineno": end_line,
                })
                text = text[cut:].lstrip("\n")
                part += 1
            if text.strip():
                final.append({
                    "label": b["label"] + (" (cont.)" if part > 1 else ""),
                    "content": text,
                    "lineno": b["lineno"],
                    "end_lineno": end_line,
                })

    # Merge tiny global blocks only (never merge named functions)
    merged: list[dict] = []
    for b in final:
        if (merged and len(b["content"]) < MIN_CHUNK_CHARS
                and b["label"] == "global" and merged[-1]["label"] == "global"):
            merged[-1]["content"] += "\n\n" + b["content"]
        else:
            merged.append(b)

    return [b for b in merged if b["content"].strip()]


@ParserRegistry.register
class ShellParser(BaseParser):
    """Parser for shell scripts — one chunk per function."""

    extensions = [".sh", ".bash", ".zsh"]
    name = "shell"

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

        blocks = _extract_blocks(text)

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
                chapter_title=block["label"],
                chapter_num=idx,
                page_start=block["lineno"],
                page_end=block["lineno"],
                paragraph=1,
                line_start=block["lineno"],
                line_end=block.get("end_lineno", block["lineno"]),
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
