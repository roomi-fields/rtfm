# SOTA 2 — Retrieval vs Exploration: Does Context Access Improve Coding Agents?

**Core thesis:** An agent that knows it doesn't know — and can search for what it needs — outperforms an agent that navigates blindly.

---

## 1. Retrieval vs Exploration in Coding Agents (Ablation Studies)

### 1.1 SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering
- **Authors:** John Yang, Carlos E. Jimenez, Alexander Wettig, Kilian Lieret, Shunyu Yao, Karthik Narasimhan, Ofir Press
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2405.15793
- **Key finding:** Ablation on 300 SWE-bench Lite instances. SWE-agent with custom ACI (search/navigation tools like `find_file`, `search_file`, `search_dir`) solves **10.7 percentage points more** instances than the baseline shell-only agent. The custom search interface is the single largest contributor to the improvement. However, when given iterative search (displaying results one-by-one via file viewer), agents exhaustively inspect every match — wasting tokens on unnecessary exploration.
- **Measured improvement:** +10.7 pp (shell-only → SWE-agent ACI). RAG-only baseline = 3.8%, full ACI = 12.5%.
- **Relevance:** The search tool is not optional — it is the critical component. But the *design* of the search interface matters enormously. An agent that can search > an agent that greps blindly > an agent with no search at all.
- **URL:** https://arxiv.org/abs/2405.15793

### 1.2 SWE-Search: Enhancing Software Agents with Monte Carlo Tree Search and Iterative Refinement
- **Authors:** Antonis Antoniades, Albert Orwall, Kexun Zhang, Yuxi Xie, Anirudh Goyal, William Wang
- **Year/Venue:** 2025, ICLR 2025
- **Ref:** arXiv:2410.20285
- **Key finding:** Structured exploration via MCTS yields **23% relative improvement** across 5 models vs standard greedy (single-trajectory) agents. The agent uses a Value Agent to evaluate search trajectories and can *backtrack* when early approaches fail. Performance scales with inference-time compute (deeper search = better results) without requiring larger models.
- **Measured improvement:** +23% relative improvement over standard agents.
- **Relevance:** Structured search (knowing when to abandon a path) >> greedy exploration. The ability to *evaluate* retrieved context and decide to explore alternatives is a metacognitive skill that directly improves task success.
- **URL:** https://arxiv.org/abs/2410.20285

### 1.3 Sourcegraph MCP Ablation (Ongoing, 2026)
- **Authors:** Stephanie Jarmak et al. (Sourcegraph)
- **Year/Venue:** 2026, Blog / preliminary results
- **Key finding:** Ablation studies comparing coding agents with and without Sourcegraph MCPs (including Deep Search) on a subset of SWE-Bench Pro. Uses Claude Code and OpenCode with Claude Haiku 4.5. Starts with the 50 most complex tasks. Core question: does "better code context" improve agent performance in realistic software tasks? Results pending but methodology is noteworthy — this is a direct tool-ablation study on MCP search.
- **Relevance:** The first public MCP-specific ablation study. Directly tests whether giving an agent an external search tool improves coding performance.
- **URL:** https://medium.com/@steph.jarmak/rethinking-coding-agent-benchmarks-5cde3c696e4a

### 1.4 On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents
- **Authors:** Jai Lal Lulla, Seyedmoein Mohsenimofidi, Matthias Galster, Jie M. Zhang, Sebastian Baltes, Christoph Treude
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2601.20404
- **Key finding:** Empirical study across 10 repositories and 124 pull requests. Agents *with* an AGENTS.md context file (providing project conventions, build commands, architecture) show **28.64% median runtime reduction** and **16.58% reduction in output tokens**, with comparable task completion. The context file acts as a "pre-retrieved" knowledge base that prevents wasteful exploration.
- **Measured improvement:** -28.64% runtime, -16.58% output tokens.
- **Relevance:** Pre-computed context (analogous to an indexed RTFM database) directly reduces the exploration cost. The agent doesn't need to *discover* conventions — it reads them from the context file.
- **URL:** https://arxiv.org/abs/2601.20404

### 1.5 Codified Context: Infrastructure for AI Agents in a Complex Codebase
- **Authors:** Aristidis Vasilopoulos
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2602.20478
- **Key finding:** Three-layer context infrastructure for a 108K-line C# system: (1) hot-memory constitution (conventions, retrieval hooks, orchestration), (2) 19 specialized domain-expert agents, (3) cold-memory knowledge base of 34 on-demand docs. Quantitative metrics across 283 development sessions show the infrastructure prevents repeated failures and maintains consistency across sessions.
- **Relevance:** Treats documentation as *infrastructure* — load-bearing artifacts that agents depend on. Without persistent context, agents "lose coherence across sessions, forget project conventions, and repeat known mistakes." This is the exact problem RTFM solves.
- **URL:** https://arxiv.org/abs/2602.20478

---

## 2. Oracle/Gold Context vs Agent Discovery

### 2.1 ContextBench: A Benchmark for Context Retrieval in Coding Agents
- **Authors:** Han Li, Letian Zhu, Bohan Zhang, Rili Feng, Jiaming Wang, Yue Pan, Earl T. Barr, Federica Sarro, Zhaoyang Chu, He Ye
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.05892
- **Key finding:** 1,136 issue-resolution tasks from 66 repos, 8 languages, each with **human-annotated gold contexts**. Critical findings:
  - LLMs favor recall over precision: line-level recall > 0.60 but precision rarely > 0.35 (F1 < 0.40)
  - **Consolidation gap:** Even when agents access most relevant code (AUC-Cov > 0.70), only **50-70% of evidence is retained** in their final context. Agents "see" critical code but don't *use* it.
  - Advanced agent scaffolding (embedding search, graph navigation, specialized tools) yields **only marginal gains** over mini-SWE-agent baseline — "The Bitter Lesson" of coding agents.
  - Claude Sonnet 4.5: 0.196 usage drop (20% of retrieved context unused); Gemini 2.5 Pro: 0.431 usage drop (43% lost).
- **Measured results (Table 2, ContextBench Lite):**
  - mini-SWE-Agent: File F1 0.634, Line F1 0.472, Pass@1 0.606
  - SWE-agent: File F1 0.625, Line F1 0.490, Pass@1 0.312
  - OpenHands: File F1 0.505, Line F1 0.490, Pass@1 0.283
- **Relevance:** The problem is NOT finding context — it's *using* it. Even with gold context provided, agents underperform. This suggests that retrieval quality matters, but the bigger bottleneck is consolidation. A search tool that delivers focused, minimal context (like RTFM's metadata-first approach) may outperform one that dumps everything.
- **URL:** https://arxiv.org/abs/2602.05892

### 2.2 CodeRAG-Bench: Can Retrieval Augment Code Generation?
- **Authors:** Zora Zhiruo Wang, Akari Asai, Xinyan Velocity Yu, Frank F. Xu, Yiqing Xie, Graham Neubig, Daniel Fried
- **Year/Venue:** 2024, NAACL 2025 Findings
- **Ref:** arXiv:2406.14497
- **Key finding:** First large-scale benchmark measuring the **gap between oracle retrieval and automated retrieval** for code generation. Specific numbers (Table 6):
  - HumanEval (StarCoder2-7B): No retrieval 31.7% → BM25 43.9% → **Gold/oracle 94.5%** (gap = 50.6 pp)
  - SWE-bench Lite (GPT-4o): No retrieval 2.3% → Best retrieval 21.7% → **Gold 30.7%** (gap = 9.0 pp)
  - Weaker models benefit most: StarCoder2-7B gains +15.6-17.8 pp on MBPP with any retrieval.
  - Even GPT-4 improves with retrieval from a diverse datastore.
- **Measured improvement:** Oracle retrieval closes up to 50.6 pp gap over no-retrieval for small models. Even for frontier models (GPT-4o), there's a 9 pp gap between best automated retrieval and oracle.
- **Relevance:** **Smoking gun for retrieval value.** The gap between "no context" and "perfect context" is enormous. Current retrievers capture only a fraction of that potential. Better retrieval = better coding. The remaining 9 pp gap for GPT-4o on SWE-bench is exactly the space RTFM targets.
- **URL:** https://arxiv.org/abs/2406.14497

### 2.3 SWE Context Bench: A Benchmark for Context Learning in Coding
- **Authors:** Jared Zhu et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.08316
- **Key finding:** Evaluates experience reuse in programming agents. Augments 300 base tasks with 99 related tasks derived from real dependency and reference relationships among GitHub issues and pull requests. Tests whether agents can leverage previously seen context for new but related tasks.
- **Relevance:** Tests a different dimension — not just retrieval, but *context learning* and transfer across related tasks. Relevant to RTFM's incremental indexing and cross-session memory.
- **URL:** https://arxiv.org/abs/2602.08316

---

## 3. File Localization as Bottleneck

### 3.1 Agentless: Demystifying LLM-based Software Engineering Agents
- **Authors:** Chunqiu Steven Xia, Yinlin Deng, Soren Dunn, Lingming Zhang
- **Year/Venue:** 2024, FSE 2025
- **Ref:** arXiv:2407.01489
- **Key finding:** Three-phase approach (localize → repair → validate). Hierarchical localization: file → class/function → edit location. **77.7% file-level accuracy, 50.8% line-level accuracy.** This simple approach achieved 32% on SWE-bench Lite at **$0.70/issue** — beating all open-source agents at time of submission.
- **Measured improvement:** 32% resolve rate at $0.70/issue. Localization-only phases show "Contains GT" metric tracking how many ground truth locations remain after each narrowing step.
- **Relevance:** **Localization IS the task.** If you can find the right files, repair is almost trivial. Agentless proves that structured, hierarchical localization (analogous to RTFM search → expand) beats autonomous agent exploration.
- **URL:** https://arxiv.org/abs/2407.01489

### 3.2 LocAgent: Graph-Guided LLM Agents for Code Localization
- **Authors:** Zhaoling Chen, Xiangru Tang, Gangda Deng, Fang Wu, Jialong Wu, Zhiwei Jiang, Viktor Prasanna, Arman Cohan, Xingyao Wang
- **Year/Venue:** 2025, ACL 2025
- **Ref:** arXiv:2503.09089
- **Key finding:** Parses codebases into directed heterogeneous graphs for multi-hop reasoning. Fine-tuned Qwen-2.5-Coder-32B achieves **92.7% file-level localization accuracy** at **~86% cost reduction** vs proprietary models. Improves downstream issue resolution by **12% at Pass@10**.
- **Measured improvement:** 92.7% file localization, 86% cost reduction, +12% issue resolution.
- **Relevance:** Graph-based structured search outperforms brute-force exploration. The key insight: code structure (imports, call graphs, dependencies) should guide search, not random navigation.
- **URL:** https://arxiv.org/abs/2503.09089

### 3.3 OrcaLoca: An LLM Agent Framework for Software Issue Localization
- **Authors:** Zhongming Yu, Hejia Zhang, Yujie Zhao, Hanxian Huang, Matrix Yao, Ke Ding, Jishen Zhao
- **Year/Venue:** 2025, ICML 2025
- **Ref:** arXiv:2502.00350
- **Key finding:** Priority-based scheduling + action decomposition with relevance scoring + distance-aware context pruning. Achieves **65.33% function match rate** on SWE-bench Lite (SOTA for open-source). Improves resolved rate by **6.33 pp** when integrated with patch generation.
- **Measured improvement:** 65.33% function match, +6.33 pp resolution rate.
- **Relevance:** Localization accuracy directly translates to downstream resolution. Better search → better localization → better fixes. The "distance-aware context pruning" is analogous to RTFM's progressive disclosure.
- **URL:** https://arxiv.org/abs/2502.00350

---

## 4. Cost of Exploration

### 4.1 How Do Coding Agents Spend Your Money? Token Consumption in Agentic Coding Tasks
- **Year/Venue:** 2025, submitted to ICLR 2026
- **Ref:** OpenReview
- **Key finding:** First empirical analysis of token consumption patterns using OpenHands agent on SWE-bench. **Input tokens dominate costs** (not output tokens), even with caching. More complex tasks consume more tokens, but variance is extreme — some runs use **10x more tokens** than others for similar tasks. The bulk of token spend is on *reading and exploring* code, not generating patches.
- **Relevance:** The exploration cost is the dominant cost. If a retrieval tool can reduce exploration (fewer wrong files read, fewer grep cycles), it directly reduces the primary cost driver.
- **URL:** https://openreview.net/forum?id=1bUeVB3fov

### 4.2 AgentDiet: Improving Efficiency through Trajectory Reduction
- **Authors:** (Multiple)
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.23586
- **Key finding:** Automatically removes "waste information" from agent trajectories (useless, redundant, expired context). Reduces input tokens by **39.9-59.7%** and costs by **21.1-35.9%** while maintaining identical performance (Pass% varies -1.0% to +2.0%). Works across 7 programming languages.
- **Measured improvement:** -39.9% to -59.7% input tokens, -21.1% to -35.9% cost, ~0% performance change.
- **Relevance:** **39-60% of tokens in agent trajectories are WASTE.** This is context that was retrieved or explored but added no value. A precision-focused retrieval system (like RTFM's metadata-first approach) could eliminate this waste at the source.
- **URL:** https://arxiv.org/abs/2509.23586

### 4.3 Reducing Token Usage of Software Engineering Agents (Thesis)
- **Authors:** Nicolas Hrubec
- **Year/Venue:** 2025, TU Wien Diploma Thesis
- **Key finding:** Identifies source code context as the natural bottleneck. Some approaches (e.g., CodeMonkeys) label files as relevant/not relevant using local LLMs, then rank by importance, including top-ranked files up to 120K tokens. This triage step is essentially a retrieval/ranking operation that precedes the actual coding.
- **Relevance:** Even approaches that don't use explicit retrieval end up re-inventing it. The "label relevant files then rank" pattern is exactly what a search index does, but less efficiently.
- **URL:** https://repositum.tuwien.at/bitstream/20.500.12708/224666/1/Hrubec%20Nicolas%20-%202025%20-%20Reducing%20Token%20Usage%20of%20Software%20Engineering%20Agents.pdf

---

## 5. Metacognition — Knowing When to Search

### 5.1 Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection
- **Authors:** Akari Asai, Zeqiu Wu, Yizhong Wang, Avirup Sil, Hannaneh Hajishirzi
- **Year/Venue:** 2023, ICLR 2024 (Oral, top 1%)
- **Ref:** arXiv:2310.11511
- **Key finding:** Trains LMs to emit special "reflection tokens" that decide when to retrieve, whether retrieved passages are relevant, and whether generated output is supported. The model *learns when it doesn't know*. Self-RAG 7B/13B outperforms ChatGPT and retrieval-augmented Llama2-chat on open-domain QA, reasoning, and fact verification. On PopQA: **always-retrieve with no self-reflection causes 40% relative performance drop** vs adaptive retrieval.
- **Measured improvement:** 40% relative gain from adaptive vs always-retrieve on PopQA. Significant gains in factuality and citation accuracy on long-form generation.
- **Relevance:** **Foundational paper for "knowing what you don't know."** The key insight: retrieval is not always helpful — knowing *when* to retrieve is as important as the retrieval itself. An agent that retrieves indiscriminately can be worse than one that retrieves selectively.
- **URL:** https://arxiv.org/abs/2310.11511

### 5.2 FLARE: Forward-Looking Active Retrieval Augmented Generation
- **Authors:** Zhengbao Jiang, Frank F. Xu, Luyu Gao et al.
- **Year/Venue:** 2023, EMNLP 2023
- **Ref:** arXiv:2305.06983
- **Key finding:** The model generates a draft sentence, checks token-level confidence, and triggers retrieval only when confidence drops below threshold theta. Uses low-confidence tokens as the retrieval query (masking high-confidence tokens). Tested on 4 long-form knowledge-intensive tasks. theta=0 (never retrieve) and theta=1 (always retrieve) are both suboptimal — the adaptive middle ground wins.
- **Measured improvement:** Superior or competitive on all 4 tasks vs always-retrieve and never-retrieve baselines.
- **Relevance:** Confidence-aware retrieval — the agent monitors its own uncertainty token by token and decides when to seek external information. This is the operational definition of "knowing what you don't know."
- **URL:** https://arxiv.org/abs/2305.06983

### 5.3 When to Retrieve: Teaching LLMs to Utilize Information Retrieval Effectively
- **Authors:** Tiziano Labruna, Jon Ander Campos, Gorka Azkune
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2404.19705
- **Key finding:** Trains an Adapt-LLM to generate a special `<RET>` token when it doesn't know the answer, triggering retrieval. On PopQA, Adapt-LLM outperforms: (1) always-retrieve, (2) always-parametric-memory, and (3) popularity-threshold baseline. When the model *chooses* not to retrieve, it achieves notably high accuracy relying on parametric memory alone.
- **Relevance:** Direct evidence that LLMs can learn *when* they need external context. The `<RET>` token is a learned "I don't know" signal — metacognitive awareness in action.
- **URL:** https://arxiv.org/abs/2404.19705

### 5.4 Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Question Complexity
- **Authors:** Soyeong Jeong, Jinheon Baek et al.
- **Year/Venue:** 2024, NAACL 2024
- **Key finding:** A trained classifier routes queries to three strategies: (A) no retrieval (simple queries), (B) single-hop retrieval, (C) multi-hop retrieval. The router predicts query complexity and selects the minimum-cost retrieval strategy that achieves target quality. 30-40% latency reduction on common queries while improving accuracy on complex reasoning.
- **Measured improvement:** 30-40% latency reduction on simple queries, improved accuracy on complex queries.
- **Relevance:** Not all queries need the same retrieval depth. A smart router (analogous to RTFM's FTS-default with optional hybrid search) avoids over-retrieving while ensuring complex queries get sufficient context.
- **URL:** https://aclanthology.org/2024.naacl-long.389/

### 5.5 Uncertainty of Thoughts (UoT): Uncertainty-Aware Planning Enhances Information Seeking in LLMs
- **Authors:** Zhiyuan Hu et al.
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2402.03271
- **Key finding:** LLMs that explicitly model uncertainty and seek to reduce it through targeted questions achieve **38.1% average improvement in task completion** across medical diagnosis, troubleshooting, and 20 Questions. Uses information-gain-based rewards — the model asks the question that would maximally reduce its uncertainty.
- **Measured improvement:** +38.1% task completion rate vs direct prompting.
- **Relevance:** The clearest demonstration that "knowing what you don't know" is actionable. An agent that can quantify its uncertainty and seek information to reduce it outperforms one that acts on incomplete information. Directly supports the thesis.
- **URL:** https://arxiv.org/abs/2402.03271

### 5.6 Evidence for Limited Metacognition in LLMs
- **Authors:** Christopher Ackerman et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.21545
- **Key finding:** Frontier LLMs since early 2024 show "increasingly strong evidence of certain metacognitive abilities" — specifically assessing confidence and anticipating their own answers. **However:** (1) abilities are limited in resolution, (2) emerge context-dependently, (3) are qualitatively different from human metacognition. Models fail at fine-grained item-wise self-assessment and don't generalize metacognitive skills across tasks without joint training.
- **Relevance:** LLMs have *some* self-knowledge but it's unreliable. This is why *external* mechanisms (like retrieval tools) are needed — the model can't reliably know what it doesn't know, so we give it tools to check. RTFM as an external metacognitive prosthetic.
- **URL:** https://arxiv.org/abs/2509.21545

### 5.7 RLCoder: Reinforcement Learning for Repository-Level Code Completion
- **Authors:** Yanlin Wang et al.
- **Year/Venue:** 2024, ICSE 2025
- **Ref:** arXiv:2407.19487
- **Key finding:** RL-trained retriever with an explicit **"stop signal"** — the retriever learns when NOT to retrieve. +12.2% exact match on CrossCodeEval/RepoEval. The stop mechanism prevents noise injection from irrelevant code.
- **Measured improvement:** +12.2% EM from learning when to stop retrieving.
- **Relevance:** Complementary to "when to retrieve" — learning when to STOP is equally important. Over-retrieval degrades quality.
- **URL:** https://arxiv.org/abs/2407.19487

---

## 6. The "Bitter Lesson" — Simple Retrieval vs Complex Scaffolding

### 6.1 ContextBench's "Bitter Lesson" Finding
- **Ref:** arXiv:2602.05892 (see 2.1 above)
- **Key finding:** Advanced agents with embedding-based search, graph navigation, or specialized file tools do NOT consistently outperform the **100-line mini-SWE-agent baseline** (which uses only bash). The marginal gains from complex retrieval scaffolding are surprisingly small. "Advanced agents tend to merely rediscover context available via straightforward shell-style search."
- **Relevance:** This is a cautionary finding. More retrieval tools != better results. What matters is *how* the agent uses the results, not the sophistication of the search. Argues for RTFM's minimalist approach (metadata-first, progressive disclosure) over complex graph-based retrieval.

### 6.2 mini-SWE-agent: The 100-Line Baseline
- **Year/Venue:** 2025
- **Key finding:** A 100-line agent using only bash (no custom search tools) scores **>74% on SWE-bench Verified**. No tools other than bash. Puts "the language model rather than the agent scaffold in the middle of attention."
- **Relevance:** The LM itself is the most important component. Retrieval tools help, but the marginal gain from *more* tools diminishes rapidly. The goal should be to serve the *right* context at the *right* time, not to provide every possible tool.
- **URL:** https://github.com/SWE-agent/mini-swe-agent

---

## 7. Agent READMEs & Context Files (Providing Context Upfront)

### 7.1 Agent READMEs: An Empirical Study of Context Files for Agentic Coding
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2511.12884
- **Key finding:** 2,303 context files from 1,925 repos across Claude Code, OpenAI Codex, and GitHub Copilot. Files prioritize functional context: build/run commands (62.3%), implementation details (69.9%), architecture (67.7%). But non-functional concerns like security (14.5%) and performance (14.5%) are rarely specified. Files are maintained like code — frequent small additions — not like documentation.
- **Relevance:** Context files are becoming infrastructure. RTFM automates what developers currently write manually into CLAUDE.md / AGENTS.md files.
- **URL:** https://arxiv.org/abs/2511.12884

---

## Summary Table: Impact of Retrieval on Coding Agent Performance

| Paper | Setting | Without retrieval/search | With retrieval/search | Delta |
|-------|---------|------------------------|----------------------|-------|
| SWE-agent (2024) | Shell-only vs ACI | ~2% solve rate | 12.5% solve rate | **+10.7 pp** |
| SWE-Search (2025) | Greedy vs MCTS | baseline | +23% relative | **+23% relative** |
| Agentless (2024) | Localization accuracy | — | 77.7% file, 50.8% line | Key enabler |
| LocAgent (2025) | File localization | — | 92.7% file accuracy | 86% cost reduction |
| CodeRAG-Bench (2024) | No retrieval vs oracle (HumanEval, SC2-7B) | 31.7% | 94.5% (oracle) | **+62.8 pp potential** |
| CodeRAG-Bench (2024) | No retrieval vs oracle (SWE-bench, GPT-4o) | 2.3% | 30.7% (oracle) | **+28.4 pp potential** |
| AGENTS.md (2025) | Without vs with context file | baseline | -28.64% runtime | **-28.64% runtime** |
| Self-RAG (2023) | Always-retrieve vs adaptive | baseline | +40% relative (PopQA) | **+40% relative** |
| UoT (2024) | No uncertainty awareness vs UoT | baseline | +38.1% task completion | **+38.1% absolute** |
| AgentDiet (2025) | Before vs after trajectory reduction | baseline tokens | -39.9% to -59.7% tokens | **~50% tokens wasted** |

---

## Key Takeaways for RTFM Paper

1. **The retrieval tool IS the performance differentiator.** SWE-agent's +10.7 pp ablation is the cleanest evidence: remove search tools, performance drops dramatically.

2. **The oracle gap is enormous.** CodeRAG-Bench shows 50+ pp gap between no-retrieval and oracle retrieval for small models, 9+ pp even for GPT-4o. Current retrievers capture only a fraction of the potential.

3. **Localization is the real task, not code generation.** Agentless proves that structured localization → simple repair beats complex autonomous agents. If you find the right files, the fix is often trivial.

4. **~40-60% of exploration tokens are waste.** AgentDiet shows most trajectory content is useless. A precision-focused retrieval tool eliminates this waste at the source.

5. **Knowing when to search matters as much as how to search.** Self-RAG shows 40% relative degradation from always-retrieve vs adaptive. Over-retrieval injects noise.

6. **But LLMs have limited self-knowledge.** They can't reliably know what they don't know (Ackerman et al. 2025). External retrieval tools serve as a metacognitive prosthetic — the agent doesn't need to know what it doesn't know if it can cheaply check.

7. **The consolidation gap is the next frontier.** ContextBench shows agents find the right context but fail to *use* it (20-43% usage drop). Serving focused, minimal context (RTFM's metadata-first approach) may outperform dumping everything.

8. **Context files work.** AGENTS.md reduces runtime by 29% and tokens by 17%. Pre-indexed, searchable context (RTFM) is the automated version of this.

---

## References

1. Yang, J., Jimenez, C.E., Wettig, A., Lieret, K., Yao, S., Narasimhan, K., & Press, O. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. NeurIPS 2024. arXiv:2405.15793.
2. Antoniades, A., Orwall, A., Zhang, K., Xie, Y., Goyal, A., & Wang, W. (2024). SWE-Search: Enhancing Software Agents with Monte Carlo Tree Search. ICLR 2025. arXiv:2410.20285.
3. Jarmak, S. (2026). Rethinking Coding Agent Benchmarks. Medium/Sourcegraph.
4. Lulla, J.L., Mohsenimofidi, S., Galster, M., Zhang, J.M., Baltes, S., & Treude, C. (2025). On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents. arXiv:2601.20404.
5. Vasilopoulos, A. (2026). Codified Context: Infrastructure for AI Agents in a Complex Codebase. arXiv:2602.20478.
6. Li, H., Zhu, L., Zhang, B., et al. (2025). ContextBench: A Benchmark for Context Retrieval in Coding Agents. arXiv:2602.05892.
7. Wang, Z., Asai, A., Yu, X.V., Xu, F.F., Xie, Y., Neubig, G., & Fried, D. (2024). CodeRAG-Bench: Can Retrieval Augment Code Generation? NAACL 2025 Findings. arXiv:2406.14497.
8. Zhu, J. et al. (2025). SWE Context Bench: A Benchmark for Context Learning in Coding. arXiv:2602.08316.
9. Xia, C.S., Deng, Y., Dunn, S., & Zhang, L. (2024). Agentless: Demystifying LLM-based Software Engineering Agents. FSE 2025. arXiv:2407.01489.
10. Chen, Z., Tang, X., Deng, G., et al. (2025). LocAgent: Graph-Guided LLM Agents for Code Localization. ACL 2025. arXiv:2503.09089.
11. Yu, Z., Zhang, H., Zhao, Y., et al. (2025). OrcaLoca: An LLM Agent Framework for Software Issue Localization. ICML 2025. arXiv:2502.00350.
12. (2025). How Do Coding Agents Spend Your Money? Token Consumption Analysis. ICLR 2026 submission.
13. (2025). AgentDiet: Improving the Efficiency of LLM Agent Systems through Trajectory Reduction. arXiv:2509.23586.
14. Hrubec, N. (2025). Reducing Token Usage of Software Engineering Agents. TU Wien Diploma Thesis.
15. Asai, A., Wu, Z., Wang, Y., Sil, A., & Hajishirzi, H. (2023). Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024. arXiv:2310.11511.
16. Jiang, Z., Xu, F.F., Gao, L. et al. (2023). Active Retrieval Augmented Generation (FLARE). EMNLP 2023. arXiv:2305.06983.
17. Labruna, T., Campos, J.A., & Azkune, G. (2024). When to Retrieve: Teaching LLMs to Utilize Information Retrieval Effectively. arXiv:2404.19705.
18. Jeong, S., Baek, J. et al. (2024). Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Question Complexity. NAACL 2024.
19. Hu, Z. et al. (2024). Uncertainty of Thoughts: Uncertainty-Aware Planning Enhances Information Seeking in LLMs. NeurIPS 2024. arXiv:2402.03271.
20. Ackerman, C. et al. (2025). Evidence for Limited Metacognition in LLMs. arXiv:2509.21545.
21. Wang, Y. et al. (2024). RLCoder: Reinforcement Learning for Repository-Level Code Completion. ICSE 2025. arXiv:2407.19487.
22. (2025). Agent READMEs: An Empirical Study of Context Files for Agentic Coding. arXiv:2511.12884.
23. (2025). An Exploratory Study of Code Retrieval Techniques in Coding Agents. Preprints.org.
