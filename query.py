#!/usr/bin/env python3
"""CLI for querying the rtfm library."""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import DB_PATH


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get database connection."""
    db_path = db_path or DB_PATH
    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        print("Run indexer.py first to create the database.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def search(query: str, limit: int = 10, book: Optional[str] = None,
           author: Optional[str] = None, subject: Optional[str] = None,
           db_path: Optional[Path] = None) -> list[dict]:
    """
    Search chunks using FTS5.

    Args:
        query: Search query (supports FTS5 syntax)
        limit: Maximum results
        book: Filter by book slug (optional)
        author: Filter by author name (optional, partial match)
        subject: Filter by subject (optional, partial match)

    Returns:
        List of matching chunks with metadata
    """
    conn = get_connection(db_path)

    # Build query with optional filters
    sql = """
        SELECT
            c.chunk_id,
            c.content,
            c.page_start,
            c.page_end,
            c.chapter_num,
            c.chapter_title,
            b.title as book_title,
            b.slug as book_slug,
            b.author as book_author,
            b.subjects as book_subjects,
            bm25(chunks_fts) as rank
        FROM chunks_fts fts
        JOIN chunks c ON c.id = fts.rowid
        JOIN books b ON b.id = c.book_id
        WHERE chunks_fts MATCH ?
    """

    params = [query]

    if book:
        sql += " AND b.slug = ?"
        params.append(book)

    if author:
        sql += " AND b.author LIKE ?"
        params.append(f"%{author}%")

    if subject:
        sql += " AND b.subjects LIKE ?"
        params.append(f"%{subject}%")

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return results


def format_results(results: list[dict], format_type: str = "default") -> str:
    """Format search results for display."""
    if not results:
        return "No results found."

    if format_type == "prompt":
        # LLM-ready format with clear source citations
        output = []
        for i, r in enumerate(results, 1):
            source = f"[{r['book_title']}, Ch.{r['chapter_num']}: {r['chapter_title']}, p.{r['page_start']}"
            if r['page_end'] != r['page_start']:
                source += f"-{r['page_end']}"
            source += "]"

            output.append(f"--- Source {i} {source} ---")
            output.append(r['content'])
            output.append("")

        return "\n".join(output)

    elif format_type == "json":
        import json
        return json.dumps(results, indent=2, ensure_ascii=False)

    elif format_type == "compact":
        # One-line per result
        output = []
        for r in results:
            loc = f"{r['book_slug']}:ch{r['chapter_num']}:p{r['page_start']}"
            preview = r['content'][:80].replace('\n', ' ') + "..."
            output.append(f"{loc} | {preview}")
        return "\n".join(output)

    else:
        # Default: readable format
        output = []
        for i, r in enumerate(results, 1):
            output.append(f"\n{'='*60}")
            output.append(f"[{i}] {r['book_title']}")
            output.append(f"    Chapter {r['chapter_num']}: {r['chapter_title']}")
            output.append(f"    Pages: {r['page_start']}-{r['page_end']}")
            output.append(f"    ID: {r['chunk_id']}")
            output.append("-" * 60)

            # Truncate content for display
            content = r['content']
            if len(content) > 500:
                content = content[:500] + "..."
            output.append(content)

        output.append(f"\n{'='*60}")
        output.append(f"Found {len(results)} results")
        return "\n".join(output)


def list_books(db_path: Optional[Path] = None) -> list[dict]:
    """List all indexed books."""
    conn = get_connection(db_path)

    cursor = conn.execute("""
        SELECT slug, title, chunk_count, total_chars, indexed_at
        FROM books
        ORDER BY title
    """)

    books = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return books


def book_info(slug: str, db_path: Optional[Path] = None) -> dict:
    """Get detailed info about a book."""
    conn = get_connection(db_path)

    # Book info
    cursor = conn.execute("""
        SELECT * FROM books WHERE slug = ?
    """, (slug,))
    book = cursor.fetchone()

    if not book:
        conn.close()
        return {'error': f"Book '{slug}' not found"}

    book = dict(book)

    # Chapters
    cursor = conn.execute("""
        SELECT num, title, page_start,
               (SELECT COUNT(*) FROM chunks WHERE chapter_id = chapters.id) as chunk_count
        FROM chapters
        WHERE book_id = ?
        ORDER BY num
    """, (book['id'],))
    book['chapters'] = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return book


def get_chunk(chunk_id: str, db_path: Optional[Path] = None) -> Optional[dict]:
    """Get a specific chunk by ID."""
    conn = get_connection(db_path)

    cursor = conn.execute("""
        SELECT c.*, b.title as book_title, b.slug as book_slug
        FROM chunks c
        JOIN books b ON b.id = c.book_id
        WHERE c.chunk_id = ?
    """, (chunk_id,))

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def get_context(chunk_id: str, before: int = 1, after: int = 1,
                db_path: Optional[Path] = None) -> list[dict]:
    """Get a chunk with surrounding context."""
    conn = get_connection(db_path)

    # Get the target chunk's position
    cursor = conn.execute("""
        SELECT id, book_id FROM chunks WHERE chunk_id = ?
    """, (chunk_id,))
    target = cursor.fetchone()

    if not target:
        conn.close()
        return []

    # Get surrounding chunks from same book
    cursor = conn.execute("""
        SELECT c.*, b.title as book_title, b.slug as book_slug
        FROM chunks c
        JOIN books b ON b.id = c.book_id
        WHERE c.book_id = ? AND c.id BETWEEN ? AND ?
        ORDER BY c.id
    """, (target['book_id'], target['id'] - before, target['id'] + after))

    chunks = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return chunks


def stats(db_path: Optional[Path] = None) -> dict:
    """Get database statistics."""
    conn = get_connection(db_path)

    result = {}

    # Counts
    cursor = conn.execute("SELECT COUNT(*) as count FROM books")
    result['books'] = cursor.fetchone()['count']

    cursor = conn.execute("SELECT COUNT(*) as count FROM chunks")
    result['chunks'] = cursor.fetchone()['count']

    cursor = conn.execute("SELECT SUM(total_chars) as total FROM books")
    result['total_chars'] = cursor.fetchone()['total'] or 0

    # DB size
    result['db_size_mb'] = Path(db_path or DB_PATH).stat().st_size / 1024 / 1024

    conn.close()
    return result


def list_authors(db_path: Optional[Path] = None) -> list[dict]:
    """List all authors with book counts."""
    import json as json_mod
    conn = get_connection(db_path)

    cursor = conn.execute("""
        SELECT author, COUNT(*) as count, GROUP_CONCAT(title, ' | ') as books
        FROM books
        WHERE author IS NOT NULL
        GROUP BY author
        ORDER BY count DESC, author
    """)

    authors = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return authors


def list_subjects(db_path: Optional[Path] = None) -> dict:
    """List all subjects with book counts."""
    import json as json_mod
    conn = get_connection(db_path)

    cursor = conn.execute("SELECT subjects, title FROM books WHERE subjects IS NOT NULL")

    subject_counts = {}
    subject_books = {}

    for row in cursor.fetchall():
        subjects = json_mod.loads(row['subjects'])
        for subject in subjects:
            subject_lower = subject.lower()
            subject_counts[subject_lower] = subject_counts.get(subject_lower, 0) + 1
            if subject_lower not in subject_books:
                subject_books[subject_lower] = []
            subject_books[subject_lower].append(row['title'])

    conn.close()

    # Sort by count
    sorted_subjects = sorted(subject_counts.items(), key=lambda x: -x[1])
    return {s: {"count": c, "books": subject_books[s]} for s, c in sorted_subjects}


def main():
    parser = argparse.ArgumentParser(
        description="Query the rtfm library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s search "essence"                    Search for 'essence'
  %(prog)s search "love AND truth" -l 20       Boolean search, 20 results
  %(prog)s search "ego" -b the-point-of-existence  Search in specific book
  %(prog)s search "soul" -a "Almaas"           Filter by author
  %(prog)s search "self" -s "narcissism"       Filter by subject
  %(prog)s search "awareness" -f prompt        LLM-ready output
  %(prog)s books                               List all books
  %(prog)s authors                             List all authors
  %(prog)s subjects                            List all subjects
  %(prog)s book the-point-of-existence         Show book details
  %(prog)s chunk <chunk_id>                    Get specific chunk
  %(prog)s context <chunk_id>                  Get chunk with context
  %(prog)s stats                               Show database stats
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Search command
    search_parser = subparsers.add_parser('search', aliases=['s'], help='Search chunks')
    search_parser.add_argument('query', help='Search query (FTS5 syntax)')
    search_parser.add_argument('-l', '--limit', type=int, default=10, help='Max results')
    search_parser.add_argument('-b', '--book', help='Filter by book slug')
    search_parser.add_argument('-a', '--author', help='Filter by author (partial match)')
    search_parser.add_argument('-s', '--subject', help='Filter by subject (partial match)')
    search_parser.add_argument('-f', '--format', choices=['default', 'prompt', 'json', 'compact'],
                               default='default', help='Output format')

    # Books list command
    books_parser = subparsers.add_parser('books', aliases=['ls'], help='List all books')

    # Authors list command
    authors_parser = subparsers.add_parser('authors', help='List all authors')

    # Subjects list command
    subjects_parser = subparsers.add_parser('subjects', help='List all subjects')

    # Book info command
    book_parser = subparsers.add_parser('book', aliases=['b'], help='Show book details')
    book_parser.add_argument('slug', help='Book slug')

    # Chunk command
    chunk_parser = subparsers.add_parser('chunk', aliases=['c'], help='Get specific chunk')
    chunk_parser.add_argument('chunk_id', help='Chunk ID')
    chunk_parser.add_argument('-f', '--format', choices=['default', 'json', 'prompt'],
                              default='default', help='Output format')

    # Context command
    ctx_parser = subparsers.add_parser('context', aliases=['ctx'], help='Get chunk with context')
    ctx_parser.add_argument('chunk_id', help='Chunk ID')
    ctx_parser.add_argument('-b', '--before', type=int, default=1, help='Chunks before')
    ctx_parser.add_argument('-a', '--after', type=int, default=1, help='Chunks after')
    ctx_parser.add_argument('-f', '--format', choices=['default', 'prompt', 'json'],
                            default='default', help='Output format')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show database statistics')

    # Global options
    parser.add_argument('-d', '--db', help='Database path')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    db_path = Path(args.db) if args.db else None

    if args.command in ('search', 's'):
        results = search(args.query, args.limit, args.book, args.author, args.subject, db_path)
        print(format_results(results, args.format))

    elif args.command in ('books', 'ls'):
        books = list_books(db_path)
        print(f"\n{'Indexed Books':^60}")
        print("=" * 60)
        for b in books:
            chars_k = b['total_chars'] / 1000
            print(f"  {b['slug']:<45} {b['chunk_count']:>4} chunks ({chars_k:.0f}k)")
        print("=" * 60)
        print(f"Total: {len(books)} books")

    elif args.command == 'authors':
        authors = list_authors(db_path)
        print(f"\n{'Authors':^60}")
        print("=" * 60)
        for a in authors:
            print(f"  {a['author']:<45} ({a['count']} books)")
        print("=" * 60)
        print(f"Total: {len(authors)} authors")

    elif args.command == 'subjects':
        subjects = list_subjects(db_path)
        print(f"\n{'Subjects':^60}")
        print("=" * 60)
        for subject, info in subjects.items():
            print(f"  {subject:<45} ({info['count']} books)")
        print("=" * 60)
        print(f"Total: {len(subjects)} subjects")

    elif args.command in ('book', 'b'):
        info = book_info(args.slug, db_path)
        if 'error' in info:
            print(info['error'])
            return

        print(f"\n{info['title']}")
        print("=" * 60)
        print(f"Slug: {info['slug']}")
        print(f"Chunks: {info['chunk_count']}")
        print(f"Characters: {info['total_chars']:,}")
        print(f"Indexed: {info['indexed_at']}")
        print(f"\nChapters ({len(info['chapters'])}):")
        for ch in info['chapters']:
            print(f"  {ch['num']:2}. {ch['title']:<40} ({ch['chunk_count']} chunks)")

    elif args.command in ('chunk', 'c'):
        chunk = get_chunk(args.chunk_id, db_path)
        if not chunk:
            print(f"Chunk '{args.chunk_id}' not found")
            return

        if args.format == 'json':
            import json
            print(json.dumps(chunk, indent=2, ensure_ascii=False))
        elif args.format == 'prompt':
            source = f"[{chunk['book_title']}, Ch.{chunk['chapter_num']}: {chunk['chapter_title']}, p.{chunk['page_start']}-{chunk['page_end']}]"
            print(f"--- {source} ---")
            print(chunk['content'])
        else:
            print(f"\n{chunk['book_title']}")
            print(f"Chapter {chunk['chapter_num']}: {chunk['chapter_title']}")
            print(f"Pages: {chunk['page_start']}-{chunk['page_end']}")
            print(f"ID: {chunk['chunk_id']}")
            print("-" * 60)
            print(chunk['content'])

    elif args.command in ('context', 'ctx'):
        chunks = get_context(args.chunk_id, args.before, args.after, db_path)
        if not chunks:
            print(f"Chunk '{args.chunk_id}' not found")
            return

        if args.format == 'json':
            import json
            print(json.dumps(chunks, indent=2, ensure_ascii=False))
        elif args.format == 'prompt':
            for c in chunks:
                marker = ">>>" if c['chunk_id'] == args.chunk_id else "   "
                source = f"[{c['book_title']}, Ch.{c['chapter_num']}: {c['chapter_title']}, p.{c['page_start']}]"
                print(f"{marker} {source}")
                print(c['content'])
                print()
        else:
            for c in chunks:
                marker = ">>> " if c['chunk_id'] == args.chunk_id else "    "
                print(f"{marker}[{c['chunk_id']}] p.{c['page_start']}-{c['page_end']}")
                content = c['content'][:200] + "..." if len(c['content']) > 200 else c['content']
                print(f"    {content.replace(chr(10), ' ')}")
                print()

    elif args.command == 'stats':
        s = stats(db_path)
        print(f"\nDatabase Statistics")
        print("=" * 40)
        print(f"Books:      {s['books']}")
        print(f"Chunks:     {s['chunks']}")
        print(f"Characters: {s['total_chars']:,}")
        print(f"DB Size:    {s['db_size_mb']:.2f} MB")


if __name__ == "__main__":
    main()
