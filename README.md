<!-- mcp-name: io.github.roomi-fields/rtfm -->
<div align="center">

# RTFM

***Retrieve The Forgotten Memory***

### The open retrieval layer your AI agent was missing

Index everything in your project — code, docs, PDFs, legal texts, research, data — and your agent finds the right context instantly. No hallucinations. No cloud. No API costs.

**`Free · Local · Open Source · MIT`**

<br>

![RTFM vs vanilla Claude Code — same task, same model, who pays the bill?](docs/demo/rtfm-split.png)

<br>

[![PyPI version](https://badge.fury.io/py/rtfm-ai.svg)](https://pypi.org/project/rtfm-ai/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/) [![MCP](https://img.shields.io/badge/MCP-2026-green.svg)](https://modelcontextprotocol.io/) [![Claude Code](https://img.shields.io/badge/Claude_Code-MCP-8A2BE2)](https://claude.ai/claude-code) [![GitHub stars](https://img.shields.io/github/stars/roomi-fields/rtfm?style=social)](https://github.com/roomi-fields/rtfm)

</div>

---

<!-- ─────────── TIER 1 — Pain & promise ─────────── -->

## The problem

Your AI agent is flying blind.

It greps through thousands of files, misses the doc that answers the question, invents modules that don't exist, forgets what you decided last session. The bigger the project, the worse it gets. You've added a smarter model. It didn't help. Because the bottleneck isn't intelligence — it's **retrieval**.

Code indexers (Augment, Sourcegraph, Cursor) only see code. But your project isn't just code. It's specs, PRs, architecture decisions, research papers, PDFs, regulations, vault notes — the context your agent needs to stop guessing.

### Why I built this

I was writing a French tax article (~50 pages of regulatory text, cross-references between code articles, case law, administrative doctrine). Claude Code kept grep-ing the same directories in loops, running out of context, and producing confidently wrong citations. I'd added more memory, better prompts, a smarter model. None of it worked, because the agent wasn't reasoning badly — it just couldn't *find* the right paragraph in a 2,000-file legal corpus. So I stopped trying to make the model smarter and built the layer it was missing. That's RTFM.

## The solution

**RTFM indexes everything.** One command, one SQLite file, one retrieval layer your agent queries before grepping.

```bash
pip install rtfm-ai && cd your-project && rtfm init
```

30 seconds. Claude Code now searches your indexed knowledge base — code *and* docs *and* PDFs *and* whatever else you drop in — with full-text, semantic, or hybrid search. The agent sees 300 tokens of metadata first, then expands only what's relevant. Progressive disclosure instead of context dumps.

> **Free. Runs locally. No API keys. No cloud. Your data stays yours.**

### What it looks like

```text
$ rtfm search "authentication flow" --limit 3
[1] src/auth/handlers.py > authenticate_user (p.2)    score 9.12
    src/auth/handlers.py:147  42 lines
[2] docs/architecture/auth.md > SSO flow (p.1)        score 7.84
    docs/architecture/auth.md:1   23 lines
[3] docs/ADR/0007-oauth.md > Decision (p.1)           score 6.90
    docs/ADR/0007-oauth.md:12  18 lines
```

Three results, ~300 tokens. The agent decides what to read next with `rtfm_expand(source, target_section)` — not a context dump, a conversation.

---

## Quick start

### Recommended — Claude Code plugin

In Claude Code (CLI or Desktop **Code** tab) :

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

RTFM is distributed via the [`roomi-fields/claude-plugins`](https://github.com/roomi-fields/claude-plugins) marketplace, which also ships [`notebooklm-mcp`](https://github.com/roomi-fields/notebooklm-mcp) for citation-backed Q&A. To grab both at once:

```
/plugin install notebooklm@roomi-fields
```

That's it. The plugin auto-initializes each project on first use:
- Creates `.rtfm/library.db` (one SQLite file)
- Injects search instructions into `CLAUDE.md`
- Pre-grants permission for the MCP tools (no prompt every search)
- Indexes the project on the first prompt, re-indexes incrementally on every prompt

**No `pip install` required.** Pure Python, runs on Linux / macOS / Windows / WSL with Python 3.10+ already on PATH. The plugin bundles its own MCP server (no `mcp` SDK dep) and resolves `python3` / `python` / `py` automatically.

Then say to Claude: *"Find the authentication flow"* — it uses `rtfm_search` instead of grepping.

### Optional extras (semantic search, PDF parsing)

The core plugin is dependency-free. Heavier optional extras (embedding model, PDF parsers) install on demand into an isolated venv inside the plugin's data directory — no pollution of your system Python, no PEP 668 conflicts:

```
/rtfm:install-embeddings    # FastEmbed ONNX (~85 MB), semantic + hybrid search
/rtfm:install-pdf           # pdftext only (~50 MB), fast text extraction
/rtfm:install-pdf-full      # + marker-pdf + CPU-only torch (~1.5 GB), complex layouts
```

The `pdf-full` install uses PyTorch's CPU-only index (no CUDA, no GPU needed) to stay around 1.5 GB instead of 5 GB.

Restart Claude Code after install for the extras to be picked up.

### Manual install (Cursor, Codex, Claude Desktop chat, other MCP clients)

For clients without Claude Code's plugin system :

```bash
pip install rtfm-ai
cd /path/to/your-project
rtfm init
```

Then point your MCP client at `rtfm-serve` (the entry exposed by the pip package). Optional extras via `pip install rtfm-ai[embeddings,pdf]`.

---

<!-- ─────────── TIER 2 — Positioning & buzz ─────────── -->

## How it compares

|                       | **RTFM**              | Augment CE    | Sourcegraph       | Code-Index-MCP | MemPalace                |
| --------------------- | --------------------- | ------------- | ----------------- | -------------- | ------------------------ |
| Code indexing         | ✅ (AST-aware)        | ✅            | ✅                | ✅             | Shallow (char-chunk)     |
| Docs, specs, markdown | ✅ (header-parsed)    | Partial       | ❌                | Limited        | Verbatim chunks          |
| Legal / regulatory    | ✅ (XML, BOFiP)       | ❌            | ❌                | ❌             | ❌                       |
| Research (LaTeX, PDF) | ✅                    | ❌            | ❌                | ❌             | ❌                       |
| Custom parsers        | ✅ (~50 lines)        | ❌            | ❌                | ❌             | ❌                       |
| Knowledge graph       | ✅ (file/code links)  | ❌            | Partial           | ❌             | Entity graph (people)    |
| File version history  | ✅ (unlimited)        | ❌            | ❌                | ❌             | ❌ (purge-and-replace)   |
| MCP native            | ✅                    | ✅            | ✅                | ✅             | ✅                       |
| Runs locally          | ✅                    | Cloud         | Enterprise        | ✅             | ✅                       |
| Open source           | MIT                   | ❌            | Partial           | ✅             | MIT                      |
| Price                 | **Free**              | $20-200/mo    | $$$/mo            | Free           | Free                     |

**RTFM is the only open-source option that indexes multi-domain content with structural parsing, a code-level knowledge graph, and unlimited per-file history.** That's the niche.

Different from MemPalace specifically: MemPalace is an entity-level memory for conversations (who/project/decision triples in SQLite, plus verbatim chunks in ChromaDB). RTFM is a retrieval layer for *artefacts* — parsed by format, linked at the file level, versioned over time. The two are stackable, not competing.

> For a deeper breakdown of the design choices behind any RAG (chunking, retrieval, augmentation, integration, freshness, storage), see **[RAG Fundamentals — the 6 axes →](docs/rag-fundamentals.md)**

---

## Memory that survives sessions

Between sessions, most agents forget. RTFM indexes Claude Code's own memory files across every project on your machine, with full version history.

```bash
rtfm memory                    # Manual snapshot
rtfm memory --install-hook     # Auto-snapshot on every SessionEnd
```

- **Cross-project index** — one DB at `~/.rtfm/memory.db` sees every `~/.claude/projects/*/memory/` directory on your machine. Ask `rtfm_search("OAuth auth decisions")` and get hits from all 18 of your projects.
- **Unlimited version history** — every change to a memory file is snapshotted (no prune). `rtfm_history <slug>` returns the full evolution.
- **Auto-snapshot on `SessionEnd`** — one command installs a global Claude Code hook. Every session you close captures a new snapshot.
- **Curated, not verbatim** — RTFM indexes the notes the agent already curated itself during the session (small, structured, signal-dense). Different philosophy from MemPalace, which indexes the full conversation transcripts in ChromaDB (large, noisy, needs aggressive semantic filtering).

---

## Obsidian vault mode

RTFM is the retrieval layer for the [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern. Karpathy himself wrote: *"at small scale the index file is enough, but as the wiki grows you want proper search."* This is proper search.

```bash
cd /path/to/your-obsidian-vault
rtfm vault
```

- Detects `.obsidian/`, proposes a folder → corpus mapping
- Resolves `[[wikilinks]]` following Obsidian rules → stored as graph edges
- Generates `_rtfm/` with Obsidian-native navigation (index, graph with Mermaid, hubs, orphans, Dataview frontmatter)
- Tested on a 1,700-note research vault

```
_rtfm/
├── index.md      # Hub: corpus list, top connected documents
├── graph.md      # Hub documents, orphans, broken links, Mermaid
├── recent.md     # Recently modified files
└── corpus/       # Per-corpus indexes
```

The LLM still writes your wiki. RTFM handles the retrieval that `index.md` can't scale to.

**[Full Obsidian guide →](docs/obsidian-vault-guide.md)**

---

## NotebookLM integration

RTFM pairs naturally with [`notebooklm-mcp`](https://github.com/roomi-fields/notebooklm-mcp). NotebookLM caps you at 50 queries/day per notebook; RTFM removes that ceiling by indexing answers locally — ask once, retrieve forever, offline, in milliseconds.

`notebooklm-mcp`'s `/batch-to-vault` endpoint writes citation-backed Q&A as `{slug}.md` (markdown with frontmatter) plus `{slug}.json` (structured `nblm-answer-v1` sidecar). Both are guaranteed to coexist. Two integration paths, both ship today:

- **Path A — Markdown (zero config)**: drop the vault into RTFM and `rtfm sync`. The default markdown parser slices each answer into question / answer / per-citation chunks automatically. No mapping, no schema, no code.
- **Path B — JSON sidecar (typed metadata)**: drop a [`nblm-answer.yaml` mapping](docs/notebooklm-integration.md#path-b--json-sidecar-typed-metadata--edges) into `.rtfm/mappings/`. Each `.json` answer file produces typed chunks with `notebook_id`, `source_name`, `citation_marker` queryable via SQL, plus `cites` edge candidates between answers and sources.

Use Path A unless you specifically need to filter or graph by structured citation fields.

**[Full NotebookLM recipe →](docs/notebooklm-integration.md)**

---

## What I measured

I ran two kinds of benchmarks. The honest picture is nuanced — retrieval helps most on tasks that are actually solvable and where the agent is spending time *looking for things*.

### Document-heavy task: French tax article generation (B10)

Writing a ~50-page regulated article from a corpus of legal code, case law, and administrative doctrine. Same agent (Claude Code + Sonnet 4), same prompt, eight configurations tested.

| Configuration               | Duration  | Cost    | Tokens |
| --------------------------- | --------- | ------- | ------ |
| Baseline (no RTFM)          | 8m 16s    | $22.61  | 8.21 M |
| **With RTFM (FTS default)** | **6m 58s**| **$11.14** | **3.22 M** |

**Δ : −51 % cost, −61 % tokens, −16 % duration — with better factual accuracy.**
This is the use case RTFM was built for: navigating a large multi-domain corpus where grep misses the right paragraph.

### Code task: [FeatureBench](https://huggingface.co/datasets/LiberCoders/FeatureBench) (LiberCoders dataset)

11 tasks, 3 repos of varying size, 4 conditions (A = standard prompt with file paths; B = discovery, no paths; C = RTFM FTS; D = RTFM hybrid), 3 runs each.

| Repo     | Size        | Where RTFM helps                                     |
| -------- | ----------- | ---------------------------------------------------- |
| metaflow | 620 files   | Everyone resolves — RTFM adds no measurable gain     |
| astropy  | 1,119 files | All conditions 25–30 % F2P pass; none fully resolve  |
| mlflow   | 8,255 files | All conditions 0–5 % F2P pass; none fully resolve    |

On a single smaller-scope run (`test_stub_generator` on metaflow), RTFM cut agent time by **−37 %** vs the no-paths baseline. On the larger repos, the tasks themselves were too hard for Sonnet 4 to resolve inside a 20-minute timeout regardless of retrieval.

### The honest caveats

- Single model (Sonnet 4), single agent (Claude Code). Not statistically bullet-proof.
- On small repos (< 1k files), `grep` is enough and RTFM adds overhead.
- FeatureBench measures *code modification*, not *information retrieval*. It's the wrong benchmark for a retrieval tool — I'm running against it because it's what exists. Better-suited benchmarks (RepoQA, SWE-QA, LocAgent) are on the roadmap.

### What this says

RTFM measurably wins when the bottleneck is **"find the right paragraph in a 2,000-file corpus"**. It doesn't magically make unsolvable tasks solvable. The model still has to do the work — RTFM just makes sure it has the right context to do it with.

---

## Who it's for

RTFM works anywhere your project isn't just code:

- **LegalTech** — Code + tax law + regulatory specs. Ships with Legifrance XML and BOFiP parsers.
- **Research** — Code + LaTeX papers + datasets. Ships with LaTeX and PDF parsers.
- **FinTech** — Code + financial regulations + XBRL reports. Write an XBRL parser in 50 lines.
- **HealthTech** — Code + medical records (HL7/FHIR) + clinical guidelines.
- **Solo devs with big projects** — Stop watching your agent grep the same 8,000 files every session.
- **Obsidian / PKM users** — Make your vault actually searchable by your AI.
- **Any regulated industry** — If your project mixes code with domain documents, RTFM is for you.

---

<!-- ─────────── TIER 3 — Technical depth ─────────── -->

## Full feature list

### Search & retrieval
- **FTS5 full-text search** — instant, zero-config, works out of the box
- **Semantic search** — optional embeddings (FastEmbed/ONNX, no GPU needed)
- **Hybrid mode** — combine both, rank by relevance score
- **Metadata-first** — results return file paths + scores (~300 tokens), not content dumps
- **Progressive disclosure** — agent expands only the chunks it actually needs
- **Knowledge graph** — wikilinks + Python imports resolved as graph edges, hub detection, centrality ranking

### Multi-format indexing
- **22 parsers built-in** — Markdown, Python (AST), LaTeX, YAML, JSON, TOML, Shell, PDF, XML, HTML, SQLite, Jupyter, CSV/TSV, XLSX, EPUB, MOBI/AZW, FB2, DJVU, DOCX, ODT, RTF, plain text
- **Extensible** — add any format in ~50 lines of Python
- **Auto-sync hooks** — index stays fresh every prompt, zero manual work
- **Incremental** — only re-indexes what changed

### Integration
- **Native Claude Code plugin** — `/plugin install rtfm@roomi-fields/rtfm`, auto-init per project
- **Pure-Python MCP server** — 0 external deps, no `mcp` SDK / `pydantic` / native binaries
- **Cross-platform** — Linux, macOS, Windows, WSL (only requires Python ≥ 3.10 on PATH)
- **13 MCP tools** — search, context, expand, graph, history, sync, tags, ...
- **Manual install fallback** — `pip install rtfm-ai` for Cursor, Codex, Claude Desktop chat, any other MCP client
- **CLI + Python API** — scriptable for pipelines
- **Non-invasive** — doesn't touch your code, doesn't replace your editor

---

## The parser architecture

Need to index a format nobody supports? Write a parser in ~50 lines.

```python
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.core.models import Chunk
import json
from uuid import uuid4

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

Drop it in your project, restart Claude Code, your medical AI agent now understands FHIR records.

### Two levels of JSON integration

For JSON-based formats specifically, RTFM offers a second extensibility path that doesn't need any Python:

| Level | What you do | What you get |
| --- | --- | --- |
| **1. Generic** | Nothing. Just index the file. | Each top-level key becomes a chunk. Full-text search works on values. |
| **2. Mapped** | Drop a YAML mapping in `.rtfm/mappings/` (~30 lines). | Typed chunks with declared metadata, custom titles, foreach extraction over arrays, edge candidates. The producing project (NotebookLM, Linear, Notion, OpenAPI…) ships the mapping; RTFM stays generic. |

See [JSON schema mappings](docs/json-mappings.md) for the full reference, and [RTFM × NotebookLM](docs/notebooklm-integration.md) for a concrete recipe.

### Built-in parsers

| Parser         | Extensions                      | Strategy                                              |
| -------------- | ------------------------------- | ----------------------------------------------------- |
| Markdown       | `.md`                           | Split by headers, YAML frontmatter extraction         |
| Python         | `.py`                           | AST-based: each class/function = 1 chunk              |
| LaTeX          | `.tex`                          | Split by `\section`, `\chapter`, etc.                 |
| YAML           | `.yaml`, `.yml`                 | Split by top-level keys                               |
| JSON           | `.json`                         | Split by top-level keys or array elements             |
| TOML           | `.toml`                         | Top-level tables; emits `depends_on` edges (PEP 621, Cargo, Poetry) |
| Shell          | `.sh`, `.bash`, `.zsh`          | Function-aware chunking                               |
| PDF            | `.pdf`                          | Page-based (`pip install rtfm-ai[pdf]`)               |
| Legifrance XML | `.xml`                          | French legal codes (LEGI format)                      |
| BOFiP HTML     | `.html`                         | French tax doctrine                                   |
| SQLite         | `.sqlite`, `.sqlite3`, `.db`    | Schema + sample rows per table; FK edges (read-only)  |
| Jupyter        | `.ipynb`                        | Group cells by markdown heading; outputs dropped      |
| CSV / TSV      | `.csv`, `.tsv`                  | Header + sample rows + lightweight type inference     |
| XLSX           | `.xlsx`                         | Per-sheet schema + sample (`pip install rtfm-ai[xlsx]`) |
| Plain text     | `.js`, `.ts`, `.rs`, `.go`, ... | Line-boundary chunks (~500 chars)                     |

---

## MCP tools

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
| `rtfm_graph`      | Show dependency graph for a source (imports, links)   |
| `rtfm_history`    | File version history and memory snapshots             |

---

## CLI reference

```bash
# Search
rtfm search "authentication flow"
rtfm search "article 39" --corpus cgi --limit 5

# Sync
rtfm sync                              # All registered sources
rtfm sync /path/to/docs --corpus docs  # Specific directory
rtfm sync . --force                    # Force re-index

# Source management
rtfm add /path/to/docs --corpus docs --extensions md,pdf
rtfm sources

# Obsidian vault
rtfm vault                             # Initialize for cwd vault
rtfm vault /path/to/vault              # Specific vault
rtfm vault --regenerate                # Regenerate _rtfm/ files

# Cross-project Claude memory
rtfm memory                            # Manual snapshot
rtfm memory --install-hook             # Auto-snapshot on SessionEnd

# Status & info
rtfm status
rtfm books
rtfm tags
rtfm history path/to/file.md           # Memory version history

# Semantic search
rtfm embed                             # Generate embeddings (one-time)
rtfm semantic-search "tax deductions" --hybrid

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

## Where RTFM fits

RTFM isn't a task manager. It's not an agent framework. It's the knowledge layer your agent needs underneath whatever you're already using.

```
┌─────────────────────────────────┐
│  GSD / Taskmaster / Claude Flow │  ← Orchestration
├─────────────────────────────────┤
│              RTFM               │  ← Knowledge (you are here)
├─────────────────────────────────┤
│          Claude Code            │  ← Execution
└─────────────────────────────────┘
```

Without RTFM, your orchestrator drives an agent that hallucinates. With RTFM, the agent knows what it's building on.

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

**Code indexers see your code. RTFM sees everything.**

[⭐ Star on GitHub](https://github.com/roomi-fields/rtfm) if RTFM saves your agent from hallucinating.

Curious how it works under the hood? See the [Architecture](docs/architecture.md) — SQLite + FTS5, the parser registry, and the priority-queue worker (ingest → embed → OCR).

</div>
