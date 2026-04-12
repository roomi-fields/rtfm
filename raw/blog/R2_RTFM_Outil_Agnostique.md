---
type: article
title: "R2) RTFM: A Knowledge Tool That Only Touches What It Must"
subtitle: "An agnostic retrieval tool — not a code tool. Five design principles, and why metadata-first architecture changes everything."
excerpt: "RTFM isn't a code tool. It's a knowledge tool. It indexes everything — code, docs, legal, research — and serves minimal context on demand. Here are its design principles and why they matter."
slug: rtfm-agnostic-retrieval-tool
focus_keyword: RTFM agnostic retrieval
tags:
  - rtfm
  - retrieval
  - mcp
  - architecture
  - progressive-disclosure
  - metadata-first
  - parsers
  - agnostic
---

> [!abstract]- SPEC
> ## Brief — R2: RTFM, the agnostic tool
> ### Position in the series
> - **Series**: R (Retrieval) — Does Retrieval Help? | **Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]]
> - Presents the tool used as the experimental intervention in the study
> - Not to claim architectural novelty, but because its design choices influence the results
> ### Topics covered
> - The 5 design principles (domain/format/protocol/model-agnostic + non-invasive)
> - The metadata-first → expand on demand pattern
> - Technical stack (SQLite + FTS5 + FastEmbed)
> - Positioning vs. existing tools (Augment CE, Sourcegraph, Code-Index-MCP, CodeCompass)
> - Why rigorous evaluation is the real differentiator
> ### SOTA sources
> - `paper/sota/08_competitive_landscape.md`

# R2) RTFM: a knowledge tool that only touches what it must

## Five design principles, and why metadata-first architecture changes everything

> Retrieval tools for coding agents already exist. What's missing is proof that they work.

## Where does this article fit?

In [[R1_Le_Goulot_de_Localisation_en|R1]], we set the diagnosis: coding agents spend 38% of their time exploring, the oracle gap is 9 to 50 percentage points, and context rot shows too much context is worse than too little. The conclusion: we need a search tool that serves *minimal* and *relevant* context, not a dump of the whole project.

This article introduces the tool we built to test this thesis: RTFM. Not to promote it — it's open source, judge for yourself — but because its design choices have direct consequences on the experimental results. When we measure the impact of retrieval ([[R4_Resultats_en|R4]]), you have to understand *which* retrieval we're measuring.

---

## The problem with existing tools

Before building anything, let's survey what exists.

### Commercial solutions

**Augment Context Engine** (February 2026) is the most serious commercial competitor. It's a proprietary semantic context engine exposed via MCP. It indexes code, documentation, tickets, internal wikis, commit history. It works with Claude Code. It costs between $20 and $200 per month.

Augment claims "+80% performance with Claude Code + Opus 4.5." The figure is impressive. The problem: no published protocol. No standardized benchmark. No confidence intervals. No methodology description. "+80%" compared to what, on which tasks, with what baseline? We don't know.

**Sourcegraph Cody** exposes its code search capabilities via MCP in the enterprise version. It's a powerful tool — cross-organization search, multi-repo, semantic and lexical. But it's enterprise-only (starting at $49/user/month), code-only, and again: no public benchmark measuring the impact on agent performance.

**Greptile** offers a codebase analysis API with MCP. Valued at $180 million. Code review focus. Cloud-only. Paid. No benchmark either.

### Open-source solutions

**Code-Index-MCP** (johnhuang316, 793 stars) indexes code in 7 languages with tree-sitter AST. It's the most popular open-source tool in this category. But it's purely code — no documentation, no config files, no structured data. And above all: zero published evaluation.

**Code-Index-MCP** (ViperJuice, 38 stars) is architecturally closest to what we built — same SQLite + FTS5 stack, same hybrid search principle. But again: code-first (Markdown/YAML as secondary), no extensible parsers, no multi-corpus. And no evaluation.

**mcp-codebase-index** uses Python AST for indexing, with incremental updates via `git diff`. Elegant, zero dependencies. But code-only.

**CodeCompass** (from the Navigation Paradox paper) is an interesting case: it's a Neo4j AST graph exposed via MCP. It does *structural* navigation, not *textual* search. It's a complementary tool, not a competitor.

### The common pattern

All these tools share two characteristics:

1. **They're code-centric.** Code, code, code. Code is important, but a real project also contains documentation, configuration files, specifications, structured data, maybe legal documents or research notes.

2. **None has published rigorous evaluation.** Marketing claims, internal micro-benchmarks, or nothing at all. No one has taken a standardized benchmark, defined a controlled protocol with an isolated variable, and measured the impact of retrieval on agent performance.

---

## Five principles for a different tool

RTFM was born from an observation: if the limiting factor is the ability to find the right context ([[R1_Le_Goulot_de_Localisation_en|R1]]), then the search tool shouldn't presume the *nature* of the context. Five principles guide its design.

### 1. Domain-agnostic — not a code tool, a knowledge tool

RTFM indexes everything. Python code (via AST), shell scripts (functions and comments), Markdown documentation (sections by headers), LaTeX articles (`\section`/`\subsection` structure), YAML and JSON configurations (top-level keys), PDF documents (extracted text), XML legal texts (Legifrance statutes), HTML pages (BOFiP), and plain text as fallback.

The same tool serves a developer searching for a function, a lawyer searching for a statute, a researcher searching for a reference in their notes, a musicologist searching for a passage in their corpus.

It's not an engineering whim. It's a direct consequence of the thesis. An agent working on a real project needs to find existing code, documentation of business constraints, corresponding tests, and maybe specifications — all in the same project, with the same tool, in the same query.

### 2. Format-agnostic — extensible parsers in 50 lines

Adding a new format to RTFM takes about 50 lines of Python. You inherit from `BaseParser`, implement `parse()`, declare supported extensions. That's it.

```python
class MyParser(BaseParser):
    extensions = {".myformat"}

    def parse(self, content: str, metadata: dict) -> list[Chunk]:
        # split the content into relevant chunks
        # return a list of Chunk(title=..., content=..., metadata=...)
        ...
```

10 parsers ship with the tool. But the real value is in extensibility: anyone can add support for their business format, their scientific data format, their internal documentation format — without touching the core of the system.

The system doesn't presume the format. It adapts. That's the difference between a *code* indexing tool and a *knowledge* indexing tool.

### 3. Protocol-agnostic — MCP as lingua franca

RTFM is exposed via MCP (Model Context Protocol), Anthropic's open standard for communication between AI agents and tools. MCP is to the agent world what HTTP is to the web: a standard protocol that enables interoperability.

Concretely: RTFM works with any MCP-compatible agent. Claude Code, Continue.dev, Cursor (via MCP), or any MCP client someone writes tomorrow. No IDE lock-in, no dependency on a model provider.

The tool exposes 11 MCP endpoints, the main ones being:
- `rtfm_search(query)` — full-text and/or semantic search
- `rtfm_context(subject)` — targeted search on a topic
- `rtfm_expand(slug)` — retrieve the full content of a chunk
- `rtfm_discover()` — fast scan of project structure

### 4. Model-agnostic — pure retrieval, zero generation

RTFM contains no language model. Zero. It generates nothing, interprets nothing, summarizes nothing. It indexes documents and returns search results. Period.

The (optional) embeddings use FastEmbed (ONNX), a lightweight encoder that runs on CPU. But even the embeddings are only there for *ranking* results — not for generation.

The consequence: RTFM is compatible with any LLM. Whether the agent runs on Claude, GPT, Gemini, Llama, Mistral, or a fine-tuned open-source model changes nothing about how RTFM works. The tool produces data; the agent's model decides what to do with it.

### 5. Non-invasive — replace what must be replaced, touch nothing else

This is perhaps the most important principle, and the one that takes the most discipline.

RTFM doesn't modify the agent's workflow. It *adds* search tools. The agent can use them — or ignore them completely. There's no forced retrieval, no context silently injected into the prompt, no background modification of the agent's behavior.

When the agent needs to find a dependency in an 8,000-file project, it uses `rtfm_search`. When it already knows where to code, it uses `Read` and `Edit` directly — exactly as before. The tool replaces blind navigation (`grep`, `glob`, `find`) where that's relevant, and doesn't touch the rest: editing, execution, debug, tests — all that stays unchanged.

It's an amplifier, not a replacement. And this distinction will turn out to be crucial in the results ([[R4_Resultats_en|R4]]).

---

## The metadata-first pattern

RTFM's central architecture is what we call **progressive disclosure** — or more precisely, **metadata-first → expand on demand**.

### The context problem

[[R1_Le_Goulot_de_Localisation_en|R1]] showed that context rot is real: beyond a threshold, adding context *degrades* performance. ContextBench shows agents see the relevant context but only retain 50-70%. AgentDiet shows 40-60% of exploration tokens are waste.

The architectural conclusion is clear: serve the *minimum* relevant context, not the maximum.

### The two-step solution

**Step 1: search returns metadata.**

```
> rtfm_search("validation scorers mlflow")

1. mlflow/models/evaluation/validation.py
   Score: 0.89 | Chunks: 12 | 342 lines
2. mlflow/models/evaluation/scorers.py
   Score: 0.76 | Chunks: 8 | 218 lines
3. mlflow/models/evaluation/data.py
   Score: 0.71 | Chunks: 6 | 156 lines
```

~300 tokens. No content. Just coordinates: which file, which relevance, which size. Enough for the agent to decide *whether* the result is worth reading.

**Step 2: the agent reads what it needs.**

The agent sees the absolute path in the results. If it decides `validation.py` is relevant, it does a `Read("/testbed/mlflow/models/evaluation/validation.py")` — its standard tool, the one it uses anyway. It loads the *entire* file into its context, at the exact moment it needs it.

If it decides `data.py` isn't relevant for its task, it doesn't load it. The 300 tokens of metadata haven't polluted its context window with useless content.

### Why this matters

Out of 5 search results, the agent might read 2 files. With a "dump all content in results" approach, all 5 files would have been loaded — say 3000 tokens of code × 5 = 15,000 tokens. With the metadata-first pattern, the agent only loads what it uses: 300 tokens of metadata + 2 files read on demand. Effective context is 2 to 5x smaller.

It's the exact opposite of systems that send entire pages of code in search results. And it's consistent with what the literature tells us: targeted minimal context is more effective than a massive dump.

---

## Technical stack

Under the hood, RTFM is simple:

**Storage:** SQLite. A single `.db` file, portable, copied from one machine to another without configuration.

**Full-text search:** FTS5, SQLite's built-in search engine. Uses BM25 for ranking. Zero external dependencies, zero cold start, sufficient performance for 180,000-chunk indexes.

**Semantic search (optional):** FastEmbed, a lightweight ONNX runtime. The `paraphrase-multilingual-MiniLM-L12-v2` model encodes chunks and queries into 384-dimensional vectors. ~17 seconds of warm-up, then instant search. Hybrid FTS + embeddings weights both scores.

**Synchronization:** incremental via SHA-256 hash. On each sync, only modified files are re-indexed. On a stable project, sync is near-instant.

**Parsing:** each format has its dedicated parser. The Python parser uses the stdlib AST to split into classes and functions. The Markdown parser splits by headers. The LaTeX parser splits by `\section`. Each parser produces chunks — indexable content units with title, content, and metadata.

| Component          | Technology       | Dependency    |
| ------------------ | ---------------- | ------------- |
| Database           | SQLite           | Python stdlib |
| Lexical search     | FTS5 (BM25)      | Python stdlib |
| Semantic search    | FastEmbed (ONNX) | optional      |
| Parsing            | AST, regex, DOM  | Python stdlib |
| Protocol           | MCP (FastMCP)    | `mcp` package |
| Sync               | SHA-256 hash     | Python stdlib |

The core has only one required dependency: `pyyaml`. The rest is optional. It's a deliberate choice: a tool that installs in 2 seconds is a tool that will actually be used.

---

## Positioning: what's novel and what isn't

Let's be honest about what RTFM brings and what it doesn't.

### What's NOT novel (and we don't claim it)

- Pre-indexing a codebase and exposing the index via MCP. Augment does it. Code-Index-MCP does it. Others too.
- FTS5 + SQLite for indexing. ViperJuice uses the same stack.
- Semantic search via embeddings. Everyone does it.
- Incremental sync. mcp-codebase-index uses `git diff`, which is even smarter.

### What's different (but not the subject of the paper)

- **Multi-domain**: the only open-source tool that indexes code + docs + legal + research + structured data.
- **Extensible parsers**: ~50 lines for a new format. No other tool offers this.
- **Metadata-first**: search results contain no content, just coordinates.
- **Multi-corpus**: multiple sources in the same database, with cross-source search.

### The real differentiator

**Evaluation.** We took a standardized benchmark (FeatureBench, ICLR 2026), defined a 4-condition protocol with an isolated variable, and measured the impact. It's described in [[R3_Protocole_Experimental_en|R3]], the results are in [[R4_Resultats_en|R4]].

None of the tools listed above did that. Augment's "+80%" is a marketing claim. Navigation Paradox's "+23.2 pp" uses 30 micro-tasks created by the authors, not a third-party benchmark. The open-source tools have no evaluation.

| Property               | RTFM                      | Augment CE            | Code-Index-MCP  | CodeCompass     |
| ---------------------- | ------------------------- | --------------------- | --------------- | --------------- |
| Multi-domain           | Code+docs+legal+research  | Code+docs+tickets     | Code only       | Python code     |
| Extensible parsers     | ~50 LOC                   | No                    | No              | No              |
| Open source            | Yes                       | No                    | Yes             | Yes             |
| Progressive disclosure | metadata-first            | N/A (proprietary)     | direct content  | AST graph       |
| **Published eval**     | **Standardized benchmark**| "+80%" no protocol    | None            | 30 micro-tasks  |
| Pricing                | Free                      | $20-200/mo            | Free            | Free            |

The contribution of this work isn't the tool. It's the empirical proof that this *type* of tool works — and under what conditions.

---

## References

- **Augment Code (2026)** — Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
- **Sourcegraph (2025)** — Cody MCP Integration. https://sourcegraph.com/docs/api/mcp
- **Greptile (2026)** — MCP Overview. https://www.greptile.com/docs/mcp/overview
- **johnhuang316** — Code-Index-MCP. https://github.com/johnhuang316/code-index-mcp
- **ViperJuice** — Code-Index-MCP. https://github.com/ViperJuice/Code-Index-MCP
- **mcp-codebase-index** — https://pypi.org/project/mcp-codebase-index/
- **Navigation Paradox (2026)** — CodeCompass MCP. arXiv:2602.20048.
- **Vasilopoulos, D. (2026)** — Codified Context. arXiv:2602.20478.
- **Hong, J. et al. (2025)** — Context Rot. Chroma Research.

---

## Glossary

- **BM25**: *Best Match 25* — ranking algorithm for full-text search, industry standard since the 1990s.
- **Chunk**: content unit indexed by RTFM — a Python function, a Markdown section, a statute.
- **FastEmbed**: Python library for embeddings via ONNX, without PyTorch/TensorFlow dependency.
- **FTS5**: *Full-Text Search 5* — search engine built into SQLite, uses BM25 for ranking.
- **Metadata-first**: architectural pattern where search results contain only metadata (title, path, score), not document content.
- **MCP**: *Model Context Protocol* — open standard for communication between AI agents and tools.
- **ONNX**: *Open Neural Network Exchange* — portable format for machine learning models.
- **Parser**: component that splits a document into indexable chunks according to the format's conventions.
- **Progressive disclosure**: providing information at increasing levels of detail, on demand.
- **SQLite**: embedded relational database, stored in a single file.

---

## Links in the series

- [[R1_Le_Goulot_de_Localisation_en|R1]] — The localization bottleneck — the fundamental problem
- **R2** (this article) — RTFM: a knowledge tool that only touches what it must
- [[R3_Protocole_Experimental_en|R3]] — The protocol: 4 conditions, 11 tasks, same model
- [[R4_Resultats_en|R4]] — The results: when repo size changes everything
- [[R5_Agent_Decide_Seul_en|R5]] — The agent calibrates itself: selective retrieval without training
- [[R6_Perspectives_en|R6]] — What it changes — and what remains to be proven

---

**Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]]
**Reading time**: 14 min
**Tags**: #rtfm #retrieval #mcp #architecture #progressive-disclosure #metadata-first #agnostic

---

*Next article: [[R3_Protocole_Experimental_en|R3]] — The protocol: 4 conditions, 11 tasks, same model*

---
