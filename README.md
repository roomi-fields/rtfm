# RTFM — Read The Fucking Manual

> Because your AI doesn't read the docs either.

<!-- TODO: [GIF DEMO — 15 seconds showing rtfm discover + rtfm context on a real project] -->

## The Problem

You have a large project. Code, docs, specs, legal texts, research papers, data.
Claude Code sees none of it — it greps randomly, loses context every session, and hallucinates modules that don't exist.

**Without RTFM:**
- **Drift** — Agent hallucinates modules, rewrites existing code, ignores specs it never read
- **Time waste** — 10 min/session re-explaining architecture and pointing to files
- **Token burn** — Random grepping through 2GB = your API budget on fire

## The Fix

RTFM indexes your entire project — every file type, every domain — and serves Claude exactly what it needs, when it needs it.

One command:

```bash
pip install -e ".[mcp]" && rtfm init
```

Ask "how does auth work?" and RTFM pulls the relevant code, the architecture doc, AND the security spec. Cross-domain. Milliseconds.

| Metric              | Without RTFM | With RTFM | Improvement |
|---------------------|--------------|-----------|-------------|
| Tokens per task     | ~45K         | ~8K       | -82%        |
| Context setup time  | ~10 min      | 0 sec     | -100%       |
| Hallucination rate  | ~35%         | ~5%       | -86%        |
| Cross-domain answers| Never        | Always    |             |

*Benchmarks from internal testing on a 4GB multi-domain project. Your mileage may vary.*

## "How is this different from GSD / Taskmaster / Claude Flow?"

They plan work. We provide knowledge. **They're complementary.**

| Tool         | What it does                          | Analogy     |
|-------------|----------------------------------------|-------------|
| GSD          | Orchestrates phases & task execution  | The GPS     |
| Taskmaster   | Breaks down & tracks tasks            | The foreman |
| Claude Flow  | Manages agent workflows               | The manager |
| **RTFM**     | **Indexes & serves project knowledge**| **The map** |

**Without RTFM**, your workflow tool orchestrates an agent that hallucinates.
**With RTFM**, your agent actually knows what it's building on.

```
                        +-----------------------------------------+
                        |   GSD / Taskmaster / Claude Flow        |  <-- Workflow: WHAT to do
                        +-----------------------------------------+
                        |              RTFM                       |  <-- Knowledge: WHAT the agent needs to know
                        +-----------------------------------------+
                        |           Claude Code                   |  <-- Execution: DO the work
                        +-----------------------------------------+
```

## Features

### Indexing & Search

Full-text search via SQLite FTS5 with porter stemming. Semantic search with sentence embeddings (multilingual MiniLM, 384 dims, runs locally). Hybrid mode combines both for best results — exact keyword matches plus conceptual similarity.

### Smart Parsers

10 parsers that chunk documents based on their structure, not arbitrary character counts:

| Parser | Extensions | Strategy |
|--------|------------|----------|
| Markdown | `.md` | Split by headers, YAML frontmatter extraction |
| Python | `.py` | AST-based: each class/function = 1 chunk |
| LaTeX | `.tex` | Split by `\section`, `\chapter`, etc. |
| YAML | `.yaml`, `.yml` | Split by top-level keys |
| JSON | `.json` | Split by top-level keys or array elements |
| Shell | `.sh`, `.bash`, `.zsh` | Function-aware chunking |
| PDF | `.pdf` | Page-based (requires `pip install rtfm[pdf]`) |
| Legifrance XML | `.xml` | French legal codes (LEGI format) |
| BOFiP HTML | `.html` | French tax doctrine |
| Plain text | `.js`, `.ts`, `.rs`, `.go`, ... | Line-boundary chunks (~500 chars) |

### Claude Code Integration

- **MCP server** exposing search/sync/context tools
- **`rtfm init`** auto-configures everything (`.mcp.json`, `CLAUDE.md`, auto-sync hook)
- **Progressive disclosure** via `rtfm_context` — the agent gets exactly what it needs

### Project Intelligence

- **`rtfm_discover`** — structural scan in ~1 second (files, languages, entry points)
- **`rtfm_context`** — surgical context retrieval (replaces blind grep)
- **Incremental sync** — only changed files are re-indexed
- **Auto-sync hook** on every prompt (transparent, <2s)

## Quick Start

### Install

```bash
pip install -e ".[mcp]"
```

### Initialize in your project

```bash
cd /path/to/your-project
rtfm init
```

This creates:
- `.rtfm/library.db` — indexed project knowledge
- `.mcp.json` — registers RTFM MCP server for Claude Code
- `CLAUDE.md` — injects "search RTFM first" instructions
- `.claude/hooks/rtfm_sync.py` — auto-sync hook (keeps index fresh every prompt)
- `.rtfm/` added to `.gitignore`

Use `--no-embeddings` to skip initial embedding generation (faster setup, FTS still works).

### Auto-Sync

By default, `rtfm init` installs a `UserPromptSubmit` hook:
- **On every prompt**: fast incremental FTS sync (typically <2s, throttled to 30s)
- **Embeddings**: generated in background by the MCP server (model stays cached in memory)

You never need to manually sync during a Claude Code session.

### MCP Tools

| Tool | Description |
|------|-------------|
| `rtfm_search` | Search the library (FTS, semantic, or hybrid) |
| `rtfm_context` | Get relevant context for a subject (use BEFORE Grep/Glob) |
| `rtfm_discover` | Scan project structure (files, languages, entry points) |
| `rtfm_stats` | Get library statistics |
| `rtfm_tags` | List all tags |
| `rtfm_books` | List indexed documents |
| `rtfm_sync` | Sync a directory (incremental) |
| `rtfm_ingest` | Ingest a single file |
| `rtfm_tag_chunks` | Add tags to specific chunks |
| `rtfm_remove` | Remove a file from the index |

### rtfm_context — Progressive Disclosure

The key tool that replaces blind grep searches:

```
rtfm_context("authentication flow")
-> Returns the 5 most relevant chunks about authentication

rtfm_context("src/auth.py")
-> If the file isn't indexed, indexes it on-the-fly, then searches

rtfm_context("rate limiting", scope="api")
-> Scoped search within the "api" corpus
```

### rtfm_discover — Project Map

Fast structural scan (~1 second) without indexing:

```
rtfm_discover(".")
-> Project: /path/to/project
   Files: 342 (2,100,000 bytes)
   Languages: Python, TypeScript
   File types:
     code: 280
     docs: 42
     config: 20
   Entry points:
     README.md
     pyproject.toml
```

## CLI Reference

### Search

```bash
# Basic search
rtfm search "depreciation" --db library.db

# Limit results
rtfm search "article 39" --limit 5

# Filter by corpus
rtfm search "tax deduction" --corpus cgi

# Filter by book
rtfm search "amortissement" --book code-general-impots

# Output formats
rtfm search "query" --format text      # Default: human-readable
rtfm search "query" --format json      # JSON output
rtfm search "query" --format markdown  # Markdown output
rtfm search "query" --format prompt    # LLM-ready format

# Control max chars for prompt format
rtfm search "query" --format prompt --max-chars 4000
```

### Semantic Search

```bash
# Generate embeddings (one-time)
rtfm embed --db library.db

# Semantic search
rtfm semantic-search "tax deductions" --db library.db

# Hybrid search (FTS5 + semantic)
rtfm semantic-search "amortissement" --hybrid
```

### Sync

```bash
# Incremental sync (only changed files)
rtfm sync . --db project.db --corpus my-project

# Force re-index all files (e.g. after adding new parsers)
rtfm sync . --db project.db --force

# Dry run
rtfm sync . --db project.db --dry-run

# Sync specific files
rtfm sync --files src/main.py README.md --db project.db

# Limit to specific extensions
rtfm sync . --extensions md,py,txt

# Skip embeddings
rtfm sync . --no-embeddings
```

### Other Commands

```bash
# Library status
rtfm status --db library.db

# List books
rtfm books --db library.db

# List corpora
rtfm corpora --db library.db

# List tags
rtfm tags --db library.db

# Field schema
rtfm schema
```

## Python API

For programmatic use or integration into your own tools.

### Library

```python
from rtfm import Library

# Create or open a library
lib = Library("my_library.db")

# Ingest documents
stats = lib.ingest("documents/article.md", corpus="docs")
print(f"Indexed {stats['chunks']} chunks ({stats['chars']} chars)")

# Search
results = lib.search("depreciation", limit=10)
results = lib.search("article 39", corpus="cgi")
results = lib.search("investment", tags=["fiscal"])

# Semantic search (requires embeddings)
lib.generate_embeddings(show_progress=True)
results = lib.semantic_search("tax deductions", limit=10)
results = lib.hybrid_search("amortissement fiscal", limit=10)

# Iterate results
for r in results:
    print(f"[{r.rank}] {r.source} ({r.page}) - Score: {r.score:.2f}")
    print(f"    {r.content[:200]}...")

# Export for LLM
prompt_context = results.to_prompt(max_chars=8000)

# Sync a directory
result = lib.sync(".", corpus="my-project")
print(result)  # SyncResult(+3 ~1 -0 =42)

lib.close()
```

### SearchResults Export

```python
results = lib.search("depreciation", limit=5)

results.to_dict()      # For JSON APIs
results.to_json()      # JSON string
results.to_markdown()  # Markdown format
results.to_prompt()    # LLM context format (XML-structured)
```

### Tag Management

```python
lib.add_tags(chunk_id, ["fiscal", "important"])
lib.remove_tags(chunk_id, ["important"])
lib.tag_chunks(["legal"], corpus="cgi")
lib.list_tags()
lib.search("query", tags=["fiscal"])
```

### Article Versioning

Track different versions of legal articles over time:

```python
lib.add_article_version(
    article_ref="CGI-39-decies-A",
    chunk_id=chunk_id,
    version_num=1,
    date_debut="2020-01-01",
    date_fin="2023-12-31",
    etat="MODIFIE",
)
lib.get_article_history("CGI-39-decies-A")
lib.get_article_at_date("CGI-39-decies-A", "2022-06-15")
```

### Custom Parsers

```python
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.core.models import Chunk

@ParserRegistry.register
class MyParser(BaseParser):
    extensions = ['.myext']
    name = "custom"

    def parse(self, path, metadata=None):
        content = path.read_text()
        yield Chunk(id="unique-id", content=content, ...)
```

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
│   ├── shell.py        # Shell (function-aware)
│   ├── pdf.py          # PDF (pdftext/marker)
│   ├── xml_legifrance.py  # Legifrance XML
│   ├── html_bofip.py   # BOFiP HTML
│   └── plaintext.py    # Catch-all plain text
├── plugin/
│   ├── claude_md.py    # CLAUDE.md instruction injection
│   ├── discover.py     # Fast project structure scan
│   ├── install.py      # Orchestration for `rtfm init`
│   └── hooks.py        # Claude Code auto-sync hook
├── cli.py              # CLI (search, sync, init, status, ...)
├── mcp.py              # MCP server (background embeddings)
└── schema.py           # Field documentation
```

## License

MIT
