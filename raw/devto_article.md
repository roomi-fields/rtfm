---
title: "I benchmarked a retrieval tool for coding agents — here's when it actually helps"
published: true
description: "Controlled experiment on FeatureBench: retrieval lifts resolve rate from 55% to 100% on large repos, but adds overhead on small ones. Data inside."
tags: opensource, ai, python, mcp
cover_image: 
canonical_url: 
---

# I benchmarked a retrieval tool for coding agents — here's when it actually helps

Coding agents spend more time *finding* code than writing it.

A trajectory study of agents on SWE-bench (2025) shows that 38% of actions are exploration — `grep`, `find`, file reads. PatchPilot (ICML 2025) quantified this: localization capability accounts for roughly 47% of an agent's total improvement. In other words, helping the agent *find* the right code improves results almost as much as helping it *write* code.

I built [RTFM](https://github.com/roomi-fields/rtfm) — an open-source retrieval layer for AI agents — and ran a controlled benchmark to see if giving agents a search tool actually helps.

## The experiment

I used [FeatureBench](https://arxiv.org/abs/2602.10975) (ICLR 2026) — a benchmark where agents implement *new features* in real codebases. Unlike SWE-bench (bug fixes, known contamination issues), FeatureBench requires understanding project architecture before coding. The best published score is 11%.

**4 conditions, same agent (Claude Code + Sonnet 4.0), same Docker environment:**

| Condition | Description |
|---|---|
| **A — Standard** | Original prompt with file paths given |
| **B — Discovery** | File paths stripped — agent must find where to code |
| **C — Discovery + FTS** | Same as B, but agent has RTFM (full-text search) |
| **D — Discovery + FTS + Embeddings** | Same as B, with RTFM in hybrid mode |

The only variable between B and C/D is the presence of the search tool.

11 tasks, 4 repos ranging from 624 to 8,260 files.

## The headline result

**`test_validation` on mlflow (8,260 files)** — implementing a data validation module that interacts with three existing components scattered across the project:

| Condition | Tests passing | Resolved? |
|---|---|---|
| A — Standard (paths given) | 55% (6/11) | No |
| B — Discovery (no retrieval) | 64% (7/11) | No |
| C — Discovery + FTS | **100% (11/11)** | **Yes** |
| D — Discovery + FTS+Embed | **100% (11/11)** | **Yes** |

Even Config A fails — knowing *where* to code isn't enough. The agent must understand how modules interact. Retrieval surfaces those cross-module dependencies.

## The counter-example

**`test_stub_generator` on metaflow (624 files)** — all 4 configs resolve the task. RTFM adds 23% overhead. On small repos, `grep` is enough.

## FTS vs Embeddings

On the tasks where both resolve, embeddings don't change the *outcome* but change the *path*:

| Metric | FTS only | FTS + Embeddings |
|---|---|---|
| Agent turns | 81 | **50** (-38%) |
| Cost | $4.04 | **$2.23** (-45%) |
| File reads | 23 | **12** (-48%) |

The agent goes more directly to the right files. Lexical search is enough for capability — embeddings add efficiency.

## The 1,000-file rule

The preliminary boundary:

- **Under ~600 files**: `grep` works fine. Retrieval is overhead.
- **Above ~8,000 files**: retrieval transforms results. Without it, the agent loops through the tree and misses cross-module dependencies.
- **The middle zone** (1K-5K files): still being explored.

Practical recommendation: deploy a pre-indexed retrieval tool on any project over 1,000 files.

## How RTFM works

```bash
pip install rtfm-ai && cd your-project && rtfm init
```

That's it. It creates a `.rtfm/library.db` (single SQLite file), registers the MCP server, and installs auto-sync hooks.

The agent gets 13 MCP tools. The key pattern is **progressive disclosure**:

1. `rtfm_search("validation scorers")` → 5 results with file paths and scores (~300 tokens of metadata, no content)
2. Agent reads only the relevant files via its standard `Read` tool

Context grows only by what's actually useful. On real documentation tasks, this cuts tokens by 61% and cost by 51%.

**Not code-only.** 10 built-in parsers: Markdown, Python (AST), LaTeX, PDF, YAML, JSON, Shell, XML, HTML, plaintext. Add any format in ~50 lines of Python. Works for code, docs, specs, research notes — same tool.

**Knowledge graph.** Resolves `[[wikilinks]]` and Python imports as graph edges. Hub detection, orphan detection, centrality ranking.

**Obsidian integration.** `rtfm vault` indexes your vault and generates navigable `_rtfm/` navigation files.

## The most interesting result

The agent decides on its own when to search. No forced retrieval, no classifier. On small repos: 1-2 calls. On large repos: 10-15 calls. On medium repos: 2-3 targeted calls.

This is consistent with Self-RAG (ICLR 2024) showing that systematic retrieval degrades performance. The sweet spot is "search when necessary" — and current LLMs have enough metacognition to figure that out on their own, provided the tool costs little to use.

**You don't need to force retrieval. You just need to make it possible.**

## Limitations (honestly)

- Single model (Sonnet 4.0). Generalization unmeasured.
- 11 tasks, 4 repos. Small sample.
- Python only. FeatureBench covers Python projects.
- Single runs. Full matrix with repetitions is in progress.
- Retrieval is necessary but not sufficient — it resolves the localization bottleneck, not the model's capability bottleneck.

The full methodology paper is being submitted to *Empirical Software Engineering* (EMSE).

## Try it

```bash
pip install rtfm-ai
cd your-project
rtfm init
```

Works with Claude Code, Cursor, Codex — any MCP client.

[GitHub](https://github.com/roomi-fields/rtfm) | [PyPI](https://pypi.org/project/rtfm-ai/) | MIT licensed

---

*I'm Romi, 24 years in tech (18 at Airbus), now building AI tools for knowledge retrieval. Happy to answer questions and share raw benchmark data.*
