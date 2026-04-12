# SOTA 6 — The Localization Bottleneck

*Angle: the primary failure mode of coding agents is NOT code generation, but finding the right files/functions to modify.*

---

## 1. The foundational evidence: SWE-bench oracle experiments

### 1.1 SWE-bench: Can Language Models Resolve Real-World GitHub Issues?
- **Authors:** Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan
- **Year/Venue:** 2024, ICLR 2024
- **Ref:** arXiv:2310.06770
- **Key results:**
  - With "oracle" retrieval (the exact patched files given to the model), Claude 2 reaches only **4.8%** — perfect localization is necessary but not sufficient.
  - When files are reduced to **edited lines only** (+/-15 lines), GPT-4 goes from **1.3% to 3.4%**, Claude 2 from **4.8% to 5.9%**.
  - Increasing the BM25 context (more files) **decreases** performance.
  - **Key quote:** "Models become distracted by additional context and sensitive to the relative location of target sequences."
- **Relevance:** Too many files hurt. Surgical retrieval (exactly what RTFM does) directly improves outcomes.
- **URL:** https://arxiv.org/abs/2310.06770

---

## 2. Agentless & Hierarchical Localization

### 2.1 Agentless: Demystifying LLM-based Software Engineering Agents
- **Authors:** Xia, Deng, Dunn, Zhang
- **Year/Venue:** 2024, arXiv (NeurIPS 2024 / ACM SIGSOFT)
- **Ref:** arXiv:2407.01489
- **Key results:**
  - Hierarchical localization: file → class/function → edit line.
  - **File: 77.7%** → **Class/function: 55.3%** → **Line: 50.8%**
  - Localization = **$0.09** per issue (26% of the total $0.34 cost).
  - 27.33% (82/300) on SWE-bench Lite.
  - **The 77.7% → 50.8% degradation shows that each localization level is a potential failure point.** Nearly half of failures come from localization, not generation.
- **Relevance:** A pre-built index (such as RTFM) could replace the file level at near-zero cost vs. $0.09/query.
- **URL:** https://arxiv.org/abs/2407.01489

---

## 3. Trajectory analysis: how agents spend their time

### 3.1 Understanding Software Engineering Agents: A Study of Thought-Action-Result Trajectories
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.18824
- **Key results:**
  - 120 trajectories, 2,822 LLM interactions (RepairAgent, AutoCodeRover, OpenHands).
  - **Action distribution:** Generate Fix (23%), Run Tests (20%), Explain (20%), **Explore (18%)**.
  - **Token consumption:**
    - AutoCodeRover: **23K tokens** (structured search-locate-fix workflow)
    - RepairAgent: **220K tokens**
    - OpenHands: **1.2M tokens** — **52x more than AutoCodeRover**
  - AutoCodeRover spends **the first 50% of its trajectory on Search, Locate, Explain** before moving to the fix.
  - **Failed trajectories** exhibit "non-adaptive repetitive cycles" — agents stuck in exploration loops.
  - RepairAgent: failed cases = **40 iterations vs. 22 for successes**.
- **Relevance:** ~38% of all actions are finding/understanding, not writing. A retrieval tool that front-loads this information eliminates a large share of wasted tokens.
- **URL:** https://arxiv.org/abs/2506.18824

---

## 4. Localization-specific benchmarks

### 4.1 LocAgent: Graph-Guided LLM Agents for Code Localization
- **Authors:** Chen, Tang, Deng, Wu, Wu, Jiang, Prasanna, Cohan, Wang
- **Year/Venue:** 2025, ACL 2025
- **Ref:** arXiv:2503.09089
- **Results:**
  - File-level on SWE-bench Lite: **Acc@1: 75.91%, Acc@3: 90.51%, Acc@5: 92.70%** (Qwen2.5-32B fine-tuned).
  - Function-level: **Acc@5: 71.90%, Acc@10: 77.01%**.
  - Better localization → **+12% Pass@10** in resolution.
  - **86% cost reduction** vs. Claude 3.5 ($0.09 vs. $0.66).
  - Uses dependency graphs (AST → heterogeneous directed graphs).
- **Relevance:** Structured/graph search for localization drastically outperforms brute-force exploration.
- **URL:** https://arxiv.org/abs/2503.09089

### 4.2 MULocBench: A Benchmark for Localizing Code and Non-Code Issues
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.25242
- **Results:**
  - 1,100 issues, 46 Python repos — more diverse than SWE-bench.
  - **Even at file level, the best methods are < 40%** (Acc@5, F1):
    - LocAgent + Claude 3.5: **35.2% Acc@5, 38.1% F1**
    - OpenHands + Claude 3.5: **33.5% Acc@5**
  - **Enhancement requests** are the hardest to localize (~30% max).
  - SWE-bench overestimates localization capabilities (memorized repos).
- **Relevance:** On genuinely new repos (not in training data), localization is even harder. Pre-indexed retrieval tools become essential.
- **URL:** https://arxiv.org/abs/2509.25242

### 4.3 CoSIL: Issue Localization via LLM-Driven Code Graph Searching
- **Authors:** Jiang et al.
- **Year/Venue:** 2025, ASE 2025
- **Ref:** arXiv:2503.22424
- **Results:**
  - Top-1 localization: **43.3% (SWE-bench Lite), 44.6% (SWE-bench Verified)** with Qwen2.5-Coder-32B.
  - **+96% improvement** over the previous state of the art.
  - Training-free and indexing-free.
- **URL:** https://arxiv.org/abs/2503.22424

---

## 5. The navigation paradox: more context ≠ better

### 5.1 The Navigation Paradox in Large-Context Agentic Coding
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2602.20048
- **Key results:**
  - **Larger context windows shift the failure mode from retrieval capacity to navigational salience.** The model does not fail from lack of tokens — it fails because it never discovers the relevant file.
  - CodeCompass (AST-graph navigation MCP tool): **+23.2 pp** on hidden dependencies (99.4% vs. 76.2% vanilla).
  - BM25 helps on semantic tasks but **zero benefit** on architecturally hidden dependencies.
  - **The right tool depends on the task type:** semantic → retrieval (100%), hidden dependencies → graph navigation.
  - 58% of trials where the navigation tool was available but unused = 80.2% ACS (baseline) — **agents must be prompted to use navigation tools**.
  - **Key quote:** "When architecturally critical but semantically distant files are absent from the model's attention, errors may occur that additional context budget alone is unlikely to resolve."
- **Relevance:** Directly validates the value of retrieval tools via MCP. Semantic search and structural navigation cover different failure modes — RTFM's hybrid FTS+embeddings covers both.
- **URL:** https://arxiv.org/abs/2602.20048

---

## 6. Context Rot: why exploration fills context with noise

### 6.1 Context Rot: How Increasing Input Tokens Impacts LLM Performance
- **Authors:** Hong, Troynikov, Huber (Chroma)
- **Year/Venue:** 2025, Technical Report
- **Results:**
  - 18 SOTA models tested (GPT-4.1, Claude 4, Gemini 2.5, Qwen3).
  - **Model reliability significantly decreases with longer inputs**, even on simple tasks.
  - Three mechanisms: "lost in the middle," quadratic attention, semantically similar distractors.
  - Models perform **better on shuffled haystacks** than on logically structured ones.
  - Claude Opus 4: **2.89% refusal rate** on long inputs.
- **Relevance:** Every failed exploration (wrong file read, irrelevant grep) consumes context and degrades reasoning. Surgical retrieval (~300 tokens for 5 results) minimizes pollution.
- **URL:** https://research.trychroma.com/context-rot

### 6.2 "Context is the Bottleneck for Coding Agents Now" (Runner)
- **Year:** 2025
- **Key claims:**
  - "The limiting factor is no longer raw intelligence, but rather context."
  - "Current coding agents are operating with maybe **20%** of the context a human developer would have."
  - Context poisoning: "When an agent spends thousands of tokens exploring a wrong solution path, it has difficulty ignoring that bad exploration even when explicitly redirected."
  - OpenAI achieved perfect scores at ICPC 2025, yet agents are "nowhere near capable of replacing software developers" — the gap is context, not intelligence.
- **URL:** https://runnercode.com/blog/context-is-the-bottleneck-for-coding-agents-now

### 6.3 "The Context Window Problem" (Factory.ai)
- **Year:** 2025
- **Key claims:**
  - "A typical enterprise monorepo can span thousands of files and several million tokens."
  - Solution = "structured repository overviews, semantic search, targeted file operations" — exactly what retrieval tools provide.
- **URL:** https://factory.ai/news/context-window-problem

---

## 7. Two-phase architectures (localize THEN repair)

### 7.1 AutoCodeRover: Autonomous Program Improvement
- **Authors:** Zhang et al.
- **Year/Venue:** 2024, ISSTA 2024
- **Ref:** arXiv:2404.05427
- **Results:**
  - Explicit separation between context retrieval (localization) and patch generation.
  - AST search APIs (search_class, search_method_in_class, search_code_in_file) rather than raw reading.
  - SBFL: **17.00% → 20.33%** (+3.33 pp).
  - Average cost: **$0.435/issue** (37,602 tokens) vs. SWE-agent $0.741 (70,181 tokens).
  - 37.3% SWE-bench Lite, 46.2% SWE-bench Verified.
- **Relevance:** Structured search APIs (analogous to RTFM) outperform raw reading with ~40% fewer tokens.
- **URL:** https://arxiv.org/abs/2404.05427

### 7.2 PatchPilot: A Cost-Efficient Agentic Patching Framework
- **Authors:** UCSB + Meta
- **Year/Venue:** 2025, ICML 2025
- **Ref:** arXiv:2502.02747
- **Results:**
  - 5-stage pipeline: reproduction, localization, generation, validation, refinement.
  - **Ablation on SWE-bench Lite:**
    - Basic localization + generation: **32.7%**
    - Improved localization + generation: **38.7%** (+6.0 pp from localization alone)
    - Full system: **45.33%**
  - **Localization alone = ~47% of the total improvement** (6.0 / 12.63 pp).
  - Cost: **$0.97/instance** vs. OpenHands $1.87-$2.14, CodeStory $20.
- **Relevance:** The ablation cleanly separates the localization contribution from repair. Localization is responsible for almost half of the total gain.
- **URL:** https://arxiv.org/abs/2502.02747

### 7.3 RepoGraph: Enhancing AI SE with Repository-level Code Graph
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2410.14684
- **Results:**
  - Fine-grained graph of code lines and definition-reference relations.
  - **+32.8% relative improvement** in resolve rate on SWE-bench Lite.
  - Agentless + RepoGraph: 29.67% (vs. ~22.33% Agentless alone).
- **URL:** https://arxiv.org/abs/2410.14684

---

## 8. Architectural analysis of SWE-bench

### 8.1 Dissecting the SWE-Bench Leaderboards
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.17208
- **Results:**
  - 80 unique approaches, 178 leaderboard entries.
  - Software maintenance pipeline: Preprocessing → Issue Reproduction → **Issue Localization** → Task Decomposition → Patch Generation → Verification → Ranking.
  - **Localization is a dedicated phase in virtually every competitive system** — no top system skips it.
- **URL:** https://arxiv.org/abs/2506.17208

---

## 9. Exploration loops and token waste

### 9.1 SWE-EVO: Benchmarking Coding Agents in Long-Horizon Software Evolution
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2512.18470
- **Results:**
  - Failing agents enter "non-productive loops of exploratory actions: **rereading the same files, searching for the same keywords, viewing the same snippets** without ever moving on to implementation."
  - Agents "succeed at gathering information but fail to synthesize it into a concrete modification."
- **Relevance:** Describes exactly the failure mode that pre-indexed retrieval prevents.
- **URL:** https://arxiv.org/abs/2512.18470

---

## 10. Token efficiency and context management

### 10.1 Reducing Token Usage of Software Engineering Agents (Hrubec, TU Wien)
- **Year/Venue:** 2025, Diploma thesis
- **Results:**
  - Poor serialization consumes **40-70%** of available tokens in formatting overhead.
  - Source code minification and structured context management significantly reduce waste.
- **URL:** https://repositum.tuwien.at/bitstream/20.500.12708/224666/1/Hrubec%20Nicolas%20-%202025%20-%20Reducing%20Token%20Usage%20of%20Software%20Engineering%20Agents.pdf

### 10.2 JetBrains Research: Cutting Through the Noise
- **Year/Venue:** 2025, NeurIPS 2025 Workshop
- **Results:**
  - LLM summarization of failed exploration causes **"Trajectory Elongation"** — agents do not realize how stuck they are.
  - Observation masking > LLM summarization for context management.
- **Relevance:** If agents explore less (because RTFM front-loads the right context), there is less context to mask/summarize.
- **URL:** https://blog.jetbrains.com/research/2025/12/efficient-context-management/

---

## 11. Localization as a learnable skill

### 11.1 Kimi-Dev: Agentless Training as Skill Prior for SWE-Agents
- **Authors:** Moonshot AI
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.23045
- **Results:**
  - Agentless training induces **"skill priors"** — including **localization of buggy implementations**.
  - SERA-32B: 60.4% SWE-bench Verified (best workflow approach).
  - **Localization is identified as a distinct and transferable skill** — not emergent behavior.
- **Relevance:** If localization is a distinct skill, then augmenting it with an external tool (RTFM) is a valid and complementary approach.
- **URL:** https://arxiv.org/abs/2509.23045

---

## 12. Bug localization: in-depth studies

### 12.1 A Deep Dive into LLMs for Automated Bug Localization and Repair
- **Authors:** Hossain et al. (Amazon)
- **Year/Venue:** 2024, FSE 2024
- **Ref:** arXiv:2404.11595
- **Contribution:** **Token-level** localization (not line) → substantial improvements.
- **URL:** https://arxiv.org/abs/2404.11595

### 12.2 An Empirical Study on LLM-based Agents for Automated Bug Fixing
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2411.10213
- **Results:**
  - W&B Programmer: **89.6%** at least 1 buggy file localized, **78.8%** all files.
  - Learn-by-interact: only **68.4%** — 31% gap.
  - "Only when the faulty code element is accurately identified can the model generate a semantically correct patch."
- **URL:** https://arxiv.org/abs/2411.10213

---

## Synthesis: key numbers for the localization bottleneck

| Metric | Value | Source |
|----------|--------|--------|
| Exploration/understanding actions | **~38%** (18% explore + 20% explain) | Trajectory Study (2025) |
| Token ratio: explorer vs. efficient agent | **52x** (OpenHands 1.2M vs. AutoCodeRover 23K) | Trajectory Study (2025) |
| Agentless file recall | **77.7%** | Agentless (2024) |
| File → line localization degradation | 77.7% → **50.8%** | Agentless (2024) |
| Share of localization in total improvement | **~47%** (6.0 / 12.63 pp) | PatchPilot (ICML 2025) |
| Best file localization (realistic benchmark) | **< 40%** Acc@5 | MULocBench (2025) |
| LocAgent SWE-bench file localization | **92.7%** Acc@5 | LocAgent (ACL 2025) |
| Graph-navigation gain on hidden dependencies | **+23.2 pp** (76.2% → 99.4%) | Navigation Paradox (2026) |
| RepoGraph SWE-bench improvement | **+32.8%** relative | RepoGraph (2024) |
| Agent vs. human context | **~20%** | Runner Blog (2025) |
| Too much context hurts resolution | GPT-4: 1.3% → 3.4% with oracle lines | SWE-bench (ICLR 2024) |

**Conclusion from the literature:** Coding agents spend 30-50% of their effort on localization/exploration, and localization accuracy accounts for roughly half of the performance gap between systems. Pre-built retrieval indexes directly address this bottleneck by providing surgical context at a fraction of the token cost of exploration.

---

## Bibliographic references

1. Jimenez, C.E. et al. (2024). SWE-bench. ICLR 2024. arXiv:2310.06770.
2. Xia, C.S. et al. (2024). Agentless. arXiv:2407.01489.
3. (2025). Understanding SE Agents: Thought-Action-Result Trajectories. arXiv:2506.18824.
4. Chen et al. (2025). LocAgent: Graph-Guided LLM Agents for Code Localization. ACL 2025. arXiv:2503.09089.
5. (2025). MULocBench. arXiv:2509.25242.
6. Jiang et al. (2025). CoSIL. ASE 2025. arXiv:2503.22424.
7. (2026). The Navigation Paradox in Large-Context Agentic Coding. arXiv:2602.20048.
8. Hong, Troynikov, Huber (2025). Context Rot. Chroma Research.
9. (2025). Context is the Bottleneck for Coding Agents Now. Runner Blog.
10. (2025). The Context Window Problem. Factory.ai.
11. Zhang et al. (2024). AutoCodeRover. ISSTA 2024. arXiv:2404.05427.
12. (2025). PatchPilot. ICML 2025. arXiv:2502.02747.
13. (2024). RepoGraph. arXiv:2410.14684.
14. (2025). Dissecting the SWE-Bench Leaderboards. arXiv:2506.17208.
15. (2025). SWE-EVO. arXiv:2512.18470.
16. Hrubec, N. (2025). Reducing Token Usage of SE Agents. TU Wien Thesis.
17. JetBrains (2025). Cutting Through the Noise. NeurIPS 2025 Workshop.
18. Moonshot AI (2025). Kimi-Dev. arXiv:2509.23045.
19. Hossain et al. (2024). Bug Localization and Repair. FSE 2024. arXiv:2404.11595.
20. (2024). Empirical Study on LLM-based Agents for Bug Fixing. arXiv:2411.10213.
