"""XLSX parser — index Excel workbooks by sheet (header + sample).

Optional dependency: `openpyxl`. If unavailable, the parser is not
registered (the registry simply returns no parser for `.xlsx`).

Per workbook we emit:

  - 1 overview chunk: file path, list of sheets with row × col counts
  - per sheet: schema chunk (column headers with inferred types)
  - per sheet: sample chunk (first N rows formatted as a table)

`read_only=True` is used so massive workbooks don't load fully in memory.
"""

import hashlib
from pathlib import Path
from typing import Any, Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

try:
    from openpyxl import load_workbook  # type: ignore
except ImportError:
    load_workbook = None  # type: ignore

SAMPLE_ROWS = 6
MAX_CELL_CHARS = 80
MAX_CHUNK_CHARS = 4000


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + "…"
    return text


def _infer_type(values: list[Any]) -> str:
    seen_int = seen_float = seen_bool = seen_str = seen_dt = 0
    for v in values:
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            seen_bool += 1
        elif isinstance(v, int):
            seen_int += 1
        elif isinstance(v, float):
            seen_float += 1
        elif hasattr(v, "isoformat"):
            seen_dt += 1
        else:
            seen_str += 1
    if seen_str:
        return "text"
    if seen_dt:
        return "datetime"
    if seen_float:
        return "float"
    if seen_int:
        return "int"
    if seen_bool:
        return "bool"
    return "empty"


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return "(empty)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths) and len(cell) > widths[i]:
                widths[i] = len(cell)
    sep = " | "
    out = [sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("-+-".join("-" * w for w in widths))
    for row in rows:
        cells = [
            (row[i] if i < len(row) else "").ljust(widths[i])
            for i in range(len(headers))
        ]
        out.append(sep.join(cells))
    return "\n".join(out)


def _truncate(text: str, limit: int = MAX_CHUNK_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n… (truncated)"


@ParserRegistry.register
class XLSXParser(BaseParser):
    """Parser for Excel `.xlsx` workbooks."""

    extensions = [".xlsx"]
    name = "xlsx"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        if load_workbook is None:
            return False
        return super().can_parse(path)

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        if load_workbook is None:
            return
        metadata = metadata or {}

        try:
            wb = load_workbook(filename=str(path), read_only=True, data_only=True)
        except Exception:
            return

        try:
            sheet_names = wb.sheetnames
            if not sheet_names:
                return

            book_title = metadata.get("title", path.name)
            book_slug = metadata.get("book_slug", self._path_to_slug(path))
            book_file = metadata.get("source_file", str(path))
            ext_meta = metadata.get("extended", {})
            idx = 0

            def _new_chunk(chapter_title: str, content: str) -> Chunk:
                nonlocal idx
                idx += 1
                return Chunk(
                    id=f"{book_slug}-{idx:04d}",
                    content=content,
                    book_title=book_title,
                    book_slug=book_slug,
                    book_file=book_file,
                    chapter_title=chapter_title,
                    chapter_num=idx,
                    page_start=1,
                    page_end=1,
                    paragraph=1,
                    content_chars=len(content),
                    content_hash=_content_hash(content),
                    metadata=ext_meta,
                )

            # ── Pre-collect per-sheet metadata for the overview ────────
            sheets_info: list[tuple[str, list[Any], list[list[Any]], int]] = []
            for name in sheet_names:
                ws = wb[name]
                rows_iter = ws.iter_rows(values_only=True)
                try:
                    header_row = next(rows_iter)
                except StopIteration:
                    sheets_info.append((name, [], [], 0))
                    continue
                headers = list(header_row)
                sample: list[list[Any]] = []
                total = 0
                for row in rows_iter:
                    total += 1
                    if len(sample) < SAMPLE_ROWS:
                        sample.append(list(row))
                sheets_info.append((name, headers, sample, total))

            # ── Overview ──────────────────────────────────────────────
            overview = [f"# Workbook: {path.name}", "", "## Sheets"]
            for name, headers, _, total in sheets_info:
                cols = len([h for h in headers if h is not None])
                overview.append(f"- `{name}` ({total:,} rows × {cols} cols)")
            yield _new_chunk("overview", _truncate("\n".join(overview)))

            # ── Per-sheet chunks ──────────────────────────────────────
            for name, headers, sample, total in sheets_info:
                if not headers:
                    continue
                clean_headers = [str(h) if h is not None else f"col{i+1}"
                                 for i, h in enumerate(headers)]
                # Schema
                types = []
                for col_idx in range(len(clean_headers)):
                    col_values = [row[col_idx] for row in sample if col_idx < len(row)]
                    types.append(_infer_type(col_values))
                schema = [f"# Sheet: {name}", "", f"**{total:,} rows × {len(clean_headers)} columns**", "", "## Columns"]
                for h, t in zip(clean_headers, types):
                    schema.append(f"- `{h}` *({t})*")
                yield _new_chunk(f"sheet: {name} (schema)", _truncate("\n".join(schema)))

                # Sample
                if sample:
                    formatted = [[_format_cell(c) for c in row] for row in sample]
                    body = [
                        f"# Sample rows from `{name}` (first {len(sample)})",
                        "",
                        "```",
                        _render_table([_format_cell(h) for h in clean_headers], formatted),
                        "```",
                    ]
                    yield _new_chunk(f"sheet: {name} (sample)", _truncate("\n".join(body)))
        finally:
            wb.close()

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
