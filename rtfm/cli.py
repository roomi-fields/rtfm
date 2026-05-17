"""Command-line interface for rtfm."""

import argparse
import json
import sys
from pathlib import Path

from rtfm.config import resolve_db
from rtfm.core.library import Library


def _get_lib(args) -> Library:
    """Resolve DB path and return a Library instance."""
    db = resolve_db(args.db)
    return Library(db)


def _deduplicate_by_source(results, limit: int):
    """Keep only the best chunk per unique source (book_slug).

    Returns a list of dicts: {best: SearchResult, count: int},
    sorted by score, limited to *limit* unique sources.
    """
    seen: dict[str, dict] = {}
    for r in results:
        slug = r.chunk.book_slug
        if slug not in seen:
            seen[slug] = {"best": r, "count": 1}
        else:
            seen[slug]["count"] += 1
            if r.score > seen[slug]["best"].score:
                seen[slug]["best"] = r

    ranked = sorted(seen.values(), key=lambda x: x["best"].score, reverse=True)
    return ranked[:limit]


def _resolve_abs_path(filepath: str, lib, corpus: str) -> str:
    """Resolve a relative filepath to absolute using stored sync root."""
    import os

    if not filepath or os.path.isabs(filepath):
        return filepath
    try:
        root = lib.get_sync_root(corpus)
        if root:
            abs_path = os.path.join(root, filepath)
            if os.path.exists(abs_path):
                return abs_path
    except Exception:
        pass
    return filepath


def cmd_search(args):
    """Search the library."""
    lib = _get_lib(args)
    # Overfetch so dedup still yields enough unique sources
    fetch_limit = args.limit * 5
    results = lib.search(
        args.query,
        limit=fetch_limit,
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
        # Default: metadata-only, deduplicated by source.
        # Same progressive-disclosure format as the MCP server.
        deduped = _deduplicate_by_source(results, args.limit)
        if not deduped:
            print(f"No results for: {args.query}")
        else:
            for rank, entry in enumerate(deduped, 1):
                r = entry["best"]
                count = entry["count"]
                filepath = _resolve_abs_path(
                    r.chunk.book_file or "", lib, ""
                )
                parts = [f"{r.source} ({r.page})"]
                parts.append(f"score: {r.score:.2f}")
                parts.append(f"{count} chunks")
                if filepath:
                    parts.append(f"file: {filepath}")
                else:
                    parts.append(f"slug: {r.chunk.book_slug}")
                print(f"[{rank}] {' — '.join(parts)}")

    lib.close()


def cmd_stats(args):
    """Show library statistics."""
    lib = _get_lib(args)
    stats = lib.get_stats()

    print(f"Books:         {stats['books']}")
    print(f"Chunks:        {stats['chunks']}")
    print(f"Total chars:   {stats['total_chars']:,}")
    print(f"Tagged chunks: {stats['tagged_chunks']}")
    print(f"Corpora:       {stats['corpora']}")

    lib.close()


def cmd_books(args):
    """List books in the library."""
    lib = _get_lib(args)
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
    lib = _get_lib(args)
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
    lib = _get_lib(args)

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
    lib = _get_lib(args)

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
    lib = _get_lib(args)

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
    lib = _get_lib(args)

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
    lib = _get_lib(args)

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
    from rtfm.core.embeddings import resolve_model, warn_if_heavy

    lib = _get_lib(args)

    requested = getattr(args, "embed_model", None)
    if requested:
        # Interactive size guard before triggering a possibly-large download
        if not warn_if_heavy(requested):
            print("Aborted.")
            lib.close()
            return
        model = resolve_model(requested).hf_name
    else:
        model = None  # Library auto-picks: DB active → default

    try:
        stats = lib.generate_embeddings(
            corpus=args.corpus,
            batch_size=args.batch_size,
            model=model,
            force=args.force,
            show_progress=True,
        )
    except ValueError as err:
        # Raised on model-mismatch without --force
        print(str(err))
        lib.close()
        return

    print(f"Embedded: {stats['embedded']} chunks")
    lib.close()


def cmd_embed_stats(args):
    """Show embedding statistics."""
    lib = _get_lib(args)
    stats = lib.get_embedding_stats()

    print(f"Chunks:    {stats['total_chunks']}")
    print(f"Embedded:  {stats['embedded']} ({stats['coverage']})")
    if stats['models']:
        print(f"Models:    {stats['models']}")

    lib.close()


def cmd_embed_models(args):
    """List curated embedding models (aliases) supported by RTFM."""
    from rtfm.core.embeddings import EMBEDDING_MODELS, DEFAULT_ALIAS, is_model_cached

    print(f"{'alias':<10} {'dim':<6} {'size':<9} {'cached':<8} {'lang':<14} model")
    print(f"{'-'*10} {'-'*6} {'-'*9} {'-'*8} {'-'*14} {'-'*50}")
    for alias, info in EMBEDDING_MODELS.items():
        mark = " *" if alias == DEFAULT_ALIAS else ""
        cached = "yes" if is_model_cached(info.hf_name) else "no"
        print(
            f"{alias+mark:<10} {info.dim:<6} ~{info.size_mb}MB    "
            f"{cached:<8} {info.languages:<14} {info.hf_name}"
        )
    print(f"\n  * = default. Pass --embed-model <alias> or a full HF model name.")



def cmd_context(args):
    """Get context for a subject (metadata-only, like MCP rtfm_context)."""
    lib = _get_lib(args)

    try:
        results = lib.hybrid_search(args.subject, limit=args.limit * 5, corpus=args.corpus)
    except Exception:
        results = lib.search(args.subject, limit=args.limit * 5, corpus=args.corpus)

    if not results:
        print(f"No context found for: {args.subject}")
        lib.close()
        return

    # Deduplicate by source
    seen: dict[str, dict] = {}
    for r in results:
        slug = r.chunk.book_slug
        if slug not in seen:
            seen[slug] = {"best": r, "count": 1}
        else:
            seen[slug]["count"] += 1
            if r.score > seen[slug]["best"].score:
                seen[slug]["best"] = r

    ranked = sorted(seen.values(), key=lambda x: x["best"].score, reverse=True)[:args.limit]

    print(f"Context for \"{args.subject}\" ({len(ranked)} sources):\n")
    for rank, entry in enumerate(ranked, 1):
        r = entry["best"]
        count = entry["count"]
        slug = r.chunk.book_slug
        filepath = r.chunk.book_file or ""
        lang = r.chunk.metadata.get("lang", "") if r.chunk.metadata else ""

        parts = [f"{r.source} ({r.page})", f"score: {r.score:.3f}", f"{count} chunks"]
        if lang:
            parts.append(f"lang: {lang}")
        if filepath:
            parts.append(f"file: {filepath}")

        print(f"[{rank}] {' — '.join(parts)}")
        print(f"    → rtfm expand \"{slug}\"")

    lib.close()


def cmd_expand(args):
    """Expand a source — show all chunks (like MCP rtfm_expand)."""
    lib = _get_lib(args)
    conn = lib._get_conn()

    # Get book info
    book_row = conn.execute(
        "SELECT id, title, filename, metadata FROM books WHERE slug = ?",
        (args.source,),
    ).fetchone()

    if not book_row:
        print(f"Source not found: {args.source}")
        lib.close()
        return

    book_title = book_row["title"]
    book_file = book_row["filename"] or ""
    meta = json.loads(book_row["metadata"]) if book_row["metadata"] else {}
    lang = meta.get("lang", "")

    header_parts = [f"Expanding \"{book_title}\""]
    if lang:
        header_parts.append(f"lang: {lang}")
    if book_file:
        header_parts.append(f"file: {book_file}")

    if args.query:
        # Search within this book
        try:
            results = lib.hybrid_search(args.query, limit=args.limit, corpus=None)
        except Exception:
            results = lib.search(args.query, limit=args.limit, corpus=None)

        filtered = [r for r in results if r.chunk.book_slug == args.source]
        if not filtered:
            results = lib.search(args.query, limit=args.limit, book=args.source)
            filtered = list(results)

        if not filtered:
            print(f"No chunks found in '{args.source}' for: {args.query}")
            lib.close()
            return

        print(f"{' | '.join(header_parts)} — {len(filtered)} chunks for \"{args.query}\":\n")
        for i, r in enumerate(filtered, 1):
            section = r.chunk.chapter_title or ""
            print(f"[{i}] {section} ({r.page}) — score: {r.score:.3f}")
            print(f"    {r.content}\n")
    else:
        # All chunks in page order
        cursor = conn.execute(
            """SELECT c.*, b.title as book_title
               FROM chunks c JOIN books b ON c.book_id = b.id
               WHERE b.slug = ?
               ORDER BY c.page_start, c.paragraph
               LIMIT ?""",
            (args.source, args.limit),
        )
        rows = cursor.fetchall()

        if not rows:
            print(f"No chunks in source: {args.source}")
            lib.close()
            return

        print(f"{' | '.join(header_parts)} — {len(rows)} chunks (page order):\n")
        for i, row in enumerate(rows, 1):
            section = row["chapter_title"] or ""
            ps = row["page_start"] or "?"
            pe = row["page_end"] or ps
            page = f"p.{ps}" if ps == pe else f"pp.{ps}-{pe}"
            print(f"[{i}] {section} ({page})")
            print(f"    {row['content']}\n")

    lib.close()


def cmd_files(args):
    """List indexed files, optionally filtered."""
    import fnmatch

    lib = _get_lib(args)
    indexed = lib.list_indexed_files(corpus=args.corpus)
    lib.close()

    if not indexed:
        print("No indexed files.")
        return

    # Optional pattern filter
    if args.pattern:
        indexed = {k: v for k, v in indexed.items() if fnmatch.fnmatch(k, args.pattern)}

    if not indexed:
        print(f"No files matching: {args.pattern}")
        return

    print(f"{len(indexed)} indexed files:\n")
    for fp, info in sorted(indexed.items()):
        corpus = info.get("corpus", "")
        size = info.get("file_size", 0)
        size_str = f"{size:,}" if size else "?"
        print(f"  [{corpus}] {fp}  ({size_str} bytes)")


def cmd_status(args):
    """Show detailed RTFM status."""
    db = resolve_db(args.db)
    lib = Library(db)

    stats = lib.get_stats()
    print(f"Database:      {db}")
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

    # Optional extras — visible install state + actionable next step
    def _check(mod: str) -> bool:
        try:
            __import__(mod)
            return True
        except ImportError:
            return False

    extras = [
        ("embeddings", _check("fastembed"), "semantic search",       "rtfm-ai[embeddings]"),
        ("pdf",        _check("pdftext"),   "PDF parsing",          "rtfm-ai[pdf]"),
    ]
    print("\nOptional extras:")
    for name, installed, purpose, pkg in extras:
        mark = "✓" if installed else "✗"
        if installed:
            print(f"  {mark} {name:<12}installed ({purpose})")
        else:
            print(f"  {mark} {name:<12}missing — pip install {pkg}   ({purpose})")

    # Health: pending sync work + known scan suspects. Best-effort, only
    # if a .rtfm/ config is reachable (skipped for ad-hoc db paths).
    try:
        from rtfm.config import find_rtfm_root, load_config
        from rtfm.core.sync import sync as _sync
        root = find_rtfm_root()
        if root:
            cfg = load_config(root)
            sources = cfg.get("sources") or [
                {"path": str(root), "corpus": cfg.get("corpus", "default")}
            ]
            pending_added = pending_modified = pending_removed = 0
            for src in sources:
                src_path = Path(src.get("path", ".")).resolve()
                src_corpus = src.get("corpus", "default")
                ext_set = None
                if src.get("extensions"):
                    ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                               for e in src["extensions"].split(",")}
                try:
                    dry = _sync(
                        library=lib, root=src_path, corpus=src_corpus,
                        extensions=ext_set, dry_run=True,
                        generate_embeddings=False,
                    )
                    pending_added += dry.added
                    pending_modified += dry.modified
                    pending_removed += dry.removed
                except Exception:
                    pass

            seen_scans = []
            scans_file = root / ".rtfm" / "seen_scans.json"
            if scans_file.exists():
                try:
                    seen_scans = json.loads(scans_file.read_text())
                except Exception:
                    pass

            print("\nIndex health:")
            if pending_added or pending_modified or pending_removed:
                if pending_added:
                    print(f"  + {pending_added} new file(s) not yet indexed   → rtfm sync")
                if pending_modified:
                    print(f"  ~ {pending_modified} modified file(s) since last sync → rtfm sync")
                if pending_removed:
                    print(f"  - {pending_removed} file(s) in DB but missing on disk → rtfm sync")
            else:
                print("  ✓ index is up to date")
            if seen_scans:
                print(f"  ⚠ {len(seen_scans)} PDF(s) flagged as likely scans (0 text)")
                for path in seen_scans[:5]:
                    print(f"      - {path}")
                if len(seen_scans) > 5:
                    print(f"      ... +{len(seen_scans) - 5} more")
    except Exception:
        pass  # health section is best-effort

    lib.close()


def _print_health_warnings(result) -> None:
    """Surface scan/empty-file warnings after a sync."""
    if result.suspect_scans:
        print()
        print(f"⚠ {len(result.suspect_scans)} PDF probablement scannés "
              f"(0 texte extrait) :")
        for path in result.suspect_scans[:10]:
            print(f"    - {path}")
        if len(result.suspect_scans) > 10:
            print(f"    ... et {len(result.suspect_scans) - 10} autre(s)")
        print("  → activer l'OCR : pip install rtfm-ai[pdf] "
              "puis rtfm sync (backend marker requis)")
    if result.empty_files:
        print()
        print(f"⚠ {len(result.empty_files)} fichier(s) sans contenu extrait :")
        for path in result.empty_files[:10]:
            print(f"    - {path}")
        if len(result.empty_files) > 10:
            print(f"    ... et {len(result.empty_files) - 10} autre(s)")


def cmd_sync(args):
    """Sync files into the library."""
    from rtfm.core.sync import sync
    from rtfm.config import find_rtfm_root, load_config

    lib = _get_lib(args)

    symbols = {"add": "+", "update": "~", "remove": "-", "error": "!", "embed": "*", "skip": "."}

    def _progress(action: str, filepath: str, detail: str) -> None:
        sym = symbols.get(action, "?")
        if filepath:
            print(f"  {sym} {filepath}  ({detail})")
        else:
            print(f"  {sym} {detail}")

    # Detect if user provided explicit path or corpus
    explicit_mode = args.path is not None or args.corpus is not None

    if not explicit_mode:
        # Config mode: sync all registered sources
        root = find_rtfm_root()
        if root:
            config = load_config(root)
            sources = config.get("sources", [])
            if sources:
                for src in sources:
                    src_path = Path(src["path"]).resolve()
                    src_corpus = src.get("corpus", "default")
                    src_ext = None
                    if src.get("extensions"):
                        src_ext = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                                   for e in src["extensions"].split(",")}

                    print(f"Syncing [{src_corpus}] {src_path} ...")
                    result = sync(
                        library=lib,
                        root=src_path,
                        corpus=src_corpus,
                        extensions=src_ext,
                        dry_run=args.dry_run,
                        generate_embeddings=not args.no_embeddings,
                        on_progress=_progress,
                        force=args.force,
                    )

                    prefix = "[dry-run] " if args.dry_run else ""
                    print(f"{prefix}  Added: {result.added}  Modified: {result.modified}  "
                          f"Removed: {result.removed}  Unchanged: {result.unchanged}")
                    if result.errors:
                        for e in result.errors:
                            print(f"  ! {e}")
                    _print_health_warnings(result)
                    print()

                lib.close()
                return

    # Explicit mode (or no config found): original behavior
    root = Path(args.path or ".").resolve()
    corpus = args.corpus or "default"

    extensions = None
    if args.extensions:
        extensions = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                      for e in args.extensions.split(",")}

    files_list = None
    if args.files:
        files_list = args.files

    if args.dry_run:
        print(f"Dry run — scanning {root} ...")

    result = sync(
        library=lib,
        root=root,
        corpus=corpus,
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
    _print_health_warnings(result)

    lib.close()


def cmd_add(args):
    """Register a source in .rtfm/config.json."""
    from rtfm.config import find_rtfm_root, add_source

    root = find_rtfm_root()
    if not root:
        print("No .rtfm/ found. Run 'rtfm init' first.")
        sys.exit(1)

    ext = args.extensions or None
    result = add_source(root, args.path, corpus=args.corpus, extensions=ext)
    resolved = str(Path(args.path).resolve())

    if result == "added":
        print(f"Added source: [{args.corpus}] {resolved}")
        if ext:
            print(f"  Extensions: {ext}")
    else:
        print(f"Source already registered: [{args.corpus}] {resolved}")


def cmd_sources(args):
    """List registered sources."""
    from rtfm.config import find_rtfm_root, list_sources

    root = find_rtfm_root()
    if not root:
        print("No .rtfm/ found. Run 'rtfm init' first.")
        sys.exit(1)

    sources = list_sources(root)
    if not sources:
        print("No sources registered. Use 'rtfm add <path>' to add one.")
        return

    print("Sources:")
    for src in sources:
        ext_info = f"  (extensions: {src['extensions']})" if src.get("extensions") else ""
        print(f"  [{src.get('corpus', 'default')}] {src['path']}{ext_info}")


def cmd_serve(args):
    """Start the RTFM MCP server."""
    import os
    db = resolve_db(args.db)
    os.environ["RTFM_DB"] = db
    print(f"Starting RTFM MCP server (db: {db}) ...", file=sys.stderr)
    from rtfm.mcp import main as mcp_main
    mcp_main()


def cmd_init(args):
    """Initialize rtfm for a project."""
    from rtfm.plugin.install import init_project

    root = Path(".").resolve()

    # Hint: if this looks like an Obsidian vault, suggest rtfm vault
    if (root / ".obsidian").is_dir():
        print("Tip: This looks like an Obsidian vault. "
              "Run 'rtfm vault' for Obsidian-specific features.\n")

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

    hints = summary.get("hints", [])
    if hints:
        print()
        for hint in hints:
            print(hint)

    print("Done.")


def cmd_vault(args):
    """Initialize RTFM for an Obsidian vault."""
    from rtfm.plugin.vault import detect_obsidian_vault, init_vault, propose_corpus_mapping

    vault_path = Path(args.path).resolve()

    # Detect vault
    vault_info = detect_obsidian_vault(vault_path)
    if not vault_info:
        print(f"No Obsidian vault found at {vault_path}")
        print("(Looking for .obsidian/ directory)")
        sys.exit(1)

    print(f"Obsidian vault detected: {vault_path}\n")

    # Regenerate-only mode
    if args.regenerate:
        from rtfm.config import load_config, resolve_db
        from rtfm.core.library import Library
        from rtfm.plugin.vault_output import generate_vault_output

        db_path = resolve_db(None)
        lib = Library(db_path)
        config = load_config(vault_path)
        result = generate_vault_output(lib, vault_path, config)
        lib.close()
        print(f"Regenerated {result['count']} files:")
        for f in result["files_written"]:
            print(f"  {f}")
        return

    # Propose corpus mapping
    mapping = propose_corpus_mapping(vault_path)
    print(f"Corpus mapping ({len(mapping)} corpora):")
    for m in mapping:
        print(f"  [{m['corpus']}] {m['path']} ({m['file_count']} files)")
    print()

    # Initialize
    print("Initializing...")
    summary = init_vault(
        vault_path,
        corpus_mapping=mapping,
        no_embeddings=args.no_embeddings,
        generate_output=not args.no_output,
    )

    if "error" in summary:
        print(f"Error: {summary['error']}")
        sys.exit(1)

    print(f"\nDatabase: {summary['db_path']}")
    print(f".mcp.json: {summary.get('mcp_json', '?')}")
    print(f"CLAUDE.md: {summary.get('claude_md', '?')}")

    sync_info = summary.get("sync", {})
    for corpus_name, info in sync_info.items():
        if "error" in info:
            print(f"  [{corpus_name}] error: {info['error']}")
        else:
            print(f"  [{corpus_name}] +{info.get('added', 0)} files")

    output = summary.get("output", {})
    if isinstance(output, dict) and "count" in output:
        print(f"\n_rtfm/ output: {output['count']} files generated")

    print("\nDone. Open Obsidian and check _rtfm/index.md")


def cmd_memory(args):
    """Index Claude Code memory files across projects, with unlimited history.

    Discovers ~/.claude/projects/*/memory/*.md files and syncs them into the
    library with corpus="claude-memory/<project>" and retain_history=None.

    Defaults to a global DB at ~/.rtfm/memory.db so every project's memory
    ends up in the same searchable cross-project index.
    """
    from rtfm.core.sync import sync

    if args.install_hook:
        from rtfm.plugin.hooks import install_memory_hook
        result = install_memory_hook()
        print(f"Memory hook {result} at ~/.claude/hooks/rtfm_memory_sync.py")
        print("Registered as SessionEnd hook in ~/.claude/settings.json")
        print("Every Claude Code session will now snapshot memory files on exit.")
        return

    # Default to global memory DB unless user passes --db explicitly.
    if not getattr(args, "db", None):
        default_db = Path.home() / ".rtfm" / "memory.db"
        default_db.parent.mkdir(parents=True, exist_ok=True)
        args.db = str(default_db)
    lib = _get_lib(args)

    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        print(f"No Claude projects directory found at {projects_root}")
        sys.exit(1)

    memory_dirs = sorted(p for p in projects_root.glob("*/memory") if p.is_dir())
    if not memory_dirs:
        print(f"No memory/ directories under {projects_root}")
        sys.exit(1)

    symbols = {"add": "+", "update": "~", "remove": "-", "error": "!"}

    def _progress(action: str, filepath: str, detail: str) -> None:
        sym = symbols.get(action, "?")
        if filepath:
            print(f"  {sym} {filepath}  ({detail})")

    total_added = total_modified = total_unchanged = 0
    for mem_dir in memory_dirs:
        # project slug = directory name of the parent (e.g. "-mnt-d-Claude-RTFM")
        project_slug = mem_dir.parent.name.strip("-") or "root"
        corpus = f"claude-memory/{project_slug}"
        print(f"Syncing [{corpus}] {mem_dir} ...")

        result = sync(
            library=lib,
            root=mem_dir,
            corpus=corpus,
            extensions={".md", ".txt"},
            generate_embeddings=not args.no_embeddings,
            on_progress=_progress if args.verbose else None,
            retain_history=None,  # unlimited history for memory files
        )

        total_added += result.added
        total_modified += result.modified
        total_unchanged += result.unchanged
        print(f"  +{result.added} ~{result.modified} ={result.unchanged}")
        if result.errors:
            for e in result.errors:
                print(f"  ! {e}")

    print(
        f"\nDone. {len(memory_dirs)} projects indexed | "
        f"+{total_added} added, ~{total_modified} modified, ={total_unchanged} unchanged"
    )
    print("History: unlimited (every change versioned)")
    lib.close()


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


def cmd_graph(args):
    """Show dependency graph for a source."""
    lib = _get_lib(args)

    neighbors = lib.get_neighbors(
        args.source,
        direction=args.direction,
        relation_type=args.type,
    )

    if not neighbors:
        print(f"No edges found for: {args.source}")
        lib.close()
        return

    outgoing = [n for n in neighbors if n["direction"] == "outgoing"]
    incoming = [n for n in neighbors if n["direction"] == "incoming"]

    if outgoing:
        print(f"Outgoing ({len(outgoing)} dependencies):")
        for n in outgoing:
            detail = f" — {n['source_detail']}" if n.get("source_detail") else ""
            print(f"  -> {n['filename'] or n['slug']} [{n['relation_type']}]{detail}")

    if incoming:
        print(f"\nIncoming ({len(incoming)} dependents):")
        for n in incoming:
            detail = f" — {n['source_detail']}" if n.get("source_detail") else ""
            print(f"  <- {n['filename'] or n['slug']} [{n['relation_type']}]{detail}")

    stats = lib.get_graph_stats()
    print(f"\nGraph: {stats['total_edges']} edges, {stats['books_with_edges']} connected files")
    if stats["relation_types"]:
        types_str = ", ".join(f"{k}: {v}" for k, v in stats["relation_types"].items())
        print(f"Types: {types_str}")

    lib.close()


def cmd_history(args):
    """Show file version history or specific version."""
    lib = _get_lib(args)

    if args.version is not None:
        ver = lib.get_file_version(args.source, args.version)
        if not ver:
            print(f"Version {args.version} not found for: {args.source}")
        elif args.format == "json":
            print(json.dumps(ver, indent=2))
        else:
            print(f"{args.source} v{ver['version_num']} — {ver['created_at']}")
            print(f"Size: {ver.get('file_size', 0):,} bytes | Hash: {ver['content_hash'][:8]}")
            print(f"\n{ver['snapshot']}")
    else:
        history = lib.get_file_history(args.source)
        if not history:
            print(f"No version history for: {args.source}")
        elif args.format == "json":
            print(json.dumps(history, indent=2))
        else:
            print(f"Version history for {args.source} ({len(history)} versions):")
            for v in history:
                size = v.get("file_size") or 0
                print(f"  v{v['version_num']}: {v['created_at']} — {size:,} bytes (hash: {v['content_hash'][:8]})")

    lib.close()


def cmd_semantic_search(args):
    """Search using semantic similarity."""
    lib = _get_lib(args)

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
        default=None,
        help="Path to database (auto-detected from .rtfm/)"
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
    p_embed.add_argument("--embed-model", dest="embed_model", metavar="ALIAS|HF_NAME",
                         help="Embedding model: alias (fast/balanced/quality) or full HF name. "
                              "Defaults to the DB's active model or 'fast'.")
    p_embed.set_defaults(func=cmd_embed)

    # embed-stats (show embedding statistics)
    p_embed_stats = subparsers.add_parser("embed-stats", help="Show embedding statistics", parents=[db_parent])
    p_embed_stats.set_defaults(func=cmd_embed_stats)

    # embed-models (list curated embedding models)
    p_embed_models = subparsers.add_parser("embed-models", help="List available embedding model aliases")
    p_embed_models.set_defaults(func=cmd_embed_models)

    # semantic-search (search using embeddings)
    p_semantic = subparsers.add_parser("semantic-search", help="Search using semantic similarity", parents=[db_parent])
    p_semantic.add_argument("query", help="Search query")
    p_semantic.add_argument("--limit", "-l", type=int, default=10)
    p_semantic.add_argument("--corpus", "-c", help="Filter by corpus")
    p_semantic.add_argument("--hybrid", action="store_true", help="Use hybrid FTS5 + semantic search")
    p_semantic.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_semantic.set_defaults(func=cmd_semantic_search)

    # context
    p_context = subparsers.add_parser("context", help="Get context for a subject (metadata-only)", parents=[db_parent])
    p_context.add_argument("subject", help="Topic, concept, or question")
    p_context.add_argument("--limit", "-l", type=int, default=5)
    p_context.add_argument("--corpus", "-c", help="Filter by corpus")
    p_context.set_defaults(func=cmd_context)

    # expand
    p_expand = subparsers.add_parser("expand", help="Expand a source — show all chunks", parents=[db_parent])
    p_expand.add_argument("source", help="Book slug (from search/context results)")
    p_expand.add_argument("query", nargs="?", help="Optional query to filter chunks")
    p_expand.add_argument("--limit", "-l", type=int, default=20)
    p_expand.set_defaults(func=cmd_expand)

    # files
    p_files = subparsers.add_parser("files", help="List indexed files", parents=[db_parent])
    p_files.add_argument("pattern", nargs="?", help="Filter by glob pattern (e.g. '*.md', '*config*')")
    p_files.add_argument("--corpus", "-c", help="Filter by corpus")
    p_files.set_defaults(func=cmd_files)

    # status
    p_status = subparsers.add_parser("status", help="Show RTFM status", parents=[db_parent])
    p_status.set_defaults(func=cmd_status)

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync files into the library", parents=[db_parent])
    p_sync.add_argument("path", nargs="?", default=None, help="Directory to sync (auto: all sources from config)")
    p_sync.add_argument("--corpus", "-c", default=None, help="Corpus name (auto: from config)")
    p_sync.add_argument("--extensions", "-e", help="Comma-separated extensions (e.g. md,py,pdf)")
    p_sync.add_argument("--dry-run", action="store_true", help="Show what would change")
    p_sync.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    p_sync.add_argument("--force", action="store_true", help="Re-index all files (ignore hash cache)")
    p_sync.add_argument("--files", nargs="+", help="Specific files to sync (for git hooks)")
    p_sync.set_defaults(func=cmd_sync)

    # add (register a source)
    p_add = subparsers.add_parser("add", help="Register a source directory")
    p_add.add_argument("path", help="Directory to register as a source")
    p_add.add_argument("--corpus", "-c", default="default", help="Corpus name")
    p_add.add_argument("--extensions", "-e", help="Comma-separated extensions (e.g. md,py,pdf)")
    p_add.set_defaults(func=cmd_add)

    # sources (list registered sources)
    p_sources = subparsers.add_parser("sources", help="List registered sources")
    p_sources.set_defaults(func=cmd_sources)

    # graph
    p_graph = subparsers.add_parser("graph", help="Show dependency graph for a source", parents=[db_parent])
    p_graph.add_argument("source", help="Book slug to query")
    p_graph.add_argument("--direction", "-D", choices=["outgoing", "incoming", "both"], default="both")
    p_graph.add_argument("--type", "-t", help="Filter by relation type (import, link, include, cite)")
    p_graph.set_defaults(func=cmd_graph)

    # history
    p_history = subparsers.add_parser("history", help="Show file version history", parents=[db_parent])
    p_history.add_argument("source", help="Book slug to query")
    p_history.add_argument("--version", "-v", type=int, help="Show specific version content")
    p_history.add_argument("--format", "-f", choices=["text", "json"], default="text")
    p_history.set_defaults(func=cmd_history)

    # serve (start MCP server)
    p_serve = subparsers.add_parser("serve", help="Start the RTFM MCP server", parents=[db_parent])
    p_serve.set_defaults(func=cmd_serve)

    # init (has its own --db default)
    p_init = subparsers.add_parser("init", help="Initialize RTFM for a project")
    p_init.add_argument("--db", "-d", default=".rtfm/library.db",
                         help="Database path (default: .rtfm/library.db)")
    p_init.add_argument("--corpus", "-c", default="default")
    p_init.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    p_init.add_argument("--no-hook", action="store_true", help="Don't install auto-sync hook")
    p_init.set_defaults(func=cmd_init)

    # vault (Obsidian vault initialization)
    p_vault = subparsers.add_parser("vault", help="Initialize RTFM for an Obsidian vault")
    p_vault.add_argument("path", nargs="?", default=".", help="Path to Obsidian vault (default: cwd)")
    p_vault.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    p_vault.add_argument("--no-output", action="store_true", help="Skip _rtfm/ output generation")
    p_vault.add_argument("--regenerate", action="store_true", help="Only regenerate _rtfm/ output")
    p_vault.set_defaults(func=cmd_vault)

    # memory (index Claude Code memory files with unlimited history)
    p_memory = subparsers.add_parser(
        "memory",
        help="Index ~/.claude/projects/*/memory/ files with unlimited version history",
        parents=[db_parent],
    )
    p_memory.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    p_memory.add_argument("--verbose", "-v", action="store_true", help="Show per-file progress")
    p_memory.add_argument("--install-hook", action="store_true",
                          help="Install a global Claude Code Stop hook that auto-snapshots memory files")
    p_memory.set_defaults(func=cmd_memory)

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Tail the RTFM log (live MCP/hook activity)")
    p_monitor.add_argument("--path", "-p", default=".rtfm/rtfm.log",
                           help="Path to log file (default: .rtfm/rtfm.log)")
    p_monitor.set_defaults(func=cmd_monitor)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
