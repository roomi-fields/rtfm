"""Main Library class - the public API for biblirag."""

import json
import sqlite3
from pathlib import Path
from typing import Optional, Iterator
from datetime import datetime

from biblirag.core.models import Chunk, SearchResult, SearchResults
from biblirag.parsers.base import BaseParser, ParserRegistry


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
    tags TEXT,  -- JSON array
    metadata TEXT,  -- JSON blob for extended metadata
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (chapter_id) REFERENCES chapters(id)
);

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
        from biblirag import Library

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

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with proper settings."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=60)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout = 60000")
            self._conn.execute("PRAGMA journal_mode = WAL")
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

        conn.commit()

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
                c.content, c.content_chars, c.content_hash, c.tags, c.metadata,
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
                raise ValueError(f"No parser available for: {path.suffix}")

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

    def _index_chunks(
        self,
        chunks: list[Chunk],
        corpus: str,
        metadata: dict
    ) -> dict:
        """Index a list of chunks into the database."""
        conn = self._get_conn()

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
                 json.dumps(metadata), datetime.now().isoformat(), book_id)
            )
        else:
            cursor = conn.execute(
                """INSERT INTO books (slug, title, filename, corpus, metadata, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (book_slug, book_title, book_file, corpus,
                 json.dumps(metadata), datetime.now().isoformat())
            )
            book_id = cursor.lastrowid

        # Track chapters
        chapters = {}  # chapter_num -> chapter_id
        stats = {"chunks": 0, "chars": 0}

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

            # Insert chunk
            conn.execute(
                """INSERT INTO chunks
                   (chunk_id, book_id, chapter_id, chapter_num, chapter_title,
                    page_start, page_end, paragraph, content, content_chars,
                    content_hash, tags, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chunk.id, book_id, chapter_id, chunk.chapter_num,
                 chunk.chapter_title, chunk.page_start, chunk.page_end,
                 chunk.paragraph, chunk.content, chunk.content_chars,
                 chunk.content_hash, tags_json, metadata_json)
            )

            stats["chunks"] += 1
            stats["chars"] += chunk.content_chars

        # Update book stats
        conn.execute(
            """UPDATE books SET chunk_count = ?, total_chars = ?, indexed_at = ?
               WHERE id = ?""",
            (stats["chunks"], stats["chars"], datetime.now().isoformat(), book_id)
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
        conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()

        return True
