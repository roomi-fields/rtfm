# Changelog

## [0.1.0] — Unreleased

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
