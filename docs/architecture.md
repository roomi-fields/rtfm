---
title: RTFM Architecture — SQLite, FTS5, parsers, edges, priority queue
description: >-
  Internal architecture of the RTFM open retrieval layer. Library class,
  SQLite + FTS5 schema, parser registry, priority-queue worker (ingest /
  embed / OCR), filesystem watcher, optional FastEmbed semantic layer.
---

# Architecture

## Pipeline

```
File on disk
  → hook / CLI / worker idle scan   (producer: detects change)
    → work_queue                    (SQLite, priority + dedup)
      → Worker daemon               (1 process, nice 19, ionice idle)
        ├─ P1 ingest                Parser → chunks → books table
        │     └─ enqueue P2 follow-up for the new chunks
        │     └─ enqueue P3 if PDF + 0 chunks + ocr_fallback
        ├─ P2 embed                 fastembed batch → chunk_embeddings
        └─ P3 OCR                   marker subprocess → re-ingest
                                       └─ enqueue P2 for OCR'd chunks
          → Search (FTS5 / semantic / hybrid)
            → Progressive disclosure (metadata → expand)
```

The queue is the spine: every producer enqueues per-file (or per-batch)
jobs, the single worker drains by priority. Granularity is intentionally
fine so a fresh P1 (file you just edited) preempts a P2/P3 backlog at
the next job boundary.

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

`work_queue` table in the same `library.db`. `Queue` class:

- `enqueue(type, payload)` → returns the row id, or `None` if a pending
  job with the same `(type, payload)` already exists (dedup).
- `dequeue()` → atomic single-statement `UPDATE … RETURNING` that picks
  the highest-priority pending row and flips it to `running`.
- `mark_done(id)` / `mark_failed(id, error)`.
- `stats()` / `list_pending()` / `list_failed()` / `retry_failed()` /
  `clear_done()` — used by `rtfm queue …`.

Concurrency: multiple producers (CLI, hooks, watcher) can enqueue at the
same time through SQLite WAL; only one consumer thanks to the worker's
`flock`. Dedup is enforced by `UNIQUE(type, payload) WHERE status =
'pending'` so a hook re-queuing the same path while the first attempt
is still pending is a no-op.

### `rtfm/core/worker.py` — The drain daemon

Single-threaded loop:

```
while not stop:
    job = queue.dequeue()
    if job is None:
        sleep IDLE_POLL_SECONDS (5 s)
        continue
    handlers[job.type](job, self)
    queue.mark_done(...)
```

Holds an exclusive `flock` on `.rtfm/worker.lock` (one worker per
project). Writes its live state atomically to `.rtfm/worker_state.json`
so `rtfm status` / `/rtfm.status` can show the running job without
touching the DB. SIGTERM/SIGINT → finish current job → exit.

### `rtfm/core/handlers.py` — Per-priority handlers

- **`handle_ingest`** (P1) — same per-file logic as the legacy inline
  sync (parse → ingest → upsert `indexed_files`). After ingest:
  - if the PDF has 0 chunks **and** `ocr_fallback: true` in
    `.rtfm/config.json` → enqueue P3 for the same file, skip P2;
  - otherwise → split the new chunks into `EMBED_BATCH_SIZE=64` batches
    and enqueue P2 jobs.
- **`handle_embed`** (P2) — load `chunk_ids` from payload, run
  `library.embed_chunks_by_id` (idempotent — already-embedded chunks
  are skipped).
- **`handle_ocr`** (P3) — drop any empty book P1 left behind, re-ingest
  with `PDFParser(backend="marker")`, enqueue P2 follow-up. Marker
  itself runs in a one-shot subprocess (see `rtfm/parsers/pdf.py`) so
  its 3–8 GB of model state is reclaimed by the OS between PDFs.

### Idle scan inside the worker (no separate watcher daemon)

There is no standalone watcher process. The worker, when its priority
queue is empty, runs the periodic source scan itself every
`SCAN_INTERVAL_SECONDS` (default 30 s). One project = one consumer
process, which is the explicit design rule.

The idle scan uses **`compute_diff` (MD5)**, not `quick_diff`. This
costs more I/O than the size+mtime check but is the only way to:

- detect **cross-corpus moves** (same MD5, different corpus) and
  transfer them inline via `Library.move_file(new_corpus=...)` —
  chunks, embeddings, tags survive untouched;
- skip **mtime false-positives** that bite on NTFS-via-WSL whenever
  a file is touched without its content changing.

**Why polling, not inotify**: RTFM frequently indexes Obsidian vaults
on `/mnt/d/…` (NTFS via WSL). Inotify events do not propagate across
that boundary, so a pure-inotify scheme would silently miss every
change there. The poll runs only while the queue is empty, so a long
ingest or OCR run is never paused to scan.

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

| Command | Mode | Notes |
|---|---|---|
| `rtfm sync` | enqueue (default) | scans sources, enqueues P1 jobs, auto-spawns worker, returns immediately |
| `rtfm sync --inline` | legacy blocking | same code path as 0.9.x; useful for CI / `--no-embeddings` / `--ocr` daemon mode |
| `rtfm sync --ocr` | enqueue P3 | persists `ocr_fallback: true`, enqueues a P3 for every flagged scan, returns |
| `rtfm embed` | enqueue (default) | scans for chunks without embedding, enqueues P2 batches |
| `rtfm embed --force` / `--inline` | legacy blocking | re-embed everything, or a one-shot run |
| `rtfm worker [start \| stop \| status] [--scan-interval S]` | manage daemon | one process per project; idle scan folded in (no separate watcher) |
| `rtfm queue [stats \| list \| failed \| clear-done \| retry-failed]` | inspect / manage queue | |
| `rtfm status` | health report | now includes `Worker / Queue:` section |

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
