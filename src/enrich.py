#!/usr/bin/env python3
"""Enrich book metadata using Open Library API."""

import json
import re
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DB_PATH


OPENLIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
RATE_LIMIT_DELAY = 1.0  # Seconds between API calls (be nice to the API)


def update_schema(conn: sqlite3.Connection) -> None:
    """Add metadata columns to books table if they don't exist."""
    # Check existing columns
    cursor = conn.execute("PRAGMA table_info(books)")
    existing = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("author", "TEXT"),
        ("subjects", "TEXT"),  # JSON array
        ("publish_year", "INTEGER"),
        ("publisher", "TEXT"),
        ("isbn", "TEXT"),
        ("pages", "INTEGER"),
        ("cover_id", "INTEGER"),
        ("openlibrary_key", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE books ADD COLUMN {col_name} {col_type}")
            print(f"  Added column: {col_name}")

    conn.commit()


def extract_search_terms(filename: str) -> tuple[str, str]:
    """Extract title and author from filename."""
    # Common patterns:
    # "Title (Author Name) (Z-Library).pdf"
    # "Title (Author, First) (Z-Library).pdf"
    # "Title by Author.pdf"

    name = filename.replace('.pdf', '').replace('.md', '')

    # Remove common suffixes
    name = re.sub(r'\s*\(Z-Library\)', '', name, flags=re.I)
    name = re.sub(r'\s*\[Z-Library\]', '', name, flags=re.I)

    # Try to extract author from parentheses
    author_match = re.search(r'\(([^)]+)\)\s*$', name)
    if author_match:
        author = author_match.group(1)
        title = name[:author_match.start()].strip()

        # Clean author name
        author = re.sub(r',\s*[A-Z]\.\s*[A-Z]\.?$', '', author)  # Remove initials at end
        author = author.replace(',', ' ').strip()

        return title, author

    # Try "Title by Author" pattern
    by_match = re.search(r'^(.+?)\s+by\s+(.+)$', name, re.I)
    if by_match:
        return by_match.group(1).strip(), by_match.group(2).strip()

    # Just use the whole name as title
    return name.strip(), ""


def search_openlibrary(title: str, author: str = "") -> Optional[dict]:
    """Search Open Library for book metadata."""
    params = {
        "title": title,
        "fields": "key,title,author_name,subject,first_publish_year,publisher,isbn,number_of_pages_median,cover_i",
        "limit": 5
    }

    if author:
        params["author"] = author

    url = f"{OPENLIBRARY_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rtfm/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

            if data.get("docs"):
                return data["docs"][0]  # Return best match
    except Exception as e:
        print(f"    API error: {e}")

    return None


def enrich_book(conn: sqlite3.Connection, book_id: int, slug: str, filename: str) -> bool:
    """Enrich a single book with Open Library metadata."""
    title, author = extract_search_terms(filename or slug)

    print(f"  Searching: \"{title}\"" + (f" by {author}" if author else ""))

    metadata = search_openlibrary(title, author)

    if not metadata:
        # Try without author
        if author:
            print(f"    Retrying without author...")
            metadata = search_openlibrary(title)

    if not metadata:
        print(f"    Not found")
        return False

    # Extract and store metadata
    updates = {
        "author": ", ".join(metadata.get("author_name", [])) or None,
        "subjects": json.dumps(metadata.get("subject", [])[:10]) if metadata.get("subject") else None,
        "publish_year": metadata.get("first_publish_year"),
        "publisher": ", ".join(metadata.get("publisher", [])[:3]) if metadata.get("publisher") else None,
        "isbn": metadata.get("isbn", [None])[0] if metadata.get("isbn") else None,
        "pages": metadata.get("number_of_pages_median"),
        "cover_id": metadata.get("cover_i"),
        "openlibrary_key": metadata.get("key"),
    }

    # Build UPDATE query
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [book_id]

    conn.execute(f"UPDATE books SET {set_clause} WHERE id = ?", values)
    conn.commit()

    print(f"    ✓ Found: {metadata.get('title')}")
    if updates["author"]:
        print(f"      Author: {updates['author']}")
    if updates["subjects"]:
        subjects = json.loads(updates["subjects"])
        print(f"      Subjects: {', '.join(subjects[:5])}")

    return True


def enrich_all(db_path: Optional[Path] = None, force: bool = False) -> dict:
    """Enrich all books in the database."""
    db_path = db_path or DB_PATH

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        return {"error": "Database not found"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Update schema first
    print("Updating schema...")
    update_schema(conn)

    # Get books to enrich
    if force:
        cursor = conn.execute("SELECT id, slug, filename, title FROM books ORDER BY title")
    else:
        cursor = conn.execute(
            "SELECT id, slug, filename, title FROM books WHERE author IS NULL ORDER BY title"
        )

    books = cursor.fetchall()

    if not books:
        print("All books already enriched. Use --force to re-fetch.")
        return {"enriched": 0, "failed": 0}

    print(f"\nEnriching {len(books)} books...\n")

    stats = {"enriched": 0, "failed": 0}

    for i, book in enumerate(books, 1):
        print(f"[{i}/{len(books)}] {book['title']}")

        success = enrich_book(conn, book['id'], book['slug'], book['filename'])

        if success:
            stats["enriched"] += 1
        else:
            stats["failed"] += 1

        # Rate limiting
        if i < len(books):
            time.sleep(RATE_LIMIT_DELAY)

    conn.close()

    print(f"\n=== Summary ===")
    print(f"Enriched: {stats['enriched']}")
    print(f"Failed: {stats['failed']}")

    return stats


def show_metadata(db_path: Optional[Path] = None) -> None:
    """Display enriched metadata for all books."""
    db_path = db_path or DB_PATH

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT title, author, subjects, publish_year, publisher
        FROM books
        ORDER BY author, title
    """)

    current_author = None

    for book in cursor.fetchall():
        author = book['author'] or "Unknown Author"

        if author != current_author:
            print(f"\n{'='*60}")
            print(f"  {author}")
            print(f"{'='*60}")
            current_author = author

        print(f"\n  {book['title']}")
        if book['publish_year']:
            print(f"    Year: {book['publish_year']}")
        if book['subjects']:
            subjects = json.loads(book['subjects'])
            print(f"    Subjects: {', '.join(subjects[:5])}")

    conn.close()


def list_subjects(db_path: Optional[Path] = None) -> dict:
    """List all subjects with book counts."""
    db_path = db_path or DB_PATH

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("SELECT subjects FROM books WHERE subjects IS NOT NULL")

    subject_counts = {}
    for row in cursor.fetchall():
        subjects = json.loads(row['subjects'])
        for subject in subjects:
            subject_lower = subject.lower()
            subject_counts[subject_lower] = subject_counts.get(subject_lower, 0) + 1

    conn.close()

    # Sort by count
    sorted_subjects = sorted(subject_counts.items(), key=lambda x: -x[1])

    print("\nSubjects:")
    print("-" * 40)
    for subject, count in sorted_subjects[:30]:
        print(f"  {subject:<35} ({count})")

    return dict(sorted_subjects)


def list_authors(db_path: Optional[Path] = None) -> list:
    """List all authors with book counts."""
    db_path = db_path or DB_PATH

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT author, COUNT(*) as count, GROUP_CONCAT(title, '; ') as books
        FROM books
        WHERE author IS NOT NULL
        GROUP BY author
        ORDER BY count DESC, author
    """)

    authors = []
    print("\nAuthors:")
    print("-" * 40)
    for row in cursor.fetchall():
        print(f"  {row['author']:<35} ({row['count']} books)")
        authors.append({"author": row['author'], "count": row['count']})

    conn.close()
    return authors


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enrich book metadata from Open Library")
    parser.add_argument("--force", action="store_true", help="Re-fetch all metadata")
    parser.add_argument("--show", action="store_true", help="Show current metadata")
    parser.add_argument("--subjects", action="store_true", help="List all subjects")
    parser.add_argument("--authors", action="store_true", help="List all authors")
    parser.add_argument("-d", "--db", help="Database path")

    args = parser.parse_args()

    db = Path(args.db) if args.db else None

    if args.show:
        show_metadata(db)
    elif args.subjects:
        list_subjects(db)
    elif args.authors:
        list_authors(db)
    else:
        enrich_all(db, args.force)
