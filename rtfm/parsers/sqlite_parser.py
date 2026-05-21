"""SQLite parser — index a .db file: schema + all rows, streaming.

A SQLite database is binary. We emit:

  - 1 overview chunk: list of tables / views / indexes with row counts
  - per table: schema chunk (CREATE TABLE + columns + foreign keys)
  - per table: data chunks covering **every row** (size-bounded,
    streamed via fetchmany so a huge table doesn't load fully)
  - per view/trigger: 1 chunk with its SQL
  - foreign keys are emitted as EdgeCandidate (table → table)

Previously only the first 5 rows per table were indexed; now the full
table is searchable. BLOB columns are binary and not text-searchable,
so they keep a `<blob NB>` placeholder; text/numeric values are kept
in full.

The DB is opened **read-only** via URI so we never mutate the file and
don't fight with another process holding a write lock.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Optional

from rtfm.core.models import Chunk, EdgeCandidate
from rtfm.parsers.base import BaseParser, ParserRegistry

MAX_CHUNK_CHARS = 4000
FETCH_BATCH = 500  # rows pulled per fetchmany() — bounds memory
SQLITE_MAGIC = b"SQLite format 3\x00"


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _looks_like_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _format_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, memoryview)):
        # Binary — not text-searchable, keep a size placeholder.
        return f"<blob {len(bytes(value))}B>"
    # Text/numeric kept in full (newlines flattened for one-line rows).
    return str(value).replace("\n", " ").replace("\r", " ")


def _format_row(cols: list[str], row: sqlite3.Row) -> str:
    return " | ".join(f"{c}={_format_cell(row[c])}" for c in cols)


def _is_internal(name: str) -> bool:
    """sqlite_master internal objects + FTS5 shadow tables."""
    if name.startswith("sqlite_"):
        return True
    for suffix in ("_data", "_idx", "_content", "_docsize", "_config", "_segdir", "_segments"):
        if name.endswith(suffix):
            return True
    return False


def _list_objects(conn: sqlite3.Connection, kind: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type=? ORDER BY name",
        (kind,),
    )
    return [r for r in cur.fetchall() if not _is_internal(r["name"])]


def _row_count(conn: sqlite3.Connection, table: str) -> Optional[int]:
    try:
        cur = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]
    except sqlite3.DatabaseError:
        return None


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return cur.fetchall()


def _foreign_keys(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    cur = conn.execute(f'PRAGMA foreign_key_list("{table}")')
    return cur.fetchall()


def _truncate(text: str, limit: int = MAX_CHUNK_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n… (truncated)"


@ParserRegistry.register
class SQLiteParser(BaseParser):
    """Parser for SQLite database files."""

    extensions = [".sqlite", ".sqlite3", ".db"]
    name = "sqlite"

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        if path.suffix.lower() not in cls.extensions:
            return False
        # `.db` is ambiguous — only accept if the magic bytes match.
        if path.suffix.lower() == ".db":
            return _looks_like_sqlite(path)
        return True

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}
        if path.suffix.lower() == ".db" and not _looks_like_sqlite(path):
            return

        try:
            conn = _connect_ro(path)
        except sqlite3.DatabaseError:
            return  # encrypted, locked, or corrupt — skip silently

        try:
            tables = _list_objects(conn, "table")
            views = _list_objects(conn, "view")
            triggers = _list_objects(conn, "trigger")
            indexes = [r for r in _list_objects(conn, "index") if r["sql"]]
        except sqlite3.DatabaseError:
            conn.close()
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

        # ── Overview chunk ──────────────────────────────────────────────
        overview_lines = [f"# Database: {path.name}", ""]
        if tables:
            overview_lines.append("## Tables")
            for t in tables:
                count = _row_count(conn, t["name"])
                count_str = f"{count:,} rows" if count is not None else "? rows"
                overview_lines.append(f"- {t['name']} ({count_str})")
        if views:
            overview_lines.append("\n## Views")
            for v in views:
                overview_lines.append(f"- {v['name']}")
        if indexes:
            overview_lines.append("\n## Indexes (user-defined)")
            for i in indexes:
                overview_lines.append(f"- {i['name']}")
        if triggers:
            overview_lines.append("\n## Triggers")
            for tr in triggers:
                overview_lines.append(f"- {tr['name']}")

        if len(overview_lines) > 2:
            yield _new_chunk("overview", "\n".join(overview_lines))

        # ── Per-table chunks ────────────────────────────────────────────
        for t in tables:
            tname = t["name"]
            sql = (t["sql"] or "").strip()
            cols = _columns(conn, tname)
            fks = _foreign_keys(conn, tname)
            count = _row_count(conn, tname)

            schema_parts = [f"# Table: {tname}", ""]
            if sql:
                schema_parts.append("```sql")
                schema_parts.append(sql)
                schema_parts.append("```")
                schema_parts.append("")
            if cols:
                schema_parts.append("## Columns")
                for c in cols:
                    pk = " PRIMARY KEY" if c["pk"] else ""
                    notnull = " NOT NULL" if c["notnull"] else ""
                    default = f" DEFAULT {c['dflt_value']}" if c["dflt_value"] is not None else ""
                    schema_parts.append(f"- `{c['name']}` {c['type']}{pk}{notnull}{default}")
            if fks:
                schema_parts.append("\n## Foreign Keys")
                for fk in fks:
                    schema_parts.append(
                        f"- `{fk['from']}` → `{fk['table']}.{fk['to']}`"
                    )
            if count is not None:
                schema_parts.append(f"\n**{count:,} rows**")

            yield _new_chunk(f"table: {tname} (schema)", _truncate("\n".join(schema_parts)))

            # Stream every row into size-bounded data chunks.
            try:
                cur = conn.execute(f'SELECT * FROM "{tname}"')
            except sqlite3.DatabaseError:
                continue
            col_names: list[str] = []
            header_line = ""
            buf: list[str] = []
            buf_chars = 0
            row_start = 1
            row_num = 0
            while True:
                try:
                    batch = cur.fetchmany(FETCH_BATCH)
                except sqlite3.DatabaseError:
                    break
                if not batch:
                    break
                if not col_names:
                    col_names = list(batch[0].keys())
                    header_line = f"table={tname} | columns: " + ", ".join(col_names)
                for row in batch:
                    row_num += 1
                    line = _format_row(col_names, row)
                    if buf and buf_chars + len(line) + 1 > MAX_CHUNK_CHARS:
                        body = header_line + "\n" + "\n".join(buf)
                        yield _new_chunk(f"table: {tname} rows {row_start}–{row_num-1}", body)
                        buf = []
                        buf_chars = 0
                        row_start = row_num
                    buf.append(line)
                    buf_chars += len(line) + 1
            if buf:
                body = header_line + "\n" + "\n".join(buf)
                yield _new_chunk(f"table: {tname} rows {row_start}–{row_num}", body)

        # ── Views / triggers ────────────────────────────────────────────
        for v in views:
            sql = (v["sql"] or "").strip()
            if not sql:
                continue
            content = f"# View: {v['name']}\n\n```sql\n{sql}\n```"
            yield _new_chunk(f"view: {v['name']}", _truncate(content))

        for tr in triggers:
            sql = (tr["sql"] or "").strip()
            if not sql:
                continue
            content = f"# Trigger: {tr['name']}\n\n```sql\n{sql}\n```"
            yield _new_chunk(f"trigger: {tr['name']}", _truncate(content))

        conn.close()

    def extract_edges(self, path: Path, metadata: Optional[dict] = None) -> list[EdgeCandidate]:
        if path.suffix.lower() == ".db" and not _looks_like_sqlite(path):
            return []
        try:
            conn = _connect_ro(path)
        except sqlite3.DatabaseError:
            return []

        edges: list[EdgeCandidate] = []
        source_file = str(path)
        try:
            tables = _list_objects(conn, "table")
            for t in tables:
                tname = t["name"]
                for fk in _foreign_keys(conn, tname):
                    edges.append(EdgeCandidate(
                        source_file=source_file,
                        target_ref=fk["table"],
                        relation_type="fk",
                        source_detail=f"{tname}.{fk['from']} → {fk['table']}.{fk['to']}",
                    ))
        except sqlite3.DatabaseError:
            pass
        finally:
            conn.close()
        return edges

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": str(path),
            "book_slug": self._path_to_slug(path),
            "title": path.name,
        }

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")
