# RAG Fundamentals — the 6 axes that every retrieval system makes choices on

"RAG" (Retrieval-Augmented Generation) is a suitcase word. It hides six very different design decisions, each with clear trade-offs. Most "RAG tools" get some of them right and hand-wave the rest — which is why one agent outperforms another on the same corpus.

This document lays out the grid. For each axis it names the common options, explains the trade-offs, and notes RTFM's choice as a concrete example. Use it to evaluate any retrieval tool — including this one.

---

## What RAG actually is

**RAG = Retrieval + Augmentation + Generation.** An LLM queries an external store, pulls relevant context, and conditions its answer on that context instead of (only) its weights.

The generation part is the LLM's job. Everything upstream of it — what you store, how you slice it, how you search it, how you feed it to the model — is what separates a RAG that works from one that does not.

The six axes:

| #   | Axis         | The question it answers                                           |
| --- | ------------ | ----------------------------------------------------------------- |
| 1   | Indexation   | How do we cut the content into searchable units?                  |
| 2   | Retrieval    | How do we find the right units for a query?                       |
| 3   | Augmentation | How do we feed the retrieved units to the LLM?                    |
| 4   | Integration  | How does the agent even know the retriever exists?                |
| 5   | Freshness    | How does the index stay aligned with the underlying content?      |
| 6   | Storage      | Where does the data live, and can you inspect / backup / migrate? |

Everything else (reranking, query rewriting, hybrid search) is a refinement inside one of these six axes.

---

## 1. Indexation — how you cut content

Before any search happens, content must be split into retrievable units ("chunks"). The cut decides what a later search can possibly return.

Common strategies:

- **Fixed char-based chunking** (e.g. 800 characters per chunk, 100 char overlap). Simple, fast, completely blind to structure. A function gets cut mid-body. A markdown section gets split across three chunks. This is the default in many conversation-memory tools and "drop-in" RAG libraries because it requires zero format knowledge.

- **Structural chunking** — use the format's own boundaries:
  - Markdown: one chunk per `#` header
  - Python: one chunk per class/function (via AST)
  - LaTeX: one chunk per `\section`
  - PDF: one chunk per page
  - XML / JSON: one chunk per top-level key
  More expensive to build, but each chunk is a semantically coherent unit before any search happens.

- **Paragraph / sliding window** — language-aware but structure-agnostic. A decent compromise when the format has no natural boundaries.

- **Semantic chunking** — an LLM decides where to cut. Highest quality, slowest, most expensive. Rarely justified vs structural.

### RTFM's choice

**Structural first.** Ten format-specific parsers ship built-in (Markdown, Python AST, LaTeX, YAML, JSON, Shell, PDF, XML, HTML, plaintext). New formats can be added in ~50 lines of Python via the parser registry.

> **Why this matters:** a chunk that maps to one Python function or one legal article is 80% of the retrieval problem already solved. Even a mediocre downstream search will return something useful. With 800-char char-chunks, even a great search returns arbitrary slices of text.

---

## 2. Retrieval — how you find the right unit

Once chunks exist, you need to map a query → the best-matching chunks. Four families, each with a distinct strength:

### Lexical (FTS5, BM25)
Match on tokens, weighted by term frequency and inverse document frequency.
- **Strong** on exact identifiers, proper nouns, code symbols, legal article numbers (`article 39`, `authenticate_user`, `OAuth2`).
- **Weak** on paraphrases — a query for "how to handle auth" will not match a chunk titled "authentication flow" unless they share actual tokens.
- **Free perks**: no model cold-start, no embedding step, no GPU, no cost.

### Semantic (vector search)
Precompute an embedding vector per chunk. At query time, embed the query and find the closest vectors (cosine / dot product / euclidean).
- **Strong** on paraphrase, synonymy, cross-lingual queries.
- **Weak** on exact identifiers — embeddings compress `authenticate_user` into the same region as `login_handler`, so FTS-precise lookups become fuzzy.
- **Choices inside vector search** (each with measurable impact):
  - **Embedding model**: MiniLM (light, multilingual), BGE (strong English), Nomic (strong code), OpenAI text-embedding-3 (paid, high quality). Model choice can swing recall by ±15pp.
  - **Distance function**: cosine for normalized vectors, dot product for raw, euclidean rarely.
  - **ANN index**: HNSW (Chroma, Qdrant), IVF (FAISS), flat (SQLite BLOB). Trade precision for speed.

### Hybrid
Run both lexical and semantic, fuse the results (rank fusion, reciprocal rank fusion, or a cross-encoder reranker on the top-N union).
- **Strong** on mixed queries that contain both exact terms and fuzzy concepts.
- **Cost**: 2× the query-time work, plus reranker latency if used.

### Graph
Follow structural edges between chunks: Python imports, `[[wikilinks]]`, LaTeX `\cite`, HTML `<a href>`, legal cross-references.
- **Strong** on dependency navigation and "show me everything connected to X".
- **Complementary** to the three above, not a competitor. Graph + FTS = find a concept's anchor, then expand its neighborhood.

### RTFM's choice

FTS5 by default (no cold-start, no setup, works on day one). Optional embeddings via FastEmbed/ONNX (~85 MB, no GPU). Hybrid mode available. Graph layer for file-level edges (imports, wikilinks, references) stored as first-class rows in the same SQLite database.

---

## 3. Augmentation — how you feed the LLM

You have the top-K chunks. How do you hand them to the agent? This is the axis where most RAG pipelines leak tokens, dilute signal, or hide their sources.

### Context stuffing
Concatenate every retrieved chunk and paste the whole thing into the prompt.
- **Pro**: trivial to implement, no extra round-trip.
- **Con**: blows the token budget on long answers, forces the agent to skim irrelevant chunks, scales linearly with top-K.
- **When it works**: top-K small (3–5) and chunks short (a few hundred tokens each).

### Templated / structured context
Same as stuffing but each chunk is wrapped in a structured block (path, score, section title, content). Let the agent see where information comes from so it can cite it or deprioritize low-score hits.
- **Pro**: slightly better agent reasoning, enables natural citations.
- **Con**: still stuffing — token cost is the same as raw concat plus template overhead.

### Reranking before stuffing
Retrieve a wider top-N (e.g. 20) with cheap search, rerank with a heavier cross-encoder or LLM to keep the top-K (e.g. 5), then stuff.
- **Pro**: much higher relevance density per token, measurable accuracy gain on ambiguous queries.
- **Con**: an extra model call at query time (latency + cost), requires picking a reranker (BGE-reranker, Cohere Rerank, cross-encoder MS MARCO…).

### Summarization before stuffing
Ask an LLM to compress each retrieved chunk into a 1–2 sentence summary, then stuff the summaries.
- **Pro**: massive token savings, useful when content is verbose (legal text, meeting notes).
- **Con**: summaries are lossy by definition — nuance, exact quotes, numerical details disappear. Bad fit for code or regulatory references.

### Progressive disclosure
Return metadata only (file paths, section titles, scores — typically < 300 tokens for 5 results). The agent decides what to read next and calls a second tool (e.g. `expand`) to fetch the full content of a specific chunk.
- **Pro**: token cost scales with what the agent actually uses, not what was retrieved. The agent self-directs.
- **Con**: requires multiple tool calls per search; only pays off when the agent can pick intelligently (modern coding agents can, simpler RAG pipelines can't).

### Agentic / multi-turn augmentation
Expose search as a tool the agent can re-call with refined queries during generation, rather than a single upfront retrieval step. Sometimes called "agentic RAG".
- **Pro**: the agent converges to the right answer by asking follow-up questions to its own retriever.
- **Con**: latency and cost grow with the number of tool calls; requires an agent loop, not a static pipeline.

### RTFM's choice

Progressive disclosure by default, agentic by extension. `rtfm_search` returns metadata only (no content). `rtfm_expand(source, target_section)` returns content for a specific chunk. The agent typically combines both across several turns, searching with narrower queries as it homes in on the answer. No summarization step (the structural chunks are already the right granularity). Reranking is optional and left to the caller.

---

## 4. Integration — how the agent knows the retriever exists

A retriever nobody calls is worthless. Two levels of "knowing":

### Technical discovery
The agent lists available tools and sees your retriever. This is what MCP (Model Context Protocol) provides — a standard for declaring tools that any MCP client (Claude Code, Cursor, Codex) can discover.

Problem: technical discovery is not enough. [Navigation Paradox](https://arxiv.org/abs/2503.09089) measures that **58% of agents ignore an external tool without explicit prompt engineering** — they fall back to native `grep` / `find` / `ls` even when a purpose-built retriever is available.

### Behavioural orientation
Instructions that tell the agent *when* to prefer your retriever over native tools. Claude Code reads these from the project's `CLAUDE.md`. Three lines of clear direction ("for any exploratory search, use `rtfm_search` before Glob/find/ls") bridge the 58% gap.

### RTFM's choice

Both. `.mcp.json` for technical discovery (auto-registered on `rtfm init`), `CLAUDE.md` injection for behavioural orientation (3-line template appended during init).

---

## 5. Freshness — how the index stays current

If the index is a day old, the agent searches stale content. Four strategies:

### Manual
User runs a command when they think of it. Reliable only as often as the user remembers.

### Cron
Scheduled every N minutes. Disconnected from actual usage. Re-indexes when nothing has changed; stale when content changes between ticks.

### Filesystem watcher
A daemon watches for file changes in real time. Robust but adds a long-running process per project. Heavy for the typical solo-dev workflow.

### Event-driven (agent hooks)
Latch onto the agent's natural events: user prompt submitted, agent stop, session end. No extra process, sync runs exactly when the user is about to ask something.

### RTFM's choice

Event-driven via Claude Code hooks:
- `UserPromptSubmit` → incremental FTS sync, throttled to once every 30 s, typically < 2 s.
- `Stop` (end of turn) → final sync to catch files the agent just wrote.
- `SessionEnd` (global) → versioned snapshot of `~/.claude/projects/*/memory/` for cross-session memory.

No cron, no watcher, no daemon. The index is fresh because the session is.

---

## 6. Storage — where the data lives

Where you store retrieval data determines what you can do with it outside the retriever: inspect, backup, migrate, version, debug.

### Dedicated vector DB
ChromaDB, Qdrant, Weaviate, Milvus. Optimized for similarity search. Opaque internal format, often a daemon or directory tree, hard to `grep` or `sqlite3 db.sqlite`. Great for scale (millions of chunks).

### Relational DB
SQLite, Postgres. Readable, queryable with ordinary tools. Can host FTS + vectors (as BLOB) + metadata + graph edges + version history in one file. Not the fastest for ANN, but plenty for < 1M chunks.

### Flat files
`index.md`, `backlinks.json`, per-file manifests. Simplest possible store. No real search — degenerates to `grep` over the filesystem.

### RTFM's choice

One SQLite file per project (`.rtfm/library.db`). Tables: `books`, `chunks`, `fts_chunks`, `edges`, `file_versions`, `embeddings` (BLOB column). Inspectable with `sqlite3`. Copy-able. Git-ignorable. A separate global DB at `~/.rtfm/memory.db` holds the cross-project agent memory index.

---

## Special case: Obsidian / LLM Wiki

Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) describes a pattern: an agent maintains a structured vault of notes for you, you navigate via Obsidian. Karpathy himself wrote: *"at small scale the index file is enough, but as the wiki grows you want proper search."* That is this axis.

RTFM's `rtfm vault` command:
- Detects `.obsidian/` and proposes a folder → corpus mapping
- Resolves `[[wikilinks]]` following Obsidian rules → stored as graph edges
- Generates a `_rtfm/` directory of Obsidian-native navigation files (index, graph with Mermaid, hubs, orphans, Dataview frontmatter)

The vault remains your primary artefact. RTFM is both the agent's retrieval engine *and* a navigation generator you can read in Obsidian directly.

---

## Decision helper — which choice for which situation

| If your content is…               | Best indexation            | Best retrieval                                |
| --------------------------------- | -------------------------- | --------------------------------------------- |
| Code (Python, JS, Rust…)          | AST / structural           | FTS + graph (imports)                         |
| Markdown docs, ADRs, specs        | Header-based               | FTS + hybrid on intros                        |
| Legal / regulatory                | Article-based              | FTS (exact article refs), graph on cross-refs |
| Academic papers (LaTeX)           | Section-based              | Hybrid                                        |
| Conversations, transcripts        | Paragraph / sliding window | Semantic                                      |
| Mixed corpus (code + docs + PDFs) | Per-format parsers         | Hybrid + graph                                |
| Small repo (< 500 files)          | Structural                 | FTS alone                                     |
| Large repo (> 5,000 files)        | Structural                 | Hybrid with reranker                          |

---

## How to evaluate a RAG (beyond the 6 axes)

When you benchmark your own retrieval layer or compare tools, measure at least three things:

- **Recall@K** — of the top-K chunks returned, how many contain the ground-truth answer? Requires a labeled set.
- **Time-to-answer** — cold start + query latency + agent context time. A tool that takes 30 s to wake up eats the session.
- **Token cost per resolved task** — agents that spend tokens grepping instead of retrieving are expensive. Compare with vs without the retriever.

FeatureBench, RepoQA, SWE-QA, LocAgent, and BRIGHT are all reasonable starting points depending on what you index. None of them perfectly measure a retrieval layer in isolation — they measure the agent + retriever + task triplet.

---

## Summary — RTFM's position on the grid

| Axis         | RTFM's choice                                         |
| ------------ | ----------------------------------------------------- |
| Indexation   | Structural (10 parsers, AST-aware)                    |
| Retrieval    | FTS5 default, optional embeddings, hybrid, graph      |
| Augmentation | Progressive disclosure (metadata → expand on request) |
| Integration  | MCP + `CLAUDE.md` injection                           |
| Freshness    | Event-driven via Claude Code hooks                    |
| Storage      | Single SQLite file per project + global memory DB     |

None of these is universally right — the correct choice depends on what you index and how the agent calls it. Use this grid to evaluate any retrieval tool (including this one) and pick the combination that matches your workload.

---

*This document is part of the [RTFM project](https://github.com/roomi-fields/rtfm). Feedback, corrections, and extensions welcome via issues or PRs.*
