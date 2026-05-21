"""Worker job handlers — one function per priority level.

P1 ingest : index a single file. Payload schema:
    {"root": <abs source path>, "corpus": <name>,
     "filepath": <relative path>}

P2 embed  : embed a batch of chunks. Payload schema:
    {"chunk_ids": [int, ...], "model": <optional hf or alias>}

P3 OCR    : OCR a page range of a scanned PDF and append its chunks.
            Payload: {"root","corpus","filepath","page_start","page_end"}.
            P1 auto-enqueues these (one per PAGES_PER_OCR_JOB tranche)
            when a PDF is a scan AND ``ocr_fallback: true``. Default
            backend is tesseract (fast on CPU, no OOM); marker is opt-in
            via ``ocr_backend: marker``.
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

# A scanned book is OCR'd in tranches of this many pages — one P3 job
# each — so a 600-page book becomes ~12 short, independently-resumable
# jobs instead of one ~hour-long block that monopolises the worker.
PAGES_PER_OCR_JOB = 50


def enqueue_ocr_jobs(queue: "Queue", root: str, corpus: str, filepath: str,
                     page_count: int) -> int:
    """Split a scanned PDF into page-range P3 jobs and enqueue them.
    Returns the number of jobs enqueued (deduped against pending).

    Each job payload: {root, corpus, filepath, page_start, page_end}.
    The page range is what makes the OCR resumable per tranche.
    """
    if page_count <= 0:
        return 0
    enq = 0
    start = 1
    while start <= page_count:
        end = min(start + PAGES_PER_OCR_JOB - 1, page_count)
        if queue.enqueue("ocr", {
            "root": root, "corpus": corpus, "filepath": filepath,
            "page_start": start, "page_end": end,
        }) is not None:
            enq += 1
        start = end + 1
    return enq


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
                # Split into page-range tranches so a big scan becomes
                # several short, resumable P3 jobs. page_count comes from
                # the parser (stats["pages"]); fall back to a single job
                # if unknown.
                pages = stats.get("pages") or 0
                if pages > 0:
                    enqueue_ocr_jobs(queue, str(root), corpus, rel, pages)
                else:
                    queue.enqueue("ocr", {
                        "root": str(root), "corpus": corpus, "filepath": rel,
                        "page_start": 1, "page_end": None,
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


def _ocr_config(db_path) -> tuple[str, str]:
    """Read (ocr_backend, ocr_langs) from .rtfm/config.json. Defaults:
    backend 'tesseract' (fast on CPU), langs 'eng+fra'."""
    import json as _json
    from pathlib import Path as _Path
    cfg = _Path(db_path).parent / "config.json"
    backend, langs = "tesseract", "eng+fra"
    if cfg.exists():
        try:
            data = _json.loads(cfg.read_text(encoding="utf-8"))
            backend = data.get("ocr_backend", backend)
            langs = data.get("ocr_langs", langs)
        except Exception:
            pass
    return backend, langs


def handle_ocr(job: Job, worker: "Worker") -> None:
    """P3 — OCR a page range of a scanned PDF and append its chunks.

    Each P3 job covers one page tranche (page_start..page_end), so a
    600-page book is several short, independently-resumable jobs rather
    than one hour-long block. The tranche's chunks are appended to the
    book idempotently (``append_ocr_chunks`` deletes that page range
    first), so a retry never duplicates and other tranches are intact.

    Backend (config ``ocr_backend``):
      - ``tesseract`` (default): pypdfium2 render → tesseract. Fast on
        CPU, no multi-GB models → no OOM/timeout.
      - ``marker``: high quality (GPU recommended), whole file.

    After appending, the new chunks are enqueued for P2 embedding.
    """
    from rtfm.core.sync import _path_to_slug
    from rtfm.parsers.pdf import (
        extract_with_tesseract, extract_with_marker,
        pages_to_chunks, extract_title_from_filename,
    )

    payload = job.payload
    root = Path(payload["root"]).resolve()
    corpus = payload["corpus"]
    rel = payload["filepath"]
    page_start = payload.get("page_start", 1)
    page_end = payload.get("page_end")  # None = to end
    abs_path = root / rel

    if not abs_path.is_file():
        raise FileNotFoundError(f"{abs_path} no longer on disk")
    if abs_path.suffix.lower() != ".pdf":
        raise ValueError(f"P3 OCR only handles .pdf — got {abs_path.suffix}")

    book_slug = _path_to_slug(rel, corpus)
    book_title = extract_title_from_filename(abs_path.stem)
    backend, langs = _ocr_config(worker.db_path)

    # OCR just this tranche.
    if backend == "marker":
        pages = extract_with_marker(abs_path)  # whole file (marker has no range)
    else:
        pages = extract_with_tesseract(
            abs_path, langs=langs, page_start=page_start, page_end=page_end)

    lib = Library(str(worker.db_path))
    try:
        # Ensure the book row exists (P1 created an empty one; if it was
        # cleaned up, recreate via a 0-chunk ingest-less insert).
        existing = lib.list_indexed_files(corpus=corpus).get(rel)
        if not existing:
            lib.set_sync_root(corpus, str(root))
            lib.update_indexed_file(
                filepath=rel, file_hash=_compute_hash(abs_path),
                corpus=corpus, book_slug=book_slug,
                file_size=abs_path.stat().st_size)
        # Make sure a book row exists for append.
        if not lib._get_conn().execute(
                "SELECT 1 FROM books WHERE slug=?", (book_slug,)).fetchone():
            lib._get_conn().execute(
                "INSERT INTO books (slug, title, filename, corpus, indexed_at) "
                "VALUES (?,?,?,?,datetime('now'))",
                (book_slug, book_title, rel, corpus))
            lib._get_conn().commit()

        chunks = list(pages_to_chunks(
            pages, book_slug, book_title, rel,
            ext_meta={"ocr": backend}))

        lo = page_start
        hi = page_end if page_end is not None else (
            max((c.page_start for c in chunks), default=page_start))
        result = lib.append_ocr_chunks(book_slug, chunks, lo, hi)

        # Enqueue P2 for the newly-added chunks of this tranche only.
        if result.get("chunks", 0) > 0:
            new_ids = [
                r["id"] for r in lib._get_conn().execute(
                    """SELECT c.id FROM chunks c JOIN books b ON c.book_id=b.id
                       WHERE b.slug=? AND c.chapter_num BETWEEN ? AND ?""",
                    (book_slug, lo, hi)).fetchall()
            ]
            if new_ids:
                queue = Queue(str(worker.db_path))
                try:
                    batches = [new_ids[i:i + EMBED_BATCH_SIZE]
                               for i in range(0, len(new_ids), EMBED_BATCH_SIZE)]
                    queue.enqueue_many("embed", [{"chunk_ids": b} for b in batches])
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
