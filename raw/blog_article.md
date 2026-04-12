# What if an AI agent knew what it didn't know?

## How a simple search tool transforms coding-agent performance on large projects

*Romi Fields — March 2026*

---

## 1. The problem nobody measures

Coding agents are everywhere. Claude Code, Cursor, Windsurf, SWE-agent — they write code, fix bugs, implement features. Benchmarks pile up: SWE-bench reports 74% resolution with the best models, and companies compete with impressive numbers.

But there's a blind spot.

When you actually observe what a coding agent does during a task, you discover something surprising: **it isn't coding most of the time**. A trajectory study of agents on SWE-bench (Trajectory Study, 2025) reveals that 38% of actions are exploration — `grep`, `find`, file reads — not code writing. The agent searches. It fumbles. It opens files, closes them, opens others. On failing agents, this ratio is even higher: they loop through the source code without finding what they're looking for.

This phenomenon has a name in the literature: **the localization bottleneck**. Before being able to code, the agent must first *find* where to code. And that's where things get complicated.

PatchPilot (ICML 2025) quantified this problem: localization capability accounts for roughly 47% of the total improvement of an agent. In other words, if you improve an agent's ability to *find* the right code, you improve its results almost as much as if you improved its ability to *write* code. Agentless (Xia et al., 2024) showed that a hierarchical approach — first find the right file, then the right function, then the right line — reaches 77.7% file-level recall but only 50.8% line-level recall. Localization is hard.

And the bigger the project, the harder it is. A repo of 600 files, an agent can traverse it quickly. A repo of 8,000 files? That's another story.

### The oracle gap: proof that retrieval matters

The most striking result comes from CodeRAG-Bench (Wang et al., NAACL 2025). The authors measured the performance of code models under three conditions: without context, with context retrieved by a search system (BM25), and with the *perfect context* — an oracle that hands exactly the relevant files.

The results are staggering:

| Condition | StarCoder2-7B on HumanEval |
|---|---|
| Without context | 31.7% |
| With BM25 (lexical search) | 43.9% |
| **With oracle context** | **94.5%** |

From 31.7% to 94.5%. Same model, same task. The only difference: the quality of context provided. The gap between the best current retrieval and the oracle is 9 to 50 percentage points depending on the model and task. Every point of retrieval quality translates directly into performance.

The conclusion is clear: **the limiting factor is not the model, it's the context**.

---

## 2. The blind tools of today's agents

How does a coding agent explore a project today? With `grep`, `glob`, `find` and `cat`. Tools designed for humans in the 1970s. The agent runs `grep -r "validate" .` and gets 847 results. It reads 12, gives up, tries another query. Starts over.

These tools have three fundamental problems when used by an AI agent:

**1. They are blind.** `grep` doesn't know the project's structure. It doesn't know that `validation.py` is linked to `scorers.py` which depends on `data.py`. It searches for textual patterns in files, with no notion of semantics or structure.

**2. They are context-expensive.** Every `grep` result is loaded into the agent's context window. And the literature shows that too much context *degrades* performance. Hong et al. (2025) demonstrated what they call "context rot": beyond a certain threshold, adding context decreases model answer quality. ContextBench (2025) goes further: even when agents find the right context (AUC-Cov > 0.70), only 50 to 70% of the information is actually retained in the final response. Seeing is not using.

**3. They don't know when to stop.** The agent has no signal telling it "you found what you needed" or "this trail is a dead end". AgentDiet (2025) showed that 40 to 60% of exploration tokens are pure waste — you can strip them without affecting the final result.

### The metacognitive paradox

There's an even deeper problem. LLMs do not know what they don't know. Ackerman et al. (2025) studied the metacognitive capabilities of language models and concluded they are "increasing but limited in resolution, context-dependent, and qualitatively different from humans." Plainly put: an LLM cannot finely evaluate what information it is missing.

That's where our central intuition lies. The agent doesn't need to *know* what it doesn't know. It needs a way to *check* at low cost. A search tool is exactly that: a metacognitive prosthesis. The agent can ask itself "does this project have a validation module?" and get an answer in 300 tokens instead of spending 15 minutes navigating the tree.

---

## 3. RTFM: a tool that only touches what it should

### The agnostic philosophy

Faced with this observation, we built RTFM — a retrieval tool designed around a simple principle: **help where it's needed, touch nothing else**.

RTFM is not a code tool. It is a knowledge tool. This distinction matters. Existing tools — Augment Context Engine, Sourcegraph Cody, Code-Index-MCP — index code. RTFM indexes *everything*: Python code (via AST), Markdown documentation, LaTeX files, YAML and JSON configurations, shell scripts, PDF documents, XML legal texts, HTML pages. The same tool can serve a developer looking for a function, a lawyer looking for a legal article, or a researcher looking for a reference in their notes.

This universality is not an engineering whim. It is a direct consequence of the thesis: if the limiting factor is the ability to find the right context, then the search tool shouldn't presume the nature of the context. An agent working on a real project needs to find existing code, documentation of business constraints, the corresponding tests, and perhaps the client's specifications — all in the same project, with the same tool.

Five design principles guide RTFM:

**Domain-agnostic.** 10 built-in parsers, but above all: adding a new format takes roughly 50 lines of Python. Inherit from `BaseParser`, implement `parse()`, that's it. The system doesn't presume the format — it adapts.

**Protocol-agnostic.** RTFM is exposed via MCP (Model Context Protocol), Anthropic's open standard for agent-tool communication. It works with any MCP-compatible agent: Claude Code, Continue.dev, Cursor, or any MCP client. No dependency on a specific IDE or vendor.

**Model-agnostic.** Pure retrieval, zero generation. No embedded language model. RTFM returns search results; the agent's model decides what to do with them. Whether the agent runs on Claude, GPT, Gemini, or an open-source model changes nothing.

**Non-invasive.** RTFM doesn't modify the agent's workflow. It adds search tools. The agent can use or ignore them. It replaces blind navigation when relevant — and doesn't touch the rest. No forced retrieval, no context silently injected into the prompt.

**Context-thrifty.** This is the most important architectural point.

### The metadata-first pattern

RTFM uses a two-step *progressive disclosure* pattern:

1. **`rtfm_search("validation mlflow")`** → returns ~300 tokens of *metadata*: chunk title, absolute source-file path, relevance score. No content. Just enough for the agent to know whether the result is relevant and where to go read it.

2. The agent reads the file directly via its standard `Read(file_path)` tool — the absolute path is in the results. It loads only what it needs, when it needs it.

This pattern is the opposite of the "dump the whole context" approach that causes context rot. The agent only consumes context for what is relevant, when it is relevant. Out of 5 search results, the agent may only read 2 files — the 300 tokens of metadata for the other 3 never polluted its context window with useless content.

On the technical side: SQLite + FTS5 (BM25) as the backbone, with optional embeddings via FastEmbed (ONNX). Portable database — a single `.db` file. Incremental synchronization via SHA-256 hashing.

### What about the competitive landscape?

This kind of tool is no longer novel in 2026. Augment Code offers a Context Engine MCP (paid, proprietary, $20-200/month). Sourcegraph Cody exposes its capabilities via MCP (enterprise-only). Several open-source tools exist: Code-Index-MCP, mcp-codebase-index, CodeCompass.

But none of them has published a rigorous evaluation. Augment claims "+80% performance with Claude Code" — no published protocol, no standardized benchmark, no confidence intervals. CodeCompass was evaluated on 30 synthetic micro-tasks created by the authors. The open-source tools have no published evaluation at all.

That is the gap we decided to fill: **not a new tool, but the first controlled evaluation of a retrieval tool for coding agents on a standardized benchmark.**

---

## 4. The experiment: 4 conditions, same tasks, same model

### FeatureBench as the playground

To rigorously evaluate the impact of retrieval, we needed a benchmark that meets three criteria: realistic tasks (not isolated functions), projects of varying sizes, and a reliable automatic evaluation.

FeatureBench (ICLR 2026) checks those boxes. Unlike SWE-bench, which focuses on bug fixing (and suffers from proven contamination — SWE-Bench Illusion, 2025), FeatureBench asks agents to *implement new features* in real projects. It's harder: the best published score is 11%, versus 74% on SWE-bench Verified. And crucially, it requires understanding the project's architecture before coding.

We selected 11 tasks across 4 repos of increasing size:

| Repo | Indexed files | Tasks |
|---|---|---|
| metaflow (Netflix) | 624 | 1 |
| pydantic | 771 | 1 |
| astropy | 1,123 | 2 |
| mlflow | 8,260 | 7 |

### The 4 conditions

The variable we isolate is simple: **does the agent have access to a pre-indexed search tool?**

To test this cleanly, we designed 4 experimental configurations:

**Config A — Standard (positive control).** The original FeatureBench prompt. It contains the paths of files to modify and the interfaces to implement. This is a semi-oracle condition: the agent already knows *where* to code. In practice, this is unrealistic — a developer launching an agent on a Jira ticket doesn't hand it the list of files to modify.

**Config B — Discovery (realistic baseline).** We remove the paths from the prompt. Concretely, we strip the `Path: /testbed/...` lines — that's less than 1% of the prompt (751 characters out of 78,000). The rest is identical: feature description, expected interfaces, function signatures. The agent must *discover* where to code. This is the realistic condition.

**Config C — Discovery + FTS.** Same prompt as B, but the agent has access to RTFM with full-text search (BM25). The database is pre-built — as in real use, where RTFM is already initialized in the project.

**Config D — Discovery + FTS + Embeddings.** Same prompt as B, with RTFM in hybrid mode: full-text + semantic search via embeddings.

The only variable between B and C/D is the presence of the search tool. Same agent (Claude Code), same model (Claude Sonnet 4.0), same environment (Docker), same timeout (1200 seconds).

---

## 5. The results: when repo size changes everything

### The headline result: test_validation on mlflow

The `test_validation` task requires implementing a data validation module in mlflow — a 8,260-file project. The difficulty: the module must interact with three existing components scattered across the project (`validation.py`, `scorers.py`, `data.py`). To succeed, the agent must find these cross-module dependencies.

| Condition | F2P (fail-to-pass) | Resolved? |
|---|---|---|
| A — Standard (paths given) | 55% (6/11 tests) | No |
| B — Discovery (no retrieval) | 64% (7/11 tests) | No |
| C — Discovery + FTS | **100% (11/11 tests)** | **Yes** |
| D — Discovery + FTS+Embed | **100% (11/11 tests)** | **Yes** |

With retrieval (C and D), 100% of tests pass. Without retrieval (A and B), between 55% and 64%.

And note: Config A, the one where paths are *given in the prompt*, also fails to resolve. Knowing *where* to code is not enough — the agent must also understand *how* the modules interact. That is precisely what retrieval brings: a search on "validation scorers" returns the relevant files *and their context*.

Configs A and B systematically fail on the same tests: those that require understanding the interactions between `validation.py`, `scorers.py` and `data.py`. The agent without retrieval implements the validation module in isolation — syntactically correct, but incompatible with the rest of the project.

### The counter-example: test_stub_generator on metaflow

At the other end, the `test_stub_generator` task is on metaflow — a 624-file repo. Result:

| Condition | F2P | Resolved? |
|---|---|---|
| A — Standard | 100% (31/31) | Yes |
| B — Discovery | 100% (31/31) | Yes |
| C — Discovery + FTS | 100% (31/31) | Yes |
| D — Discovery + FTS+Embed | 96.8% (30/31) | No (1 test missed) |

All four configs resolve the task (except D, which misses 1 test out of 31 — an artifact). And RTFM is even counter-productive: Config C is 23% slower and 22% more expensive than A. The RTFM agent barely uses the tool (1-2 calls) — it navigates directly because the repo is small.

**On a 624-file repo, `grep` is enough.** The localization bottleneck does not exist. RTFM is a tool for large repos.

### FTS vs Embeddings: the surprise

Comparing Config C (FTS only) and Config D (FTS + embeddings) reveals a result that confirms the recent literature:

| Metric | Config C (FTS) | Config D (FTS+Embed) |
|---|---|---|
| Resolved | Yes (100%) | Yes (100%) |
| Turns | 81 | **50** |
| Cost | $4.04 | **$2.23** |
| Read calls | 23 | **12** |
| Bash calls | 20 | **9** |

The resolve rate is identical. But D is significantly more efficient: fewer turns (-38%), cheaper (-45%), fewer file reads (-48%). Embeddings don't change the *outcome*, but they change the *path*: the agent goes more directly to the right files instead of groping with text queries.

This result is consistent with Galimzyanov (2025) and GrepRAG (ISSTA 2026), which show that BM25 is competitive with dense embeddings for code search. Lexical search is often enough — embeddings add a layer of efficiency, not capability.

### The failure case: when retrieval is not enough

`test_responses_agent` is the most complex task in the benchmark: 78,000-character prompt, 15 interfaces to implement, a ground truth of 226,000 characters across 60 files. Result: **no configuration resolves the task**. Neither A, nor B, nor C, nor D.

But the analysis reveals interesting nuances:

| Metric | A (Standard) | B (Discovery) | C (FTS) | D (Embed+) |
|---|---|---|---|---|
| Resolved | No (3.5%) | No (TIMEOUT) | No (0%) | No (0%) |
| Interfaces covered | 15/15 | 0/15 (timeout) | 8/15 | 12/15 |
| Patch size | 92K chars | 0 | 51K chars | 91K chars |
| Cache read | 23.8M | 18.9M | 8.7M | 9.0M |

Config B doesn't even produce code — it times out at 1200 seconds, lost in the 8,260 files. Config D covers 12 out of 15 interfaces and produces a patch nearly as large as A (which had the paths). Embeddings guide the agent to the right files, but Sonnet 4.0 simply cannot handle the complexity of 15 simultaneous interfaces.

**Retrieval is necessary but not sufficient.** It resolves the localization bottleneck, not the model's capability bottleneck.

A notable detail: configs C and D consume 2 to 3 times less cache read than A and B (8-9M vs 19-24M tokens). The metadata-first pattern works — the agent loads less context and does more targeted work.

---

## 6. The agent decides alone when to search

An unexpected result of our study concerns how the agent uses the search tool.

The literature on adaptive retrieval (Self-RAG, Repoformer, FLARE) has established an important result: systematic retrieval degrades performance. Repoformer (ICML 2024) shows that 70% of code retrievals are useless. Self-RAG (ICLR 2024) shows that adaptive retrieval outperforms systematic retrieval by 40% relative. The sweet spot is neither "always search" nor "never search" — it's "search when necessary".

These systems use trained classifiers or fine-tuning to decide when to retrieve. Our approach is simpler: **we give the tool to the agent and let it decide on its own.**

And it works. On `test_validation`, the agent makes 2 to 3 RTFM calls — just enough to locate the critical modules. On `test_stub_generator` (small repo), it makes 1 call and never returns to it. On `test_responses_agent` (the monster task), it makes 10 to 15 calls to cover as many interfaces as possible.

The agent does selective retrieval naturally, with no specific training, no classifier. This suggests that current LLMs (at least Claude Sonnet 4.0) have sufficient metacognition to decide when a search tool is useful — provided the tool is available and its cost of use is low (300 tokens of metadata per query).

This may be the most important result of this study, beyond the performance numbers: **you don't need to force retrieval. You just need to make it possible.**

---

## 7. What this changes in practice

### The 1,000-file rule

Our preliminary results draw a clear boundary:

- **Under ~600 files**: direct navigation (`grep`, `glob`, `find`) is enough. The agent traverses the project quickly enough to find what it needs. Retrieval is overhead with no benefit.

- **Above ~8,000 files**: retrieval transforms results. The agent without retrieval gets lost in the tree, falls into exploration loops, and fails to find cross-module dependencies. The agent with retrieval finds them immediately.

The middle zone (1,000 to 5,000 files) remains to be explored — this is precisely what our in-progress runs on pydantic (771 files) and astropy (1,123 files) aim to clarify.

If this threshold is confirmed, the practical recommendation is simple: **deploy a pre-indexed retrieval tool on any project over 1,000 files.** The initialization cost is negligible — 10 to 78 seconds of parsing depending on repo size — and the potential benefit is considerable.

### The real cost: per resolved task

An argument against retrieval is that it increases the per-task cost. And that's true: on `test_validation`, Config D costs $2.23 versus $1.50 for Config B. +49%.

But Config B does not resolve the task. Config D does. The relevant cost is not the cost per attempt — it's the cost per *resolved* task. A $2.23 run that resolves is infinitely better than a $1.50 run that fails, which you'll have to re-run, maybe several times, or complete manually.

### Beyond code

We tested RTFM on code, but its agnostic philosophy extends to broader uses. In a separate A/B test on writing an academic article (a documentation use case, not code), RTFM v3 cut cost by 51% and duration by 16% versus the baseline, while producing a more complete article.

The tool replaces blind navigation where necessary — dependency search, locating relevant files, discovering related content — and doesn't touch the rest. It does not change editing, execution, or debugging. It is an amplifier, not a replacement.

---

## 8. What the literature does not prove (and neither do we, yet)

Let's be honest about the limits of this study — and of others.

**What nobody has rigorously proven:**

Augment Code claims "+80% performance with Claude Code + Opus 4.5". No published protocol, no standardized benchmark, no confidence intervals. Sourcegraph Cody has no public benchmark. The open-source MCP tools (Code-Index-MCP, mcp-codebase-index) have no published evaluation. The Navigation Paradox paper evaluates CodeCompass on 30 synthetic micro-tasks created by the authors — not on a third-party benchmark.

**Our own limits:**

- A single model (Sonnet 4.0). Generalization to other models is unmeasured.
- A single tool (RTFM). A competing tool could give different results.
- 11 tasks, 4 repos. The sample is small.
- Python only. FeatureBench lite covers only Python projects.
- The data presented here are from single runs. The full matrix (11 tasks × 4 conditions × N repetitions) is in progress.

What we do claim is the method: **a controlled protocol on a standardized benchmark, with an isolated variable and reproducible metrics.** When the full results are available, they will be submitted to *Empirical Software Engineering* (EMSE) — the reference journal for empirical software engineering studies.

---

## 9. Conclusion: give the agent a choice

The opening question was simple: **does giving a coding agent a search tool help?**

The answer is nuanced but clear: **yes, on large projects.** On mlflow (8,260 files), retrieval lifts the resolve rate from 55-64% to 100%. On metaflow (624 files), no measurable gain.

But beyond the numbers, the most interesting result may be philosophical. We don't need to force the agent to search, nor to train it to decide when to search. We just need to *give it the choice*. When the tool is there, costs little in context (300 tokens per query), and doesn't change the rest of the workflow — the agent uses it intelligently, when it needs to, and ignores it when it doesn't.

That is the practical lesson of this study: coding agents are not limited by their intelligence. They are limited by their navigation tools. Give them a map of the territory — not a GPS that dictates the route, just a map they can consult — and they find their way.

---

## References

1. Jimenez, C.E. et al. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.
2. FeatureBench (2026). ICLR 2026. arXiv:2602.10975.
3. Yang, J. et al. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. NeurIPS 2024. arXiv:2405.15793.
4. Xia, C.S. et al. (2024). Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489.
5. PatchPilot (2025). ICML 2025. arXiv:2502.02747.
6. Chen, Y. et al. (2025). LocAgent. ACL 2025. arXiv:2503.09089.
7. Trajectory Study (2025). arXiv:2506.18824.
8. Navigation Paradox (2026). arXiv:2602.20048.
9. Wang, Z. et al. (2024). CodeRAG-Bench: Can Retrieval Augment Code Generation? NAACL 2025. arXiv:2406.14497.
10. Galimzyanov, F. et al. (2025). Practical Code RAG at Scale. arXiv:2510.20609.
11. GrepRAG (2026). ISSTA 2026.
12. Asai, A. et al. (2023). Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024. arXiv:2310.11511.
13. Wu, Y. et al. (2024). Repoformer: Selective Retrieval for Repository-Level Code Completion. ICML 2024. arXiv:2403.10059.
14. Jiang, Z. et al. (2023). Active Retrieval Augmented Generation (FLARE). EMNLP 2023. arXiv:2305.06983.
15. Jeong, S. et al. (2024). Adaptive-RAG. NAACL 2024.
16. Hong, J. et al. (2025). Context Rot. Chroma Research.
17. ContextBench (2025). arXiv:2602.05892.
18. AgentDiet (2025). Trajectory Optimization for Coding Agents.
19. Ackerman et al. (2025). Metacognition in LLMs. arXiv.
20. Tokenomics (2026). arXiv:2601.14470.
21. Liang, J. et al. (2025). SWE-Bench Illusion. arXiv:2506.12286.
22. Augment Code (2026). Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
23. Vasilopoulos, D. (2026). Codified Context. arXiv:2602.20478.
