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
