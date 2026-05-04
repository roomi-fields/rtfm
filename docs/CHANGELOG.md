# Changelog

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
