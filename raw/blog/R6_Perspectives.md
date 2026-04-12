---
type: article
title: "R6) What It Changes — and What Remains to Be Proven"
subtitle: "The 1,000-file rule, the limits of our study, and why the bar is so low in this field."
excerpt: "Deploy a retrieval tool on any project with more than 1,000 files. But don't take our word for it — here's exactly what we proved and what we didn't."
slug: perspectives-retrieval-coding-agents
focus_keyword: retrieval agents perspectives
tags:
  - perspectives
  - limits
  - recommendations
  - rigor
  - reproducibility
  - emse
  - conclusion
---

> [!abstract]- SPEC
> ## Brief — R6: Perspectives
> ### Position in the series
> - **Series**: R (Retrieval) — Does Retrieval Help? | **Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]] through [[R5_Agent_Decide_Seul_en|R5]]
> - Last article of the series: synthesis, limits, recommendations
> ### Topics covered
> - Practical recommendations (the 1,000-file rule)
> - Methodological limits (one model, one tool, 11 tasks)
> - The state of rigor in the field
> - Future work
> - Call for reproducibility

# R6) What it changes — and what remains to be proven

## The 1,000-file rule, the limits, and why the bar is so low

> This study's best contribution may not be its results — it's its protocol.

## Where does this article fit?

This series has traversed a complete arc: the problem ([[R1_Le_Goulot_de_Localisation_en|R1]]), the tool ([[R2_RTFM_Outil_Agnostique_en|R2]]), the protocol ([[R3_Protocole_Experimental_en|R3]]), the results ([[R4_Resultats_en|R4]]), and the behavioral analysis ([[R5_Agent_Decide_Seul_en|R5]]).

It's time to step back. What's established? What isn't? And above all: what does it change in practice?

---

## What is established

### 1. Retrieval transforms results on large repos

On test_validation (mlflow, 8,260 files), the resolve rate goes from 55-64% without retrieval to 100% with retrieval. It's a strong result: same task, same agent, same model — the only difference is access to a pre-indexed search tool.

The causal mechanism is identified: the agent without retrieval doesn't find cross-module dependencies (`validation.py` ↔ `scorers.py` ↔ `data.py`). The agent with retrieval locates them in 2-3 queries and implements a compatible module.

### 2. Retrieval is useless on small repos

On test_stub_generator (metaflow, 624 files), all 4 configs resolve the task. Retrieval is overhead without benefit: +23% time, +22% cost. The agent knows it intuitively — it barely uses the tool.

### 3. FTS is enough, embeddings add efficiency

Config C (FTS alone) and Config D (FTS+embeddings) resolve the same tasks. Embeddings reduce turns (-38%), cost (-45%), and file reads (-48%) — but don't change the binary outcome. FTS, via BM25, is a remarkably strong baseline for code search.

### 4. Retrieval doesn't compensate for intrinsic complexity

test_responses_agent (78K chars, 15 interfaces) isn't resolved by any config. Retrieval helps cover more interfaces (12/15 with embeddings vs 8/15 with FTS alone), but Sonnet 4.0 can't handle the task's complexity even with perfect context. Retrieval is necessary but not sufficient.

### 5. The agent does selective retrieval naturally

Without special instructions, the agent adjusts retrieval intensity to the task: 1-2 calls on a small repo, 2-3 on a simple large repo, 10-15 on a complex task. Adaptive retrieval emerges from tool availability, without fine-tuning or classifier.

---

## What is NOT established

### The size threshold

We have one point at 624 files (no gain) and one at 8,260 files (strong gain). The zone between 700 and 5,000 files is terra incognita. Runs on pydantic (771) and astropy (1,123) are in progress and will tell us if the threshold sits around 1,000, 2,000 or 5,000 files.

### Statistical significance

The results presented are single runs. We don't yet have N ≥ 3 repetitions per condition to compute confidence intervals and p-values. Coding agent variability is substantial — the same agent can succeed or fail on the same task depending on model stochastic choices.

### Generalization to other models

We tested a single model: Claude Sonnet 4.0. GPT-4, Gemini 2.5 Pro, Llama, or even Claude Opus might show different results. The metacognitive capability enabling selective retrieval could vary across models.

### Generalization to other tools

We tested a single tool: RTFM. Augment Context Engine, Sourcegraph Cody, or another retrieval tool might give different results. Is the metadata-first pattern crucial, or would any search tool do?

### Generalization to other languages

FeatureBench lite is Python-only. Does the localization bottleneck exist the same way in a Java, TypeScript, or Rust project? Language structure (modules, imports, types) could change the dynamics.

---

## Practical recommendations

Despite the limits, the results are clear enough for provisional recommendations.

### The 1,000-file rule

**Deploy a pre-indexed retrieval tool on any project with more than 1,000 files.** The initialization cost is negligible (10-78 seconds of parsing for FTS) and the potential benefit is substantial.

On projects with fewer than 600 files, retrieval overhead isn't justified. Direct navigation is enough.

Between 600 and 1,000: case by case, depending on project complexity.

### FTS first, embeddings later

FTS (BM25 via SQLite FTS5) is the strong baseline. It resolves the same tasks as FTS+embeddings, without the embeddings indexing cost (which can reach 90 minutes on a large repo). Start with FTS. Add embeddings if you need efficiency (fewer turns, lower cost per run).

### Don't force retrieval

Don't put an "ALWAYS use RTFM" instruction in the agent's prompt. The agent does selective retrieval naturally. Forcing systematic retrieval is counterproductive — that's exactly what Self-RAG and Repoformer demonstrated.

### Metadata-first

If you build or pick a retrieval tool, favor a pattern that returns metadata (title, path, score) rather than full content. Context rot is real. Fewer tokens in search results = more room for the code that matters.

---

## The elephant in the room: the rigor bar

One aspect of this study strikes us: **the rigor bar is incredibly low in this field.**

Augment Code claims "+80% performance" without publishing a protocol. Hundreds of companies claim their tools "improve developer productivity" without controlled data. Academic papers evaluate their tools on micro-tasks created by the authors themselves.

Our study isn't perfect. A single model, a single tool, 11 tasks, single runs. But we have:
- A **third-party** benchmark (FeatureBench, ICLR 2026) — not tasks we created.
- A **4-condition** protocol with an isolated variable.
- **Reproducible metrics** (resolve rate, F2P, cost, duration).
- Transparency about **limits** and missing data.

The fact that this minimal level of rigor is *exceptional* in the field of coding agent tools speaks volumes about the state of the field.

We don't claim to have definitively proven retrieval helps. We claim to have posed the right question, with the right protocol. Full results, with repetitions and statistical significance, will be submitted to *Empirical Software Engineering* (EMSE).

---

## Future work

### Short term (this study)

- Complete the 11 tasks × 4 conditions × N ≥ 3 repetitions matrix.
- Evaluate the intermediate repos (pydantic 771, astropy 1,123) to locate the threshold.
- Statistical tests (Wilcoxon signed-rank, confidence intervals).
- Qualitative analysis: on each task where C/D > B, which files did retrieval find that B didn't?

### Medium term

- Test with other models (GPT-4, Gemini, Opus, open-source models).
- Test with other retrieval tools (Augment, Cody) — if APIs allow.
- Extend to SWE-bench for comparability.
- Measure impact on non-Python tasks (FeatureBench full).

### Long term

- Study the retrieval × model interaction: do more powerful models benefit more or less from retrieval?
- Explore *proactive* retrieval: could the tool pre-load relevant context before the agent even searches?
- Measure impact in real conditions (not benchmark) on daily development tasks.

---

## What this series is really about

We started from a simple intuition: coding agents are limited by their ability to find the right context, not by their ability to write code. We built a tool to test that intuition. And the results confirm: **giving an agent a pre-indexed search tool transforms its performance on large projects.**

But the deepest lesson isn't technical. It's a lesson about *designing* tools for AI agents.

You don't need to force the agent. You don't need to modify its behavior. You don't need to build complex decision mechanisms. It's enough to **give it the choice** — an available, cheap, non-invasive tool — and it chooses well.

It's not a GPS dictating the route. It's a map the agent can consult when it wants. And this distinction — between the tool that commands and the tool that enables — makes all the difference.

---

## References

- **FeatureBench (2026)** — ICLR 2026. arXiv:2602.10975.
- **Jimenez, C.E. et al. (2024)** — SWE-bench. ICLR 2024. arXiv:2310.06770.
- **Asai, A. et al. (2023)** — Self-RAG. ICLR 2024. arXiv:2310.11511.
- **Wu, Y. et al. (2024)** — Repoformer. ICML 2024. arXiv:2403.10059.
- **Augment Code (2026)** — Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
- **Liang, J. et al. (2025)** — SWE-Bench Illusion. arXiv:2506.12286.
- **Tokenomics (2026)** — arXiv:2601.14470.

---

## Glossary

- **EMSE**: *Empirical Software Engineering* — Springer journal specialized in empirical software engineering studies. The submission target for the full academic version of this study.
- **Complete matrix**: the full set of 11 tasks × 4 conditions × N repetitions constituting the study's complete dataset.
- **P-value**: probability of observing the results (or more extreme) under the null hypothesis — a measure of statistical significance.
- **Reproducibility**: a third party's ability to reproduce the study's results with the same protocol.

---

## Links in the series

- [[R1_Le_Goulot_de_Localisation_en|R1]] — The localization bottleneck — the fundamental problem
- [[R2_RTFM_Outil_Agnostique_en|R2]] — RTFM: a knowledge tool that only touches what it must
- [[R3_Protocole_Experimental_en|R3]] — The protocol: 4 conditions, 11 tasks, same model
- [[R4_Resultats_en|R4]] — The results: when repo size changes everything
- [[R5_Agent_Decide_Seul_en|R5]] — The agent calibrates itself: selective retrieval without training
- **R6** (this article) — What it changes — and what remains to be proven

---

**Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]] through [[R5_Agent_Decide_Seul_en|R5]]
**Reading time**: 11 min
**Tags**: #perspectives #limits #recommendations #rigor #reproducibility #emse

---

*End of series R — Does Retrieval Help?*

*RTFM is open source: [github.com/roomi-fields/rtfm](https://github.com/roomi-fields/rtfm)*

---
