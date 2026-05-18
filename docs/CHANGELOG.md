---
title: RTFM Changelog
description: >-
  Release notes for RTFM (rtfm-ai) — every version since 0.1.0 with
  added features, bug fixes, and breaking changes.
---

# Changelog

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
