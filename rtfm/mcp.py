"""MCP server for rtfm — exposes search, sync, and tagging tools.

Run with::

    python -m rtfm.mcp

Or register in Claude Code::

    claude mcp add rtfm -- python -m rtfm.mcp

Environment variables:
    RTFM_DB  — path to the SQLite database (default: library.db)
"""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from rtfm.log import log

mcp = FastMCP("rtfm")


# ── Progressive disclosure helpers ───────────────────────────────────────

def _deduplicate_by_source(results, limit: int):
    """Keep only the best chunk per unique source (book_slug).

    Returns a list of dicts with best result, chunk count, and metadata,
    sorted by score, limited to *limit* unique sources.
    """
    seen: dict[str, dict] = {}  # book_slug -> {best, count}
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


def _resolve_abs_path(filepath: str, corpus: str) -> str:
    """Resolve a relative filepath to absolute using stored sync root."""
    if not filepath:
        return ""
    if os.path.isabs(filepath):
        return filepath
    try:
        lib = _get_library()
        root = lib.get_sync_root(corpus)
        if root:
            abs_path = os.path.join(root, filepath)
            if os.path.exists(abs_path):
                return abs_path
    except Exception:
        pass
    return filepath


def _format_source_line(r, count: int, slug: str) -> str:
    """Format a single source as a compact metadata line.

    Level 0: metadata only — title, score, chunk count, lang, absolute file path.
    No content preview. Agent uses Read(file_path) to get content.
    """
    filepath = r.chunk.book_file or ""

    # lang and corpus come from book metadata
    lang = ""
    corpus = ""
    try:
        lib = _get_library()
        conn = lib._get_conn()
        import json as _json
        row = conn.execute("SELECT metadata, corpus FROM books WHERE slug = ?", (slug,)).fetchone()
        if row:
            corpus = row["corpus"] or ""
            if row["metadata"]:
                book_meta = _json.loads(row["metadata"])
                lang = book_meta.get("lang", "")
    except Exception:
        pass

    # Resolve to absolute path so agent can Read directly
    if filepath:
        filepath = _resolve_abs_path(filepath, corpus)

    parts = [f"{r.source} ({r.page})"]
    parts.append(f"score: {r.score:.3f}")
    parts.append(f"{count} chunks")
    if lang:
        parts.append(f"lang: {lang}")

    if filepath:
        parts.append(f"file: {filepath}")
    else:
        parts.append(f"slug: {slug}")

    return " — ".join(parts)



# ── Library singleton ─────────────────────────────────────────────────────

_library = None
_embed_lock = threading.Lock()


def _get_library():
    """Return (and lazily create) the Library singleton."""
    global _library
    if _library is None:
        from rtfm.core.library import Library
        db_path = os.environ.get("RTFM_DB")
        if not db_path:
            from rtfm.config import resolve_db
            db_path = resolve_db()
        _library = Library(db_path)
    return _library


def _embed_in_background(corpus: str | None = None):
    """Run embedding generation in a background thread.

    Uses the cached MiniLM model (loaded once, stays in memory).
    Thread-safe via _embed_lock — concurrent calls are skipped.
    """
    if not _embed_lock.acquire(blocking=False):
        return  # Another embed is already running

    def _run():
        try:
            lib = _get_library()
            lib.generate_embeddings(corpus=corpus, show_progress=False)
        except Exception:
            pass  # Non-critical — FTS search still works
        finally:
            _embed_lock.release()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# ── Read tools ────────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_search(
    query: str,
    limit: int = 5,
    corpus: str | None = None,
    search_type: str = "fts",
) -> str:
    """Search the knowledge base. Returns metadata only — no content.

    Like a search engine results page: shows which sources are relevant.
    Use rtfm_expand(source) to read the actual content.

    Args:
        query: The search query.
        limit: Maximum number of unique sources to return (default 5).
        corpus: Filter by corpus name (optional).
        search_type: One of "fts", "semantic", or "hybrid" (default "fts").
    """
    t0 = time.time()
    lib = _get_library()

    # Overfetch to ensure enough unique sources after dedup
    fetch_limit = limit * 5

    try:
        if search_type == "semantic":
            results = lib.semantic_search(query, limit=fetch_limit, corpus=corpus)
        elif search_type == "fts":
            results = lib.search(query, limit=fetch_limit, corpus=corpus)
        else:
            results = lib.hybrid_search(query, limit=fetch_limit, corpus=corpus)
    except Exception:
        results = lib.search(query, limit=fetch_limit, corpus=corpus)

    elapsed = time.time() - t0

    if not results:
        log("search", f"query={query!r} type={search_type} results=0 time={elapsed:.3f}s")
        return f"No results found for: {query}"

    # Deduplicate: 1 best chunk per source
    deduped = _deduplicate_by_source(results, limit)
    log("search", f"query={query!r} type={search_type} sources={len(deduped)}/{results.total_found} time={elapsed:.3f}s")

    # Metadata-only output — no content, minimal tokens
    lines = [f"Found {len(deduped)} sources for \"{query}\":\n"]
    for rank, entry in enumerate(deduped, 1):
        r = entry["best"]
        count = entry["count"]
        slug = r.chunk.book_slug
        lines.append(f"[{rank}] {_format_source_line(r, count, slug)}")

    return "\n".join(lines)


@mcp.tool()
def rtfm_stats() -> str:
    """Get library statistics: total chunks, books, corpora, tag and embedding coverage."""
    log("stats", "called")
    lib = _get_library()
    stats = lib.get_stats()

    lines = [
        f"Books:         {stats['books']}",
        f"Chunks:        {stats['chunks']}",
        f"Total chars:   {stats['total_chars']:,}",
        f"Tagged chunks: {stats['tagged_chunks']}",
        f"Corpora:       {stats['corpora']}",
    ]

    try:
        emb = lib.get_embedding_stats()
        lines.append(f"Embeddings:    {emb['embedded']} ({emb['coverage']})")
    except Exception:
        pass

    return "\n".join(lines)


@mcp.tool()
def rtfm_tags(corpus: str | None = None) -> str:
    """List all tags in the library, optionally filtered by corpus.

    Args:
        corpus: Filter by corpus name (optional).
    """
    log("tags", f"corpus={corpus!r}")
    lib = _get_library()
    tags = lib.list_tags(corpus=corpus)
    if not tags:
        return "No tags found."
    lines = [f"{t['tag']}: {t['count']} chunks" for t in tags]
    return "\n".join(lines)


@mcp.tool()
def rtfm_books(
    corpus: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List indexed books/documents with pagination.

    Returns a per-corpus summary, then books from `offset` to `offset + limit`.
    Call again with a higher `offset` to paginate through all books.

    Args:
        corpus: Filter by corpus name (optional).
        limit: Max books per page (default 50). Set 0 for all.
        offset: Number of books to skip (default 0). Use for pagination.
    """
    log("books", f"corpus={corpus!r} limit={limit} offset={offset}")
    lib = _get_library()
    books = lib.list_books(corpus=corpus)
    if not books:
        return "No books indexed."

    # Per-corpus summary
    corpus_counts: dict[str, int] = {}
    for b in books:
        c = b.get("corpus", "default")
        corpus_counts[c] = corpus_counts.get(c, 0) + 1
    summary_lines = [f"Total: {len(books)} books across {len(corpus_counts)} corpus(es)"]
    for c, count in sorted(corpus_counts.items()):
        summary_lines.append(f"  [{c}] {count} books")

    # Paginated book listing
    if limit == 0:
        page = books[offset:]
    else:
        page = books[offset : offset + limit]
    book_lines = []
    if offset > 0:
        book_lines.append(f"(showing from #{offset + 1})")
    for b in page:
        prefix = f"[{b['corpus']}] " if b.get("corpus") else ""
        book_lines.append(f"{prefix}{b['title']}: {b['chunk_count']} chunks")
    remaining = len(books) - offset - len(page)
    if remaining > 0:
        next_offset = offset + len(page)
        book_lines.append(f"... {remaining} more. Use offset={next_offset} to see next page.")

    return "\n".join(summary_lines + [""] + book_lines)


# ── Write tools ───────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_sync(
    path: str = ".",
    corpus: str = "default",
    extensions: str | None = None,
) -> str:
    """Sync a directory into the library. Only processes changed files.

    Args:
        path: Directory to sync (default: current directory).
        corpus: Corpus name for indexed documents (default: "default").
        extensions: Comma-separated file extensions to include (e.g. "md,py,pdf").
    """
    t0 = time.time()
    log("sync", f"path={path!r} corpus={corpus!r} ext={extensions!r}")
    lib = _get_library()

    ext_set = None
    if extensions:
        ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                   for e in extensions.split(",")}

    result = lib.sync(
        root=Path(path),
        corpus=corpus,
        extensions=ext_set,
        generate_embeddings=False,  # Embeddings run in background thread
    )

    elapsed = time.time() - t0
    log("sync", f"+{result.added} ~{result.modified} -{result.removed} ={result.unchanged} time={elapsed:.3f}s")

    # Trigger background embeddings if new chunks were added
    if result.added or result.modified:
        _embed_in_background(corpus=corpus)
        log("embed", f"triggered background embeddings for corpus={corpus!r}")

    return (
        f"Sync complete: +{result.added} added, ~{result.modified} modified, "
        f"-{result.removed} removed, ={result.unchanged} unchanged"
        + (f"\nErrors: {result.errors}" if result.errors else "")
    )


@mcp.tool()
def rtfm_ingest(path: str, corpus: str = "default") -> str:
    """Ingest a single file into the library.

    Args:
        path: Path to the file to ingest.
        corpus: Corpus name (default: "default").
    """
    log("ingest", f"path={path!r} corpus={corpus!r}")
    lib = _get_library()
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"

    try:
        stats = lib.ingest(p, corpus=corpus)
        _embed_in_background(corpus=corpus)
        log("ingest", f"{p.name}: {stats['chunks']} chunks, {stats['chars']:,} chars")
        return f"Ingested {p.name}: {stats['chunks']} chunks, {stats['chars']:,} chars"
    except Exception as exc:
        log("ingest", f"ERROR: {exc}")
        return f"Error ingesting {path}: {exc}"


@mcp.tool()
def rtfm_tag_chunks(chunk_ids: str, tags: str) -> str:
    """Add tags to specific chunks.

    Args:
        chunk_ids: Comma-separated chunk IDs to tag.
        tags: Comma-separated tags to add.
    """
    log("tag", f"chunks={chunk_ids!r} tags={tags!r}")
    lib = _get_library()

    ids = [c.strip() for c in chunk_ids.split(",")]
    tag_list = [t.strip() for t in tags.split(",")]

    count = lib.tag_chunks(tag_list, chunk_ids=ids)
    return f"Added tags {tag_list} to {count} chunks."


@mcp.tool()
def rtfm_remove(filepath: str) -> str:
    """Remove a file and its chunks from the library.

    Args:
        filepath: The filepath (as tracked in the index) to remove.
    """
    log("remove", f"filepath={filepath!r}")
    lib = _get_library()
    if lib.remove_file(filepath):
        return f"Removed: {filepath}"
    return f"Not found in index: {filepath}"


# ── Plugin tools ──────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_discover(path: str = ".") -> str:
    """Scan a project directory and return a structural map.

    Fast (~1 second). Returns file types, languages, entry points,
    and size breakdown — useful to understand a project before diving in.

    Args:
        path: Project root directory (default: current directory).
    """
    from rtfm.plugin.discover import discover, format_discover

    log("discover", f"path={path!r}")
    try:
        info = discover(path)
        log("discover", f"files={info['total_files']} languages={info['languages']}")
        return format_discover(info)
    except Exception as exc:
        log("discover", f"ERROR: {exc}")
        return f"Error scanning {path}: {exc}"


@mcp.tool()
def rtfm_context(
    subject: str,
    scope: str | None = None,
    limit: int = 5,
) -> str:
    """Get relevant context for a subject. Returns metadata only — no content.

    Like a search engine results page: shows which sources are relevant.
    Use rtfm_expand(source, subject) to read the actual content.

    Args:
        subject: Topic, concept, file path, or question to get context for.
        scope: Optional corpus filter.
        limit: Maximum unique sources to return (default 5).
    """
    t0 = time.time()
    lib = _get_library()

    # If subject looks like a file path and exists, try lazy indexing
    subject_path = Path(subject)
    if subject_path.exists() and subject_path.is_file():
        indexed = lib.list_indexed_files()
        rel_path = str(subject_path)
        if rel_path not in indexed:
            try:
                lib.ingest(subject_path, corpus="lazy")
            except Exception:
                pass  # Non-blocking — still search for the subject

    # Overfetch for dedup
    fetch_limit = limit * 5

    # FTS search across all corpora (or scoped) — fast, no model loading
    results = lib.search(subject, limit=fetch_limit, corpus=scope)

    elapsed = time.time() - t0

    if not results:
        log("context", f"subject={subject!r} scope={scope!r} results=0 time={elapsed:.3f}s")
        return f"No context found for: {subject}\nTip: use Grep/Glob as fallback."

    # Deduplicate: 1 best chunk per source
    deduped = _deduplicate_by_source(results, limit)
    log("context", f"subject={subject!r} scope={scope!r} sources={len(deduped)}/{results.total_found} time={elapsed:.3f}s")

    # Metadata-only output — no content, minimal tokens
    lines = [f"Context for \"{subject}\" ({len(deduped)} sources):\n"]
    for rank, entry in enumerate(deduped, 1):
        r = entry["best"]
        count = entry["count"]
        slug = r.chunk.book_slug
        lines.append(f"[{rank}] {_format_source_line(r, count, slug)}")

    return "\n".join(lines)


# ── Drill-down ───────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_expand(
    source: str,
    query: str | None = None,
    limit: int = 20,
) -> str:
    """Drill into a specific source document. Shows all matching chunks.

    Use this AFTER rtfm_search or rtfm_context identified a relevant source.
    Like clicking a search result to read the full page.

    Args:
        source: Book slug (shown in search results as the expand hint).
        query: Optional query to rank chunks by relevance. If omitted, returns all chunks in order.
        limit: Maximum chunks to return (default 20).
    """
    t0 = time.time()
    lib = _get_library()

    # Get book metadata for header
    conn = lib._get_conn()
    book_row = conn.execute(
        "SELECT title, filename, metadata FROM books WHERE slug = ?",
        (source,),
    ).fetchone()

    if not book_row:
        return f"Source not found: {source}"

    book_title = book_row["title"]
    book_file = book_row["filename"] or ""
    import json as _json
    book_meta = _json.loads(book_row["metadata"]) if book_row["metadata"] else {}
    lang = book_meta.get("lang", "")

    # Resolve absolute path for expand (actionable output)
    corpus = ""
    try:
        c_row = conn.execute("SELECT corpus FROM books WHERE slug = ?", (source,)).fetchone()
        corpus = c_row["corpus"] if c_row else ""
    except Exception:
        pass
    abs_path = _resolve_abs_path(book_file, corpus)

    header_parts = [f"Expanding \"{book_title}\""]
    if lang:
        header_parts.append(f"lang: {lang}")
    if abs_path:
        header_parts.append(f"path: {abs_path}")

    if query:
        # Search within this specific book (FTS — fast, no model loading)
        results = lib.search(query, limit=limit, corpus=None)

        # Filter to only this book
        filtered = [r for r in results if r.chunk.book_slug == source]

        if not filtered:
            # Fallback: try FTS with book filter
            results = lib.search(query, limit=limit, book=source)
            filtered = list(results)

        elapsed = time.time() - t0
        log("expand", f"source={source!r} query={query!r} chunks={len(filtered)} time={elapsed:.3f}s")

        if not filtered:
            return f"No chunks found in '{source}' for: {query}"

        lines = [f"{' | '.join(header_parts)} — {len(filtered)} chunks for \"{query}\":\n"]
        for i, r in enumerate(filtered, 1):
            section = r.chunk.chapter_title or ""
            page = r.page
            loc_parts = [f"{section} ({page})"]
            if r.chunk.line_start:
                if r.chunk.line_end and r.chunk.line_end != r.chunk.line_start:
                    loc_parts.append(f"L{r.chunk.line_start}-{r.chunk.line_end}")
                else:
                    loc_parts.append(f"L{r.chunk.line_start}")
            lines.append(f"[{i}] {' — '.join(loc_parts)} — score: {r.score:.3f}")
            lines.append(f"    {r.content}\n")
    else:
        # No query — return all chunks from this book, in page order
        cursor = conn.execute(
            """SELECT c.*, b.title as book_title, b.slug as book_slug,
                      b.filename as book_file
               FROM chunks c
               JOIN books b ON c.book_id = b.id
               WHERE b.slug = ?
               ORDER BY c.page_start, c.paragraph
               LIMIT ?""",
            (source, limit),
        )
        rows = cursor.fetchall()

        elapsed = time.time() - t0
        log("expand", f"source={source!r} query=None chunks={len(rows)} time={elapsed:.3f}s")

        if not rows:
            return f"Source not found: {source}"

        lines = [f"{' | '.join(header_parts)} — {len(rows)} chunks (page order):\n"]
        for i, row in enumerate(rows, 1):
            section = row["chapter_title"] or ""
            ps = row["page_start"] or "?"
            pe = row["page_end"] or ps
            page = f"p.{ps}" if ps == pe else f"pp.{ps}-{pe}"
            loc_parts = [f"{section} ({page})"]
            ls = row["line_start"]
            le = row["line_end"]
            if ls:
                if le and le != ls:
                    loc_parts.append(f"L{ls}-{le}")
                else:
                    loc_parts.append(f"L{ls}")
            lines.append(f"[{i}] {' — '.join(loc_parts)}")
            lines.append(f"    {row['content']}\n")

    lines.append("⏹")
    return "\n".join(lines)


# ── entry point ───────────────────────────────────────────────────────────

def main():
    log("server", f"starting — RTFM_DB={os.environ.get('RTFM_DB', 'library.db')}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
