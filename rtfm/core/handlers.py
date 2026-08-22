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
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rtfm.core.library import Library
from rtfm.core.queue import Queue, Job

if TYPE_CHECKING:
    from rtfm.core.worker import JobContext


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

# A file modified within this many seconds is young enough that it might
# still be in the middle of being written (a download landing, an rsync,
# an editor's atomic save that isn't atomic on this filesystem). Only for
# such young files do we pay the cost of the stability double-stat below;
# anything older is settled and ingested straight away.
INGEST_SETTLE_GRACE_SECONDS = 30

# A scanned book is OCR'd in tranches of this many pages — one P3 job
# each — so a 600-page book becomes ~12 short, independently-resumable
# jobs instead of one ~hour-long block that monopolises the worker.
PAGES_PER_OCR_JOB = 50

# Above this many ``remove`` jobs enqueued by a single ``scan``, the
# handler also schedules a one-shot VACUUM. Big deletions leave lots
# of free pages in the SQLite file; without a VACUUM the DB stays
# bloated. Threshold tuned so a handful of removed files never triggers
# it (vacuum is exclusive-lock + slow), but a real bulk wipe does.
AUTO_VACUUM_AFTER_REMOVES = 200


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


def _looks_like_partial_write(path: Path, since_mtime: float,
                              since_size: int) -> bool:
    """True if *path* looks like it was still being written when we parsed it.

    Called only after a parse actually failed, so it costs nothing on the
    (overwhelmingly common) success path. A download or ``rsync`` that lands
    mid-scan yields a truncated file — the parser raises (e.g. ``PDFium:
    Data format error``) and the job is marked failed for good even though
    the file is perfect seconds later. Two signals say "still in flight":
    the file changed since we started, or it was last modified within
    :data:`INGEST_SETTLE_GRACE_SECONDS` and is *still* changing across a
    short observation.
    """
    try:
        st = path.stat()
    except OSError:
        return False
    if st.st_mtime != since_mtime or st.st_size != since_size:
        return True  # changed under us mid-parse
    if time.time() - st.st_mtime > INGEST_SETTLE_GRACE_SECONDS:
        return False  # settled well before we touched it — a genuine failure
    time.sleep(0.6)
    try:
        st2 = path.stat()
    except OSError:
        return False
    return st2.st_size != st.st_size or st2.st_mtime != st.st_mtime


def _compute_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def handle_scan(job: Job, worker: "JobContext") -> None:
    """P1 — scan one source root and fan out per-file work to the queue.

    Replaces the legacy inline ``sync()`` for the worker path: instead of
    parsing files itself, the scan computes a diff and emits child jobs:

    * cross-corpus moves and same-corpus moves are applied inline — they
      are cheap (DB row updates only, no parsing, no re-embedding).
    * removals → one ``remove`` job per file, guarded by the same
      mass-removal circuit breaker that protects ``sync()``: if a batch
      is both big in absolute terms (>= ``REMOVE_CIRCUIT_MIN_FILES``)
      *and* a large fraction of the corpus (>= ``REMOVE_CIRCUIT_RATIO``),
      the whole batch is refused — the scan is almost certainly
      incomplete (mount hiccup, external reorg in progress). Pass
      ``force_remove=True`` in the payload to override deliberately.
    * additions + modifications → one ``ingest`` job per file.

    When a single scan enqueues more than :data:`AUTO_VACUUM_AFTER_REMOVES`
    remove jobs, a one-shot ``vacuum`` job is also queued so the freed
    pages get reclaimed once the removes drain.

    Payload schema::

        {
          "root": "<absolute path of source root>",
          "corpus": "<corpus name>",
          "extensions": "csv,txt" | None,   # optional override
          "force_remove": False,             # optional, default False
          "honor_gitignore": True            # optional, default True.
                                             # Set to False to index files
                                             # that are gitignored — useful
                                             # for private corpora (copyrighted
                                             # material kept out of git).
        }
    """
    from rtfm.core.sync import (
        confirm_removals, _path_to_slug, compute_diff, scan_directory,
    )

    payload = job.payload or {}
    root_raw = payload.get("root")
    corpus = payload.get("corpus")
    if not root_raw or not corpus:
        raise ValueError("scan payload requires 'root' and 'corpus'")

    root = Path(root_raw).resolve()
    if not root.is_dir():
        worker._log(f"scan [{corpus}] {root}: not a directory, skipped")
        return

    # Build the extension override set (None → registry default).
    ext_set: set[str] | None = None
    ext_raw = payload.get("extensions")
    if ext_raw:
        ext_set = {
            e.strip() if e.strip().startswith(".") else f".{e.strip()}"
            for e in ext_raw.split(",") if e.strip()
        } or None

    force_remove = bool(payload.get("force_remove", False))
    honor_gitignore = bool(payload.get("honor_gitignore", True))
    include = payload.get("include") or None
    exclude = payload.get("exclude") or None

    lib = Library(str(worker.db_path))
    try:
        lib.set_sync_root(corpus, str(root))
        files_on_disk = scan_directory(root, ext_set,
                                       honor_gitignore=honor_gitignore,
                                       include=include, exclude=exclude)
        indexed = lib.list_indexed_files(corpus=corpus)
        indexed_global = lib.list_indexed_files()
        diff = compute_diff(
            files_on_disk, indexed, root,
            indexed_global=indexed_global,
            current_corpus=corpus,
            known_failures=lib.list_ingest_failures(corpus=corpus),
        )

        # Cross-corpus moves: cheap, in-place — no parsing, no re-embed.
        cross_moved = 0
        for old_rel, _old_corpus, new_path in diff.cross_moved:
            try:
                new_rel = str(new_path.relative_to(root))
            except ValueError:
                new_rel = str(new_path)
            try:
                new_slug = _path_to_slug(new_rel, corpus)
                if lib.move_file(old_rel, new_rel, new_slug,
                                 new_corpus=corpus):
                    cross_moved += 1
            except Exception as exc:
                worker._log(f"scan [{corpus}] cross-move error {old_rel}: {exc}")

        # Same-corpus moves: same content, new path within the corpus.
        # Mirrors the inline branch in :func:`rtfm.core.sync.sync` so the
        # worker doesn't pointlessly re-ingest a renamed file.
        moved = 0
        for old_rel, new_path in diff.moved:
            try:
                new_rel = str(new_path.relative_to(root))
            except ValueError:
                new_rel = str(new_path)
            try:
                new_slug = _path_to_slug(new_rel, corpus)
                if lib.move_file(old_rel, new_rel, new_slug):
                    moved += 1
            except Exception as exc:
                worker._log(f"scan [{corpus}] move error {old_rel}: {exc}")
    finally:
        lib.close()

    # Removals → ``remove`` jobs, each confirmed against the live filesystem
    # (see :func:`confirm_removals`): a file is only enqueued for removal when
    # it is genuinely absent and its location is readable. A file that
    # reappeared, or one whose mount went dark, is kept.
    queue = Queue(str(worker.db_path))
    remove_jobs = 0
    skipped_removed = 0
    try:
        if diff.removed:
            confirmed, kept = confirm_removals(
                root, list(diff.removed), force=force_remove)
            skipped_removed = len(kept)
            if confirmed:
                payloads = [{"filepath": rel, "corpus": corpus}
                            for rel in confirmed]
                inserted, _ = queue.enqueue_many("remove", payloads)
                remove_jobs = inserted

        # Additions + modifications → ``ingest`` jobs.
        ingest_jobs = 0
        ingest_payloads: list[dict] = []
        for fpath in diff.added + diff.modified:
            try:
                rel = str(fpath.relative_to(root))
            except ValueError:
                rel = str(fpath)
            ingest_payloads.append({
                "root": str(root), "corpus": corpus, "filepath": rel,
            })
        if ingest_payloads:
            inserted, _ = queue.enqueue_many("ingest", ingest_payloads)
            ingest_jobs = inserted

        # Big-scan auto-vacuum: schedule a one-shot VACUUM so the freed
        # pages get reclaimed once the removes drain.
        if remove_jobs > AUTO_VACUUM_AFTER_REMOVES:
            queue.enqueue("vacuum", {"reason": "auto-after-big-scan-remove"})
    finally:
        queue.close()

    worker._log(
        f"scan [{corpus}] +{ingest_jobs} ~{moved + cross_moved} "
        f"-{remove_jobs} (skip_removed={skipped_removed})"
    )


def handle_ingest(job: Job, worker: "JobContext") -> None:
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

    # Remember the file's stamp before we parse it, so that if the parse
    # fails we can tell a genuinely-broken file from one that was still
    # being written under us (see the except below).
    try:
        _st_before = abs_path.stat()
        _mtime_before, _size_before = _st_before.st_mtime, _st_before.st_size
    except OSError:
        _mtime_before, _size_before = 0.0, -1

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
        try:
            stats = lib.ingest(
                abs_path, corpus=corpus,
                metadata={"book_slug": book_slug, "source_file": rel},
            )
        except Exception as exc:
            # A parse failure on a file that's still being written (a
            # download/rsync finishing mid-scan) is not a real failure —
            # re-queue it to try again once it settles instead of marking
            # it failed for good. A genuinely-broken file re-raises.
            if not _looks_like_partial_write(abs_path, _mtime_before, _size_before):
                # Remember *this content* failed, so the next scan doesn't
                # offer the same broken file again — and the one after that,
                # and the one after that.
                try:
                    lib.record_ingest_failure(
                        rel, corpus, file_hash,
                        abs_path.stat().st_size if abs_path.exists() else 0,
                        f"{type(exc).__name__}: {exc}")
                except Exception:
                    pass  # bookkeeping must not mask the real error
            if _looks_like_partial_write(abs_path, _mtime_before, _size_before):
                q = Queue(str(worker.db_path))
                try:
                    q.enqueue("ingest", {
                        "root": str(root), "corpus": corpus, "filepath": rel,
                    })
                finally:
                    q.close()
                worker._log(
                    f"ingest [{corpus}] {rel}: file still being written — "
                    f"re-queued")
                return
            raise
        lib.update_indexed_file(
            filepath=rel,
            file_hash=file_hash,
            corpus=corpus,
            book_slug=book_slug,
            file_size=abs_path.stat().st_size,
        )
        # It parsed — any past failure for this path is history.
        try:
            lib.clear_ingest_failure(rel, corpus)
        except Exception:
            pass

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


def handle_ocr(job: Job, worker: "JobContext") -> None:
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


def handle_vacuum(job: Job, worker: "JobContext") -> None:
    """P4 — VACUUM the SQLite DB to reclaim space from deleted rows.

    VACUUM rebuilds the file, so it needs an EXCLUSIVE lock on the
    whole DB. We open a *fresh* direct connection (not via Library,
    whose long-lived connections would block VACUUM) and run it in
    autocommit mode (``isolation_level=None``) — VACUUM cannot run
    inside a transaction. A 60s ``busy_timeout`` gives other writers
    a chance to finish; if the lock still can't be taken, the
    ``OperationalError`` propagates and the worker marks the job
    ``failed`` — the user retries later.

    Payload is empty by design (vacuum is global). An optional
    ``"reason"`` key (free text) is echoed in the log line.
    """
    import sqlite3

    reason = (job.payload or {}).get("reason") or "explicit"
    db_path = Path(worker.db_path)
    before_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0.0

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute("VACUUM")
    finally:
        conn.close()

    after_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0.0
    worker._log(f"vacuum done — {before_mb:.0f}M → {after_mb:.0f}M ({reason})")


def handle_remove(job: Job, worker: "JobContext") -> None:
    """P2 — remove a single file from the index.

    Inverse of :func:`handle_ingest`: drops the book row (its chunks
    follow via FK cascade) and the ``indexed_files`` tracking entry.
    Payload schema: ``{"filepath": <rel path>, "corpus": <name>}``.

    A filepath that is not in ``indexed_files`` is logged as a no-op
    rather than raising — the user may have already removed it, or the
    queue may be replaying a stale event after a manual ``rtfm reindex``.
    """
    payload = job.payload
    corpus = payload["corpus"]
    rel = payload["filepath"]

    lib = Library(str(worker.db_path))
    try:
        removed = lib.remove_file(rel)
        if removed:
            worker._log(f"remove [{corpus}] {rel}")
        else:
            worker._log(f"remove [{corpus}] {rel}: not in index")
    finally:
        lib.close()


def handle_reconcile(job: Job, worker: "JobContext") -> None:
    """P4 — self-heal pass: purge orphan embeddings, re-queue un-embedded
    chunks.

    Thin wrapper around :func:`rtfm.core.reconcile.reconcile`, which holds
    the actual logic (and is also covered by ``test_reconcile.py``).

    Payload schema:
        ``{}`` — just reconcile.
        ``{"vacuum": True}`` — opt-in: after reconciliation, also enqueue a
        P4 ``vacuum`` job (only if anything was purged — vacuuming an
        unchanged DB is pure overhead).
    """
    from rtfm.core.reconcile import reconcile

    stats = reconcile(worker.db_path, log=worker._log)
    worker._log(
        f"reconcile: purged {stats['orphans_purged']} orphan(s), "
        f"{stats.get('fossils_purged', 0)} fossil(s), "
        f"re-queued {stats['chunks_requeued']} chunk(s) "
        f"as {stats['embed_jobs']} P5 batch(es)"
    )
    if job.payload.get("vacuum") and stats["orphans_purged"] > 0:
        queue = Queue(str(worker.db_path))
        try:
            queue.enqueue("vacuum", {"reason": "after-reconcile"})
        finally:
            queue.close()


def handle_embed(job: Job, worker: "JobContext") -> None:
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
    "scan": handle_scan,
    "remove": handle_remove,
    "ingest": handle_ingest,
    "reconcile": handle_reconcile,
    "vacuum": handle_vacuum,
    "embed": handle_embed,
    "ocr": handle_ocr,
}
