---
title: RTFM Changelog
description: >-
  Release notes for RTFM (rtfm-ai) — every version since 0.1.0 with
  added features, bug fixes, and breaking changes.
---

# Changelog

## [0.20.0] — 2026-05-24

### Added — memory guard prevents OOM-kill of the whole worker

A pathological PDF once made the worker consume ~13 GB of RSS, which triggered the kernel OOM-killer; the worker died without a graceful exit, lost in-flight state, and required manual recovery. Two layers of defence now:

- **`RLIMIT_AS` cap at startup** (default 8 GB, configurable via `RTFM_WORKER_MEMORY_LIMIT_GB`). The next allocation past the cap raises `MemoryError` — catchable by the per-job handler, which marks the job `failed` and moves on. Converts a kernel `SIGKILL` into a normal Python exception.
- **RSS polling at every idle tick**. Above `WORKER_RSS_EXIT_MB` (5 GB) the worker exits cleanly; the next hook respawns a fresh process. Catches slow leaks that wouldn't trip the per-alloc cap.

Opt out with `RTFM_WORKER_MEMORY_LIMIT_GB=0` when running marker-pdf, whose ML models legitimately need 3-8 GB.

Test suite: 568 passed.

## [0.19.0] — 2026-05-23

### Added — worker self-restarts after a version upgrade

A long-running worker keeps the code it imported into memory at startup; a fresh `pip install --force-reinstall` (or `pipx install`) writes new files on disk but the running worker silently ignores them. Bit this project once already — workers from 0.15 era kept handling jobs while 0.17 / 0.18 lived on disk, so the new `handle_scan` never fired and ~1200 PDFs sat unindexed.

Now at every idle tick the worker compares `importlib.metadata.version("rtfm-ai")` against the version it captured at startup. If they diverge, it logs `version changed on disk, exiting for restart` and exits cleanly. The next hook (UserPromptSubmit / PostToolUse) calls `ensure_worker_running`, which spawns a fresh worker with the up-to-date code. Source-checkout developers are unaffected — when either side reports `"unknown"` (no installed metadata) the check is a no-op.

`rtfm check`, the CLI command introduced earlier today, also gains the `ocr_attempted` / `ocr_pending` / `ocr_failed` triplet (and the same `ingest_*` split) so consumers can route differently: `pending` → wait, `failed` → escalate to human, neither → fully done.

Test suite: 566 passed.

## [0.18.0] — 2026-05-23

### Changed — every DB write now goes through the worker (no more inline path)

The CLI, the hooks and the slash commands stop touching the DB directly. They become *producers* that enqueue jobs into a single 7-level priority queue; the worker daemon is the only consumer. This removes a whole class of bugs (concurrent writes from different RTFM versions, inline OCR that blocks the user's terminal for hours, hooks that ran a full destructive sync on every prompt) and makes the system observable: a `rtfm sync` shows live queue progress instead of a long opaque blocking call.

Seven priority lanes, lowest number wins:

- **P0** = explicit user (slash commands, manual CLI invocations)
- **P1** = `scan` — detect changes in a source
- **P2** = `remove` — drop a vanished file from the index
- **P3** = `ingest` — parse one file → chunks
- **P4** = `reconcile` / `vacuum` — short maintenance
- **P5** = `embed` — vectorise a batch of chunks
- **P6** = `ocr` — OCR a page-range of a scanned PDF

What changed concretely:

- **New job types**: `scan`, `remove`, `reconcile`, `vacuum`, each with its own handler in `rtfm/core/handlers.py`. The `scan` handler subsumes the old `_scan_once` method on the worker and the destructive `sync()` removed-path — including the mass-removal circuit breaker from 0.16.0.
- **Worker periodic ticks** (`_maybe_scan`, `_maybe_reconcile`) now just enqueue jobs. The work happens in handlers. Queue dedup (`UNIQUE(type, payload) WHERE status='pending'`) keeps the queue clean across repeated ticks.
- **CLI** — every mutating command (`rtfm sync`, `rtfm gc`, `rtfm doctor`, `rtfm reindex`, `rtfm vacuum`, `rtfm backfill-pages`) becomes "enqueue P0 + watch progress + exit". `--background` skips the watching loop. `rtfm sync --inline` is gone (the inline path is gone). `cli.py` shrank 2587 → 2274 lines.
- **DB migration is automatic**: pre-0.18 DBs had a `CHECK(type IN ('ingest','embed','ocr'))` on `work_queue` that blocked the new job types. The first 0.18+ `Queue` open rebuilds the table in place, rows preserved.
- **Docs**: `docs/architecture.md` rewritten for the new model (priority table, handler list, periodic-tick semantics).

Test suite: 552 → 565 passed (24 skipped).

## [0.17.0] — 2026-05-23

### Fixed — stop indexing our own state directory (feedback loop)

Some live DBs ballooned absurdly (RTFM 2.3 GB for 441 books, tradingbot 8.5 GB for 59 books). Forensics: the parser registry was happily ingesting `.rtfm/library.db` itself — every chunk of the index became more rows, which the next sync re-ingested, snowballing. New default excludes block this and other generic noise:

- `.rtfm/` — RTFM's own state dir (library.db, logs, locks). Indexing it is always a bug.
- `.cache/` — generic cache dirs (import caches, browser caches, build caches): always noise.
- **Honor root `.gitignore`** — when `pathspec` is installed (now a core dep), `scan_directory()` filters out anything matched by the project's own `.gitignore`. Reuses what the user has already declared as ignored artifacts rather than maintaining a parallel exclude list. Nested `.gitignore` files in subdirs are not walked (root-only) — covers the vast majority of real-world setups while keeping the scan simple. Opt out with `honor_gitignore=False`.

To purge the historical garbage on an already-polluted DB, run once: `rtfm sync --force-remove` (the mass-removal circuit breaker from 0.16 will otherwise block the cleanup since 90%+ of "files" disappear under the new excludes).

## [0.16.0] — 2026-05-21

### Fixed — sync no longer wipes a corpus on an incomplete scan (data-loss bug)

A live corpus on NTFS-via-WSL lost ~500 fully-indexed PDFs (and their embeddings). Root cause: the session hooks ran a **full `sync()` of every source on every prompt**. While an external process was reorganising files on flaky NTFS, a scan caught a moment when hundreds of files were temporarily absent → `sync()` flagged them `removed` → `delete_book` destroyed their chunks; a later `gc` then purged the now-orphaned embeddings. The background worker was never the cause — its idle-scan only ever *adds*, never deletes.

- **Mass-removal circuit breaker** in `sync()`: refuses a removal batch that is both large (≥ `REMOVE_CIRCUIT_MIN_FILES`, default 25) **and** a big fraction of the corpus (≥ `REMOVE_CIRCUIT_RATIO`, default 25%) — the signature of an incomplete scan, not real deletions. Index left intact; a warning is surfaced. Override with `rtfm sync --force-remove` (or `force_remove=True`) for deliberate bulk deletes.
- **File-list mode never deletes**: when `sync(files=[...])` is given a partial list, files not in that list are no longer treated as removed (their absence from a partial list is not evidence of deletion).

### Changed — lightweight hooks: the worker does the work

The Claude Code hooks no longer run a full `sync()` (which re-MD5'd the entire corpus on every prompt — slow on NTFS, and the trigger for the data-loss bug above). New design:

- **UserPromptSubmit / Stop** → only revive the background worker if it died. No scan, no hashing, nothing on the user's hot path.
- **PostToolUse (Write\|Edit\|MultiEdit)** → enqueue *the one file* the agent just wrote as a P1 ingest job (mapped to its source/corpus, gated on a registered parser). Non-destructive: only ever adds work.
- Discovery of new/changed/moved files across all sources is the worker's non-destructive idle-scan. New `install_hook` registers all three; re-running is idempotent.

## [0.15.0] — 2026-05-21

### Changed — OCR: tesseract backend by default, split into page tranches

marker (Surya models) is excellent but unusable for OCR on CPU: on a real corpus every big scan (Narmour 499p, Eco 253p, Chomsky…) either **timed out at 20 min or OOM-crashed** during layout. New default OCR path:

- **`extract_with_tesseract`** — renders each page via pypdfium2 (already a dep) and OCRs it with tesseract (fast C binary, no multi-GB ML models → no OOM/timeout). Multilingual (eng, fra, + indic packs). Languages auto-filtered to those actually installed.
- **Page-range splitting** — a scanned book is OCR'd in tranches of `PAGES_PER_OCR_JOB = 50`, one P3 job each. A 600-page book becomes ~12 short, independently-resumable jobs instead of one hour-long block that monopolises the worker. `enqueue_ocr_jobs()` does the split; P1, `rtfm doctor --enqueue-ocr` and `backfill-pages --enqueue-ocr` all use it.
- **Idempotent append** — `Library.append_ocr_chunks(book_slug, chunks, page_lo, page_hi)` deletes that page range then inserts, so re-running a tranche (retry) never duplicates and other tranches stay intact. Each tranche enqueues P2 embedding for just its new chunks.
- **Config**: `ocr_backend` (`tesseract` default | `marker` | `auto`), `ocr_langs` (default `eng+fra`; set e.g. `eng+fra+tam+hin+san` for Indic-script scans).
- New `[ocr]` extra: `pytesseract`, `pypdfium2`, `Pillow` (+ the system `tesseract` binary).
- `pages_to_chunks()` extracted from `PDFParser.parse` and shared with the OCR handler so OCR'd pages produce identical chunk shapes. 6 new tests (split ranges, idempotent tranche append).

Trade-off: tesseract is excellent on clean print (your scanned books) but weaker than marker on heavy maths/tables/multi-column. For making text searchable it's the right call on a GPU-less machine; marker stays available via `ocr_backend: marker`.

## [0.14.1] — 2026-05-21

### Fixed
- `rtfm.core.embeddings` no longer hard-imports numpy at module load. numpy is part of the `[embeddings]` extra, but `reconcile()` (and the queue handlers) need only the metadata helpers (`resolve_model`, `DEFAULT_MODEL`) — which don't touch numpy. The top-level `import numpy` made `test_reconcile` fail in the core/dev CI matrix (`ModuleNotFoundError: numpy`). numpy is now imported lazily inside the functions that use it, with `from __future__ import annotations` keeping the `np.ndarray` type hints from evaluating at import time.

## [0.14.0] — 2026-05-21

### Fixed — embeddings no longer leak when chunks are deleted

`Library._get_conn` now sets `PRAGMA foreign_keys = ON`. SQLite has FK enforcement **off by default**, so the `chunk_embeddings → chunks` `ON DELETE CASCADE` never fired: every re-ingest/`delete_book` left the old embeddings behind as orphans (a real index had **197k orphans = 19%** of all embeddings). They didn't pollute search (the semantic query JOINs on `chunks`, excluding them) but wasted disk. With FKs on, deleting a chunk removes its embedding.

### Added — self-healing reconciliation (`rtfm gc` + idle worker pass)

A live pipeline is never perfectly consistent (interrupted syncs, re-ingests, moves). Rather than try to prevent every gap, RTFM now **reconciles** the index periodically:

- `rtfm.core.reconcile.reconcile()` — purges orphan embeddings and re-queues every chunk missing an embedding as P2 jobs.
- **The worker runs it automatically while idle** (every `RECONCILE_INTERVAL_SECONDS = 3600`, only when the queue is empty — so it never races an in-flight re-ingest/move, and an orphan only ever means "chunk gone for good" since `move_file` preserves chunk ids).
- **`rtfm gc [--vacuum] [--force]`** — manual trigger. Refuses while the worker is busy (reconciliation is only safe at rest); `--force` overrides; `--vacuum` reclaims disk after purging.

This also surfaces and self-heals **un-embedded chunks** — content that exists but was never embedded (e.g. after an inline/`--no-embeddings` sync), so it's invisible to semantic search until reconciled. 5 new tests in `test_reconcile.py`, incl. a regression that FK=ON cascades the delete.

## [0.13.0] — 2026-05-21

### Fixed — half the supported formats were never scanned

`DEFAULT_EXTENSIONS` was a hand-maintained list of 27 extensions that omitted **27 formats RTFM has a parser for**: csv, tsv, xlsx, sqlite, sqlite3, db, epub, mobi, azw, azw3, docx, odt, rtf, fb2, djvu, ipynb, sql, and several languages (kotlin, swift, lua, r, perl, scala, …). Those files were silently ignored unless a source declared `extensions` explicitly. `DEFAULT_EXTENSIONS` is now **derived from the parser registry** (`default_extensions()`), so every format with a parser is scanned — 56 extensions, and any newly-added parser is picked up automatically.

### Added — `rtfm reindex` (targeted refresh after a parser change)

When a parser is improved (e.g. the 0.12.0 tabular fix), the affected files need re-ingesting — but their content hash is unchanged, so `rtfm sync` skips them and `--force` would re-ingest *everything* (including a thousand PDFs mid-embed). `rtfm reindex` enqueues P1 ingest jobs **only** for a chosen category, leaving the rest of the queue and in-flight embeddings untouched:

```
rtfm reindex --ext csv,tsv,xlsx,sqlite,db   # after a tabular parser fix
rtfm reindex --parser csv                   # by parser name
rtfm reindex --ext pdf --corpus icm-bibliography
```

P1 jobs preempt pending P2/P3, so the refresh runs first. This is the "nominal" way to roll out a parser change to an existing index.

## [0.12.0] — 2026-05-21

### Changed — tabular parsers index the **whole** file, not a sample

CSV/TSV, XLSX and SQLite were *samplers*, not parsers: they indexed only the header + a handful of rows (CSV 8, XLSX 6, SQLite 5). A value on row 5000 was invisible to search. They now index **every row**, so the full table is searchable.

- **CSV/TSV** (`csv_parser.py`): overview chunk (columns + inferred types) then **all rows** in size-bounded data chunks. Each row rendered as `col=value | col=value` (every value tied to its column for FTS/semantic match), full values (no more 80-char cell truncation), header repeated per chunk. Streamed — memory stays bounded on million-row files.
- **XLSX** (`xlsx.py`): same treatment per sheet — schema chunk + all-rows data chunks, via `read_only` `iter_rows`.
- **SQLite** (`sqlite_parser.py`): per table, schema chunk + all rows streamed with `fetchmany(500)`. BLOB columns keep a `<blob NB>` placeholder (binary, not text-searchable); text/numeric values kept in full. FK edges unchanged.

Type inference still samples the first ~50 rows (it doesn't need the whole file). Trade-off: indexing a large table produces many more chunks → bigger index and more embeddings, which is the cost of "everything searchable". Tests updated/added across all three parsers (full-content, column-context, large-file, no-truncation).

## [0.11.2] — 2026-05-20

### Changed — PDF health scan hardened for unattended corpus runs

A cross-team freeze post-mortem (a sibling tool ran two poppler-based PDF scanners in parallel on a DrvFs/9p mount; corrupt files wedged `pdfinfo` in uninterruptible D-state, full-document `pdftotext` on big healthy PDFs saturated I/O) drove three hardening changes so RTFM can scan an entire corpus in the background without freezing WSL:

- **Page sampling**: `measure_pdf_text(path, sample_pages=10)` now text-extracts only the first ~10 pages. The scan signal (≈0 chars/page) is unambiguous there; extracting a 700-page book in full was pure I/O waste. Verdict unchanged, ~10× faster per large file (Narmour 499p: 0.5 s vs seconds).
- **Buffer read**: the file bytes are read in Python (`path.read_bytes()`, an interruptible syscall we own) and handed to pypdfium2 as a buffer, instead of letting pdfium open the path and block on the slow mount. RTFM was already subprocess-free (pypdfium2 in-process), so it never had the D-state child problem in the first place.
- **No two scanners at once**: `rtfm doctor` refuses to run while the worker is `busy` (use `--force` to override, or stop the worker). One PDF scanner per mount.

`measure_pdf_text` now also returns `sampled_pages`. `backfill-pages` no longer overwrites `total_chars` (the sampled count isn't the document total) — it writes `page_count` and bases the scan verdict on the freshly-sampled real text.

## [0.11.1] — 2026-05-20

### Fixed — scan detection reads the file, not the DB

A cross-check against a hand-curated 28-PDF list exposed a flaw: scan detection (and `backfill-pages`) computed chars/page from the **stored** `books.total_chars`, which can be stale (different file revision, prior OCR run). It made a genuine 0-char scan (Chomsky 1957) look like text. Now the density is measured from the real file every time.

- `parsers.pdf.measure_pdf_text(path)` — opens via pypdfium2, extracts the real text of every page, returns `{pages, chars, chars_per_page, error}`. A non-None `error` is a distinct "unreadable" state (pdfium "Data format error" on corrupt files) — such files can't be OCR'd by marker either (same backend), so they need re-acquisition, not OCR.
- `backfill-pages` rewrites both `page_count` **and** a freshly-measured `total_chars`, and only flags readable scans.

### Added — format sniffing + `rtfm doctor`

- `core.sniff.detect_real_format(path)` — magic-byte detection (pdf / zip / epub / docx / xlsx / pptx / html / rtf / gzip / empty). Catches files saved with a lying extension (e.g. an EPUB named `.pdf`).
- The P1 ingest handler no longer queues OCR for a `.pdf` that isn't really a PDF (marker would fail too).
- **New `rtfm doctor`** — diagnoses every indexed PDF into ok / scan / unreadable / wrong-format / missing by reading the real file. Flags: `--enqueue-ocr` (queue P3 for readable scans), `--fix-extensions` (rename mislabeled files on disk so a re-sync routes them to the right parser).
- 11 new tests in `test_sniff.py`.

## [0.11.0] — 2026-05-20

### Added — deterministic scanned-PDF detection

The "is this PDF a scan that needs OCR?" decision is now based on **text density (chars per page)**, not the chunk count. On a real corpus the chunk-count heuristic was badly wrong: of 143 low-chunk PDF candidates, only **4 were actual scans** — the other ~113 had plenty of text that the chunker had merged into 1-2 large chunks. Conversely, scans that produced 1-2 junk chunks slipped past the old `chunks == 0` test entirely.

- `PDFParser.parse()` writes the real `pypdfium2` page count into the shared metadata dict, so `Library._index_chunks` persists it to the new use of `books.page_count`.
- `Library._index_chunks` returns `pages` in its stats and stores `page_count` (via `COALESCE`, so a re-ingest never nulls it).
- `handlers._pdf_is_scan(stats)` — deterministic test: `chars / pages < SCAN_CHARS_PER_PAGE` (20). Falls back to the zero-chunk signal only when no page count is available. The P1 ingest handler uses it to decide whether to enqueue a P3 OCR job.
- **New `rtfm backfill-pages [--enqueue-ocr]`** — fills `books.page_count` for already-indexed PDFs (cheap: pypdfium2 page count, no text extraction), reports which are provably scans, and optionally enqueues P3 OCR jobs for them (enabling `ocr_fallback` if needed).
- 4 new tests in `rtfm/tests/test_handlers.py`.

## [0.10.6] — 2026-05-19

### Fixed
- `rtfm sync` no longer crashes with `database is locked` when the Library connection has an open implicit transaction at the moment the Queue tries `BEGIN IMMEDIATE`. Two connections to the same SQLite DB **from the same Python process** see each other as locked even in WAL mode — `busy_timeout` doesn't help in that intra-process case. `_cmd_sync_enqueue` now commits the Library connection right before every batch enqueue.

## [0.10.5] — 2026-05-19

### Fixed
- `Queue.enqueue_many` wraps each batch in a single `BEGIN IMMEDIATE` transaction (was N individual auto-commits) and retries up to 3× on transient `database is locked`. `busy_timeout` bumped from 10 s → 60 s for multi-MCP-server setups (3+ Claude Code sessions on the same project).

## [0.10.4] — 2026-05-19

### Changed — single consumer process + MD5 enqueue

Two corrections to the 0.10.3 design after a real-world run on the user's musicology-phd project.

- **`rtfm sync` enqueue now uses `compute_diff` (MD5)**, not `quick_diff` (size + mtime). On a 4400-job sample the previous quick-diff path was ~14 % waste: ~10 % cross-corpus duplicates (a file already in the DB under another corpus with the same MD5) and ~4 % mtime false-positives (NTFS-via-WSL re-touching files without content change). Quick-diff missed the cross-corpus case entirely.
- **Cross-corpus moves are now applied inline** during `rtfm sync`, before any enqueue, via `Library.move_file(new_corpus=...)`. The book row's corpus is updated and its chunks / embeddings / tags follow (FK on chunk_id, not on the on-disk path). This is the work-preservation guarantee the user asked for: a file moved between configured corpora keeps the embeddings already paid for.

### Changed — one process, no more watcher

`rtfm/core/watcher.py` and `rtfm/tests/test_watcher.py` are gone. The periodic scan is folded into the worker idle loop: when the priority queue is empty, the worker runs the same MD5-based scan + cross-corpus move logic itself, then sleeps. One project = one process, exactly as the user originally specified.

- New `--scan-interval SECONDS` option on `rtfm worker start` (default 30 s). The worker reads it via `rtfm worker-daemon --scan-interval`.
- `rtfm watch [start|stop|status]` and `watch-daemon` are removed.
- `rtfm status` keeps showing the `Worker / Queue:` section unchanged — it was already worker-only.

The 0.10.3 watcher made sense in isolation but doubled the daemon footprint for no benefit: scanning is cheap (`quick_diff` had been ~ms per file; `compute_diff` is the new cost and only runs while the queue is empty, so a long ingest or OCR run is never paused to scan).

## [0.10.3] — 2026-05-19

### Added — filesystem watcher + enriched status (queue phase 4)

- **`rtfm watch [start|stop|status]`** — a polling daemon that scans every configured source every 30 s (configurable via `--poll`) and enqueues P1 ingest jobs for new/modified files. Auto-spawns the worker after each scan that found something. Held by an exclusive `flock` on `.rtfm/watcher.lock` (one watcher per project), with `.rtfm/watcher_state.json` for status. Combined with the worker, a file you save now lands in the index within ~30 s, automatically, without any manual `rtfm sync`.
- Polling (not inotify) chosen on purpose: RTFM frequently indexes Obsidian vaults on `/mnt/d/…` (NTFS via WSL), where inotify does not propagate events. The poll uses `quick_diff` (size + mtime, no MD5), so a 30 s tick is cheap even on huge corpora.
- **`rtfm status` shows a new `Worker / Queue:` section** when relevant: worker status (running/idle/busy), current job preview, per-type counts (`ingest`, `embed`, `ocr`) with `pending/running/done/failed` breakdown. Silent on projects that never used the queue path.
- New module `rtfm/core/watcher.py` (`Watcher`, `WatcherLock`, `watcher_running`, state primitives). `cli_worker.ensure_watcher_running()` mirrors `ensure_worker_running()`. 10 new unit tests in `rtfm/tests/test_watcher.py`.

Phase 4 closes the queue redesign loop: producers (CLI, hooks, **watcher**) → priority queue → worker (one process, three priorities, bounded resources). From here on the user can edit a file and the index catches up on its own.

## [0.10.2] — 2026-05-19

### Added — P3 OCR handler (queue phase 3)

The OCR pass is now a P3 job in the unified worker. Pipeline:

```
P1 ingest (PDF, ocr_fallback=true)
    ├─ pdftext yields ≥1 chunk → ingest OK, enqueue P2 follow-up
    └─ pdftext yields 0 chunks → enqueue P3 OCR for this same file
P3 ocr
    ├─ delete the empty book P1 left behind
    ├─ re-ingest with PDFParser(backend="marker") — marker runs in
    │   an isolated subprocess (0.9.5) so its 3-8 GB of model RAM
    │   is reclaimed between PDFs
    └─ enqueue P2 follow-up for the freshly OCR'd chunks
```

P3 sits below P1 / P2 in the queue, so a freshly-edited markdown file is always indexed before the worker burns CPU on a slow OCR run.

- `handlers.handle_ocr` — P3 handler. Drops any empty book P1 left behind, re-ingests with the marker backend, updates `indexed_files`, then enqueues P2 follow-up so the OCR'd chunks reach the embedding column on their own.
- `handlers.handle_ingest` (existing) now detects zero-chunk PDFs and auto-enqueues a P3 job *iff* `ocr_fallback: true` is set in `.rtfm/config.json`. Skips the P2 follow-up in that case (no point embedding an empty book).
- **`rtfm sync --ocr` is queue-based by default**: persists `ocr_fallback: true` (idempotent), enqueues a P3 for every previously-flagged scan from `.rtfm/seen_scans.json`, auto-spawns the worker. The legacy detached `ocr-worker` daemon is still reachable via `rtfm sync --inline --ocr` and will be removed in 0.11.
- 3 new tests in `rtfm/tests/test_handlers.py` (auto-enqueue P3 with fallback on; no P3 with fallback off; reject non-PDF payloads).

Phase 3 closes the queue redesign the user asked for: one process, three priorities (ingest > embed > OCR), per-file granularity for responsive preemption, bounded resources (`nice 19` + `ionice -c 3` + marker subprocess isolation).

## [0.10.1] — 2026-05-19

### Added — P2 embed handler (queue phase 2)

The priority-queue worker now drains P2 embed jobs in addition to P1 ingest. The full pipeline is:

```
producer ─► P1 ingest job ─► worker ─► parse + index + upsert tracking
                                   ─► enqueue N P2 jobs (chunks of the new book,
                                       split at EMBED_BATCH_SIZE=64)
producer ─► P2 embed job  ─► worker ─► fastembed batch → chunk_embeddings
```

- `Library.embed_chunks_by_id(chunk_ids, model=None)` — embed a specific list of chunk ids. Skips chunks that already carry an embedding for the active model (idempotent retry). The 500-id chunked filter dodges SQLite's parameter limit even for huge backfills.
- `Library.chunk_ids_for_book(slug)` and `Library.chunk_ids_without_embedding(corpus=None)` — small helpers used by the P1 follow-up enqueue and by `rtfm embed` in queue mode.
- `handlers.handle_embed` — P2 handler: load `chunk_ids` from payload, call `embed_chunks_by_id`. Empty payload is a no-op (so a malformed enqueue doesn't fail the job).
- `handlers.handle_ingest` (existing) now enqueues a P2 batch per `EMBED_BATCH_SIZE=64` chunks of the newly-created book — chunks reach the embedding column on their own, no manual `rtfm embed` needed.
- **`rtfm embed` is queue-based by default**: scans for chunks missing an embedding, splits at `EMBED_BATCH_SIZE`, enqueues P2 jobs, auto-spawns the worker, returns immediately. `--inline` and `--force` keep the legacy blocking path (CI / re-embedding the whole DB).
- 5 new tests in `rtfm/tests/test_handlers.py`. Fixed an `INSERT … ON CONFLICT(chunk_id, model)` clause to match the table's actual `UNIQUE(chunk_id)` constraint.

### Coming

Phase 3 (P3 OCR handler — folds the existing OCR daemon into the unified worker) lands in 0.10.2.

## [0.10.0] — 2026-05-19

### Added — priority-queue worker (MVP / phase 1)

The work model moves from "every command blocks on a full-tree sync" to a single in-project background daemon that drains a priority queue. Producers (CLI, hooks, MCP tools) enqueue per-file jobs; the worker picks them up by priority. Ingestion (P1) preempts embeddings (P2) which preempts OCR (P3), so a file you just edited is indexed before any embedding/OCR backlog. Granularity is one file per job, so preemption is responsive (next-job boundary).

- New `work_queue` table in `.rtfm/library.db` with priority + status + dedup index on `(type, payload) WHERE status='pending'` — multiple producers can safely enqueue concurrently.
- `rtfm.core.queue.Queue` — atomic `enqueue` / `dequeue` (single-statement `UPDATE ... RETURNING`), `mark_done` / `mark_failed`, `stats` / `list_pending` / `list_failed`, `retry_failed`, `clear_done`. 13 unit tests.
- `rtfm.core.worker.Worker` — single-threaded loop, dispatch by job type, atomic state snapshot to `.rtfm/worker_state.json`, exclusive `flock` on `.rtfm/worker.lock` so at most one worker drains a project at a time.
- `rtfm.core.handlers.handle_ingest` — P1 worker handler. Equivalent to the per-file path of the legacy inline sync (parse → ingest → upsert tracking), but isolated to a single file.
- **`rtfm sync` is now queue-based by default**: scans configured sources, enqueues P1 jobs for new/modified files, auto-spawns the worker daemon (at `nice 19` + `ionice -c 3` when available), returns immediately. `--inline` keeps the legacy blocking sync for CI / scripted use; `--ocr`, `--no-embeddings`, `--files`, explicit path, `--dry-run`, `--force` also stay on the legacy path.
- **New CLI commands**:
  - `rtfm worker [start|stop|status]` — manage the daemon directly.
  - `rtfm worker-daemon` — hidden; the actual loop, invoked by `ensure_worker_running()`.
  - `rtfm queue [stats|list|failed|clear-done|retry-failed]` — inspect & manage the queue (`--limit`, `--keep`).

### Coming

Phase 2 (P2 embed handler — chunks-without-embeddings as scheduled jobs) and Phase 3 (P3 OCR handler — folds the existing OCR daemon into the unified worker) will land in 0.10.1 / 0.10.2.

## [0.9.5] — 2026-05-18

### Fixed
- **OCR no longer accumulates RAM across PDFs.** `marker.models.create_model_dict()` loads 3-8 GB of ML state (layout + OCR + table + reading-order pipelines) and caches it at module level — marker never releases it. The old in-process loop in `extract_with_marker()` re-loaded those models for every PDF without freeing the previous run, so a long `rtfm sync --ocr` on WSL (16 GB cap) climbed past the ceiling, swapped on NTFS, and froze the whole VM. Now each PDF is OCR'd in a one-shot Python subprocess (`subprocess.run`); the OS reclaims the full footprint when the child exits. Adds a 20-min per-PDF timeout (`PDFExtractionError` instead of an indefinite hang) and a structured JSON protocol between worker and host. 3 new tests in `rtfm/tests/test_pdf_parser.py`.

## [0.9.4] — 2026-05-18

### Changed
- **Claude Code hooks: targeted per-turn sync instead of full-tree rescan.** Before 0.9.4 the `UserPromptSubmit` and `Stop` hooks both iterated every configured source (e.g. 35 sources for a multi-vault project) at every turn — ~30–60s per hook, fighting an `rtfm sync --ocr` daemon for SQLite write locks on multi-session setups and producing 100+ redundant scans per hour. The new design is event-driven:
  - New `PostToolUse` hook (`rtfm_record_edit.py`, matcher `Write|Edit|MultiEdit|NotebookEdit`) appends each touched `file_path` to `.rtfm/touched_files.tmp` in O(1).
  - `Stop` (`rtfm_stop_sync.py`) reads that queue, groups files by their longest-matching configured source, and runs `sync(files=[...])` only for those files. Empty queue → instant no-op.
  - `UserPromptSubmit` (`rtfm_sync.py`) is now just a safety-net drain for orphan queues left behind by sessions abandoned before their Stop hook ran.
- Net effect: zero-cost hooks on turns with no edits; sub-second sync on turns with 1–5 edits; never re-scans untouched sources; no more lock contention with the OCR daemon. `hooks.json` updated to register `PostToolUse`.

## [0.9.3] — 2026-05-18

### Fixed
- **Sync no longer drops embeddings with `Model paraphrase-multilingual-MiniLM-L12-v2 is not supported in TextEmbedding`** on DBs created by older RTFM versions. Early releases stored the short, unqualified model name (`paraphrase-multilingual-MiniLM-L12-v2`) in `chunk_embeddings.model`. Recent fastembed releases only accept the fully-qualified `sentence-transformers/...` form, so reusing the DB's active model on a fresh sync threw mid-batch and silently disabled embedding generation for every new chunk. `resolve_model()` now suffix-matches a short name back to the registered fully-qualified entry, and `Library.generate_embeddings()` normalizes the DB-stored name through `resolve_model` before handing it to fastembed. 4 new tests in `rtfm/tests/test_embeddings.py::TestResolveModel`.

## [0.9.2] — 2026-05-18

### Fixed
- **`move_file()` no longer crashes with `UNIQUE constraint failed: indexed_files.filepath`.** Previously the cross-corpus move pass did a plain `DELETE + INSERT` on the tracking table, which raised mid-sync as soon as the target `filepath` already had a row (typical when only the corpus name changes in `config.json` and every cross-move has `old_filepath == new_filepath`). The DELETE had already run when the INSERT threw, so the `books` row was repointed at the new corpus but its tracking entry was gone — leaving thousands of "orphan" books with no `indexed_files` mapping. Replaced with an `INSERT ... ON CONFLICT(filepath) DO UPDATE` (same pattern as `update_indexed_file`) and an explicit `DELETE old_filepath` only when it differs from `new_filepath`. 2 new regression tests in `rtfm/tests/test_cross_corpus_move.py` (`test_corpus_rename_in_place_no_unique_conflict` reproduces the user-facing scenario; `test_move_file_preexisting_target_filepath` is a belt-and-braces unit test). Full suite: 501 passed.

## [0.9.1] — 2026-05-18

### Fixed
- **MCP tools now coerce numeric params passed as strings.** Some MCP clients/LLMs emit `"limit": "5"` instead of `"limit": 5`; downstream comparisons like `len(results) >= limit` in `library.search()` then crashed with `TypeError: '>=' not supported between instances of 'int' and 'str'`. Affected `rtfm_search`, `rtfm_context`, `rtfm_books`, `rtfm_expand`, and `rtfm_history`. New `_coerce_int`/`_coerce_float` helpers in `rtfm/mcp.py` cast incoming values, fall back to the documented default on unparseable input, and reject `bool` (which is a subclass of `int` in Python). 9 new regression tests in `rtfm/tests/test_mcp.py`. Full suite: 487 passed.

## [0.9.0] — 2026-05-18

### Added
- **`rtfm sync --ocr` runs as a detached background daemon.** Marker-based OCR takes minutes per scanned PDF, hours for a real corpus — the previous foreground implementation died with the terminal or the Claude Code hook timeout, losing the entire run. The command now: (1) refuses to relaunch if another daemon is already running (shows live progress and PID instead), (2) persists `ocr_fallback: true` in `.rtfm/config.json`, (3) invalidates the hash of every PDF in `.rtfm/seen_scans.json` so the worker's incremental sync re-ingests them, (4) forks a `subprocess.Popen(..., start_new_session=True)` worker (immune to parent SIGHUP) and exits immediately with the daemon's PID. New internal `rtfm ocr-worker` subcommand does the actual sync.
- **Resumable**: the worker writes its live state to `.rtfm/ocr_state.json` (atomic temp+rename) with `pid`, `status`, `total`, `done`, `current_file`, `started_at`, `last_update`. If the daemon is killed mid-run, the next `rtfm sync --ocr` resumes from where the incremental sync left off — files already OCR'd have a real hash and are skipped.
- **`rtfm status` now surfaces the OCR daemon** when one is present:
  - Live: `OCR running (PID 12345): 23/156 PDFs (15%), 1h20m elapsed, ETA ~6h\n  current: scan_45.pdf`
  - Dead-but-resumable: `OCR interrupted at 23/156 (...). Resume: rtfm sync --ocr`
- `/rtfm.status` and `/rtfm.ocr` slash command prompts updated to highlight the daemon state and never wait/poll.
- New module `rtfm/core/ocr_daemon.py` exposes the helpers (`pid_alive`, `read_state`, `write_state`, `daemon_running`, `format_progress`) and the on-disk `ocr_state.json` schema.
- 14 new unit tests in `rtfm/tests/test_ocr_daemon.py` cover PID liveness, atomic write semantics, the running-detection logic, malformed-JSON tolerance, and the progress renderer for running/crashed states. Full suite: 475 passed.

### Changed
- `rtfm sync --ocr` no longer accepts running in the foreground. (If you really need a foreground run for debugging, invoke `rtfm ocr-worker` directly — it's hidden from `--help` but documented in `rtfm/core/ocr_daemon.py`.)

## [0.8.9] — 2026-05-18

### Added
- **Cross-corpus move detection by content hash.** When a file is reorganised across corpus boundaries (e.g. moved from an Obsidian `Projets/` into `Publications/` when those map to different RTFM corpora), `compute_diff()` now spots the hash match against `library.list_indexed_files()` (all corpora) and transfers ownership instead of treating the file as deleted-in-A + added-in-B. The book row is updated in place, so chunks, **embeddings, and tags all survive** (they reference `chunk_id`, not the on-disk path). Critical when expensive computation has already been done — semantic embeddings, OCR output, manual tagging.
- `library.move_file(..., new_corpus=...)` is the new entry point. The same on-disk filepath cannot belong to two corpora at once (table constraint), so this is also a safe partition guarantee.
- 3 new tests in `rtfm/tests/test_cross_corpus_move.py` covering chunk-id preservation across the move, regression on in-corpus moves, and the "really new file" path. Full suite: 461 passed.

## [0.8.8] — 2026-05-18

### Added
- **`/rtfm.status` slash command.** Wraps `rtfm status --health` so the user can check index health from the Claude Code `/` menu without dropping to a terminal. Returns the full status (books, chunks, corpora, embeddings, last sync, parsers, extras) plus pending-sync counts and known scan suspects. Defined in `commands/rtfm.status.md`.

## [0.8.7] — 2026-05-17

### Fixed
- **Slash command moved to the correct location and renamed to `/rtfm.ocr`.** In 0.8.6 the file lived at `.claude-plugin/commands/ocr.md`, which is not a directory scanned by Claude Code — plugin slash commands must sit in `commands/` at the plugin root (per the official Plugins reference). Renamed to `commands/rtfm.ocr.md`, so the command surfaces as `/rtfm.ocr` in the slash menu once the marketplace plugin is updated (`/plugin marketplace update roomi-fields` then reinstall `rtfm@roomi-fields`).

## [0.8.6] — 2026-05-17

### Added
- **`/rtfm:ocr` slash command.** Users who install RTFM via `/plugin install rtfm@roomi-fields` now get a Claude Code slash command that wraps `rtfm sync --ocr` — pick it from the `/` menu, the agent runs the command, summarises results, and confirms persistent OCR fallback is active. Defined in `.claude-plugin/commands/ocr.md`.

### Fixed
- **`rtfm sync --ocr` now works from any directory.** When invoked outside a `.rtfm/` project (no config to persist into), the flag still forces `ocr_fallback=True` for the current run. Previously it was silently ignored: the persistent flag could only be saved when a `.rtfm/` was reachable, and the run itself fell back to pdftext-only.

## [0.8.5] — 2026-05-17

### Added
- **One-shot `rtfm sync --ocr` — persistent OCR fallback for scanned PDFs.** Activates an `ocr_fallback: true` flag in `.rtfm/config.json` and re-runs sync with `force=True` so previously-empty scans get OCR'd immediately. From then on, every sync (CLI or auto via hook) instantiates `PDFParser(backend='auto')` for PDFs: it tries `pdftext` first (fast, ~ms) and only falls back to `marker-pdf` (slow OCR) when no text was extractable. **The user runs the command once** — new scans added to indexed sources are OCR'd automatically by the next sync. Successfully OCR'd files drop off `.rtfm/seen_scans.json` so `rtfm status` reflects the real remaining backlog.
- **`PDFParser` gains a `backend='auto'` mode** that does the pdftext → marker fallback in-process. Existing `pdftext` and `marker` modes are unchanged. Picks the cheap backend by default; only spends OCR cycles on real scans.
- **Periodic progress reporting inside `sync()`.** New `progress_interval` parameter (seconds) emits a heartbeat line via `on_progress("progress", "", "K/N files, Xmin elapsed, ~Ymin remaining")` while the inner loop runs. CLI auto-enables a 10-minute interval when `--ocr` is set; `--progress-every N` overrides. Long OCR passes no longer look frozen.
- **`ACTION REQUIRED` blocks now propose a concrete copy-pastable command.** Both the MCP `rtfm_sync` tool and the auto-sync hook print `ON APPROVAL RUN: rtfm sync --ocr` (instead of the previous "install [pdf] and re-sync" phrasing) and explicitly tell the user that the command is one-shot — future scans are handled automatically.

### Changed
- The hook (UserPromptSubmit + Stop) reads `ocr_fallback` from `.rtfm/config.json` and propagates it to the inner `sync()` call, so the auto-sync respects the persistent flag.
- `_print_health_warnings()` now adapts its message: when OCR fallback is already on but scans still survive, it tells the user the PDFs are likely corrupt rather than re-suggesting OCR.

## [0.8.4] — 2026-05-17

### Fixed
- **`rtfm status` and the auto-sync hook no longer block on remote/NTFS sources.** 0.8.3 reduced the status-health diff from "hash every file" to "stat every file"; on a small local repo that's instant, but on a 1700-file Obsidian vault sitting on NTFS via WSL even `os.stat()` adds up to ~90 seconds per source. Two changes:
  - `rtfm status` now keeps the index-health pending counts behind an opt-in `--health` flag. The default `rtfm status` runs in well under a second again, and known scan suspects (a single JSON read) are still shown unconditionally.
  - The `UserPromptSubmit` hook bounds its pre-sync diff to a 2-second total budget. If the budget is exhausted before all sources are scanned, the "indexing N files" announcement is silently skipped and the actual sync proceeds normally — the post-sync `✓ RTFM sync` summary still fires.

## [0.8.3] — 2026-05-17

### Fixed
- **`rtfm status` no longer hangs on large corpora.** The "Index health" section introduced in 0.8.1 ran `sync(..., dry_run=True)` for every configured source, which computes the MD5 of every tracked file — fine on a small repo, but a hard wait on corpora with hundreds of large PDFs (e.g. research libraries). Replaced by a new `quick_diff()` helper in `rtfm/core/sync.py` that compares path presence + on-disk `st_size` against the stored tracking metadata. The same helper now also feeds the `UserPromptSubmit` hook's "indexing N files" announcement. Trade-off: an in-place edit that does not change the file size can be missed by `quick_diff`; the real `rtfm sync` still uses the hash diff for correctness.
- Tests: 3 new in `rtfm/tests/test_sync_health.py` covering the added / modified-by-size / removed paths of `quick_diff`.

## [0.8.2] — 2026-05-17

### Fixed
- **`rtfm.__version__` no longer reports `"0.0.0"` to installed users.** `rtfm/__init__.py` was looking up `importlib.metadata.version("rtfm")` but the distribution name on PyPI is `rtfm-ai` (the `rtfm` import name was already taken by an unrelated package). The lookup raised `PackageNotFoundError` silently and fell back to `"0.0.0"`, which leaked into every place that reads `__version__` — the CLI, the MCP server stats output, and `rtfm status`. Now uses `version("rtfm-ai")` and adds a regression test (`rtfm/tests/test_version.py`) that fails if `__version__` drifts from `pyproject.toml`.

## [0.8.1] — 2026-05-17

### Added
- **Sync health signals — RTFM no longer swallows scanned PDFs silently.** `SyncResult` now exposes `suspect_scans` (PDFs that parsed without error but produced 0 chunks — almost always image-only scans needing OCR) and `empty_files` (other 0-chunk parses). The CLI, MCP server and the auto-sync hook all surface this state instead of silently treating it as a successful sync.
  - `rtfm sync` (CLI) prints a localized warning block listing the suspect PDFs and the OCR install path.
  - `rtfm_sync` (MCP) emits an `ACTION REQUIRED — surface to the user verbatim` block, the same format used when the `pdf` extra is missing, so the agent raises it with the user instead of moving on.
  - `UserPromptSubmit` hook dry-runs the diff first; announces `→ RTFM: indexing N files...` when there are ≥ 50 new/modified files, prints `✓ RTFM sync: +A ~M -R files (Xs)` when something actually changed, and forwards new scan warnings as the same `ACTION REQUIRED` block. Already-reported scans are tracked in `.rtfm/seen_scans.json` so the warning does not repeat on every turn.
- **`rtfm status` — new "Index health" section.** Reports pending added / modified / removed files relative to the configured sources (best-effort dry-run) and known scan suspects. Answers the question "is my index up to date?" in one command.
- Tests: 9 new in `rtfm/tests/test_sync_health.py` covering `SyncResult` shape, sync-time classification, the CLI warning helper, and the MCP `ACTION REQUIRED` block. Full suite: 448 passed, 17 skipped.

## [0.8.0] — 2026-05-16

### Added
- **7 new document parsers — ebook and office formats.** RTFM now indexes EPUB, MOBI/AZW/AZW3, FB2, DJVU, DOCX, ODT, and RTF in addition to the existing 15 formats.
  - `epub` (extra `[epub]`: `ebooklib`, `beautifulsoup4`) — walks the spine in reading order, one chunk group per chapter, OPF title/author lifted into metadata.
  - `mobi_parser` (extra `[mobi]`: `mobi`, `beautifulsoup4`) — Kindle MOBI/AZW/AZW3, DRM-free only; DRM-protected files surface a clean `MOBIExtractionError`.
  - `fb2` — FictionBook XML, zero external dependency (stdlib `xml.etree`). Sections become chapters, `<title-info>` becomes title/author.
  - `djvu` — DJVU via the `djvutxt` system binary from `djvulibre-bin` (no Python dep), one chunk group per page.
  - `docx` (extra `[office]`: `python-docx`, `odfpy`, `striprtf`) — paragraphs walked in document order, Heading 1/2/3 styles cut sections, tables flattened to `cell | cell`. `core_properties.title/author` lifted into metadata.
  - `odt` (extra `[office]`) — same shape as `docx`, sections cut by `text:h` with `text:outline-level`. Metadata via `dc:title` / `dc:creator`.
  - `rtf` (extra `[office]`) — text-only extraction via `striprtf`; RTF has no native hierarchy so chunking is paragraph-based.
- **Shared chunking helpers** in `rtfm/parsers/_chunking.py` (`split_into_paragraphs`, `merge_short_paragraphs`, `split_on_sentence`, `slugify`, `content_hash`, `estimate_page`). New parsers reuse these; the older `markdown.py` and `pdf.py` keep their own copies for now (no behaviour change).
- New tests: `rtfm/tests/test_ebook_parsers.py` and `rtfm/tests/test_office_parsers.py` — fixtures synthesise minimal files in-process; tests `importorskip` cleanly when an optional dep is absent.

## [0.7.2] — 2026-05-06

### Fixed
- **MCP server connection: `bin/rtfm-serve` now executable.** The shell launchers (`rtfm-serve`, `rtfm-hook`, `rtfm-install-extras`) were checked into git with mode `100644` (no exec bit) because they were authored on a WSL/NTFS filesystem that does not preserve the POSIX exec bit. Claude Code clones plugins respecting the git index modes, so on Linux/macOS the MCP server failed to start with no helpful error in the `/plugin` UI ("rtfm MCP · failed"). Index permissions are now `100755` for the three shell launchers; `.cmd` siblings keep `100644` (Windows ignores the exec bit). To receive the fix: `/plugin marketplace update roomi-fields` then `/reload-plugins`.

## [0.7.1] — 2026-05-06

### Changed
- **Distribution: marketplace consolidated.** The standalone `roomi-fields/rtfm` marketplace is retired; RTFM now ships exclusively through the aggregator marketplace [`roomi-fields/claude-plugins`](https://github.com/roomi-fields/claude-plugins). Install command changes: `/plugin marketplace add roomi-fields/claude-plugins` then `/plugin install rtfm@roomi-fields`. The plugin itself is unchanged — same `bin/rtfm-serve`, same hooks, same skills. Existing users of the standalone marketplace should run `/plugin marketplace remove rtfm` and re-install via the aggregator.

No code changes — the wheel is byte-identical to 0.7.0. This release exists to carry the version bump in `.claude-plugin/plugin.json` and signal the marketplace migration to PyPI users via the release feed.

## [0.7.0] — 2026-05-04

### Added
- **Generic JSON schema mappings** — declaratively map any JSON schema to chunks and edges via YAML files in `.rtfm/mappings/`, no Python required. Drop a mapping file (matched by `$schema` URL or by a discriminator like `type: foo`) and matching JSON files are extracted into typed chunks at sync time. The system replaces what would otherwise be N format-specific parsers (NotebookLM exports, Linear/Jira dumps, OpenAPI specs, structured logs…) with one extensibility point that lives outside RTFM. Mini-templating engine (`{{ dotted.path }}` only — no eval, no Jinja). 35 new tests, zero new dependencies. See [docs/json-mappings.md](json-mappings.md).
- **NotebookLM integration recipe** — [docs/notebooklm-integration.md](notebooklm-integration.md) covers both the zero-friction markdown path and the typed JSON path, with a ready-to-copy `nblm-answer.yaml` mapping for `notebooklm-mcp` batch outputs.

### Changed
- `JSONParser` consults `MappingRegistry.find_mapping(data)` before falling back to the generic structural parser. Plain JSON files are unaffected.
- `Library.__init__` autoloads mappings from `<db_dir>/mappings/*.{yaml,yml,json}`.

## [0.6.0] — 2026-05-04

### Added
- **SQLite parser** (`.sqlite`, `.sqlite3`, `.db`) — read-only URI connection. Emits an overview chunk (tables, views, indexes, triggers + row counts), then per-table schema + sample chunks. Foreign keys extracted as `EdgeCandidate(relation_type="fk")`. FTS5 shadow tables filtered. `.db` extension validated by SQLite magic bytes to avoid false positives.
- **Jupyter parser** (`.ipynb`) — groups cells by markdown heading, code cells fenced as ```python, outputs dropped (often huge / low-signal). Zero deps.
- **TOML parser** (`.toml`) — one chunk per top-level table; emits `depends_on` edges for `pyproject.toml` (PEP 621, Poetry, build-system) and `Cargo.toml`. Uses stdlib `tomllib` (3.11+) with `tomli` fallback; gracefully unregistered if neither importable.
- **CSV/TSV parser** (`.csv`, `.tsv`) — dialect sniffing (delimiter), overview chunk with column types via lightweight inference (int/float/bool/text), sample chunk (first N rows aligned). Streams rows so big files don't blow memory.
- **XLSX parser** (`.xlsx`) — per-workbook overview + per-sheet schema + per-sheet sample. Optional dependency: `pip install rtfm-ai[xlsx]` (openpyxl). Uses `read_only=True` for huge workbooks.

### Changed
- Parser count: **10 → 15**.
- `pyproject.toml`: new optional extras `[xlsx]` (openpyxl).

## [0.5.0] — 2026-04-16

### Added — native Claude Code plugin
- **`/plugin marketplace add roomi-fields/rtfm` + `/plugin install rtfm@rtfm`** — zero pip required on user side.
- **Pure-Python MCP server** (`rtfm/_mcp/`, ~300 LOC) — drops the upstream `mcp` SDK, no `pydantic`, no `cryptography`, no native binaries. JSON-RPC 2.0 over stdio, schemas inferred from type hints + docstrings.
- **Cross-platform launchers** (`bin/`) — POSIX `sh` + Windows `.cmd`, auto-resolve `python3`/`python`/`py`, dodge the Microsoft Store `python3` stub.
- **Plugin hooks** — `SessionStart` bootstraps the project, `UserPromptSubmit` throttled sync (30s), `Stop` final sync.
- **Skills** — `/rtfm:search`, `/rtfm:expand`, `/rtfm:install-embeddings` (FastEmbed ONNX ~85 MB), `/rtfm:install-pdf` (~50 MB), `/rtfm:install-pdf-full` (CPU-only torch + marker-pdf, ~1.5 GB, isolated venv in `$CLAUDE_PLUGIN_DATA`, no PEP 668 conflicts).

### Fixed
- **Short files no longer silently skipped** — single-header markdown, title-only LaTeX sections, Python modules without classes, short legal articles. Affects `markdown`, `pdf`, `python`, `latex`, `xml_legifrance`, `html_bofip`.
- **Memory history preserved on file deletion** — `sync(retain_history=None)` no longer cascades deletes through `books.id → file_versions.book_id`. Restores the "unlimited version history" promise of the memory hook. Default (`retain_history=50`) unchanged.

### Changed
- Dropped `mcp>=1.0.0` dependency. Only `pyyaml` remains.
- README: plugin install promoted to primary path; `pip install rtfm-ai` kept as fallback for Cursor, Codex, Claude Desktop chat, other MCP clients.

## [0.4.0] — 2026-04-09

### Added — Obsidian Vault Integration
- **`rtfm vault` command** — detects Obsidian vaults (`.obsidian/`), auto-proposes corpus mappings from folder structure, generates `_rtfm/` navigation files (Obsidian-native: wikilinks, YAML frontmatter Dataview-queryable, callouts, Mermaid).
- **Wikilink resolution** — `[[wikilinks]]` resolved to actual files following Obsidian rules (basename match case-insensitive, path-suffix `[[folder/Note]]`, disambiguation by path distance). Resolved links become graph edges → powers hub detection + centrality ranking.
- **`_rtfm/` auto-generated navigation** — `index.md` (corpus list, top connected docs), `graph.md` (hubs, orphans, broken links, Mermaid), `recent.md` (auto-updates on sync), `corpus/*.md` (per-corpus indexes).
- **Karpathy 3-layer repo restructure** — `raw/` (source), `docs/` (compiled wiki), `CLAUDE.md` (schema).
- **Docs**: Obsidian Vault Guide, Architecture, Parsers Guide, Positioning.

### Stats
- 357 tests pass, 0 regressions; 32 new tests (wikilink + vault integration); 7,100+ LOC added.

## [0.3.1] — 2026-03-01

### Changed
- **`rtfm_expand` reads raw file lines** — Content is now read from disk between `line_start` and `line_end`, guaranteeing line numbers match `Read`/`Edit` exactly.
- **Strict path resolution** — `rtfm_expand` uses exact path matching instead of fuzzy slug lookup. No more ambiguous results from duplicate files.
- **CLAUDE.md template mentions `rtfm_expand`** — Guides agents to use `rtfm_search` then `rtfm_expand` instead of defaulting to `Read`.
- **Batch corpus resolution** — Search formatting resolves corpus paths in a single query instead of per-result SQL.

### Fixed
- **Markdown/LaTeX parser `line_start` off-by-one** — Content line numbers now point to first content line after the header.
- **Double search removed in expand query mode** — Was falling back to unscoped search, causing irrelevant matches.

### Added
- **`count` parameter for `rtfm_expand`** — Read multiple consecutive chunks in one call.
- **End-to-end search→expand→Edit test** — Proves line numbers from expand match the real file.

## [0.3.0] — 2026-02-27

### Removed
- **biblirag dissociation** — Removed all RAG/question-answering code (`ask.py`, `llm.py`, `cmd_ask`, `Citation`, `GroundingResult`, `Answer` models). RTFM is now a pure retrieval layer.
- **Legacy code** — Removed `src/` (biblirag legacy), `config/`, `extract.py`, `query.py`, `requirements.txt`.
- **Gemini dependency** — No more LLM client code. RTFM indexes and retrieves; generation is the agent's job.

## [0.2.3] — 2026-02-25

### Fixed
- **Dynamic version** — `__version__` now reads from `importlib.metadata` instead of hardcoded string, stays in sync with `pyproject.toml`.
- **`rtfm_books` pagination** — MCP tool now returns per-corpus summary + paginated listing (default 50 books/page) with `limit`/`offset` params. Previously dumped all books at once (~18k tokens for large repos).

## [0.2.2] — 2026-02-24

### Fixed
- **Auto-enable MCP in Claude Code settings** — `rtfm init` now adds `rtfm` to `enabledMcpjsonServers` in `.claude/settings.json` and `.claude/settings.local.json`. Previously the server was configured in `.mcp.json` but not activated, causing it to silently disappear from `/mcp`.
- **Simplified CLAUDE.md template** — Replaced verbose 30-line workflow with concise 4-line instruction (search, Read, Edit). Less prescriptive, better agent compliance.
- **CLI progressive disclosure** — `rtfm search` now deduplicates results by source and shows metadata-only output with absolute file paths, matching the MCP server format.
- **Semantic search slug extraction** — Fixed slug parsing in `library.py` for semantic search results.

## [0.2.0] — 2026-02-21

### Added
- **Config auto-detection** — `.rtfm/` directory found automatically (like `.git/`), no more `--db` on every command
- **Source management** — `rtfm add`, `rtfm sources` to register directories for recurring sync
- **Multi-source sync** — `rtfm sync` (no args) syncs all registered sources from `.rtfm/config.json`
- **`rtfm serve`** — start MCP server directly from CLI (replaces `python -m rtfm.mcp`)
- **`rtfm context`** / **`rtfm expand`** — CLI commands for progressive disclosure
- **`rtfm monitor`** — tail live MCP and hook activity
- **Progressive disclosure in MCP** — search/context return metadata-only (file paths, scores, chunk counts), expand returns full content
- **Absolute path resolution** — search results include absolute file paths so agents can `Read()` directly
- **End-of-content marker** — expand output ends with `⏹` to prevent "file seems truncated" false positives
- **Dual auto-sync hooks** — UserPromptSubmit (every 30s) + Stop (final sync)
- **Corpus-prefixed slugs** — FR/EN translations get distinct slugs (e.g. `published--b4-flags` vs `published-en--b4-flags`)
- **Language in search results** — `lang: fr` / `lang: en` shown when available from frontmatter

### Changed
- **FTS as default search** — `rtfm_search` defaults to `search_type="fts"` instead of `"hybrid"` (avoids 6min MiniLM cold start)
- **Data/instruction separation** — search results contain pure data (file paths, slugs, scores), no inline instructions
- **CLAUDE.md template** — simplified: "RTFM first, then Read", "NEVER Glob for research"
- **Hook architecture** — simplified from 4 hooks to 2 (UserPromptSubmit + Stop)

### Removed
- `rtfm_remember` tool — replaced by scratch files + auto-sync (simpler, same result)
- Inline `rtfm_expand()` hints in search results — replaced by `file:` / `slug:` pure data fields

### Performance (benchmarked on real tasks)
- **-51% cost** vs no-RTFM ($11.14 vs $22.61)
- **-16% duration** (6m58s vs 8m16s)
- **-61% tokens** (3.22M vs 8.21M)

## [0.1.0] — 2026-02-15

### Added
- Full-text search with SQLite FTS5 (porter stemming)
- Semantic search with sentence embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- Hybrid search (FTS5 + semantic)
- 10 smart parsers: Markdown, Python (AST), LaTeX, YAML, JSON, Shell, PDF, Legifrance XML, BOFiP HTML, plain text
- MCP server with tools: rtfm_search, rtfm_context, rtfm_discover, rtfm_stats, rtfm_sync, rtfm_ingest, rtfm_tags, rtfm_books, rtfm_tag_chunks, rtfm_remove
- `rtfm init` — one-command project setup (database, .mcp.json, CLAUDE.md, auto-sync hook, .gitignore)
- `rtfm_context` — progressive disclosure for AI agents (lazy indexing, hybrid search)
- `rtfm_discover` — fast project structure scan (~1 second)
- Incremental sync with file hash tracking and corpus isolation
- Auto-sync hook for Claude Code (UserPromptSubmit, throttled to 30s)
- Background embedding generation in MCP server (model cached in memory)
- Multi-corpus support for organizing documents by source
- Tag management (manual + batch tagging)
- Article versioning for legal documents (history, date lookup, diff)
- CLI with search, semantic-search, stats, status, sync, init, embed, books, corpora, tags, schema commands
- Python API (Library, SearchResults with to_dict/to_json/to_markdown/to_prompt)
- LLM-ready exports with to_prompt() (XML-structured context)
- `--force` flag for re-indexing all files
- Extensible metadata (domain-specific fields stored as JSON)
