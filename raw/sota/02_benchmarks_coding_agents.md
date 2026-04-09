# SOTA 2 — Benchmarks for Evaluating AI Coding Agents

## 1. SWE-bench Family

### 1.1 SWE-bench (Original)
- **Authors:** Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan
- **Year/Venue:** 2024, ICLR 2024
- **Ref:** arXiv:2310.06770
- **Contribution:** Premier benchmark large-scale pour LLMs sur des tâches SE réelles. 2,294 problèmes issus de vrais GitHub issues/PRs, 12 repos Python. Étant donné un codebase + description d'issue, le modèle doit éditer le code pour résoudre l'issue.
- **Métriques:** Resolve rate (% d'issues où le patch passe tous les tests).
- **URL:** https://arxiv.org/abs/2310.06770

### 1.2 SWE-bench Lite
- **Sous-ensemble:** 300 instances échantillonnées de SWE-bench pour évaluation rapide.
- **Note:** 67% des entrées Lite sont open-source. Top performance ~50% (Agentless + Claude 3.5 Sonnet).

### 1.3 SWE-bench Verified
- **Authors:** OpenAI + Princeton NLP
- **Year:** 2024
- **Contribution:** Sous-ensemble de 500 échantillons validés humainement. SOTA actuel ~79.2% (Claude Opus 4.5 + Live-SWE-agent).
- **Note:** 52% des entrées du leaderboard sont open-source. 99 entrées, 50 approches distinctes.
- **URL:** https://openai.com/index/introducing-swe-bench-verified/

### 1.4 SWE-bench Pro
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.16941
- **Contribution:** 1,865 problèmes, 41 repos, 123 langages. Tâches enterprise long-horizon. SOTA ~23%.
- **Pertinence:** Les tâches longues et complexes sont celles où le retrieval aide le plus.
- **URL:** https://arxiv.org/abs/2509.16941

### 1.5 SWE-bench-Live
- **Authors:** Linghao Zhang et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2505.23419
- **Contribution:** Benchmark live-updatable. 1,319 tâches depuis 2024, 93 repos. Élimine la contamination.
- **URL:** https://arxiv.org/abs/2505.23419

### 1.6 SWE-bench-CL (Continual Learning)
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2507.00014
- **Contribution:** Séquences chronologiques d'issues SWE-bench Verified. Évalue accumulation d'expérience et transfert.
- **URL:** https://arxiv.org/abs/2507.00014

---

## 2. FeatureBench

### 2.1 FeatureBench (ICLR 2026)
- **Year/Venue:** 2026, ICLR 2026
- **Ref:** arXiv:2602.10975
- **Contribution:** 200 tâches + 3,825 environnements exécutables, 24 repos open-source. Génération data-driven via traces de tests unitaires. Claude 4.5 Opus : 74.4% SWE-bench mais seulement **11.0% FeatureBench** — les features sont drastiquement plus dures que les bug fixes.
- **Métriques:** Resolved rate, Passed rate (fraction F2P), Token IO.
- **Pertinence:** **Le benchmark utilisé pour les tests RTFM.** Les tâches de feature implementation nécessitent la compréhension de la structure du projet — exactement le scénario où le retrieval aide.
- **URL:** https://arxiv.org/abs/2602.10975

### 2.2 FeatBench (Vibe Coding)
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2509.22237
- **Contribution:** 157 tâches, 27 repos. Inputs purement NL (pas de hints code). Meilleur : 29.94%. Les agents exhibent une "implémentation agressive" causant du scope creep.
- **URL:** https://arxiv.org/abs/2509.22237

---

## 3. Autres Benchmarks de Coding Agents

### 3.1 HumanEval / MBPP (Fondamentaux)
- **HumanEval:** 164 challenges Python (OpenAI, 2021).
- **MBPP:** ~1,000 problèmes entry-level (Google, 2021).
- **HumanEval Pro / MBPP Pro:** ACL 2025 Findings, arXiv:2412.21199. o1-mini: 96.2% HumanEval mais 76.2% HumanEval Pro.
- **Pertinence:** Function-level, ne teste PAS la compréhension repo-level.
- **URL:** https://arxiv.org/abs/2412.21199

### 3.2 CrossCodeEval
- **Venue:** NeurIPS 2023
- **Contribution:** Code completion cross-file, Python/Java/TypeScript/C#. Teste si les modèles utilisent le contexte d'autres fichiers.
- **Pertinence:** Teste exactement la capacité que le retrieval fournit — le contexte cross-file.
- **URL:** https://openreview.net/forum?id=wgDcbBMSfh

### 3.3 RepoBench
- **Year/Venue:** 2024, ICLR 2024
- **Ref:** arXiv:2306.03091
- **Contribution:** 3 sous-tâches : RepoBench-R (Retrieval), RepoBench-C (Completion), RepoBench-P (Pipeline). Python + Java.
- **Pertinence:** RepoBench-R benchmarke spécifiquement le retrieval de snippets cross-file.
- **URL:** https://arxiv.org/abs/2306.03091

### 3.4 LiveCodeBench
- **Year/Venue:** 2025, ICLR 2025
- **Ref:** arXiv:2403.07974
- **Contribution:** Collecte continue depuis LeetCode, AtCoder, CodeForces. 1,055 problèmes (v6). Contamination-free.
- **Pertinence:** Algorithmique/compétition, pas repo-level.
- **URL:** https://arxiv.org/abs/2403.07974

### 3.5 DevBench
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2601.11895
- **Contribution:** Benchmark telemetry-driven, 1,800 instances, 6 langages, 6 catégories de tâches.
- **URL:** https://arxiv.org/abs/2601.11895

### 3.6 MLE-bench
- **Authors:** OpenAI
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2410.07095
- **Contribution:** 75 compétitions Kaggle ML. o1-preview + AIDE: 16.9% bronze pass@1, 34.1% pass@8.
- **URL:** https://arxiv.org/abs/2410.07095

### 3.7 SWE-PolyBench
- **Authors:** Amazon
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2504.08703
- **Contribution:** 2,110 instances, 21 repos, Java/JavaScript/TypeScript/Python. Métriques AST-based pour precision/recall sur l'identification de contexte.
- **Pertinence:** **Mesure explicitement la capacité des agents à identifier les bons fichiers/contexte** — directement analogue à la qualité du retrieval.
- **URL:** https://arxiv.org/abs/2504.08703

### 3.8 SWE-Compass
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2511.05459
- **Contribution:** 2,000 instances, 8 types de tâches, 10 langages. Claude Sonnet 4 SOTA: 32.9%.
- **URL:** https://arxiv.org/abs/2511.05459

### 3.9 NL2Repo-Bench
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2512.12730
- **Contribution:** 104 tâches de construction de librairies Python complètes depuis specs NL (~19K tokens). Best agents <40%.
- **Pertinence:** Teste la gestion de contexte sur des tâches longues.
- **URL:** https://arxiv.org/abs/2512.12730

### 3.10 Aider Polyglot
- **Authors:** Paul Gauthier (Aider)
- **Contribution:** 225 exercices Exercism, 6 langages, protocole à deux essais. SOTA: 93.3%.
- **URL:** https://aider.chat/docs/leaderboards/

### 3.11 Context-Bench (Letta)
- **Authors:** Letta (UC Berkeley spinoff)
- **Year:** 2025
- **Contribution:** Évalue l'agentic context engineering — comment les agents décident stratégiquement quel contexte charger.
- **Pertinence:** **Mesure exactement ce que le retrieval fournit** — la qualité du contexte.
- **URL:** https://www.letta.com/blog/context-bench

### 3.12 ContextBench: A Benchmark for Context Retrieval in Coding Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.05892
- **Contribution:** 1,136 tâches, 66 repos, 8 langages. Gold contexts annotés humainement. Mesure recall, precision, efficience du contexte.
- **Pertinence:** **Benchmark idéal pour évaluer la qualité du retrieval.** Mesure ce que le retrieval fournit, pas juste le résultat final.
- **URL:** https://arxiv.org/abs/2602.05892

### 3.13 SWE Context Bench
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.08316
- **Contribution:** Réutilisation d'expérience. 300 tâches de base + 99 dérivées. 3 dimensions : précision, temps, coût.
- **URL:** https://arxiv.org/abs/2602.08316

---

## 4. Évaluation Methodology & Critiques

### 4.1 UTBoost: Rigorous Evaluation of Coding Agents on SWE-Bench
- **Year/Venue:** 2025, ACL 2025
- **Ref:** arXiv:2506.09289
- **Contribution:** 345 patchs erronés identifiés (176 Lite, 169 Verified). 40.9% des entrées Lite et 24.4% Verified affectées. UTGenerator pour augmentation automatique de tests.
- **Pertinence:** Le resolve rate seul est unreliable — la qualité des tests compte.
- **URL:** https://arxiv.org/abs/2506.09289

### 4.2 The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason
- **Authors:** Shanchao Liang, Spandan Garg, Roshanak Zilouchian Moghaddam (Microsoft)
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.12286
- **Contribution:** 76% d'identification de file-path sur SWE-bench depuis la description d'issue seule (sans accès au repo) vs 53% sur des repos non-SWE-bench. Overlap 5-gram: 35% vs 18%.
- **Pertinence:** **Contamination sérieuse.** Motive l'utilisation de FeatureBench (plus récent, moins contaminé).
- **URL:** https://arxiv.org/abs/2506.12286

### 4.3 Dissecting the SWE-Bench Leaderboards
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2506.17208
- **Contribution:** Analyse des 80 approches uniques. Classification Agentless/workflow, SWE-Agent/autonome, Hybrid/multi-agent. Les designs retrieval-augmented et hybrides sont communs parmi les top performers.
- **URL:** https://arxiv.org/abs/2506.17208

### 4.4 Saving SWE-Bench: A Benchmark Mutation Approach
- **Authors:** Microsoft
- **Year/Venue:** 2025, arXiv (CAIN 2026)
- **Ref:** arXiv:2510.08996
- **Contribution:** Transforme les descriptions formelles en requêtes utilisateur réalistes. Les benchmarks actuels surestiment les capacités de >50%.
- **URL:** https://arxiv.org/abs/2510.08996

---

## 5. Études de Coût / Efficience Tokens

### 5.1 How Do Coding Agents Spend Your Money?
- **Venue:** OpenReview 2025
- **Contribution:** Analyse tokens OpenHands/SWE-bench. Tâches complexes = variance 10x. Input tokens dominent même avec caching.
- **Pertinence:** Le retrieval chirurgical réduit les input tokens — le principal poste de coût.
- **URL:** https://openreview.net/forum?id=1bUeVB3fov

### 5.2 Tokenomics: Quantifying Where Tokens Are Used in Agentic Software Engineering
- **Year/Venue:** 2026, arXiv
- **Ref:** arXiv:2601.14470
- **Contribution:** Code Review = 59.4% des tokens. Input tokens = 53.9% de la consommation totale. Le coût principal n'est pas la génération initiale mais le refinement/vérification automatisé.
- **Pertinence:** **Réduire le contexte inutile en phase exploration réduit le poste de coût dominant.**
- **URL:** https://arxiv.org/abs/2601.14470

---

## 6. Métriques Recommandées (Synthèse)

| Métrique | Utilisée dans | Ce qu'elle mesure |
|----------|---------------|-------------------|
| **Resolve rate** | SWE-bench, FeatureBench, FeatBench | % de tâches entièrement résolues |
| **F2P (Fail-to-Pass)** | FeatureBench, FeatBench | Tests qui doivent passer de fail à pass |
| **P2P (Pass-to-Pass)** | FeatureBench, FeatBench | Détection de régressions |
| **Passed rate** | FeatureBench | Fraction moyenne de tests F2P passés (crédit partiel) |
| **Token IO** | FeatureBench, Tokenomics | Tokens input + output consommés |
| **Coût ($)** | Agentless, RTFM A/B | Coût dollar par tâche |
| **Latence/Durée** | RTFM A/B | Temps wall-clock |
| **File localization precision/recall** | SWE-PolyBench | L'agent identifie-t-il les bons fichiers ? |

---

## Références bibliographiques

1. Jimenez, C.E., Yang, J., Wettig, A., Yao, S., Pei, K., Press, O., & Narasimhan, K. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.
2. OpenAI & Princeton NLP (2024). SWE-bench Verified. https://openai.com/index/introducing-swe-bench-verified/
3. Deng, Y. et al. (2025). SWE-Bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks? arXiv:2509.16941.
4. Zhang, L. et al. (2025). SWE-bench Goes Live! arXiv:2505.23419.
5. (2025). SWE-Bench-CL: Continual Learning for Coding Agents. arXiv:2507.00014.
6. (2026). FeatureBench: Benchmarking Agentic Coding for Complex Feature Development. ICLR 2026. arXiv:2602.10975.
7. (2025). FeatBench: Evaluating Coding Agents on Feature Implementation for Vibe Coding. arXiv:2509.22237.
8. (2025). HumanEval Pro / MBPP Pro. ACL 2025 Findings. arXiv:2412.21199.
9. CrossCodeEval. NeurIPS 2023. https://openreview.net/forum?id=wgDcbBMSfh
10. (2024). RepoBench. ICLR 2024. arXiv:2306.03091.
11. (2025). LiveCodeBench. ICLR 2025. arXiv:2403.07974.
12. (2025). DevBench. arXiv:2601.11895.
13. OpenAI (2024). MLE-bench. arXiv:2410.07095.
14. Amazon (2025). SWE-PolyBench. arXiv:2504.08703.
15. (2025). SWE-Compass. arXiv:2511.05459.
16. (2025). NL2Repo-Bench. arXiv:2512.12730.
17. Gauthier, P. Aider Polyglot Leaderboard. https://aider.chat/docs/leaderboards/
18. Letta (2025). Context-Bench. https://www.letta.com/blog/context-bench
19. (2025). ContextBench: A Benchmark for Context Retrieval in Coding Agents. arXiv:2602.05892.
20. (2025). SWE Context Bench. arXiv:2602.08316.
21. (2025). UTBoost: Rigorous Evaluation on SWE-Bench. ACL 2025. arXiv:2506.09289.
22. Liang, S., Garg, S., & Moghaddam, R.Z. (2025). The SWE-Bench Illusion. arXiv:2506.12286.
23. (2025). Dissecting the SWE-Bench Leaderboards. arXiv:2506.17208.
24. Microsoft (2025). Saving SWE-Bench. CAIN 2026. arXiv:2510.08996.
25. (2025). How Do Coding Agents Spend Your Money? OpenReview.
26. (2026). Tokenomics: Quantifying Where Tokens Are Used. arXiv:2601.14470.
