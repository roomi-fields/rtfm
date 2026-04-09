# Positioning — RTFM in the AI Tooling Landscape

## The Problem

AI coding agents are blind. They grep through thousands of files, lose context every session, and hallucinate modules that don't exist. The bottleneck isn't reasoning — it's **localization**: finding the right files before writing code.

Our benchmarks on SWE-bench Verified show:
- On repos with 1000+ files, agents with retrieval tools solve **more tasks**
- Token cost drops **51%**, duration drops **16%**
- The gain is proportional to repo size — small repos don't need it, large repos can't work without it

See [[raw/benchmarks/benchmark_results|Benchmark Results]] for the data.

## The Landscape

### Code-only indexers

**Augment Context Engine**, **Sourcegraph**, **Code-Index-MCP** — all index code. None index docs, specs, legal texts, research papers, or domain-specific formats. If your project mixes code with non-code documents (which most regulated industries do), they can't help.

### Karpathy's LLM Wiki

Andrej Karpathy proposed using Obsidian vaults as human-readable RAG — three layers (raw, wiki, schema) maintained by an LLM. Projects like **Claudesidian** (2.1k stars), **claude-obsidian**, **obsidian-second-brain** implement this.

**The ceiling**: navigation relies on a flat `index.md` maintained by the LLM. Works for ~100 notes. Breaks at scale.

See [[docs/obsidian-vault-guide|Obsidian Vault Guide]] for how RTFM removes this ceiling.

### Where RTFM fits

```
                    Code-only          Multi-domain
                    ┌─────────────────┬──────────────────┐
  Enterprise ($$$)  │ Sourcegraph     │                  │
                    │ Augment CE      │                  │
                    ├─────────────────┼──────────────────┤
  Open source       │ Code-Index-MCP  │     RTFM         │
                    │                 │                  │
                    └─────────────────┴──────────────────┘
```

RTFM is the only open-source, multi-domain retrieval layer with:
- 10 built-in parsers (extensible in ~50 lines)
- FTS5 + semantic + hybrid search
- Graph-based ranking (wikilinks, imports)
- Progressive disclosure (metadata first, content on demand)
- Obsidian vault integration with auto-generated navigation
- MCP native (works with Claude Code, Cursor, Codex)

## The Pitch

> "Augment indexes your code. RTFM indexes everything."

> "Karpathy showed the vision. RTFM automates it."

> "When your vault outgrows index.md, RTFM takes over."

## Key Differentiators

### vs RAG pipelines

RAG requires: vector database, embedding infrastructure, retrieval-per-query tokenization, opaque vectors. RTFM: SQLite file, local embeddings (optional), FTS5 by default, everything in readable markdown.

### vs Karpathy wiki tools

They inject entire files into context. RTFM serves **progressive disclosure** — metadata first (~300 tokens), then expand only what's needed. At 1700 files, the difference is the difference between burning your quota in minutes and working all day.

### vs code indexers

They parse code. RTFM parses **everything**: code (Python AST), docs (Markdown headers), research (LaTeX sections), legal texts (XML articles), data (YAML/JSON keys), and any custom format via the parser API.

## Target Audiences

1. **Developers with large codebases** — retrieval instead of grep
2. **Researchers** — LaTeX + PDF + code in one searchable index
3. **Regulated industries** — code + legal/compliance docs
4. **Obsidian power users** — scalable vault retrieval for AI agents
5. **MCP ecosystem** — drop-in retrieval server for any MCP client
