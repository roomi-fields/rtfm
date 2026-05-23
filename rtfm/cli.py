"""Command-line interface for rtfm.

Since 0.16.x every mutating command is a thin producer: it enqueues
P0 (``P_USER``) jobs, ensures the worker daemon is running, and watches
queue stats until the work it asked for is drained. No CLI command
parses or writes to the library in-process anymore — that's the worker's
job. Use ``--background`` to enqueue and return immediately.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rtfm.config import resolve_db
from rtfm.core.library import Library


def _watch_jobs(
    queue,
    initial_ids: set[int],
    *,
    poll_s: float = 1.0,
    background: bool = False,
    label: str = "",
) -> int:
    """Block until every pending/running job has reached a terminal
    state, polling ``queue.stats()`` every ``poll_s`` seconds.

    We watch the *whole* queue (not just ``initial_ids``) because the
    jobs we enqueued typically fan out child jobs — a scan enqueues
    ingest/remove jobs, a reconcile may enqueue embed batches, etc. The
    user expects ``rtfm sync`` to return only when all of that has
    drained.

    Returns 0 if no failures, 1 if any job ended ``failed``. With
    ``background=True``, returns 0 immediately.
    """
    if background:
        return 0
    start = time.time()
    try:
        while True:
            stats = queue.stats()
            pending = sum(s.get("pending", 0) for s in stats.values())
            running = sum(s.get("running", 0) for s in stats.values())
            done = sum(s.get("done", 0) for s in stats.values())
            failed = sum(s.get("failed", 0) for s in stats.values())
            elapsed = time.time() - start
            per_type = [
                f"{t}={s.get('pending', 0)}p/{s.get('running', 0)}r"
                for t, s in sorted(stats.items())
                if s.get("pending") or s.get("running")
            ]
            extra = ("  " + " ".join(per_type)) if per_type else ""
            lbl = f"{label} " if label else ""
            sys.stderr.write(
                f"\r[{elapsed:5.0f}s] {lbl}pending={pending} running={running} "
                f"done={done} failed={failed}{extra}\033[K"
            )
            sys.stderr.flush()
            if pending == 0 and running == 0:
                sys.stderr.write("\n")
                return 1 if failed else 0
            time.sleep(poll_s)
    except KeyboardInterrupt:
        sys.stderr.write("\n(interrupted — worker keeps draining in background)\n")
        return 130


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
    """Generate embeddings for chunks.

    Default mode (0.10.0+): scan the DB for chunks without an embedding
    (optionally scoped to ``--corpus``), split into P2 batches, enqueue
    them, auto-spawn the worker. Returns immediately. The worker drains
    in the background, preempted by any incoming P1 ingest.

    Legacy mode (--inline): run embedding in-process and block. Useful
    for one-shot CI / scripted runs and for ``--force`` (re-embedding
    everything).
    """
    from rtfm.core.embeddings import resolve_model, warn_if_heavy

    # --force keeps the legacy path: re-embedding *every* chunk doesn't
    # fit the dedup-on-pending model of the queue (we'd want a separate
    # "wipe + queue everything" semantic). For now, force is inline.
    use_queue = (
        not getattr(args, "inline", False)
        and not getattr(args, "force", False)
    )

    if use_queue:
        return _cmd_embed_enqueue(args)

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


def _cmd_embed_enqueue(args):
    """Queue-mode embed (0.10.0+).

    Finds every chunk without an embedding for the active model
    (optionally narrowed by ``--corpus``), batches them at
    ``EMBED_BATCH_SIZE``, enqueues P2 jobs, then auto-spawns the
    worker. Returns immediately.
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.handlers import EMBED_BATCH_SIZE
    from rtfm.core.library import Library
    from rtfm.core.queue import Queue
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("rtfm embed: no .rtfm/ project root in the cwd chain. "
                 "Use `rtfm embed --inline` for a one-shot blocking run.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    lib = Library(str(db_path))
    try:
        chunk_ids = lib.chunk_ids_without_embedding(corpus=args.corpus)
    finally:
        lib.close()

    if not chunk_ids:
        scope = f" in corpus={args.corpus!r}" if args.corpus else ""
        print(f"rtfm embed: nothing to do{scope} — every chunk already embedded.")
        return

    queue = Queue(db_path)
    try:
        batches = [chunk_ids[i:i + EMBED_BATCH_SIZE]
                   for i in range(0, len(chunk_ids), EMBED_BATCH_SIZE)]
        inserted, deduped = queue.enqueue_many(
            "embed", [{"chunk_ids": b} for b in batches])
    finally:
        queue.close()

    scope = f" in {args.corpus!r}" if args.corpus else ""
    print(f"rtfm embed: {len(chunk_ids)} chunk(s){scope} queued as "
          f"{inserted} batch(es) of up to {EMBED_BATCH_SIZE}"
          + (f" ({deduped} dedup'd)" if deduped else "") + ".")

    pid = ensure_worker_running(rtfm_dir)
    if pid:
        print(f"Worker draining in background (PID {pid}). "
              "Track: `rtfm queue stats` / `rtfm worker status`.")
    else:
        print("Worker already running — drain in progress.")


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
    print("\n  * = default. Pass --embed-model <alias> or a full HF model name.")



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


def _classify_pdf(abs_path: Path) -> dict:
    """Classify a PDF file deterministically into one of:

        'missing'      — not on disk
        'wrong-format' — magic bytes say it's not a PDF (epub/zip/html…)
        'unreadable'   — pdfium can't open it (Data format error etc.)
        'scan'         — opens, but < SCAN_CHARS_PER_PAGE chars/page
        'ok'           — opens, has a real text layer

    Returns ``{category, pages, chars, cpp, real_format, error}``.
    Reads the file (magic bytes + real text via pypdfium2) — never the
    DB's possibly-stale total_chars.
    """
    from rtfm.core.handlers import SCAN_CHARS_PER_PAGE
    from rtfm.core.sniff import detect_real_format
    from rtfm.parsers.pdf import measure_pdf_text

    out = {"category": None, "pages": 0, "chars": 0, "cpp": 0.0,
           "real_format": None, "error": None}
    if not abs_path.is_file():
        out["category"] = "missing"
        return out

    fmt = detect_real_format(abs_path)
    out["real_format"] = fmt
    if fmt not in ("pdf", None):
        # A .pdf that is really an epub/zip/html/etc.
        out["category"] = "wrong-format"
        return out

    m = measure_pdf_text(abs_path)
    out["pages"], out["chars"] = m["pages"], m["chars"]
    out["cpp"], out["error"] = m["chars_per_page"], m["error"]
    if m["error"] is not None:
        out["category"] = "unreadable"
    elif m["chars_per_page"] < SCAN_CHARS_PER_PAGE:
        out["category"] = "scan"
    else:
        out["category"] = "ok"
    return out


def cmd_backfill_pages(args):
    """Re-ingest every PDF whose ``books.page_count`` is missing.

    Enqueues a P0 ingest job per PDF — the worker's ingest path runs the
    real PDF parser, which populates ``page_count`` and the scan signal
    deterministically. With ``ocr_fallback: true`` in config, scans will
    chain into P0/P3 OCR jobs automatically (no special path in this
    command anymore).
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("backfill-pages: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")

    roots = {r["corpus"]: r["root_path"]
             for r in conn.execute("SELECT corpus, root_path FROM sync_roots")}

    pdfs = conn.execute(
        """SELECT id, corpus, filename
           FROM books
           WHERE (filename LIKE '%.pdf' OR filename LIKE '%.PDF')
             AND (page_count IS NULL OR page_count = 0)"""
    ).fetchall()
    conn.close()
    print(f"PDFs missing page_count: {len(pdfs)}")

    if not pdfs:
        return

    payloads = []
    skipped_no_root = 0
    for b in pdfs:
        root = roots.get(b["corpus"])
        if not root:
            skipped_no_root += 1
            continue
        payloads.append({
            "root": root, "corpus": b["corpus"], "filepath": b["filename"],
        })

    if not payloads:
        print(f"  all {skipped_no_root} skipped (no sync root for corpus).")
        return

    queue = Queue(str(db_path))
    try:
        inserted, deduped = queue.enqueue_many(
            "ingest", payloads, priority=P_USER,
        )
        print(f"  queued {inserted} P0 ingest job(s)"
              + (f", {deduped} already pending" if deduped else "")
              + (f", {skipped_no_root} skipped (no sync root)"
                 if skipped_no_root else "")
              + ".")
        if inserted == 0:
            return
        ensure_worker_running(rtfm_dir)
        sys.exit(_watch_jobs(
            queue, set(),
            background=getattr(args, "background", False),
            label="backfill",
        ))
    finally:
        queue.close()


def cmd_gc(args):
    """Reconcile the index: purge orphan embeddings + re-queue
    un-embedded chunks.

    Enqueues a P0 ``reconcile`` job (carrying ``vacuum`` when ``--vacuum``
    is set) and watches the queue until it drains. The actual purge /
    requeue logic lives in :func:`rtfm.core.reconcile.reconcile`, called
    by the worker.
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("gc: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    queue = Queue(db_path)
    try:
        jid = queue.enqueue(
            "reconcile",
            {"vacuum": bool(getattr(args, "vacuum", False))},
            priority=P_USER,
        )
        if jid is None:
            print("gc: a reconcile job is already pending.")
        else:
            print(f"gc: P0 reconcile job #{jid} queued"
                  + (" (with vacuum)" if getattr(args, "vacuum", False) else "")
                  + ".")

        ensure_worker_running(rtfm_dir)
        rc = _watch_jobs(
            queue, {jid} if jid else set(),
            background=getattr(args, "background", False),
            label="gc",
        )

        # Report the final outcome from the queue itself.
        if not getattr(args, "background", False):
            failed = queue.list_failed(limit=5)
            recent_failed = [j for j in failed if j.type in ("reconcile", "vacuum", "embed")]
            if recent_failed:
                print("Recent failures:")
                for j in recent_failed:
                    err = (j.error or "").splitlines()[0][:120]
                    print(f"  #{j.id} {j.type}: {err}")
        sys.exit(rc)
    finally:
        queue.close()


def cmd_reindex(args):
    """Targeted re-ingestion after a parser change — by extension,
    corpus, or parser name.

    Why this exists: when a parser is improved (e.g. CSV went from
    "sample 8 rows" to "index everything" in 0.12.0), the affected
    files must be re-ingested — but their content hash hasn't changed,
    so a normal `rtfm sync` skips them, and `--force` would re-ingest
    *everything* (including a thousand PDFs mid-embed). This enqueues
    P1 ingest jobs **only** for the matching files, leaving the rest of
    the queue (and your in-flight PDF embeddings) untouched.

    Examples:
        rtfm reindex --ext csv,tsv,xlsx,sqlite,db   # after a tabular parser fix
        rtfm reindex --parser csv                   # same, by parser name
        rtfm reindex --ext pdf --corpus icm-bibliography
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("reindex: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    # Resolve the set of extensions to match.
    exts: set[str] = set()
    if getattr(args, "ext", None):
        for e in args.ext.split(","):
            e = e.strip().lower()
            if e:
                exts.add(e if e.startswith(".") else f".{e}")
    if getattr(args, "parser", None):
        # Map a parser name → its registered extensions.
        from rtfm.parsers.base import ParserRegistry
        pname = args.parser.strip().lower()
        for parser_cls in set(ParserRegistry.list_parsers().values()):
            if getattr(parser_cls, "name", "").lower() == pname:
                for e in getattr(parser_cls, "extensions", []):
                    exts.add(e.lower() if e.startswith(".") else f".{e.lower()}")
    if not exts and not getattr(args, "corpus", None):
        sys.exit("reindex: specify at least --ext, --parser, or --corpus.")

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    roots = {r["corpus"]: r["root_path"]
             for r in conn.execute("SELECT corpus, root_path FROM sync_roots")}

    # Build the query: books whose filename ends with a target extension,
    # optionally scoped to a corpus.
    where = []
    params: list = []
    if exts:
        ors = " OR ".join("LOWER(filename) LIKE ?" for _ in exts)
        where.append(f"({ors})")
        params.extend(f"%{e}" for e in exts)
    if getattr(args, "corpus", None):
        where.append("corpus = ?")
        params.append(args.corpus)
    sql = "SELECT corpus, filename FROM books"
    if where:
        sql += " WHERE " + " AND ".join(where)
    books = conn.execute(sql, params).fetchall()
    conn.close()

    if not books:
        print("reindex: no matching indexed files.")
        return

    queue = Queue(str(db_path))
    payloads = []
    skipped_no_root = 0
    for b in books:
        root = roots.get(b["corpus"])
        if not root:
            skipped_no_root += 1
            continue
        payloads.append({"root": root, "corpus": b["corpus"],
                         "filepath": b["filename"]})
    try:
        inserted, deduped = queue.enqueue_many(
            "ingest", payloads, priority=P_USER,
        )

        scope = []
        if exts:
            scope.append("ext " + ",".join(sorted(e.lstrip(".") for e in exts)))
        if getattr(args, "corpus", None):
            scope.append(f"corpus {args.corpus}")
        print(f"reindex ({'; '.join(scope)}): {len(books)} matching file(s), "
              f"{inserted} P0 ingest job(s) queued"
              + (f", {deduped} already pending" if deduped else "")
              + (f", {skipped_no_root} skipped (no sync root)" if skipped_no_root else "")
              + ".")
        if inserted == 0:
            return

        ensure_worker_running(rtfm_dir)
        # We don't track the ids per-row (enqueue_many returns counts),
        # but watching the whole queue is fine — reindex is intentionally
        # the only producer in this command.
        sys.exit(_watch_jobs(
            queue, set(),
            background=getattr(args, "background", False),
            label="reindex",
        ))
    finally:
        queue.close()


def cmd_vacuum(args):
    """Enqueue a P0 vacuum job (rebuilds the SQLite DB to reclaim space
    from deleted rows) and watch until it drains. Reports the file size
    before/after via the worker log.
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("vacuum: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    before_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0.0
    queue = Queue(db_path)
    try:
        jid = queue.enqueue(
            "vacuum", {"reason": "explicit-cli"}, priority=P_USER,
        )
        if jid is None:
            print("vacuum: a vacuum job is already pending.")
        else:
            print(f"vacuum: P0 job #{jid} queued. DB size before: "
                  f"{before_mb:.1f} MB.")

        ensure_worker_running(rtfm_dir)
        rc = _watch_jobs(
            queue, {jid} if jid else set(),
            background=getattr(args, "background", False),
            label="vacuum",
        )
        if not getattr(args, "background", False):
            after_mb = (db_path.stat().st_size / (1024 * 1024)
                        if db_path.exists() else 0.0)
            print(f"DB size after: {after_mb:.1f} MB "
                  f"(reclaimed {before_mb - after_mb:+.1f} MB).")
        sys.exit(rc)
    finally:
        queue.close()


def cmd_doctor(args):
    """Trigger a full pass over the project: P0 scan(s) + P0 reconcile,
    then watch the queue until drained.

    Also prints a diagnostic report of every indexed PDF (ok / scan /
    unreadable / wrong-format) so the user knows what the worker will
    fix on its own (scans → OCR via ``ocr_fallback`` heuristic) and what
    needs manual attention (wrong-format, unreadable).

    Use ``--background`` to enqueue and return immediately.
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.handlers import SCAN_CHARS_PER_PAGE
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("doctor: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    # --- Diagnostic report (read-only) ---
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    roots = {r["corpus"]: r["root_path"]
             for r in conn.execute("SELECT corpus, root_path FROM sync_roots")}

    pdfs = conn.execute(
        """SELECT corpus, filename FROM books
           WHERE filename LIKE '%.pdf' OR filename LIKE '%.PDF'
           ORDER BY corpus, filename"""
    ).fetchall()
    if pdfs:
        print(f"Diagnosing {len(pdfs)} indexed PDFs (reading real text)...\n")
        cats: dict[str, list] = {"ok": [], "scan": [], "unreadable": [],
                                 "wrong-format": [], "missing": []}
        for b in pdfs:
            root = roots.get(b["corpus"])
            if not root:
                cats["missing"].append((b["corpus"], b["filename"], None))
                continue
            info = _classify_pdf(Path(root) / b["filename"])
            cats[info["category"]].append((b["corpus"], b["filename"], info))

        print("=== PDF summary ===")
        print(f"  ok (has text layer) : {len(cats['ok'])}")
        print(f"  scan (need OCR)     : {len(cats['scan'])}")
        print(f"  unreadable (corrupt): {len(cats['unreadable'])}")
        print(f"  wrong-format        : {len(cats['wrong-format'])}")
        print(f"  missing on disk     : {len(cats['missing'])}")

        if cats["wrong-format"]:
            print("\n=== Wrong-format (not really PDF — OCR won't help) ===")
            for corpus, fn, info in cats["wrong-format"][:30]:
                print(f"  [{corpus:<16}] {info['real_format']:<6} {fn[:55]}")
            print("  → rename these manually so a future sync picks the right parser.")

        if cats["unreadable"]:
            print("\n=== Unreadable (pdfium can't open — re-acquire source) ===")
            for corpus, fn, info in cats["unreadable"][:30]:
                print(f"  [{corpus:<16}] {fn[:60]}")

        if cats["scan"]:
            print(f"\n=== Scans (< {SCAN_CHARS_PER_PAGE} c/p, readable) ===")
            for corpus, fn, info in sorted(cats["scan"], key=lambda x: x[2]["cpp"])[:40]:
                print(f"  [{corpus:<16}] {info['cpp']:4.1f}c/p {info['pages']:4}p  {fn[:48]}")
            if len(cats["scan"]) > 40:
                print(f"  ... +{len(cats['scan']) - 40} more")
            print("  → the worker auto-enqueues OCR for these when "
                  "ocr_fallback=true (`rtfm sync --ocr` to enable).")
    conn.close()

    # --- Trigger a full pass via the queue ---
    print("\nEnqueuing P0 scan(s) + P0 reconcile...")
    sources = _resolve_sources(rtfm_root, args)
    queue = Queue(db_path)
    try:
        enqueued: set[int] = set()
        for src in sources:
            src_path = Path(src.get("path", ".")).resolve()
            src_corpus = src.get("corpus", "default")
            if not src_path.is_dir():
                continue
            payload: dict = {"root": str(src_path), "corpus": src_corpus,
                             "force_remove": False}
            if src.get("extensions"):
                payload["extensions"] = src["extensions"]
            jid = queue.enqueue("scan", payload, priority=P_USER)
            if jid is not None:
                enqueued.add(jid)
        jid = queue.enqueue("reconcile", {}, priority=P_USER)
        if jid is not None:
            enqueued.add(jid)
        print(f"  {len(enqueued)} P0 job(s) queued.")

        ensure_worker_running(rtfm_dir)
        sys.exit(_watch_jobs(
            queue, enqueued,
            background=getattr(args, "background", False),
            label="doctor",
        ))
    finally:
        queue.close()


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
        print("\nIndexed files: 0")

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

    # OCR daemon status (cheap: one JSON read + a kill -0 syscall).
    # Always shown when present so the user knows a long OCR is in
    # flight or that a previous one died.
    try:
        from rtfm.config import find_rtfm_root
        from rtfm.core.ocr_daemon import (
            read_state, pid_alive, format_progress,
        )
        _root_for_ocr = find_rtfm_root()
        if _root_for_ocr is not None:
            _ocr_state = read_state(_root_for_ocr / ".rtfm")
            if _ocr_state is not None:
                if _ocr_state.status == "running" and not pid_alive(_ocr_state.pid):
                    # Daemon died without cleaning up. Promote to "crashed"
                    # so the message is accurate without rewriting state.
                    _ocr_state.status = "crashed"
                print("\nOCR daemon:")
                for line in format_progress(_ocr_state).splitlines():
                    print(f"  {line}")
    except Exception:
        pass  # best-effort

    # Priority-queue worker (0.10.0+). Shown only when relevant: a worker
    # is running OR there are pending/failed jobs OR the queue table
    # exists with rows. Stays silent on a vanilla project that never
    # used the queue path.
    try:
        from rtfm.config import find_rtfm_root as _frr
        from rtfm.core.worker import worker_running as _wr
        from rtfm.core.queue import Queue as _Q
        _root_for_worker = _frr()
        if _root_for_worker is not None:
            _rtfm_dir = _root_for_worker / ".rtfm"
            _wstate = _wr(_rtfm_dir)
            # Queue stats (cheap; reads from the same library.db)
            _q = _Q(str(_rtfm_dir / "library.db"))
            try:
                _qstats = _q.stats()
            finally:
                _q.close()

            _has_active = _wstate is not None
            _has_pending = any(
                _qstats.get(t, {}).get("pending", 0) for t in ("ingest", "embed", "ocr")
            )
            _has_failed = any(
                _qstats.get(t, {}).get("failed", 0) for t in ("ingest", "embed", "ocr")
            )

            if _has_active or _has_pending or _has_failed:
                print("\nWorker / Queue:")
                if _wstate:
                    line = f"  worker:  running (PID {_wstate.pid}, {_wstate.status})"
                    print(line)
                    if _wstate.current_job_id is not None:
                        _payload = _wstate.current_job_payload or {}
                        _fp = _payload.get("filepath") or _payload.get("chunk_ids")
                        _detail = f" — {_fp}" if _fp else ""
                        if isinstance(_fp, list):
                            _detail = f" — {len(_fp)} chunk(s)"
                        print(f"           job #{_wstate.current_job_id} "
                              f"[{_wstate.current_job_type}]{_detail}")
                    print(f"           {_wstate.jobs_done} done, "
                          f"{_wstate.jobs_failed} failed since "
                          f"{_wstate.started_at}")
                else:
                    print("  worker:  not running"
                          + (" — run `rtfm worker start` (or any `rtfm sync`)"
                             if _has_pending else ""))
                # Compact per-type breakdown (only types with rows)
                for _t in ("ingest", "embed", "ocr"):
                    _b = _qstats.get(_t)
                    if not _b:
                        continue
                    _parts = [f"{s}={n}" for s, n in sorted(_b.items())]
                    print(f"  {_t:<8} {' '.join(_parts)}")
    except Exception:
        pass  # best-effort

    # Index health. Always cheap by default — just a JSON read for known
    # scan suspects. Pending-sync counts are opt-in via --health because
    # stat()-ing every tracked file is fine on a local repo but can take
    # tens of seconds per source on NTFS-via-WSL or network shares.
    try:
        from rtfm.config import find_rtfm_root, load_config
        root = find_rtfm_root()
        if root:
            health_flag = getattr(args, "health", False)
            seen_scans = []
            scans_file = root / ".rtfm" / "seen_scans.json"
            if scans_file.exists():
                try:
                    seen_scans = json.loads(scans_file.read_text())
                except Exception:
                    pass

            if seen_scans or health_flag:
                print("\nIndex health:")

            if health_flag:
                from rtfm.core.sync import quick_diff
                cfg = load_config(root)
                sources = cfg.get("sources") or [
                    {"path": str(root), "corpus": cfg.get("corpus", "default")}
                ]
                pending_added = pending_modified = pending_removed = 0
                print("  (scanning sources, may take a moment)...")
                for src in sources:
                    src_path = Path(src.get("path", ".")).resolve()
                    src_corpus = src.get("corpus", "default")
                    ext_set = None
                    if src.get("extensions"):
                        ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                                   for e in src["extensions"].split(",")}
                    try:
                        qd = quick_diff(
                            library=lib, root=src_path, corpus=src_corpus,
                            extensions=ext_set,
                        )
                        pending_added += len(qd.added)
                        pending_modified += len(qd.modified)
                        pending_removed += len(qd.removed)
                    except Exception:
                        pass

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

            if not health_flag:
                print("\n(Run `rtfm status --health` for pending-sync counts.)")
    except Exception:
        pass  # health section is best-effort

    lib.close()


def cmd_ocr_worker(args):
    """Removed in 0.16.x — the OCR pass is now part of the unified
    worker queue (P0 scan + P3 OCR jobs). Kept as a stub so that any
    stale invocation prints a clear message instead of crashing.
    """
    sys.exit(
        "ocr-worker has been retired in 0.16.x. Use:\n"
        "  rtfm sync --ocr      # persists ocr_fallback + re-queues scans\n"
        "  rtfm worker status   # watch progress"
    )


def _print_health_warnings(result, ocr_already_on: bool = False) -> None:
    """Format scan/empty-file warnings from a legacy ``SyncResult``.

    No longer called by ``cmd_sync`` (sync is queue-driven and the
    worker's scan/ingest handlers maintain ``seen_scans.json`` on their
    own), but kept as a pure helper so :mod:`test_sync_health` and any
    other consumer of the legacy ``sync()`` return value can still
    format the report identically.
    """
    if result.suspect_scans:
        print()
        print(f"⚠ {len(result.suspect_scans)} PDF probablement scannés "
              f"(0 texte extrait) :")
        for path in result.suspect_scans[:10]:
            print(f"    - {path}")
        if len(result.suspect_scans) > 10:
            print(f"    ... et {len(result.suspect_scans) - 10} autre(s)")
        if ocr_already_on:
            print("  → marker n'a pas pu en extraire de texte non plus "
                  "(PDF corrompu / pages vides).")
        else:
            print("  → activer l'OCR automatique :  rtfm sync --ocr")
            print("    (commande à lancer UNE FOIS — les syncs suivantes "
                  "OCR-isent automatiquement les nouveaux scans)")
    if result.empty_files:
        print()
        print(f"⚠ {len(result.empty_files)} fichier(s) sans contenu extrait :")
        for path in result.empty_files[:10]:
            print(f"    - {path}")
        if len(result.empty_files) > 10:
            print(f"    ... et {len(result.empty_files) - 10} autre(s)")


def _resolve_sources(rtfm_root: Path, args) -> list[dict]:
    """Pick the right ``sources`` list for a sync run.

    Honours an explicit ``--path`` / ``--corpus`` / ``--extensions`` on
    the CLI; otherwise falls back to ``.rtfm/config.json``.
    """
    from rtfm.config import load_config

    explicit_path = getattr(args, "path", None)
    explicit_corpus = getattr(args, "corpus", None)
    explicit_ext = getattr(args, "extensions", None)
    if explicit_path or explicit_corpus or explicit_ext:
        return [{
            "path": str(Path(explicit_path or ".").resolve()),
            "corpus": explicit_corpus or "default",
            "extensions": explicit_ext,
        }]

    cfg = load_config(rtfm_root)
    sources = cfg.get("sources") or [
        {"path": str(rtfm_root), "corpus": cfg.get("corpus", "default")}
    ]
    return sources


def _enqueue_sync_ocr(args) -> int:
    """``rtfm sync --ocr`` — persist ``ocr_fallback: true`` in config,
    enqueue a P0 OCR job for every previously-flagged scan, ensure the
    worker is up, then watch progress. Replaces the old detached
    ``ocr-worker`` daemon.
    """
    from rtfm.config import find_rtfm_root, load_config, save_config
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("rtfm sync --ocr requires a .rtfm/ project root. "
                 "Run `rtfm init` first.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    # 1. Persist the toggle. Idempotent.
    cfg = load_config(rtfm_root)
    if not cfg.get("ocr_fallback"):
        cfg["ocr_fallback"] = True
        save_config(rtfm_root, cfg)
        print("ocr_fallback: true persisted in .rtfm/config.json.")
    else:
        print("ocr_fallback already enabled — re-queuing known scans.")

    # 2. Re-enqueue every PDF flagged as a scan.
    seen_path = rtfm_dir / "seen_scans.json"
    known: list[str] = []
    if seen_path.exists():
        try:
            known = json.loads(seen_path.read_text(encoding="utf-8"))
        except Exception:
            known = []

    if not known:
        print("\nNo previously-flagged scans in .rtfm/seen_scans.json.")
        print("Run `rtfm sync` first — P1 will flag scans as it sees them.")
        return 0

    sources = cfg.get("sources") or [
        {"path": str(rtfm_root), "corpus": cfg.get("corpus", "default")}
    ]
    sources_resolved = [
        (Path(s.get("path", ".")).resolve(),
         s.get("corpus", cfg.get("corpus", "default")))
        for s in sources
    ]

    queue = Queue(db_path)
    enqueued_ids: set[int] = set()
    unmatched = 0
    try:
        for rel in known:
            matched = False
            for root, corpus in sources_resolved:
                candidate = root / rel
                if candidate.is_file():
                    rel_to_root = str(candidate.relative_to(root))
                    jid = queue.enqueue(
                        "ocr",
                        {"root": str(root), "corpus": corpus,
                         "filepath": rel_to_root},
                        priority=P_USER,
                    )
                    if jid is not None:
                        enqueued_ids.add(jid)
                    matched = True
                    break
            if not matched:
                unmatched += 1

        print(f"\nQueued {len(enqueued_ids)} P0 OCR job(s)"
              + (f", {unmatched} unmatched (file gone?)" if unmatched else "")
              + ".")
        if not enqueued_ids and not getattr(args, "background", False):
            return 0

        ensure_worker_running(rtfm_dir)
        return _watch_jobs(
            queue, enqueued_ids,
            background=getattr(args, "background", False),
            label="ocr",
        )
    finally:
        queue.close()


def cmd_sync(args):
    """Sync files into the library.

    Enqueues a P0 scan job for every configured source (or a P0 ingest
    job per file under ``--files``), ensures the worker daemon is alive,
    then polls queue stats until the work has drained. Use
    ``--background`` to return as soon as the jobs are enqueued.
    """
    from rtfm.config import find_rtfm_root
    from rtfm.core.queue import Queue, P_USER
    from rtfm.cli_worker import ensure_worker_running

    # --ocr takes its own dedicated path (persist flag + re-queue scans).
    if getattr(args, "ocr", False):
        rc = _enqueue_sync_ocr(args)
        sys.exit(rc)

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("rtfm sync: no .rtfm/ project root in the cwd chain. "
                 "Run `rtfm init` first.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    dry_run = bool(getattr(args, "dry_run", False))
    background = bool(getattr(args, "background", False))
    force_remove = bool(getattr(args, "force_remove", False))
    files = getattr(args, "files", None) or None

    # --files: targeted ingest of specific paths, no scan.
    if files:
        sources = _resolve_sources(rtfm_root, args)
        # Pick the single source to anchor the relative paths.
        src = sources[0]
        src_path = Path(src["path"]).resolve()
        src_corpus = src.get("corpus", "default")

        payloads = []
        for fp in files:
            fpath = Path(fp).resolve()
            try:
                rel = str(fpath.relative_to(src_path))
            except ValueError:
                rel = str(fpath)
            payloads.append({
                "root": str(src_path), "corpus": src_corpus, "filepath": rel,
            })

        if dry_run:
            print(f"[dry-run] would enqueue {len(payloads)} P0 ingest job(s):")
            for p in payloads:
                print(f"  [{p['corpus']}] {p['filepath']}")
            return

        queue = Queue(db_path)
        try:
            enqueued_ids: set[int] = set()
            for p in payloads:
                jid = queue.enqueue("ingest", p, priority=P_USER)
                if jid is not None:
                    enqueued_ids.add(jid)
            print(f"Queued {len(enqueued_ids)} P0 ingest job(s).")
            if not enqueued_ids and not background:
                return
            ensure_worker_running(rtfm_dir)
            sys.exit(_watch_jobs(
                queue, enqueued_ids,
                background=background, label="ingest",
            ))
        finally:
            queue.close()
        return

    # Default: one P0 scan job per configured source.
    sources = _resolve_sources(rtfm_root, args)
    scan_payloads: list[dict] = []
    for src in sources:
        src_path = Path(src.get("path", ".")).resolve()
        src_corpus = src.get("corpus", "default")
        if not src_path.is_dir():
            print(f"  ! [{src_corpus}] {src_path} (path missing — skipped)")
            continue
        payload: dict = {
            "root": str(src_path),
            "corpus": src_corpus,
            "force_remove": force_remove,
        }
        if src.get("extensions"):
            payload["extensions"] = src["extensions"]
        scan_payloads.append(payload)

    if not scan_payloads:
        print("rtfm sync: nothing to do (no valid source).")
        return

    if dry_run:
        print(f"[dry-run] would enqueue {len(scan_payloads)} P0 scan job(s):")
        for p in scan_payloads:
            ext = f"  ext={p['extensions']}" if p.get("extensions") else ""
            print(f"  [{p['corpus']}] {p['root']}{ext}")
        return

    queue = Queue(db_path)
    try:
        enqueued_ids = set()
        for p in scan_payloads:
            jid = queue.enqueue("scan", p, priority=P_USER)
            if jid is not None:
                enqueued_ids.add(jid)
        print(f"Queued {len(enqueued_ids)} P0 scan job(s) "
              f"({len(scan_payloads) - len(enqueued_ids)} already pending).")
        ensure_worker_running(rtfm_dir)
        sys.exit(_watch_jobs(
            queue, enqueued_ids,
            background=background, label="sync",
        ))
    finally:
        queue.close()


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

    NOTE: this command still calls :func:`rtfm.core.sync.sync` directly
    because the global memory DB has no ``.rtfm/`` project root and
    therefore no worker daemon to drain a queue. The queue-based path
    used by every other CLI command would have nowhere to enqueue to.
    """
    from rtfm.core import sync as _sync_module
    sync = _sync_module.sync

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
    p_embed.add_argument("--force", action="store_true", help="Re-generate all embeddings (implies --inline)")
    p_embed.add_argument(
        "--inline", action="store_true",
        help="Run embedding in-process and block until done (legacy "
             "0.9.x behaviour). The default is to enqueue P2 batches "
             "and let the worker daemon drain them in the background.",
    )
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
    p_status.add_argument(
        "--health", action="store_true",
        help="Also compute pending-sync counts. Can be slow on big or remote "
             "(NTFS over WSL, network) corpora — each source is stat()-ed.",
    )
    p_status.set_defaults(func=cmd_status)

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync files into the library", parents=[db_parent])
    p_sync.add_argument("path", nargs="?", default=None, help="Directory to sync (auto: all sources from config)")
    p_sync.add_argument("--corpus", "-c", default=None, help="Corpus name (auto: from config)")
    p_sync.add_argument("--extensions", "-e", help="Comma-separated extensions (e.g. md,py,pdf)")
    p_sync.add_argument("--dry-run", action="store_true",
                        help="Print what would be enqueued, but do not queue anything.")
    p_sync.add_argument("--no-embeddings", action="store_true",
                        help=argparse.SUPPRESS)  # kept for back-compat; the worker manages embeds
    p_sync.add_argument("--force", action="store_true",
                        help=argparse.SUPPRESS)  # back-compat no-op (the scan handler diffs by hash)
    p_sync.add_argument(
        "--force-remove", action="store_true",
        help="Override the mass-removal circuit breaker (scan jobs refuse "
             "to delete a large fraction of a corpus in one pass — sign of "
             "an incomplete scan). Use for deliberate bulk deletes.")
    p_sync.add_argument("--files", nargs="+",
                        help="Specific files to ingest (for git/Claude hooks). "
                             "Enqueues P0 ingest jobs instead of a scan.")
    p_sync.add_argument(
        "--ocr", action="store_true",
        help="Persist ocr_fallback=true in .rtfm/config.json and re-queue "
             "every previously-flagged scan as a P0 OCR job. The worker "
             "auto-enqueues OCR for fresh scans on subsequent syncs.",
    )
    p_sync.add_argument(
        "--progress-every", type=float, default=None, metavar="SECONDS",
        help=argparse.SUPPRESS,  # legacy — kept so old invocations don't break
    )
    p_sync.add_argument(
        "--background", action="store_true",
        help="Enqueue and return immediately. Default: poll queue stats "
             "until the work has drained.",
    )
    p_sync.set_defaults(func=cmd_sync)

    # ocr-worker (internal — invoked by `rtfm sync --ocr` as a detached
    # subprocess, not meant for direct use). Hidden from --help.
    p_worker = subparsers.add_parser(
        "ocr-worker", help=argparse.SUPPRESS, parents=[db_parent]
    )
    p_worker.set_defaults(func=cmd_ocr_worker)

    # worker — the priority-queue daemon (0.10.0+).
    # Producers (rtfm sync, hooks) enqueue jobs; this single process
    # drains them AND, while idle, periodically re-scans configured
    # sources to enqueue P1 ingest jobs (the old standalone watcher's
    # job, folded in at 0.10.4 per the "one consumer process" rule).
    from rtfm.cli_worker import cmd_worker, cmd_worker_daemon, cmd_queue
    p_w = subparsers.add_parser(
        "worker",
        help="Start/stop/inspect the RTFM background worker "
             "(priority queue + idle scan)",
    )
    p_w.add_argument(
        "action", nargs="?", choices=["start", "stop", "status"],
        default="status",
        help="start: spawn a detached worker. stop: SIGTERM the worker. "
             "status (default): report on the running worker.",
    )
    p_w.add_argument(
        "--scan-interval", type=float, default=None, metavar="SECONDS",
        help="How often (idle) the worker re-scans sources for new files. "
             "Default 30s.",
    )
    p_w.set_defaults(func=cmd_worker)

    # worker-daemon (hidden — invoked by ensure_worker_running()).
    p_wd = subparsers.add_parser("worker-daemon", help=argparse.SUPPRESS)
    p_wd.add_argument("--scan-interval", type=float, default=None)
    p_wd.set_defaults(func=cmd_worker_daemon)

    # queue — inspect / manage the work queue.
    p_q = subparsers.add_parser(
        "queue",
        help="Inspect or manage the work queue (stats / list / failed / "
             "clear-done / retry-failed)",
    )
    p_q.add_argument(
        "action", nargs="?",
        choices=["stats", "list", "failed", "clear-done", "retry-failed"],
        default="stats",
    )
    p_q.add_argument("--limit", type=int, default=20,
                     help="Max rows for list/failed (default 20).")
    p_q.add_argument("--keep", type=int, default=100,
                     help="Rows to keep when clear-done (default 100).")
    p_q.set_defaults(func=cmd_queue)

    # backfill-pages — re-ingest PDFs missing books.page_count.
    p_bp = subparsers.add_parser(
        "backfill-pages",
        help="Re-ingest indexed PDFs whose page_count is missing (enqueues "
             "P0 ingest jobs; OCR is auto-chained when ocr_fallback=true).",
    )
    p_bp.add_argument("--background", action="store_true",
                      help="Enqueue and return immediately.")
    p_bp.set_defaults(func=cmd_backfill_pages)

    # doctor — diagnostic + full P0 pass (scan + reconcile).
    p_doc = subparsers.add_parser(
        "doctor",
        help="Report on indexed PDFs (scan/corrupt/mislabeled) and trigger a "
             "full P0 pass: scan every source + reconcile.",
    )
    p_doc.add_argument("--background", action="store_true",
                       help="Enqueue and return immediately.")
    p_doc.set_defaults(func=cmd_doctor)

    # reindex — targeted re-ingestion after a parser change.
    p_re = subparsers.add_parser(
        "reindex",
        help="Re-ingest only files of a given category (extension / parser / "
             "corpus) — e.g. after a parser improvement. Leaves everything "
             "else (and in-flight embeds) untouched.",
    )
    p_re.add_argument("--ext", help="Comma-separated extensions, e.g. csv,tsv,xlsx,sqlite,db")
    p_re.add_argument("--parser", help="Re-ingest files handled by this parser (e.g. csv)")
    p_re.add_argument("--corpus", "-c", help="Limit to this corpus")
    p_re.add_argument("--background", action="store_true",
                      help="Enqueue and return immediately.")
    p_re.set_defaults(func=cmd_reindex)

    # gc — reconcile the index (purge orphan embeddings, re-queue
    # un-embedded chunks). Same logic the worker runs while idle.
    p_gc = subparsers.add_parser(
        "gc",
        help="Reconcile the index: purge orphan embeddings + re-queue "
             "chunks missing an embedding.",
    )
    p_gc.add_argument("--vacuum", action="store_true",
                      help="Also enqueue a VACUUM after reconciliation.")
    p_gc.add_argument("--background", action="store_true",
                      help="Enqueue and return immediately.")
    p_gc.set_defaults(func=cmd_gc)

    # vacuum — explicit VACUUM to reclaim space.
    p_vac = subparsers.add_parser(
        "vacuum",
        help="Run VACUUM on the library DB to reclaim free pages.",
    )
    p_vac.add_argument("--background", action="store_true",
                       help="Enqueue and return immediately.")
    p_vac.set_defaults(func=cmd_vacuum)

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
