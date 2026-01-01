# biblirag - Project Context

## Overview
Local document library with semantic search - a local alternative to NotebookLM.

## Database
- **Location**: `db/library.db` (local SQLite)
- **Content**: 3250 chunks, 100% tagged
- **Corpus**: Spiritual/philosophical texts (Nisargadatta, Ramana, etc.)

## Key Features
- **FTS5 search**: Full-text search with porter stemming
- **Semantic search**: Sentence embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- **Hybrid search**: Combines FTS5 + semantic similarity
- **Tagging**: Auto-generated via Gemini Flash

## Architecture
```
biblirag/
├── core/
│   ├── library.py      # Main Library class
│   ├── models.py       # Chunk, SearchResult, SearchResults
│   └── embeddings.py   # Embedding utilities
├── parsers/            # Document parsers (markdown, pdf, xml, html)
├── cli.py              # Command-line interface
└── schema.py           # Field documentation

config/
└── settings.py         # DB path, chunk settings

src/
└── tagger.py           # Gemini-based auto-tagger

db/
└── library.db          # Main database (3250 chunks)
```

## Common Commands
```bash
# Search
biblirag search "query" --db db/library.db

# Semantic search
biblirag semantic-search "query" --db db/library.db

# Stats
biblirag stats --db db/library.db

# Generate embeddings
biblirag embed --db db/library.db

# Tag with Gemini
GEMINI_API_KEY="..." python src/tagger.py -d db/library.db
```

## API Key
Gemini API key is stored in `/mnt/d/Claude/optimisaiton-fiscale/.env`

## Tests
```bash
.venv/bin/pytest tests/ -v
```

## Recent Changes
- Semantic search with sentence embeddings (MiniLM multilingual)
- Hybrid search (FTS5 + semantic)
- Gemini Flash tagger (batch mode, 10 chunks/request)
- 100% tagging coverage (3250 chunks)
