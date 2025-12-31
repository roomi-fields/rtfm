"""SQLite indexer with FTS5 full-text search."""

import json
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DB_PATH, JSONL_DIR


SCHEMA = """
-- Books table
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    filename TEXT,
    page_count INTEGER,
    chunk_count INTEGER DEFAULT 0,
    total_chars INTEGER DEFAULT 0,
    indexed_at TEXT
);

-- Chapters table
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

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
"""


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Initialize the database with schema and resilient settings."""
    db_path = db_path or DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")  # Wait up to 60s on lock
    conn.execute("PRAGMA journal_mode = WAL")    # Better concurrent access
    conn.executescript(SCHEMA)
    conn.commit()

    return conn


def import_jsonl(jsonl_path: Path, conn: sqlite3.Connection) -> dict:
    """
    Import a JSONL file into the database.

    Returns:
        Stats dict with counts
    """
    stats = {'chunks': 0, 'chars': 0}

    with open(jsonl_path, 'r', encoding='utf-8') as f:
        first_line = f.readline()
        if not first_line:
            return stats

        first_chunk = json.loads(first_line)
        f.seek(0)  # Reset to beginning

        # Get or create book
        book_slug = first_chunk['book_slug']
        book_title = first_chunk['book_title']
        book_file = first_chunk['book_file']

        cursor = conn.execute(
            "SELECT id FROM books WHERE slug = ?", (book_slug,)
        )
        row = cursor.fetchone()

        if row:
            book_id = row['id']
            # Clear existing chunks for this book (re-import)
            conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        else:
            cursor = conn.execute(
                """INSERT INTO books (slug, title, filename, indexed_at)
                   VALUES (?, ?, ?, ?)""",
                (book_slug, book_title, book_file, datetime.now().isoformat())
            )
            book_id = cursor.lastrowid

        # Track chapters
        chapters = {}  # chapter_num -> chapter_id

        # Import chunks
        for line in f:
            chunk = json.loads(line)

            # Get or create chapter (use part_num as fallback, or section index)
            ch_num = chunk.get('chapter_num') or chunk.get('part_num') or 0
            ch_title = chunk.get('chapter_title') or chunk.get('part_title') or 'Unknown'

            if ch_num not in chapters:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO chapters (book_id, num, title, page_start)
                       VALUES (?, ?, ?, ?)""",
                    (book_id, ch_num, ch_title, chunk['page_start'])
                )
                if cursor.lastrowid:
                    chapters[ch_num] = cursor.lastrowid
                else:
                    cursor = conn.execute(
                        "SELECT id FROM chapters WHERE book_id = ? AND num = ?",
                        (book_id, ch_num)
                    )
                    row = cursor.fetchone()
                    chapters[ch_num] = row['id'] if row else None

            chapter_id = chapters.get(ch_num)

            # Insert chunk
            conn.execute(
                """INSERT INTO chunks
                   (chunk_id, book_id, chapter_id, chapter_num, chapter_title,
                    page_start, page_end, paragraph, content, content_chars, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chunk['id'], book_id, chapter_id, chunk['chapter_num'],
                 chunk['chapter_title'], chunk['page_start'], chunk['page_end'],
                 chunk['paragraph'], chunk['content'], chunk['content_chars'],
                 chunk['content_hash'])
            )

            stats['chunks'] += 1
            stats['chars'] += chunk['content_chars']

        # Update book stats
        conn.execute(
            """UPDATE books SET chunk_count = ?, total_chars = ?, indexed_at = ?
               WHERE id = ?""",
            (stats['chunks'], stats['chars'], datetime.now().isoformat(), book_id)
        )

        conn.commit()

    return stats


def index_all(
    jsonl_dir: Optional[Path] = None,
    db_path: Optional[Path] = None
) -> dict:
    """
    Index all JSONL files into the database.

    Returns:
        Total stats
    """
    jsonl_dir = Path(jsonl_dir) if jsonl_dir else JSONL_DIR
    db_path = Path(db_path) if db_path else DB_PATH

    jsonl_files = list(jsonl_dir.glob('*.jsonl'))

    if not jsonl_files:
        print(f"No JSONL files found in {jsonl_dir}")
        return {'books': 0, 'chunks': 0, 'chars': 0}

    print(f"Found {len(jsonl_files)} JSONL files")
    print(f"Database: {db_path}\n")

    conn = init_db(db_path)

    total_stats = {'books': 0, 'chunks': 0, 'chars': 0}

    for i, jsonl_path in enumerate(jsonl_files, 1):
        print(f"[{i}/{len(jsonl_files)}] Indexing: {jsonl_path.name}")

        try:
            stats = import_jsonl(jsonl_path, conn)
            total_stats['books'] += 1
            total_stats['chunks'] += stats['chunks']
            total_stats['chars'] += stats['chars']
            print(f"  Chunks: {stats['chunks']}, Chars: {stats['chars']:,}")
        except Exception as e:
            print(f"  ERROR: {e}")

    conn.close()

    print(f"\n=== Summary ===")
    print(f"Books indexed: {total_stats['books']}")
    print(f"Total chunks: {total_stats['chunks']}")
    print(f"Total chars: {total_stats['chars']:,}")
    print(f"Database size: {db_path.stat().st_size / 1024 / 1024:.2f} MB")

    return total_stats


def get_db_stats(db_path: Optional[Path] = None) -> dict:
    """Get database statistics."""
    db_path = db_path or DB_PATH

    if not Path(db_path).exists():
        return {'error': 'Database does not exist'}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    stats = {}

    # Book count
    cursor = conn.execute("SELECT COUNT(*) as count FROM books")
    stats['books'] = cursor.fetchone()['count']

    # Chunk count
    cursor = conn.execute("SELECT COUNT(*) as count FROM chunks")
    stats['chunks'] = cursor.fetchone()['count']

    # Total chars
    cursor = conn.execute("SELECT SUM(content_chars) as total FROM chunks")
    stats['total_chars'] = cursor.fetchone()['total'] or 0

    # Book list
    cursor = conn.execute(
        "SELECT slug, title, chunk_count, total_chars FROM books ORDER BY title"
    )
    stats['book_list'] = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Index JSONL into SQLite")
    parser.add_argument("--stats", action="store_true", help="Show database stats")
    parser.add_argument("-d", "--db", help="Database path")
    parser.add_argument("-i", "--input", help="JSONL directory")

    args = parser.parse_args()

    if args.stats:
        stats = get_db_stats(args.db)
        if 'error' in stats:
            print(stats['error'])
        else:
            print(f"Books: {stats['books']}")
            print(f"Chunks: {stats['chunks']}")
            print(f"Total chars: {stats['total_chars']:,}")
            print("\nBooks:")
            for book in stats['book_list']:
                print(f"  - {book['title']}: {book['chunk_count']} chunks")
    else:
        index_all(args.input, args.db)
