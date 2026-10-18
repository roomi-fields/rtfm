---
date: 2026-10-18
authors: [romain]
title: "A Zero-Infrastructure Alternative to claude-context: One SQLite File"
description: >-
  Looking for a claude-context alternative without an API key or Milvus? This compares the setups honestly and shows
  when one local SQLite file is enough, and when claude-context is the better tool.
slug: claude-context-alternative
---

# A Zero-Infrastructure Alternative to claude-context: One SQLite File

[claude-context](https://github.com/zilliztech/claude-context) is a solid MCP server for semantic code search, but
its default setup asks for an OpenAI API key and a Zilliz Cloud account, and its fully local setup means running
Milvus in Docker plus Ollama for embeddings. If you want project search for Claude Code without any of that, RTFM
is one `pip install` and one SQLite file, with embeddings optional and running on your CPU. It is not a better
semantic code search engine. It's a lighter one that also indexes everything that isn't code.

<!-- more -->

## What does claude-context need to run?

From its README and FAQ, as of this writing:

- **Node.js 20 or later.**
- **An embedding provider**: OpenAI by default, with VoyageAI, Gemini or Ollama as alternatives.
- **A vector database**: Milvus or Zilliz Cloud. The quick start uses a Zilliz Cloud account and token.
- **For a fully local deployment**, the FAQ points to running Milvus with Docker Compose and setting
  `EMBEDDING_PROVIDER=Ollama` with a local Ollama server.

So "claude-context without an API key" is possible, but it means operating two services: a Milvus instance in Docker
and an Ollama daemon with an embedding model pulled. Some people already run both and won't notice. For others,
on a laptop, inside WSL, or on a machine where Docker isn't an option, that's the reason they search for an
alternative.

## Why does claude-context use that stack?

Because it's built for semantic code search, and it does it properly:

- **Hybrid search**: BM25 keyword scoring plus dense vectors, in the vector database.
- **Syntax-aware chunking**: an AST-based splitter for many languages (TypeScript, JavaScript, Python, Java, C++,
  C#, Go, Rust, PHP, Ruby, Swift, Kotlin, Scala), with a character-based fallback.
- **Incremental re-indexing** using Merkle trees, so only changed files are re-embedded.
- **A real vector index** in Milvus, which keeps queries fast as the codebase grows.

That design pays off on large, multi-language codebases where most questions are conceptual ("where do we validate
webhook signatures?") and the code doesn't share words with the question.

## What does the RTFM setup look like?

```bash
pip install rtfm-ai
cd your-project
rtfm init
rtfm sync
```

That's the whole setup. `rtfm init` creates `.rtfm/library.db`, writes `.mcp.json` for Claude
Code and adds a short search section to `CLAUDE.md`; `rtfm sync` indexes the project. There is no server to run besides the MCP process the client
starts, no Docker, no account. Python 3.10 or later is the only requirement.

In Claude Code you can skip pip entirely:

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

The plugin indexes each project on first use and keeps the index fresh incrementally (files are tracked by hash, so
only changed files are re-parsed).

## Do I need embeddings at all?

Not to start. The default search is SQLite FTS5 with BM25 ranking: keyword search with stemming, from the same file.
Agents mostly search for named things (a class, a function, an error string, a config key), and keyword search
handles those well.

When you want semantic recall too, the embeddings are local and CPU-only:

```bash
pip install "rtfm-ai[embeddings]"   # FastEmbed + ONNX runtime, no PyTorch, no GPU
rtfm embed                          # default model ~85 MB, multilingual
```

Vectors are stored in the same SQLite file. The agent can then pass `search_type="semantic"` or `"hybrid"` to
`rtfm_search`. Hybrid takes the keyword matches and re-orders them by semantic similarity, falling back to pure
semantic search when no keyword matches.

## What does the agent get back?

`rtfm_search` returns locations, not content: one line per file, with line ranges and the section or symbol name.
The agent then calls `rtfm_expand` to read the part it chose. An illustrative result (invented project):

```text
rtfm_search("webhook signature validation", limit=3)

3 sources for "webhook signature validation":
/home/me/shop/src/payments/webhooks.py L58-104 (def verify_signature)
/home/me/shop/docs/integrations/stripe.md L20-61 (Verifying events)
/home/me/shop/docs/adr/0012-webhook-retries.md L3-40 (Decision)
```

Note the last two lines: RTFM indexes non-code files with format-aware parsers. Markdown is split by headings,
Python by class and function, LaTeX by section, and there are parsers for PDF, DOCX, ODT, EPUB, Jupyter notebooks,
CSV, XLSX, SQLite databases, YAML, JSON, TOML and Obsidian vaults (some need a small optional extra). If your
answers live in specs, ADRs, papers or spreadsheets as much as in code, that's where the difference shows.

It also records links between files (Python imports, Markdown links and wikilinks, LaTeX includes, TOML
dependencies), which `rtfm_graph` exposes.

## Side by side

| | claude-context | RTFM |
| --- | --- | --- |
| Runtime | Node.js 20+ | Python 3.10+ |
| Default setup | OpenAI key + Zilliz Cloud | none (`rtfm init`, `rtfm sync`) |
| Fully local setup | Milvus in Docker + Ollama | default; embeddings optional, on CPU |
| Storage | Milvus / Zilliz Cloud | one SQLite file |
| Default search | hybrid (BM25 + dense) | keyword (FTS5/BM25) |
| Semantic search | yes, vector index | optional, brute-force over stored vectors |
| Code chunking | AST for ~13 languages | AST for Python; line-based for JS/TS/Go/Rust/… |
| Non-code formats | Markdown | Markdown, PDF, office docs, notebooks, data… |

## Where is claude-context the better choice?

Being honest about this saves you an evening:

- **Semantic code search at scale.** On a large codebase where most questions are conceptual, claude-context's
  hybrid search over a real vector index is the stronger engine. RTFM's semantic search compares the query with
  every stored vector; that's fine for a project, not for millions of chunks.
- **Non-Python code structure.** claude-context splits TypeScript, Go, Rust, Java and others along syntax. RTFM only
  parses Python (and shell functions) structurally; other languages get line-based chunks, which are less precise.
- **You already run Milvus or Zilliz.** If the infrastructure exists, its main cost to you is gone.
- **Better embedding models.** Hosted models from OpenAI or Voyage generally beat a CPU-sized local model on hard
  semantic queries.

RTFM fits better when you don't want to run services, when your project is more than code, or when most queries
name the thing being looked for.

## Try it

```bash
pip install rtfm-ai          # or: pipx install rtfm-ai
cd your-project
rtfm init
rtfm sync
rtfm search "your query"
```

Add `pip install "rtfm-ai[embeddings]"` and `rtfm embed` for semantic and hybrid search. In Claude Code, use the
plugin (`/plugin install rtfm@roomi-fields` after adding the `roomi-fields/claude-plugins` marketplace). For Cursor,
Codex and other MCP clients, install with pip and point the client at `rtfm-serve`.

Further reading: [RTFM vs vector RAG](../../comparisons/vs-vector-rag.md), [parsers guide](../../parsers.md) and
[architecture](../../architecture.md).
