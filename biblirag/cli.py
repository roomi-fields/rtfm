"""Command-line interface for biblirag."""

import argparse
import json
import sys
from pathlib import Path

from biblirag.core.library import Library


def cmd_search(args):
    """Search the library."""
    lib = Library(args.db)
    results = lib.search(
        args.query,
        limit=args.limit,
        corpus=args.corpus,
        book=args.book,
    )

    if args.format == "json":
        print(results.to_json())
    elif args.format == "markdown":
        print(results.to_markdown())
    elif args.format == "prompt":
        print(results.to_prompt(max_chars=args.max_chars))
    else:
        # Default: simple text
        for r in results:
            print(f"\n[{r.rank}] {r.source} ({r.page}) - score: {r.score:.2f}")
            if r.tags:
                print(f"    Tags: {', '.join(r.tags)}")
            print(f"    {r.content[:200]}...")

    lib.close()


def cmd_stats(args):
    """Show library statistics."""
    lib = Library(args.db)
    stats = lib.get_stats()

    print(f"Books:         {stats['books']}")
    print(f"Chunks:        {stats['chunks']}")
    print(f"Total chars:   {stats['total_chars']:,}")
    print(f"Tagged chunks: {stats['tagged_chunks']}")
    print(f"Corpora:       {stats['corpora']}")

    lib.close()


def cmd_books(args):
    """List books in the library."""
    lib = Library(args.db)
    books = lib.list_books(corpus=args.corpus)

    if args.format == "json":
        print(json.dumps(books, indent=2))
    else:
        for b in books:
            corpus = f"[{b['corpus']}] " if b.get('corpus') else ""
            print(f"{corpus}{b['title']}: {b['chunk_count']} chunks")

    lib.close()


def cmd_corpora(args):
    """List corpora in the library."""
    lib = Library(args.db)
    corpora = lib.list_corpora()

    if args.format == "json":
        print(json.dumps(corpora, indent=2))
    else:
        for c in corpora:
            print(f"{c['corpus']}: {c['book_count']} books, {c['total_chunks']} chunks")

    lib.close()


def cmd_schema(args):
    """Show biblirag schema."""
    from biblirag.schema import print_schema
    print_schema()


def cmd_tags(args):
    """List or manage tags."""
    lib = Library(args.db)

    if args.format == "json":
        tags = lib.list_tags(corpus=args.corpus)
        print(json.dumps(tags, indent=2))
    else:
        tags = lib.list_tags(corpus=args.corpus)
        if not tags:
            print("No tags found.")
        else:
            for t in tags:
                print(f"{t['tag']}: {t['count']} chunks")

    lib.close()


def cmd_tag_add(args):
    """Add tags to chunks."""
    lib = Library(args.db)

    tags = [t.strip() for t in args.tags.split(",")]

    if args.chunk:
        # Tag a specific chunk
        if lib.add_tags(args.chunk, tags):
            print(f"Added tags {tags} to chunk {args.chunk}")
        else:
            print(f"Chunk not found: {args.chunk}")
    else:
        # Tag multiple chunks by corpus/book
        count = lib.tag_chunks(
            tags,
            corpus=args.corpus,
            book=args.book,
        )
        print(f"Added tags {tags} to {count} chunks")

    lib.close()


def main():
    parser = argparse.ArgumentParser(
        prog="biblirag",
        description="Local document library with semantic search"
    )
    parser.add_argument(
        "--db", "-d",
        default="library.db",
        help="Path to database file (default: library.db)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # search
    p_search = subparsers.add_parser("search", help="Search the library")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", "-l", type=int, default=10)
    p_search.add_argument("--corpus", "-c", help="Filter by corpus")
    p_search.add_argument("--book", "-b", help="Filter by book slug")
    p_search.add_argument("--format", "-f", choices=["text", "json", "markdown", "prompt"], default="text")
    p_search.add_argument("--max-chars", type=int, default=8000, help="Max chars for prompt format")
    p_search.set_defaults(func=cmd_search)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show library statistics")
    p_stats.set_defaults(func=cmd_stats)

    # books
    p_books = subparsers.add_parser("books", help="List books")
    p_books.add_argument("--corpus", "-c", help="Filter by corpus")
    p_books.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_books.set_defaults(func=cmd_books)

    # corpora
    p_corpora = subparsers.add_parser("corpora", help="List corpora")
    p_corpora.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_corpora.set_defaults(func=cmd_corpora)

    # schema
    p_schema = subparsers.add_parser("schema", help="Show field schema")
    p_schema.set_defaults(func=cmd_schema)

    # tags
    p_tags = subparsers.add_parser("tags", help="List all tags")
    p_tags.add_argument("--corpus", "-c", help="Filter by corpus")
    p_tags.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_tags.set_defaults(func=cmd_tags)

    # tag (add tags)
    p_tag = subparsers.add_parser("tag", help="Add tags to chunks")
    p_tag.add_argument("tags", help="Comma-separated tags to add")
    p_tag.add_argument("--chunk", help="Specific chunk ID to tag")
    p_tag.add_argument("--corpus", "-c", help="Tag all chunks in corpus")
    p_tag.add_argument("--book", "-b", help="Tag all chunks in book")
    p_tag.set_defaults(func=cmd_tag_add)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
