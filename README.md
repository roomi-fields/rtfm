# RTFM — Read The Fucking Manual

> The open retrieval layer for AI agents.

<!-- TODO: [GIF DEMO — 15 seconds showing rtfm init + rtfm context] -->

## Why retrieval matters

Augment Code just proved it: same model, same benchmark (SWE-bench Pro), **6 points higher** — just because of better context retrieval. Not a better model. Better retrieval.

Your AI coding agent is blind. It greps randomly through your project, loses context every session, hallucinates modules that don't exist. The fix isn't a smarter model — it's smarter retrieval.

**The problem with existing retrieval:**

| | Augment | Sourcegraph | RTFM |
|---|---|---|---|
| Code indexing | Yes | Yes | Yes |
| Docs, specs, markdown | No | No | Yes |
| Legal / regulatory | No | No | Yes |
| Research (LaTeX, PDF) | No | No | Yes |
| Custom formats | No | No | Yes (50 lines) |
| Open source | No | Partial | Yes (MIT) |
| Self-hosted | No | Yes | Yes |
| MCP native | Coming soon | Coming soon | Yes |
| Install time | Enterprise onboarding | Enterprise onboarding | 30 seconds |
| Price | $$$/month | $$$/month | Free |

RTFM is the open alternative. Any format, any domain, extensible by anyone.

## What it does

RTFM indexes your entire project — code, docs, specs, legal texts, research papers, data — and serves your AI agent exactly the context it needs, when it needs it.

```bash
cd your-project
pip install rtfm-ai[mcp] && rtfm init
```

That's it. Claude Code now searches RTFM before grepping.

### Benchmarks

Tested on identical article generation tasks (Claude Opus 4, musicology PhD project):

| Metric | Without RTFM | With RTFM | Improvement |
|---|---|---|---|
| Cost per task | $22.61 | $11.14 | **-51%** |
| Duration | 8m16s | 6m58s | **-16%** |
| Tokens consumed | 8.21M | 3.22M | **-61%** |
| Glob/Grep calls for research | 8+ | 0 | **-100%** |
| Minor errors | 3 major | 3 minor (auto-corrected) | better quality |

*8 iterations (sessions A-H), same prompt, same model. [Detailed analysis](docs/benchmark-b10.md)*

## The plugin architecture

This is what makes RTFM different from everything else.

Need to index a format nobody supports? Write a parser:

```python
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.core.models import Chunk

@ParserRegistry.register
class FHIRParser(BaseParser):
    """Parse HL7 FHIR medical records."""
    extensions = ['.fhir.json']
    name = "fhir"

    def parse(self, path, metadata=None):
        data = json.loads(path.read_text())
        for entry in data.get('entry', []):
            resource = entry.get('resource', {})
            yield Chunk(
                id=resource.get('id', str(uuid4())),
                content=json.dumps(resource, indent=2),
                book_title=f"FHIR {resource.get('resourceType', 'Unknown')}",
                book_slug=resource.get('id', 'unknown'),
                page_start=1,
                page_end=1,
            )
```

50 lines. Now your medical AI agent understands FHIR records.

RTFM ships with 10 parsers out of the box:

| Parser | Extensions | Strategy |
|--------|------------|----------|
| Markdown | `.md` | Split by headers, YAML frontmatter extraction |
| Python | `.py` | AST-based: each class/function = 1 chunk |
| LaTeX | `.tex` | Split by `\section`, `\chapter`, etc. |
| YAML | `.yaml`, `.yml` | Split by top-level keys |
| JSON | `.json` | Split by top-level keys or array elements |
| Shell | `.sh`, `.bash`, `.zsh` | Function-aware chunking |
| PDF | `.pdf` | Page-based (requires `pip install rtfm-ai[pdf]`) |
| Legifrance XML | `.xml` | French legal codes (LEGI format) |
| BOFiP HTML | `.html` | French tax doctrine |
| Plain text | `.js`, `.ts`, `.rs`, `.go`, ... | Line-boundary chunks (~500 chars) |

But the real power is that **you can add any format**. Financial data (XBRL), CAD files (STEP), music scores (MusicXML), genomics (VCF), architecture docs (AsciiDoc) — whatever your project needs.

## Works with your workflow tools

RTFM isn't a task manager. It's a knowledge layer.

| Tool | Role | Analogy |
|------|------|---------|
| GSD / Taskmaster / Claude Flow | Orchestrate WHAT to do | The GPS |
| **RTFM** | **Provide WHAT the agent needs to know** | **The map** |
| Claude Code | Execute the work | The engine |

Without RTFM, your workflow tool orchestrates an agent that hallucinates.
With RTFM, your agent knows what it's building on.

Use both. They're complementary.

```
┌─────────────────────────────────┐
│  GSD / Taskmaster / Claude Flow │  <- Workflow
├─────────────────────────────────┤
│              RTFM               │  <- Knowledge
├─────────────────────────────────┤
│          Claude Code            │  <- Execution
└─────────────────────────────────┘
```

## Quick Start

### Install

```bash
pip install rtfm-ai[mcp]
```

Optional extras:

```bash
pip install rtfm-ai[embeddings]   # Semantic search (MiniLM + torch)
pip install rtfm-ai[pdf]          # PDF parsing (pdftext + marker)
pip install rtfm-ai[mcp,embeddings,pdf]  # Everything
```

### Initialize in your project

```bash
cd /path/to/your-project
rtfm init
```

This creates:
- `.rtfm/library.db` — indexed project knowledge
- `.rtfm/config.json` — registered sources for auto-sync
- `.mcp.json` — registers RTFM MCP server for Claude Code
- `CLAUDE.md` — injects "search RTFM first" instructions
- `.claude/hooks/rtfm_sync.py` — auto-sync hook (keeps index fresh every prompt)
- `.rtfm/` added to `.gitignore`

Use `--no-embeddings` to skip initial embedding generation (faster setup, FTS still works).

### Register additional sources

```bash
# Add external documentation directories
rtfm add /path/to/docs --corpus docs
rtfm add /path/to/specs --corpus specs --extensions md,pdf

# List registered sources
rtfm sources

# Sync all registered sources at once
rtfm sync
```

### Auto-Sync

By default, `rtfm init` installs two hooks:
- **UserPromptSubmit**: fast incremental FTS sync on every prompt (throttled to 30s)
- **Stop**: final sync when the session ends

You never need to manually sync during a Claude Code session.

### MCP Tools

| Tool | Description |
|------|-------------|
| `rtfm_search` | Search the library (FTS, semantic, or hybrid). Returns metadata with file paths. |
| `rtfm_context` | Get relevant context for a subject (metadata-only, use BEFORE Grep/Glob) |
| `rtfm_expand` | Expand a source — show all chunks with full content |
| `rtfm_discover` | Scan project structure (files, languages, entry points) |
| `rtfm_stats` | Get library statistics |
| `rtfm_tags` | List all tags |
| `rtfm_books` | List indexed documents |
| `rtfm_sync` | Sync a directory (incremental) |
| `rtfm_ingest` | Ingest a single file |
| `rtfm_tag_chunks` | Add tags to specific chunks |
| `rtfm_remove` | Remove a file from the index |

### Progressive disclosure

Search and context return **metadata only** — file paths, scores, chunk counts, language. No content. This keeps token consumption minimal (~300 tokens for 5 results).

The agent then uses `Read(file_path)` to get the actual content of relevant files. For sources without a file path (e.g. learned corpus), `rtfm_expand(slug)` retrieves full content.

```
rtfm_search("authentication")    -> metadata: file paths, scores, chunk counts
Read("/path/to/auth.py")         -> actual content (only what's needed)
```

### rtfm_context — Surgical Context

```
rtfm_context("authentication flow")
-> Returns the 5 most relevant sources about authentication (metadata only)

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
# Basic search (auto-detects .rtfm/ database)
rtfm search "depreciation"

# Explicit database
rtfm search "article 39" --db library.db

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

### Context & Expand (CLI)

```bash
# Get metadata-only context
rtfm context "authentication flow"

# Expand a source (show all chunks)
rtfm expand published--auth-module
```

### Semantic Search

```bash
# Generate embeddings (one-time)
rtfm embed

# Semantic search
rtfm semantic-search "tax deductions"

# Hybrid search (FTS5 + semantic)
rtfm semantic-search "amortissement" --hybrid
```

### Sync

```bash
# Sync all registered sources (from .rtfm/config.json)
rtfm sync

# Sync a specific directory
rtfm sync /path/to/docs --corpus my-project

# Force re-index all files
rtfm sync . --force

# Dry run
rtfm sync . --dry-run

# Sync specific files
rtfm sync --files src/main.py README.md

# Limit to specific extensions
rtfm sync . --extensions md,py,txt

# Skip embeddings
rtfm sync . --no-embeddings
```

### Source Management

```bash
# Register a source directory
rtfm add /path/to/docs --corpus docs --extensions md,txt

# List registered sources
rtfm sources
```

### Other Commands

```bash
# Start MCP server
rtfm serve

# Library status
rtfm status

# List books
rtfm books

# List corpora
rtfm corpora

# List tags
rtfm tags

# Monitor live activity (MCP + hook calls)
rtfm monitor

# Field schema
rtfm schema

# Ask a question (RAG with citations)
rtfm ask "What is the depreciation schedule?"
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
│   ├── claude_md.py    # CLAUDE.md instruction injection
│   ├── discover.py     # Fast project structure scan
│   ├── install.py      # Orchestration for `rtfm init`
│   └── hooks.py        # Claude Code auto-sync hook
├── config.py           # Auto-detect .rtfm/, config load/save
├── cli.py              # CLI (search, sync, init, add, sources, serve, ...)
├── mcp.py              # MCP server (background embeddings)
└── schema.py           # Field documentation
```

## Use cases

RTFM works anywhere your project isn't just code:

- **LegalTech / RegTech** — Code + tax law articles + regulatory specs. Ships with Legifrance XML and BOFiP parsers.
- **HealthTech** — Code + medical records (HL7/FHIR) + clinical guidelines. Write a FHIR parser in 50 lines.
- **Academic research** — Code + LaTeX papers + datasets + methodology docs. Ships with LaTeX and PDF parsers.
- **FinTech** — Code + financial regulations + XBRL reports. Write an XBRL parser.
- **Defense / Aerospace** — Code + technical specs + compliance docs. Fully self-hosted, no cloud dependency.
- **Any regulated industry** — If your project mixes code with domain-specific documents, RTFM is for you.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a parser is the easiest way to contribute — and the most impactful.

## License

MIT — use it, fork it, extend it, ship it.
