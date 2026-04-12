# SOTA 5 — Context-Aware Retrieval vs. Blind Exploration

*Angle: an agent with search tools vs. an agent navigating blindly. Empirical evidence.*

---

## 1. The search tool IS the performance differentiator

### 1.1 SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering
- **Authors:** Yang, Jimenez et al. (Princeton)
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2405.15793
- **Key ablation:** Removing the search tools = **-10.7 percentage points**. Shell-only ~2%, with search ACI 12.5%.
- **URL:** https://arxiv.org/abs/2405.15793

### 1.2 SWE-Search: Enhancing Software Agents with MCTS
- **Year/Venue:** 2025, ICLR 2025
- **Contribution:** Structured exploration via Monte Carlo Tree Search = **+23% relative** over standard greedy agents.
- **URL:** https://openreview.net/forum?id=G7sIFXugTX

---

## 2. The oracle gap: how much is left to gain?

### 2.1 CodeRAG-Bench: Can Retrieval Augment Code Generation?
- **Authors:** Wang, Asai et al. (CMU)
- **Year/Venue:** 2024, NAACL 2025 Findings
- **Ref:** arXiv:2406.14497
- **Striking result:**
  - HumanEval, StarCoder2-7B: no retrieval 31.7% → BM25 43.9% → **oracle context 94.5%**
  - SWE-bench Lite, GPT-4o: no retrieval 2.3% → best retrieval 21.7% → **oracle 30.7%**
  - The current oracle-retrieval gap = **9-50 pp depending on the model**
- **Relevance:** Every point of retrieval quality translates directly into performance. Perfect retrieval triples results.
- **URL:** https://arxiv.org/abs/2406.14497

---

## 3. ~40-60% of exploration tokens are waste

### 3.1 AgentDiet: Trajectory Optimization for Coding Agents
- **Year/Venue:** 2025, arXiv
- **Contribution:** Automatic trajectory reduction = **-39.9% to -59.7% input tokens**, -21.1% to -35.9% cost, **with no loss of performance**.
- **Relevance:** If 40-60% of exploration tokens are useless, a tool that front-loads context eliminates that waste.

### 3.2 AGENTS.md Study
- **Year/Venue:** 2025, arXiv
- **Contribution:** Providing a structured context file = **-28.64% runtime, -16.58% output tokens**.
- **Relevance:** Simply giving the agent structured context significantly reduces both time and cost.

---

## 4. Knowing WHEN to search > always searching

### 4.1 Self-RAG (see SOTA 4 §1.1 for full details)
- **Key result for this angle:** Adaptive retrieval vs. always-retrieve = **+40% relative** on PopQA.
- **Indiscriminate retrieval DEGRADES performance.**

### 4.2 UoT: Uncertainty of Thoughts
- **Year/Venue:** 2024, NeurIPS 2024
- **Contribution:** Explicit uncertainty modeling = **+38.1% completion rate** vs. direct prompting.
- **Relevance:** When the agent models its uncertainty, it better knows when to search.

### 4.3 FLARE (see SOTA 4 §2.1 for full details)
- **Key result:** θ=0 (never retrieve) and θ=1 (always retrieve) are both suboptimal. The sweet spot is adaptive.

---

## 5. LLMs do NOT know what they don't know

### 5.1 Ackerman et al. — Metacognition in LLMs
- **Year/Venue:** 2025, arXiv
- **Contribution:** LLMs show growing metacognitive abilities but **limited in resolution, context-dependent, and qualitatively different from humans**. They fail at fine-grained self-assessment.
- **RTFM implication:** The agent does not need to *know* what it does not know if it can *verify* cheaply via a retrieval tool. The external tool = metacognitive prosthesis.

---

## 6. The consolidation gap: seeing ≠ using

### 6.1 ContextBench: A Benchmark for Context Retrieval in Coding Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.05892
- **Striking result:** Even when agents find the right context (AUC-Cov > 0.70), only **50-70%** of the evidence is retained in the final context.
  - Claude Sonnet 4.5: **20% loss**
  - Gemini 2.5 Pro: **43% loss**
- **Implication:** Agents "see" critical code but do not *use* it. A tool that serves **minimal and targeted context** (metadata-first) could outperform a massive dump.
- **URL:** https://arxiv.org/abs/2602.05892

---

## 7. Direct connection to the paper's thesis

| Empirical finding | Source | Implication |
|---|---|---|
| Search tool = +10.7 pp | SWE-agent (NeurIPS 2024) | Retrieval as an MCP tool is the right pattern |
| Oracle gap = 50+ pp (small models) | CodeRAG-Bench (NAACL 2025) | Better retrieval = direct impact on quality |
| Hierarchical localization beats navigation | Agentless (2024) | search → expand = exactly the right pattern |
| 40-60% of tokens wasted on exploration | AgentDiet (2025) | Metadata-first avoids loading useless context |
| Adaptive retrieval > always-retrieve | Self-RAG (ICLR 2024) | Giving the choice > forcing use |
| LLMs do not know themselves (limited metacognition) | Ackerman (2025) | External tool as metacognitive prosthesis |
| Consolidation gap (seeing ≠ using) | ContextBench (2025) | Minimal, precise context > massive dump |

---

## Bibliographic references

1. Yang, J. et al. (2024). SWE-agent. NeurIPS 2024. arXiv:2405.15793.
2. (2025). SWE-Search. ICLR 2025. https://openreview.net/forum?id=G7sIFXugTX
3. Wang, Z. et al. (2024). CodeRAG-Bench. NAACL 2025 Findings. arXiv:2406.14497.
4. (2025). AgentDiet: Trajectory Optimization for Coding Agents. arXiv.
5. (2025). AGENTS.md Study. arXiv.
6. Asai, A. et al. (2023). Self-RAG. ICLR 2024. arXiv:2310.11511.
7. (2024). UoT: Uncertainty of Thoughts. NeurIPS 2024.
8. Jiang, Z. et al. (2023). FLARE. EMNLP 2023. arXiv:2305.06983.
9. Ackerman et al. (2025). Metacognition in LLMs. arXiv.
10. (2025). ContextBench. arXiv:2602.05892.
