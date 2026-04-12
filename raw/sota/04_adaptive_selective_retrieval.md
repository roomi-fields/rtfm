# SOTA 4 — Adaptive & Selective Retrieval: Knowing When to Search

*Central angle: instead of always retrieving or never retrieving, the agent has the CHOICE to search when it recognizes that it lacks information.*

---

## 1. Self-RAG and Descendants (Retrieval through Self-Reflection)

### 1.1 Self-RAG (foundational paper)
- **Title:** Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection
- **Authors:** Akari Asai, Zeqiu Wu, Yizhong Wang, Avirup Sil, Hannaneh Hajishirzi
- **Year/Venue:** 2023, ICLR 2024 (Oral, top 1%)
- **Ref:** arXiv:2310.11511
- **Mechanism:** The LM generates special **reflection tokens**: `[Retrieve]` (should I search?), `[IsREL]` (relevant?), `[IsSUP]` (supported?), `[IsUSE]` (quality). Decision **at every segment**.
- **Results:** Self-RAG 7B/13B outperforms ChatGPT and Llama2-chat+RAG on open QA and fact verification.
- **Code relevance:** Reflection tokens are transposable to code agents: deciding at each step whether repo context is needed.
- **URL:** https://arxiv.org/abs/2310.11511 | https://selfrag.github.io/

### 1.2 Self-BioRAG (biomedical specialization)
- **Authors:** Jeong et al. (DMIS Lab)
- **Year/Venue:** 2024, ISMB/ECCB 2024, Bioinformatics
- **Ref:** arXiv:2401.15269
- **Results:** +7.2% absolute improvement over the best open 7B model.
- **URL:** https://arxiv.org/abs/2401.15269

### 1.3 Auto-RAG (autonomous iterative retrieval)
- **Title:** Auto-RAG: Autonomous Retrieval-Augmented Generation for Large Language Models
- **Authors:** Tian Yu, Shaolei Zhang, Yang Feng
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2411.19443
- **Mechanism:** LLM-retriever interaction modeled as a **multi-turn dialogue**. The LLM decides when and what to retrieve, adjusts the number of iterations according to difficulty, and stops when it has enough information.
- **Results:** Superior performance on 6 benchmarks; the number of iterations adapts to complexity.
- **Code relevance:** Very close to the workflow of a code agent (search → read → refine → search again).
- **URL:** https://arxiv.org/abs/2411.19443

---

## 2. FLARE and Active Retrieval (Retrieval During Generation)

### 2.1 FLARE (Forward-Looking Active REtrieval)
- **Title:** Active Retrieval Augmented Generation
- **Authors:** Zhengbao Jiang, Frank Xu, Luyu Gao, Zhiqing Sun, Qian Liu, Jane Dwivedi-Yu, Yiming Yang, Jamie Callan, Graham Neubig
- **Year/Venue:** 2023, EMNLP 2023
- **Ref:** arXiv:2305.06983
- **Mechanism:** During generation, if **low-confidence tokens** are detected, FLARE uses the sentence as a query to retrieve documents, then regenerates. Iterative.
- **Results:** Superior or competitive on 4 long-form knowledge-intensive generation tasks.
- **Code relevance:** A code agent could detect its "zones of uncertainty" (unknown APIs, architectural patterns) and search for context specifically.
- **URL:** https://arxiv.org/abs/2305.06983

### 2.2 DRAGIN (Dynamic Retrieval based on Information Needs)
- **Title:** DRAGIN: Dynamic Retrieval Augmented Generation based on the Real-time Information Needs of Large Language Models
- **Authors:** Weihang Su, Yichen Tang, Qingyao Ai, Zhijing Wu, Yiqun Liu
- **Year/Venue:** 2024, ACL 2024 (Oral)
- **Ref:** arXiv:2403.10081
- **Mechanism:** **RIND** (Real-time Information Needs Detection) measures LLM uncertainty to decide WHEN. **QFS** (Query Formulation based on Self-Attention) determines WHAT to retrieve.
- **Results:** Outperforms FLARE and all dynamic methods.
- **Code relevance:** Real-time detection of information needs = exactly what a code agent should do.
- **URL:** https://arxiv.org/abs/2403.10081

### 2.3 DeepRAG (Retrieval as MDP)
- **Title:** DeepRAG: Thinking to Retrieve Step by Step for Large Language Models
- **Authors:** Xinyan Guan, Jiali Zeng et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2502.01142
- **Mechanism:** Retrieval-augmented reasoning modeled as a **Markov Decision Process (MDP)**. Atomic binary decision at each step: retrieve OR rely on parametric knowledge.
- **Results:** +21.99% retrieval efficiency, +26.4% accuracy.
- **URL:** https://arxiv.org/abs/2502.01142

---

## 3. Adaptive-RAG (Adaptation by Complexity)

### 3.1 Adaptive-RAG
- **Title:** Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity
- **Authors:** Soyeong Jeong, Jinheon Baek, Sukmin Cho, Sung Ju Hwang, Jong Park
- **Year/Venue:** 2024, NAACL 2024
- **Ref:** arXiv:2403.14403
- **Mechanism:** A **classifier (small LM)** routes to 3 strategies: (A) no retrieval (simple questions), (B) single-step retrieval (moderate), (C) iterative multi-step retrieval (complex).
- **Results:** Avoids overhead on simple questions, maintains accuracy on complex ones.
- **Code relevance:** Directly applicable: "What is the value of X?" → no retrieval, vs. "How does this project handle distributed transactions?" → multi-step.
- **URL:** https://arxiv.org/abs/2403.14403

### 3.2 UAR (Unified Active Retrieval)
- **Title:** Unified Active Retrieval for Retrieval Augmented Generation
- **Authors:** Qinyuan Cheng et al.
- **Year/Venue:** 2024, Findings of EMNLP 2024
- **Ref:** arXiv:2406.12534
- **Mechanism:** 4 orthogonal criteria: Intent-aware, Knowledge-aware, Time-Sensitive-aware, **Self-aware** (does the LLM possess the internal knowledge?). Unified in a decision tree.
- **Code relevance:** The "self-aware" criterion = knowing whether you already know the API or the project structure.
- **URL:** https://arxiv.org/abs/2406.12534

---

## 4. Corrective RAG (Post-Retrieval Evaluation)

### 4.1 CRAG (Corrective RAG)
- **Title:** Corrective Retrieval Augmented Generation
- **Authors:** Shi-Qi Yan, Jia-Chen Gu, Yun Zhu, Zhen-Hua Ling
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2401.15884
- **Mechanism:** A lightweight retrieval evaluator judges document quality. If >70% are irrelevant → **corrective actions** (web search, decomposition-recomposition). Plug-and-play.
- **Results:** Outperforms standard RAG in robustness, works even when initial retrieval fails.
- **URL:** https://arxiv.org/abs/2401.15884

### 4.2 ROWEN (Retrieve Only When Needed)
- **Title:** Rowen: Adaptive Retrieval-Augmented Generation for Hallucination Mitigation in LLMs
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2402.10612
- **Mechanism:** Generates an initial answer via CoT, then a **consistency detection module** evaluates. On inconsistency → retrieval triggered. Otherwise → answer retained.
- **URL:** https://arxiv.org/abs/2402.10612

---

## 5. Retrieval Necessity Prediction (Predicting WHEN to Retrieve)

### 5.1 When to Retrieve / Adapt-LLM
- **Title:** When to Retrieve: Teaching LLMs to Utilize Information Retrieval Effectively
- **Authors:** Tiziano Labruna, Jon Ander Campos, Gorka Azkune
- **Year/Venue:** 2024, arXiv (RANLP 2025)
- **Ref:** arXiv:2404.19705
- **Mechanism:** The LLM is fine-tuned to generate a **special `<RET>` token** when it does not know the answer. If `<RET>` → IR is called. Otherwise → direct answer from parametric memory.
- **Results:** Outperforms 3 baselines (always retrieve, always memory, popularity threshold) on PopQA.
- **Code relevance:** **The most directly relevant paper.** The `<RET>` mechanism = the decision "should I search or should I code?"
- **URL:** https://arxiv.org/abs/2404.19705

### 5.2 SKR (Self-Knowledge Guided Retrieval)
- **Title:** Self-Knowledge Guided Retrieval Augmentation for Large Language Models
- **Authors:** Yile Wang, Peng Li, Maosong Sun, Yang Liu
- **Year/Venue:** 2023, Findings of EMNLP 2023
- **Ref:** arXiv:2310.05002
- **Mechanism:** The LLM **recognizes what it knows and what it doesn't** (self-knowledge). Adaptively decides whether external resources are needed.
- **Code relevance:** The "self-knowledge" idea = knowing whether you already know this repo or need to search.
- **URL:** https://arxiv.org/abs/2310.05002

---

## 6. Tool-Use Decision Making

### 6.1 Toolformer (foundational paper)
- **Title:** Toolformer: Language Models Can Teach Themselves to Use Tools
- **Authors:** Timo Schick, Jane Dwivedi-Yu et al. (Meta AI)
- **Year/Venue:** 2023, NeurIPS 2023
- **Ref:** arXiv:2302.04761
- **Mechanism:** Self-supervised fine-tuning to insert API calls. Criterion: a call is kept only if it **reduces perplexity on future tokens**.
- **Results:** GPT-J 6.7B + Toolformer outperforms GPT-3 (175B) zero-shot.
- **Code relevance:** The perplexity criterion = a signal for "searching for context reduces my uncertainty."
- **URL:** https://arxiv.org/abs/2302.04761

### 6.2 MeCo (Meta-Cognition Trigger for Adaptive Tool Use)
- **Title:** Adaptive Tool Use in Large Language Models with Meta-Cognition Trigger
- **Year/Venue:** 2025, ACL 2025
- **Ref:** arXiv:2502.12961
- **Mechanism:** Quantifies a **metacognitive score** from the LLM's internal representations. Guides the decision to invoke a tool. Zero fine-tuning, minimal cost.
- **Results:** Reliably detects internal cognitive signals.
- **Code relevance:** **Very relevant.** Detects whether the LLM "knows that it doesn't know" — without fine-tuning.
- **URL:** https://arxiv.org/abs/2502.12961

### 6.3 Gorilla (massive APIs)
- **Title:** Gorilla: Large Language Model Connected with Massive APIs
- **Authors:** Shishir Patil et al. (UC Berkeley)
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2305.15334
- **Mechanism:** LLaMA fine-tuned with Retriever Aware Training (RAT) for 1600+ APIs.
- **URL:** https://arxiv.org/abs/2305.15334

---

## 7. Calibration, Uncertainty and Abstention

### 7.1 Know Your Limits (abstention survey)
- **Title:** Know Your Limits: A Survey of Abstention in Large Language Models
- **Authors:** Bingbing Wen, Jihan Yao, Shangbin Feng et al.
- **Year/Venue:** 2025, TACL vol. 13
- **Ref:** arXiv:2407.18418
- **Contribution:** Comprehensive survey of abstention methods. Three-perspective framework: query, model, human values.
- **Code relevance:** When an agent should say "I don't know, let me search" rather than hallucinate code.
- **URL:** https://arxiv.org/abs/2407.18418

### 7.2 Do RALMs Know When They Don't Know?
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2509.01476
- **Contribution:** When all retrieved documents are irrelevant, RALMs tend to **refuse questions they could have correctly answered** (over-refusal).
- **Code relevance:** Risk that the agent searches too much and becomes less performant.
- **URL:** https://arxiv.org/abs/2509.01476

### 7.3 CalibRAG (Calibration-Oriented RAG)
- **Year/Venue:** 2024, arXiv (submitted to ICLR 2025)
- **Ref:** arXiv:2411.08891
- **Contribution:** Retrieval that ensures **well-calibrated** decisions.
- **URL:** https://arxiv.org/abs/2411.08891

### 7.4 Uncertainty Quantification in RAG
- **Year/Venue:** 2025, ICLR 2025
- **Contribution:** Passage utility judgments to predict answer correctness.
- **URL:** https://openreview.net/pdf?id=8r8H4gbFXf

---

## 8. Code-Specific Selective Retrieval

### 8.1 Repoformer — THE key paper
- **Title:** Repoformer: Selective Retrieval for Repository-Level Code Completion
- **Authors:** Di Wu, Wasi Uddin Ahmad, Dejiao Zhang, Murali Krishna Ramanathan, Xiaofei Ma (Amazon)
- **Year/Venue:** 2024, ICML 2024 (Oral)
- **Ref:** arXiv:2403.10059
- **Mechanism:** The code LM **self-evaluates** whether repo-level retrieval can improve its output. If so → retrieval. Otherwise → abstention. Robust to noisy context.
- **Results:** **>85% accuracy on retrieval decisions. Up to 70% inference speedup** without degradation.
- **Code relevance:** **This is THE paper that answers "should I search or should I code?"** The demonstration that 70% of retrievals are useless is a strong argument for selective retrieval.
- **URL:** https://arxiv.org/abs/2403.10059

### 8.2 RepoCoder (iterative retrieval)
- **Title:** RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation
- **Authors:** Fengji Zhang et al. (Microsoft)
- **Year/Venue:** 2023, EMNLP 2023
- **Ref:** arXiv:2303.12570
- **Results:** +10% over the In-File baseline.
- **URL:** https://arxiv.org/abs/2303.12570

### 8.3 CodeAgent (integrated tools for code)
- **Year/Venue:** 2024, ACL 2024
- **Ref:** arXiv:2401.07339
- **Contribution:** Agent framework with 5 programming tools. The agent decides which tool to use at each step.
- **Results:** +18.1% to +250% depending on the model.
- **URL:** https://arxiv.org/abs/2401.07339

---

## 9. Compression and Selective Augmentation

### 9.1 RECOMP
- **Title:** RECOMP: Improving Retrieval-Augmented LMs with Compression and Selective Augmentation
- **Authors:** Fangyuan Xu, Weijia Shi, Eunsol Choi
- **Year/Venue:** 2024, ICLR 2024
- **Ref:** arXiv:2310.04408
- **Mechanism:** Compresses retrieved documents into summaries. **When documents are irrelevant → empty string** = selective augmentation.
- **Results:** Compression down to 6% with minimal loss.
- **Code relevance:** Metadata-only search + expand on demand = exactly this philosophy.
- **URL:** https://arxiv.org/abs/2310.04408

---

## 10. Foundational Papers (Pre-2023)

### 10.1 RETRO
- **Authors:** Borgeaud et al. (DeepMind)
- **Year/Venue:** 2022, ICML 2022
- **Ref:** arXiv:2112.04426
- **Contribution:** Retrieval over 2 trillion tokens. Performance comparable to GPT-3 with 25x fewer parameters.
- **URL:** https://arxiv.org/abs/2112.04426

### 10.2 REALM
- **Authors:** Guu et al. (Google)
- **Year/Venue:** 2020, ICML 2020
- **Ref:** arXiv:2002.08909
- **Contribution:** First dynamic RAG model: retriever + generator trained jointly.
- **URL:** https://arxiv.org/abs/2002.08909

---

## Synthesis: The 5 most relevant papers for the "knowing when to search" thesis

| # | Paper | Why |
|---|--------|----------|
| 1 | **Repoformer** (Wu et al., ICML 2024) | Code-specific selective retrieval; 85% accuracy; 70% speedup; proves that 70% of retrievals are useless |
| 2 | **When to Retrieve / Adapt-LLM** (Labruna et al., 2024) | `<RET>` token = exactly "should I search or should I code?" |
| 3 | **Self-RAG** (Asai et al., ICLR 2024) | General framework: the model decides at every segment whether to search |
| 4 | **MeCo** (ACL 2025) | Meta-cognition without fine-tuning: detecting whether the LLM "knows that it doesn't know" |
| 5 | **Adaptive-RAG** (Jeong et al., NAACL 2024) | Complexity-based routing: no retrieval / single / multi-step |

### The central argument for the paper:
The literature shows that **systematic retrieval degrades performance** (noise, latency, over-refusal), whereas **selective retrieval** improves both quality AND efficiency. Repoformer demonstrates that **70% of retrievals in a code context are useless**. The RTFM thesis: rather than fine-tuning the model to decide when to search, we **give it the search tool** and observe whether it learns to use it selectively — and whether it performs better with it than with blind navigation.

---

## Bibliographic references

1. Asai, A., Wu, Z., Wang, Y., Sil, A., & Hajishirzi, H. (2023). Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024. arXiv:2310.11511.
2. Jeong et al. (2024). Self-BioRAG. ISMB/ECCB 2024. arXiv:2401.15269.
3. Tian, Y., Zhang, S., & Feng, Y. (2024). Auto-RAG. arXiv:2411.19443.
4. Jiang, Z. et al. (2023). Active Retrieval Augmented Generation (FLARE). EMNLP 2023. arXiv:2305.06983.
5. Su, W. et al. (2024). DRAGIN. ACL 2024. arXiv:2403.10081.
6. Guan, X. et al. (2025). DeepRAG. arXiv:2502.01142.
7. Jeong, S. et al. (2024). Adaptive-RAG. NAACL 2024. arXiv:2403.14403.
8. Cheng, Q. et al. (2024). UAR: Unified Active Retrieval. EMNLP 2024 Findings. arXiv:2406.12534.
9. Yan, S.-Q. et al. (2024). CRAG: Corrective Retrieval Augmented Generation. arXiv:2401.15884.
10. (2024). ROWEN: Retrieve Only When Needed. arXiv:2402.10612.
11. Labruna, T., Campos, J.A., & Azkune, G. (2024). When to Retrieve. RANLP 2025. arXiv:2404.19705.
12. Wang, Y., Li, P., Sun, M., & Liu, Y. (2023). SKR: Self-Knowledge Guided Retrieval. EMNLP 2023 Findings. arXiv:2310.05002.
13. Schick, T. et al. (2023). Toolformer. NeurIPS 2023. arXiv:2302.04761.
14. (2025). MeCo: Meta-Cognition Trigger. ACL 2025. arXiv:2502.12961.
15. Patil, S. et al. (2024). Gorilla. NeurIPS 2024. arXiv:2305.15334.
16. Wen, B. et al. (2025). Know Your Limits: A Survey of Abstention. TACL. arXiv:2407.18418.
17. (2024). Do RALMs Know When They Don't Know? arXiv:2509.01476.
18. (2024). CalibRAG. arXiv:2411.08891.
19. (2025). Uncertainty Quantification in RAG. ICLR 2025.
20. Wu, D. et al. (2024). Repoformer: Selective Retrieval for Repository-Level Code Completion. ICML 2024. arXiv:2403.10059.
21. Zhang, F. et al. (2023). RepoCoder. EMNLP 2023. arXiv:2303.12570.
22. (2024). CodeAgent. ACL 2024. arXiv:2401.07339.
23. Xu, F., Shi, W., & Choi, E. (2024). RECOMP. ICLR 2024. arXiv:2310.04408.
24. Borgeaud et al. (2022). RETRO. ICML 2022. arXiv:2112.04426.
25. Guu et al. (2020). REALM. ICML 2020. arXiv:2002.08909.
