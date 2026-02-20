# RTFM — Project Context

## What is RTFM?

Project intelligence layer for AI coding agents. Indexes entire projects (code, docs, legal, data) and serves surgical context via MCP. Not a task manager — a knowledge layer that complements tools like GSD, Taskmaster, and Claude Flow.

## Positioning

- GSD/Taskmaster = HOW to work (workflow orchestration)
- RTFM = WHAT the agent needs to know (project knowledge)
- "GSD is the GPS. RTFM is the map."

## Architecture

```
rtfm/
├── core/
│   ├── library.py      # Main Library class (SQLite + FTS5)
│   ├── models.py       # Chunk, SearchResult, SearchResults
│   ├── embeddings.py   # Semantic search (MiniLM)
│   ├── sync.py         # Incremental file sync
│   ├── ask.py          # Traceable RAG (question answering)
│   └── llm.py          # LLM client
├── parsers/
│   ├── base.py         # BaseParser, ParserRegistry
│   ├── markdown.py     # Markdown (header-based)
│   ├── python.py       # Python (AST-based)
│   ├── latex.py        # LaTeX (section-based)
│   ├── yaml_parser.py  # YAML (top-level keys)
│   ├── json_parser.py  # JSON (keys/arrays)
│   ├── shell.py        # Shell (function-aware)
│   ├── pdf.py          # PDF (pdftext/marker)
│   ├── xml_legifrance.py  # Legifrance XML
│   ├── html_bofip.py   # BOFiP HTML
│   └── plaintext.py    # Catch-all plain text
├── plugin/
│   ├── claude_md.py    # CLAUDE.md injection for target projects
│   ├── discover.py     # Fast project structure scan
│   ├── install.py      # Orchestration for `rtfm init`
│   └── hooks.py        # Claude Code auto-sync hook
├── cli.py              # CLI (search, sync, init, status, embed, ...)
├── mcp.py              # MCP server (background embeddings)
└── schema.py           # Field documentation
```

## Key Components

- `rtfm/core/library.py` — Main Library class (SQLite + FTS5)
- `rtfm/core/sync.py` — Incremental file sync with hash tracking
- `rtfm/core/embeddings.py` — Semantic search (paraphrase-multilingual-MiniLM-L12-v2)
- `rtfm/mcp.py` — MCP server (search, context, discover, sync tools + background embeddings)
- `rtfm/plugin/install.py` — `rtfm init` orchestration
- `rtfm/plugin/discover.py` — Fast project structure scan (~1s)
- `rtfm/parsers/` — 10 document parsers (markdown, python AST, latex, yaml, json, shell, pdf, xml, html, plaintext)
- `rtfm/cli.py` — CLI interface

## Common Dev Commands

```bash
# Run tests
.venv/bin/pytest tests/ -v

# Search locally
rtfm search "query" --db db/library.db

# Stats
rtfm stats --db db/library.db

# Status (detailed)
rtfm status --db db/library.db

# Init in a project (for testing)
rtfm init --no-embeddings
```

## Environment Variables

- `RTFM_DB` — path to SQLite database (used by MCP server)

## Design Principles

1. **Search-first** — Agent should search RTFM before grepping the filesystem
2. **Progressive disclosure** — Serve minimal relevant context, not everything
3. **Zero config** — `rtfm init` should just work
4. **Incremental** — Only re-index what changed
5. **Complementary** — Works WITH workflow tools, doesn't replace them
