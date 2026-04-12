---
type: article
title: "R1) The Localization Bottleneck: Why AI Agents Spend More Time Searching Than Producing"
subtitle: "The limiting factor for AI agents isn't their intelligence — it's their ability to find the right information in a large corpus. Whether it's code, law, research, or finance."
excerpt: "AI agents don't produce, most of the time. They search. They fumble. As soon as the corpus exceeds a few hundred documents, they get lost. This problem affects every domain — code is just the one where we know how to measure it."
slug: localization-bottleneck-ai-agents
focus_keyword: AI agent localization
tags:
  - ai-agents
  - localization
  - retrieval
  - context
  - exploration
  - knowledge
  - large-corpora
---

> [!abstract]- SPEC
> ## Brief — R1: The localization bottleneck
> ### Position in the series
> - **Series**: R (Retrieval) — Does Retrieval Help? | **Prerequisites**: none
> - First article in the series: frames the fundamental problem
> - Universal framing (all domains), then zoom in on code as the measurement ground
> ### Topics covered
> - The universal problem: any serious AI user facing a large corpus
> - Concrete examples: researchers, lawyers, developers, financial analysts
> - Empirical evidence via coding agents (the most advanced literature)
> - The oracle gap, context rot, the metacognitive paradox
> - Localization as a cross-cutting bottleneck
> ### SOTA sources
> - `paper/sota/05_context_aware_retrieval_vs_exploration.md`
> - `paper/sota/06_localization_bottleneck.md`

# R1) The localization bottleneck

## Why AI agents spend more time searching than producing

> AI agents are everywhere. But what do they *really* do with their time?

## Where does this article fit?

This article opens a series of six pieces devoted to a simple question: **does an AI agent work better when given a search tool pre-indexed on its knowledge base?**

The question sounds obvious — *of course it does*. But no one has measured it rigorously. And the question concerns everyone — not just developers.

In this series, we document our approach: understanding the problem (this article), designing a tool ([[R2_RTFM_Outil_Agnostique_en|R2]]), building an experimental protocol ([[R3_Protocole_Experimental_en|R3]]), analyzing the results ([[R4_Resultats_en|R4]]), and drawing lessons from them ([[R5_Agent_Decide_Seul_en|R5]], [[R6_Perspectives_en|R6]]).

Let's start at the beginning: what problem do a developer, a lawyer, a researcher, and a financial analyst share when they use an AI agent?

---

## The universal problem: searching a large corpus

### It's not a code problem. It's a knowledge problem.

Picture a lawyer who asks an AI agent to draft an analysis on the taxation of real estate capital gains. The working corpus: the General Tax Code (3,000+ articles), the BOFiP (thousands of pages of doctrine), the case law of the Council of State, tax rulings, international conventions. The agent knows tax law *in general* — it has seen it in its training data. But does it know ruling No. 2024-12 published last March that changes the interpretation of article 150 VB? No. That information is in the firm's local corpus, not in training data.

What does the agent do? It drafts with what it knows — that is, with potentially outdated or incomplete knowledge. Or it searches. It navigates the files, opens documents, closes them, opens others. It fumbles.

Picture a particle physics researcher who asks an agent to synthesize the state of the art on the mass of the W boson. The corpus: 500 articles in their Zotero, their Obsidian notes, the appendices of their own thesis, CERN experimental data. The agent knows what the W boson is. But does it know that internal note ATLAS-CONF-2025-003 contradicts the 2022 CDF result? No. That's in the researcher's corpus.

Picture a financial analyst who asks an agent to model the impact of a rate hike on a portfolio. The corpus: quarterly reports from 200 companies, broker notes, Fed minutes, internal models. The agent knows financial theory. But does it know about the covenants clause in company X's March 2025 bond issue that changes the picture? No. That's in a PDF on the team's drive.

Picture a developer who asks an agent to implement a feature in a project of 8,000 files. The agent knows how to code. But does it know that `validation.py` depends on `scorers.py` which depends on `data.py` — three files scattered across different subdirectories? No. That's in the codebase, not in its memory.

**The problem is the same in every case**: the agent needs information that is in the local corpus, not in its training data. And it has no efficient way to find it.

### Why it's a problem *now*

This problem isn't new — search engines have existed for 30 years. What's new is the **scale of AI agent usage on specialized corpora**.

In 2024-2025, AI agents went from curiosity to daily work tool. Claude Code writes production code. Law firms use agents for legal research. Analysts use agents to synthesize reports. Researchers use agents for literature reviews.

And they all hit the same wall: **as soon as the corpus exceeds a few hundred documents, the agent gets lost**. It doesn't know what's in the corpus. It doesn't know *where* to search. It navigates blindly with rudimentary tools — `grep` and `find` for code, manual copy-paste for the rest.

---

## Evidence from code: the domain where we know how to measure

The problem is universal. But to *measure* it, you need a playing field with objective metrics. That's what code offers.

Why code? Because there are standardized benchmarks (SWE-bench, FeatureBench), binary metrics (the test passes or not), reproducible environments (Docker), and a growing literature that analyzes agent behavior. No other domain has this tooling.

Research results on coding agents are therefore the best *proxy* for understanding a problem that affects every domain.

### The agent that doesn't code

A trajectory study of agents on SWE-bench (Trajectory Study, 2025) analyzed thousands of runs. The finding: **38% of a coding agent's actions are exploration** — `grep`s, `find`s, file reads — not code writing. The agent searches. It fumbles. It opens files, closes them, opens others. And for agents that *fail*, the ratio goes even higher: they loop without finding what they're looking for.

Translate that number to the lawyer: 38% of their time with the agent is spent navigating corpus files instead of drafting analysis. To the researcher: 38% opening PDFs instead of synthesizing. To the developer: 38% running `grep`s instead of coding.

The same type of analysis reveals a staggering token ratio: between the most and least efficient agents, the ratio of tokens consumed is **52x** — fifty-two times more tokens to reach the same result, or to fail to reach it at all. Most of those tokens are exploration noise. Pure waste.

This phenomenon has a name in the literature: **the localization bottleneck**. Before *producing*, the agent must first *find* the relevant information. And that's where things get complicated.

---

## Localization is half the problem

PatchPilot (ICML 2025) quantified this bottleneck strikingly in the code domain. The authors decomposed coding agent improvement into components: locating the relevant code, generating the patch, validation. Result: **localization capability accounts for about 47% of the total improvement** of an agent. Nearly half.

Put another way: if you improve an agent's ability to *find* the right information, you improve its results almost as much as if you improved its ability to *use* that information. This result is measured on code, but the intuition is cross-cutting. The lawyer who immediately finds the right statute writes a better analysis than the one who fumbles for twenty minutes.

Agentless (Xia et al., 2024) showed that a hierarchical approach — first search for the right file, then the right section, then the right passage — works remarkably well. Their method achieves 77.7% recall at the file level. But at the line level? 50.8%. Finding the right *document* is relatively easy. Finding the right *passage* within it is twice as hard.

LocAgent (ACL 2025) confirms: by guiding the agent with a dependency graph, you reach 92.7% precision. And Navigation Paradox (2026) gave an agent a structured navigation tool exposed via MCP. Result: **+23.2 percentage points** of resolution. Just by giving the agent a navigation tool a bit smarter than `grep`.

---

## The oracle gap: evidence that context is the limiting factor

The most striking result comes from CodeRAG-Bench (Wang et al., NAACL 2025 Findings). The authors measured model performance in three conditions: without external context, with context retrieved by a standard search system (BM25), and with *perfect context* — an oracle that gives exactly the relevant documents.

| Condition                | StarCoder2-7B on HumanEval | GPT-4o on SWE-bench Lite |
| ------------------------ | -------------------------- | ------------------------ |
| No context               | 31.7%                      | 2.3%                     |
| With BM25                | 43.9%                      | 21.7%                    |
| **With oracle context**  | **94.5%**                  | **30.7%**                |

From 31.7% to 94.5%. Same model, same task. The only difference: the quality of the context provided.

The gap between the best current retrieval and the oracle is **9 to 50 percentage points** depending on the model and task. These are "free" performance points waiting to be picked up, simply by improving retrieval quality.

The conclusion is clear: **the limiting factor isn't the model, it's the context you give it.** This conclusion is demonstrated on code. But it applies to any domain where the agent must work on a specialized corpus. The lawyer with the right legal context produces a better analysis. The researcher with the right references produces a better synthesis. The model is the same — it's the context that makes the difference.

---

## Blind tools

How does an agent explore a corpus today?

For code: `grep`, `glob`, `find`, and `cat`. Terminal tools designed for humans in the 1970s.

For everything else — law, research, finance — it's often *worse*. The agent doesn't even have a search tool for the local corpus. It works with what you paste into the prompt: a few copy-pasted documents, a basic RAG that returns out-of-context chunks, or nothing at all.

These approaches have three fundamental problems:

**They're blind.** `grep` doesn't know the project structure. Basic RAG doesn't know document relationships. The agent searching for "real estate capital gains" in a legal corpus of 10,000 documents gets 300 results — it's no further along than before.

**They're context-expensive.** Every result is loaded into the agent's context window. And the literature shows that too much context *degrades* performance. Hong et al. (2025) demonstrated the phenomenon of **context rot**: beyond a certain threshold, adding context makes answer quality *drop*. Noise drowns signal. ContextBench (2025) adds that even when agents find the right context, only 50 to 70% of the information is actually retained — seeing isn't using.

**They don't know when to stop.** AgentDiet (2025) showed that **40 to 60% of exploration tokens are pure waste** — you can remove them from agent trajectories *without affecting the final result*. The agent explores, but a large chunk of that exploration is useless.

> **Sidebar: The lawyer and the developer have the same problem**
>
> A developer running `grep -r "validate" .` in an 8,000-file repo and getting 847 results is in exactly the same situation as a lawyer searching "exemption" across 3,000 CGI articles and getting 200 hits. The tool doesn't understand the *structure* of the corpus, the *relationships* between documents, or *contextual* relevance. It searches text in files. It's a 1970s tool used by a 2026 AI.

---

## The metacognitive paradox

There's a deeper problem still, and it's the one that most directly motivates our work. This problem is the same regardless of the domain.

**LLMs don't know what they don't know.**

Ackerman et al. (2025) studied the metacognitive capabilities of language models — their ability to assess what they know and what they're missing. The conclusion: these capabilities are "growing but limited in resolution, context-dependent, and qualitatively different from human."

It's an existential problem for any AI agent working on a specialized corpus:
- The developer: how can the agent know it should look for `scorers.py` if it doesn't know that file exists?
- The lawyer: how can the agent know that ruling No. 2024-12 changes the analysis if it has never seen that ruling?
- The researcher: how can the agent know that ATLAS-CONF-2025-003 contradicts CDF if that document is in the local corpus?
- The analyst: how can the agent know that the covenants clause changes the model if it's in a PDF it hasn't read?

In every case, **the agent doesn't know what it doesn't know**. It produces with what it has — training knowledge, potentially outdated or incomplete — instead of checking the local corpus.

Our intuition: **the agent doesn't need to *know* what it doesn't know. It needs a way to *check* at low cost.**

A search tool pre-indexed on the local corpus is exactly that: a **metacognitive prosthesis**. The agent can ask itself "does my corpus contain anything on scorer validation?" / "is there a recent ruling on 150 VB?" / "did ATLAS publish a contradictory note?" — and get an answer in a few hundred tokens instead of navigating for ten minutes.

The question isn't "does the agent know that it doesn't know?". It's "can the agent cheaply check what it doesn't know?". And if so, does that change the results?

---

## What the literature suggests — and doesn't prove

Let's recap what we know — keeping in mind these results are measured on code, but the mechanism is cross-cutting:

| Finding                          | Source                     | Implication                                                       |
| -------------------------------- | -------------------------- | ----------------------------------------------------------------- |
| 38% of actions = exploration    | Trajectory Study (2025)    | Exploration is the main cost item for an agent                    |
| Localization = 47% of total gain | PatchPilot (ICML 2025)     | Better locating ≈ better producing                                |
| Oracle gap = 9-50 pp             | CodeRAG-Bench (NAACL 2025) | Every point of retrieval = point of performance                   |
| 40-60% of tokens wasted          | AgentDiet (2025)           | Much exploration is useless                                       |
| Context rot                      | Hong et al. (2025)         | Too much context degrades performance                             |
| Seeing ≠ using                   | ContextBench (2025)        | Targeted minimal context > massive dump                           |
| LLMs ≠ fine metacognition        | Ackerman et al. (2025)     | The external tool as prosthesis                                   |
| MCP navigation = +23.2 pp        | Navigation Paradox (2026)  | A navigation tool helps the agent                                 |

Everything points in the same direction: giving a search tool to an AI agent working on a large corpus *should* improve its results.

But nobody has *proven* it in a controlled protocol on a standardized benchmark. The studies above show correlations, ablations, post-hoc analyses. They don't show the direct experiment: same agent, same task, same model — with and without a search tool.

That's what we did. We chose code as the measurement ground — because it's the only domain that offers standardized benchmarks with objective metrics. But the tool we built ([[R2_RTFM_Outil_Agnostique_en|R2]]) is agnostic: it indexes code, documentation, law, research, data — any structured textual corpus. And the lessons we draw from it ([[R5_Agent_Decide_Seul_en|R5]], [[R6_Perspectives_en|R6]]) apply to any domain.

The protocol is described in [[R3_Protocole_Experimental_en|R3]]. The results are in [[R4_Resultats_en|R4]].

---

## References

- **Trajectory Study (2025)** — Analysis of coding agent trajectories on SWE-bench. arXiv:2506.18824.
- **PatchPilot (2025)** — Decomposing coding agent gains: localization, generation, validation. ICML 2025. arXiv:2502.02747.
- **Xia, C.S. et al. (2024)** — Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489.
- **Chen, Y. et al. (2025)** — LocAgent: Graph-Guided LLM Agents for Code Localization. ACL 2025. arXiv:2503.09089.
- **Navigation Paradox (2026)** — CodeCompass MCP and the navigation paradox. arXiv:2602.20048.
- **Wang, Z. et al. (2024)** — CodeRAG-Bench: Can Retrieval Augment Code Generation? NAACL 2025 Findings. arXiv:2406.14497.
- **Hong, J. et al. (2025)** — Context Rot: Understanding the Impact of Context on Retrieval-Augmented Generation. Chroma Research.
- **ContextBench (2025)** — A Benchmark for Context Retrieval in Coding Agents. arXiv:2602.05892.
- **AgentDiet (2025)** — Trajectory Optimization for Coding Agents.
- **Ackerman et al. (2025)** — Metacognition in Large Language Models. arXiv.
- **Jimenez, C.E. et al. (2024)** — SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.

---

## Glossary

- **AI agent**: autonomous system that uses an LLM to accomplish complex tasks — writing, analysis, code, research.
- **Context rot**: degradation of LLM performance when the provided context exceeds a critical threshold — noise drowns signal.
- **Local corpus**: the set of documents specific to a project, a company, a researcher — as opposed to model training data.
- **Oracle gap**: performance difference between the best current retrieval and an oracle providing perfect context.
- **Localization bottleneck**: the fact that the ability to *find* the right information is often the limiting factor of an agent's performance, not its ability to *use* that information.
- **LLM**: *Large Language Model* (Claude, GPT, Gemini, etc.).
- **MCP**: *Model Context Protocol* — open standard from Anthropic for communication between AI agents and external tools.
- **Metacognition**: a system's ability to assess what it knows and what it's missing.
- **Metacognitive prosthesis**: an external tool letting an agent check what it doesn't know, compensating for the limits of its own metacognition.
- **RAG**: *Retrieval-Augmented Generation* — a technique that enriches an LLM's prompt with documents retrieved by a search engine.
- **Retrieval**: retrieving relevant information from an index — as opposed to sequential navigation.

---

## Links in the series

- **R1** (this article) — The localization bottleneck — the fundamental problem
- [[R2_RTFM_Outil_Agnostique_en|R2]] — RTFM: a knowledge tool that only touches what it must
- [[R3_Protocole_Experimental_en|R3]] — The protocol: 4 conditions, 11 tasks, same model
- [[R4_Resultats_en|R4]] — The results: when repo size changes everything
- [[R5_Agent_Decide_Seul_en|R5]] — The agent calibrates itself: selective retrieval without training
- [[R6_Perspectives_en|R6]] — What it changes — and what remains to be proven

---

**Prerequisites**: none
**Reading time**: 14 min
**Tags**: #ai-agents #localization #retrieval #context #exploration #knowledge #large-corpora

---

*Next article: [[R2_RTFM_Outil_Agnostique_en|R2]] — RTFM: a knowledge tool that only touches what it must*

---
