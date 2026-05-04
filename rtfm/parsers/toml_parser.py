"""TOML parser — chunk by top-level table, with dependency edges.

Most config-as-TOML files have a manageable set of top-level tables
(`[project]`, `[tool.*]`, `[dependencies]`, …). We turn each into a chunk
re-serialised as TOML so the indexed text stays readable.

Dependencies are extracted as `EdgeCandidate(relation_type="depends_on")`
to feed the graph. Recognised flavours:

  - `pyproject.toml`  : [project].dependencies, [project.optional-dependencies.*],
                        [tool.poetry.dependencies], [tool.poetry.dev-dependencies],
                        [build-system].requires
  - `Cargo.toml`      : [dependencies], [dev-dependencies], [build-dependencies]

Stdlib `tomllib` (Python 3.11+) is preferred; falls back to `tomli`.
If neither is importable, the parser is not registered.
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Iterator, Optional

from rtfm.core.models import Chunk, EdgeCandidate
from rtfm.parsers.base import BaseParser, ParserRegistry

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

TARGET_CHUNK_CHARS = 1200
MAX_CHUNK_CHARS = 3000

# Match a dep specifier like "requests>=2.0" or "numpy" → name only.
DEP_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+")


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _serialise_value(value: Any, indent: int = 0) -> str:
    """Best-effort TOML-ish rendering for indexed display."""
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if isinstance(v, dict):
                lines.append(f"{pad}[{k}]")
                lines.append(_serialise_value(v, indent + 1))
            elif isinstance(v, list):
                lines.append(f"{pad}{k} = {_render_list(v)}")
            else:
                lines.append(f"{pad}{k} = {_render_scalar(v)}")
        return "\n".join(lines)
    if isinstance(value, list):
        return _render_list(value)
    return _render_scalar(value)


def _render_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return f'"{v}"'


def _render_list(items: list) -> str:
    if not items:
        return "[]"
    rendered = [_render_scalar(x) if not isinstance(x, (dict, list)) else str(x) for x in items]
    return "[" + ", ".join(rendered) + "]"


def _dep_name(spec: str) -> Optional[str]:
    """Extract the package name from a dep spec string."""
    if not isinstance(spec, str):
        return None
    m = DEP_NAME_RE.match(spec.strip())
    return m.group(0) if m else None


def _walk_deps(data: dict, source_file: str) -> list[EdgeCandidate]:
    """Extract dependency edges from common TOML schemas."""
    edges: list[EdgeCandidate] = []

    def add(name: str, detail: str) -> None:
        if name:
            edges.append(EdgeCandidate(
                source_file=source_file,
                target_ref=name,
                relation_type="depends_on",
                source_detail=detail,
            ))

    # PEP 621 / pyproject.toml
    project = data.get("project", {})
    if isinstance(project, dict):
        for spec in project.get("dependencies", []) or []:
            n = _dep_name(spec)
            if n:
                add(n, f"[project] {spec}")
        opt = project.get("optional-dependencies", {})
        if isinstance(opt, dict):
            for group, specs in opt.items():
                for spec in specs or []:
                    n = _dep_name(spec)
                    if n:
                        add(n, f"[project.optional-dependencies.{group}] {spec}")

    # build-system
    bs = data.get("build-system", {})
    if isinstance(bs, dict):
        for spec in bs.get("requires", []) or []:
            n = _dep_name(spec)
            if n:
                add(n, f"[build-system] {spec}")

    # Poetry
    tool = data.get("tool", {})
    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
    if isinstance(poetry, dict):
        for section in ("dependencies", "dev-dependencies"):
            deps = poetry.get(section, {})
            if isinstance(deps, dict):
                for name, spec in deps.items():
                    if name == "python":
                        continue
                    add(name, f"[tool.poetry.{section}] {name} = {spec!r}")

    # Cargo
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        deps = data.get(section)
        if isinstance(deps, dict):
            for name, spec in deps.items():
                add(name, f"[{section}] {name} = {spec!r}")

    return edges


@ParserRegistry.register
class TOMLParser(BaseParser):
    """Parser for TOML config files — one chunk per top-level table."""

    extensions = [".toml"]
    name = "toml"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        if tomllib is None:
            return False
        return super().can_parse(path)

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        if tomllib is None:
            return
        metadata = metadata or {}

        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, Exception):  # tomllib.TOMLDecodeError or any read error
            return
        if not isinstance(data, dict) or not data:
            return

        book_title = metadata.get("title", path.name)
        book_slug = metadata.get("book_slug", self._path_to_slug(path))
        book_file = metadata.get("source_file", str(path))
        ext_meta = metadata.get("extended", {})

        # One chunk per top-level table; merge tiny ones.
        blocks: list[dict] = []
        for key, value in data.items():
            if isinstance(value, dict):
                content = f"[{key}]\n{_serialise_value(value, indent=0)}"
            elif isinstance(value, list):
                content = f"{key} = {_render_list(value)}"
            else:
                content = f"{key} = {_render_scalar(value)}"
            blocks.append({"key": key, "content": content})

        merged = _merge_blocks(blocks)

        for idx, block in enumerate(merged, 1):
            content = block["content"]
            yield Chunk(
                id=f"{book_slug}-{idx:04d}",
                content=content,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=block["key"],
                chapter_num=idx,
                page_start=1,
                page_end=1,
                paragraph=1,
                content_chars=len(content),
                content_hash=_content_hash(content),
                metadata=ext_meta,
            )

    def extract_edges(self, path: Path, metadata: Optional[dict] = None) -> list[EdgeCandidate]:
        if tomllib is None:
            return []
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, Exception):
            return []
        if not isinstance(data, dict):
            return []
        return _walk_deps(data, str(path))

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")


def _merge_blocks(blocks: list[dict]) -> list[dict]:
    """Coalesce small blocks; split oversized ones."""
    merged: list[dict] = []
    buf_keys: list[str] = []
    buf_content: list[str] = []
    buf_len = 0

    for b in blocks:
        if buf_len + len(b["content"]) > TARGET_CHUNK_CHARS and buf_content:
            merged.append({
                "key": ", ".join(buf_keys),
                "content": "\n\n".join(buf_content),
            })
            buf_keys, buf_content, buf_len = [], [], 0
        buf_keys.append(b["key"])
        buf_content.append(b["content"])
        buf_len += len(b["content"])

    if buf_content:
        merged.append({
            "key": ", ".join(buf_keys),
            "content": "\n\n".join(buf_content),
        })

    final: list[dict] = []
    for b in merged:
        if len(b["content"]) <= MAX_CHUNK_CHARS:
            final.append(b)
            continue
        text = b["content"]
        part = 1
        while len(text) > MAX_CHUNK_CHARS:
            cut = text.rfind("\n", 0, MAX_CHUNK_CHARS)
            if cut < 200:
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
