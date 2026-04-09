# SOTA 3 — Agents LLM Augmentés par Outils, MCP & Gestion de Contexte

## 1. Model Context Protocol (MCP)

### 1.1 MCP: Landscape, Security Threats, and Future Research Directions
- **Authors:** Xinyi Hou et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2503.23278
- **Contribution:** Première étude systématique de MCP. Cycle de vie en 4 phases (création, déploiement, opération, maintenance), 16 activités. Taxonomie des menaces. Adoption par OpenAI, Google, Microsoft.
- **URL:** https://arxiv.org/abs/2503.23278

### 1.2 A Survey of the Model Context Protocol
- **Year/Venue:** 2025, Preprints.org
- **Ref:** Preprints.org 202504.0245
- **URL:** https://www.preprints.org/manuscript/202504.0245

### 1.3 MCP-Bench: Benchmarking Tool-Using LLM Agents with Complex Real-World Tasks via MCP Servers
- **Authors:** Accenture
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2508.20453
- **Contribution:** 28 serveurs MCP, 250 outils, 20 LLMs. Évalue planification multi-étapes, coordination inter-outils.
- **URL:** https://arxiv.org/abs/2508.20453

### 1.4 RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection via RAG
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2505.03275
- **Contribution:** Le nombre de serveurs MCP dégrade la sélection d'outils. Framework RAG pour ne charger que les MCP pertinents.
- **Pertinence:** Valide le principe de ne pas tout charger — servir le minimum pertinent.
- **URL:** https://arxiv.org/abs/2505.03275

### 1.5 MCP-Zero: Active Tool Discovery for Autonomous LLM Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.01056
- **Contribution:** Retrieval query-based plafonne à 65-72%. Précision quasi-optimale via active discovery, contexte réduit de 2 ordres de grandeur.
- **URL:** https://arxiv.org/abs/2506.01056

### 1.6 Dynamic ReAct: Scalable Tool Selection for Large-Scale MCP Environments
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.20386
- **URL:** https://arxiv.org/abs/2509.20386

### 1.7 ScaleMCP: Dynamic and Auto-Synchronizing MCP Tools for LLM Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2505.06416
- **Contribution:** Synchronisation automatique, 10 LLMs, 5 modèles d'embedding, 5 retrievers testés.
- **URL:** https://arxiv.org/abs/2505.06416

---

## 2. Agents LLM Augmentés par Outils

### 2.1 Large Language Model-Based Agents for Software Engineering: A Survey
- **Authors:** FudanSELab
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2409.02977
- **Contribution:** 124 papers analysés. Génération de code, test, maintenance, décision autonome. Catégorisation depuis les perspectives SE et agent.
- **URL:** https://arxiv.org/abs/2409.02977

### 2.2 SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering
- **Authors:** Yang et al. (Princeton)
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2405.15793
- **Contribution:** ACI custom pour navigation de repo, édition, tests. 12.5% pass@1 sur SWE-bench. RAG seul = 3.8%.
- **Pertinence:** SWE-agent utilise grep/find — le retrieval structuré remplace cette étape.
- **URL:** https://arxiv.org/abs/2405.15793

### 2.3 LLM-Based Agents for Tool Learning: A Survey
- **Year/Venue:** 2025, Springer Data Science and Engineering
- **Contribution:** 100+ papers (2020-2024). 3 étapes : invoquer, retrouver l'outil, utiliser efficacement.
- **URL:** https://link.springer.com/article/10.1007/s41019-025-00296-9

### 2.4 LLM Agents Improve Semantic Code Search (RepoRift)
- **Authors:** Sarthak Jain et al. (UIUC/Cisco)
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2408.11058
- **Contribution:** Agents LLM injectent des infos contextuelles dans les requêtes via RAG. 78.2% Success@10.
- **URL:** https://arxiv.org/abs/2408.11058

---

## 3. RAG pour le Génie Logiciel

### 3.1 RACG Survey (Repository-Level)
- **Authors:** Yicheng Tao, Yao Qin, Yepang Liu
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2510.04905
- **Contribution:** Survey exhaustif RACG. Distinction file-level vs repository-level. Les vrais défis = dépendances longue portée + cohérence sémantique.
- **Pertinence:** Ne couvre que le code. Gap pour le multi-format.
- **URL:** https://arxiv.org/abs/2510.04905

### 3.2 CodeRAG-Bench: Can Retrieval Augment Code Generation?
- **Authors:** Wang, Asai, Yu, Xu, Xie, Neubig, Fried (CMU)
- **Year/Venue:** 2024, NAACL 2025 Findings
- **Ref:** arXiv:2406.14497
- **Contribution:** 5 sources, 10 retrievers, 10 LLMs. Les retrievers échouent avec faible overlap lexical.
- **Pertinence:** Valide le besoin de recherche hybride (FTS + sémantique).
- **URL:** https://arxiv.org/abs/2406.14497

### 3.3 cAST: Enhancing Code RAG with Structural Chunking via AST
- **Authors:** Zhang, Zhao, Wang, Yang, Wei, Wu (CMU)
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.15655
- **Contribution:** Chunking par AST > chunking par lignes. Respecte les frontières sémantiques.
- **URL:** https://arxiv.org/abs/2506.15655

### 3.4 Agentic RAG: A Survey
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2501.09136
- **Contribution:** Taxonomie Agentic RAG. L'agent décide quand chercher et quoi expand.
- **URL:** https://arxiv.org/abs/2501.09136

### 3.5 A-RAG: Scaling Agentic RAG via Hierarchical Retrieval Interfaces
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.03442
- **Contribution:** **3 outils hiérarchiques** : keyword search, semantic search, chunk read. L'agent choisit la granularité. Outperforms baselines avec moins de tokens.
- **Pertinence:** **Architecture quasi-identique à RTFM** (search → expand). Validé sur QA, pas sur SE.
- **URL:** https://arxiv.org/abs/2602.03442

---

## 4. Systèmes Industriels

### 4.1 Sourcegraph Cody
- **Authors:** Hartman, Mehrotra, Sagtani et al. (Sourcegraph)
- **Year/Venue:** 2024, RecSys 2024
- **Ref:** arXiv:2408.05344
- **Contribution:** Retrieval multi-couche (local, repo, distant). RSG. "Expand and Refine". 90% contexte = logical codebase.
- **Pertinence:** Code-only, closed-source, enterprise.
- **URL:** https://arxiv.org/abs/2408.05344

### 4.2 Augment Code Context Engine
- **Year:** 2024-2025
- **Contribution:** 400K+ fichiers, graphe sémantique, MCP exposé fév 2026. 30-80% amélioration revendiquée.
- **Pertinence:** Closed-source, code-only.
- **URL:** https://www.augmentcode.com/context-engine

---

## 5. Benchmarks de Contexte

### 5.1 ContextBench: A Benchmark for Context Retrieval in Coding Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.05892
- **Contribution:** 1,136 tâches, 66 repos, 8 langages. Gold contexts annotés. Recall, precision, efficience.
- **Pertinence:** **Benchmark idéal** pour évaluer la qualité du retrieval.
- **URL:** https://arxiv.org/abs/2602.05892

### 5.2 SWE Context Bench
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.08316
- **Contribution:** Réutilisation d'expérience. 300 tâches + 99 dérivées.
- **URL:** https://arxiv.org/abs/2602.08316

### 5.3 RepoGraph: Enhancing AI SE with Repository-level Code Graph
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2410.14684
- **Contribution:** Graphe de structure du repo. SOTA open-source sur SWE-bench.
- **URL:** https://arxiv.org/abs/2410.14684

---

## 6. Gestion de Contexte & Progressive Disclosure

### 6.1 Codified Context: Infrastructure for AI Agents in a Complex Codebase
- **Authors:** Aristidis Vasilopoulos
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2602.20478
- **Contribution:** 3 niveaux : hot memory (constitution), 19 agents spécialisés, cold memory (34 docs on-demand). 283 sessions. Open source. **Le savoir SUR le code, pas le code lui-même.**
- **Pertinence:** **Le plus comparable.** Même philosophie hot/warm/cold. Mais manuel vs automatique (RTFM).
- **URL:** https://arxiv.org/abs/2602.20478

### 6.2 PAACE: Plan-Aware Automated Agent Context Engineering
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2512.16970
- **Contribution:** Compression du contexte guidée par le plan. 91.5% réduction latence, 83.6% réduction coût tokens.
- **URL:** https://arxiv.org/abs/2512.16970

### 6.3 Acon: Optimizing Context Compression for Long-horizon LLM Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2510.00615
- **Contribution:** -26-54% mémoire peak. +20-46% performance petits LMs.
- **URL:** https://arxiv.org/abs/2510.00615

### 6.4 JetBrains Research: Cutting Through the Noise
- **Year:** 2025
- **Contribution:** Observation masking vs LLM summarization. Approche hybride réduit les coûts.
- **URL:** https://blog.jetbrains.com/research/2025/12/efficient-context-management/

### 6.5 LoCoBench-Agent: Interactive Benchmark for LLM Agents in Long-Context SE
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2511.13998
- **Contribution:** Mémoire hiérarchique : working, compressed, architectural.
- **URL:** https://arxiv.org/abs/2511.13998

### 6.6 Anthropic Engineering: Effective Context Engineering for AI Agents
- **Year:** 2025
- **Contribution:** Guide pratique : progressive disclosure, retrieval on-demand, éviter le context rot.
- **Pertinence:** **Source primaire** des principes de design.
- **URL:** https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

---

## 7. Parsing Multi-Format

### 7.1 Docling: An Efficient Open-Source Toolkit for AI-driven Document Conversion
- **Authors:** IBM Research Zurich
- **Year/Venue:** 2024-2025, arXiv
- **Ref:** arXiv:2408.09869 (tech report), arXiv:2501.17887 (paper)
- **Contribution:** Parser multi-format open source (PDF, DOCX, PPTX, XLSX, HTML, images). MIT.
- **Pertinence:** Conversion de documents, pas indexation/retrieval. Complémentaire.
- **URL:** https://arxiv.org/abs/2408.09869

### 7.2 Document Parsing Unveiled: Techniques, Challenges, and Prospects
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2410.21169
- **Contribution:** Survey extraction structurée depuis documents non-structurés.
- **URL:** https://arxiv.org/abs/2410.21169

---

## Références bibliographiques

1. Hou, X. et al. (2025). MCP: Landscape, Security Threats, and Future Research Directions. arXiv:2503.23278.
2. (2025). A Survey of the Model Context Protocol. Preprints.org 202504.0245.
3. Accenture (2025). MCP-Bench. arXiv:2508.20453.
4. (2025). RAG-MCP: Mitigating Prompt Bloat. arXiv:2505.03275.
5. (2025). MCP-Zero: Active Tool Discovery. arXiv:2506.01056.
6. (2025). Dynamic ReAct: Scalable Tool Selection. arXiv:2509.20386.
7. (2025). ScaleMCP: Dynamic MCP Tools. arXiv:2505.06416.
8. FudanSELab (2024). LLM-Based Agents for SE: A Survey. arXiv:2409.02977.
9. Yang, J. et al. (2024). SWE-agent. NeurIPS 2024. arXiv:2405.15793.
10. (2025). LLM-Based Agents for Tool Learning. Springer DSE.
11. Jain, S. et al. (2024). RepoRift. arXiv:2408.11058.
12. Tao, Y. et al. (2025). RACG Survey. arXiv:2510.04905.
13. Wang, Z. et al. (2024). CodeRAG-Bench. NAACL 2025. arXiv:2406.14497.
14. Zhang et al. (2025). cAST. arXiv:2506.15655.
15. Singh, A. et al. (2025). Agentic RAG Survey. arXiv:2501.09136.
16. (2025). A-RAG. arXiv:2602.03442.
17. Hartman, J. et al. (2024). Cody. RecSys 2024. arXiv:2408.05344.
18. (2025). ContextBench. arXiv:2602.05892.
19. (2025). SWE Context Bench. arXiv:2602.08316.
20. (2024). RepoGraph. arXiv:2410.14684.
21. Vasilopoulos, A. (2026). Codified Context. arXiv:2602.20478.
22. (2025). PAACE. arXiv:2512.16970.
23. (2025). Acon. arXiv:2510.00615.
24. JetBrains (2025). Cutting Through the Noise.
25. (2025). LoCoBench-Agent. arXiv:2511.13998.
26. Anthropic (2025). Effective Context Engineering.
27. IBM (2024). Docling. arXiv:2408.09869.
28. (2024). Document Parsing Unveiled. arXiv:2410.21169.
