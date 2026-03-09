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
import re
import sys
import time
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from rtfm.log import log

mcp = FastMCP("rtfm")


# ── Progressive disclosure helpers ───────────────────────────────────────

def _deduplicate_by_source(results, limit: int):
    """Keep only the best chunk per unique source file.

    Two-pass dedup:
    1. First dedup by book_slug (multiple chunks from same book → keep best)
    2. Then dedup by filename basename (copies in libs/skinny/, libs/tracing/ etc.)
       Keep the entry with the shortest path (= the canonical copy).

    Returns a list of dicts with best result, count, and others (top 3 chunks
    besides the best), sorted by score, limited to *limit* unique sources.
    """
    # Pass 1: group by book_slug
    seen: dict[str, dict] = {}  # book_slug -> {best, all}
    for r in results:
        slug = r.chunk.book_slug
        if slug not in seen:
            seen[slug] = {"best": r, "all": [r]}
        else:
            seen[slug]["all"].append(r)
            if r.score > seen[slug]["best"].score:
                seen[slug]["best"] = r

    # Pass 2: dedup by filename basename when files share the same relative
    # path within their subtree (e.g. libs/skinny/mlflow/x.py vs mlflow/x.py).
    by_key: dict[str, dict] = {}  # dedup_key -> {best, all}
    for entry in seen.values():
        r = entry["best"]
        fname = r.chunk.book_file or r.chunk.book_slug
        basename = os.path.basename(fname)

        parts = fname.replace("\\", "/").split("/")
        dedup_key = "/".join(parts[-2:]) if len(parts) >= 2 else basename

        if dedup_key not in by_key:
            by_key[dedup_key] = {"best": r, "all": list(entry["all"])}
        else:
            existing = by_key[dedup_key]
            existing["all"].extend(entry["all"])
            existing_path = existing["best"].chunk.book_file or ""
            new_path = r.chunk.book_file or ""
            if len(new_path) < len(existing_path) or r.score > existing["best"].score:
                existing["best"] = r

    # Compute count, top-3 others, and resolve absolute paths per source
    ranked = sorted(by_key.values(), key=lambda x: x["best"].score, reverse=True)

    # Batch-resolve corpus → abs_path (avoids per-result SQL in _format_source_line)
    corpus_cache: dict[str, str] = {}
    try:
        lib = _get_library()
        conn = lib._get_conn()
        for row in conn.execute("SELECT slug, corpus FROM books").fetchall():
            corpus_cache[row["slug"]] = row["corpus"] or ""
    except Exception:
        pass

    for entry in ranked:
        entry["count"] = len(entry["all"])
        others = sorted(
            [r for r in entry["all"] if r is not entry["best"]],
            key=lambda r: r.score, reverse=True,
        )[:3]
        entry["others"] = others
        del entry["all"]

        # Pre-resolve absolute path
        r = entry["best"]
        filepath = r.chunk.book_file or ""
        corpus = corpus_cache.get(r.chunk.book_slug, "")
        entry["abs_path"] = _resolve_abs_path(filepath, corpus) if filepath else ""

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


def _render_chunk(abs_path: str, line_start: int | None, line_end: int | None) -> str:
    """Read raw lines from the actual file and format with line numbers.

    Guarantees line numbers match what Read/Edit see — always reads the real
    file on disk.  Returns an error message if the file is unavailable.
    """
    if not abs_path or not line_start:
        return "[file not available — no path or line info]"
    try:
        p = Path(abs_path)
        if not p.is_file():
            return f"[file not found on disk: {abs_path}]"
        all_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = (line_start or 1) - 1  # 0-indexed
        end = line_end or len(all_lines)
        selected = all_lines[start:end]
        result = []
        for i, line in enumerate(selected):
            result.append(f"{start + i + 1:>6}\t{line}")
        return "\n".join(result)
    except Exception as e:
        return f"[error reading {abs_path}: {e}]"


def _resolve_book_by_path(conn, filepath: str):
    """Resolve an absolute file path to a book row.

    Strict matching — no LIKE, no fuzzy:
    1. Exact match on books.filename = filepath
    2. Strip each sync_root prefix, match relative path

    Returns sqlite3.Row or None.
    """
    # 1. Exact match (covers directly ingested files with absolute paths)
    row = conn.execute(
        "SELECT id, slug, title, filename, corpus, metadata FROM books WHERE filename = ?",
        (filepath,),
    ).fetchone()
    if row:
        return row

    # 2. Strip sync_root and try relative path
    roots = conn.execute("SELECT corpus, root_path FROM sync_roots").fetchall()
    candidates = []
    for root_row in roots:
        root_path = root_row["root_path"].rstrip("/").rstrip("\\")
        prefix = root_path + "/"
        if filepath.startswith(prefix):
            rel = filepath[len(prefix):]
            row = conn.execute(
                "SELECT id, slug, title, filename, corpus, metadata FROM books WHERE filename = ?",
                (rel,),
            ).fetchone()
            if row:
                candidates.append(row)

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # Dedup by last 2 path components, keep shortest path
        by_key: dict[str, dict] = {}
        for c in candidates:
            fname = c["filename"] or ""
            parts = fname.replace("\\", "/").split("/")
            dedup_key = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
            if dedup_key not in by_key or len(fname) < len(by_key[dedup_key]["filename"] or ""):
                by_key[dedup_key] = c
        results = list(by_key.values())
        if len(results) == 1:
            return results[0]
        return min(results, key=lambda r: len(r["filename"] or ""))

    return None


def _format_source_line(entry: dict, rank: int) -> str:
    """Format a source as a search result line.

    Format:
      [rank] /abs/path > best_section — L<start>-<end> — score: 0.89
          Also: section2 (L<start>-<end>), section3 (L<start>-<end>)

    Expects entry["abs_path"] to be pre-resolved by _deduplicate_by_source.
    """
    r = entry["best"]
    others = entry.get("others", [])

    # Best chunk info
    section = r.chunk.chapter_title or ""
    ls = r.chunk.line_start
    le = r.chunk.line_end

    # Build: path > section — L<lines> — score
    display = entry.get("abs_path") or r.chunk.book_file or r.chunk.book_slug
    if section:
        display += f" > {section}"

    parts = [display]
    if ls:
        line_str = f"L{ls}-{le}" if le and le != ls else f"L{ls}"
        parts.append(line_str)
    parts.append(f"score: {r.score:.2f}")

    main_line = f"[{rank}] {' — '.join(parts)}"

    # "Also:" line for other chunks in the same file
    if others:
        also_items = []
        for o in others:
            s = o.chunk.chapter_title or "?"
            o_ls = o.chunk.line_start
            o_le = o.chunk.line_end
            if o_ls:
                line_str = f"L{o_ls}-{o_le}" if o_le and o_le != o_ls else f"L{o_ls}"
                also_items.append(f"{s} ({line_str})")
            else:
                also_items.append(s)
        main_line += f"\n    Also: {', '.join(also_items)}"

    return main_line



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
    freshness_weight: float = 0.0,
    centrality_weight: float = 0.0,
) -> str:
    """Search the knowledge base. Returns metadata only — no content.

    Like a search engine results page: shows which sources are relevant.
    Use rtfm_expand(source) to read the actual content.

    Args:
        query: The search query.
        limit: Maximum number of unique sources to return (default 5).
        corpus: Filter by corpus name (optional).
        search_type: One of "fts", "semantic", or "hybrid" (default "fts").
        freshness_weight: Boost recently indexed files (0.0 = off, 0.1 = mild).
        centrality_weight: Boost files with many incoming edges (0.0 = off, 0.1 = mild).
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

    # Apply reranking if weights are provided
    if freshness_weight > 0 or centrality_weight > 0:
        results = lib.rerank(results, freshness_weight=freshness_weight,
                             centrality_weight=centrality_weight)

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
        lines.append(_format_source_line(entry, rank))

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
        lines.append(_format_source_line(entry, rank))

    return "\n".join(lines)


# ── Drill-down ───────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_expand(
    source: str,
    target: str | None = None,
    query: str | None = None,
    offset: int = 0,
    count: int = 1,
) -> str:
    """Read content from an indexed source with line numbers.

    Use AFTER rtfm_search to read actual content. Like Read, but for indexed files.

    Args:
        source: Absolute file path (from search results).
        target: Jump to a section name ("class Foo") or line ("L120").
        query: Filter chunks by relevance within the file.
        offset: Pagination offset for query results (default 0).
        count: Number of chunks to return (default 1). Use 0 for all remaining.
    """
    t0 = time.time()
    lib = _get_library()
    conn = lib._get_conn()

    # Resolve path → book (strict matching, no fuzzy)
    book_row = _resolve_book_by_path(conn, source)
    if not book_row:
        return f"File not found in RTFM index: {source}\nTip: use rtfm_search to find indexed files."

    book_slug = book_row["slug"]
    book_title = book_row["title"]
    book_file = book_row["filename"] or ""
    corpus = book_row["corpus"] or ""
    abs_path = _resolve_abs_path(book_file, corpus)

    # All chunks in file order
    all_chunks = conn.execute(
        """SELECT c.*, b.title as book_title, b.slug as book_slug,
                  b.filename as book_file
           FROM chunks c
           JOIN books b ON c.book_id = b.id
           WHERE b.slug = ?
           ORDER BY c.page_start, c.paragraph""",
        (book_slug,),
    ).fetchall()

    if not all_chunks:
        return f"No content indexed for: {source}"

    total = len(all_chunks)
    display_path = abs_path or source

    # --- Query mode: search within file ---
    if query:
        filtered = list(lib.search(query, limit=50, book=book_slug))

        if not filtered:
            return f"No chunks in {display_path} match: {query}"

        total_relevant = len(filtered)
        if offset >= total_relevant:
            return f"No more results for \"{query}\" in {display_path} (offset={offset}, total={total_relevant})"

        # Return count results starting from offset
        end_offset = total_relevant if count == 0 else min(offset + count, total_relevant)
        selected = filtered[offset:end_offset]

        # Header from first result
        r0 = selected[0]
        chunk_idx = next(
            (i for i, row in enumerate(all_chunks) if row["chunk_id"] == r0.chunk.id),
            0,
        )
        section = r0.chunk.chapter_title or book_title
        ls = r0.chunk.line_start
        le = r0.chunk.line_end
        line_info = f"L{ls}-{le}" if ls and le else (f"L{ls}" if ls else "")
        n_shown = len(selected)
        pos = f"[{chunk_idx + 1}/{total}]" if n_shown == 1 else f"[{n_shown} chunks]"

        header = f"{display_path} > {section} {pos}"
        if line_info:
            header += f" — {line_info}"

        lines = [header, "", _render_chunk(display_path, ls, le)]

        # Additional results
        for r in selected[1:]:
            s = r.chunk.chapter_title or ""
            r_ls = r.chunk.line_start
            r_le = r.chunk.line_end
            r_line = f"L{r_ls}-{r_le}" if r_ls and r_le else (f"L{r_ls}" if r_ls else "")
            r_idx = next(
                (i for i, row in enumerate(all_chunks) if row["chunk_id"] == r.chunk.id),
                0,
            )
            lines.append(f"\n─── {s} [{r_idx + 1}/{total}] — {r_line} ───\n")
            lines.append(_render_chunk(display_path, r_ls, r_le))

        # Navigation hints
        if n_shown == 1 and chunk_idx + 1 < total:
            nx = all_chunks[chunk_idx + 1]
            ns = nx["chapter_title"] or ""
            nls, nle = nx["line_start"], nx["line_end"]
            nl = f"L{nls}-{nle}" if nls and nle else (f"L{nls}" if nls else "")
            lines.append(f"\n⏹ Next in file [{chunk_idx + 2}/{total}]: \"{ns}\" {nl}")

        remaining = total_relevant - end_offset
        if remaining > 0:
            lines.append(f"  {remaining} more relevant chunks. Next: rtfm_expand(\"{source}\", query=\"{query}\", offset={end_offset})")

        elapsed = time.time() - t0
        log("expand", f"source={source!r} query={query!r} offset={offset} count={n_shown} time={elapsed:.3f}s")
        return "\n".join(lines)

    # --- Target or default mode ---
    if target:
        chunk_idx = None
        if re.match(r'^L\d+', target):
            target_line = int(re.match(r'^L(\d+)', target).group(1))
            # Find chunk containing target_line
            for i, row in enumerate(all_chunks):
                ls, le = row["line_start"], row["line_end"]
                if ls and le and ls <= target_line <= le:
                    chunk_idx = i
                    break
            # Fallback: first chunk starting at or after target_line
            if chunk_idx is None:
                for i, row in enumerate(all_chunks):
                    if row["line_start"] and row["line_start"] >= target_line:
                        chunk_idx = i
                        break
        else:
            # Section name — exact match on chapter_title
            for i, row in enumerate(all_chunks):
                if row["chapter_title"] == target:
                    chunk_idx = i
                    break

        if chunk_idx is None:
            sections = [
                f"\"{row['chapter_title']}\" L{row['line_start']}"
                for row in all_chunks if row["chapter_title"]
            ]
            return f"Target not found in {display_path}: {target}\nAvailable sections: {', '.join(sections)}"
    else:
        chunk_idx = 0

    # Return count consecutive chunks starting from chunk_idx
    end_idx = total if count == 0 else min(chunk_idx + count, total)
    selected_rows = all_chunks[chunk_idx:end_idx]
    n_shown = len(selected_rows)

    # Header
    first = selected_rows[0]
    section = first["chapter_title"] or book_title
    ls = first["line_start"]
    last_le = selected_rows[-1]["line_end"]
    if n_shown == 1:
        le = first["line_end"]
        line_info = f"L{ls}-{le}" if ls and le else (f"L{ls}" if ls else "")
        pos = f"[{chunk_idx + 1}/{total}]"
    else:
        line_info = f"L{ls}-{last_le}" if ls and last_le else (f"L{ls}" if ls else "")
        pos = f"[{chunk_idx + 1}-{end_idx}/{total}]"

    header = f"{display_path} > {section} {pos}"
    if line_info:
        header += f" — {line_info}"

    lines = [header, "", _render_chunk(display_path, ls, first["line_end"])]

    # Additional chunks
    for j, row in enumerate(selected_rows[1:], 1):
        s = row["chapter_title"] or ""
        r_ls = row["line_start"]
        r_le = row["line_end"]
        r_line = f"L{r_ls}-{r_le}" if r_ls and r_le else (f"L{r_ls}" if r_ls else "")
        r_idx = chunk_idx + j
        lines.append(f"\n─── {s} [{r_idx + 1}/{total}] — {r_line} ───\n")
        lines.append(_render_chunk(display_path, r_ls, r_le))

    # Navigation: next in file
    if end_idx < total:
        nx = all_chunks[end_idx]
        ns = nx["chapter_title"] or ""
        nls, nle = nx["line_start"], nx["line_end"]
        nl = f"L{nls}-{nle}" if nls and nle else (f"L{nls}" if nls else "")
        lines.append(f"\n⏹ Next in file [{end_idx + 1}/{total}]: \"{ns}\" {nl}")
    else:
        lines.append("\n⏹")

    elapsed = time.time() - t0
    log("expand", f"source={source!r} target={target!r} chunk={chunk_idx + 1}-{end_idx}/{total} time={elapsed:.3f}s")
    return "\n".join(lines)


# ── Graph tools ──────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_graph(
    source: str,
    direction: str = "both",
    relation_type: str | None = None,
) -> str:
    """Show dependency graph neighbors of a file.

    Shows which files import/link/include the source and which files
    the source depends on. Useful for understanding code structure.

    Args:
        source: Book slug or absolute file path.
        direction: "outgoing" (dependencies), "incoming" (dependents), or "both".
        relation_type: Filter by type: "import", "link", "include", "cite" (optional).
    """
    log("graph", f"source={source!r} direction={direction} type={relation_type!r}")
    lib = _get_library()
    conn = lib._get_conn()

    # Resolve source: try as slug first, then as file path
    book_slug = source
    book_row = conn.execute("SELECT slug FROM books WHERE slug = ?", (source,)).fetchone()
    if not book_row:
        book_row = _resolve_book_by_path(conn, source)
        if book_row:
            book_slug = book_row["slug"]
        else:
            return f"Source not found: {source}"

    neighbors = lib.get_neighbors(book_slug, direction=direction, relation_type=relation_type)

    if not neighbors:
        return f"No edges found for: {book_slug} (direction={direction})"

    # Group by direction
    outgoing = [n for n in neighbors if n["direction"] == "outgoing"]
    incoming = [n for n in neighbors if n["direction"] == "incoming"]

    lines = [f"Graph for {book_slug}:"]

    if outgoing:
        lines.append(f"\nOutgoing ({len(outgoing)} dependencies):")
        for n in outgoing:
            detail = f" — {n['source_detail']}" if n.get("source_detail") else ""
            lines.append(f"  -> {n['filename'] or n['slug']} [{n['relation_type']}]{detail}")

    if incoming:
        lines.append(f"\nIncoming ({len(incoming)} dependents):")
        for n in incoming:
            detail = f" — {n['source_detail']}" if n.get("source_detail") else ""
            lines.append(f"  <- {n['filename'] or n['slug']} [{n['relation_type']}]{detail}")

    # Graph stats
    stats = lib.get_graph_stats()
    lines.append(f"\nGraph: {stats['total_edges']} edges, {stats['books_with_edges']} connected files")

    return "\n".join(lines)


# ── History tools ────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_history(
    source: str,
    version: int | None = None,
) -> str:
    """Show version history of an indexed file, or retrieve a specific version.

    Each time a file is re-synced, its previous content is saved as a snapshot.

    Args:
        source: Book slug or absolute file path.
        version: Version number to retrieve (optional). If omitted, lists all versions.
    """
    log("history", f"source={source!r} version={version!r}")
    lib = _get_library()
    conn = lib._get_conn()

    # Resolve source
    book_slug = source
    book_row = conn.execute("SELECT slug FROM books WHERE slug = ?", (source,)).fetchone()
    if not book_row:
        book_row = _resolve_book_by_path(conn, source)
        if book_row:
            book_slug = book_row["slug"]
        else:
            return f"Source not found: {source}"

    if version is not None:
        # Return specific version content
        ver = lib.get_file_version(book_slug, version)
        if not ver:
            return f"Version {version} not found for: {book_slug}"
        return (
            f"{book_slug} v{ver['version_num']} — {ver['created_at']} "
            f"({ver['file_size'] or 0:,} bytes, hash: {ver['content_hash'][:8]})\n\n"
            f"{ver['snapshot']}"
        )

    # List versions
    history = lib.get_file_history(book_slug)
    if not history:
        return f"No version history for: {book_slug}"

    lines = [f"Version history for {book_slug} ({len(history)} versions):"]
    for v in history:
        size = v.get("file_size") or 0
        lines.append(
            f"  v{v['version_num']}: {v['created_at']} — "
            f"{size:,} bytes (hash: {v['content_hash'][:8]})"
        )
    lines.append(f"\nUse rtfm_history(\"{source}\", version=N) to read a specific version.")
    return "\n".join(lines)


# ── entry point ───────────────────────────────────────────────────────────

def main():
    log("server", f"starting — RTFM_DB={os.environ.get('RTFM_DB', 'library.db')}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
