# RTFM — Project Context

## What is RTFM?

The open retrieval layer for AI coding agents. Indexes entire projects (code, docs, legal, research, data) and serves surgical context via MCP.

Key differentiator: extensible parser architecture. Anyone can add support for any file format in ~50 lines of Python — or, for JSON-based formats, ~30 lines of declarative YAML via the JSON schema mappings system (`.rtfm/mappings/`). Ships with 15 parsers, the community can add any format.

Not a task manager — a knowledge layer that complements GSD, Taskmaster, Claude Flow, and any workflow tool.

## Positioning

- Augment Context Engine / Sourcegraph = closed, code-only, enterprise pricing
- RTFM = open source, multi-domain, extensible, free
- "Augment indexes your code. RTFM indexes everything."
- Works WITH workflow tools (GSD = GPS, RTFM = map)

## Architecture

```
rtfm/
├── core/
│   ├── library.py      # Main Library class (SQLite + FTS5)
│   ├── models.py       # Chunk, SearchResult, SearchResults
│   ├── embeddings.py   # Semantic search (MiniLM)
│   └── sync.py         # Incremental file sync
├── parsers/
│   ├── base.py         # BaseParser, ParserRegistry
│   ├── markdown.py     # Markdown (header-based)
│   ├── python.py       # Python (AST-based)
│   ├── latex.py        # LaTeX (section-based)
│   ├── yaml_parser.py  # YAML (top-level keys)
│   ├── json_parser.py  # JSON (keys/arrays)
│   ├── toml_parser.py  # TOML (top-level tables; depends_on edges)
│   ├── shell.py        # Shell (function-aware)
│   ├── pdf.py          # PDF (pdftext/marker)
│   ├── xml_legifrance.py  # Legifrance XML
│   ├── html_bofip.py   # BOFiP HTML
│   ├── sqlite_parser.py   # SQLite DB (schema + samples; FK edges)
│   ├── jupyter.py      # Jupyter .ipynb (cells grouped by heading)
│   ├── csv_parser.py   # CSV/TSV (overview + sample with type inference)
│   ├── xlsx.py         # XLSX (per-sheet schema + sample, openpyxl)
│   ├── plaintext.py    # Catch-all plain text
│   └── mappings/       # Generic JSON schema mappings (.rtfm/mappings/*.yaml)
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
- `rtfm/parsers/` — 15 document parsers (markdown, python AST, latex, yaml, json, toml, shell, pdf, xml, html, sqlite, jupyter, csv/tsv, xlsx, plaintext)
- `rtfm/cli.py` — CLI interface

## Common Dev Commands

```bash
# Run tests
.venv/bin/pytest rtfm/tests/ -v

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

## RTFM — Indexed Knowledge Base

This project has been indexed with RTFM.

For any **exploratory search** (finding which files/modules/classes are relevant
to a topic), use `rtfm_search` instead of Glob, find, ls, or broad Grep.
Then use `rtfm_expand` to read easily most relevant files/sections.
