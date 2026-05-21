"""CSV/TSV parser — index the full table, streaming.

Earlier this was a *sampler*: it only indexed the header + 8 rows, so
searching for a value on row 5000 found nothing. Now it indexes **every
row**, in size-bounded chunks, so the whole table is searchable.

Output:
  - overview chunk: column names with inferred types (+ row count)
  - data chunks   : every row, grouped into chunks of up to
                    MAX_CHUNK_CHARS, each prefixed with the header so a
                    matched value keeps its column context.

Streaming: rows are read lazily and chunks are yielded as they fill, so
memory stays bounded even on million-row files. Cell values are kept in
full (newlines flattened to spaces for table readability) — nothing is
truncated, that was the whole point of the fix.
"""

import csv
import hashlib
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry

# Rows scanned up-front purely to infer column types for the overview.
TYPE_SAMPLE_ROWS = 50
# Soft cap on a data chunk. A single row larger than this still becomes
# one (oversized) chunk rather than being split mid-row or truncated.
MAX_CHUNK_CHARS = 4000
SNIFF_BYTES = 8192


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _flatten_cell(value: str) -> str:
    """Flatten newlines so a cell stays on one table line — but keep the
    full value (no truncation)."""
    return (value or "").replace("\n", " ").replace("\r", " ")


def _infer_type(values: list[str]) -> str:
    """Cheap type inference over a sample of cell values."""
    seen_int = seen_float = seen_bool = 0
    for v in values:
        if v == "" or v is None:
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
    if seen_int + seen_float + seen_bool == 0:
        return "empty"
    if seen_bool and not seen_int and not seen_float:
        return "bool"
    if seen_float:
        return "float"
    if seen_int:
        return "int"
    return "text"


def _format_row(headers: list[str], row: list[str]) -> str:
    """One row rendered as `col=value | col=value`, full values. This
    keeps every cell tied to its column name so FTS/semantic search
    matches with context, and avoids the unreadable wide-column
    alignment problem on big tables."""
    parts = []
    for i, h in enumerate(headers):
        val = _flatten_cell(row[i]) if i < len(row) else ""
        parts.append(f"{h}={val}")
    # Trailing extra cells (ragged row) — keep them, don't drop data.
    for j in range(len(headers), len(row)):
        parts.append(f"col{j}={_flatten_cell(row[j])}")
    return " | ".join(parts)


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
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    reader = csv.reader(f, dialect=dialect)
    return f, reader


@ParserRegistry.register
class CSVParser(BaseParser):
    """Parser for CSV / TSV tabular files. Indexes the whole table."""

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

        book_title = metadata.get("title", path.name)
        book_slug = metadata.get("book_slug", self._path_to_slug(path))
        book_file = metadata.get("source_file", str(path))
        ext_meta = metadata.get("extended", {})

        idx = 0

        def _new_chunk(chapter_title: str, content: str,
                       row_start: int, row_end: int) -> Chunk:
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
                page_start=row_start,
                page_end=row_end,
                paragraph=1,
                content_chars=len(content),
                content_hash=_content_hash(content),
                metadata=ext_meta,
            )

        try:
            try:
                headers = next(reader)
            except StopIteration:
                return
            if not headers:
                return
            headers = [_flatten_cell(h) for h in headers]

            # Buffer the first rows to infer column types for the overview,
            # then replay them as the first data rows (no second file pass).
            type_buffer: list[list[str]] = []
            for row in reader:
                type_buffer.append(row)
                if len(type_buffer) >= TYPE_SAMPLE_ROWS:
                    break

            types: list[str] = []
            for col_idx in range(len(headers)):
                col_values = [r[col_idx] for r in type_buffer if col_idx < len(r)]
                types.append(_infer_type(col_values))

            overview = [f"# Tabular file: {path.name}", "",
                        f"- {len(headers)} columns", "", "## Columns"]
            for h, t in zip(headers, types):
                overview.append(f"- `{h}` *({t})*")
            yield _new_chunk("overview", "\n".join(overview), 0, 0)

            # Stream every row into size-bounded data chunks. The header
            # is repeated at the top of each chunk for column context.
            header_line = "columns: " + ", ".join(headers)
            buf_lines: list[str] = []
            buf_chars = 0
            chunk_row_start = 1
            row_num = 0

            def _flush(end_row: int):
                nonlocal buf_lines, buf_chars, chunk_row_start
                if not buf_lines:
                    return None
                body = header_line + "\n" + "\n".join(buf_lines)
                ch = _new_chunk(f"rows {chunk_row_start}–{end_row}",
                                body, chunk_row_start, end_row)
                buf_lines = []
                buf_chars = 0
                chunk_row_start = end_row + 1
                return ch

            from itertools import chain
            for row in chain(type_buffer, reader):
                row_num += 1
                line = _format_row(headers, row)
                # +1 for the newline join.
                if buf_lines and buf_chars + len(line) + 1 > MAX_CHUNK_CHARS:
                    ch = _flush(row_num - 1)
                    if ch is not None:
                        yield ch
                buf_lines.append(line)
                buf_chars += len(line) + 1
            ch = _flush(row_num)
            if ch is not None:
                yield ch
        finally:
            f.close()

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
