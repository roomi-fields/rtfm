"""Worker job handlers — one function per priority level.

P1 ingest : index a single file. Payload schema:
    {"root": <abs source path>, "corpus": <name>,
     "filepath": <relative path>, "extensions": <comma list or null>}

Phase 1 of the queue/worker redesign ships P1 only. Embed (P2) and
OCR (P3) handlers will be added incrementally.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from rtfm.core.library import Library
from rtfm.core.queue import Job

if TYPE_CHECKING:
    from rtfm.core.worker import Worker


def _compute_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def handle_ingest(job: Job, worker: "Worker") -> None:
    """P1 — ingest a single file.

    Equivalent to the per-file path in :func:`rtfm.core.sync.sync`
    (added/modified branch): parse → ingest into ``books`` + ``chunks``
    → upsert tracking row in ``indexed_files``.

    Errors leave the file unindexed and the job marked ``failed`` by
    the worker loop; the user can retry via ``rtfm queue retry-failed``.
    """
    payload = job.payload
    root = Path(payload["root"]).resolve()
    corpus = payload["corpus"]
    rel = payload["filepath"]
    abs_path = root / rel

    if not abs_path.is_file():
        raise FileNotFoundError(f"{abs_path} no longer on disk")

    # Slug + ingest go through the same helper :func:`rtfm.core.sync._path_to_slug`
    # used by the legacy inline sync, so on-disk slugs stay stable.
    from rtfm.core.sync import _path_to_slug
    book_slug = _path_to_slug(rel, corpus)

    lib = Library(str(worker.db_path))
    try:
        # Persist the corpus root once per (corpus, root) so future
        # MCP path resolution still works.
        lib.set_sync_root(corpus, str(root))

        # If this is an update of an already-indexed file, preserve a
        # version snapshot before re-ingesting — same as the inline
        # sync does in the modified-branch.
        existing = lib.list_indexed_files(corpus=corpus).get(rel)
        if existing and existing.get("book_slug"):
            old_slug = existing["book_slug"]
            old_hash = existing.get("file_hash", "")
            try:
                lib.save_file_version(old_slug, old_hash, prune_limit=50)
            except Exception:
                pass  # versioning is best-effort
            if old_slug != book_slug:
                # Slug format changed (rare): drop the old book row so
                # the new ingest doesn't UNIQUE-collide.
                lib.delete_book(old_slug)

        file_hash = _compute_hash(abs_path)
        lib.ingest(
            abs_path, corpus=corpus,
            metadata={"book_slug": book_slug, "source_file": rel},
        )
        lib.update_indexed_file(
            filepath=rel,
            file_hash=file_hash,
            corpus=corpus,
            book_slug=book_slug,
            file_size=abs_path.stat().st_size,
        )
    finally:
        lib.close()


# Dispatch table consumed by :func:`rtfm.core.worker.Worker`.
HANDLERS = {
    "ingest": handle_ingest,
}
