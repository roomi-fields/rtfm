---
type: article
title: "R5) The Agent Calibrates Itself: Selective Retrieval Without Training"
subtitle: "We guide the agent toward the tool. But the agent decides how much to search — and calibrates intensity without fine-tuning, without a classifier, without a router."
excerpt: "The literature says systematic retrieval degrades performance. Our approach: guide the agent toward the tool with 3 lines of instructions, and let it calibrate intensity itself. The agent does selective retrieval naturally."
slug: selective-retrieval-autonomous-agent
focus_keyword: selective retrieval autonomous agent
tags:
  - selective-retrieval
  - self-rag
  - metacognition
  - autonomous-agent
  - tool-use
  - repoformer
  - adaptive-rag
---

> [!abstract]- SPEC
> ## Brief — R5: The agent calibrates itself
> ### Position in the series
> - **Series**: R (Retrieval) — Does Retrieval Help? | **Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]] through [[R4_Resultats_en|R4]]
> - Qualitative analysis of agent behavior
> - Connection with the adaptive retrieval literature
> ### Topics covered
> - Self-RAG, Repoformer, FLARE: systematic retrieval degrades
> - The observed usage pattern: surgical, not systematic
> - Light guidance + emergent intensity calibration
> - Tool universality: beyond code
> - Cost-quality trade-off: cost per resolved task
> ### SOTA sources
> - `paper/sota/04_adaptive_selective_retrieval.md`
> - `paper/sota/05_context_aware_retrieval_vs_exploration.md`

# R5) The agent calibrates itself

## Selective retrieval without training — or why three lines of instructions are enough

> The agent doesn't need to be told *how much* to search. It needs to be told *where* to search.

## Where does this article fit?

[[R4_Resultats_en|R4]] showed the raw numbers. RTFM lifts the resolve rate from 55-64% to 100% on test_validation (mlflow, 8,260 files), adds nothing on test_stub_generator (metaflow, 624 files), and doesn't compensate for the intrinsic complexity of test_responses_agent.

But numbers alone don't tell the whole story. There's a qualitative result, perhaps more important than the numbers: **the agent calibrates the intensity of its search to the task — without anyone prescribing it**. We tell it *to use* the tool. But it decides *how much*. And that behavior has deep implications.

---

## The trap of systematic retrieval

The literature on augmented retrieval has established a counterintuitive result: **searching all the time is worse than never searching**.

### Self-RAG: only retrieve when useful

Self-RAG (Asai et al., ICLR 2024) proposed a model that decides itself when to retrieve, via special "reflection tokens" learned during fine-tuning. The main result: adaptive retrieval beats systematic retrieval by **+40% relative** on PopQA. When you force the model to always search, it drowns in irrelevant context. When you let it choose, it searches only when it needs to.

### Repoformer: 70% of retrievals are waste

Repoformer (Wu et al., ICML 2024) measured the phenomenon specifically for code. Their classifier identified that **70% of code retrievals are useless** — the model would have produced the same result without them. By filtering these useless retrievals, they get a **70% speedup** with no performance loss.

Seventy percent. Seven out of ten retrievals serve no purpose.

### FLARE: the sweet spot is adaptive

FLARE (Jiang et al., EMNLP 2023) explored the space between "never retrieve" (θ=0) and "always retrieve" (θ=1). Both extremes are suboptimal. The sweet spot is somewhere in between — and it depends on context.

### Adaptive-RAG: route by complexity

Adaptive-RAG (Jeong et al., NAACL 2024) goes further: it classifies queries into three complexity levels (no retrieval / simple retrieval / multi-step retrieval) and routes each query to the appropriate pipeline. Question complexity determines retrieval intensity.

### The common thread

All these works converge on the same conclusion: **retrieval must be adaptive**. Neither always nor never. And to be adaptive, you need a *decision* mechanism: when to search, when not to.

The question is: what mechanism?

Self-RAG uses **fine-tuning** — special tokens trained into the model. Repoformer uses a separately trained **classifier**. Adaptive-RAG uses a **router** with a small classification model.

Our approach is radically simpler.

---

## Our approach: guide toward the tool, let it calibrate usage

We trained nothing. No fine-tuning, no classifier, no router. But — let's be honest — we didn't "just give the tool without saying anything" either.

### What we tell the agent

The tool is declared in the agent's MCP configuration. It appears in the list of available tools alongside `Read`, `Grep`, `Glob`, `Edit`, `Bash`. Nothing special so far.

But `rtfm init` also injects **three lines of instructions** into the project's `CLAUDE.md` file — the guidelines file the agent reads at the start of each session:

> *For any **exploratory search** (finding which files/modules/classes are relevant to a topic), use `rtfm_search` instead of Glob, find, ls, or broad Grep.*
>
> *This returns file paths + context metadata. Then continue normally — Read the files, Grep for exact patterns within them, Edit to modify.*

That's it. Three lines. No rule about *how much* to search, no threshold, no "if the repo has more than N files then search more" condition. The instruction says *what to use* for exploration. It doesn't say *when to stop*.

### What the agent does on its own

And that's where it gets interesting. With these three identical lines across all projects, the agent produces **radically different behaviors** depending on context.

On `test_validation` (mlflow, 8,260 files), the agent makes **2-3 `rtfm_search` calls** — at the start of the session, to locate the relevant modules. Then it switches to standard tools (`Read`, `Edit`) for the rest of the task. The 2-3 searches are enough to identify `validation.py`, `scorers.py`, and `data.py` — the three critical files the agent without retrieval can't find.

On `test_stub_generator` (metaflow, 624 files), the agent makes **1 `rtfm_search` call**. It sees the repo is small, that results don't tell it more than it can find directly. It doesn't come back.

On `test_responses_agent` (mlflow, 78K prompt, 15 interfaces), the agent makes **10-15 `rtfm_search` calls** — roughly one per interface. It uses the tool intensively because the task is massive and it needs to locate many files.

| Task                 | Repo     | Files | RTFM calls | Pattern                      |
| -------------------- | -------- | ----- | ---------- | ---------------------------- |
| test_stub_generator  | metaflow | 624   | 1-2        | Quick try, abandon           |
| test_validation      | mlflow   | 8,260 | 2-3        | Targeted early localization  |
| test_responses_agent | mlflow   | 8,260 | 10-15      | Intensive usage              |

The instruction is identical in all three cases. But the agent adjusts retrieval intensity to task complexity and repo size — **without any rule prescribing it**. What's emergent is the calibration, not the usage itself.

> **Sidebar: The difference between guiding and calibrating**
>
> Two decision levels must be distinguished. The first: *to use or not* the search tool. That's guided — CLAUDE.md instructions explicitly say to use it for exploration. The second: *how much* to use it, with what intensity, when to stop. That's emergent — nothing in the instructions prescribes 1 call rather than 15. And it's this second level that produces selective retrieval.

---

## Sufficient metacognition

This result is in tension with the literature on LLM metacognition. Ackerman et al. (2025) showed that model metacognitive capabilities are "limited in resolution and qualitatively different from human." LLMs don't finely know what they know and what they don't.

But our observations suggest a nuance: **LLMs don't need fine metacognition to do selective retrieval**. They need two much coarser capabilities:

1. **Detecting that something is missing.** "I have to implement a validation module, but I don't see any existing validation code in my context." That isn't fine metacognition — it's absence detection.

2. **Evaluating whether a tool might help.** "I have a search tool. My query is about validation in a big repo. The tool might help." That isn't sophisticated decision-making — it's pattern matching on tool availability.

The combination of these two coarse capabilities, with a tool that costs little context (~300 tokens per query), produces behavior that *resembles* adaptive retrieval — without the complex mechanism.

> **Sidebar: The metacognitive prosthesis revisited**
>
> In [[R1_Le_Goulot_de_Localisation_en|R1]] we described the search tool as a "metacognitive prosthesis." The idea was the agent can *check* cheaply what it doesn't know, without needing to *know* that it doesn't know. The results confirm this intuition: the agent doesn't "know" it's missing `scorers.py`. But it can search "validation scorers" and get the answer in 300 tokens. Verification cost is so low the "do I know?" question becomes moot.

---

## The cost-quality trade-off

One argument against retrieval is that it increases per-task cost. And that's true.

On test_validation:

| Condition     | Cost  | Resolved? | Cost per resolved task |
| ------------- | ----- | --------- | ---------------------- |
| B (Discovery) | $1.50 | No        | ∞ (never resolved)     |
| C (FTS)       | $2.42 | Yes       | **$2.42**              |
| D (FTS+Embed) | $1.33 | Yes       | **$1.33**              |

Config B costs less *per attempt*. But it never resolves the task. In practice, a developer who launches an agent unsuccessfully will re-run, maybe 2-3 times, then intervene manually. The real cost of "no retrieval" isn't $1.50 — it's $1.50 × N attempts + human intervention time.

Config D resolves on the first try for $1.33. **The relevant cost isn't cost per attempt — it's cost per *resolved* task.**

On test_stub_generator, the calculation is reversed:

| Condition | Cost  | Resolved? |
| --------- | ----- | --------- |
| B         | $1.07 | Yes       |
| C         | $1.30 | Yes       |
| D         | $1.44 | Yes       |

B resolves for less. RTFM overhead (+21% to +35%) is pure waste on a small repo. Hence the importance of *selective* retrieval: the agent should use RTFM intensively on large repos and ignore it on small ones. And that's precisely what it does — 1-2 calls on metaflow, 2-3 on mlflow.

---

## Beyond code: universality as strength

The results of this study concern code. But the RTFM philosophy ([[R2_RTFM_Outil_Agnostique_en|R2]]) is broader: it's a *knowledge* tool, not a *code* tool.

In a separate A/B test — an academic article writing task, not code — we measured RTFM's impact on a musicology corpus (Markdown documents, published articles, research notes). After 3 iterations of tool optimization:

| Metric   | Without RTFM             | RTFM v3                    |
| -------- | ------------------------ | -------------------------- |
| Duration | 8m16s                    | **6m58s** (-16%)           |
| Cost     | $22.61                   | **$11.14** (-51%)          |
| Quality  | 10 sections, 31K chars   | 14 sections, 38.5K chars   |

**-51% cost, -16% duration, and a more complete article.** On a documentation task, not code.

The tool replaces blind navigation where necessary — whether in a code repo or a research corpus — and leaves the rest alone. A `grep` in an 8,000-file repo is as blind as a `grep` in a 900-document Markdown corpus. The problem is the same. So is the solution.

---

## The lesson: guide lightly, let it calibrate

Let's recap what this series of observations teaches us.

**Self-RAG, Repoformer, FLARE** tell us that systematic retrieval is suboptimal. Adaptive retrieval is better. But their decision mechanisms (fine-tuning, classifiers, routers) are expensive to build and model-specific.

**Our approach** boils down to two elements: three lines of instructions in CLAUDE.md that point the agent toward the tool for exploration, and a cheap tool that costs ~300 tokens per call. No calibration machinery. No "if repo exceeds N files, search more" rule. The agent calibrates itself.

And it works. Not because the agent has sophisticated metacognition. But because:
- The tool is **oriented** (instructions say "use it for exploration").
- The tool is **cheap** (~300 tokens per query).
- The tool is **non-invasive** (no forced context, no automatic retrieval).
- The agent has sufficient **absence detection** capability ("I'm missing something").
- **Nothing prescribes intensity** — the agent calibrates itself between 1 and 15 calls.

This is perhaps the most actionable result of this study: **you don't need to build sophisticated adaptive retrieval mechanisms. It's enough to orient the agent toward a cheap tool and let it calibrate intensity.**

Current agents are smart enough to do selective retrieval — provided you show them the tool, don't force systematic use, and let them adjust.

---

## References

- **Asai, A. et al. (2023)** — Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024. arXiv:2310.11511.
- **Wu, Y. et al. (2024)** — Repoformer: Selective Retrieval for Repository-Level Code Completion. ICML 2024. arXiv:2403.10059.
- **Jiang, Z. et al. (2023)** — Active Retrieval Augmented Generation (FLARE). EMNLP 2023. arXiv:2305.06983.
- **Jeong, S. et al. (2024)** — Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity. NAACL 2024.
- **Ackerman et al. (2025)** — Metacognition in Large Language Models. arXiv.
- **Galimzyanov, F. et al. (2025)** — Practical Code RAG at Scale. arXiv:2510.20609.

---

## Glossary

- **Fine-tuning**: additional training of a language model on specialized data to modify its behavior.
- **Reflection token**: in Self-RAG, a special token learned during fine-tuning that encodes the decision to retrieve or not.
- **Adaptive/selective retrieval**: strategy where the system decides case-by-case whether to search an index, instead of always or never searching.
- **Router**: in Adaptive-RAG, a small model that classifies query complexity to pick the appropriate pipeline.
- **Tool use**: an LLM's ability to call external tools (files, API, databases) during generation.

---

## Links in the series

- [[R1_Le_Goulot_de_Localisation_en|R1]] — The localization bottleneck — the fundamental problem
- [[R2_RTFM_Outil_Agnostique_en|R2]] — RTFM: a knowledge tool that only touches what it must
- [[R3_Protocole_Experimental_en|R3]] — The protocol: 4 conditions, 11 tasks, same model
- [[R4_Resultats_en|R4]] — The results: when repo size changes everything
- **R5** (this article) — The agent calibrates itself: selective retrieval without training
- [[R6_Perspectives_en|R6]] — What it changes — and what remains to be proven

---

**Prerequisites**: [[R1_Le_Goulot_de_Localisation_en|R1]] through [[R4_Resultats_en|R4]]
**Reading time**: 13 min
**Tags**: #selective-retrieval #self-rag #metacognition #autonomous-agent #tool-use #adaptive-rag

---

*Next article: [[R6_Perspectives_en|R6]] — What it changes — and what remains to be proven*

---
