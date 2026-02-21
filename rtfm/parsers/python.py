"""Python parser — AST-aware chunking by class and function.

Each top-level class or function becomes its own chunk.  Module-level code
(imports, constants, top-level statements) is grouped into an "module" chunk.
Nested functions/methods stay with their parent.

Falls back to line-based chunking if the file has syntax errors.
"""

import ast
import hashlib
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

TARGET_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 100
MAX_CHUNK_CHARS = 3000


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _node_label(node: ast.AST) -> str:
    """Human-readable label for an AST node."""
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return f"def {node.name}"
    return "module"


def _extract_blocks(source: str) -> list[dict]:
    """Split Python source into semantic blocks using AST.

    Returns a list of dicts: {label, content, lineno}.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Unparseable — return whole file as one block
        return [{"label": "module", "content": source, "lineno": 1,
                 "end_lineno": source.count("\n") + 1}]

    lines = source.splitlines(keepends=True)
    blocks: list[dict] = []

    # Sort top-level nodes by line number
    top_nodes = [n for n in ast.iter_child_nodes(tree)
                 if hasattr(n, "lineno")]
    top_nodes.sort(key=lambda n: n.lineno)

    prev_end = 0  # 0-indexed line

    for node in top_nodes:
        node_start = node.lineno - 1  # 0-indexed

        # Module-level code between previous node and this one
        if node_start > prev_end:
            preamble = "".join(lines[prev_end:node_start]).strip()
            if preamble:
                blocks.append({
                    "label": "module",
                    "content": preamble,
                    "lineno": prev_end + 1,
                    "end_lineno": node_start,
                })

        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            node_end = node.end_lineno or node.lineno
            block_text = "".join(lines[node_start:node_end]).rstrip()
            blocks.append({
                "label": _node_label(node),
                "content": block_text,
                "lineno": node.lineno,
                "end_lineno": node_end,
            })
            prev_end = node_end
        else:
            # Other top-level statement (assignment, expression, etc.)
            node_end = getattr(node, "end_lineno", node.lineno) or node.lineno
            prev_end = node_end

    # Trailing module code
    if prev_end < len(lines):
        tail = "".join(lines[prev_end:]).strip()
        if tail:
            blocks.append({
                "label": "module",
                "content": tail,
                "lineno": prev_end + 1,
                "end_lineno": len(lines),
            })

    # Merge consecutive "module" blocks
    merged: list[dict] = []
    for b in blocks:
        if merged and merged[-1]["label"] == "module" and b["label"] == "module":
            merged[-1]["content"] += "\n\n" + b["content"]
            merged[-1]["end_lineno"] = b.get("end_lineno", b["lineno"])
        else:
            merged.append(b)

    # Split oversized blocks
    final: list[dict] = []
    for b in merged:
        if len(b["content"]) <= MAX_CHUNK_CHARS:
            final.append(b)
        else:
            # Split large class/function by sub-chunks
            text = b["content"]
            end_line = b.get("end_lineno", b["lineno"])
            while len(text) > MAX_CHUNK_CHARS:
                cut = text.rfind("\n\n", 0, MAX_CHUNK_CHARS)
                if cut < MIN_CHUNK_CHARS:
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
            if text.strip():
                final.append({
                    "label": b["label"] + " (cont.)",
                    "content": text,
                    "lineno": b["lineno"],
                    "end_lineno": end_line,
                })

    return [b for b in final if b["content"].strip()]


@ParserRegistry.register
class PythonParser(BaseParser):
    """Parser for Python source files — one chunk per class/function."""

    extensions = [".py"]
    name = "python"

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
