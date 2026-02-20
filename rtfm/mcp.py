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
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rtfm")

# ── Library singleton ─────────────────────────────────────────────────────

_library = None


def _get_library():
    """Return (and lazily create) the Library singleton."""
    global _library
    if _library is None:
        from rtfm.core.library import Library
        db_path = os.environ.get("RTFM_DB", "library.db")
        _library = Library(db_path)
    return _library


# ── Read tools ────────────────────────────────────────────────────────────

@mcp.tool()
def rtfm_search(
    query: str,
    limit: int = 10,
    corpus: str | None = None,
    search_type: str = "hybrid",
) -> str:
    """Search the document library. Returns ranked chunks with source and page.

    Args:
        query: The search query.
        limit: Maximum number of results (default 10).
        corpus: Filter by corpus name (optional).
        search_type: One of "fts", "semantic", or "hybrid" (default).
    """
    lib = _get_library()

    try:
        if search_type == "semantic":
            results = lib.semantic_search(query, limit=limit, corpus=corpus)
        elif search_type == "fts":
            results = lib.search(query, limit=limit, corpus=corpus)
        else:
            results = lib.hybrid_search(query, limit=limit, corpus=corpus)
    except Exception:
        # Fallback to FTS if embeddings are not available
        results = lib.search(query, limit=limit, corpus=corpus)

    if not results:
        return f"No results found for: {query}"

    lines = [f"Found {results.total_found} results for \"{query}\":\n"]
    for r in results:
        lines.append(f"[{r.rank}] {r.source} ({r.page}) — score: {r.score:.3f}")
        if r.tags:
            lines.append(f"    Tags: {', '.join(r.tags)}")
        lines.append(f"    {r.content}\n")

    return "\n".join(lines)


@mcp.tool()
def rtfm_stats() -> str:
    """Get library statistics: total chunks, books, corpora, tag and embedding coverage."""
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
    lib = _get_library()
    tags = lib.list_tags(corpus=corpus)
    if not tags:
        return "No tags found."
    lines = [f"{t['tag']}: {t['count']} chunks" for t in tags]
    return "\n".join(lines)


@mcp.tool()
def rtfm_books(corpus: str | None = None) -> str:
    """List all indexed books/documents.

    Args:
        corpus: Filter by corpus name (optional).
    """
    lib = _get_library()
    books = lib.list_books(corpus=corpus)
    if not books:
        return "No books indexed."
    lines = []
    for b in books:
        prefix = f"[{b['corpus']}] " if b.get("corpus") else ""
        lines.append(f"{prefix}{b['title']}: {b['chunk_count']} chunks")
    return "\n".join(lines)


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
    lib = _get_library()

    ext_set = None
    if extensions:
        ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                   for e in extensions.split(",")}

    result = lib.sync(
        root=Path(path),
        corpus=corpus,
        extensions=ext_set,
        generate_embeddings=False,  # Don't block on embeddings in MCP
    )

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
    lib = _get_library()
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"

    try:
        stats = lib.ingest(p, corpus=corpus)
        return f"Ingested {p.name}: {stats['chunks']} chunks, {stats['chars']:,} chars"
    except Exception as exc:
        return f"Error ingesting {path}: {exc}"


@mcp.tool()
def rtfm_tag_chunks(chunk_ids: str, tags: str) -> str:
    """Add tags to specific chunks.

    Args:
        chunk_ids: Comma-separated chunk IDs to tag.
        tags: Comma-separated tags to add.
    """
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

    try:
        info = discover(path)
        return format_discover(info)
    except Exception as exc:
        return f"Error scanning {path}: {exc}"


@mcp.tool()
def rtfm_context(
    subject: str,
    scope: str | None = None,
    limit: int = 5,
) -> str:
    """Get relevant context for a subject. Use this BEFORE Grep/Glob.

    Progressive disclosure: searches the indexed knowledge base and returns
    the most relevant chunks. If the subject is a file path that exists but
    isn't indexed, it will be indexed on-the-fly.

    Args:
        subject: Topic, concept, file path, or question to get context for.
        scope: Optional corpus filter.
        limit: Maximum chunks to return (default 5).
    """
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

    # Hybrid search across all corpora (or scoped)
    try:
        results = lib.hybrid_search(subject, limit=limit, corpus=scope)
    except Exception:
        results = lib.search(subject, limit=limit, corpus=scope)

    if not results:
        return f"No context found for: {subject}\nTip: use Grep/Glob as fallback."

    lines = [f"Context for \"{subject}\" ({results.total_found} matches):\n"]
    for r in results:
        lines.append(f"--- [{r.rank}] {r.source} ({r.page}) ---")
        # Truncate long chunks to keep output manageable
        content = r.content
        if len(content) > 1500:
            content = content[:1500] + "..."
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


# ── entry point ───────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
