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

from rtfm._mcp import FastMCP
from rtfm.log import log

mcp = FastMCP("rtfm")


# ── Tool profile (token footprint) ───────────────────────────────────────
# RTFM_MCP_PROFILE controls which tools are exposed to the agent at runtime.
#   "runtime" (default) : 6 retrieval tools — minimal context footprint
#   "admin" / "all"     : all 13 tools (incl. sync, ingest, remove, tags…)
# Admin operations (sync, ingest, …) are also available via CLI and the
# Python API (used by hooks), so excluding them from MCP doesn't break them.

_PROFILE = os.environ.get("RTFM_MCP_PROFILE", "runtime").lower()


def _admin_tool():
    """Register a tool ONLY when RTFM_MCP_PROFILE is admin/all.

    Returns a no-op decorator otherwise (function stays callable from Python
    but isn't exposed as an MCP tool).
    """
    if _PROFILE in ("admin", "all"):
        return mcp.tool()
    return lambda fn: fn


# ── Param coercion (LLM-friendly) ────────────────────────────────────────

def _coerce_int(value, default: int) -> int:
    """Coerce LLM-passed values to int.

    Some MCP clients/LLMs pass numeric params as JSON strings (e.g.
    ``"limit": "5"``). Without coercion this crashes downstream in
    comparisons like ``len(results) >= limit``. Falls back to ``default``
    for ``None`` or unparseable values rather than raising.
    """
    if value is None:
        return default
    if isinstance(value, bool):  # bool is a subclass of int — reject it
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default: float) -> float:
    """Coerce LLM-passed values to float. See ``_coerce_int``."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── Progressive disclosure helpers ───────────────────────────────────────

def _deduplicate_by_source(results, limit: int, lib=None):
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

    # Batch-resolve book_slug → sync-root (avoids per-result SQL). The shared
    # resolver is the *same* one the CLI uses, so both report identical paths.
    from rtfm.core.pathresolve import (
        build_slug_root_resolver, owning_root, resolve_source_path)
    # The resolver has to come from the index the results came *from*: a
    # neighbour's slugs mean nothing to our own sync roots, and resolving
    # them against ours yields paths that do not exist — which then reads,
    # correctly and uselessly, as "every one of these files is deleted".
    roots_for_slug = build_slug_root_resolver(lib if lib is not None
                                              else _get_library())

    for entry in ranked:
        entry["count"] = len(entry["all"])
        others = sorted(
            [r for r in entry["all"] if r is not entry["best"]],
            key=lambda r: r.score, reverse=True,
        )[:3]
        entry["others"] = others
        del entry["all"]

        # Pre-resolve absolute path via the shared rule.
        r = entry["best"]
        filepath = r.chunk.book_file or ""
        corpus_roots = roots_for_slug(r.chunk.book_slug)
        entry["filepath"] = filepath
        entry["abs_path"] = (
            resolve_source_path(filepath, corpus_roots) if filepath else "")
        # The one directory this file belongs to — what re-indexing needs.
        entry["root"] = owning_root(entry["abs_path"], corpus_roots)

    return ranked[:limit]


def _catch_up_before_empty_answer() -> bool:
    """Bring the index level with disk before reporting that nothing matches.

    "No results" is the one answer read-time verification cannot check: with
    no file returned, there is nothing to compare against disk. And it is the
    answer that misleads most — "this does not exist" sends an agent off to
    write code that is already there, or to conclude a symbol was removed.

    So an empty answer earns a look at the disk: drain whatever the edit hook
    queued, and failing that scan the sources outright, all inside the
    freshness budget. Returns ``True`` if the index moved.
    """
    try:
        from rtfm.core import freshness

        budget = freshness.refresh_wait_seconds()
        if budget <= 0 or not freshness.indexer_is_running():
            return False
        lib = _get_library()
        project_root = Path(lib.db_path).resolve().parent.parent
        t0 = time.time()
        caught_up = freshness.catch_up(str(lib.db_path), str(project_root), budget)
        log("freshness", f"empty answer — catch-up "
                         f"{'ran' if caught_up else 'skipped'} "
                         f"in {time.time() - t0:.2f}s")
        return caught_up
    except Exception:
        return False


def _verify_freshness(entries: list[dict], lib=None) -> bool:
    """Check answered sources against disk, and repair before answering.

    The index is eventually consistent; an agent must never be left to
    assume otherwise. Each answered file is stat'ed (hashed when small). On
    drift the fix is queued at top priority and this call **waits** for it —
    a single-file re-ingest takes about a second, which is worth paying to
    answer from a correct index rather than to explain that it isn't one.

    The write happens in the supervisor, never here: one writer per database
    is what keeps them from corrupting, and a reader must not take that role.

    Returns ``True`` when the index was repaired and the caller should ask
    its question again. Otherwise the drifting entries carry a ``stale``
    verdict to report. Best-effort — a search must still answer if any of
    this fails.
    """
    if not entries:
        return False
    try:
        from rtfm.core import freshness

        if lib is None:
            lib = _get_library()
        # A project we are only visiting is never written to: its worker
        # owns its queue, and a reader that queues work into someone else's
        # index is a second writer by another name. Its drift is reported,
        # not repaired.
        visiting = bool(getattr(lib, "read_only", False)) or lib is not _library
        verdicts = freshness.verify(
            lib, [(e.get("abs_path", ""), e.get("filepath", "")) for e in entries])
        if not verdicts:
            return False

        repairable, gone, withheld = [], [], []
        for entry in entries:
            found = verdicts.get(entry.get("abs_path", ""))
            if not found:
                continue
            entry["stale"] = found["verdict"]
            if (found["verdict"] == freshness.STALE and entry.get("root")
                    and found.get("corpus")):
                repairable.append(
                    (entry["root"], found["corpus"], found["filepath"]))
            elif (found["verdict"] == freshness.GONE and found.get("corpus")
                  and freshness.deleted_source_is_certain(
                      entry.get("abs_path", ""), entry.get("root"))):
                withheld.append(entry)
                gone.append((found["corpus"], found["filepath"]))

        # Content that is not on disk any more is not an answer, and
        # labelling it as one leaves the reading to the agent. Measured on a
        # repository that had just condensed 338 documents into one: eleven
        # of twelve results named files that no longer existed, the one
        # surviving authority was buried under them, and the agent concluded
        # that nothing decided the question. They are withheld and their
        # removal is queued; the worker re-checks the disk before acting.
        if visiting:
            # Say what is wrong; leave the fixing to whoever owns the index.
            return False
        for entry in withheld:
            entries.remove(entry)
        removed = freshness.queue_removals(str(lib.db_path), gone)
        if withheld:
            log("freshness", f"{len(withheld)} deleted source(s) withheld "
                             f"from the answer, {removed} queued for removal")

        job_ids = freshness.requeue(str(lib.db_path), repairable)
        budget = freshness.refresh_wait_seconds()
        if not job_ids or budget <= 0 or not freshness.indexer_is_running():
            log("freshness", f"drift on {len(verdicts)} source(s), "
                             f"{len(job_ids)} re-ingest queued")
            return False

        t0 = time.time()
        repaired = freshness.wait_for(str(lib.db_path), job_ids, budget)
        log("freshness", f"drift on {len(verdicts)} source(s), "
                         f"{len(job_ids)} re-ingest "
                         f"{'done' if repaired else 'still running'} "
                         f"in {time.time() - t0:.2f}s")
        if not repaired:
            return False
        # Fresh index — the answer must be recomputed, not patched up.
        for entry in entries:
            entry.pop("stale", None)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        log("freshness", f"check skipped: {exc}")
        return False


def _expand_freshness(abs_path: str, filepath: str, corpus: str,
                      root: str | None, lib=None) -> tuple[str, bool]:
    """Reconcile an expanded file with its index before reading it.

    Returns ``(warning, repaired)``. ``repaired`` means the file was out of
    date and has just been re-indexed, so the caller must re-read its chunk
    rows — the boundaries it holds describe the old content. A non-empty
    warning means the drift is still there and the line ranges below cannot
    be trusted (the content can: it is read live off disk either way).
    """
    if not abs_path:
        return "", False
    try:
        from rtfm.core import freshness

        if lib is None:
            lib = _get_library()
        verdicts = freshness.verify(lib, [(abs_path, filepath)])
        found = verdicts.get(abs_path)
        if not found:
            return "", False

        # A project we are only visiting is reported on, never written to.
        visiting = bool(getattr(lib, "read_only", False)) or lib is not _library
        if found["verdict"] == freshness.STALE and root and not visiting:
            job_ids = freshness.requeue(
                str(lib.db_path), [(root, found.get("corpus") or corpus, filepath)])
            budget = freshness.refresh_wait_seconds()
            if job_ids and budget > 0 and freshness.indexer_is_running():
                t0 = time.time()
                if freshness.wait_for(str(lib.db_path), job_ids, budget):
                    log("freshness", f"expand re-indexed in {time.time() - t0:.2f}s: "
                                     f"{abs_path}")
                    return "", True
        log("freshness", f"expand on {found['verdict']}: {abs_path}")
        return (f"⚠ {found['verdict']} — content below is read from disk and "
                f"current; the line ranges and sections come from the index "
                f"and may have shifted."
                + ("" if visiting else " Re-indexing queued."), False)
    except Exception:
        return "", False


def _render_chunk(abs_path: str, line_start: int | None, line_end: int | None,
                  indexed_text: str | None = None) -> str:
    """Return the passage: raw lines off disk, or the indexed text.

    For a text file the lines are read live so they match exactly what
    Read/Edit see. A PDF, an ebook or a spreadsheet has no lines to read —
    its text exists only as extracted, in the index — and this used to answer
    "[file not available]" for every one of them. Search found the right
    document and then nothing could be read out of it, which left a corpus of
    PDFs searchable but unreadable.

    So: lines when there are lines, the indexed text otherwise.
    """
    if indexed_text is not None and (not abs_path or not line_start):
        return indexed_text
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


def _format_source_line(entry: dict, rank: int = 0) -> str:
    """Format a source as a search result line.

    Format:
      /abs/path L<start>-<end> (section_name)
        + L<start>-<end> (other), L<start>-<end> (other2)

    `rank` arg is kept for API compat but unused (agent counts naturally).
    Expects entry["abs_path"] to be pre-resolved by _deduplicate_by_source.
    """
    r = entry["best"]
    others = entry.get("others", [])

    display = entry.get("abs_path") or r.chunk.book_file or r.chunk.book_slug
    parts = [display]

    ls = r.chunk.line_start
    le = r.chunk.line_end
    if ls:
        parts.append(f"L{ls}-{le}" if le and le != ls else f"L{ls}")

    section = r.chunk.chapter_title or ""
    if section:
        parts.append(f"({section})")

    # Say it out loud when the index disagrees with the file on disk: the
    # path and content are still right (expand reads the real file), but the
    # line range may have drifted and the match may no longer be there.
    stale = entry.get("stale")
    if stale:
        parts.append(f"⚠ {stale}")

    main_line = " ".join(parts)

    if others:
        also_items = []
        for o in others:
            o_ls = o.chunk.line_start
            o_le = o.chunk.line_end
            o_section = o.chunk.chapter_title or ""
            piece = ""
            if o_ls:
                piece = f"L{o_ls}-{o_le}" if o_le and o_le != o_ls else f"L{o_ls}"
            if o_section:
                piece = f"{piece} ({o_section})" if piece else f"({o_section})"
            if piece:
                also_items.append(piece)
        if also_items:
            main_line += f"\n  + {', '.join(also_items)}"

    return main_line



# ── Library singleton ─────────────────────────────────────────────────────

_library = None
_library_identity = None
_embed_lock = threading.Lock()


class NoIndexHere(RuntimeError):
    """Raised when this directory has no RTFM index. Not an error state —
    just an honest answer, and far better than the alternative."""


def _get_library(project: str | None = None):
    """Return the Library singleton, opening an existing index only.

    The server never creates one. It is a reader, and creating on open is
    how a 27 GB index once appeared in a directory nobody had indexed: the
    plugin points ``RTFM_DB`` at the *relative* ``.rtfm/library.db``, so a
    session opened anywhere aimed the server at a database in that
    directory — and opening it brought it into being, schema and all. A
    scan then found 151 416 files there (a tree of twenty-six already-indexed
    projects, their virtualenvs and their vendored dependencies) and spent
    three days and three cores indexing them.

    Refusing to create it costs a clear message; creating it costs the disk.

    The handle is also re-validated on every call. A session outlives the
    index it reads: re-running ``rtfm init``, or republishing a directory
    that other projects read, replaces ``library.db`` with a new file — and
    on Unix the old connection keeps working against the unlinked inode,
    answering for ever from a snapshot nobody else can see. A ``stat`` per
    call is nothing next to a neighbour served plausible, permanently stale
    answers with no error and no zero to warn them.
    """
    global _library, _library_identity
    from rtfm.core.library import Library

    if project:
        return _get_foreign_library(project)

    db_path = os.environ.get("RTFM_DB")
    if not db_path:
        from rtfm.config import resolve_db
        db_path = resolve_db()

    identity = _db_identity(db_path)
    if _library is not None and identity != _library_identity:
        try:
            _library.close()
        except Exception:
            pass
        _library = None

    if _library is None:
        try:
            _library = Library(db_path, create=False)
            _library_identity = identity
        except FileNotFoundError:
            raise NoIndexHere(
                f"No RTFM index for this directory (looked for {db_path}). "
                f"RTFM indexes a project only once you ask it to: run "
                f"`rtfm init` here if this directory should be indexed. "
                f"Use your own file tools in the meantime."
            ) from None
    return _library


#: Indexes of *other* projects, opened on demand and kept for the session.
#: Keyed by the resolved database path, and re-validated by inode on every
#: call exactly like the local one — a neighbour's index is republished far
#: more often than one's own.
_foreign: dict[str, tuple[object, tuple[int, int] | None]] = {}
_foreign_lock = threading.Lock()


def _get_foreign_library(project: str):
    """Open another project's index, read-only if that is all it allows.

    The knowledge that binds a workshop of repositories together lives in
    none of them, and an index resolved from the working directory cannot
    reach it: the query comes back empty, and an empty answer reads as "no
    such rule exists". This is the way out of that, and it is deliberately
    a *read*: nothing here writes to a project we are visiting.
    """
    from rtfm.core.library import Library
    from rtfm.core.projects import resolve_project_db, UnknownProject

    try:
        db_path = str(resolve_project_db(project))
    except UnknownProject as exc:
        raise NoIndexHere(str(exc)) from None

    identity = _db_identity(db_path)
    with _foreign_lock:
        cached = _foreign.get(db_path)
        if cached is not None and cached[1] == identity:
            return cached[0]
        if cached is not None:
            try:
                cached[0].close()
            except Exception:
                pass
        lib = Library(db_path, create=False)
        _foreign[db_path] = (lib, identity)
        return lib


def _db_identity(db_path):
    """Device+inode of the index file, or ``None`` if it is not there.

    The path is unchanged when a database is replaced; the inode is not.
    """
    try:
        st = os.stat(db_path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


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
    project: str | None = None,
) -> str:
    """Search the indexed knowledge base. Returns ranked source paths
    with line ranges, no content. Use rtfm_expand to read content.

    Args:
        query: search query
        limit: max sources (default 5)
        corpus: filter by corpus name
        search_type: "fts" | "semantic" | "hybrid"
        freshness_weight: boost recently indexed files (0.0–0.5)
        centrality_weight: boost files with many incoming edges (0.0–0.5)
        project: another project's index to search instead of this one —
            its name (``"hub"``), or its path when two projects share a
            name. Omit for the project you are working in.
    """
    t0 = time.time()
    lib = _get_library(project)

    # Defensive coercion: some MCP clients pass ints as strings
    limit = _coerce_int(limit, 5)
    freshness_weight = _coerce_float(freshness_weight, 0.0)
    centrality_weight = _coerce_float(centrality_weight, 0.0)

    # Overfetch to ensure enough unique sources after dedup
    fetch_limit = limit * 5

    def _run():
        try:
            if search_type == "semantic":
                found = lib.semantic_search(query, limit=fetch_limit, corpus=corpus)
            elif search_type == "fts":
                found = lib.search(query, limit=fetch_limit, corpus=corpus)
            else:
                found = lib.hybrid_search(query, limit=fetch_limit, corpus=corpus)
        except Exception:
            found = lib.search(query, limit=fetch_limit, corpus=corpus)
        if freshness_weight > 0 or centrality_weight > 0:
            found = lib.rerank(found, freshness_weight=freshness_weight,
                               centrality_weight=centrality_weight)
        return found

    results = _run()
    if not results and not project and _catch_up_before_empty_answer():
        results = _run()
    elapsed = time.time() - t0

    if not results:
        log("search", f"query={query!r} type={search_type} results=0 time={elapsed:.3f}s")
        return f"No results found for: {query}"

    # Deduplicate: 1 best chunk per source
    deduped = _deduplicate_by_source(results, limit, lib)
    if _verify_freshness(deduped, lib):
        # A source had drifted and has just been re-indexed. The ranking and
        # the line ranges were computed from the old content, so ask again
        # rather than hand back an answer we know was built on stale rows.
        results = _run()
        deduped = _deduplicate_by_source(results, limit, lib) if results else []
        elapsed = time.time() - t0
        if not deduped:
            return f"No results found for: {query}"
    log("search", f"query={query!r} type={search_type} sources={len(deduped)}/{results.total_found} time={elapsed:.3f}s")

    lines = [f"{len(deduped)} sources for \"{query}\":\n"]
    for entry in deduped:
        lines.append(_format_source_line(entry))

    return "\n".join(lines)


@mcp.tool()
def rtfm_coverage(project: str | None = None) -> str:
    """How much of a project this index actually holds.

    Say this before answering from the index when completeness matters: a
    partial index read as a complete one is how an absent result becomes
    "there is nothing on the subject".

    The denominator is the scan's own list of files — not everything in the
    directory. Logs, lock files, state files and build output are not
    counted as gaps, because RTFM was never going to index them.

    Args:
        project: another project to measure — its name ("hub"), or its path
            when two projects share a name. Omit for the current one.
    """
    from rtfm.core.coverage import measure

    lib = _get_library(project)
    root = Path(lib.db_path).parent.parent
    try:
        cov = measure(root, Path(lib.db_path))
    except Exception as exc:
        return f"coverage: could not measure {root} — {exc}"

    lines = [cov.one_line()]
    if len(cov.sources) > 1 or any(s.error for s in cov.sources):
        for src in cov.sources:
            if src.error:
                lines.append(f"  [{src.corpus}] {src.root}: unreadable — {src.error}")
            else:
                lines.append(f"  [{src.corpus}] {src.root}: "
                             f"{src.readable}/{src.indexable} "
                             f"({100 * src.ratio:.1f}%)")
    if cov.unaccounted:
        lines.append(f"  {cov.unaccounted} tracked file(s) under no configured "
                     f"source — indexed from a directory no longer listed")
    log("coverage", f"project={project!r} {cov.readable}/{cov.indexable}")
    return "\n".join(lines)


@_admin_tool()
def rtfm_stats() -> str:
    """Get library statistics: total chunks, books, corpora, tag and embedding coverage.

    Also reports the install state of optional extras (embeddings, pdf) and
    surfaces actionable recommendations when the current index would benefit
    from an extra the user has not installed.
    """
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

    # Optional-extras state, visible to the agent so it can proactively
    # suggest installs to the user when the signal justifies it.
    def _has(mod: str) -> bool:
        try:
            __import__(mod)
            return True
        except ImportError:
            return False

    has_embeddings = _has("fastembed")
    has_pdf = _has("pdftext")

    lines.append("")
    lines.append("Optional extras:")
    lines.append(f"  embeddings: {'installed' if has_embeddings else 'missing'}"
                 " (semantic search)")
    lines.append(f"  pdf:        {'installed' if has_pdf else 'missing'}"
                 " (PDF parsing)")

    # Actionable instructions for the agent — factual triggers, explicit
    # user-facing message, exact command to run. No hedging, no "might help".
    actions = []
    conn = lib._conn
    total_chunks = stats['chunks']

    if not has_embeddings and total_chunks > 500:
        actions.append({
            "trigger": f"Index has {total_chunks} chunks, embeddings not installed.",
            "impact": "Paraphrase queries fail. FTS matches literal tokens only — "
                      "'auth flow' will not retrieve 'authentication handler'.",
            "tell_user": (
                f"\"Your RTFM index has {total_chunks} chunks. Semantic search "
                "would measurably improve retrieval on paraphrase queries. "
                "Install the embeddings extra? One-time 85 MB ONNX download, "
                "no GPU required.\""
            ),
            "command": "pip install rtfm-ai[embeddings] && rtfm embed",
        })

    if not has_pdf:
        try:
            n_pdf = conn.execute(
                "SELECT COUNT(*) FROM indexed_files WHERE filepath LIKE '%.pdf'"
            ).fetchone()[0]
        except Exception:
            n_pdf = 0
        if n_pdf:
            actions.append({
                "trigger": f"{n_pdf} PDF file(s) present in indexed directories, "
                           "pdf extra not installed.",
                "impact": f"These {n_pdf} PDFs are invisible to search. "
                          "Any content inside them cannot be retrieved.",
                "tell_user": (
                    f"\"I found {n_pdf} PDF file(s) in your project that RTFM "
                    "cannot index without the pdf extra. Install it so your "
                    "agent can search them?\""
                ),
                "command": "pip install rtfm-ai[pdf] && rtfm sync --force",
            })

    if actions:
        lines.append("")
        lines.append("=" * 60)
        lines.append("ACTIONS REQUIRED — surface these to the user verbatim:")
        lines.append("=" * 60)
        for i, a in enumerate(actions, 1):
            lines.append(f"\n[{i}] TRIGGER: {a['trigger']}")
            lines.append(f"    IMPACT:  {a['impact']}")
            lines.append(f"    SAY TO USER: {a['tell_user']}")
            lines.append(f"    ON APPROVAL RUN: {a['command']}")

    return "\n".join(lines)


@_admin_tool()
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
    project: str | None = None,
) -> str:
    """List indexed books with per-corpus summary and pagination.

    Args:
        corpus: filter by corpus name (optional)
        limit: max books per page (default 50, 0 for all)
        offset: skip N books for pagination (default 0)
        project: another project's index to read instead of this one — its
            name (``"hub"``), or its path when two projects share a name.
    """
    limit = _coerce_int(limit, 50)
    offset = _coerce_int(offset, 0)
    log("books", f"corpus={corpus!r} limit={limit} offset={offset}")
    lib = _get_library(project)
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

@_admin_tool()
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

    out = [
        f"Sync complete: +{result.added} added, ~{result.modified} modified, "
        f"-{result.removed} removed, ={result.unchanged} unchanged"
    ]
    if result.errors:
        out.append(f"Errors: {result.errors}")

    # Sync saw PDFs but no pdf parser is installed → emit an explicit
    # action block (same format as rtfm_stats) so the agent knows exactly
    # what to say to the user and which command to run on approval.
    try:
        import pdftext  # noqa: F401
    except ImportError:
        pdf_seen = [e for e in result.errors if ".pdf" in e.lower()]
        if pdf_seen:
            out.append("")
            out.append("=" * 60)
            out.append("ACTION REQUIRED — surface to the user verbatim:")
            out.append("=" * 60)
            out.append(f"TRIGGER: {len(pdf_seen)} PDF file(s) skipped during this sync, "
                       "pdf extra not installed.")
            out.append(f"IMPACT:  Those {len(pdf_seen)} PDFs are not indexed. "
                       "Their content will not appear in any search result.")
            out.append(
                f"SAY TO USER: \"This sync skipped {len(pdf_seen)} PDF file(s) "
                "because RTFM's PDF parser is not installed. "
                "Install it so I can index them?\""
            )
            out.append("ON APPROVAL RUN: pip install rtfm-ai[pdf] && rtfm sync --force")

    # PDFs that parsed without error but produced zero text → almost
    # always scanned images. Same ACTION REQUIRED format so the agent
    # raises it with the user instead of silently ignoring.
    if result.suspect_scans:
        n = len(result.suspect_scans)
        preview = ", ".join(result.suspect_scans[:3])
        if n > 3:
            preview += f", +{n - 3} more"
        out.append("")
        out.append("=" * 60)
        out.append("ACTION REQUIRED — surface to the user verbatim:")
        out.append("=" * 60)
        out.append(f"TRIGGER: {n} PDF file(s) extracted 0 text — likely scanned "
                   "images (no text layer).")
        out.append(f"IMPACT:  Those {n} PDFs are indexed as empty. Their content "
                   "will not appear in any search result.")
        out.append(f"FILES:   {preview}")
        out.append(
            f"SAY TO USER: \"RTFM detected {n} PDF(s) that look like scans "
            "(no extractable text). Want me to enable OCR? You only run "
            "this command once — future syncs will OCR new scans "
            "automatically.\""
        )
        out.append("EXACT COMMAND TO PROPOSE: rtfm sync --ocr")
        out.append("ON APPROVAL RUN: rtfm sync --ocr")

    return "\n".join(out)


@_admin_tool()
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


@_admin_tool()
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


@_admin_tool()
def rtfm_remove(filepath: str, corpus: str = "default") -> str:
    """Remove a file and its chunks from the library.

    Args:
        filepath: The filepath (as tracked in the index) to remove.
        corpus: Which corpus it belongs to. A relative path identifies a file
            only within its corpus — the same README.md can be indexed in
            several — so removing without saying which one is ambiguous.
    """
    log("remove", f"filepath={filepath!r} corpus={corpus!r}")
    lib = _get_library()
    if lib.remove_file(filepath, corpus):
        return f"Removed: [{corpus}] {filepath}"
    return f"Not found in index: [{corpus}] {filepath}"


# ── Plugin tools ──────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_discover(path: str = ".") -> str:
    """Scan a project directory and return a structural map (file types,
    languages, entry points, size breakdown). ~1 second.

    Args:
        path: project root directory (default ".")
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
    project: str | None = None,
) -> str:
    """Get sources relevant to a subject. Returns paths + line ranges,
    no content. Use rtfm_expand to read.

    Args:
        subject: topic, concept, file path, or question
        scope: corpus filter (optional)
        limit: max sources (default 5)
        project: another project's index to read instead of this one — its
            name (``"hub"``), or its path when two projects share a name.
    """
    t0 = time.time()
    lib = _get_library(project)

    limit = _coerce_int(limit, 5)

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
    if not results and not project and _catch_up_before_empty_answer():
        results = lib.search(subject, limit=fetch_limit, corpus=scope)

    elapsed = time.time() - t0

    if not results:
        log("context", f"subject={subject!r} scope={scope!r} results=0 time={elapsed:.3f}s")
        return f"No context found for: {subject}\nTip: use Grep/Glob as fallback."

    # Deduplicate: 1 best chunk per source
    deduped = _deduplicate_by_source(results, limit, lib)
    if _verify_freshness(deduped, lib):
        # A source drifted and was just re-indexed — ask again (see rtfm_search).
        results = lib.search(subject, limit=fetch_limit, corpus=scope)
        deduped = _deduplicate_by_source(results, limit, lib) if results else []
        elapsed = time.time() - t0
        if not deduped:
            return f"No context found for: {subject}\nTip: use Grep/Glob as fallback."
    log("context", f"subject={subject!r} scope={scope!r} sources={len(deduped)}/{results.total_found} time={elapsed:.3f}s")

    lines = [f"{len(deduped)} sources for \"{subject}\":\n"]
    for entry in deduped:
        lines.append(_format_source_line(entry))

    return "\n".join(lines)


# ── Drill-down ───────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_expand(
    source: str,
    target: str | None = None,
    query: str | None = None,
    offset: int = 0,
    count: int = 1,
    project: str | None = None,
) -> str:
    """Read content of an indexed file with line numbers.

    Use after rtfm_search. Like Read, but for indexed files.

    Args:
        source: absolute file path (from search results)
        target: jump to section name ("class Foo") or "L120"
        query: filter chunks by relevance within the file
        offset: pagination offset (default 0)
        count: chunks to return, 0 for all remaining (default 1)
        project: another project's index to read instead of this one — its
            name (``"hub"``), or its path when two projects share a name.
    """
    t0 = time.time()
    lib = _get_library(project)
    conn = lib._get_conn()

    offset = _coerce_int(offset, 0)
    count = _coerce_int(count, 1)

    # Resolve path → book (strict matching, no fuzzy)
    book_row = _resolve_book_by_path(conn, source)
    if not book_row:
        return f"File not found in RTFM index: {source}\nTip: use rtfm_search to find indexed files."

    book_slug = book_row["slug"]
    book_title = book_row["title"]
    book_file = book_row["filename"] or ""
    corpus = book_row["corpus"] or ""
    from rtfm.core.pathresolve import owning_root, resolve_source_path
    corpus_roots = lib.list_sync_roots(corpus)
    abs_path = resolve_source_path(book_file, corpus_roots)
    sync_root = owning_root(abs_path, corpus_roots)

    # Content below is read live off disk, so it is never stale — but the
    # chunk boundaries come from the index, and they drift as soon as lines
    # are added above. Repair that before reading; say so if we could not.
    stale_note, repaired = _expand_freshness(abs_path, book_file, corpus,
                                             sync_root, lib)
    if repaired:
        # The book row may have been rebuilt — resolve it again before
        # reading chunks, or we would read the rows we just replaced.
        book_row = _resolve_book_by_path(conn, source) or book_row
        book_slug = book_row["slug"]
        book_title = book_row["title"]

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

        lines = [header, "", _render_chunk(display_path, ls, le,
                                           r0.chunk.content)]
        if stale_note:
            lines.insert(1, stale_note)

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
            lines.append(_render_chunk(display_path, r_ls, r_le,
                                       r.chunk.content))

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

    lines = [header, "", _render_chunk(display_path, ls, first["line_end"],
                                       first["content"])]
    if stale_note:
        lines.insert(1, stale_note)

    # Additional chunks
    for j, row in enumerate(selected_rows[1:], 1):
        s = row["chapter_title"] or ""
        r_ls = row["line_start"]
        r_le = row["line_end"]
        r_line = f"L{r_ls}-{r_le}" if r_ls and r_le else (f"L{r_ls}" if r_ls else "")
        r_idx = chunk_idx + j
        lines.append(f"\n─── {s} [{r_idx + 1}/{total}] — {r_line} ───\n")
        lines.append(_render_chunk(display_path, r_ls, r_le, row["content"]))

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
    """Show graph neighbors of a file (imports, links, includes, citations).

    Args:
        source: book slug or absolute file path
        direction: "outgoing" (deps), "incoming" (dependents), or "both"
        relation_type: filter by "import" | "link" | "include" | "cite"
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

@_admin_tool()
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
    if version is not None:
        version = _coerce_int(version, 0) or None
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
