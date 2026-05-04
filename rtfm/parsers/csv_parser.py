"""CSV/TSV parser — index a tabular file by header + sample.

Tabular files can be huge (millions of rows). We don't dump everything;
we produce two compact chunks:

  - overview: file path, dialect, column names with inferred types,
              total row count (best-effort)
  - sample : the first N rows, formatted as an aligned table

If the file is misshapen (no header, inconsistent columns), we degrade
to plaintext-style chunking handled elsewhere — the parser yields nothing
and the registry never re-routes (plaintext catch-all picks it up).
"""

import csv
import hashlib
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

SAMPLE_ROWS = 8
MAX_CELL_CHARS = 80
MAX_CHUNK_CHARS = 4000
SNIFF_BYTES = 8192


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _format_cell(value: str) -> str:
    text = (value or "").replace("\n", " ").replace("\r", " ")
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + "…"
    return text


def _infer_type(values: list[str]) -> str:
    """Cheap type inference over a sample of cell values."""
    seen_int = seen_float = seen_bool = seen_empty = 0
    for v in values:
        if v == "" or v is None:
            seen_empty += 1
            continue
        s = v.strip()
        if s.lower() in {"true", "false"}:
            seen_bool += 1
            continue
        try:
            int(s)
            seen_int += 1
            continue
        except ValueError:
            pass
        try:
            float(s)
            seen_float += 1
            continue
        except ValueError:
            pass
        return "text"
    total = seen_int + seen_float + seen_bool
    if total == 0:
        return "empty"
    if seen_bool and not seen_int and not seen_float:
        return "bool"
    if seen_float:
        return "float"
    if seen_int:
        return "int"
    return "text"


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


def _open_with_dialect(path: Path):
    """Open a CSV/TSV file and sniff its dialect. Returns (file, reader)."""
    f = path.open("r", encoding="utf-8", errors="replace", newline="")
    sample = f.read(SNIFF_BYTES)
    f.seek(0)
    if not sample.strip():
        f.close()
        return None, None
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        # Fall back to extension hint
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    reader = csv.reader(f, dialect=dialect)
    return f, reader


@ParserRegistry.register
class CSVParser(BaseParser):
    """Parser for CSV / TSV tabular files."""

    extensions = [".csv", ".tsv"]
    name = "csv"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}

        f, reader = _open_with_dialect(path)
        if f is None or reader is None:
            return

        try:
            try:
                headers = next(reader)
            except StopIteration:
                return

            sample_rows: list[list[str]] = []
            total_rows = 0
            for row in reader:
                total_rows += 1
                if len(sample_rows) < SAMPLE_ROWS:
                    sample_rows.append([_format_cell(c) for c in row])
        finally:
            f.close()

        if not headers:
            return

        # Infer types from the sample.
        types: list[str] = []
        for col_idx in range(len(headers)):
            col_values = [row[col_idx] for row in sample_rows if col_idx < len(row)]
            types.append(_infer_type(col_values))

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

        overview = [f"# Tabular file: {path.name}", ""]
        overview.append(f"- {len(headers)} columns")
        overview.append(f"- {total_rows:,} data rows")
        overview.append("")
        overview.append("## Columns")
        for h, t in zip(headers, types):
            overview.append(f"- `{h}` *({t})*")
        yield _new_chunk("overview", _truncate("\n".join(overview)))

        if sample_rows:
            sample = [
                f"# Sample rows from `{path.name}` (first {len(sample_rows)})",
                "",
                "```",
                _render_table([_format_cell(h) for h in headers], sample_rows),
                "```",
            ]
            yield _new_chunk("sample", _truncate("\n".join(sample)))

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
