# Positioning — RTFM in the AI Tooling Landscape

## How RTFM came to exist

RTFM started as **biblirag** — a semantic-search layer I built for an AI tool doing French tax optimization. The French tax code is a minefield of cross-references between articles, administrative doctrine, and case law. Embeddings over that corpus worked fine, but the whole pipeline was glued to that one domain: specific parsers for Legifrance XML, specific ingestion scripts, specific ranking.

When I moved back to my computational musicology research, I needed the same retrieval idea but for a completely different shape of project: symbolic music scripts, Python analysis code, dozens of LaTeX papers, an Obsidian vault years deep, a handful of PDFs. So I rewrote biblirag into RTFM — format-agnostic parsers, one SQLite file per project, incremental sync.

Today the same plugin runs on both workloads. The tax AI points at the regulatory corpus; the research agent points at the lab folder. Same MCP server, same tools, different data.

## The Problem RTFM addresses

AI coding agents are blind. They grep through thousands of files, lose context every session, hallucinate modules that don't exist. The bottleneck isn't reasoning — it's **localization**: finding the right files before writing code or drafting a section.

Measured gains on a document-heavy task (French tax article generation, ~50 pages of sourced regulatory text):

- Token cost: **−51%** vs baseline
- Turn duration: **−16%**
- Output quality improves (fewer fabricated article numbers, tighter citations)

The gain is proportional to corpus size. Small repos don't need retrieval. Large corpora (code + docs + PDFs, research archives, regulatory texts) can't work without it.

Benchmarks are being formalized for an upcoming paper.

## The landscape

### Code-only indexers

**Augment Context Engine**, **Sourcegraph**, **Code-Index-MCP** all index code. They don't index LaTeX, PDFs, legal XML, YAML configs, research notes, or anything beyond source files. If your project mixes code with non-code (regulated industries, research, ops, legal tech), they don't help.

### Karpathy's LLM Wiki pattern

Andrej Karpathy proposed a 3-layer wiki (raw, wiki, schema) maintained by an agent in Obsidian. Projects like **Claudesidian** (2.1k stars), **claude-obsidian**, **obsidian-second-brain** implement that idea.

The ceiling: navigation leans on a flat `index.md` that the agent maintains. Fine for ~100 notes. Breaks at a few thousand because the index itself no longer fits in context.

RTFM lifts that ceiling by moving the index into SQLite FTS5 and the graph into an `edges` table, while keeping the vault itself human-readable in Obsidian.

### Where RTFM sits

```
                    Code-only          Multi-domain
                    ┌─────────────────┬──────────────────┐
  Enterprise ($$$)  │ Sourcegraph     │                  │
                    │ Augment CE      │                  │
                    ├─────────────────┼──────────────────┤
  Open source       │ Code-Index-MCP  │     RTFM         │
                    └─────────────────┴──────────────────┘
```

To my knowledge, RTFM is the only open-source, multi-domain retrieval layer that combines:
- 15 built-in format parsers (code, docs, tabular, notebooks, databases), extensible in ~50 lines each
- FTS5 out of the box, optional local embeddings (FastEmbed/ONNX), hybrid mode
- Graph-based ranking from wikilinks, Python imports, LaTeX cites, legal cross-refs
- Progressive disclosure — metadata first (~300 tokens for 5 results), content on demand
- Obsidian vault mode with auto-generated navigation files (index, graph, hubs, orphans)
- MCP native — Claude Code, Cursor, Codex, any MCP client

## What makes RTFM different in practice

### vs hosted RAG pipelines

Most RAG stacks need: a vector database, embedding service, pipeline glue, per-query tokenization, opaque vector storage. RTFM needs: one SQLite file. Embeddings are optional and local (FastEmbed/ONNX, no GPU). FTS5 works without any model. You can open the DB with `sqlite3` and read everything.

### vs Karpathy-style wiki tools

They inject whole files into context when a note is relevant. RTFM serves metadata first, then the agent expands the chunk it actually needs. On a 1,700-file vault, the difference is between burning your quota in minutes and working through the day.

### vs code indexers

They parse code. RTFM parses code **and** docs (Markdown headers), **and** research papers (LaTeX sections), **and** legal articles (XML with cross-references), **and** structured data (YAML/JSON keys), **and** whatever custom format you write a ~50-line parser for.

## Who RTFM is for

- **Developers with large codebases** who want retrieval instead of grep loops.
- **Researchers** juggling LaTeX, PDFs, Python analysis code, data files — in one searchable index.
- **Regulated industries** mixing code with compliance documents, legal text, internal procedures.
- **Obsidian power users** whose vaults have outgrown `index.md` but who still want agent-readable navigation.
- **MCP ecosystem users** looking for a drop-in retrieval server that doesn't care which client is on the other end.

## Elevator description (150 chars)

> Open, local retrieval layer for AI agents. Indexes code, docs, PDFs, legal, research into one SQLite file. Claude searches it before grepping.
