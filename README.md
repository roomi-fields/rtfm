# biblirag

Local document library with semantic search - like NotebookLM but local and extensible.

## Features

- **Full-text search** with SQLite FTS5 (porter stemming)
- **Semantic search** with sentence embeddings (multilingual MiniLM)
- **Hybrid search** combining FTS5 keywords and semantic similarity
- **Pluggable parsers** for Markdown, XML (Legifrance), HTML (BOFiP)
- **Multi-corpus support** for organizing documents
- **Python API** for integration into your apps
- **CLI** for command-line operations
- **LLM-ready exports** with `to_prompt()` for AI workflows
- **Extensible metadata** for domain-specific fields

## Installation

```bash
# Basic installation
pip install -e .

# With PDF support (optional)
pip install -e ".[pdf]"
```

## Quick Start

### Creating a Library

```python
from biblirag import Library

# Create or open a library (creates the file if it doesn't exist)
lib = Library("my_library.db")

# Or specify create=False to only open existing libraries
lib = Library("existing_library.db", create=False)
```

### Ingesting Documents

```python
from biblirag import Library

lib = Library("my_library.db")

# Ingest a Markdown file
stats = lib.ingest("documents/article.md", corpus="articles")
print(f"Indexed {stats['chunks']} chunks ({stats['chars']} chars)")

# Ingest XML from Legifrance (French legal codes)
stats = lib.ingest("legal/cgi_article.xml", corpus="cgi")

# Ingest HTML from BOFiP (French tax doctrine)
stats = lib.ingest("doctrine/boi-is-base.html", corpus="bofip")

# Ingest with custom metadata
stats = lib.ingest(
    "documents/report.md",
    corpus="reports",
    metadata={"author": "Legal Team", "year": 2024}
)
```

### Searching

```python
from biblirag import Library

lib = Library("my_library.db")

# Basic search
results = lib.search("amortissement", limit=10)

# Filter by corpus
results = lib.search("article 39", corpus="cgi")

# Filter by multiple corpora
results = lib.search("deduction fiscale", corpus=["cgi", "bofip"])

# Filter by specific book
results = lib.search("depreciation", book="tax-guide-2024")

# Filter by tags
results = lib.search("investment", tags=["fiscal", "enterprise"])

# Use raw FTS5 query syntax
results = lib.search('"exact phrase" OR alternative', raw_query=True)

# Iterate over results
for r in results:
    print(f"[{r.rank}] {r.source} ({r.page}) - Score: {r.score:.2f}")
    print(f"    {r.content[:200]}...")
    if r.tags:
        print(f"    Tags: {', '.join(r.tags)}")
```

### Using Search Results

The `SearchResults` object provides multiple export formats:

```python
results = lib.search("depreciation", limit=5)

# Export as dictionary (for APIs)
data = results.to_dict()
# Returns: {"query": "...", "total_found": N, "results": [...]}

# Export as JSON string
json_str = results.to_json()

# Export as Markdown (for display/reports)
markdown = results.to_markdown()

# Export for LLM prompting (optimized context injection)
prompt_context = results.to_prompt(max_chars=8000)
# Returns XML-formatted context ready for LLM consumption
```

Example LLM integration:

```python
from biblirag import Library

lib = Library("knowledge_base.db")
results = lib.search("capital gains tax", limit=5)

# Build prompt with search context
prompt = f"""Based on the following documents:

{results.to_prompt(max_chars=6000)}

Question: How are capital gains taxed for individuals?
"""

# Send to your LLM of choice
# response = llm.generate(prompt)
```

### Corpus Management

```python
lib = Library("my_library.db")

# Get library statistics
stats = lib.get_stats()
# {'books': 10, 'chunks': 3250, 'total_chars': 5843386, 'tagged_chunks': 145, 'corpora': 3}

# List all corpora with stats
for corpus in lib.list_corpora():
    print(f"{corpus['corpus']}: {corpus['book_count']} books, {corpus['total_chunks']} chunks")

# List all books
for book in lib.list_books():
    print(f"[{book['corpus']}] {book['title']}: {book['chunk_count']} chunks")

# List books in a specific corpus
for book in lib.list_books(corpus="legal"):
    print(f"{book['title']}: {book['chunk_count']} chunks")

# Delete a book
lib.delete_book("outdated-document-slug")
```

## CLI Usage

biblirag includes a command-line interface for common operations.

### Search

```bash
# Basic search
biblirag search "depreciation" --db library.db

# Limit results
biblirag search "article 39" --limit 5

# Filter by corpus
biblirag search "tax deduction" --corpus cgi

# Filter by book
biblirag search "amortissement" --book code-general-impots

# Output formats
biblirag search "query" --format text      # Default: human-readable
biblirag search "query" --format json      # JSON output
biblirag search "query" --format markdown  # Markdown output
biblirag search "query" --format prompt    # LLM-ready format

# Control max chars for prompt format
biblirag search "query" --format prompt --max-chars 4000
```

### Statistics

```bash
# Show library statistics
biblirag stats --db library.db
# Output:
# Books:         10
# Chunks:        3250
# Total chars:   5,843,386
# Tagged chunks: 145
# Corpora:       3
```

### List Books and Corpora

```bash
# List all books
biblirag books --db library.db

# List books in a specific corpus
biblirag books --corpus legal

# Output as JSON
biblirag books --format json

# List all corpora
biblirag corpora --db library.db

# Output as JSON
biblirag corpora --format json
```

### View Schema

```bash
# Display field schema documentation
biblirag schema
```

## Parsers

biblirag includes parsers for common document formats. Parsers are auto-detected based on file extension.

### Available Parsers

| Parser | Extensions | Description |
|--------|------------|-------------|
| `markdown` | `.md`, `.markdown` | Markdown files with header-based chunking |
| `pdf` | `.pdf` | PDF files (requires `pip install biblirag[pdf]`) |
| `legifrance` | `.xml` | French legal codes in LEGI XML format |
| `bofip` | `.html`, `.htm` | French tax doctrine (BOFiP) HTML files |

### Markdown Parser

Parses Markdown files, splitting content by headers into chunks.

```python
# Automatic detection
lib.ingest("document.md", corpus="docs")

# Supports YAML frontmatter for metadata
# ---
# title: My Document
# author: Jane Doe
# ---
# # Content starts here
```

### PDF Parser

Parses PDF files using `pdftext` (fast) or `marker-pdf` (high quality).

```python
# Install PDF support
# pip install biblirag[pdf]

# Basic usage (uses pdftext backend)
lib.ingest("document.pdf", corpus="docs")

# Use marker backend for complex PDFs
from biblirag.parsers.pdf import PDFParser
parser = PDFParser(backend='marker')
lib.ingest("complex.pdf", corpus="docs", parser=parser)
```

### Legifrance XML Parser

Parses French legal XML files in LEGI format (from data.gouv.fr).

```python
# Ingest a legal code XML file
lib.ingest("code_general_impots.xml", corpus="cgi")

# Each article becomes a chunk with legal metadata:
# - numero_article: Article number (e.g., "39 decies A")
# - code: Code identifier
# - date_debut, date_fin: Validity dates
# - etat: Status (VIGUEUR, ABROGE, etc.)
```

### BOFiP HTML Parser

Parses HTML exports from the French tax doctrine database (bofip.impots.gouv.fr).

```python
# Ingest BOFiP HTML file
lib.ingest("boi-is-base-10.html", corpus="bofip")

# Metadata includes:
# - identifiant_boi: BOI identifier
# - serie, division: Classification
# - date_publication: Publication date
# - references_cgi: Extracted CGI article references
```

### Custom Parsers

Create custom parsers by extending `BaseParser`:

```python
from biblirag.parsers.base import BaseParser, ParserRegistry
from biblirag.core.models import Chunk

@ParserRegistry.register
class MyCustomParser(BaseParser):
    extensions = ['.myext']
    name = "custom"

    def parse(self, path, metadata=None):
        """Parse file and yield Chunk objects."""
        metadata = metadata or {}

        # Read and process your file
        with open(path, 'r') as f:
            content = f.read()

        # Yield chunks
        yield Chunk(
            id="unique-chunk-id",
            content=content,
            book_title=metadata.get('title', path.stem),
            book_slug=path.stem.lower(),
            page_start=1,
            page_end=1,
            # ... other fields
        )

    def extract_metadata(self, path):
        """Extract metadata without full parsing (optional)."""
        return {
            "source_file": path.name,
            "book_slug": path.stem.lower(),
        }
```

## API Reference

### Library

Main class for interacting with a biblirag database.

```python
class Library:
    def __init__(self, db_path: str | Path, create: bool = True):
        """
        Initialize or open a library.

        Args:
            db_path: Path to the SQLite database file
            create: If True, create the database if it doesn't exist
        """

    def search(
        self,
        query: str,
        limit: int = 10,
        corpus: str | list[str] | None = None,
        tags: list[str] | None = None,
        book: str | None = None,
        raw_query: bool = False,
    ) -> SearchResults:
        """
        Search the library.

        Args:
            query: Search query (words are OR'd by default)
            limit: Maximum number of results
            corpus: Filter by corpus name(s)
            tags: Filter by tag(s) - chunks must have ALL specified tags
            book: Filter by book slug
            raw_query: If True, pass query directly to FTS5 (advanced syntax)
        """

    def ingest(
        self,
        path: str | Path,
        corpus: str = "default",
        parser: BaseParser | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """
        Ingest a document into the library.

        Returns: {"chunks": N, "chars": N}
        """

    def list_books(self, corpus: str | None = None) -> list[dict]:
        """List all books, optionally filtered by corpus."""

    def list_corpora(self) -> list[dict]:
        """List all corpora with stats."""

    def get_stats(self) -> dict:
        """Get library statistics."""

    def delete_book(self, slug: str) -> bool:
        """Delete a book and all its chunks."""

    def close(self):
        """Close database connection."""
```

### Chunk

A chunk of content from a document.

```python
@dataclass
class Chunk:
    id: str                              # Unique identifier
    content: str                         # Text content
    book_title: str                      # Document title
    book_slug: str                       # URL-safe identifier

    # Location
    page_start: int                      # Starting page
    page_end: int                        # Ending page
    chapter_title: str | None            # Chapter/section title
    chapter_num: int | None              # Chapter number
    paragraph: int                       # Paragraph number within section

    # Content metadata
    content_chars: int                   # Character count
    content_hash: str | None             # Content hash for deduplication
    tags: list[str] | None               # Tags for filtering

    # Extended metadata (domain-specific)
    metadata: dict                       # Custom metadata (stored as JSON)

    # Properties
    @property
    def source(self) -> str:             # "Book > Chapter" format
    @property
    def page(self) -> str:               # "p.1" or "pp.1-2" format

    # Methods
    def to_dict(self) -> dict
    def to_json(self) -> str
```

### SearchResult

A single search result with score.

```python
@dataclass
class SearchResult:
    chunk: Chunk                         # The matched chunk
    score: float                         # BM25 relevance score
    rank: int                            # Result ranking (1-based)

    # Convenience properties (delegate to chunk)
    @property
    def content(self) -> str
    @property
    def source(self) -> str
    @property
    def page(self) -> str
    @property
    def book_title(self) -> str
    @property
    def chapter_title(self) -> str | None
    @property
    def tags(self) -> list[str] | None

    def to_dict(self) -> dict
```

### SearchResults

Collection of search results with export methods.

```python
@dataclass
class SearchResults:
    results: list[SearchResult]          # List of results
    query: str                           # Original query
    total_found: int                     # Total matches found

    # Iteration
    def __iter__(self)                   # Iterate over results
    def __len__(self)                    # Number of results
    def __getitem__(self, idx)           # Access by index

    # Export methods
    def to_dict(self) -> dict            # For JSON APIs
    def to_json(self) -> str             # JSON string
    def to_markdown(self) -> str         # Markdown format
    def to_prompt(self, max_chars=8000) -> str  # LLM context format
```

## Extended Metadata

biblirag supports domain-specific metadata through the `metadata` field:

```python
from biblirag import METADATA_EXAMPLES

# Example for French legal documents
chunk.metadata = {
    "legal_fr": {
        "numero_article": "39 decies A",
        "code": "cgi",
        "date_debut": "2024-01-01",
        "etat": "VIGUEUR",
    }
}

# Generate links to source
def lien_legifrance(article, code="cgi"):
    return f"https://legifrance.gouv.fr/search?query=article+{article}+{code}"
```

See `biblirag/schema.py` for the full schema and examples.

## Tag Management

Tags allow you to categorize and filter chunks.

### Python API

```python
lib = Library("library.db")

# Add tags to a specific chunk
lib.add_tags(chunk_id, ["fiscal", "important"])

# Remove tags from a chunk
lib.remove_tags(chunk_id, ["important"])

# Tag all chunks in a corpus or book
count = lib.tag_chunks(["legal", "2024"], corpus="cgi")
count = lib.tag_chunks(["reviewed"], book="tax-guide")

# List all tags with counts
tags = lib.list_tags()
# [{"tag": "fiscal", "count": 150}, {"tag": "legal", "count": 200}]

# List tags for a specific corpus
tags = lib.list_tags(corpus="cgi")

# Get chunks by tag
chunks = lib.get_chunks_by_tag("important")

# Search with tag filter
results = lib.search("amortissement", tags=["fiscal"])
```

### CLI

```bash
# List all tags
biblirag tags --db library.db

# List tags for a corpus
biblirag tags --corpus cgi

# Add tags to a specific chunk
biblirag tag "fiscal,important" --chunk chunk-id-here

# Tag all chunks in a corpus
biblirag tag "legal,2024" --corpus cgi

# Tag all chunks in a book
biblirag tag "reviewed" --book tax-guide
```

## Article Versioning

Track different versions of legal articles over time - essential for legal research to know which version of a law was applicable at a given date.

### Python API

```python
lib = Library("library.db")

# Add a version record
version_id = lib.add_article_version(
    article_ref="CGI-39-decies-A",      # Stable identifier
    chunk_id=chunk_id,                   # Link to chunk content
    version_num=1,
    date_debut="2020-01-01",
    date_fin="2023-12-31",               # None if current
    etat="MODIFIE",                      # VIGUEUR, MODIFIE, ABROGE
    texte_modificateur="Loi 2019-1479",  # Modifying law
)

# Get version history for an article
history = lib.get_article_history("CGI-39-decies-A")
# Returns list of versions ordered by version_num

# Get the version applicable at a specific date
version = lib.get_article_at_date("CGI-39-decies-A", "2022-06-15")

# List all versioned articles
articles = lib.list_versioned_articles(corpus="cgi")
# [{"article_ref": "CGI-39", "version_count": 3}, ...]

# Compare two versions
diff = lib.compare_versions("CGI-39-decies-A", 1, 2)
# {"v1": {...}, "v2": {...}, "chars_diff": 150, "content_changed": True}
```

### CLI

```bash
# List all versioned articles
biblirag versions --db library.db

# Show version history for an article
biblirag versions --article CGI-39-decies-A

# Get article at a specific date
biblirag version-at CGI-39-decies-A 2022-06-15

# Compare two versions
biblirag compare-versions CGI-39-decies-A 1 2
```

### Automatic Extraction

When ingesting Légifrance XML files, the parser automatically extracts version metadata:

```python
lib.ingest("cgi.xml", corpus="cgi", metadata={"code": "cgi"})

# Each chunk will have metadata including:
# - article_ref: "CGI-39" (stable identifier for versioning)
# - date_debut, date_fin: validity period
# - etat: VIGUEUR, MODIFIE, ABROGE, PERIME
# - texte_modificateur: modifying law reference
```

## Semantic Search (Embeddings)

biblirag supports semantic search using sentence embeddings, allowing you to find conceptually similar content even without exact keyword matches.

### Installation

```bash
# Install with embedding support
pip install sentence-transformers
```

### Generating Embeddings

```python
lib = Library("library.db")

# Generate embeddings for all chunks (one-time, idempotent)
stats = lib.generate_embeddings(show_progress=True)
print(f"Embedded: {stats['embedded']} chunks")

# Generate for a specific corpus only
lib.generate_embeddings(corpus="cgi")

# Force regeneration (if model changed)
lib.generate_embeddings(force=True)

# Check embedding coverage
stats = lib.get_embedding_stats()
# {'total_chunks': 3250, 'embedded': 3250, 'coverage': '100.0%', 'models': 'paraphrase-multilingual-MiniLM-L12-v2'}
```

### Semantic Search

```python
# Pure semantic search - finds conceptually similar content
results = lib.semantic_search("tax deductions for investments", limit=10)

# Hybrid search - combines FTS5 keywords + semantic similarity
# Best of both worlds: exact matches + semantic understanding
results = lib.hybrid_search("amortissement fiscal", limit=10)

# Filter by corpus
results = lib.semantic_search("depreciation rules", corpus="cgi")
```

### CLI

```bash
# Generate embeddings
biblirag embed --db library.db
biblirag embed --corpus cgi --batch-size 64

# Check embedding stats
biblirag embed-stats --db library.db

# Semantic search
biblirag semantic-search "tax deductions" --db library.db
biblirag semantic-search "depreciation" --limit 5 --corpus cgi

# Hybrid search (FTS5 + semantic)
biblirag semantic-search "amortissement" --hybrid
```

### Model

The default model is `paraphrase-multilingual-MiniLM-L12-v2`:
- **Multilingual**: French, English, German, Spanish, etc.
- **Fast**: 384-dimensional embeddings
- **Local**: Runs entirely on your machine
- **Free**: Open source, no API costs

Embeddings are stored in the `chunk_embeddings` table as BLOB (float32 arrays).

## Architecture

```
biblirag/
├── core/
│   ├── library.py      # Main Library class
│   ├── models.py       # Chunk, SearchResult, SearchResults
│   └── embeddings.py   # Embedding utilities
├── parsers/
│   ├── base.py         # BaseParser, ParserRegistry
│   ├── markdown.py     # Markdown parser
│   ├── xml_legifrance.py  # Legifrance XML parser
│   └── html_bofip.py   # BOFiP HTML parser
├── cli.py              # Command-line interface
└── schema.py           # Field documentation
```

## Database

biblirag uses SQLite with FTS5 for full-text search. The database supports:

- **WAL mode** for concurrent read access
- **Porter stemming** for better search matching
- **Automatic triggers** to keep the FTS index in sync

```python
# Default location: db/library.db
lib = Library("db/library.db")

# Database is automatically created with proper schema
```

## License

MIT
