"""Command-line interface for rtfm."""

import argparse
import json
import sys
from pathlib import Path

from rtfm.core.library import Library


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
    """Show rtfm schema."""
    from rtfm.schema import print_schema
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


def cmd_ask(args):
    """Ask a question (traceable RAG)."""
    lib = Library(args.db)

    answer = lib.ask(
        args.question,
        limit=args.limit,
        corpus=args.corpus,
        search_mode=args.search_mode,
        check_context=not args.no_context_check,
        verify=not args.no_verify,
        deep_verify=args.deep_verify,
    )

    if args.format == "json":
        print(answer.to_json())
    elif args.format == "markdown":
        print(answer.to_markdown())
    else:
        # Default: text format
        if not answer.sufficient_context:
            print(f"Contexte insuffisant : {answer.confidence_note}")
            lib.close()
            return

        print(answer.text)
        print()
        print("--- Sources ---")
        for c in answer.citations:
            print(f"  [{c.ref}] {c.chunk.source} ({c.chunk.page})")

        if answer.grounding_scores:
            score_pct = f"{answer.grounding_score * 100:.0f}%"
            print(f"\nGrounding : {score_pct}")
            if answer.ungrounded_claims:
                print(f"Claims non verifies : {len(answer.ungrounded_claims)}")
                for claim in answer.ungrounded_claims:
                    print(f"  - {claim}")

    lib.close()


def cmd_status(args):
    """Show detailed RTFM status."""
    lib = Library(args.db)

    stats = lib.get_stats()
    print(f"Database:      {args.db}")
    print(f"Books:         {stats['books']}")
    print(f"Chunks:        {stats['chunks']}")
    print(f"Total chars:   {stats['total_chars']:,}")
    print(f"Tagged chunks: {stats['tagged_chunks']}")

    # Corpora breakdown
    corpora = lib.list_corpora()
    if corpora:
        print(f"\nCorpora ({len(corpora)}):")
        for c in corpora:
            print(f"  {c['corpus']}: {c['book_count']} books, {c['total_chunks']} chunks")

    # Embedding coverage
    try:
        emb = lib.get_embedding_stats()
        print(f"\nEmbeddings:    {emb['embedded']}/{emb['total_chunks']} ({emb['coverage']})")
        if emb.get('models'):
            print(f"Model:         {emb['models']}")
    except Exception:
        print("\nEmbeddings:    n/a")

    # Indexed files summary
    indexed = lib.list_indexed_files()
    if indexed:
        from datetime import datetime
        dates = []
        for info in indexed.values():
            if info.get("indexed_at"):
                try:
                    dates.append(info["indexed_at"])
                except Exception:
                    pass
        if dates:
            last_sync = max(dates)
            print(f"\nIndexed files: {len(indexed)}")
            print(f"Last sync:     {last_sync}")
    else:
        print(f"\nIndexed files: 0")

    # Parsers available
    from rtfm.parsers.base import ParserRegistry
    exts = ParserRegistry.list_extensions()
    print(f"\nParsers:       {len(set(ParserRegistry.list_parsers().values()))} registered")
    print(f"Extensions:    {', '.join(sorted(exts))}")

    lib.close()


def cmd_sync(args):
    """Sync files into the library."""
    from rtfm.core.sync import sync

    root = Path(args.path).resolve()
    lib = Library(args.db)

    extensions = None
    if args.extensions:
        extensions = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                      for e in args.extensions.split(",")}

    files_list = None
    if args.files:
        files_list = args.files

    if args.dry_run:
        print(f"Dry run — scanning {root} ...")

    symbols = {"add": "+", "update": "~", "remove": "-", "error": "!", "embed": "*", "skip": "."}

    def _progress(action: str, filepath: str, detail: str) -> None:
        sym = symbols.get(action, "?")
        if filepath:
            print(f"  {sym} {filepath}  ({detail})")
        else:
            print(f"  {sym} {detail}")

    result = sync(
        library=lib,
        root=root,
        corpus=args.corpus,
        extensions=extensions,
        dry_run=args.dry_run,
        generate_embeddings=not args.no_embeddings,
        files=files_list,
        on_progress=_progress,
        force=args.force,
    )

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Added:     {result.added}")
    print(f"{prefix}Modified:  {result.modified}")
    print(f"{prefix}Removed:   {result.removed}")
    print(f"{prefix}Unchanged: {result.unchanged}")
    if result.errors:
        print(f"Errors: {len(result.errors)}")
        for e in result.errors:
            print(f"  - {e}")

    lib.close()


def cmd_init(args):
    """Initialize rtfm for a project."""
    from rtfm.plugin.install import init_project

    root = Path(".").resolve()

    print(f"Initializing RTFM in {root} ...")

    summary = init_project(
        project_root=root,
        db_path=args.db if args.db != ".rtfm/library.db" else None,
        corpus=args.corpus,
        install_hook=not args.no_hook,
        no_embeddings=args.no_embeddings,
    )

    print(f"Database: {summary['db_path']}")
    info = summary["discover"]
    print(f"Project: {info['total_files']} files, languages: {', '.join(info['languages']) or 'none detected'}")
    print(f".mcp.json: {summary['mcp_json']}")
    print(f"CLAUDE.md: {summary['claude_md']}")
    print(f"Hook: {summary['hook']}")
    sync_info = summary["sync"]
    print(f"Synced: {sync_info['added']} entry-point files")
    print("Done.")


def cmd_monitor(args):
    """Tail the RTFM log file — shows live MCP and hook activity."""
    import subprocess
    log_path = Path(args.path)
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch()
        print(f"Created {log_path} — waiting for activity...")
    else:
        print(f"Monitoring {log_path} — Ctrl+C to stop\n")
    try:
        subprocess.run(["tail", "-f", str(log_path)])
    except KeyboardInterrupt:
        print("\nStopped.")


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
    # Shared --db argument inherited by every subcommand
    db_parent = argparse.ArgumentParser(add_help=False)
    db_parent.add_argument(
        "--db", "-d",
        default="library.db",
        help="Path to database file (default: library.db)"
    )

    parser = argparse.ArgumentParser(
        prog="rtfm",
        description="RTFM — Read The F***ing Manual",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # search
    p_search = subparsers.add_parser("search", help="Search the library", parents=[db_parent])
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", "-l", type=int, default=10)
    p_search.add_argument("--corpus", "-c", help="Filter by corpus")
    p_search.add_argument("--book", "-b", help="Filter by book slug")
    p_search.add_argument("--format", "-f", choices=["text", "json", "markdown", "prompt"], default="text")
    p_search.add_argument("--max-chars", type=int, default=8000, help="Max chars for prompt format")
    p_search.set_defaults(func=cmd_search)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show library statistics", parents=[db_parent])
    p_stats.set_defaults(func=cmd_stats)

    # books
    p_books = subparsers.add_parser("books", help="List books", parents=[db_parent])
    p_books.add_argument("--corpus", "-c", help="Filter by corpus")
    p_books.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_books.set_defaults(func=cmd_books)

    # corpora
    p_corpora = subparsers.add_parser("corpora", help="List corpora", parents=[db_parent])
    p_corpora.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_corpora.set_defaults(func=cmd_corpora)

    # schema
    p_schema = subparsers.add_parser("schema", help="Show field schema")
    p_schema.set_defaults(func=cmd_schema)

    # tags
    p_tags = subparsers.add_parser("tags", help="List all tags", parents=[db_parent])
    p_tags.add_argument("--corpus", "-c", help="Filter by corpus")
    p_tags.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_tags.set_defaults(func=cmd_tags)

    # tag (add tags)
    p_tag = subparsers.add_parser("tag", help="Add tags to chunks", parents=[db_parent])
    p_tag.add_argument("tags", help="Comma-separated tags to add")
    p_tag.add_argument("--chunk", help="Specific chunk ID to tag")
    p_tag.add_argument("--corpus", "-c", help="Tag all chunks in corpus")
    p_tag.add_argument("--book", "-b", help="Tag all chunks in book")
    p_tag.set_defaults(func=cmd_tag_add)

    # versions (list versioned articles or show history)
    p_versions = subparsers.add_parser("versions", help="List versioned articles or show history", parents=[db_parent])
    p_versions.add_argument("--article", "-a", help="Show history for specific article (e.g., CGI-39-decies-A)")
    p_versions.add_argument("--corpus", "-c", help="Filter by corpus")
    p_versions.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_versions.set_defaults(func=cmd_versions)

    # version-at (get article at specific date)
    p_version_at = subparsers.add_parser("version-at", help="Get article at specific date", parents=[db_parent])
    p_version_at.add_argument("article", help="Article reference (e.g., CGI-39-decies-A)")
    p_version_at.add_argument("date", help="Date in YYYY-MM-DD format")
    p_version_at.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_version_at.set_defaults(func=cmd_version_at)

    # compare-versions (compare two versions)
    p_compare = subparsers.add_parser("compare-versions", help="Compare two article versions", parents=[db_parent])
    p_compare.add_argument("article", help="Article reference (e.g., CGI-39-decies-A)")
    p_compare.add_argument("v1", type=int, help="First version number")
    p_compare.add_argument("v2", type=int, help="Second version number")
    p_compare.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_compare.set_defaults(func=cmd_compare_versions)

    # embed (generate embeddings)
    p_embed = subparsers.add_parser("embed", help="Generate embeddings for chunks", parents=[db_parent])
    p_embed.add_argument("--corpus", "-c", help="Only embed chunks in this corpus")
    p_embed.add_argument("--batch-size", type=int, default=32, help="Batch size")
    p_embed.add_argument("--force", action="store_true", help="Re-generate all embeddings")
    p_embed.set_defaults(func=cmd_embed)

    # embed-stats (show embedding statistics)
    p_embed_stats = subparsers.add_parser("embed-stats", help="Show embedding statistics", parents=[db_parent])
    p_embed_stats.set_defaults(func=cmd_embed_stats)

    # semantic-search (search using embeddings)
    p_semantic = subparsers.add_parser("semantic-search", help="Search using semantic similarity", parents=[db_parent])
    p_semantic.add_argument("query", help="Search query")
    p_semantic.add_argument("--limit", "-l", type=int, default=10)
    p_semantic.add_argument("--corpus", "-c", help="Filter by corpus")
    p_semantic.add_argument("--hybrid", action="store_true", help="Use hybrid FTS5 + semantic search")
    p_semantic.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_semantic.set_defaults(func=cmd_semantic_search)

    # status
    p_status = subparsers.add_parser("status", help="Show RTFM status", parents=[db_parent])
    p_status.set_defaults(func=cmd_status)

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync files into the library", parents=[db_parent])
    p_sync.add_argument("path", nargs="?", default=".", help="Directory to sync")
    p_sync.add_argument("--corpus", "-c", default="default")
    p_sync.add_argument("--extensions", "-e", help="Comma-separated extensions (e.g. md,py,pdf)")
    p_sync.add_argument("--dry-run", action="store_true", help="Show what would change")
    p_sync.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    p_sync.add_argument("--force", action="store_true", help="Re-index all files (ignore hash cache)")
    p_sync.add_argument("--files", nargs="+", help="Specific files to sync (for git hooks)")
    p_sync.set_defaults(func=cmd_sync)

    # init (has its own --db default)
    p_init = subparsers.add_parser("init", help="Initialize RTFM for a project")
    p_init.add_argument("--db", "-d", default=".rtfm/library.db",
                         help="Database path (default: .rtfm/library.db)")
    p_init.add_argument("--corpus", "-c", default="default")
    p_init.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    p_init.add_argument("--no-hook", action="store_true", help="Don't install auto-sync hook")
    p_init.set_defaults(func=cmd_init)

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Tail the RTFM log (live MCP/hook activity)")
    p_monitor.add_argument("--path", "-p", default=".rtfm/rtfm.log",
                           help="Path to log file (default: .rtfm/rtfm.log)")
    p_monitor.set_defaults(func=cmd_monitor)

    # ask (traceable RAG)
    p_ask = subparsers.add_parser("ask", help="Poser une question (RAG tracable)", parents=[db_parent])
    p_ask.add_argument("question", help="Question a poser")
    p_ask.add_argument("--limit", "-l", type=int, default=10)
    p_ask.add_argument("--corpus", "-c", help="Filtrer par corpus")
    p_ask.add_argument("--search-mode", choices=["fts", "semantic", "hybrid"], default="hybrid")
    p_ask.add_argument("--format", "-f", choices=["text", "json", "markdown"], default="text")
    p_ask.add_argument("--no-context-check", action="store_true", help="Desactiver le niveau 0")
    p_ask.add_argument("--no-verify", action="store_true", help="Desactiver la verification grounding")
    p_ask.add_argument("--deep-verify", action="store_true", help="Verification LLM-as-judge (niveau 2+)")
    p_ask.set_defaults(func=cmd_ask)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
