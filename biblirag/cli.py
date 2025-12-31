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


def cmd_versions(args):
    """List versioned articles or show version history."""
    lib = Library(args.db)

    if args.article:
        # Show history for a specific article
        history = lib.get_article_history(args.article)
        if not history:
            print(f"No versions found for: {args.article}")
        elif args.format == "json":
            print(json.dumps(history, indent=2, default=str))
        else:
            print(f"Version history for {args.article}:")
            for v in history:
                date_range = f"{v['date_debut'] or '?'} - {v['date_fin'] or 'current'}"
                etat = v.get('etat', '')
                print(f"  v{v['version_num']}: {date_range} [{etat}]")
                if v.get('texte_modificateur'):
                    print(f"       Modified by: {v['texte_modificateur'][:60]}...")
    else:
        # List all versioned articles
        articles = lib.list_versioned_articles(corpus=args.corpus)
        if not articles:
            print("No versioned articles found.")
        elif args.format == "json":
            print(json.dumps(articles, indent=2))
        else:
            for a in articles:
                print(f"{a['article_ref']}: {a['version_count']} versions")

    lib.close()


def cmd_version_at(args):
    """Get article content at a specific date."""
    lib = Library(args.db)

    result = lib.get_article_at_date(args.article, args.date)

    if not result:
        print(f"No version found for {args.article} at {args.date}")
    elif args.format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        v = result
        print(f"Article: {args.article} (v{v['version_num']})")
        print(f"Period: {v['date_debut']} - {v['date_fin'] or 'current'}")
        print(f"State: {v['etat']}")
        if v.get('texte_modificateur'):
            print(f"Modified by: {v['texte_modificateur']}")
        print(f"\n{v['content']}")

    lib.close()


def cmd_compare_versions(args):
    """Compare two versions of an article."""
    lib = Library(args.db)

    result = lib.compare_versions(args.article, args.v1, args.v2)

    if "error" in result:
        print(f"Error: {result['error']}")
    elif args.format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        v1_data, v2_data = result['v1'], result['v2']
        print(f"Comparing {args.article}: v{args.v1} vs v{args.v2}")
        print(f"\nVersion {args.v1}: {v1_data['date_debut']} - {v1_data['date_fin'] or 'current'}")
        print(f"Version {args.v2}: {v2_data['date_debut']} - {v2_data['date_fin'] or 'current'}")
        print(f"\nCharacters: {result['chars_v1']} -> {result['chars_v2']} ({result['chars_diff']:+d})")
        print(f"Content changed: {'Yes' if result['content_changed'] else 'No'}")

    lib.close()


def cmd_embed(args):
    """Generate embeddings for chunks."""
    lib = Library(args.db)

    stats = lib.generate_embeddings(
        corpus=args.corpus,
        batch_size=args.batch_size,
        force=args.force,
        show_progress=True,
    )

    print(f"Embedded: {stats['embedded']} chunks")
    lib.close()


def cmd_embed_stats(args):
    """Show embedding statistics."""
    lib = Library(args.db)
    stats = lib.get_embedding_stats()

    print(f"Chunks:    {stats['total_chunks']}")
    print(f"Embedded:  {stats['embedded']} ({stats['coverage']})")
    if stats['models']:
        print(f"Models:    {stats['models']}")

    lib.close()


def cmd_semantic_search(args):
    """Search using semantic similarity."""
    lib = Library(args.db)

    if args.hybrid:
        results = lib.hybrid_search(
            args.query,
            limit=args.limit,
            corpus=args.corpus,
        )
    else:
        results = lib.semantic_search(
            args.query,
            limit=args.limit,
            corpus=args.corpus,
        )

    if args.format == "json":
        print(results.to_json())
    else:
        for r in results:
            print(f"\n[{r.rank}] {r.source} - score: {r.score:.3f}")
            print(f"    {r.content[:200]}...")

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

    # versions (list versioned articles or show history)
    p_versions = subparsers.add_parser("versions", help="List versioned articles or show history")
    p_versions.add_argument("--article", "-a", help="Show history for specific article (e.g., CGI-39-decies-A)")
    p_versions.add_argument("--corpus", "-c", help="Filter by corpus")
    p_versions.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_versions.set_defaults(func=cmd_versions)

    # version-at (get article at specific date)
    p_version_at = subparsers.add_parser("version-at", help="Get article at specific date")
    p_version_at.add_argument("article", help="Article reference (e.g., CGI-39-decies-A)")
    p_version_at.add_argument("date", help="Date in YYYY-MM-DD format")
    p_version_at.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_version_at.set_defaults(func=cmd_version_at)

    # compare-versions (compare two versions)
    p_compare = subparsers.add_parser("compare-versions", help="Compare two article versions")
    p_compare.add_argument("article", help="Article reference (e.g., CGI-39-decies-A)")
    p_compare.add_argument("v1", type=int, help="First version number")
    p_compare.add_argument("v2", type=int, help="Second version number")
    p_compare.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_compare.set_defaults(func=cmd_compare_versions)

    # embed (generate embeddings)
    p_embed = subparsers.add_parser("embed", help="Generate embeddings for chunks")
    p_embed.add_argument("--corpus", "-c", help="Only embed chunks in this corpus")
    p_embed.add_argument("--batch-size", type=int, default=32, help="Batch size")
    p_embed.add_argument("--force", action="store_true", help="Re-generate all embeddings")
    p_embed.set_defaults(func=cmd_embed)

    # embed-stats (show embedding statistics)
    p_embed_stats = subparsers.add_parser("embed-stats", help="Show embedding statistics")
    p_embed_stats.set_defaults(func=cmd_embed_stats)

    # semantic-search (search using embeddings)
    p_semantic = subparsers.add_parser("semantic-search", help="Search using semantic similarity")
    p_semantic.add_argument("query", help="Search query")
    p_semantic.add_argument("--limit", "-l", type=int, default=10)
    p_semantic.add_argument("--corpus", "-c", help="Filter by corpus")
    p_semantic.add_argument("--hybrid", action="store_true", help="Use hybrid FTS5 + semantic search")
    p_semantic.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_semantic.set_defaults(func=cmd_semantic_search)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
