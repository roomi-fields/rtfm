"""Worker job handlers — one function per priority level.

P1 ingest : index a single file. Payload schema:
    {"root": <abs source path>, "corpus": <name>,
     "filepath": <relative path>}

P2 embed  : embed a batch of chunks. Payload schema:
    {"chunk_ids": [int, ...], "model": <optional hf or alias>}

P3 OCR    : re-ingest a scanned PDF with the marker backend so the
            text layer is reconstructed from page images. Payload:
                {"root": ..., "corpus": ..., "filepath": ...}
            P1 auto-enqueues this when a PDF produces zero chunks
            AND ``ocr_fallback: true`` is set in ``.rtfm/config.json``.
            The marker run itself happens in an isolated subprocess
            (see :mod:`rtfm.parsers.pdf`) so its 3–8 GB of model state
            is reclaimed by the OS between PDFs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from rtfm.core.library import Library
from rtfm.core.queue import Queue, Job

if TYPE_CHECKING:
    from rtfm.core.worker import Worker


# How many chunks fit into a single P2 embed job. Tuned so a batch
# runs in seconds (responsive preemption by an incoming P1) while
# still amortising the fastembed startup cost.
EMBED_BATCH_SIZE = 64

# Deterministic scan threshold: a PDF whose extractable text density is
# below this many characters per page is treated as a scanned image
# (needs OCR). Born-digital PDFs run into the hundreds/thousands of
# chars per page; scans yield ~0. This replaces the old "0 chunks"
# heuristic, which missed scans that produced 1-2 junk chunks.
SCAN_CHARS_PER_PAGE = 20


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
        stats = lib.ingest(
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

        # Health signal: detect scanned-image PDFs deterministically by
        # text density (chars per page). Born-digital PDFs run into the
        # hundreds/thousands of chars/page; a scan yields ~0. This
        # catches scans that produced 1-2 junk chunks (which the old
        # ``chunks == 0`` test missed). When OCR fallback is on, enqueue
        # a lower-priority P3 to re-ingest with marker. P3 sits below
        # any pending P1/P2 so editing a note is never blocked by OCR.
        is_scan = (
            abs_path.suffix.lower() == ".pdf"
            and _pdf_is_scan(stats)
            # Don't queue OCR for a .pdf that isn't really a PDF (e.g. an
            # EPUB/zip saved with the wrong extension) — marker uses the
            # same pdfium backend and would fail too. `rtfm doctor
            # --fix-extensions` is the right tool for those.
            and _is_real_pdf(abs_path)
        )
        if is_scan and _ocr_enabled(worker.db_path):
            queue = Queue(str(worker.db_path))
            try:
                queue.enqueue("ocr", {
                    "root": str(root), "corpus": corpus, "filepath": rel,
                })
            finally:
                queue.close()
            return  # no P2 for a zero-chunk book — wait until P3 fills it

        # Enqueue follow-up P2 embed jobs for the chunks just created.
        # Splitting into fixed-size batches keeps each P2 short enough
        # that a fresh P1 (e.g. file edited mid-run) is picked up at
        # the next job boundary — that is the cooperative preemption
        # the user asked for in the worker design.
        chunk_ids = lib.chunk_ids_for_book(book_slug)
        if chunk_ids:
            queue = Queue(str(worker.db_path))
            try:
                batches = [chunk_ids[i:i + EMBED_BATCH_SIZE]
                           for i in range(0, len(chunk_ids), EMBED_BATCH_SIZE)]
                queue.enqueue_many("embed",
                                   [{"chunk_ids": b} for b in batches])
            finally:
                queue.close()
    finally:
        lib.close()


def _pdf_is_scan(stats: dict) -> bool:
    """Deterministic scan test from ingest stats.

    Uses chars-per-page when the parser reported a page count
    (``stats["pages"]``); otherwise falls back to the old
    zero-chunk signal. A PDF below :data:`SCAN_CHARS_PER_PAGE`
    chars/page is treated as a scanned image needing OCR.
    """
    chars = stats.get("chars", 0)
    pages = stats.get("pages")
    if pages and pages > 0:
        return (chars / pages) < SCAN_CHARS_PER_PAGE
    # No page count → can only tell a totally-empty extraction.
    return stats.get("chunks", 0) == 0


def _is_real_pdf(path: Path) -> bool:
    """True if the file's magic bytes say it really is a PDF. Guards
    against OCR-queuing a mislabeled EPUB/zip/html."""
    try:
        from rtfm.core.sniff import detect_real_format
        return detect_real_format(path) == "pdf"
    except Exception:
        return True  # on any sniff failure, don't block the normal path


def _ocr_enabled(db_path) -> bool:
    """Read ``ocr_fallback`` from ``.rtfm/config.json``. False if the
    file is missing or unreadable — we never silently OCR by default."""
    import json as _json
    from pathlib import Path as _Path
    cfg = _Path(db_path).parent / "config.json"
    if not cfg.exists():
        return False
    try:
        return bool(_json.loads(cfg.read_text(encoding="utf-8"))
                    .get("ocr_fallback", False))
    except Exception:
        return False


def handle_ocr(job: Job, worker: "Worker") -> None:
    """P3 — re-ingest a scanned PDF with the marker (OCR) backend.

    Called when P1 detected a zero-chunk PDF and ``ocr_fallback`` is
    on. Drops whatever empty book P1 left behind, then re-ingests the
    same file forcing ``PDFParser(backend="marker")``. Marker itself
    runs in a one-shot subprocess (rtfm/parsers/pdf.py), so its RAM
    footprint is reclaimed between PDFs.

    After a successful OCR ingest, the chunks need embeddings — we
    enqueue P2 batches for them, same as the P1 path.
    """
    from rtfm.core.sync import _path_to_slug
    from rtfm.parsers.pdf import PDFParser

    payload = job.payload
    root = Path(payload["root"]).resolve()
    corpus = payload["corpus"]
    rel = payload["filepath"]
    abs_path = root / rel

    if not abs_path.is_file():
        raise FileNotFoundError(f"{abs_path} no longer on disk")
    if abs_path.suffix.lower() != ".pdf":
        raise ValueError(f"P3 OCR only handles .pdf — got {abs_path.suffix}")

    book_slug = _path_to_slug(rel, corpus)
    file_hash = _compute_hash(abs_path)

    lib = Library(str(worker.db_path))
    try:
        # Drop any empty book P1 left behind for this file. Cascade
        # cleans up chunks/embeddings/edges/file_versions.
        lib.delete_book(book_slug)

        stats = lib.ingest(
            abs_path, corpus=corpus,
            parser=PDFParser(backend="marker"),
            metadata={"book_slug": book_slug, "source_file": rel},
        )
        lib.update_indexed_file(
            filepath=rel, file_hash=file_hash,
            corpus=corpus, book_slug=book_slug,
            file_size=abs_path.stat().st_size,
        )

        # Even after OCR, marker may legitimately fail on a corrupted
        # PDF — surface that as a job failure rather than queueing P2
        # for a still-empty book.
        if stats.get("chunks", 0) == 0:
            raise RuntimeError(
                f"marker produced 0 chunks for {rel} — file may be "
                "corrupted or genuinely empty"
            )

        # Same P2 follow-up logic as P1.
        chunk_ids = lib.chunk_ids_for_book(book_slug)
        if chunk_ids:
            queue = Queue(str(worker.db_path))
            try:
                batches = [chunk_ids[i:i + EMBED_BATCH_SIZE]
                           for i in range(0, len(chunk_ids), EMBED_BATCH_SIZE)]
                queue.enqueue_many("embed",
                                   [{"chunk_ids": b} for b in batches])
            finally:
                queue.close()
    finally:
        lib.close()


def handle_embed(job: Job, worker: "Worker") -> None:
    """P2 — embed a batch of chunks identified by id.

    The batch size is bounded by :data:`EMBED_BATCH_SIZE` at enqueue
    time, so this handler runs in seconds rather than minutes. The
    library skips chunks that already carry an embedding for the active
    model, so retries are idempotent.
    """
    payload = job.payload
    chunk_ids = payload.get("chunk_ids") or []
    model = payload.get("model")  # None → DB-active or DEFAULT

    if not chunk_ids:
        return  # Nothing to do; job is recorded as done.

    lib = Library(str(worker.db_path))
    try:
        lib.embed_chunks_by_id(chunk_ids, model=model)
    finally:
        lib.close()


# Dispatch table consumed by :func:`rtfm.core.worker.Worker`.
HANDLERS = {
    "ingest": handle_ingest,
    "embed": handle_embed,
    "ocr": handle_ocr,
}
