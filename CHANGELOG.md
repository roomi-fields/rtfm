# Changelog

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
