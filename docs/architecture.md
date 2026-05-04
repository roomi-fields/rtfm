# Architecture

## Pipeline

```
File on disk
  → Parser (one per format)
    → Chunks (content + metadata)
      → SQLite (books + chunks + FTS5)
        → Search (FTS5 / semantic / hybrid)
          → Progressive disclosure (metadata → expand)
```

## Core Modules

- **[[docs/obsidian-vault-guide|Obsidian Vault Guide]]** — `rtfm vault` integration
- **[[README|README]]** — Project overview and quick start

### `rtfm/core/library.py` — Main Library class

SQLite database with FTS5 virtual table. Handles ingest, search, graph queries, embeddings.

Key methods: `search()`, `semantic_search()`, `hybrid_search()`, `ingest()`, `rerank()`, `get_neighbors()`, `get_in_degree()`.

### `rtfm/core/sync.py` — Incremental sync engine

Tracks file hashes in `indexed_files` table. Only re-parses what changed. Detects moves via hash matching. Resolves edges (imports, links, [[wikilinks]]).

### `rtfm/core/embeddings.py` — Semantic search

Uses `paraphrase-multilingual-MiniLM-L12-v2` via FastEmbed (ONNX, no GPU). Cosine similarity search over chunk embeddings.

### `rtfm/core/models.py` — Data models

`Chunk`, `SearchResult`, `SearchResults`, `EdgeCandidate`. Export formats: JSON, Markdown, XML prompt.

## Parser Architecture

See [[docs/parsers|Parsers Guide]].

15 built-in parsers, extensible via `@ParserRegistry.register`. Each parser implements `parse()` → `Iterator[Chunk]` and optionally `extract_edges()` → `list[EdgeCandidate]`.

## Plugin System

### `rtfm/plugin/install.py` — `rtfm init`

Creates `.rtfm/`, `.mcp.json`, `CLAUDE.md`, auto-sync hooks. Registers project as source.

### `rtfm/plugin/vault.py` — `rtfm vault`

Obsidian-specific initialization. Detects vault, proposes corpus mapping, generates `_rtfm/` navigation. See [[docs/obsidian-vault-guide|Obsidian Guide]].

### `rtfm/plugin/vault_output.py` — `_rtfm/` generation

Generates Obsidian-native .md files: index, graph, corpus pages, recent. Uses wikilinks, YAML frontmatter, Mermaid diagrams, callouts.

### `rtfm/plugin/hooks.py` — Auto-sync

Two Claude Code hooks:
- `UserPromptSubmit` → incremental FTS sync (throttled 30s)
- `Stop` → final sync to capture last writes

## MCP Server

`rtfm/mcp.py` — Exposes search, expand, context, sync, discover, graph, history tools. Background embedding generation.

## Database Schema

| Table | Purpose |
|---|---|
| `books` | Documents (slug, title, filename, corpus, metadata) |
| `chunks` | Content segments (content, line_start, line_end, tags) |
| `chunks_fts` | FTS5 virtual table for full-text search |
| `edges` | Dependency graph (source → target, relation_type) |
| `indexed_files` | Sync tracking (filepath, hash, corpus) |
| `chunk_embeddings` | Vector embeddings (BLOB) |
| `sync_roots` | Project roots per corpus |
| `file_versions` | File snapshots for versioning |

## Graph System

Edges extracted from:
- Python imports (`import x`, `from x import y`)
- Markdown links (`[text](path)`)
- Obsidian wikilinks (`[[target]]`, `[[target|display]]`)
- LaTeX includes (`\input{}`, `\include{}`, `\cite{}`)

Used for: hub detection, orphan detection, centrality-based reranking.
