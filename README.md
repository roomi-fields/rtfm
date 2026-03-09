<div align="center">

# RTFM

***Retrieve The Forgotten Memory***

**The open retrieval layer for AI agents**

Index your entire project — code, docs, legal, research, data — and serve your AI agent exactly the context it needs.

<!-- Badges -->

[![PyPI version](https://badge.fury.io/py/rtfm-ai.svg)](https://pypi.org/project/rtfm-ai/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/) [![MCP](https://img.shields.io/badge/MCP-2025-green.svg)](https://modelcontextprotocol.io/) [![Claude Code](https://img.shields.io/badge/Claude_Code-MCP-8A2BE2)](https://claude.ai/claude-code) [![GitHub](https://img.shields.io/github/stars/roomi-fields/rtfm?style=social)](https://github.com/roomi-fields/rtfm)

<!-- End Badges -->

</div>

---

## Why?

Your AI agent is blind. It greps through thousands of files, loses context every session, hallucinates modules that don't exist. The fix isn't a smarter model — it's smarter retrieval.

Augment, Sourcegraph, and Cursor index code. **RTFM indexes everything.**

```bash
pip install rtfm-ai[mcp] && cd your-project && rtfm init
```

30 seconds. Claude Code now searches your indexed knowledge base before grepping.

---

## Features

### Search & Retrieval

- **FTS5 full-text search** — instant, zero-config, works out of the box
- **Semantic search** — optional embeddings (FastEmbed/ONNX, no GPU needed)
- **Metadata-first** — search returns file paths + scores (~300 tokens), not content dumps
- **Progressive disclosure** — the agent reads only what it needs via `Read(file_path)`

### Indexing

- **10 parsers built-in** — Markdown, Python (AST), LaTeX, YAML, JSON, Shell, PDF, XML, HTML, plain text
- **Extensible** — add any format in ~50 lines of Python
- **Incremental sync** — only re-indexes what changed
- **Auto-sync** — hooks keep the index fresh every prompt, zero manual work

### Integration

- **MCP server** — works with Claude Code, Cursor, Codex, any MCP client
- **CLI** — `rtfm search`, `rtfm sync`, `rtfm status`, ...
- **Python API** — `Library`, `SearchResults`, custom parsers
- **Non-invasive** — doesn't touch your code, doesn't replace your workflow tools

---

## Quick Start

### Install

```bash
pip install rtfm-ai[mcp]
```

### Initialize in your project

```bash
cd /path/to/your-project
rtfm init
```

This creates `.rtfm/library.db`, registers the MCP server, injects search instructions into `CLAUDE.md`, and installs auto-sync hooks. Done.

Then say to Claude Code: _"Search for authentication flow"_ — it uses `rtfm_search` instead of grepping.

### Optional extras

```bash
pip install rtfm-ai[embeddings]  # Semantic search (FastEmbed ONNX)
pip install rtfm-ai[pdf]         # PDF parsing (pdftext + marker)
pip install rtfm-ai[mcp,embeddings,pdf]  # Everything
```

---

## MCP Tools

| Tool              | What it does                                          |
| ----------------- | ----------------------------------------------------- |
| `rtfm_search`     | Search the index (FTS, semantic, or hybrid)           |
| `rtfm_context`    | Get relevant context for a subject (metadata-only)    |
| `rtfm_expand`     | Show all chunks of a source with full content         |
| `rtfm_discover`   | Fast project structure scan (~1s, no indexing needed) |
| `rtfm_books`      | List indexed documents                                |
| `rtfm_stats`      | Library statistics                                    |
| `rtfm_sync`       | Sync a directory (incremental)                        |
| `rtfm_ingest`     | Ingest a single file                                  |
| `rtfm_tags`       | List all tags                                         |
| `rtfm_tag_chunks` | Add tags to specific chunks                           |
| `rtfm_remove`     | Remove a file from the index                          |

---

## The Parser Architecture

This is what makes RTFM different. Need to index a format nobody supports?

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

### Built-in parsers

| Parser         | Extensions                      | Strategy                                      |
| -------------- | ------------------------------- | --------------------------------------------- |
| Markdown       | `.md`                           | Split by headers, YAML frontmatter extraction |
| Python         | `.py`                           | AST-based: each class/function = 1 chunk      |
| LaTeX          | `.tex`                          | Split by `\section`, `\chapter`, etc.         |
| YAML           | `.yaml`, `.yml`                 | Split by top-level keys                       |
| JSON           | `.json`                         | Split by top-level keys or array elements     |
| Shell          | `.sh`, `.bash`, `.zsh`          | Function-aware chunking                       |
| PDF            | `.pdf`                          | Page-based (`pip install rtfm-ai[pdf]`)       |
| Legifrance XML | `.xml`                          | French legal codes (LEGI format)              |
| BOFiP HTML     | `.html`                         | French tax doctrine                           |
| Plain text     | `.js`, `.ts`, `.rs`, `.go`, ... | Line-boundary chunks (~500 chars)             |

---

## How It Compares

|                       | RTFM              | Augment CE    | Sourcegraph       | Code-Index-MCP |
| --------------------- | ----------------- | ------------- | ----------------- | -------------- |
| Code indexing         | Yes               | Yes           | Yes               | Yes            |
| Docs, specs, markdown | Yes               | Partial       | No                | Limited        |
| Legal / regulatory    | Yes               | No            | No                | No             |
| Research (LaTeX, PDF) | Yes               | No            | No                | No             |
| Custom parsers        | Yes (50 lines)    | No            | No                | No             |
| MCP native            | Yes               | Yes           | Yes               | Yes            |
| Open source           | MIT               | No            | Partial           | Yes            |
| Dependencies          | SQLite (built-in) | Cloud service | Enterprise server | Varies         |
| Price                 | Free              | $20-200/mo    | $$$/mo            | Free           |

---

## Use Cases

RTFM works anywhere your project isn't just code:

- **LegalTech** — Code + tax law + regulatory specs. Ships with Legifrance XML and BOFiP parsers.
- **Research** — Code + LaTeX papers + datasets. Ships with LaTeX and PDF parsers.
- **FinTech** — Code + financial regulations + XBRL reports. Write an XBRL parser in 50 lines.
- **HealthTech** — Code + medical records (HL7/FHIR) + clinical guidelines.
- **Any regulated industry** — If your project mixes code with domain documents, RTFM is for you.

---

## CLI Reference

```bash
# Search (auto-detects .rtfm/ database)
rtfm search "authentication flow"
rtfm search "article 39" --corpus cgi --limit 5

# Sync
rtfm sync                              # All registered sources
rtfm sync /path/to/docs --corpus docs  # Specific directory
rtfm sync . --force                    # Force re-index

# Source management
rtfm add /path/to/docs --corpus docs --extensions md,pdf
rtfm sources

# Status & info
rtfm status
rtfm books
rtfm tags

# Semantic search (requires embeddings)
rtfm embed                                      # Generate embeddings (one-time)
rtfm semantic-search "tax deductions" --hybrid   # Hybrid FTS + semantic

# MCP server
rtfm serve
```

---

## Python API

```python
from rtfm import Library

lib = Library("my_library.db")

# Index
stats = lib.ingest("documents/article.md", corpus="docs")
result = lib.sync(".", corpus="my-project")  # SyncResult(+3 ~1 -0 =42)

# Search
results = lib.search("depreciation", limit=10, corpus="cgi")
results = lib.hybrid_search("amortissement fiscal", limit=10)

# Export for LLM
prompt_context = results.to_prompt(max_chars=8000)

lib.close()
```

---

## Works With Your Workflow Tools

RTFM isn't a task manager. It's a knowledge layer.

```
┌─────────────────────────────────┐
│  GSD / Taskmaster / Claude Flow │  <- Workflow
├─────────────────────────────────┤
│              RTFM               │  <- Knowledge
├─────────────────────────────────┤
│          Claude Code            │  <- Execution
└─────────────────────────────────┘
```

Without RTFM, your workflow tool orchestrates an agent that hallucinates. With RTFM, your agent knows what it's building on.

---

## Contributing

Adding a parser is the easiest way to contribute — and the most impactful. See [CONTRIBUTING.md](CONTRIBUTING.md).

Found a bug? Have an idea? [Open an issue](https://github.com/roomi-fields/rtfm/issues).

## License

MIT — use it, fork it, extend it, ship it.

## Author

**Romain Peyrichou** — [@roomi-fields](https://github.com/roomi-fields)

---

<div align="center">

Augment indexes your code. RTFM indexes everything.

[Star on GitHub](https://github.com/roomi-fields/rtfm) if this saves your agent from hallucinating!

</div>
