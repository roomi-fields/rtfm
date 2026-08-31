"""Main Library class - the public API for rtfm."""

import json
import sqlite3
from pathlib import Path
from typing import Optional, Iterator
from datetime import datetime

from rtfm.core.models import Chunk, SearchResult, SearchResults
from rtfm.parsers.base import BaseParser, ParserRegistry


# Default schema with extended metadata support
SCHEMA = """
-- Books/Documents table
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    filename TEXT,
    corpus TEXT DEFAULT 'default',
    page_count INTEGER,
    chunk_count INTEGER DEFAULT 0,
    total_chars INTEGER DEFAULT 0,
    indexed_at TEXT,
    metadata TEXT  -- JSON blob for extended metadata
);

-- Chapters/Sections table
CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    num INTEGER NOT NULL,
    title TEXT NOT NULL,
    page_start INTEGER,
    FOREIGN KEY (book_id) REFERENCES books(id),
    UNIQUE(book_id, num)
);

-- Chunks table
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT UNIQUE NOT NULL,
    book_id INTEGER NOT NULL,
    chapter_id INTEGER,
    chapter_num INTEGER,
    chapter_title TEXT,
    page_start INTEGER,
    page_end INTEGER,
    paragraph INTEGER,
    content TEXT NOT NULL,
    content_chars INTEGER,
    content_hash TEXT,
    line_start INTEGER,  -- First line in source file (1-indexed)
    line_end INTEGER,    -- Last line in source file (1-indexed)
    tags TEXT,  -- JSON array
    metadata TEXT,  -- JSON blob for extended metadata
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (chapter_id) REFERENCES chapters(id)
);

-- Article versions table (for legal text versioning)
CREATE TABLE IF NOT EXISTS article_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_ref TEXT NOT NULL,       -- stable identifier: "CGI-39-decies-A"
    chunk_id INTEGER NOT NULL,       -- link to chunk content
    version_num INTEGER NOT NULL,    -- version number (1, 2, 3...)
    date_debut DATE,                 -- effective start date
    date_fin DATE,                   -- effective end date (NULL = current)
    date_publication DATE,           -- publication date (JO)
    etat TEXT,                       -- VIGUEUR, ABROGE, MODIFIE, PERIME
    texte_modificateur TEXT,         -- "Loi 2023-1322 du 29/12/2023"
    previous_id INTEGER,             -- previous version ID
    FOREIGN KEY (chunk_id) REFERENCES chunks(id),
    FOREIGN KEY (previous_id) REFERENCES article_versions(id)
);

-- Indexes for version queries
CREATE INDEX IF NOT EXISTS idx_versions_article ON article_versions(article_ref);
CREATE INDEX IF NOT EXISTS idx_versions_dates ON article_versions(date_debut, date_fin);
CREATE INDEX IF NOT EXISTS idx_versions_chunk ON article_versions(chunk_id);

-- Chunk embeddings table (for semantic search)
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER NOT NULL UNIQUE,
    model TEXT NOT NULL,              -- model name for future upgrades
    embedding BLOB NOT NULL,          -- binary float32 array
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON chunk_embeddings(chunk_id);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    chunk_id,
    book_title,
    chapter_title,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content, chunk_id, book_title, chapter_title)
    SELECT NEW.id, NEW.content, NEW.chunk_id,
           (SELECT title FROM books WHERE id = NEW.book_id),
           NEW.chapter_title;
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content, chunk_id, book_title, chapter_title)
    VALUES('delete', OLD.id, OLD.content, OLD.chunk_id,
           (SELECT title FROM books WHERE id = OLD.book_id),
           OLD.chapter_title);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content, chunk_id, book_title, chapter_title)
    VALUES('delete', OLD.id, OLD.content, OLD.chunk_id,
           (SELECT title FROM books WHERE id = OLD.book_id),
           OLD.chapter_title);
    INSERT INTO chunks_fts(rowid, content, chunk_id, book_title, chapter_title)
    SELECT NEW.id, NEW.content, NEW.chunk_id,
           (SELECT title FROM books WHERE id = NEW.book_id),
           NEW.chapter_title;
END;

-- Indexed files tracking (for incremental sync)
-- Tracking of indexed files. The path is relative to the source directory
-- it came from, so it is unique *within a corpus*, never globally: the same
-- README.md legitimately exists in two indexed trees. A global UNIQUE made
-- them fight over one row — each scan claimed the file from the other corpus
-- and the next scan claimed it back, for ever (932 000 re-ingestions on one
-- project here, 82 000 of them for a single file).
CREATE TABLE IF NOT EXISTS indexed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    corpus TEXT DEFAULT 'default',
    book_slug TEXT,
    indexed_at TEXT,
    file_size INTEGER,
    -- Which source directory this path is relative to. Without it, scanning
    -- one directory of a multi-directory corpus sees every other directory's
    -- files as missing, and has to stat each one against every sibling to
    -- find out otherwise — thousands of network round-trips per scan, on
    -- every scan. NULL means "not yet established"; a scan claims its own.
    root_path TEXT,
    UNIQUE (filepath, corpus)
);
CREATE INDEX IF NOT EXISTS idx_indexed_filepath ON indexed_files(filepath);

-- Files whose ingestion genuinely failed (a corrupt PDF, an unreadable
-- archive). Without this a scan re-proposes them on every pass, forever:
-- a failed ingest writes no indexed_files row, so the next scan sees the
-- file as new again. On a corpus with thousands of broken PDFs that is a
-- permanent retry storm — 50 000 failed jobs in twenty minutes, measured,
-- burning the very lanes that fresh work needs. Recording the attempt with
-- the content's fingerprint stops the loop while keeping the retry
-- automatic: change the file and it no longer matches, so it is tried again.
CREATE TABLE IF NOT EXISTS ingest_failures (
    filepath TEXT NOT NULL,
    corpus TEXT NOT NULL DEFAULT 'default',
    file_hash TEXT,
    file_size INTEGER,
    error TEXT,
    attempts INTEGER DEFAULT 1,
    failed_at TEXT,
    PRIMARY KEY (filepath, corpus)
);

-- Sync roots tracking (absolute source directories, one row per root).
-- A corpus may gather several directories — `rtfm add` allows it and real
-- projects use it — so the key is the pair, not the corpus alone.
CREATE TABLE IF NOT EXISTS sync_roots (
    corpus TEXT NOT NULL,
    root_path TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (corpus, root_path)
);

-- Dependency graph edges (book-level: imports, links, includes, citations)
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_book_id INTEGER NOT NULL,
    target_book_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    source_detail TEXT,
    target_detail TEXT,
    FOREIGN KEY (source_book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (target_book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_book_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_book_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
    ON edges(source_book_id, target_book_id, relation_type, source_detail);

-- File version snapshots (content before re-ingest)
CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    version_num INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL,
    file_size INTEGER,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_file_versions_book ON file_versions(book_id, version_num);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_books_corpus ON books(corpus);
"""


class Library:
    """
    A document library with full-text search.

    Usage:
        from rtfm import Library

        lib = Library("path/to/library.db")
        results = lib.search("query", limit=10)
        for r in results:
            print(r.content, r.source, r.page)
    """

    def __init__(self, db_path: str | Path, create: bool = True):
        """
        Initialize or open a library.

        Args:
            db_path: Path to the SQLite database file
            create: If True, create the database if it doesn't exist
        """
        self.db_path = Path(db_path)

        if not self.db_path.exists() and not create:
            raise FileNotFoundError(f"Library not found: {db_path}")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        self._load_mappings()

    def _load_mappings(self):
        """Load project-local extensions from the ``.rtfm/`` directory:
        declarative JSON schema mappings (``mappings/``) and Python
        parser drop-ins (``parsers/``). Both are per-project, so a
        format-specific parser lives with the project instead of the
        shipped package."""
        from rtfm.parsers.mappings import load_mappings_from_dir
        rtfm_dir = self.db_path.parent
        load_mappings_from_dir(rtfm_dir / "mappings")
        from rtfm.parsers.local import load_local_parsers
        load_local_parsers(rtfm_dir / "parsers")

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with proper settings."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=60)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout = 60000")
            self._conn.execute("PRAGMA journal_mode = WAL")
            # Enforce ON DELETE CASCADE. SQLite has FKs OFF by default,
            # so deleting a chunk used to leave its chunk_embeddings row
            # behind (orphan). Must be set per-connection.
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_conn()

        # Check if this is an existing database
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='books'"
        )
        existing_db = cursor.fetchone() is not None

        if existing_db:
            # Migrate existing schema - add new columns if missing
            self._migrate_schema(conn)
        else:
            # Fresh database - create full schema
            conn.executescript(SCHEMA)

        # Key widenings run either way: a database can carry an old table
        # even when the schema script has just run (CREATE IF NOT EXISTS
        # leaves it alone), and a wrong key here is not a missing column —
        # it is a permanent index/de-index loop.
        self._migrate_keys(conn)
        conn.commit()

    def _migrate_keys(self, conn: sqlite3.Connection):
        """Widen keys that were once too narrow.

        Both of these treated a name as if it identified a file on its own:

        * ``sync_roots`` keyed on the corpus, so a corpus gathering several
          directories kept only the last one scanned. Nothing then knew where
          the other directories' files lived, and every scan of one directory
          saw the others' files as deleted.
        * ``indexed_files`` had ``filepath`` globally UNIQUE, so the same
          relative path in two corpora fought over one row — each scan
          claiming the file from the other corpus, for ever.

        Rebuilding is the only way to change a key in SQLite. Both are
        idempotent and keep every existing row.
        """
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='sync_roots'"
        ).fetchone()
        if row and "PRIMARY KEY (corpus, root_path)" not in (row[0] or ""):
            conn.executescript("""
                CREATE TABLE sync_roots_new (
                    corpus TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (corpus, root_path)
                );
                INSERT OR IGNORE INTO sync_roots_new (corpus, root_path, updated_at)
                    SELECT corpus, root_path, updated_at FROM sync_roots;
                DROP TABLE sync_roots;
                ALTER TABLE sync_roots_new RENAME TO sync_roots;
            """)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(indexed_files)")}
        if cols and "root_path" not in cols:
            conn.execute("ALTER TABLE indexed_files ADD COLUMN root_path TEXT")

        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='indexed_files'"
        ).fetchone()
        if row and "UNIQUE (filepath, corpus)" not in (row[0] or ""):
            conn.executescript("""
                CREATE TABLE indexed_files_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    corpus TEXT DEFAULT 'default',
                    book_slug TEXT,
                    indexed_at TEXT,
                    file_size INTEGER,
                    root_path TEXT,
                    UNIQUE (filepath, corpus)
                );
                INSERT OR IGNORE INTO indexed_files_new
                    (filepath, file_hash, corpus, book_slug, indexed_at, file_size)
                    SELECT filepath, file_hash, corpus, book_slug, indexed_at,
                           file_size FROM indexed_files;
                DROP TABLE indexed_files;
                ALTER TABLE indexed_files_new RENAME TO indexed_files;
                CREATE INDEX IF NOT EXISTS idx_indexed_filepath
                    ON indexed_files(filepath);
            """)

    def _migrate_schema(self, conn: sqlite3.Connection):
        """Add new columns to existing database."""
        # Check and add missing columns to books table
        cursor = conn.execute("PRAGMA table_info(books)")
        book_cols = {row[1] for row in cursor.fetchall()}

        if "corpus" not in book_cols:
            conn.execute("ALTER TABLE books ADD COLUMN corpus TEXT DEFAULT 'default'")
        if "metadata" not in book_cols:
            conn.execute("ALTER TABLE books ADD COLUMN metadata TEXT")

        # Check and add missing columns to chunks table
        cursor = conn.execute("PRAGMA table_info(chunks)")
        chunk_cols = {row[1] for row in cursor.fetchall()}

        if "metadata" not in chunk_cols:
            conn.execute("ALTER TABLE chunks ADD COLUMN metadata TEXT")
        if "line_start" not in chunk_cols:
            conn.execute("ALTER TABLE chunks ADD COLUMN line_start INTEGER")
        if "line_end" not in chunk_cols:
            conn.execute("ALTER TABLE chunks ADD COLUMN line_end INTEGER")

        # Create indexed_files table if missing
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='indexed_files'"
        )
        if not cursor.fetchone():
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS indexed_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    corpus TEXT DEFAULT 'default',
                    book_slug TEXT,
                    indexed_at TEXT,
                    file_size INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_indexed_filepath ON indexed_files(filepath);
            """)

        # Create ingest_failures table if missing (see the schema comment).
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='ingest_failures'"
        )
        if not cursor.fetchone():
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ingest_failures (
                    filepath TEXT NOT NULL,
                    corpus TEXT NOT NULL DEFAULT 'default',
                    file_hash TEXT,
                    file_size INTEGER,
                    error TEXT,
                    attempts INTEGER DEFAULT 1,
                    failed_at TEXT,
                    PRIMARY KEY (filepath, corpus)
                );
            """)

        # sync_roots: create if missing. Widening its key is handled by
        # :meth:`_migrate_keys`, which runs for every database.
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='sync_roots'"
        ).fetchone()
        if not row:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sync_roots (
                    corpus TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (corpus, root_path)
                );
            """)

        # Create edges table if missing
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='edges'"
        )
        if not cursor.fetchone():
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_book_id INTEGER NOT NULL,
                    target_book_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    source_detail TEXT,
                    target_detail TEXT,
                    FOREIGN KEY (source_book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_book_id) REFERENCES books(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_book_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_book_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
                    ON edges(source_book_id, target_book_id, relation_type, source_detail);
            """)

        # Create file_versions table if missing
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_versions'"
        )
        if not cursor.fetchone():
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    version_num INTEGER NOT NULL DEFAULT 1,
                    content_hash TEXT NOT NULL,
                    snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    file_size INTEGER,
                    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_file_versions_book
                    ON file_versions(book_id, version_num);
            """)

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # =========================================================================
    # Search
    # =========================================================================

    def search(
        self,
        query: str,
        limit: int = 10,
        corpus: Optional[str | list[str]] = None,
        tags: Optional[list[str]] = None,
        book: Optional[str] = None,
        raw_query: bool = False,
    ) -> SearchResults:
        """
        Search the library.

        Args:
            query: Search query (words are OR'd by default)
            limit: Maximum number of results
            corpus: Filter by corpus name(s)
            tags: Filter by tag(s) - chunks must have ALL specified tags
            book: Filter by book slug
            raw_query: If True, pass query directly to FTS5 (advanced syntax)

        Returns:
            SearchResults object with results and export methods
        """
        conn = self._get_conn()

        # Escape query for FTS5 unless raw_query is True
        if not raw_query:
            # Quote each word to prevent FTS5 operator interpretation
            words = query.split()
            query = " OR ".join(f'"{w}"' for w in words)

        # Build query with filters
        sql = """
            SELECT
                c.id, c.chunk_id, c.book_id, c.chapter_id, c.chapter_num,
                c.chapter_title, c.page_start, c.page_end, c.paragraph,
                c.content, c.content_chars, c.content_hash,
                c.line_start, c.line_end, c.tags, c.metadata,
                b.title as book_title, b.slug as book_slug, b.filename as book_file,
                b.corpus,
                bm25(chunks_fts) as score
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN books b ON c.book_id = b.id
            WHERE chunks_fts MATCH ?
        """
        params: list = [query]

        # Corpus filter
        if corpus:
            if isinstance(corpus, str):
                corpus = [corpus]
            placeholders = ",".join("?" * len(corpus))
            sql += f" AND b.corpus IN ({placeholders})"
            params.extend(corpus)

        # Book filter
        if book:
            sql += " AND b.slug = ?"
            params.append(book)

        sql += " ORDER BY score LIMIT ?"
        params.append(limit * 2)  # Fetch extra for tag filtering

        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

        # Build results with tag filtering
        results = []
        for rank, row in enumerate(rows, 1):
            if len(results) >= limit:
                break

            # Parse tags from JSON
            chunk_tags = json.loads(row["tags"]) if row["tags"] else None

            # Tag filter (if specified, chunk must have ALL tags)
            if tags:
                if not chunk_tags:
                    continue
                if not all(t in chunk_tags for t in tags):
                    continue

            # Parse extended metadata
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}

            chunk = Chunk(
                id=row["chunk_id"],
                content=row["content"],
                book_title=row["book_title"],
                book_slug=row["book_slug"],
                book_file=row["book_file"],
                chapter_title=row["chapter_title"],
                chapter_num=row["chapter_num"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                paragraph=row["paragraph"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                content_chars=row["content_chars"],
                content_hash=row["content_hash"],
                tags=chunk_tags,
                metadata=metadata,
            )

            results.append(SearchResult(
                chunk=chunk,
                score=abs(row["score"]),  # BM25 returns negative scores
                rank=len(results) + 1
            ))

        return SearchResults(
            results=results,
            query=query,
            total_found=len(rows)
        )

    # =========================================================================
    # Ingestion
    # =========================================================================

    def ingest(
        self,
        path: str | Path,
        corpus: str = "default",
        parser: Optional[BaseParser] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Ingest a document into the library.

        Args:
            path: Path to the document
            corpus: Corpus name for grouping documents
            parser: Optional parser to use (auto-detected if not specified)
            metadata: Optional metadata to associate with the document

        Returns:
            Stats dict with chunk count, etc.
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # Get parser
        if parser is None:
            parser = ParserRegistry.get_parser(path)
            if parser is None:
                # Text catch-all. A selected file with no registered parser
                # (unknown or absent extension — e.g. BP3 prefix-named data
                # files like ``-gr.dhati``, or extensionless files) is indexed
                # as plain text when it is textual, and skipped — not failed —
                # when it is binary. This lets a source opt into indexing a
                # whole tree without a bespoke parser per exotic format.
                from rtfm.parsers.plaintext import PlainTextParser
                try:
                    with open(path, "rb") as fh:
                        head = fh.read(8192)
                except OSError as exc:
                    raise ValueError(f"unreadable file: {path}") from exc
                if b"\x00" in head:
                    return {"chunks": 0, "chars": 0, "skipped": "binary"}
                parser = PlainTextParser()

        # Extract or use provided metadata
        doc_metadata = parser.extract_metadata(path)
        if metadata:
            doc_metadata.update(metadata)

        # Parse document
        chunks = list(parser.parse(path, doc_metadata))

        if not chunks:
            return {"chunks": 0, "chars": 0}

        # Index chunks
        return self._index_chunks(chunks, corpus, doc_metadata)

    def ingest_chunks(
        self,
        chunks: Iterator[Chunk],
        corpus: str = "default",
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Ingest pre-parsed chunks into the library.

        Useful when you have chunks from an external source or custom parser.
        """
        chunk_list = list(chunks)
        if not chunk_list:
            return {"chunks": 0, "chars": 0}

        return self._index_chunks(chunk_list, corpus, metadata or {})

    def append_ocr_chunks(
        self,
        book_slug: str,
        chunks: list[Chunk],
        page_lo: int,
        page_hi: int,
    ) -> dict:
        """Append OCR'd chunks for a page range to an existing book,
        idempotently. Used by the split P3 OCR handler: each tranche
        (pages lo..hi) replaces just its own chunks, so re-running a
        tranche (retry) doesn't duplicate, and other tranches are left
        intact. The book row must already exist (P1 created it).

        Chunks carry ``chapter_num == page_num`` (set by the PDF parser),
        which is how we scope the delete to this tranche.

        Returns ``{"chunks": n_added}``.
        """
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM books WHERE slug = ?",
                           (book_slug,)).fetchone()
        if not row:
            return {"chunks": 0, "error": "book not found"}
        book_id = row["id"]

        # Idempotency: drop existing chunks in this page range first.
        # FK=ON cascades to chunk_embeddings.
        conn.execute(
            "DELETE FROM chunks WHERE book_id = ? "
            "AND chapter_num BETWEEN ? AND ?",
            (book_id, page_lo, page_hi),
        )

        # Other tranches' chunks remain, so seed the de-dup set with the
        # book's surviving ids to keep this tranche's ids unique against them.
        seen_ids: set[str] = {
            r["chunk_id"] for r in conn.execute(
                "SELECT chunk_id FROM chunks WHERE book_id = ?", (book_id,))
        }
        added = 0
        for chunk in chunks:
            tags_json = json.dumps(chunk.tags) if chunk.tags else None
            metadata_json = json.dumps(chunk.metadata) if chunk.metadata else None
            conn.execute(
                """INSERT INTO chunks
                   (chunk_id, book_id, chapter_id, chapter_num, chapter_title,
                    page_start, page_end, paragraph, content, content_chars,
                    content_hash, line_start, line_end, tags, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self._unique_chunk_id(book_slug, chunk.id, seen_ids),
                 book_id, None, chunk.chapter_num, chunk.chapter_title,
                 chunk.page_start, chunk.page_end, chunk.paragraph,
                 chunk.content, chunk.content_chars, chunk.content_hash,
                 chunk.line_start, chunk.line_end, tags_json, metadata_json),
            )
            added += 1

        # Recompute book totals from the actual chunks.
        agg = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(content_chars),0) AS c "
            "FROM chunks WHERE book_id = ?", (book_id,)
        ).fetchone()
        conn.execute(
            "UPDATE books SET chunk_count = ?, total_chars = ?, indexed_at = ? "
            "WHERE id = ?",
            (agg["n"], agg["c"], datetime.now().isoformat(), book_id),
        )
        conn.commit()
        return {"chunks": added}

    @staticmethod
    def _unique_chunk_id(book_slug: str, raw_id: str, seen: set[str]) -> str:
        """Return a globally-unique ``chunk_id`` for storage.

        Parsers derive a chunk's id from its content alone (``md5(text)[:12]``),
        but the ``chunks.chunk_id`` column is UNIQUE across the whole DB — so
        two chunks with identical text (a PDF's blank/boilerplate pages, or the
        same passage in two books) collided and aborted the entire ingest with
        ``UNIQUE constraint failed: chunks.chunk_id``. Scoping the id to the
        book (``slug:rawid``) removes cross-book collisions; a ``#n`` suffix
        removes duplicates within one book. ``seen`` accumulates the ids
        already used for this book (pre-seed it with the book's existing rows
        when appending rather than replacing)."""
        cid = f"{book_slug}:{raw_id}"
        if cid in seen:
            base, n = cid, 1
            while cid in seen:
                cid = f"{base}#{n}"
                n += 1
        seen.add(cid)
        return cid

    def _index_chunks(
        self,
        chunks: list[Chunk],
        corpus: str,
        metadata: dict
    ) -> dict:
        """Index a list of chunks into the database."""
        conn = self._get_conn()

        # A passage with no text is findable and unreadable: search matches
        # the document, the reader is handed nothing. A parser that produces
        # one has produced noise, not content — the HTML parser did, on
        # markup with no text in it. Never store them.
        chunks = [c for c in chunks if (c.content or "").strip()]
        if not chunks:
            return {"chunks": 0, "chars": 0}

        first_chunk = chunks[0]
        book_slug = first_chunk.book_slug
        book_title = first_chunk.book_title
        book_file = first_chunk.book_file or ""

        # Get or create book
        cursor = conn.execute(
            "SELECT id FROM books WHERE slug = ?", (book_slug,)
        )
        row = cursor.fetchone()

        if row:
            book_id = row["id"]
            # Clear existing chunks (re-import)
            conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            # Update book metadata
            conn.execute(
                """UPDATE books SET title = ?, filename = ?, corpus = ?,
                   metadata = ?, indexed_at = ? WHERE id = ?""",
                (book_title, book_file, corpus,
                 json.dumps(metadata, default=str), datetime.now().isoformat(), book_id)
            )
        else:
            cursor = conn.execute(
                """INSERT INTO books (slug, title, filename, corpus, metadata, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (book_slug, book_title, book_file, corpus,
                 json.dumps(metadata, default=str), datetime.now().isoformat())
            )
            book_id = cursor.lastrowid

        # Track chapters
        chapters = {}  # chapter_num -> chapter_id
        # page_count comes from the parser (e.g. PDFParser writes the real
        # pypdfium2 page count into metadata). Kept in stats so callers
        # like the worker's ingest handler can compute a deterministic
        # chars-per-page scan signal.
        page_count = metadata.get("page_count")
        stats = {"chunks": 0, "chars": 0, "pages": page_count}

        # Old chunks for this book were just deleted, so ids only need to be
        # unique within this batch.
        seen_ids: set[str] = set()
        for chunk in chunks:
            # Get or create chapter
            ch_num = chunk.chapter_num or chunk.part_num or 0
            ch_title = chunk.chapter_title or chunk.part_title or "Unknown"

            if ch_num not in chapters:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO chapters (book_id, num, title, page_start)
                       VALUES (?, ?, ?, ?)""",
                    (book_id, ch_num, ch_title, chunk.page_start)
                )
                if cursor.lastrowid:
                    chapters[ch_num] = cursor.lastrowid
                else:
                    cursor = conn.execute(
                        "SELECT id FROM chapters WHERE book_id = ? AND num = ?",
                        (book_id, ch_num)
                    )
                    row = cursor.fetchone()
                    chapters[ch_num] = row["id"] if row else None

            chapter_id = chapters.get(ch_num)

            # Serialize tags and metadata
            tags_json = json.dumps(chunk.tags) if chunk.tags else None
            metadata_json = json.dumps(chunk.metadata) if chunk.metadata else None

            # Insert chunk (id scoped to the book + de-duplicated).
            conn.execute(
                """INSERT INTO chunks
                   (chunk_id, book_id, chapter_id, chapter_num, chapter_title,
                    page_start, page_end, paragraph, content, content_chars,
                    content_hash, line_start, line_end, tags, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self._unique_chunk_id(book_slug, chunk.id, seen_ids),
                 book_id, chapter_id, chunk.chapter_num,
                 chunk.chapter_title, chunk.page_start, chunk.page_end,
                 chunk.paragraph, chunk.content, chunk.content_chars,
                 chunk.content_hash, chunk.line_start, chunk.line_end,
                 tags_json, metadata_json)
            )

            stats["chunks"] += 1
            stats["chars"] += chunk.content_chars

        # Update book stats (incl. page_count when the parser provided it).
        conn.execute(
            """UPDATE books SET chunk_count = ?, total_chars = ?,
               page_count = COALESCE(?, page_count), indexed_at = ?
               WHERE id = ?""",
            (stats["chunks"], stats["chars"], page_count,
             datetime.now().isoformat(), book_id)
        )

        conn.commit()
        return stats

    # =========================================================================
    # Corpus management
    # =========================================================================

    def list_books(self, corpus: Optional[str] = None) -> list[dict]:
        """List all books in the library."""
        conn = self._get_conn()

        if corpus:
            cursor = conn.execute(
                """SELECT slug, title, corpus, chunk_count, total_chars, indexed_at
                   FROM books WHERE corpus = ? ORDER BY title""",
                (corpus,)
            )
        else:
            cursor = conn.execute(
                """SELECT slug, title, corpus, chunk_count, total_chars, indexed_at
                   FROM books ORDER BY corpus, title"""
            )

        return [dict(row) for row in cursor.fetchall()]

    def list_corpora(self) -> list[dict]:
        """List all corpora with stats."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT corpus, COUNT(*) as book_count,
                      SUM(chunk_count) as total_chunks,
                      SUM(total_chars) as total_chars
               FROM books GROUP BY corpus ORDER BY corpus"""
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get library statistics."""
        conn = self._get_conn()

        stats = {}

        cursor = conn.execute("SELECT COUNT(*) FROM books")
        stats["books"] = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM chunks")
        stats["chunks"] = cursor.fetchone()[0]

        cursor = conn.execute("SELECT SUM(content_chars) FROM chunks")
        stats["total_chars"] = cursor.fetchone()[0] or 0

        cursor = conn.execute("SELECT COUNT(*) FROM chunks WHERE tags IS NOT NULL")
        stats["tagged_chunks"] = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(DISTINCT corpus) FROM books")
        stats["corpora"] = cursor.fetchone()[0]

        return stats

    def delete_book(self, slug: str) -> bool:
        """Delete a book and all its chunks."""
        conn = self._get_conn()

        cursor = conn.execute("SELECT id FROM books WHERE slug = ?", (slug,))
        row = cursor.fetchone()

        if not row:
            return False

        book_id = row["id"]
        conn.execute("DELETE FROM edges WHERE source_book_id = ? OR target_book_id = ?", (book_id, book_id))
        conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()

        return True

    # =========================================================================
    # Dependency graph
    # =========================================================================

    def get_neighbors(
        self,
        book_slug: str,
        direction: str = "both",
        relation_type: Optional[str] = None,
    ) -> list[dict]:
        """Get graph neighbors of a book.

        Args:
            book_slug: Slug of the book to query.
            direction: "outgoing", "incoming", or "both".
            relation_type: Filter by relation type (optional).

        Returns:
            List of dicts with slug, filename, relation_type, direction, source_detail.
        """
        conn = self._get_conn()

        # Resolve book_id
        row = conn.execute("SELECT id FROM books WHERE slug = ?", (book_slug,)).fetchone()
        if not row:
            return []
        book_id = row["id"]

        results = []

        if direction in ("outgoing", "both"):
            sql = """SELECT b.slug, b.filename, e.relation_type, e.source_detail
                     FROM edges e JOIN books b ON e.target_book_id = b.id
                     WHERE e.source_book_id = ?"""
            params: list = [book_id]
            if relation_type:
                sql += " AND e.relation_type = ?"
                params.append(relation_type)
            for r in conn.execute(sql, params).fetchall():
                results.append({
                    "slug": r["slug"], "filename": r["filename"],
                    "relation_type": r["relation_type"], "direction": "outgoing",
                    "source_detail": r["source_detail"],
                })

        if direction in ("incoming", "both"):
            sql = """SELECT b.slug, b.filename, e.relation_type, e.source_detail
                     FROM edges e JOIN books b ON e.source_book_id = b.id
                     WHERE e.target_book_id = ?"""
            params = [book_id]
            if relation_type:
                sql += " AND e.relation_type = ?"
                params.append(relation_type)
            for r in conn.execute(sql, params).fetchall():
                results.append({
                    "slug": r["slug"], "filename": r["filename"],
                    "relation_type": r["relation_type"], "direction": "incoming",
                    "source_detail": r["source_detail"],
                })

        return results

    def get_in_degree(self, book_id: Optional[int] = None) -> dict[int, int]:
        """Get in-degree counts for books in the graph.

        Args:
            book_id: If given, return only for this book. Otherwise, all books.

        Returns:
            Dict mapping book_id to in-degree count.
        """
        conn = self._get_conn()
        if book_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM edges WHERE target_book_id = ?",
                (book_id,),
            ).fetchone()
            return {book_id: row["cnt"]}

        rows = conn.execute(
            "SELECT target_book_id, COUNT(*) as cnt FROM edges GROUP BY target_book_id"
        ).fetchall()
        return {r["target_book_id"]: r["cnt"] for r in rows}

    def get_graph_stats(self) -> dict:
        """Get statistics about the dependency graph."""
        conn = self._get_conn()

        total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        relation_rows = conn.execute(
            "SELECT relation_type, COUNT(*) as cnt FROM edges GROUP BY relation_type"
        ).fetchall()
        relation_types = {r["relation_type"]: r["cnt"] for r in relation_rows}

        books_with_edges = conn.execute(
            """SELECT COUNT(DISTINCT id) FROM (
                SELECT source_book_id as id FROM edges
                UNION
                SELECT target_book_id as id FROM edges
            )"""
        ).fetchone()[0]

        return {
            "total_edges": total_edges,
            "relation_types": relation_types,
            "books_with_edges": books_with_edges,
        }

    # =========================================================================
    # Reranking
    # =========================================================================

    def rerank(
        self,
        results: "SearchResults",
        freshness_weight: float = 0.0,
        centrality_weight: float = 0.0,
    ) -> "SearchResults":
        """Rerank search results with freshness and centrality boosts.

        final_score = base_score * (1 + freshness_boost + centrality_boost)

        Args:
            results: Original SearchResults.
            freshness_weight: Weight for freshness boost (0 = disabled).
            centrality_weight: Weight for centrality boost (0 = disabled).

        Returns:
            New SearchResults with adjusted scores and ranks.
        """
        if not results or (freshness_weight == 0.0 and centrality_weight == 0.0):
            return results

        conn = self._get_conn()
        now = datetime.now()

        # Batch-fetch book metadata: slug → (book_id, indexed_at)
        book_rows = conn.execute(
            "SELECT id, slug, indexed_at FROM books"
        ).fetchall()
        slug_to_info: dict[str, dict] = {}
        for r in book_rows:
            slug_to_info[r["slug"]] = {
                "book_id": r["id"],
                "indexed_at": r["indexed_at"],
            }

        # Batch-fetch in-degree for centrality
        in_degrees: dict[int, int] = {}
        max_in_degree = 0
        if centrality_weight > 0:
            in_degrees = self.get_in_degree()
            max_in_degree = max(in_degrees.values()) if in_degrees else 0

        # Recompute scores
        scored = []
        for r in results:
            base_score = r.score
            freshness_boost = 0.0
            centrality_boost = 0.0

            info = slug_to_info.get(r.chunk.book_slug, {})

            if freshness_weight > 0 and info.get("indexed_at"):
                try:
                    indexed_dt = datetime.fromisoformat(info["indexed_at"])
                    days_since = (now - indexed_dt).total_seconds() / 86400
                    freshness_boost = freshness_weight * (0.99 ** days_since)
                except (ValueError, TypeError):
                    pass

            if centrality_weight > 0 and max_in_degree > 0:
                book_id = info.get("book_id")
                if book_id:
                    in_deg = in_degrees.get(book_id, 0)
                    centrality_boost = centrality_weight * min(in_deg / max_in_degree, 1.0)

            final_score = base_score * (1 + freshness_boost + centrality_boost)
            scored.append((final_score, r))

        # Sort by final score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        from rtfm.core.models import SearchResult
        reranked = []
        for rank, (score, r) in enumerate(scored, 1):
            reranked.append(SearchResult(chunk=r.chunk, score=score, rank=rank))

        return SearchResults(
            results=reranked,
            query=results.query,
            total_found=results.total_found,
        )

    # =========================================================================
    # Tag management
    # =========================================================================

    def list_tags(self, corpus: Optional[str] = None) -> list[dict]:
        """
        List all unique tags with their counts.

        Args:
            corpus: Optional corpus filter

        Returns:
            List of dicts with 'tag' and 'count' keys, sorted by count desc
        """
        conn = self._get_conn()

        # SQLite doesn't have native JSON array functions, so we fetch and count in Python
        if corpus:
            cursor = conn.execute(
                """SELECT c.tags FROM chunks c
                   JOIN books b ON c.book_id = b.id
                   WHERE c.tags IS NOT NULL AND b.corpus = ?""",
                (corpus,)
            )
        else:
            cursor = conn.execute(
                "SELECT tags FROM chunks WHERE tags IS NOT NULL"
            )

        tag_counts: dict[str, int] = {}
        for row in cursor:
            tags = json.loads(row["tags"])
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return sorted(
            [{"tag": t, "count": c} for t, c in tag_counts.items()],
            key=lambda x: (-x["count"], x["tag"])
        )

    def add_tags(self, chunk_id: str, tags: list[str]) -> bool:
        """
        Add tags to a chunk.

        Args:
            chunk_id: The chunk_id to modify
            tags: List of tags to add

        Returns:
            True if successful, False if chunk not found
        """
        conn = self._get_conn()

        cursor = conn.execute(
            "SELECT id, tags FROM chunks WHERE chunk_id = ?",
            (chunk_id,)
        )
        row = cursor.fetchone()

        if not row:
            return False

        existing = json.loads(row["tags"]) if row["tags"] else []
        new_tags = list(set(existing + tags))

        conn.execute(
            "UPDATE chunks SET tags = ? WHERE id = ?",
            (json.dumps(new_tags), row["id"])
        )
        conn.commit()
        return True

    def remove_tags(self, chunk_id: str, tags: list[str]) -> bool:
        """
        Remove tags from a chunk.

        Args:
            chunk_id: The chunk_id to modify
            tags: List of tags to remove

        Returns:
            True if successful, False if chunk not found
        """
        conn = self._get_conn()

        cursor = conn.execute(
            "SELECT id, tags FROM chunks WHERE chunk_id = ?",
            (chunk_id,)
        )
        row = cursor.fetchone()

        if not row:
            return False

        existing = json.loads(row["tags"]) if row["tags"] else []
        new_tags = [t for t in existing if t not in tags]

        conn.execute(
            "UPDATE chunks SET tags = ? WHERE id = ?",
            (json.dumps(new_tags) if new_tags else None, row["id"])
        )
        conn.commit()
        return True

    def tag_chunks(
        self,
        tags: list[str],
        corpus: Optional[str] = None,
        book: Optional[str] = None,
        chunk_ids: Optional[list[str]] = None,
    ) -> int:
        """
        Add tags to multiple chunks at once.

        Args:
            tags: Tags to add
            corpus: Filter by corpus
            book: Filter by book slug
            chunk_ids: Specific chunk IDs to tag

        Returns:
            Number of chunks modified
        """
        conn = self._get_conn()

        # Build query to find chunks
        sql = """
            SELECT c.id, c.tags FROM chunks c
            JOIN books b ON c.book_id = b.id
            WHERE 1=1
        """
        params: list = []

        if corpus:
            sql += " AND b.corpus = ?"
            params.append(corpus)
        if book:
            sql += " AND b.slug = ?"
            params.append(book)
        if chunk_ids:
            placeholders = ",".join("?" * len(chunk_ids))
            sql += f" AND c.chunk_id IN ({placeholders})"
            params.extend(chunk_ids)

        cursor = conn.execute(sql, params)
        count = 0

        for row in cursor:
            existing = json.loads(row["tags"]) if row["tags"] else []
            new_tags = list(set(existing + tags))
            conn.execute(
                "UPDATE chunks SET tags = ? WHERE id = ?",
                (json.dumps(new_tags), row["id"])
            )
            count += 1

        conn.commit()
        return count

    def get_chunks_by_tag(
        self,
        tag: str,
        corpus: Optional[str] = None,
        limit: int = 100,
    ) -> list[Chunk]:
        """
        Get all chunks with a specific tag.

        Args:
            tag: Tag to search for
            corpus: Optional corpus filter
            limit: Maximum chunks to return

        Returns:
            List of Chunk objects
        """
        conn = self._get_conn()

        sql = """
            SELECT c.*, b.title as book_title, b.slug as book_slug,
                   b.filename as book_file, b.corpus
            FROM chunks c
            JOIN books b ON c.book_id = b.id
            WHERE c.tags IS NOT NULL
        """
        params: list = []

        if corpus:
            sql += " AND b.corpus = ?"
            params.append(corpus)

        sql += " LIMIT ?"
        params.append(limit * 10)  # Fetch extra since we filter in Python

        cursor = conn.execute(sql, params)
        chunks = []

        for row in cursor:
            if len(chunks) >= limit:
                break

            chunk_tags = json.loads(row["tags"]) if row["tags"] else []
            if tag not in chunk_tags:
                continue

            metadata = json.loads(row["metadata"]) if row["metadata"] else {}

            chunks.append(Chunk(
                id=row["chunk_id"],
                content=row["content"],
                book_title=row["book_title"],
                book_slug=row["book_slug"],
                book_file=row["book_file"],
                chapter_title=row["chapter_title"],
                chapter_num=row["chapter_num"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                paragraph=row["paragraph"],
                content_chars=row["content_chars"],
                content_hash=row["content_hash"],
                tags=chunk_tags,
                metadata=metadata,
            ))

        return chunks

    # =========================================================================
    # Article versioning
    # =========================================================================

    def add_article_version(
        self,
        article_ref: str,
        chunk_id: str,
        version_num: int,
        date_debut: Optional[str] = None,
        date_fin: Optional[str] = None,
        date_publication: Optional[str] = None,
        etat: Optional[str] = None,
        texte_modificateur: Optional[str] = None,
        previous_id: Optional[int] = None,
    ) -> int:
        """
        Add a version record for an article.

        Args:
            article_ref: Stable article identifier (e.g., "CGI-39-decies-A")
            chunk_id: The chunk_id containing the article text
            version_num: Version number (1, 2, 3...)
            date_debut: Effective start date (YYYY-MM-DD)
            date_fin: Effective end date (YYYY-MM-DD), None if current
            date_publication: Publication date
            etat: Status (VIGUEUR, ABROGE, MODIFIE, PERIME)
            texte_modificateur: Modifying law reference
            previous_id: ID of previous version record

        Returns:
            ID of the created version record
        """
        conn = self._get_conn()

        # Get the internal chunk ID
        cursor = conn.execute(
            "SELECT id FROM chunks WHERE chunk_id = ?",
            (chunk_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Chunk not found: {chunk_id}")

        internal_chunk_id = row["id"]

        cursor = conn.execute(
            """INSERT INTO article_versions
               (article_ref, chunk_id, version_num, date_debut, date_fin,
                date_publication, etat, texte_modificateur, previous_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (article_ref, internal_chunk_id, version_num, date_debut, date_fin,
             date_publication, etat, texte_modificateur, previous_id)
        )
        conn.commit()
        return cursor.lastrowid

    def get_article_history(
        self,
        article_ref: str,
    ) -> list[dict]:
        """
        Get version history for an article.

        Args:
            article_ref: Article identifier (e.g., "CGI-39-decies-A")

        Returns:
            List of version records, oldest first
        """
        conn = self._get_conn()

        cursor = conn.execute(
            """SELECT av.*, c.chunk_id, c.content, c.chapter_title
               FROM article_versions av
               JOIN chunks c ON av.chunk_id = c.id
               WHERE av.article_ref = ?
               ORDER BY av.version_num ASC""",
            (article_ref,)
        )

        return [
            {
                "id": row["id"],
                "article_ref": row["article_ref"],
                "chunk_id": row["chunk_id"],
                "version_num": row["version_num"],
                "date_debut": row["date_debut"],
                "date_fin": row["date_fin"],
                "date_publication": row["date_publication"],
                "etat": row["etat"],
                "texte_modificateur": row["texte_modificateur"],
                "previous_id": row["previous_id"],
                "content": row["content"],
                "title": row["chapter_title"],
            }
            for row in cursor.fetchall()
        ]

    def get_article_at_date(
        self,
        article_ref: str,
        date: str,
    ) -> Optional[dict]:
        """
        Get the version of an article that was in effect at a given date.

        Args:
            article_ref: Article identifier
            date: Date to query (YYYY-MM-DD)

        Returns:
            Version record or None if no version was in effect
        """
        conn = self._get_conn()

        cursor = conn.execute(
            """SELECT av.*, c.chunk_id, c.content, c.chapter_title
               FROM article_versions av
               JOIN chunks c ON av.chunk_id = c.id
               WHERE av.article_ref = ?
                 AND av.date_debut <= ?
                 AND (av.date_fin IS NULL OR av.date_fin >= ?)
               ORDER BY av.version_num DESC
               LIMIT 1""",
            (article_ref, date, date)
        )

        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row["id"],
            "article_ref": row["article_ref"],
            "chunk_id": row["chunk_id"],
            "version_num": row["version_num"],
            "date_debut": row["date_debut"],
            "date_fin": row["date_fin"],
            "date_publication": row["date_publication"],
            "etat": row["etat"],
            "texte_modificateur": row["texte_modificateur"],
            "content": row["content"],
            "title": row["chapter_title"],
        }

    def search_at_date(
        self,
        query: str,
        date: str,
        limit: int = 10,
        corpus: Optional[str] = None,
    ) -> SearchResults:
        """
        Search for articles that were in effect at a specific date.

        Args:
            query: Search query
            date: Date to query (YYYY-MM-DD)
            limit: Maximum results
            corpus: Optional corpus filter

        Returns:
            SearchResults with only versions valid at the given date
        """
        # First do a regular search
        results = self.search(query, limit=limit * 3, corpus=corpus)

        # Filter to only include chunks that have a valid version at the date
        conn = self._get_conn()
        filtered_results = []

        for r in results:
            # Check if this chunk has a version valid at the date
            cursor = conn.execute(
                """SELECT 1 FROM article_versions av
                   JOIN chunks c ON av.chunk_id = c.id
                   WHERE c.chunk_id = ?
                     AND av.date_debut <= ?
                     AND (av.date_fin IS NULL OR av.date_fin >= ?)""",
                (r.chunk.id, date, date)
            )
            if cursor.fetchone():
                filtered_results.append(r)
                if len(filtered_results) >= limit:
                    break

        # Re-rank
        for i, r in enumerate(filtered_results):
            r.rank = i + 1

        return SearchResults(
            results=filtered_results,
            query=f"{query} (at {date})",
            total_found=len(filtered_results),
        )

    def list_versioned_articles(
        self,
        corpus: Optional[str] = None,
    ) -> list[dict]:
        """
        List all articles that have version history.

        Returns:
            List of articles with version counts
        """
        conn = self._get_conn()

        if corpus:
            cursor = conn.execute(
                """SELECT av.article_ref,
                          COUNT(*) as version_count,
                          MIN(av.date_debut) as first_version,
                          MAX(av.date_debut) as latest_version
                   FROM article_versions av
                   JOIN chunks c ON av.chunk_id = c.id
                   JOIN books b ON c.book_id = b.id
                   WHERE b.corpus = ?
                   GROUP BY av.article_ref
                   ORDER BY av.article_ref""",
                (corpus,)
            )
        else:
            cursor = conn.execute(
                """SELECT article_ref,
                          COUNT(*) as version_count,
                          MIN(date_debut) as first_version,
                          MAX(date_debut) as latest_version
                   FROM article_versions
                   GROUP BY article_ref
                   ORDER BY article_ref"""
            )

        return [dict(row) for row in cursor.fetchall()]

    def compare_versions(
        self,
        article_ref: str,
        v1: int,
        v2: int,
    ) -> dict:
        """
        Compare two versions of an article.

        Args:
            article_ref: Article identifier
            v1: First version number
            v2: Second version number

        Returns:
            Dict with both versions and diff info
        """
        conn = self._get_conn()

        versions = {}
        for v in [v1, v2]:
            cursor = conn.execute(
                """SELECT av.*, c.content, c.chapter_title
                   FROM article_versions av
                   JOIN chunks c ON av.chunk_id = c.id
                   WHERE av.article_ref = ? AND av.version_num = ?""",
                (article_ref, v)
            )
            row = cursor.fetchone()
            if row:
                versions[v] = {
                    "version_num": row["version_num"],
                    "date_debut": row["date_debut"],
                    "date_fin": row["date_fin"],
                    "etat": row["etat"],
                    "texte_modificateur": row["texte_modificateur"],
                    "content": row["content"],
                    "title": row["chapter_title"],
                }

        if len(versions) != 2:
            return {"error": "One or both versions not found", "versions": versions}

        # Simple diff: content changed?
        content_changed = versions[v1]["content"] != versions[v2]["content"]

        return {
            "article_ref": article_ref,
            "v1": versions[v1],
            "v2": versions[v2],
            "content_changed": content_changed,
            "chars_v1": len(versions[v1]["content"]),
            "chars_v2": len(versions[v2]["content"]),
            "chars_diff": len(versions[v2]["content"]) - len(versions[v1]["content"]),
        }

    # =========================================================================
    # File versioning (snapshots before re-ingest)
    # =========================================================================

    def save_file_version(
        self,
        book_slug: str,
        content_hash: str,
        prune_limit: Optional[int] = 50,
    ) -> Optional[int]:
        """Save a snapshot of the current content before re-ingest.

        Reads content from chunks, stores as a single snapshot.

        Args:
            book_slug: book to version
            content_hash: hash of the outgoing content
            prune_limit: keep only the last N versions (default 50).
                Pass None to keep unlimited history (used for memory corpora).

        Returns:
            Version ID, or None if book not found or no content.
        """
        conn = self._get_conn()

        row = conn.execute("SELECT id FROM books WHERE slug = ?", (book_slug,)).fetchone()
        if not row:
            return None
        book_id = row["id"]

        # Concatenate chunk content in order
        chunks = conn.execute(
            """SELECT content FROM chunks WHERE book_id = ?
               ORDER BY page_start, paragraph""",
            (book_id,),
        ).fetchall()

        if not chunks:
            return None

        snapshot = "\n\n".join(r["content"] for r in chunks)
        file_size = len(snapshot.encode("utf-8"))

        # Get next version number
        max_row = conn.execute(
            "SELECT MAX(version_num) as mx FROM file_versions WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        next_version = (max_row["mx"] or 0) + 1

        cursor = conn.execute(
            """INSERT INTO file_versions
               (book_id, version_num, content_hash, snapshot, created_at, file_size)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (book_id, next_version, content_hash, snapshot,
             datetime.now().isoformat(), file_size),
        )
        version_id = cursor.lastrowid

        # Prune unless caller requests unlimited history.
        if prune_limit is not None:
            conn.execute(
                """DELETE FROM file_versions WHERE book_id = ? AND id NOT IN (
                    SELECT id FROM file_versions WHERE book_id = ?
                    ORDER BY version_num DESC LIMIT ?
                )""",
                (book_id, book_id, prune_limit),
            )

        conn.commit()
        return version_id

    def get_file_history(self, book_slug: str) -> list[dict]:
        """Get version history for a file (without content).

        Returns:
            List of dicts with version_num, content_hash, created_at, file_size.
        """
        conn = self._get_conn()

        row = conn.execute("SELECT id FROM books WHERE slug = ?", (book_slug,)).fetchone()
        if not row:
            return []
        book_id = row["id"]

        rows = conn.execute(
            """SELECT version_num, content_hash, created_at, file_size
               FROM file_versions WHERE book_id = ?
               ORDER BY version_num ASC""",
            (book_id,),
        ).fetchall()

        return [dict(r) for r in rows]

    def get_file_version(self, book_slug: str, version_num: int) -> Optional[dict]:
        """Get a specific version snapshot (with content).

        Returns:
            Dict with version_num, content_hash, created_at, file_size, snapshot.
        """
        conn = self._get_conn()

        row = conn.execute("SELECT id FROM books WHERE slug = ?", (book_slug,)).fetchone()
        if not row:
            return None
        book_id = row["id"]

        row = conn.execute(
            """SELECT version_num, content_hash, created_at, file_size, snapshot
               FROM file_versions WHERE book_id = ? AND version_num = ?""",
            (book_id, version_num),
        ).fetchone()

        return dict(row) if row else None

    def compare_file_versions(self, book_slug: str, v1: int, v2: int) -> dict:
        """Compare metadata of two file versions.

        Returns:
            Dict with both versions' metadata and size diff.
        """
        ver1 = self.get_file_version(book_slug, v1)
        ver2 = self.get_file_version(book_slug, v2)

        if not ver1 or not ver2:
            return {"error": "One or both versions not found"}

        return {
            "book_slug": book_slug,
            "v1": {"version_num": ver1["version_num"], "content_hash": ver1["content_hash"],
                    "created_at": ver1["created_at"], "file_size": ver1["file_size"]},
            "v2": {"version_num": ver2["version_num"], "content_hash": ver2["content_hash"],
                    "created_at": ver2["created_at"], "file_size": ver2["file_size"]},
            "size_diff": (ver2["file_size"] or 0) - (ver1["file_size"] or 0),
            "content_changed": ver1["content_hash"] != ver2["content_hash"],
        }

    # ==================== Embeddings ====================

    def generate_embeddings(
        self,
        corpus: Optional[str] = None,
        batch_size: int = 32,
        model: Optional[str] = None,
        force: bool = False,
        show_progress: bool = True,
    ) -> dict:
        """
        Generate embeddings for chunks.

        Args:
            corpus: Only process chunks in this corpus (None = all)
            batch_size: Number of chunks to embed at once
            model: Embedding model name (None = default)
            force: Re-generate even if embedding exists
            show_progress: Show progress bar

        Returns:
            Stats dict with counts
        """
        from rtfm.core.embeddings import (
            embed_texts, embedding_to_bytes, DEFAULT_MODEL, resolve_model
        )

        # Resolve alias to full HF name early so we store a single canonical name
        requested = resolve_model(model).hf_name if model else None
        # ``active`` may be a short name from an older DB (e.g. plain
        # ``paraphrase-multilingual-MiniLM-L12-v2``) — normalize so we always
        # hand fastembed the fully-qualified form it expects.
        active_raw = self.get_active_embedding_model()
        active = resolve_model(active_raw).hf_name if active_raw else None

        if requested and active and requested != active and not force:
            raise ValueError(
                f"\n  ⚠️  Model mismatch: DB already uses '{active}', "
                f"got '{requested}'.\n"
                f"     Use --force to rebuild all embeddings with the new model,\n"
                f"     or omit --embed-model to continue with the active model."
            )

        # Precedence: explicit arg → existing DB model → default
        model = requested or active or DEFAULT_MODEL

        # If forcing and the model is changing, wipe existing embeddings first
        # so we don't end up with a mixed-dim DB that breaks similarity search.
        if force and active and requested and requested != active:
            self._get_conn().execute("DELETE FROM chunk_embeddings")

        conn = self._get_conn()

        # Get chunks to embed
        if force:
            if corpus:
                cursor = conn.execute(
                    """SELECT c.id, c.content FROM chunks c
                       JOIN books b ON c.book_id = b.id
                       WHERE b.corpus = ?""",
                    (corpus,)
                )
            else:
                cursor = conn.execute("SELECT id, content FROM chunks")
        else:
            if corpus:
                cursor = conn.execute(
                    """SELECT c.id, c.content FROM chunks c
                       JOIN books b ON c.book_id = b.id
                       LEFT JOIN chunk_embeddings e ON c.id = e.chunk_id
                       WHERE b.corpus = ? AND e.id IS NULL""",
                    (corpus,)
                )
            else:
                cursor = conn.execute(
                    """SELECT c.id, c.content FROM chunks c
                       LEFT JOIN chunk_embeddings e ON c.id = e.chunk_id
                       WHERE e.id IS NULL"""
                )

        chunks = cursor.fetchall()

        if not chunks:
            return {"embedded": 0, "skipped": 0}

        # Process in batches
        total = len(chunks)
        embedded = 0

        if show_progress:
            print(f"Generating embeddings for {total} chunks...")

        for i in range(0, total, batch_size):
            batch = chunks[i:i + batch_size]
            ids = [c["id"] for c in batch]
            texts = [c["content"] for c in batch]

            # Generate embeddings
            embeddings = embed_texts(texts, model, batch_size=batch_size)

            # Store in database
            for chunk_id, emb in zip(ids, embeddings):
                emb_bytes = embedding_to_bytes(emb)

                if force:
                    conn.execute(
                        """INSERT OR REPLACE INTO chunk_embeddings
                           (chunk_id, model, embedding) VALUES (?, ?, ?)""",
                        (chunk_id, model, emb_bytes)
                    )
                else:
                    conn.execute(
                        """INSERT INTO chunk_embeddings
                           (chunk_id, model, embedding) VALUES (?, ?, ?)""",
                        (chunk_id, model, emb_bytes)
                    )
                embedded += 1

            conn.commit()

            if show_progress:
                pct = min(100, (embedded * 100) // total)
                print(f"\r  [{embedded}/{total}] {pct}% embedded...", end="", flush=True)

        if show_progress:
            print(f"\r  [{embedded}/{total}] 100% embedded.   ")
            print(f"Done. Embedded {embedded} chunks.")

        return {"embedded": embedded, "total": total}

    def embed_chunks_by_id(
        self,
        chunk_ids: list[int],
        model: Optional[str] = None,
    ) -> dict:
        """Generate embeddings for a specific list of chunk ids.

        Used by the priority-queue worker (P2 handler) so a batch of
        chunks created by a P1 ingest can be embedded as a self-contained
        unit. Skips chunks that already have an embedding for the active
        model — idempotent on retry.
        """
        from rtfm.core.embeddings import (
            embed_texts, embedding_to_bytes, DEFAULT_MODEL, resolve_model
        )

        if not chunk_ids:
            return {"embedded": 0, "skipped": 0}

        requested = resolve_model(model).hf_name if model else None
        active_raw = self.get_active_embedding_model()
        active = resolve_model(active_raw).hf_name if active_raw else None
        model_name = requested or active or DEFAULT_MODEL

        conn = self._get_conn()
        # Filter: only chunks that exist AND don't already have an
        # embedding for this model. Use parameter-binding with
        # ``executemany``-style chunking to dodge SQLite's parameter
        # limit if a P2 batch ever grows beyond 999 ids.
        to_embed: list[tuple[int, str]] = []
        for batch in (chunk_ids[i:i + 500] for i in range(0, len(chunk_ids), 500)):
            placeholders = ",".join(["?"] * len(batch))
            rows = conn.execute(
                f"""SELECT c.id, c.content FROM chunks c
                    LEFT JOIN chunk_embeddings e
                      ON c.id = e.chunk_id AND e.model = ?
                    WHERE c.id IN ({placeholders}) AND e.id IS NULL""",
                (model_name, *batch),
            ).fetchall()
            to_embed.extend((r["id"], r["content"]) for r in rows)

        skipped = len(chunk_ids) - len(to_embed)
        if not to_embed:
            return {"embedded": 0, "skipped": skipped}

        # Run fastembed in one shot — the caller is expected to slice
        # ``chunk_ids`` into reasonable batches (32-128) before calling.
        texts = [c for _, c in to_embed]
        ids = [i for i, _ in to_embed]
        embeddings = embed_texts(texts, model_name, batch_size=len(texts))
        for chunk_id, emb in zip(ids, embeddings):
            conn.execute(
                """INSERT INTO chunk_embeddings (chunk_id, model, embedding)
                   VALUES (?, ?, ?)
                   ON CONFLICT(chunk_id) DO UPDATE SET
                       model = excluded.model,
                       embedding = excluded.embedding""",
                (chunk_id, model_name, embedding_to_bytes(emb)),
            )
        conn.commit()
        return {"embedded": len(ids), "skipped": skipped}

    def chunk_ids_for_book(self, book_slug: str) -> list[int]:
        """Return the chunk ids of a book, in stable order. Used by the
        P1 ingest handler to enqueue follow-up P2 embed jobs."""
        rows = self._get_conn().execute(
            """SELECT c.id FROM chunks c
               JOIN books b ON c.book_id = b.id
               WHERE b.slug = ?
               ORDER BY c.id ASC""",
            (book_slug,),
        ).fetchall()
        return [r["id"] for r in rows]

    def chunk_ids_without_embedding(self, corpus: Optional[str] = None,
                                    limit: Optional[int] = None) -> list[int]:
        """Return chunk ids that don't yet have an embedding for the
        active (or default) model. Used by ``rtfm embed`` to enqueue a
        backfill across the whole DB."""
        from rtfm.core.embeddings import DEFAULT_MODEL, resolve_model
        active_raw = self.get_active_embedding_model()
        model_name = (resolve_model(active_raw).hf_name if active_raw
                      else DEFAULT_MODEL)

        sql = """SELECT c.id FROM chunks c
                 LEFT JOIN chunk_embeddings e
                   ON c.id = e.chunk_id AND e.model = ?
                 LEFT JOIN books b ON c.book_id = b.id
                 WHERE e.id IS NULL"""
        params: list = [model_name]
        if corpus:
            sql += " AND b.corpus = ?"
            params.append(corpus)
        sql += " ORDER BY c.id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [r["id"] for r in
                self._get_conn().execute(sql, params).fetchall()]

    def get_embedding_stats(self) -> dict:
        """Get statistics about embeddings."""
        conn = self._get_conn()

        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]

        models = conn.execute(
            "SELECT model, COUNT(*) as count FROM chunk_embeddings GROUP BY model"
        ).fetchall()

        return {
            "total_chunks": total_chunks,
            "embedded": embedded,
            "coverage": f"{100 * embedded / total_chunks:.1f}%" if total_chunks > 0 else "0%",
            "models": {r["model"]: r["count"] for r in models},
        }

    def get_active_embedding_model(self) -> Optional[str]:
        """Return the embedding model dominant in this DB, or None if empty.

        If multiple models coexist (rare, usually a bug), returns the most used.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT model, COUNT(*) as n FROM chunk_embeddings "
            "GROUP BY model ORDER BY n DESC LIMIT 1"
        ).fetchone()
        return row["model"] if row else None

    def semantic_search(
        self,
        query: str,
        limit: int = 10,
        corpus: Optional[str] = None,
        model: Optional[str] = None,
    ) -> SearchResults:
        """
        Search using semantic similarity (embeddings).

        Args:
            query: Search query
            limit: Maximum results
            corpus: Filter by corpus
            model: Embedding model name (None = default)

        Returns:
            SearchResults ordered by similarity
        """
        from rtfm.core.embeddings import (
            embed_text, bytes_to_embedding, cosine_similarity_batch, DEFAULT_MODEL
        )
        import numpy as np

        # Use the DB's active model by default so dim matches stored vectors.
        model = model or self.get_active_embedding_model() or DEFAULT_MODEL
        conn = self._get_conn()

        # Get query embedding
        query_emb = embed_text(query, model)

        # Get all embeddings (with chunk data)
        if corpus:
            cursor = conn.execute(
                """SELECT c.*, e.embedding, b.title as book_title, b.corpus
                   FROM chunks c
                   JOIN chunk_embeddings e ON c.id = e.chunk_id
                   JOIN books b ON c.book_id = b.id
                   WHERE b.corpus = ?""",
                (corpus,)
            )
        else:
            cursor = conn.execute(
                """SELECT c.*, e.embedding, b.title as book_title, b.corpus
                   FROM chunks c
                   JOIN chunk_embeddings e ON c.id = e.chunk_id
                   JOIN books b ON c.book_id = b.id"""
            )

        rows = cursor.fetchall()

        if not rows:
            return SearchResults(results=[], query=query, total_found=0)

        # Compute similarities
        embeddings = np.array([bytes_to_embedding(r["embedding"]) for r in rows])
        similarities = cosine_similarity_batch(query_emb, embeddings)

        # Get top results
        top_indices = np.argsort(similarities)[::-1][:limit]

        results = []
        for rank, idx in enumerate(top_indices, 1):
            row = rows[idx]
            slug = row["chunk_id"].rsplit("-", 1)[0] if row["chunk_id"] else ""
            score = float(similarities[idx])

            chunk = Chunk(
                id=row["chunk_id"],
                content=row["content"],
                book_title=row["book_title"],
                book_slug=slug,
                chapter_title=row["chapter_title"],
                chapter_num=row["chapter_num"],
                page_start=row["page_start"] or 1,
                page_end=row["page_end"] or 1,
                paragraph=row["paragraph"] or 1,
                line_start=row["line_start"],
                line_end=row["line_end"],
                content_chars=row["content_chars"] or len(row["content"]),
                content_hash=row["content_hash"],
                tags=json.loads(row["tags"]) if row["tags"] else None,
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )

            results.append(SearchResult(chunk=chunk, score=score, rank=rank))

        return SearchResults(results=results, query=query, total_found=len(rows))

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        corpus: Optional[str] = None,
        fts_weight: float = 0.3,
        semantic_weight: float = 0.7,
        model: Optional[str] = None,
    ) -> SearchResults:
        """
        Hybrid search combining FTS5 and semantic similarity.

        Args:
            query: Search query
            limit: Maximum results
            corpus: Filter by corpus
            fts_weight: Weight for FTS5 score (0-1)
            semantic_weight: Weight for semantic score (0-1)
            model: Embedding model name (None = default)

        Returns:
            SearchResults with combined scoring
        """
        from rtfm.core.embeddings import (
            embed_text, bytes_to_embedding, cosine_similarity, DEFAULT_MODEL
        )

        model = model or self.get_active_embedding_model() or DEFAULT_MODEL

        # Get FTS results (more than limit to have candidates)
        fts_results = self.search(query, limit=limit * 3, corpus=corpus)

        if not fts_results:
            # Fall back to pure semantic search
            return self.semantic_search(query, limit=limit, corpus=corpus, model=model)

        # Get query embedding
        query_emb = embed_text(query, model)

        conn = self._get_conn()

        # Score each FTS result with semantic similarity
        scored_results = []
        max_fts_score = max(r.score for r in fts_results) if fts_results else 1

        for fts_result in fts_results:
            # Get embedding for this chunk
            cursor = conn.execute(
                """SELECT embedding FROM chunk_embeddings
                   WHERE chunk_id = (SELECT id FROM chunks WHERE chunk_id = ?)""",
                (fts_result.chunk.id,)
            )
            row = cursor.fetchone()

            if row:
                emb = bytes_to_embedding(row["embedding"])
                semantic_score = cosine_similarity(query_emb, emb)
            else:
                semantic_score = 0.0

            # Normalize FTS score to 0-1 range
            fts_norm = fts_result.score / max_fts_score if max_fts_score > 0 else 0

            # Combined score
            combined = (fts_weight * fts_norm) + (semantic_weight * semantic_score)

            scored_results.append((combined, fts_result))

        # Sort by combined score and take top results
        scored_results.sort(key=lambda x: x[0], reverse=True)

        results = []
        for rank, (score, fts_result) in enumerate(scored_results[:limit], 1):
            results.append(SearchResult(
                chunk=fts_result.chunk,
                score=score,
                rank=rank
            ))

        return SearchResults(
            results=results,
            query=query,
            total_found=len(scored_results)
        )

    # =========================================================================
    # File tracking (for incremental sync)
    # =========================================================================

    def list_indexed_files(self, corpus: str | None = None,
                           root: str | None = None) -> dict[str, dict]:
        """Return {filepath: {file_hash, corpus, book_slug, indexed_at, file_size}}.

        If *corpus* is given, only return files belonging to that corpus. If
        *root* is also given, only those that came from that directory — what
        a scan must compare itself against, so the other directories of the
        same corpus are not mistaken for deleted files. Rows whose directory
        was never established are included: they are claimed on the first
        scan that finds them (see :meth:`claim_files_for_root`).
        """
        conn = self._get_conn()
        cols = ("SELECT filepath, file_hash, corpus, book_slug, indexed_at, "
                "file_size FROM indexed_files")
        if corpus and root:
            cursor = conn.execute(
                f"{cols} WHERE corpus = ? AND (root_path = ? OR root_path IS NULL)",
                (corpus, root),
            )
        elif corpus:
            cursor = conn.execute(f"{cols} WHERE corpus = ?", (corpus,))
        else:
            cursor = conn.execute(cols)
        return {
            row["filepath"]: {
                "file_hash": row["file_hash"],
                "corpus": row["corpus"],
                "book_slug": row["book_slug"],
                "indexed_at": row["indexed_at"],
                "file_size": row["file_size"],
            }
            for row in cursor.fetchall()
        }

    def list_ingest_failures(self, corpus: str | None = None) -> dict[str, dict]:
        """Return ``{filepath: {file_hash, file_size, attempts, failed_at}}``.

        The scan uses this to stop re-proposing a file whose content it has
        already tried and failed to parse.
        """
        conn = self._get_conn()
        if corpus:
            cursor = conn.execute(
                "SELECT filepath, file_hash, file_size, attempts, failed_at, error "
                "FROM ingest_failures WHERE corpus = ?", (corpus,))
        else:
            cursor = conn.execute(
                "SELECT filepath, file_hash, file_size, attempts, failed_at, error "
                "FROM ingest_failures")
        return {
            row["filepath"]: {
                "file_hash": row["file_hash"],
                "file_size": row["file_size"],
                "attempts": row["attempts"],
                # Named to match indexed_files so the same freshness helpers
                # can compare either kind of row against the file on disk.
                "indexed_at": row["failed_at"],
                "error": row["error"],
            }
            for row in cursor.fetchall()
        }

    def record_ingest_failure(self, filepath: str, corpus: str,
                              file_hash: str | None, file_size: int,
                              error: str) -> None:
        """Remember that *this content* could not be parsed."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO ingest_failures
                   (filepath, corpus, file_hash, file_size, error, attempts, failed_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(filepath, corpus) DO UPDATE SET
                   file_hash = excluded.file_hash,
                   file_size = excluded.file_size,
                   error = excluded.error,
                   attempts = ingest_failures.attempts + 1,
                   failed_at = excluded.failed_at""",
            (filepath, corpus, file_hash, file_size, error[:2000],
             datetime.now().isoformat()),
        )
        conn.commit()

    def forget_ingest_failures(self) -> int:
        """Forget every remembered parse failure. Returns how many.

        A remembered failure keeps a scan from re-proposing a file whose
        content it already choked on — which is right while the reason
        persists, and wrong the moment the reason is fixed in RTFM itself.
        After such a fix the memory is what keeps the file out of the index,
        so retrying failures has to clear it too.
        """
        conn = self._get_conn()
        n = conn.execute("SELECT COUNT(*) FROM ingest_failures").fetchone()[0]
        conn.execute("DELETE FROM ingest_failures")
        conn.commit()
        return n

    def clear_ingest_failure(self, filepath: str, corpus: str) -> None:
        """Forget a past failure — the file parsed this time."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM ingest_failures WHERE filepath = ? AND corpus = ?",
            (filepath, corpus))
        conn.commit()

    def update_indexed_file(
        self, filepath: str, file_hash: str, corpus: str,
        book_slug: str, file_size: int = 0, root_path: str | None = None,
    ):
        """Insert or update the tracking entry for an indexed file."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO indexed_files (filepath, file_hash, corpus, book_slug, indexed_at, file_size, root_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(filepath, corpus) DO UPDATE SET
                   file_hash = excluded.file_hash,
                   corpus = excluded.corpus,
                   book_slug = excluded.book_slug,
                   indexed_at = excluded.indexed_at,
                   file_size = excluded.file_size,
                   root_path = COALESCE(excluded.root_path, indexed_files.root_path)""",
            (filepath, file_hash, corpus, book_slug,
             datetime.now().isoformat(), file_size, root_path),
        )
        conn.commit()

    def claim_files_for_root(self, corpus: str, root: str,
                             filepaths) -> int:
        """Record that these paths belong to this source directory.

        Called by a scan with what it actually found on disk. One cheap write
        per scan replaces what used to be thousands of filesystem probes: the
        next scan can tell its own files from a sibling directory's by asking
        the index instead of asking the disk — which mattered most where it
        hurt most, on corpora that live on a network mount.
        """
        conn = self._get_conn()
        cur = conn.executemany(
            "UPDATE indexed_files SET root_path = ? "
            "WHERE corpus = ? AND filepath = ? "
            "AND (root_path IS NULL OR root_path <> ?)",
            [(root, corpus, rel, root) for rel in filepaths],
        )
        n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        return n

    def remove_file(self, filepath: str, corpus: str) -> bool:
        """Remove a file from the index: chunks + book + tracking.

        ``corpus`` is required: a relative path identifies a file only within
        its own corpus, and removing "the" README.md without saying which one
        would take a different corpus's copy with it.
        """
        conn = self._get_conn()

        # Find the book_slug from tracking
        cursor = conn.execute(
            "SELECT book_slug FROM indexed_files WHERE filepath = ? AND corpus = ?",
            (filepath, corpus)
        )
        row = cursor.fetchone()
        if not row:
            return False

        book_slug = row["book_slug"]

        # Delete book and its chunks
        if book_slug:
            self.delete_book(book_slug)

        # Remove tracking entry
        conn.execute(
            "DELETE FROM indexed_files WHERE filepath = ? AND corpus = ?",
            (filepath, corpus))
        conn.commit()
        return True

    def move_file(
        self,
        old_filepath: str,
        new_filepath: str,
        new_slug: str,
        corpus: str,
        new_corpus: str | None = None,
    ) -> bool:
        """Update tracking for a moved file (same content, new path).

        Updates the indexed_files tracking and renames the book slug.
        Chunks are linked by book_id (FK) so they follow automatically;
        embeddings (FK on chunk_id) and tags (FK on chunk_id) follow too.

        ``corpus`` names the corpus the file is moving *from* — a relative
        path is unique only within one. When *new_corpus* is provided, the
        file is reassigned to that corpus — used for cross-corpus moves where
        the user reorganises their tree across corpus boundaries without
        re-indexing.
        """
        conn = self._get_conn()

        # Get old tracking info
        cursor = conn.execute(
            "SELECT book_slug, file_hash, corpus, file_size FROM indexed_files "
            "WHERE filepath = ? AND corpus = ?",
            (old_filepath, corpus)
        )
        row = cursor.fetchone()
        if not row:
            return False

        old_slug = row["book_slug"]
        target_corpus = new_corpus if new_corpus is not None else row["corpus"]

        # Update books table (slug + filename + optional corpus)
        if old_slug:
            conn.execute(
                "UPDATE books SET slug = ?, filename = ?, corpus = ? WHERE slug = ?",
                (new_slug, new_filepath, target_corpus, old_slug)
            )

        # Upsert the new tracking row first. ``ON CONFLICT(filepath) DO UPDATE``
        # tolerates any pre-existing row at ``new_filepath`` (e.g. when only
        # the corpus is renamed, ``new_filepath == old_filepath``; or when an
        # earlier sync step happened to write the same path). Without this,
        # a plain INSERT raised ``UNIQUE constraint failed: indexed_files.filepath``
        # mid-sync and left the DB with orphan ``books`` rows whose tracking
        # row had already been DELETEd.
        conn.execute(
            """INSERT INTO indexed_files (filepath, file_hash, corpus, book_slug, indexed_at, file_size)
               VALUES (?, ?, ?, ?, datetime('now'), ?)
               ON CONFLICT(filepath, corpus) DO UPDATE SET
                   file_hash = excluded.file_hash,
                   corpus = excluded.corpus,
                   book_slug = excluded.book_slug,
                   indexed_at = excluded.indexed_at,
                   file_size = excluded.file_size""",
            (new_filepath, row["file_hash"], target_corpus, new_slug, row["file_size"])
        )
        # Clean up the old tracking row only if it differs from the new one,
        # otherwise the upsert above already covered it.
        if (old_filepath, corpus) != (new_filepath, target_corpus):
            conn.execute(
                "DELETE FROM indexed_files WHERE filepath = ? AND corpus = ?",
                (old_filepath, corpus))
        conn.commit()
        return True

    def book_slug_for(self, filepath: str, corpus: str) -> str | None:
        """The identity this file was indexed under, or None if it is new.

        A file that has not moved keeps its slug whatever the naming rule
        does later, so every writer must ask here before computing one.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT book_slug FROM indexed_files WHERE filepath = ? AND corpus = ?",
            (filepath, corpus),
        ).fetchone()
        return row["book_slug"] if row and row["book_slug"] else None

    def allocate_book_slug(self, preferred: str, filepath: str,
                           corpus: str) -> str:
        """Return a slug for this file that no other file already owns.

        The slug scheme keeps distinct files distinct, but no naming rule can
        promise that for ever — two different paths can always normalise to
        the same string. When they did, the second file raised a UNIQUE
        violation and was dropped from the index without a word. So the write
        side settles it: if the preferred slug belongs to a different file, a
        counter is appended until one is free.

        Returns ``preferred`` unchanged in the ordinary case, and for a file
        that already owns it.
        """
        conn = self._get_conn()
        candidate = preferred
        n = 1
        while True:
            row = conn.execute(
                "SELECT filename, corpus FROM books WHERE slug = ?",
                (candidate,),
            ).fetchone()
            if row is None:
                return candidate
            if row["filename"] == filepath and (row["corpus"] or "") == corpus:
                return candidate          # already this file's own slug
            n += 1
            candidate = f"{preferred}-{n}"

    def set_sync_root(self, corpus: str, root_path: str):
        """Record an absolute source directory for a corpus.

        Adds to what the corpus already has — a corpus may gather several
        directories. Re-recording one just refreshes its timestamp.
        """
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO sync_roots (corpus, root_path, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(corpus, root_path) DO UPDATE SET
                   updated_at = excluded.updated_at""",
            (corpus, root_path),
        )
        conn.commit()

    def list_sync_roots(self, corpus: str | None = None) -> list[str]:
        """Every source directory recorded for a corpus, most recent first.

        Path resolution tries them in order, and a scan uses the others to
        tell a genuinely deleted file from one that simply lives under a
        sibling directory of the same corpus.
        """
        conn = self._get_conn()
        if corpus is None:
            rows = conn.execute(
                "SELECT root_path FROM sync_roots ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT root_path FROM sync_roots WHERE corpus = ? "
                "ORDER BY updated_at DESC",
                (corpus,),
            ).fetchall()
        return [r["root_path"] for r in rows]

    def sync(
        self,
        root: str | Path,
        corpus: str = "default",
        extensions: set[str] | None = None,
        exclude_dirs: set[str] | None = None,
        dry_run: bool = False,
        generate_embeddings: bool = True,
    ) -> dict:
        """Convenience method that delegates to sync module."""
        from rtfm.core.sync import sync as _sync
        return _sync(
            library=self,
            root=Path(root),
            corpus=corpus,
            extensions=extensions,
            exclude_dirs=exclude_dirs,
            dry_run=dry_run,
            generate_embeddings=generate_embeddings,
        )

