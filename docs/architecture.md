---
title: RTFM Architecture — SQLite, FTS5, parsers, edges, priority queue
description: >-
  Internal architecture of the RTFM open retrieval layer. Library class,
  SQLite + FTS5 schema, parser registry, priority-queue worker (ingest /
  embed / OCR), filesystem watcher, optional FastEmbed semantic layer.
---

# Architecture

## Pipeline

Every write to the DB goes through the worker. The CLI, the hooks, the
slash commands and the worker's own periodic ticks are all *producers*;
the worker is the only consumer. There is no other path — and that's the
property the rest of the architecture depends on.

```
File on disk
  ↑                            (producers — enqueue jobs)
  │   ┌── CLI commands         → P0 (user-explicit)
  │   ├── slash commands       → P0
  │   ├── PostToolUse hook     → P3 ingest (edited file)
  │   └── Worker periodic tick → P1 scan / P4 reconcile
  │
  └── work_queue (SQLite, priority + dedup)
                ↓
      Worker daemon  (1 process per project, nice 19, ionice idle)
                ↓ dequeue by priority, FIFO within priority
      Handler dispatch:
        P0 = user-explicit            (priority lane, no work in itself)
        P1 scan       → compute_diff, fan out P2 remove + P3 ingest
        P2 remove     → drop a vanished file from the index
        P3 ingest     → parse one file → chunks → books
                        + enqueue P5 embed for the new chunks
                        + enqueue P6 OCR if PDF + ocr_fallback + scan
        P4 reconcile  → purge orphan embeddings, re-queue un-embedded
        P4 vacuum     → reclaim space (auto after big remove batch)
        P5 embed      → fastembed batch → chunk_embeddings
        P6 OCR        → tesseract page-range → append chunks
                        + enqueue P5 for those chunks
                ↓
      Search (FTS5 / semantic / hybrid)
        → Progressive disclosure (metadata → expand)
```

Granularity is intentionally fine — 1 source per `scan`, 1 file per
`ingest`/`remove`, 1 batch per `embed`, 1 page-range per `ocr` — so a
fresh P0 command preempts a long P5/P6 backlog at the next job boundary
(a handful of seconds, not hours).

## Core Modules

- **[[docs/obsidian-vault-guide|Obsidian Vault Guide]]** — `rtfm vault` integration
- **[[README|README]]** — Project overview and quick start

### `rtfm/core/library.py` — Main `Library` class

SQLite database with FTS5 virtual table. Handles ingest, search, graph
queries, embeddings. Key methods: `search()`, `semantic_search()`,
`hybrid_search()`, `ingest()`, `move_file()` (cross-corpus moves preserve
chunk ids → embeddings + tags survive), `embed_chunks_by_id()` (called by
the P2 handler), `chunk_ids_for_book()` / `chunk_ids_without_embedding()`
(used by producers to enqueue P2 backfills).

### `rtfm/core/sync.py` — Diff engine

Tracks file hashes in `indexed_files` table. `compute_diff()` walks the
filesystem and classifies each file as `added` / `modified` / `removed`
/ `moved` / `cross_moved` (same MD5 in another corpus → transfer
ownership, no re-ingest). `quick_diff()` skips MD5 (size + mtime) — used
by the hot path of `rtfm sync` and the watcher.

### `rtfm/core/queue.py` — Persistent priority queue

`work_queue` table in the same `library.db`. Seven priority lanes:

| Priority | Type(s)             | Who enqueues                              |
|---------:|---------------------|-------------------------------------------|
| **P0**   | any                 | explicit user (CLI, slash command)        |
| **P1**   | `scan`              | worker periodic tick, also any user P0    |
| **P2**   | `remove`            | the `scan` handler when files vanished    |
| **P3**   | `ingest`            | the `scan` handler, PostToolUse hook      |
| **P4**   | `reconcile`, `vacuum` | worker periodic tick; auto after big remove |
| **P5**   | `embed`             | `ingest` handler                          |
| **P6**   | `ocr`               | `ingest` handler when PDF + `ocr_fallback` |

`Queue` class:

- `enqueue(type, payload, priority=None)` → returns the row id, or `None`
  if a pending job with the same `(type, payload)` already exists. The
  default priority comes from `DEFAULT_PRIORITY[type]`; callers pass
  `priority=P_USER` (= 0) to claim the P0 lane.
- `dequeue()` → atomic single-statement `UPDATE … RETURNING` that picks
  the highest-priority pending row (lowest number wins) and flips it to
  `running`.
- `mark_done(id)` / `mark_failed(id, error)`.
- `stats()` / `list_pending()` / `list_failed()` / `retry_failed()` /
  `clear_done()` — used by `rtfm queue …`.

Concurrency: multiple producers (CLI, hooks, MCP) can enqueue at the
same time through SQLite WAL; only one consumer thanks to the worker's
`flock`. Dedup is enforced by `UNIQUE(type, payload) WHERE status =
'pending'` so a periodic tick re-queuing the same scan while the first
one is still pending is a no-op.

On a pre-0.18 DB the `work_queue` table only knew three job types
(`ingest`, `embed`, `ocr`) via a CHECK constraint. The first time a
0.18+ `Queue` opens such a DB it rebuilds the table in place — rows
preserved — so the new types can be enqueued.

### `rtfm/core/worker.py` — The drain daemon

Single-threaded loop. **All DB writes pass through here** — the CLI, the
hooks and the MCP server only enqueue:

```
while not stop:
    job = queue.dequeue()
    if job is None:
        _maybe_scan()         # enqueue P1 scans every SCAN_INTERVAL
        _maybe_reconcile()    # enqueue P4 reconcile every hour
        sleep IDLE_POLL_SECONDS (5 s)
        continue
    HANDLERS[job.type](job, self)
    queue.mark_done(...)
```

Holds an exclusive `flock` on `.rtfm/worker.lock` (one worker per
project). Writes its live state atomically to `.rtfm/worker_state.json`
so `rtfm status` / `/rtfm.status` can show the running job without
touching the DB. SIGTERM/SIGINT → finish current job → exit.

Preemption is at job boundary, not in the middle of a job: a fresh P0
`scan` queued mid-OCR waits for that OCR tranche (a few minutes at
most, never a full book) to finish before running. Long work is
deliberately chunked — 1 file, 1 batch of 64 chunks, 1 page-range of
50 pages — so the "next boundary" arrives quickly.

### `rtfm/core/handlers.py` — One handler per job type

- **`handle_scan`** (P1) — walks a source via `scan_directory` +
  `compute_diff`, applies cross-corpus and same-corpus moves inline
  (cheap row updates; chunks, embeddings, tags survive), then fans out
  child jobs: a P2 `remove` per disappeared file, a P3 `ingest` per new
  or modified file. A **mass-removal circuit breaker** refuses to enqueue
  removes if a single scan would drop more than 25 files and more than
  25 % of the corpus — the signature of a flaky mount or a mid-reorg
  scan, not real deletions. `force_remove=True` in the payload overrides.
  When the breaker fires, the index is left intact and a warning is
  surfaced. When a scan does emit a big batch of removes (above
  `AUTO_VACUUM_AFTER_REMOVES`, default 200), a P4 `vacuum` is queued
  behind to reclaim the freed pages.
- **`handle_remove`** (P2) — drops the book row (chunks cascade via FK)
  and the `indexed_files` tracking entry. A path that's no longer
  tracked is logged and skipped, never raised.
- **`handle_ingest`** (P3) — parse → ingest → upsert `indexed_files`.
  After ingest:
  - if the PDF has 0 chunks **and** `ocr_fallback: true` in
    `.rtfm/config.json` → enqueue P6 OCR jobs (one per page-range
    tranche), skip P5;
  - otherwise → split the new chunks into `EMBED_BATCH_SIZE=64` batches
    and enqueue P5 jobs.
- **`handle_reconcile`** (P4) — purge orphan embeddings, re-queue chunks
  missing an embedding. Optional `{"vacuum": true}` payload enqueues a
  follow-up vacuum if anything was purged.
- **`handle_vacuum`** (P4) — opens its own SQLite connection (Library's
  long-lived one would block VACUUM), runs `VACUUM` in autocommit, logs
  the before→after size.
- **`handle_embed`** (P5) — load `chunk_ids` from payload, run
  `library.embed_chunks_by_id` (idempotent — already-embedded chunks
  are skipped).
- **`handle_ocr`** (P6) — tesseract via pypdfium2 on a page range,
  append chunks idempotently, enqueue P5 follow-up.

### Periodic ticks: just enqueuers

The worker has two periodic ticks, both throttled and both idempotent
thanks to the queue's dedup:

- **`_maybe_scan`** (every `SCAN_INTERVAL_SECONDS`, default 30 s) →
  enqueues one P1 `scan` job per configured source.
- **`_maybe_reconcile`** (every `RECONCILE_INTERVAL_SECONDS`, default
  1 h) → enqueues one P4 `reconcile` job.

Neither does any scanning or reconciling itself — that work lives in
`handle_scan` and `handle_reconcile`. There is no `_scan_once` method
anymore; if you find a reference to it, that's a stale doc.

**Why polling for the scan tick, not inotify**: RTFM frequently indexes
Obsidian vaults on `/mnt/d/…` (NTFS via WSL). Inotify events do not
propagate across that boundary, so a pure-inotify scheme would silently
miss every change there. The tick only enqueues; the actual scan still
uses `compute_diff` (MD5) inside the `scan` handler, which is the only
way to:

- detect **cross-corpus moves** (same MD5, different corpus) and
  transfer them inline via `Library.move_file(new_corpus=...)` —
  chunks, embeddings, tags survive untouched;
- skip **mtime false-positives** that bite on NTFS-via-WSL whenever
  a file is touched without its content changing.

### `rtfm/core/embeddings.py` — Semantic search

Uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via
FastEmbed (ONNX, no GPU). Cosine similarity over chunk embeddings.
`resolve_model()` also accepts the legacy short name
(`paraphrase-multilingual-MiniLM-L12-v2`) for back-compat with DBs
written by older RTFM versions.

### `rtfm/core/models.py` — Data models

`Chunk`, `SearchResult`, `SearchResults`, `EdgeCandidate`. Export
formats: JSON, Markdown, XML prompt.

## Parser Architecture

See [[docs/parsers|Parsers Guide]].

22 built-in parsers, extensible via `@ParserRegistry.register`. Each
parser implements `parse()` → `Iterator[Chunk]` and optionally
`extract_edges()` → `list[EdgeCandidate]`. The PDF parser supports
three backends:

- `pdftext` (default) — fast, basic text extraction.
- `marker` — high-quality with layout awareness and OCR; runs in a
  one-shot subprocess per PDF for memory isolation.
- `auto` — try `pdftext` first, fall back to `marker` if it yields no
  text (= scan).

## Plugin System

### `rtfm/plugin/install.py` — `rtfm init`

Creates `.rtfm/`, `.mcp.json`, `CLAUDE.md`, registers Claude Code hooks,
adds the project as a source.

### `rtfm/plugin/vault.py` — `rtfm vault`

Obsidian-specific initialization. Detects vault, proposes corpus
mapping, generates `_rtfm/` navigation. See
[[docs/obsidian-vault-guide|Obsidian Guide]].

### `rtfm/plugin/vault_output.py` — `_rtfm/` generation

Generates Obsidian-native `.md` files: index, graph, corpus pages,
recent. Uses wikilinks, YAML frontmatter, Mermaid diagrams, callouts.

### `hooks/` — Claude Code integration

Event-driven, never re-scans full sources. Three hooks plus a hidden
record helper:

- **`PostToolUse`** (matcher `Write|Edit|MultiEdit|NotebookEdit`) →
  `rtfm_record_edit.py` appends the target `file_path` to
  `.rtfm/touched_files.tmp`. O(1).
- **`Stop`** → `rtfm_stop_sync.py` reads that queue, groups by source,
  runs `sync(files=[…])` only for the touched files, clears the queue
  on success.
- **`UserPromptSubmit`** → `rtfm_sync.py` is a catch-up drain in case
  a previous session was abandoned before its Stop hook ran.
- **`SessionStart`** → `rtfm_bootstrap.py` initialises the project if
  needed.

## MCP Server

`rtfm/mcp.py` — Exposes `rtfm_search`, `rtfm_expand`, `rtfm_context`,
`rtfm_books`, `rtfm_sync`, `rtfm_discover`, `rtfm_graph`, `rtfm_history`
tools. Tolerates numeric params as JSON strings (`"limit": "5"`) for
clients that don't honour the integer schema. Background embedding
generation kicks off the first time semantic search is requested.

## CLI Surface

Every mutating command follows the same shape: **enqueue P0 jobs, ensure
the worker is alive, watch the queue until pending and running both
hit zero, exit**. `--background` skips the watching loop and returns
immediately. No command ever writes to the DB directly — that's the
property the architecture is built around.

| Command | Enqueues | Notes |
|---|---|---|
| `rtfm sync` | P0 `scan` per source | watches; `--force-remove` flows into the payload; `--dry-run` prints the plan without enqueuing; `--files FILE…` enqueues P0 `ingest` instead of scanning |
| `rtfm sync --ocr` | P0 `ocr` per flagged scan | also persists `ocr_fallback: true` so future ingestions auto-OCR |
| `rtfm reindex --ext / --parser / --corpus` | P0 `ingest` (filtered) | bumped to P0 — user's explicit refresh wins over the periodic backlog |
| `rtfm gc [--vacuum]` | P0 `reconcile` | `--vacuum` flag rides in the payload, fires only if something was purged |
| `rtfm vacuum` | P0 `vacuum` | reports before→after size |
| `rtfm doctor` | P0 `scan`s + P0 `reconcile` | full pass + diagnostic report |
| `rtfm backfill-pages` | P0 `ingest` (filtered) | re-parse to repopulate stale `page_count` |
| `rtfm embed` | enqueue (default) | scans for chunks without embedding, enqueues P5 batches |
| `rtfm worker [start \| stop \| status] [--scan-interval S]` | manage daemon | one process per project; periodic ticks fold in |
| `rtfm queue [stats \| list \| failed \| clear-done \| retry-failed]` | inspect / manage queue | |
| `rtfm status` | health report | includes `Worker / Queue:` section |

## Database Schema

| Table | Purpose |
|---|---|
| `books` | Documents (slug, title, filename, corpus, metadata) |
| `chunks` | Content segments (content, line_start, line_end, tags) |
| `chunks_fts` | FTS5 virtual table for full-text search |
| `edges` | Dependency graph (source → target, relation_type) |
| `indexed_files` | Sync tracking (filepath, hash, corpus, book_slug) |
| `chunk_embeddings` | Vector embeddings (BLOB) |
| `sync_roots` | Project roots per corpus |
| `file_versions` | File snapshots for versioning |
| **`work_queue`** | Persistent priority queue (type, priority, payload JSON, status, attempts) |

`work_queue` indexes:

- `idx_queue_pending(priority ASC, created_at ASC) WHERE status =
  'pending'` — the hot path of `dequeue()`.
- `idx_queue_unique_pending(type, payload) WHERE status = 'pending'` —
  partial unique index for dedup.

## Graph System

Edges extracted from:

- Python imports (`import x`, `from x import y`)
- Markdown links (`[text](path)`)
- Obsidian wikilinks (`[[target]]`, `[[target|display]]`)
- LaTeX includes (`\input{}`, `\include{}`, `\cite{}`)

Used for: hub detection, orphan detection, centrality-based reranking.

## Resource Bounds

A single project run as a whole obeys:

- **At most one worker process per project** (`flock` on
  `.rtfm/worker.lock`). The same process drains the queue and runs
  the idle scan — no separate watcher daemon.
- The worker inherits `nice 19` and `ionice -c 3` (idle I/O class)
  when those binaries are available, so it never steals CPU or disk
  from the user's foreground work.
- The OCR (marker) backend runs in a **one-shot subprocess per PDF**;
  the OS reclaims its 3–8 GB of model state on exit. No leak across
  the run.
- Producers (CLI, hooks, watcher) never block on the worker — they
  enqueue, possibly spawn it, and return.

## Contributors

Thanks to everyone who reported issues and tested RTFM.
