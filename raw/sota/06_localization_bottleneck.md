# SOTA 6 — Le Goulot d'Étranglement de la Localisation

*Angle : le principal mode d'échec des agents codeurs n'est PAS la génération de code, mais trouver les bons fichiers/fonctions à modifier.*

---

## 1. L'évidence fondatrice : expériences oracle SWE-bench

### 1.1 SWE-bench: Can Language Models Resolve Real-World GitHub Issues?
- **Authors:** Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan
- **Year/Venue:** 2024, ICLR 2024
- **Ref:** arXiv:2310.06770
- **Résultats clés :**
  - Avec retrieval "oracle" (les fichiers patchés exact donnés au modèle), Claude 2 = seulement **4.8%** — la localisation parfaite est nécessaire mais pas suffisante.
  - Quand les fichiers sont réduits aux **lignes éditées uniquement** (+/-15 lignes), GPT-4 passe de **1.3% à 3.4%**, Claude 2 de **4.8% à 5.9%**.
  - Augmenter le contexte BM25 (plus de fichiers) **diminue** la performance.
  - **Citation clé :** "Models become distracted by additional context and sensitive to the relative location of target sequences."
- **Pertinence :** Trop de fichiers nuit. Le retrieval chirurgical (exactement ce que fait RTFM) améliore directement les résultats.
- **URL:** https://arxiv.org/abs/2310.06770

---

## 2. Agentless & Localisation Hiérarchique

### 2.1 Agentless: Demystifying LLM-based Software Engineering Agents
- **Authors:** Xia, Deng, Dunn, Zhang
- **Year/Venue:** 2024, arXiv (NeurIPS 2024 / ACM SIGSOFT)
- **Ref:** arXiv:2407.01489
- **Résultats clés :**
  - Localisation hiérarchique : fichier → classe/fonction → ligne d'édition.
  - **Fichier : 77.7%** → **Classe/fonction : 55.3%** → **Ligne : 50.8%**
  - Localisation = **$0.09** par issue (26% du coût total de $0.34).
  - 27.33% (82/300) sur SWE-bench Lite.
  - **La dégradation 77.7% → 50.8% montre que chaque niveau de localisation est un point de défaillance potentiel.** Presque la moitié des échecs viennent de la localisation, pas de la génération.
- **Pertinence :** Un index pré-construit (comme RTFM) pourrait remplacer le fichier-level à coût quasi-nul vs $0.09/query.
- **URL:** https://arxiv.org/abs/2407.01489

---

## 3. Analyse de trajectoires : comment les agents passent leur temps

### 3.1 Understanding Software Engineering Agents: A Study of Thought-Action-Result Trajectories
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.18824
- **Résultats clés :**
  - 120 trajectoires, 2,822 interactions LLM (RepairAgent, AutoCodeRover, OpenHands).
  - **Distribution des actions :** Generate Fix (23%), Run Tests (20%), Explain (20%), **Explore (18%)**.
  - **Consommation tokens :**
    - AutoCodeRover : **23K tokens** (workflow search-locate-fix structuré)
    - RepairAgent : **220K tokens**
    - OpenHands : **1.2M tokens** — **52x plus que AutoCodeRover**
  - AutoCodeRover passe **les 50% premiers de sa trajectoire sur Search, Locate, Explain** avant de passer au fix.
  - **Les trajectoires échouées** exhibent des "cycles répétitifs non-adaptatifs" — agents bloqués en boucles d'exploration.
  - RepairAgent : cas échoués = **40 itérations vs 22 pour les succès**.
- **Pertinence :** ~38% de toutes les actions sont du finding/understanding, pas de l'écriture. Un outil de retrieval qui front-load cette info élimine une large fraction de tokens gaspillés.
- **URL:** https://arxiv.org/abs/2506.18824

---

## 4. Benchmarks spécifiques à la localisation

### 4.1 LocAgent: Graph-Guided LLM Agents for Code Localization
- **Authors:** Chen, Tang, Deng, Wu, Wu, Jiang, Prasanna, Cohan, Wang
- **Year/Venue:** 2025, ACL 2025
- **Ref:** arXiv:2503.09089
- **Résultats :**
  - File-level sur SWE-bench Lite : **Acc@1: 75.91%, Acc@3: 90.51%, Acc@5: 92.70%** (Qwen2.5-32B fine-tuné).
  - Function-level : **Acc@5: 71.90%, Acc@10: 77.01%**.
  - Meilleure localisation → **+12% Pass@10** en résolution.
  - **86% de réduction de coût** vs Claude 3.5 ($0.09 vs $0.66).
  - Utilise des graphes de dépendances (AST → graphes dirigés hétérogènes).
- **Pertinence :** La recherche structurée/graph pour la localisation bat drastiquement l'exploration brute-force.
- **URL:** https://arxiv.org/abs/2503.09089

### 4.2 MULocBench: A Benchmark for Localizing Code and Non-Code Issues
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.25242
- **Résultats :**
  - 1,100 issues, 46 repos Python — plus diversifié que SWE-bench.
  - **Même au niveau fichier, les meilleures méthodes < 40%** (Acc@5, F1) :
    - LocAgent + Claude 3.5 : **35.2% Acc@5, 38.1% F1**
    - OpenHands + Claude 3.5 : **33.5% Acc@5**
  - **Enhancement requests** sont les plus durs à localiser (~30% max).
  - SWE-bench surestime les capacités de localisation (repos mémorisés).
- **Pertinence :** Sur des repos vraiment nouveaux (pas dans les données d'entraînement), la localisation est encore plus dure. Les outils de retrieval pré-indexés deviennent essentiels.
- **URL:** https://arxiv.org/abs/2509.25242

### 4.3 CoSIL: Issue Localization via LLM-Driven Code Graph Searching
- **Authors:** Jiang et al.
- **Year/Venue:** 2025, ASE 2025
- **Ref:** arXiv:2503.22424
- **Résultats :**
  - Top-1 localisation : **43.3% (SWE-bench Lite), 44.6% (SWE-bench Verified)** avec Qwen2.5-Coder-32B.
  - **+96% d'amélioration** vs état de l'art précédent.
  - Training-free et indexing-free.
- **URL:** https://arxiv.org/abs/2503.22424

---

## 5. Le paradoxe de la navigation : plus de contexte ≠ meilleur

### 5.1 The Navigation Paradox in Large-Context Agentic Coding
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2602.20048
- **Résultats clés :**
  - **Les fenêtres de contexte plus larges déplacent le mode d'échec de la capacité de retrieval vers la saillance navigatrice.** Le modèle n'échoue pas par manque de tokens — il échoue parce qu'il ne découvre jamais le fichier pertinent.
  - CodeCompass (outil MCP de navigation par graphe AST) : **+23.2 pp** sur les dépendances cachées (99.4% vs 76.2% vanilla).
  - BM25 aide sur les tâches sémantiques mais **zéro bénéfice** sur les dépendances architecturalement cachées.
  - **Le bon outil dépend du type de tâche** : sémantique → retrieval (100%), dépendances cachées → navigation graphe.
  - 58% des essais où l'outil de navigation était disponible mais non utilisé = 80.2% ACS (baseline) — **les agents doivent être incités à utiliser les outils de navigation**.
  - **Citation clé :** "When architecturally critical but semantically distant files are absent from the model's attention, errors may occur that additional context budget alone is unlikely to resolve."
- **Pertinence :** Valide directement la valeur des outils de retrieval via MCP. Recherche sémantique et navigation structurelle couvrent des modes d'échec différents — l'hybride FTS+embeddings de RTFM couvre les deux.
- **URL:** https://arxiv.org/abs/2602.20048

---

## 6. Context Rot : pourquoi l'exploration remplit le contexte de bruit

### 6.1 Context Rot: How Increasing Input Tokens Impacts LLM Performance
- **Authors:** Hong, Troynikov, Huber (Chroma)
- **Year/Venue:** 2025, Technical Report
- **Résultats :**
  - 18 modèles SOTA testés (GPT-4.1, Claude 4, Gemini 2.5, Qwen3).
  - **La fiabilité du modèle décroît significativement avec des inputs plus longs**, même sur des tâches simples.
  - 3 mécanismes : "lost in the middle", attention quadratique, distracteurs sémantiquement similaires.
  - Les modèles performent **mieux sur des haystacks mélangés** que logiquement structurés.
  - Claude Opus 4 : **2.89% taux de refus** sur inputs longs.
- **Pertinence :** Chaque exploration ratée (mauvais fichier lu, grep irrelevant) consomme du contexte et dégrade le raisonnement. Le retrieval chirurgical (~300 tokens pour 5 résultats) minimise la pollution.
- **URL:** https://research.trychroma.com/context-rot

### 6.2 "Context is the Bottleneck for Coding Agents Now" (Runner)
- **Year:** 2025
- **Claims clés :**
  - "The limiting factor is no longer raw intelligence, but rather context."
  - "Current coding agents are operating with maybe **20%** of the context a human developer would have."
  - Context poisoning : "When an agent spends thousands of tokens exploring a wrong solution path, it has difficulty ignoring that bad exploration even when explicitly redirected."
  - OpenAI a obtenu des scores parfaits à l'ICPC 2025, mais les agents "nowhere near capable of replacing software developers" — le gap est le contexte, pas l'intelligence.
- **URL:** https://runnercode.com/blog/context-is-the-bottleneck-for-coding-agents-now

### 6.3 "The Context Window Problem" (Factory.ai)
- **Year:** 2025
- **Claims clés :**
  - "A typical enterprise monorepo can span thousands of files and several million tokens."
  - Solution = "structured repository overviews, semantic search, targeted file operations" — exactement ce que les outils de retrieval fournissent.
- **URL:** https://factory.ai/news/context-window-problem

---

## 7. Architectures deux-phases (localiser PUIS réparer)

### 7.1 AutoCodeRover: Autonomous Program Improvement
- **Authors:** Zhang et al.
- **Year/Venue:** 2024, ISSTA 2024
- **Ref:** arXiv:2404.05427
- **Résultats :**
  - Séparation explicite context retrieval (localisation) / patch generation.
  - APIs de recherche AST (search_class, search_method_in_class, search_code_in_file) plutôt que lecture brute.
  - SBFL : **17.00% → 20.33%** (+3.33 pp).
  - Coût moyen : **$0.435/issue** (37,602 tokens) vs SWE-agent $0.741 (70,181 tokens).
  - 37.3% SWE-bench Lite, 46.2% SWE-bench Verified.
- **Pertinence :** Les APIs de recherche structurées (analogues à RTFM) outperforment la lecture brute avec ~40% moins de tokens.
- **URL:** https://arxiv.org/abs/2404.05427

### 7.2 PatchPilot: A Cost-Efficient Agentic Patching Framework
- **Authors:** UCSB + Meta
- **Year/Venue:** 2025, ICML 2025
- **Ref:** arXiv:2502.02747
- **Résultats :**
  - Pipeline 5 étapes : reproduction, localisation, génération, validation, refinement.
  - **Ablation sur SWE-bench Lite :**
    - Localisation basique + génération : **32.7%**
    - Localisation améliorée + génération : **38.7%** (+6.0 pp de la localisation seule)
    - Système complet : **45.33%**
  - **La localisation seule = ~47% de l'amélioration totale** (6.0 / 12.63 pp).
  - Coût : **$0.97/instance** vs OpenHands $1.87-$2.14, CodeStory $20.
- **Pertinence :** L'ablation sépare proprement la contribution de la localisation vs la réparation. La localisation est responsable de presque la moitié du gain total.
- **URL:** https://arxiv.org/abs/2502.02747

### 7.3 RepoGraph: Enhancing AI SE with Repository-level Code Graph
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2410.14684
- **Résultats :**
  - Graphe fin de lignes de code et relations definition-reference.
  - **+32.8% d'amélioration relative** en resolve rate sur SWE-bench Lite.
  - Agentless + RepoGraph : 29.67% (vs ~22.33% Agentless seul).
- **URL:** https://arxiv.org/abs/2410.14684

---

## 8. Analyse architecturale SWE-bench

### 8.1 Dissecting the SWE-Bench Leaderboards
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.17208
- **Résultats :**
  - 80 approches uniques, 178 entrées leaderboard.
  - Pipeline maintenance logicielle : Preprocessing → Issue Reproduction → **Issue Localization** → Task Decomposition → Patch Generation → Verification → Ranking.
  - **La localisation est une phase dédiée dans virtuellement chaque système compétitif** — aucun top système ne la saute.
- **URL:** https://arxiv.org/abs/2506.17208

---

## 9. Boucles d'exploration et gaspillage de tokens

### 9.1 SWE-EVO: Benchmarking Coding Agents in Long-Horizon Software Evolution
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2512.18470
- **Résultats :**
  - Les agents en échec entrent dans des "boucles non-productives d'actions exploratoires : **relire les mêmes fichiers, chercher les mêmes mots-clés, voir les mêmes snippets** sans jamais passer à l'implémentation."
  - Les agents "réussissent à rassembler l'information mais échouent à la synthétiser en modification concrète."
- **Pertinence :** Décrit exactement le mode d'échec que le retrieval pré-indexé prévient.
- **URL:** https://arxiv.org/abs/2512.18470

---

## 10. Efficience tokens et gestion de contexte

### 10.1 Reducing Token Usage of Software Engineering Agents (Hrubec, TU Wien)
- **Year/Venue:** 2025, Diploma thesis
- **Résultats :**
  - La sérialisation pauvre consomme **40-70%** des tokens disponibles en overhead de formatage.
  - La minification de code source et la gestion structurée du contexte réduisent significativement le gaspillage.
- **URL:** https://repositum.tuwien.at/bitstream/20.500.12708/224666/1/Hrubec%20Nicolas%20-%202025%20-%20Reducing%20Token%20Usage%20of%20Software%20Engineering%20Agents.pdf

### 10.2 JetBrains Research: Cutting Through the Noise
- **Year/Venue:** 2025, NeurIPS 2025 Workshop
- **Résultats :**
  - La summarization LLM de l'exploration ratée cause la **"Trajectory Elongation"** — les agents ne réalisent pas à quel point ils sont bloqués.
  - Observation masking > LLM summarization pour la gestion de contexte.
- **Pertinence :** Si les agents explorent moins (parce que RTFM front-load le bon contexte), il y a moins de contexte à masquer/summariser.
- **URL:** https://blog.jetbrains.com/research/2025/12/efficient-context-management/

---

## 11. La localisation comme compétence apprénable

### 11.1 Kimi-Dev: Agentless Training as Skill Prior for SWE-Agents
- **Authors:** Moonshot AI
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.23045
- **Résultats :**
  - L'entraînement Agentless induit des **"skill priors"** — incluant la **localisation d'implémentations buguées**.
  - SERA-32B : 60.4% SWE-bench Verified (meilleur workflow approach).
  - **La localisation est identifiée comme une compétence distincte et transférable** — pas un comportement émergent.
- **Pertinence :** Si la localisation est une compétence distincte, alors l'augmenter avec un outil externe (RTFM) est une approche valide et complémentaire.
- **URL:** https://arxiv.org/abs/2509.23045

---

## 12. Bug localization : études approfondies

### 12.1 A Deep Dive into LLMs for Automated Bug Localization and Repair
- **Authors:** Hossain et al. (Amazon)
- **Year/Venue:** 2024, FSE 2024
- **Ref:** arXiv:2404.11595
- **Contribution:** Localisation au niveau **token** (pas ligne) → améliorations substantielles.
- **URL:** https://arxiv.org/abs/2404.11595

### 12.2 An Empirical Study on LLM-based Agents for Automated Bug Fixing
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2411.10213
- **Résultats :**
  - W&B Programmer : **89.6%** au moins 1 fichier bugué localisé, **78.8%** tous les fichiers.
  - Learn-by-interact : seulement **68.4%** — gap de 31%.
  - "Only when the faulty code element is accurately identified can the model generate a semantically correct patch."
- **URL:** https://arxiv.org/abs/2411.10213

---

## Synthèse : les chiffres clés du goulot de localisation

| Métrique | Valeur | Source |
|----------|--------|--------|
| Actions d'exploration/compréhension | **~38%** (18% explore + 20% explain) | Trajectory Study (2025) |
| Ratio tokens : agent explorateur vs efficace | **52x** (OpenHands 1.2M vs AutoCodeRover 23K) | Trajectory Study (2025) |
| Recall fichier Agentless | **77.7%** | Agentless (2024) |
| Dégradation localisation fichier → ligne | 77.7% → **50.8%** | Agentless (2024) |
| Part de la localisation dans l'amélioration totale | **~47%** (6.0 / 12.63 pp) | PatchPilot (ICML 2025) |
| Meilleure localisation fichier (benchmark réaliste) | **< 40%** Acc@5 | MULocBench (2025) |
| Localisation fichier LocAgent SWE-bench | **92.7%** Acc@5 | LocAgent (ACL 2025) |
| Amélioration navigation graphe sur dépendances cachées | **+23.2 pp** (76.2% → 99.4%) | Navigation Paradox (2026) |
| Amélioration RepoGraph SWE-bench | **+32.8%** relatif | RepoGraph (2024) |
| Contexte des agents vs humains | **~20%** | Runner Blog (2025) |
| Trop de contexte nuit à la résolution | GPT-4: 1.3% → 3.4% avec oracle lignes | SWE-bench (ICLR 2024) |

**Conclusion de la littérature :** Les agents codeurs passent 30-50% de leur effort sur la localisation/exploration, et la précision de localisation compte pour environ la moitié de l'écart de performance entre systèmes. Les index de retrieval pré-construits adressent directement ce goulot d'étranglement en fournissant du contexte chirurgical à une fraction du coût en tokens de l'exploration.

---

## Références bibliographiques

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
