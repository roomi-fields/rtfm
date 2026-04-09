# SOTA 1 — Retrieval-Augmented Code Generation & Context Retrieval for AI Coding Agents

## 1. Surveys & Overviews

### 1.1 Retrieval-Augmented Code Generation: A Survey with Focus on Repository-Level Approaches
- **Authors:** Yicheng Tao, Yao Qin, Yepang Liu
- **Year/Venue:** 2025 (revised Jan 2026), arXiv
- **Ref:** arXiv:2510.04905
- **Contribution:** Survey exhaustif RACG. 5 dimensions : stratégies de génération, modalités de retrieval, architectures, paradigmes d'entraînement, protocoles d'évaluation. Emphase sur le fait que le repo-level nécessite des dépendances longue portée et une cohérence sémantique globale.
- **Pertinence:** Cadre de référence pour positionner le retrieval au niveau projet. Le survey ne couvre que le code — gap pour le multi-format.
- **URL:** https://arxiv.org/abs/2510.04905

### 1.2 A Survey on Code Generation with LLM-based Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2508.00083
- **Contribution:** Couvre 2022-2025. Note que les implémentations mainstream de mémoire long-terme adoptent le framework RAG. Couvre planification, tool use, réflexion, mémoire.
- **Pertinence:** Positionne le retrieval comme composant "mémoire long-terme" des agents codeurs.
- **URL:** https://arxiv.org/abs/2508.00083

### 1.3 AI Agentic Programming: A Survey of Techniques, Challenges, and Opportunities
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2508.11126
- **Contribution:** 152 références (2022-2025), 53% de 2024. Identifie tool usage, planification, mémoire et réflexion comme composants core.
- **Pertinence:** Taxonomie pour positionner le retrieval dans la pile agentique.
- **URL:** https://arxiv.org/abs/2508.11126

### 1.4 Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG
- **Authors:** Singh, Ehtesham et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2501.09136
- **Contribution:** Définit "Agentic RAG" = agents autonomes intégrés dans le pipeline RAG. Taxonomie des architectures. Applications santé, finance, éducation.
- **Pertinence:** RTFM + MCP = exactement un système Agentic RAG — l'agent décide quand chercher.
- **URL:** https://arxiv.org/abs/2501.09136

---

## 2. Méthodes de Retrieval pour le Code

### 2.1 Practical Code RAG at Scale: Task-Aware Retrieval Design Choices under Compute Budgets
- **Authors:** Timur Galimzyanov, Olga Kolomyttseva, Egor Bogomolov
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2510.20609
- **Contribution:** Comparaison systématique sur Long Code Arena. **BM25 + word splitting bat les embeddings denses** pour code-to-code (10x plus rapide). Dense (Voyager-3) meilleur pour NL-to-code mais 100x plus lent. Chunking par lignes = chunking syntax-aware. Chunk size 32-64 lignes optimal.
- **Pertinence:** **Valide directement le choix FTS5 (BM25) comme défaut.** Hybrid search justifié pour les requêtes NL.
- **URL:** https://arxiv.org/abs/2510.20609

### 2.2 GrepRAG: An Empirical Study and Optimization of Grep-Like Retrieval for Code Completion
- **Authors:** Baoyi Wang et al.
- **Year/Venue:** 2026, ISSTA '26
- **Ref:** arXiv:2601.23254
- **Contribution:** Retrieval lexical via ripgrep, LLMs génèrent des commandes rg autonomes. +7-15% sur CrossCodeEval vs méthodes graph-based.
- **Pertinence:** Le retrieval lexical léger bat les méthodes complexes. Valide l'idée que l'agent peut piloter son propre retrieval.
- **URL:** https://arxiv.org/abs/2601.23254

### 2.3 RLCoder: Reinforcement Learning for Repository-Level Code Completion
- **Authors:** Yanlin Wang et al.
- **Year/Venue:** 2024, ICSE 2025
- **Ref:** arXiv:2407.19487
- **Contribution:** RL pour entraîner un retriever sans données labellisées. Mécanisme de "stop signal" — le retriever décide quand NE PAS retriever. +12.2% EM sur CrossCodeEval/RepoEval.
- **Pertinence:** Le concept de "savoir quand ne pas chercher" est central à la thèse.
- **URL:** https://arxiv.org/abs/2407.19487

### 2.4 LLM Agents Improve Semantic Code Search (RepoRift)
- **Authors:** Sarthak Jain et al.
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2408.11058
- **Contribution:** Agents RAG enrichissent les requêtes avec le contexte du repo avant la recherche sémantique. 78.2% Success@10 sur CodeSearchNet.
- **Pertinence:** L'enrichissement de requête via l'agent améliore le retrieval — l'agent utilise activement le retrieval.
- **URL:** https://arxiv.org/abs/2408.11058

### 2.5 STALL+: Boosting LLM-based Repository-level Code Completion with Static Analysis
- **Authors:** Mingwei Liu et al.
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2406.10018
- **Contribution:** Première étude systématique d'intégration de l'analyse statique. L'intégration des dépendances au niveau fichier dans le prompting est la plus efficace.
- **Pertinence:** Surfacer les relations de dépendances (imports, call graphs) dans le prompt = valeur maximale.
- **URL:** https://arxiv.org/abs/2406.10018

### 2.6 Hierarchical Context Pruning (HCP)
- **Year/Venue:** 2024, AAAI 2025
- **Ref:** arXiv:2406.18294
- **Contribution:** Modélise les repos au niveau fonction, préserve les dépendances topologiques. Meilleur sur 5/6 Code LLMs sur CrossCodeEval.
- **Pertinence:** La granularité fonction-level avec awareness des dépendances est la bonne approche.
- **URL:** https://arxiv.org/abs/2406.18294

### 2.7 CodeRAG-Bench: Can Retrieval Augment Code Generation?
- **Authors:** Zora Wang, Akari Asai et al. (CMU)
- **Year/Venue:** 2024, NAACL 2025 Findings
- **Ref:** arXiv:2406.14497
- **Contribution:** ~9,000 problèmes, 25M+ documents, 5 sources (solutions, tutoriels, docs, StackOverflow, GitHub). 10 retrievers × 10 LLMs. RAG améliore même GPT-4. +15.6-17.8 pp MBPP pour StarCoder2-7B.
- **Pertinence:** Valide que le RAG améliore la génération de code de manière universelle. Les retrievers actuels échouent avec faible overlap lexical → besoin de hybride.
- **URL:** https://arxiv.org/abs/2406.14497

### 2.8 What to Retrieve for Effective Retrieval-Augmented Code Generation?
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2503.20589
- **Contribution:** Compare 3 sources : code contextuel, info API, snippets similaires. **Les snippets similaires introduisent du bruit (-15%)**. Code contextuel + API = le bon signal. AllianceCoder: +20% Pass@1.
- **Pertinence:** La qualité du retrieval compte plus que la quantité. Le bruit dégrade activement.
- **URL:** https://arxiv.org/abs/2503.20589

### 2.9 An Empirical Study of Retrieval-Augmented Code Generation: Challenges and Opportunities
- **Year/Venue:** 2025, ACM TOSEM
- **Ref:** arXiv:2501.13742
- **Contribution:** Impact du retrieval sur CodeGen, UniXcoder, CodeT5. Recommande BM25 + Sequential Integration Fusion.
- **Pertinence:** BM25 = baseline forte, cohérent avec le choix FTS5.
- **URL:** https://arxiv.org/abs/2501.13742

### 2.10 cAST: Enhancing Code RAG with Structural Chunking via Abstract Syntax Tree
- **Authors:** Zhang, Zhao, Wang, Yang, Wei, Wu (CMU)
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.15655
- **Contribution:** Chunking par AST > chunking par lignes. Respecte les frontières sémantiques du code.
- **Pertinence:** Validation du chunking AST déjà implémenté dans RTFM (parser Python).
- **URL:** https://arxiv.org/abs/2506.15655

---

## 3. Compréhension & Génération Repo-Level

### 3.1 InlineCoder: Repository-Level Code Generation via Context Inlining
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2601.00376
- **Contribution:** Inlining bidirectionnel dans le call graph (callers + callees). Meilleur sur DevEval/RepoExec.
- **Pertinence:** Complémentaire — le retrieval fournit le contenu, l'inlining structure le contexte.
- **URL:** https://arxiv.org/abs/2601.00376

### 3.2 RepoHyper: Search-Expand-Refine on Semantic Graphs
- **Year/Venue:** 2024, FORGE 2025
- **Ref:** arXiv:2403.06095
- **Contribution:** Repo-level Semantic Graph (RSG) + GNN link prediction. Pipeline "search-expand-refine".
- **Pertinence:** Le pattern search→expand→refine correspond exactement à rtfm_search → rtfm_expand.
- **URL:** https://arxiv.org/abs/2403.06095

### 3.3 GraphCoder: Enhancing Repository-Level Code Completion via Code Context Graph
- **Authors:** Liu, Yu et al. (Peking, CAS, Huawei)
- **Year/Venue:** 2024, ASE 2024
- **Ref:** arXiv:2406.07003
- **Contribution:** Retrieval coarse-to-fine via Code Context Graph (CCG). +6.06 EM code match.
- **Pertinence:** Le retrieval graph-based outperforms le séquentiel. Le chunking par dépendances ajoute de la valeur.
- **URL:** https://arxiv.org/abs/2406.07003

### 3.4 CodeRAG: Supportive Code Retrieval on Bigraph for Real-World Code Generation
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2504.10046
- **Contribution:** Modélise requirements comme un graphe, mappe vers le code. +40.9 Pass@1 GPT-4o sur DevEval. Bat Copilot et Cursor.
- **Pertinence:** Le retrieval guidé par les requirements >> retrieval code-only. Valide l'indexation multi-format.
- **URL:** https://arxiv.org/abs/2504.10046

### 3.5 CodePlan: Repository-level Coding using LLMs and Planning
- **Authors:** Bairi, Sonwane et al. (Microsoft Research)
- **Year/Venue:** 2023, FSE 2024
- **Ref:** arXiv:2309.12499
- **Contribution:** Repo-level coding comme problème de planification. Chain-of-edits via dependency analysis. 5/7 repos valides vs 0/7 baselines.
- **Pertinence:** Le contexte du "entire repository" est nécessaire à chaque étape d'édition.
- **URL:** https://arxiv.org/abs/2309.12499

---

## 4. Agents Codeurs & Systèmes Tool-Augmented

### 4.1 SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering
- **Authors:** Yang, Jimenez et al. (Princeton)
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2405.15793
- **Contribution:** Agent-Computer Interface (ACI). RAG seul = 3.8%, ACI = 12.5%. +10.7 pp vs shell brut.
- **Pertinence:** RAG seul insuffisant — mais les outils de navigation (dont recherche) sont critiques.
- **URL:** https://arxiv.org/abs/2405.15793

### 4.2 Agentless: Demystifying LLM-based Software Engineering Agents
- **Authors:** Chunqiu Steven Xia, Yinlin Deng, Soren Dunn, Lingming Zhang
- **Year/Venue:** 2024, NeurIPS 2024 / ACM SIGSOFT
- **Ref:** arXiv:2407.01489
- **Contribution:** Localisation hiérarchique (fichier → classe → fonction → ligne) → repair → validation. 32% SWE-bench Lite à $0.70/issue.
- **Pertinence:** **La localisation hiérarchique est directement analogue à search→expand.** La localisation structurée bat la navigation autonome.
- **URL:** https://arxiv.org/abs/2407.01489

### 4.3 Code Researcher: Deep Research Agent for Large Systems Code and Commit History
- **Authors:** Microsoft Research
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.11060
- **Contribution:** Agent "deep research" pour le code. Explore 10 fichiers/trajectoire vs 1.33 pour SWE-agent. Mémoire structurée. 58% crash resolution.
- **Pertinence:** Explorer plus de fichiers (contexte plus large) → meilleurs résultats.
- **URL:** https://arxiv.org/abs/2506.11060

### 4.4 Confucius Code Agent: Scalable Agent Scaffolding for Real-World Codebases
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2512.10398
- **Contribution:** 54.3% Resolve@1 SWE-Bench-Pro (SOTA). Note-taking persistant, extensions modulaires. **"Le scaffolding, pas le pre-training, est le facteur déterminant à l'échelle."**
- **Pertinence:** **Citation clé.** Le scaffolding (outils de contexte) > la taille du modèle.
- **URL:** https://arxiv.org/abs/2512.10398

### 4.5 Codified Context: Infrastructure for AI Agents in a Complex Codebase
- **Authors:** Aristidis Vasilopoulos
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2602.20478
- **Contribution:** 3 niveaux : hot memory (constitution), 19 agents spécialisés, cold memory (34 docs on-demand). 283 sessions de développement. Open source.
- **Pertinence:** **Comparable le plus direct.** Même problème (LLMs ne retiennent pas le contexte projet). RTFM = automatique, Codified Context = manuel.
- **URL:** https://arxiv.org/abs/2602.20478

---

## 5. Systèmes Industriels Comparables

### 5.1 Sourcegraph Cody — Lessons from Context Retrieval and Evaluation for Code Recommendations
- **Authors:** Hartman, Mehrotra, Sagtani et al. (Sourcegraph)
- **Year/Venue:** 2024, RecSys 2024
- **Ref:** arXiv:2408.05345
- **Contribution:** Architecture multi-couche (fichier local, repo local, repos distants). Repo-level Semantic Graph (RSG). "Expand and Refine". 90% du contexte = "logical codebase".
- **Pertinence:** Concurrent direct mais code-only, closed-source, enterprise. Seul paper industriel publié sur le context retrieval pour coding assistants.
- **URL:** https://arxiv.org/abs/2408.05345

### 5.2 Augment Code Context Engine
- **Year:** 2024-2025
- **Contribution:** 400K+ fichiers, graphe sémantique, MCP exposé en fév 2026. 30-80% amélioration qualité revendiquée. ISO/IEC 42001.
- **Pertinence:** Concurrent enterprise. Closed-source, code-only.
- **URL:** https://www.augmentcode.com/context-engine

---

## 6. MCP (Model Context Protocol)

### 6.1 MCP: Landscape, Security Threats, and Future Research Directions
- **Authors:** Xinyi Hou et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2503.23278
- **Contribution:** Première étude systématique architecture + sécurité MCP. Cycle de vie en 4 phases, taxonomie des menaces.
- **URL:** https://arxiv.org/abs/2503.23278

### 6.2 MCP-Bench: Benchmarking Tool-Using LLM Agents with Complex Real-World Tasks via MCP Servers
- **Year/Venue:** 2025, arXiv (Accenture)
- **Ref:** arXiv:2508.20453
- **Contribution:** 28 serveurs MCP, 250 outils, 20 LLMs benchmarkés.
- **URL:** https://arxiv.org/abs/2508.20453

### 6.3 RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection via RAG
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2505.03275
- **Contribution:** Trop de serveurs MCP = bruit. RAG pour ne charger que les pertinents.
- **URL:** https://arxiv.org/abs/2505.03275

### 6.4 MCP-Zero: Active Tool Discovery for Autonomous LLM Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.01056
- **Contribution:** Retrieval query-based plafonne à 65-72%. Active discovery = précision quasi-optimale, contexte réduit de 2 ordres de grandeur.
- **URL:** https://arxiv.org/abs/2506.01056

### 6.5 MCP at First Glance: Studying the Security and Maintainability of MCP Servers
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.13538
- **Contribution:** Étude empirique de l'écosystème MCP. 8M+ téléchargements SDK/semaine.
- **URL:** https://arxiv.org/abs/2506.13538

### 6.6 A-RAG: Scaling Agentic RAG via Hierarchical Retrieval Interfaces
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.03442
- **Contribution:** 3 outils hiérarchiques : keyword search, semantic search, chunk read. L'agent choisit la granularité. Outperforms les baselines avec moins de tokens.
- **Pertinence:** **Architecture identique à RTFM** (search metadata → expand content). Validé théoriquement sur QA, pas sur SE.
- **URL:** https://arxiv.org/abs/2602.03442

### 6.7 ScaleMCP: Dynamic and Auto-Synchronizing MCP Tools
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2505.06416
- **Contribution:** Synchronisation automatique, 10 LLMs, 5 modèles d'embedding, 5 retrievers testés.
- **URL:** https://arxiv.org/abs/2505.06416

### 6.8 Dynamic ReAct: Scalable Tool Selection for Large-Scale MCP Environments
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.20386
- **Contribution:** Dynamic MCP ReAct Agent — chargement systématique via meta-outils et recherche sémantique.
- **URL:** https://arxiv.org/abs/2509.20386

---

## Références bibliographiques

1. Tao, Y., Qin, Y., & Liu, Y. (2025). Retrieval-Augmented Code Generation: A Survey with Focus on Repository-Level Approaches. arXiv:2510.04905.
2. (2025). A Survey on Code Generation with LLM-based Agents. arXiv:2508.00083.
3. (2025). AI Agentic Programming: A Survey of Techniques, Challenges, and Opportunities. arXiv:2508.11126.
4. Singh, A., Ehtesham, A., et al. (2025). Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG. arXiv:2501.09136.
5. Galimzyanov, T., Kolomyttseva, O., & Bogomolov, E. (2025). Practical Code RAG at Scale. arXiv:2510.20609.
6. Wang, B. et al. (2026). GrepRAG: An Empirical Study and Optimization of Grep-Like Retrieval for Code Completion. ISSTA '26. arXiv:2601.23254.
7. Wang, Y. et al. (2024). RLCoder: Reinforcement Learning for Repository-Level Code Completion. ICSE 2025. arXiv:2407.19487.
8. Jain, S. et al. (2024). LLM Agents Improve Semantic Code Search (RepoRift). arXiv:2408.11058.
9. Liu, M. et al. (2024). STALL+: Boosting LLM-based Repository-level Code Completion with Static Analysis. arXiv:2406.10018.
10. (2024). Hierarchical Context Pruning. AAAI 2025. arXiv:2406.18294.
11. Wang, Z., Asai, A., et al. (2024). CodeRAG-Bench: Can Retrieval Augment Code Generation? NAACL 2025. arXiv:2406.14497.
12. (2025). What to Retrieve for Effective Retrieval-Augmented Code Generation? arXiv:2503.20589.
13. (2025). An Empirical Study of Retrieval-Augmented Code Generation. ACM TOSEM. arXiv:2501.13742.
14. Zhang et al. (2025). cAST: Enhancing Code RAG with Structural Chunking via AST. arXiv:2506.15655.
15. (2026). InlineCoder: Repository-Level Code Generation via Context Inlining. arXiv:2601.00376.
16. (2024). RepoHyper: Search-Expand-Refine on Semantic Graphs. FORGE 2025. arXiv:2403.06095.
17. Liu, Yu et al. (2024). GraphCoder: Code Context Graph for Repository-Level Code Completion. ASE 2024. arXiv:2406.07003.
18. (2025). CodeRAG: Supportive Code Retrieval on Bigraph. arXiv:2504.10046.
19. Bairi, R., Sonwane, S. et al. (2023). CodePlan: Repository-level Coding using LLMs and Planning. FSE 2024. arXiv:2309.12499.
20. Yang, J., Jimenez, C. et al. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. NeurIPS 2024. arXiv:2405.15793.
21. Xia, C.S., Deng, Y., Dunn, S., & Zhang, L. (2024). Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489.
22. Microsoft Research (2025). Code Researcher: Deep Research Agent for Large Systems Code. arXiv:2506.11060.
23. (2025). Confucius Code Agent: Scalable Agent Scaffolding for Real-World Codebases. arXiv:2512.10398.
24. Vasilopoulos, A. (2026). Codified Context: Infrastructure for AI Agents in a Complex Codebase. arXiv:2602.20478.
25. Hartman, J., Mehrotra, R. et al. (2024). AI-assisted Coding with Cody: Lessons from Context Retrieval. RecSys 2024. arXiv:2408.05345.
26. Hou, X. et al. (2025). MCP: Landscape, Security Threats, and Future Research Directions. arXiv:2503.23278.
27. (2025). MCP-Bench: Benchmarking Tool-Using LLM Agents. arXiv:2508.20453.
28. (2025). RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection. arXiv:2505.03275.
29. (2025). MCP-Zero: Active Tool Discovery for Autonomous LLM Agents. arXiv:2506.01056.
30. (2025). MCP at First Glance: Studying the Security and Maintainability. arXiv:2506.13538.
31. (2025). A-RAG: Scaling Agentic RAG via Hierarchical Retrieval Interfaces. arXiv:2602.03442.
32. (2025). ScaleMCP: Dynamic and Auto-Synchronizing MCP Tools. arXiv:2505.06416.
33. (2025). Dynamic ReAct: Scalable Tool Selection for Large-Scale MCP Environments. arXiv:2509.20386.
