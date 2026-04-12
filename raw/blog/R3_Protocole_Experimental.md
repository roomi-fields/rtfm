---
type: article
title: "R3) The Protocol: 4 Conditions, 11 Tasks, Same Model"
subtitle: "How to isolate the 'retrieval' variable in a coding-agent experiment — and why FeatureBench is the right playground."
excerpt: "To measure the impact of retrieval, you need a protocol that isolates that single variable. 4 experimental conditions, 11 tasks, 4 repos of increasing size, one model. Here's how we did it."
slug: experimental-protocol-retrieval-agents
focus_keyword: experimental protocol coding agents
tags:
  - protocol
  - featurebench
  - benchmark
  - experimental-conditions
  - claude-code
  - discovery
  - methodology
---

> [!abstract]- SPEC
> ## Brief — R3: The experimental protocol
> ### Position in the series
> - **Series**: R (Retrieval) — Does Retrieval Help? | **Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]], [[R2_RTFM_Outil_Agnostique_en|R2]]
> - Describes the experimental protocol in detail
> - Justifies each methodological choice
> ### Topics covered
> - Why FeatureBench and not SWE-bench
> - The 4 conditions (A/B/C/D) and what they isolate
> - "Discovery" mode and prompt manipulation
> - Metrics collected
> - Index initialization costs
> - Agent and model used
> ### SOTA sources
> - `paper/sota/02_benchmarks_coding_agents.md`
> - `paper/benchmark_paper.md`

# R3) The protocol: 4 conditions, 11 tasks, same model

## How to isolate the "retrieval" variable in a coding-agent experiment

> Everyone claims their tool improves agents. Nobody proves it properly. We're trying.

## Where does this article fit?

[[R1_Le_Goulot_de_Localisation_en|R1]] set the diagnosis: localization is the bottleneck for coding agents. [[R2_RTFM_Outil_Agnostique_en|R2]] introduced the tool we propose as a solution: an agnostic, metadata-first retrieval tool.

The central question remains: **does it work?**

To answer, it isn't enough to run an agent with and without RTFM and compare results. You need a protocol that isolates the "retrieval" variable and controls for everything else. This article describes that protocol — and the methodological choices behind it.

---

## Why FeatureBench and not SWE-bench

Benchmark choice is the first methodological choice, and it isn't trivial.

### The SWE-bench problem

SWE-bench (Jimenez et al., ICLR 2024) is the reference benchmark for coding agents. 2,294 tasks drawn from real GitHub issues, across 12 Python repos. It's the standard. It's also a problematic benchmark.

SWE-Bench Illusion (Liang et al., 2025) showed that many SWE-bench tasks suffer from **contamination**: solutions are in git history, issue descriptions contain explicit hints, and some tasks resolve via pattern-matching on the diff rather than code understanding. The authors estimate that a significant proportion of "correct" resolutions don't demonstrate real understanding.

More fundamentally for our study, SWE-bench focuses on **bug fixing**. That's a specific type of task: the broken code already exists, you have to find and repair it. It isn't the same as *implementing a new feature* — which requires understanding the project's architecture, identifying extension points, and producing code compatible with the existing base.

### FeatureBench: feature implementation

FeatureBench (ICLR 2026) fills this gap. Instead of fixing bugs, tasks ask you to **implement new features** in real projects. It's harder — the best published score is 11%, compared to 74% on SWE-bench Verified — and more realistic.

Why FeatureBench is better suited to our study:

1. **Discovery required.** To implement a feature, you have to understand the architecture. Where to add the code? Which existing modules interact? What conventions to follow? These are exactly the questions a retrieval tool can answer.

2. **Less contaminated.** FeatureBench is more recent, solutions aren't in public git history at testing time.

3. **Projects of varied sizes.** The lite version includes repos from 624 to 8,260 files — exactly the range we need to test the size-threshold hypothesis.

4. **Reliable evaluation.** Each task has a dedicated test suite. Resolution is binary: tests pass or they don't. No subjective evaluation.

---

## The 4 repos and 11 tasks

We selected 11 tasks from the lite split (no GPU) of FeatureBench, spread across 4 repos of increasing size:

| Repo                   | Domain                | Indexed files  | Chunks   | Tasks |
| ---------------------- | --------------------- | -------------- | -------- | ----- |
| **metaflow** (Netflix) | ML orchestration      | 624            | ~5,060   | 1     |
| **pydantic**           | Data validation       | 771            | ~14,762  | 1     |
| **astropy**            | Astronomy             | 1,123          | ~41,231  | 2     |
| **mlflow**             | MLOps                 | 8,260          | 180,262  | 7     |

The distribution isn't uniform — 7 of 11 tasks are in mlflow. That's a FeatureBench bias (big repos generate more tasks), but it's also an advantage for our study: it's precisely on big repos that we expect a retrieval effect.

### Task diversity

Tasks cover a complexity spectrum:

- **test_stub_generator** (metaflow): implement a type stub generator — a well-scoped task, one file to create.
- **test_validation** (mlflow): implement a validation module that interacts with scorers and data — requires understanding cross-module dependencies.
- **test_responses_agent** (mlflow): implement 15 interfaces for a responses agent — the monster task, 78K characters of prompt.

---

## The 4 experimental conditions

The variable we isolate is simple: **does the agent have access to a pre-indexed search tool?**

To test it, we designed 4 configurations. Each varies a single parameter:

### Config A — Standard (semi-oracle control)

The original FeatureBench prompt, unmodified. This prompt contains the **file paths** to modify and the interfaces to implement:

```
Path: /testbed/mlflow/models/evaluation/validation.py
...implement the validate_data function...
```

The agent knows *where* to code. It's a semi-oracle condition — unrealistic, but useful as a positive control. If even with paths the agent fails, the task is too hard for the model (not a localization problem).

### Config B — Discovery (realistic baseline)

Same prompt as A, but we **remove the paths**. Concretely, we strip the `Path: /testbed/...` lines and replace "under the specified path" with "Explore the existing codebase to determine where".

How much of the prompt do we modify? **751 characters out of 78,036** — less than 1%. The rest is identical: feature description, expected interfaces, function signatures, docstrings. The agent has all the information except one: *where* to code.

This is the realistic condition. When a developer launches an agent on a Jira ticket, they don't give it the list of files to modify. They give it the description of what they want.

### Config C — Discovery + FTS

Same prompt as B, but the agent has access to RTFM with **full-text search** (BM25 via FTS5). The database is pre-built — as in real usage, where the tool is already initialized in the project.

### Config D — Discovery + FTS + Embeddings

Same prompt as B, with RTFM in **hybrid** mode: full-text search + semantic embeddings search.

### What changes and what doesn't

| Parameter              | A           | B           | C           | D             |
| ---------------------- | ----------- | ----------- | ----------- | ------------- |
| Prompt                 | Original    | Discovery   | Discovery   | Discovery     |
| Paths in prompt        | Yes         | **No**      | **No**      | **No**        |
| RTFM available         | No          | No          | **FTS**     | **FTS+Embed** |
| Agent                  | Claude Code | Claude Code | Claude Code | Claude Code   |
| Model                  | Sonnet 4.0  | Sonnet 4.0  | Sonnet 4.0  | Sonnet 4.0    |
| Timeout                | 1200s       | 1200s       | 1200s       | 1200s         |
| Environment            | Docker      | Docker      | Docker      | Docker        |

The only variable between B and C is the presence of the FTS tool. The only variable between C and D is the addition of embeddings. A is the semi-oracle control. B is the realistic baseline.

> **Sidebar: Why B is the real baseline**
>
> You might think A (standard prompt) is the natural baseline. But A gives the paths — it's a form of cheating. In realistic conditions, the agent doesn't know *where* to code. B is therefore the baseline matching the real-world use case. The experimental question is: **C/D > B?** — not C/D > A.

---

## The agent and the model

**Agent:** Claude Code (Anthropic). It's a production agent, not a research prototype. It has access to standard tools: `Read`, `Edit`, `Write`, `Grep`, `Glob`, `Bash`. In configs C and D, it additionally has access to RTFM's MCP tools.

**Model:** Claude Sonnet 4.0, fixed across all conditions. A single model guarantees that observed differences are due to the experimental variable (retrieval), not the model.

**Environment:** Docker (standard FeatureBench container). 1200-second timeout. Authentication via OAuth MAX.

### Why not multiple models?

It's a conscious limit. Testing with GPT-4, Gemini, or Llama would reinforce generalizability. But the cost of each run (compute + tokens) and the complexity of Docker setup make extension to N models prohibitive for a first study. We fix the model and vary retrieval. Generalization to other models is future work.

---

## Metrics

### Performance

- **Resolve rate**: the test passes or not. Binary, evaluated by `fb eval`. It's the main metric — no half-measures.
- **F2P pass rate**: fraction of fail-to-pass tests that pass. Gives partial credit — an agent that makes 7 of 11 tests pass is better than one that passes 0, even if neither "resolves" the task.

### Cost

- **Cost ($)**: via Claude Code's `total_cost_usd`.
- **Tokens**: input, output, cache read — to understand where the money goes.

### Time

- **Total duration**: wall-clock time, including RTFM setup.
- **Agent duration**: time excluding setup — the time the agent actually spends working.

### Behavior

- **Tool calls**: number and type (Read, Grep, Glob, Edit, Bash, rtfm_search, rtfm_expand...).
- **Exploration/coding ratio**: (Read + Grep + Glob + rtfm_search) / (Edit + Write). A high ratio = the agent spends more time searching than coding.

---

## RTFM initialization costs

In real usage, RTFM is initialized once per project (`rtfm init`). The indexing cost is amortized across all future sessions. It's not a "per-run" cost.

For transparency, here are the measured initialization costs:

| Repo     | Books | Chunks   | Parse + FTS | + Embeddings | DB FTS | DB FTS+Embed |
| -------- | ----- | -------- | ----------- | ------------ | ------ | ------------ |
| metaflow | 876   | ~5,060   | ~10s        | +161s        | 12 MB  | 22 MB        |
| pydantic | 771   | ~14,762  | ~15s        | +444s        | 18 MB  | 48 MB        |
| astropy  | 1,123 | ~41,231  | ~30s        | +1,232s      | 52 MB  | 133 MB       |
| mlflow   | 8,260 | 180,262  | 78s         | +5,368s      | 234 MB | 592 MB       |

Parsing + FTS is fast: 10 to 78 seconds. Embeddings are expensive: throughput is constant at ~33 chunks/second on CPU, giving ~90 minutes for mlflow. That's an argument for Config C (FTS only) for lightweight use.

### Per-run setup

With pre-built DBs (realistic condition), per-run setup is minimal:

| Step            | Config C (FTS) | Config D (FTS+Embed) |
| --------------- | -------------- | -------------------- |
| Install RTFM    | ~18s           | ~30s                 |
| DB copy         | ~1s            | ~1s                  |
| Warm FastEmbed  | N/A            | ~17s                 |
| **Total setup** | **~20s**       | **~50s**             |

20 to 50 seconds of setup — on a 7- to 12-minute run. The overhead is modest.

---

## Statistical significance

This is the trickiest point. Coding agent runs are expensive ($1-5 per run, 5-20 minutes per run), and results are stochastic — the same agent on the same task can succeed or fail depending on model choices.

Our goal is N ≥ 3 repetitions per condition. With 11 tasks × 4 conditions × 3 repetitions = 132 runs. At 10 minutes and ~$2 on average, that's ~22 hours of compute and ~$264 of tokens.

For statistical tests, we plan:
- **Wilcoxon signed-rank** for paired comparisons (B vs C, B vs D) if N is sufficient.
- **Permutation test** if N is small.
- **95% confidence intervals** on resolution rates.

Preliminary results (single runs) are presented in [[R4_Resultats_en|R4]]. The complete matrix is in progress.

---

## Protocol recap

```
                    ┌──────────┐
                    │ 11 tasks │
                    │ 4 repos  │
                    └────┬─────┘
                         │
         ┌───────┬───────┼───────┬───────┐
         │       │       │       │       │
    ┌────▼───┐ ┌─▼──┐ ┌──▼──┐ ┌─▼───┐
    │Config A│ │ B  │ │  C  │ │  D  │
    │Standard│ │Disc│ │ FTS │ │Embed│
    │(oracle)│ │    │ │     │ │     │
    └────┬───┘ └─┬──┘ └──┬──┘ └─┬───┘
         │       │       │       │
         │  Same agent (Claude Code)
         │  Same model (Sonnet 4.0)
         │  Same env (Docker, 1200s)
         │       │       │       │
    ┌────▼───────▼───────▼───────▼───┐
    │  Metrics: resolve, F2P,        │
    │  cost, duration, tool calls,   │
    │  exploration/coding ratio      │
    └────────────────────────────────┘
```

The question: **do C and D beat B on large repos?**

The results are in [[R4_Resultats_en|R4]].

---

## References

- **Jimenez, C.E. et al. (2024)** — SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.
- **FeatureBench (2026)** — ICLR 2026. arXiv:2602.10975.
- **Liang, J. et al. (2025)** — SWE-Bench Illusion. arXiv:2506.12286.
- **Tokenomics (2026)** — arXiv:2601.14470.
- **UTBoost (2025)** — ACL 2025. arXiv:2506.09289.

---

## Glossary

- **Config A/B/C/D**: the 4 experimental conditions of our study. A = standard prompt (paths given), B = discovery (paths removed), C = discovery + FTS, D = discovery + FTS + embeddings.
- **Discovery mode**: mode where file paths are removed from the prompt, forcing the agent to locate relevant files itself.
- **FeatureBench**: coding-agent benchmark focused on implementing new features (not fixing bugs). ICLR 2026.
- **F2P**: *fail-to-pass* — tests that failed before the agent's intervention and pass after.
- **OAuth MAX**: authentication mode for Claude Code using the Anthropic account directly (no API key).
- **Lite split**: FeatureBench subset not requiring a GPU, with tasks of moderate difficulty.
- **SWE-bench**: reference benchmark for coding agents based on real GitHub issues. ICLR 2024.
- **Wilcoxon signed-rank**: non-parametric statistical test to compare two paired conditions.

---

## Links in the series

- [[R1_Le_Goulot_de_Localisation_en|R1]] — The localization bottleneck — the fundamental problem
- [[R2_RTFM_Outil_Agnostique_en|R2]] — RTFM: a knowledge tool that only touches what it must
- **R3** (this article) — The protocol: 4 conditions, 11 tasks, same model
- [[R4_Resultats_en|R4]] — The results: when repo size changes everything
- [[R5_Agent_Decide_Seul_en|R5]] — The agent calibrates itself: selective retrieval without training
- [[R6_Perspectives_en|R6]] — What it changes — and what remains to be proven

---

**Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]], [[R2_RTFM_Outil_Agnostique_en|R2]]
**Reading time**: 12 min
**Tags**: #protocol #featurebench #benchmark #experimental-conditions #methodology

---

*Next article: [[R4_Resultats_en|R4]] — The results: when repo size changes everything*

---
