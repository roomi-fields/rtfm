# biblirag

Local document library with semantic search - like NotebookLM but local and extensible.

## Features

- **Full-text search** with SQLite FTS5 (porter stemming)
- **Pluggable parsers** for PDF, Markdown, XML, HTML
- **Multi-corpus support** for organizing documents
- **LLM tagging** with local Ollama
- **Python API** for integration into your apps
- **Extensible metadata** for domain-specific fields

## Installation

```bash
pip install -e .

# With PDF support
pip install -e ".[pdf]"
```

## Quick Start

### Python API

```python
from biblirag import Library

# Open or create a library
lib = Library("library.db")

# Search
results = lib.search("self-realization", limit=10)
for r in results:
    print(f"{r.source} ({r.page})")
    print(r.content[:200])

# Export for LLM
prompt_context = results.to_prompt(max_chars=8000)

# Export as JSON (for API)
json_data = results.to_json()

# Export as Markdown (for display)
markdown = results.to_markdown()
```

### Search with filters

```python
# Filter by corpus
results = lib.search("amortissement", corpus="cgi")

# Filter by tags
results = lib.search("tax", tags=["fiscal", "deduction"])

# Filter by book
results = lib.search("ego", book="inner-journey-home")

# Multiple corpora
results = lib.search("article 39", corpus=["cgi", "bofip"])
```

### Corpus management

```python
# List all books
lib.list_books()

# List books in a corpus
lib.list_books(corpus="legal")

# List all corpora with stats
lib.list_corpora()

# Get library stats
lib.get_stats()
# {'books': 10, 'chunks': 3250, 'total_chars': 5843386, 'tagged_chunks': 145}
```

### Extended metadata

biblirag stores core fields and allows custom metadata for domain-specific needs:

```python
from biblirag import METADATA_EXAMPLES

# Example for French legal documents
chunk.metadata = {
    "numero_article": "39 decies A",
    "code": "cgi",
    "date_debut": "2024-01-01",
}

# Your app handles domain logic
def lien_legifrance(article):
    return f"https://legifrance.gouv.fr/search?query={article}"
```

See `biblirag/schema.py` for the full schema and examples.

## Architecture

```
biblirag/
├── core/
│   ├── library.py      # Main Library class
│   └── models.py       # Chunk, SearchResult, SearchResults
├── parsers/
│   ├── base.py         # BaseParser, ParserRegistry
│   └── markdown.py     # Markdown parser
└── schema.py           # Field documentation
```

### Adding a custom parser

```python
from biblirag.parsers.base import BaseParser, ParserRegistry

@ParserRegistry.register
class XMLParser(BaseParser):
    extensions = ['.xml']
    name = "xml"

    def parse(self, path, metadata=None):
        # Parse XML and yield Chunk objects
        yield Chunk(
            id="...",
            content="...",
            book_title="...",
            # ...
        )
```

## Database

biblirag uses SQLite with FTS5 for full-text search. The database can be shared across machines via network storage (NFS, SMB) using WAL mode for concurrent access.

```python
# Shared database on NAS
lib = Library(r"\\filer\homes\biblirag\library.db")
```

## License

MIT
