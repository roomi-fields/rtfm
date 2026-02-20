# RTFM - Project Context

## Overview
Read The F***ing Manual — Claude Code plugin for indexed project knowledge.
Local document library with semantic search, MCP server, and plugin architecture.

## Database
- **Location**: `db/library.db` (local SQLite)
- **Content**: 3250 chunks, 100% tagged
- **Corpus**: Spiritual/philosophical texts (Nisargadatta, Ramana, etc.)

## Key Features
- **FTS5 search**: Full-text search with porter stemming
- **Semantic search**: Sentence embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- **Hybrid search**: Combines FTS5 + semantic similarity
- **Tagging**: Auto-generated via Gemini Flash
- **MCP server**: Exposes search/sync/context tools to Claude Code
- **Plugin**: Auto-configures CLAUDE.md + .mcp.json for any project

## Architecture
```
rtfm/
├── core/
│   ├── library.py      # Main Library class
│   ├── models.py       # Chunk, SearchResult, SearchResults
│   ├── embeddings.py   # Embedding utilities
│   ├── sync.py         # Incremental sync
│   ├── ask.py          # Traceable RAG
│   └── llm.py          # Gemini LLM client
├── plugin/
│   ├── claude_md.py    # CLAUDE.md injection
│   ├── discover.py     # Project scanner
│   ├── install.py      # rtfm init orchestration
│   └── hooks.py        # Claude Code hooks
├── parsers/            # Document parsers (markdown, pdf, xml, html, plaintext)
├── cli.py              # Command-line interface
├── mcp.py              # MCP server
└── schema.py           # Field documentation

config/
└── settings.py         # DB path, chunk settings

db/
└── library.db          # Main database (3250 chunks)
```

## Common Commands
```bash
# Search
rtfm search "query" --db db/library.db

# Semantic search
rtfm semantic-search "query" --db db/library.db

# Stats
rtfm stats --db db/library.db

# Generate embeddings
rtfm embed --db db/library.db

# Initialize in a project
rtfm init --no-embeddings

# Tag with Gemini
GEMINI_API_KEY="..." python src/tagger.py -d db/library.db
```

## Environment Variables
- `RTFM_DB` — path to SQLite database (used by MCP server)
- `GEMINI_API_KEY` — for RAG and tagging

## API Key
Gemini API key is stored in `/mnt/d/Claude/optimisaiton-fiscale/.env`

## Tests
```bash
.venv/bin/pytest tests/ -v
```

## Recent Changes
- Renamed from biblirag to rtfm
- Plugin architecture (claude_md, discover, install, hooks)
- MCP tools: rtfm_discover, rtfm_context
- Semantic search with sentence embeddings (MiniLM multilingual)
- Hybrid search (FTS5 + semantic)
- Gemini Flash tagger (batch mode, 10 chunks/request)
- 100% tagging coverage (3250 chunks)
