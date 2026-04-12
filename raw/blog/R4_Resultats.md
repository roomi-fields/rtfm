---
type: article
title: "R4) The Results: When Repo Size Changes Everything"
subtitle: "On mlflow (8,260 files), retrieval lifts the resolve rate from 55% to 100%. On metaflow (624 files), nothing changes. The size threshold exists."
excerpt: "The results of our controlled study. Retrieval transforms performance on large repos — and is useless on small ones. Data, tables, failure analysis."
slug: retrieval-results-coding-agents
focus_keyword: retrieval results coding agents
tags:
  - results
  - benchmark
  - resolve-rate
  - mlflow
  - metaflow
  - fts
  - embeddings
  - size-threshold
---

> [!abstract]- SPEC
> ## Brief — R4: The results
> ### Position in the series
> - **Series**: R (Retrieval) — Does Retrieval Help? | **Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]], [[R2_RTFM_Outil_Agnostique_en|R2]], [[R3_Protocole_Experimental_en|R3]]
> - Heart of the series: the experimental data
> - Preliminary results (complete matrix in progress)
> ### Topics covered
> - Main result: test_validation (mlflow, 8260 files)
> - Counter-example: test_stub_generator (metaflow, 624 files)
> - FTS vs FTS+Embeddings: the surprise
> - Failure analysis: test_responses_agent
> - Cost and duration per condition
> - Tool usage by the agent
> ### SOTA sources
> - `paper/benchmark_paper.md`

# R4) The results: when repo size changes everything

## On mlflow, retrieval lifts resolution from 55% to 100%. On metaflow, nothing changes.

> The answer isn't "yes" or "no". It's "it depends on size."

## Where does this article fit?

[[R1_Le_Goulot_de_Localisation_en|R1]] framed the problem. [[R2_RTFM_Outil_Agnostique_en|R2]] introduced the tool. [[R3_Protocole_Experimental_en|R3]] described the protocol. Here are the results.

**Important caveat:** the results presented here are preliminary. They come from single runs (no repetitions yet, N ≥ 3). The complete matrix (11 tasks × 4 conditions × N repetitions) is in progress. Conclusions are *trends*, not yet statistical proof. Transparency about this limit is a requirement we impose on ourselves — unlike the "+80%" without protocol that the industry publishes without blushing.

---

## The main result: test_validation on mlflow

### The context

`test_validation` asks you to implement a data validation module in mlflow — a **8,260-file project**. The difficulty: the module must interact with three existing components scattered across the project: `validation.py`, `scorers.py`, and `data.py`. These files are in different subdirectories. To succeed, the agent must find these cross-module dependencies.

11 tests must pass. If even one fails, the task isn't "resolved."

### The results

| Condition                         | F2P (fail-to-pass) | Resolved? | Duration | Cost  |
| --------------------------------- | ------------------ | --------- | -------- | ----- |
| A — Standard (paths given)        | 6/11 (55%)         | No        | 479s     | $1.12 |
| B — Discovery (no retrieval)      | 7/11 (64%)         | No        | 459s     | $1.50 |
| C — Discovery + FTS               | **11/11 (100%)**   | **Yes**   | 732s     | $2.42 |
| D — Discovery + FTS+Embed         | **11/11 (100%)**   | **Yes**   | 605s     | $1.33 |

The result is clear. **With retrieval (C and D), 100% of tests pass. Without retrieval (A and B), between 55% and 64%.**

And note the detail that shifts perspective: **Config A, the one where paths are *given in the prompt*, does not resolve the task**. The agent has the paths. It knows *where* to code. And it still fails on 5 tests. Knowing *where* to code isn't enough — you also have to understand *how* the modules interact. That's exactly what retrieval provides: a search for "validation scorers" returns the relevant files *and their architectural context*.

### Why A and B fail

The 4-5 tests that fail in A and B are always the same: `test_validate_scorers_invalid_all_scorers`, `test_validate_data_with_correctness`, `test_validate_data_missing_columns`. All involve interactions between the validation module and distant modules — the scorers, the data structures.

The agent without retrieval implements the validation module *in isolation*. The code is syntactically correct, the types are good, the local logic is consistent. But the implementation is *incompatible* with the rest of the project because the agent hasn't seen the code of neighboring modules.

The agent with retrieval makes a `rtfm_search("validation scorers")` at the start of the session. It gets the coordinates of `scorers.py` and `data.py`. It reads them. It understands the existing interfaces. And it implements a *compatible* validation module.

---

## The counter-example: test_stub_generator on metaflow

### The context

`test_stub_generator` asks you to implement a type stub generator in metaflow — a **624-file repo**. It's a well-scoped task: a single file to create, clear interfaces.

31 tests must pass.

### The results

| Condition                  | F2P           | Resolved?         | Duration | Cost  |
| -------------------------- | ------------- | ----------------- | -------- | ----- |
| A — Standard               | 31/31 (100%)  | **Yes**           | 370s     | $0.97 |
| B — Discovery              | 31/31 (100%)  | **Yes**           | 395s     | $1.07 |
| C — Discovery + FTS        | 31/31 (100%)  | **Yes**           | 454s     | $1.30 |
| D — Discovery + FTS+Embed  | 30/31 (96.8%) | No (1 test miss)  | 541s     | $1.44 |

**Everyone resolves** (except D, which misses one test out of 31 — an artifact, not a signal).

But RTFM is *counterproductive* in terms of cost and duration:
- Config C is **23% slower** and **22% more expensive** than A.
- Config D is **46% slower** and **48% more expensive** than A.

The RTFM agent barely uses the tool: only 1-2 calls. It navigates directly in the repo with `grep` and `Read` — because the repo is small enough for that to work.

### The conclusion

**On a 624-file repo, `grep` is enough.** The localization bottleneck doesn't exist. RTFM is overhead without benefit. The agent knows it intuitively — it makes 1-2 RTFM calls then returns to standard tools.

---

## Cross-analysis: the size threshold

Juxtaposing the two results:

| Repo     | Files | Retrieval gain (resolve rate)  | Retrieval gain (cost)          |
| -------- | ----- | ------------------------------ | ------------------------------ |
| metaflow | 624   | 0% (B=C=D=100%)                | **-23% to -48%** (overhead)    |
| mlflow   | 8,260 | **+36 to +45 pp** (B→C/D)      | N/A (B doesn't resolve)        |

The pattern is clear: **retrieval only helps when the repo is big enough that direct navigation is a bottleneck.**

The data for pydantic (771 files) and astropy (1,123 files) — the intermediate repos — are in progress. They'll tell us where the threshold lies. Our hypothesis: somewhere around 1,000 to 2,000 files.

---

## FTS vs FTS+Embeddings: the surprise

Comparing Config C (FTS alone) and Config D (FTS + embeddings) on test_validation reveals a result that confirms recent literature.

### The resolve rate is identical

Both C and D resolve at 100%. Embeddings don't change the *result*. On this task, BM25 is enough to find the relevant files.

### But efficiency differs significantly

| Metric     | Config C (FTS) | Config D (FTS+Embed) | Delta    |
| ---------- | -------------- | -------------------- | -------- |
| Turns      | 81             | **50**               | **-38%** |
| Cost       | $4.04          | **$2.23**            | **-45%** |
| Read calls | 23             | **12**               | **-48%** |
| Bash calls | 20             | **9**                | **-55%** |
| Grep calls | 7              | 13                   | +86%     |

The agent with embeddings goes *more directly* to the right files. It reads fewer files (12 vs 23), runs less Bash (9 vs 20 — less debug), and finishes in fewer turns (50 vs 81). It runs more Grep — but targeted Greps in files it has already identified as relevant.

The result is consistent with Galimzyanov (2025) and GrepRAG (ISSTA 2026): BM25 is competitive with dense embeddings for code search. Lexical search is enough to find the files. Embeddings add a layer of *efficiency* — the right file appears higher in results, the agent fumbles less — but no additional *capability*.

> **Sidebar: Practical implications**
>
> Config C (FTS alone) has a ~20-second setup and a 10-78 second indexing cost. Config D (FTS+Embed) has a ~50-second setup and a 10-90 *minute* indexing cost for large repos. If FTS is enough to resolve the same tasks, cost/benefit favors FTS for a quick deployment. Embeddings are worth it for long-term efficiency, not for raw outcome.

---

## Failure analysis: test_responses_agent

### The extreme use case

`test_responses_agent` is the most complex task in the benchmark: **78,000 characters** of prompt, **15 interfaces** to implement, a ground truth of 226,000 characters across 60 files.

Result: **no configuration resolves the task**. Neither A, nor B, nor C, nor D.

| Metric               | A (Standard)   | B (Discovery) | C (FTS)   | D (Embed+) |
| -------------------- | -------------- | ------------- | --------- | ---------- |
| Resolved             | No (3.5% F2P)  | No (TIMEOUT)  | No (0%)   | No (0%)    |
| Interfaces covered   | 15/15          | 0/15          | 8/15      | 12/15      |
| Patch size           | 92K chars      | 0 (timeout)   | 51K chars | 91K chars  |
| Cache read           | 23.8M          | 18.9M         | 8.7M      | 9.0M       |

### What this teaches us

**Config B times out.** Without paths AND without retrieval, the agent is lost in 8,260 files. It explores for 1,200 seconds without producing code. The localization bottleneck in its purest form.

**Config A covers all 15 interfaces but still fails.** The agent had the paths. It modified all 15 files. But tests fail (3.5% F2P). It isn't a localization problem — it's a problem of *model capability*. 15 simultaneous interfaces exceed what Sonnet 4.0 can handle coherently.

**Config D covers 12/15 interfaces, Config C only 8/15.** Embeddings guide better — the agent identifies more relevant files. But even 12/15 isn't enough.

**Configs C and D consume 2-3x less cache read** (8-9M vs 19-24M tokens). The metadata-first pattern works: the agent loads less context. But the context gain doesn't compensate for the task's intrinsic complexity.

### The diagnosis

Config C's failure is revealing. The agent said: *"Due to space constraints, let me focus on the most critical interfaces"* — and abandoned the 8 most complex interfaces. The model *knows* it can't do everything. It makes a rational choice — but an incomplete one.

Config D's failure is different. The agent covered 12 interfaces — embeddings guided it better. But a series of 4 successive `Edit`s on `responses.py` corrupted the file: a `continue` turned into `continue(chunks:...` → immediate SyntaxError. An edit bug, not a retrieval bug.

**Retrieval is necessary but not sufficient.** It resolves the localization bottleneck. It doesn't resolve the model-capability bottleneck.

---

## Tool usage analysis

How does the agent use its tools in each condition? Here's the breakdown for test_validation (mlflow):

| Tool        | B (Discovery) | C (FTS) | D (Embed+) |
| ----------- | ------------- | ------- | ---------- |
| Grep        | 6             | 7       | 13         |
| Read        | 13            | 23      | 12         |
| Edit        | 6             | 12      | 5          |
| Bash        | 22            | 20      | 9          |
| Glob        | 0             | 7       | 1          |
| RTFM search | 0             | 3       | 2          |
| RTFM expand | 0             | 2       | 0          |
| **Total**   | 53            | 81      | 50         |

Three observations:

**1. Config D runs less Bash.** 9 Bash calls vs 22 in B and 20 in C. Bash is mainly debug — executing code to see if it works, fixing, re-running. The agent with embeddings writes correct code on the first try more often, because it found the right files from the start.

**2. Config C reads more files.** 23 Reads vs 12 in D and 13 in B. Without embeddings, FTS returns relevant but not optimally ordered results — the agent reads more files to find the right one. Embeddings refine ranking.

**3. The RTFM agent barely uses RTFM.** 2-3 search calls, 0-2 expands. It's not a tool it hammers — it's a tool it uses *surgically*, at the right moment. That's the subject of [[R5_Agent_Decide_Seul_en|R5]].

---

## Synthesis: what's established and what isn't

### Established (current data)

- On test_validation (mlflow, 8,260 files): retrieval transforms the result (55-64% → 100%).
- On test_stub_generator (metaflow, 624 files): retrieval adds nothing.
- FTS alone resolves as much as FTS+embeddings. Embeddings add efficiency (-38% turns, -45% cost).
- Retrieval doesn't compensate for intrinsic complexity (test_responses_agent).
- The metadata-first pattern reduces context consumption (2-3x less cache read).

### Pending confirmation

- The exact size threshold (pydantic and astropy data in progress).
- Generalizability to other mlflow tasks (7 tasks, not all evaluated in 4 conditions yet).
- Statistical significance (N ≥ 3 repetitions not yet reached).
- The repo-size × retrieval-gain correlation.
- The cost per *resolved* task (requires more data).

---

## References

- **FeatureBench (2026)** — ICLR 2026. arXiv:2602.10975.
- **Galimzyanov, F. et al. (2025)** — Practical Code RAG at Scale. arXiv:2510.20609.
- **GrepRAG (2026)** — ISSTA 2026.
- **PatchPilot (2025)** — ICML 2025. arXiv:2502.02747.

---

## Glossary

- **Cache read**: tokens already present in the model's cache during a multi-turn conversation — cheaper than fresh tokens.
- **Cross-module**: interaction between components located in different files/directories of the project.
- **F2P**: *fail-to-pass* — tests that failed before and pass after the agent's intervention.
- **Overhead**: extra cost (time, money, tokens) induced by using a tool.
- **Resolve rate**: proportion of tasks fully resolved (all tests pass).

---

## Links in the series

- [[R1_Le_Goulot_de_Localisation_en|R1]] — The localization bottleneck — the fundamental problem
- [[R2_RTFM_Outil_Agnostique_en|R2]] — RTFM: a knowledge tool that only touches what it must
- [[R3_Protocole_Experimental_en|R3]] — The protocol: 4 conditions, 11 tasks, same model
- **R4** (this article) — The results: when repo size changes everything
- [[R5_Agent_Decide_Seul_en|R5]] — The agent calibrates itself: selective retrieval without training
- [[R6_Perspectives_en|R6]] — What it changes — and what remains to be proven

---

**Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]], [[R2_RTFM_Outil_Agnostique_en|R2]], [[R3_Protocole_Experimental_en|R3]]
**Reading time**: 15 min
**Tags**: #results #benchmark #resolve-rate #mlflow #metaflow #fts #embeddings #size-threshold

---

*Next article: [[R5_Agent_Decide_Seul_en|R5]] — The agent calibrates itself: selective retrieval without training*

---
