# SOTA 4 — Adaptive & Selective Retrieval : Savoir Quand Chercher

*Angle central : au lieu de toujours retriever ou jamais retriever, l'agent a le CHOIX de chercher quand il reconnaît qu'il manque d'information.*

---

## 1. Self-RAG et Descendants (Retrieval par Auto-Réflexion)

### 1.1 Self-RAG (papier fondateur)
- **Titre:** Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection
- **Auteurs:** Akari Asai, Zeqiu Wu, Yizhong Wang, Avirup Sil, Hannaneh Hajishirzi
- **Year/Venue:** 2023, ICLR 2024 (Oral, top 1%)
- **Ref:** arXiv:2310.11511
- **Mécanisme:** Le LM génère des **reflection tokens** spéciaux : `[Retrieve]` (faut-il chercher ?), `[IsREL]` (pertinent ?), `[IsSUP]` (supporté ?), `[IsUSE]` (qualité). Décision **à chaque segment**.
- **Résultats:** Self-RAG 7B/13B surpasse ChatGPT et Llama2-chat+RAG sur QA ouvert et vérification factuelle.
- **Pertinence code:** Les reflection tokens sont transposables aux agents code : décider à chaque étape si le contexte de repo est nécessaire.
- **URL:** https://arxiv.org/abs/2310.11511 | https://selfrag.github.io/

### 1.2 Self-BioRAG (spécialisation biomédicale)
- **Auteurs:** Jeong et al. (DMIS Lab)
- **Year/Venue:** 2024, ISMB/ECCB 2024, Bioinformatics
- **Ref:** arXiv:2401.15269
- **Résultats:** +7.2% amélioration absolue sur le meilleur modèle open 7B.
- **URL:** https://arxiv.org/abs/2401.15269

### 1.3 Auto-RAG (retrieval itératif autonome)
- **Titre:** Auto-RAG: Autonomous Retrieval-Augmented Generation for Large Language Models
- **Auteurs:** Tian Yu, Shaolei Zhang, Yang Feng
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2411.19443
- **Mécanisme:** Interaction LLM-retriever modélisée comme **dialogue multi-tour**. Le LLM décide quand et quoi récupérer, ajuste le nombre d'itérations selon la difficulté, s'arrête quand il a assez d'info.
- **Résultats:** Performances supérieures sur 6 benchmarks ; le nombre d'itérations s'adapte à la complexité.
- **Pertinence code:** Très proche du workflow d'un agent code (search → read → refine → search again).
- **URL:** https://arxiv.org/abs/2411.19443

---

## 2. FLARE et Active Retrieval (Retrieval Pendant la Génération)

### 2.1 FLARE (Forward-Looking Active REtrieval)
- **Titre:** Active Retrieval Augmented Generation
- **Auteurs:** Zhengbao Jiang, Frank Xu, Luyu Gao, Zhiqing Sun, Qian Liu, Jane Dwivedi-Yu, Yiming Yang, Jamie Callan, Graham Neubig
- **Year/Venue:** 2023, EMNLP 2023
- **Ref:** arXiv:2305.06983
- **Mécanisme:** Pendant la génération, si des **tokens à faible confiance** sont détectés, FLARE utilise la phrase comme query pour récupérer des documents, puis régénère. Itératif.
- **Résultats:** Supérieur ou compétitif sur 4 tâches de génération longue knowledge-intensive.
- **Pertinence code:** Un agent code pourrait détecter ses "zones d'incertitude" (APIs inconnues, patterns architecturaux) et chercher du contexte spécifiquement.
- **URL:** https://arxiv.org/abs/2305.06983

### 2.2 DRAGIN (Dynamic Retrieval based on Information Needs)
- **Titre:** DRAGIN: Dynamic Retrieval Augmented Generation based on the Real-time Information Needs of Large Language Models
- **Auteurs:** Weihang Su, Yichen Tang, Qingyao Ai, Zhijing Wu, Yiqun Liu
- **Year/Venue:** 2024, ACL 2024 (Oral)
- **Ref:** arXiv:2403.10081
- **Mécanisme:** **RIND** (Real-time Information Needs Detection) mesure l'incertitude du LLM pour décider QUAND. **QFS** (Query Formulation based on Self-Attention) détermine QUOI retriever.
- **Résultats:** Surpasse FLARE et toutes les méthodes dynamiques.
- **Pertinence code:** Détection en temps réel des besoins d'information = exactement ce qu'un agent code devrait faire.
- **URL:** https://arxiv.org/abs/2403.10081

### 2.3 DeepRAG (Retrieval comme MDP)
- **Titre:** DeepRAG: Thinking to Retrieve Step by Step for Large Language Models
- **Auteurs:** Xinyan Guan, Jiali Zeng et al.
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2502.01142
- **Mécanisme:** Raisonnement augmenté par retrieval modélisé comme **Markov Decision Process (MDP)**. Décision binaire atomique à chaque étape : récupérer OU s'appuyer sur le savoir paramétrique.
- **Résultats:** +21.99% efficacité de retrieval, +26.4% précision.
- **URL:** https://arxiv.org/abs/2502.01142

---

## 3. Adaptive-RAG (Adaptation selon la Complexité)

### 3.1 Adaptive-RAG
- **Titre:** Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity
- **Auteurs:** Soyeong Jeong, Jinheon Baek, Sukmin Cho, Sung Ju Hwang, Jong Park
- **Year/Venue:** 2024, NAACL 2024
- **Ref:** arXiv:2403.14403
- **Mécanisme:** Un **classificateur (petit LM)** route vers 3 stratégies : (A) pas de retrieval (questions simples), (B) retrieval single-step (modérées), (C) retrieval multi-step itératif (complexes).
- **Résultats:** Évite l'overhead sur les questions simples, maintient la précision sur les complexes.
- **Pertinence code:** Directement applicable : "Quelle est la valeur de X ?" → pas de retrieval vs "Comment ce projet gère-t-il les transactions distribuées ?" → multi-step.
- **URL:** https://arxiv.org/abs/2403.14403

### 3.2 UAR (Unified Active Retrieval)
- **Titre:** Unified Active Retrieval for Retrieval Augmented Generation
- **Auteurs:** Qinyuan Cheng et al.
- **Year/Venue:** 2024, Findings of EMNLP 2024
- **Ref:** arXiv:2406.12534
- **Mécanisme:** 4 critères orthogonaux : Intent-aware, Knowledge-aware, Time-Sensitive-aware, **Self-aware** (le LLM a-t-il la connaissance interne ?). Unifiés dans un arbre de décision.
- **Pertinence code:** Le critère "self-aware" = savoir si on connaît déjà l'API ou la structure du projet.
- **URL:** https://arxiv.org/abs/2406.12534

---

## 4. Corrective RAG (Évaluation Post-Retrieval)

### 4.1 CRAG (Corrective RAG)
- **Titre:** Corrective Retrieval Augmented Generation
- **Auteurs:** Shi-Qi Yan, Jia-Chen Gu, Yun Zhu, Zhen-Hua Ling
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2401.15884
- **Mécanisme:** Évaluateur de retrieval léger juge la qualité des documents. Si >70% non pertinents → **actions correctives** (recherche web, décomposition-recomposition). Plug-and-play.
- **Résultats:** Surpasse le RAG standard en robustesse, fonctionne même quand le retrieval initial échoue.
- **URL:** https://arxiv.org/abs/2401.15884

### 4.2 ROWEN (Retrieve Only When Needed)
- **Titre:** Rowen: Adaptive Retrieval-Augmented Generation for Hallucination Mitigation in LLMs
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2402.10612
- **Mécanisme:** Génère une réponse initiale via CoT, puis un **module de détection de cohérence** évalue. Si incohérences → retrieval déclenché. Sinon → réponse conservée.
- **URL:** https://arxiv.org/abs/2402.10612

---

## 5. Retrieval Necessity Prediction (Prédire QUAND Retriever)

### 5.1 When to Retrieve / Adapt-LLM
- **Titre:** When to Retrieve: Teaching LLMs to Utilize Information Retrieval Effectively
- **Auteurs:** Tiziano Labruna, Jon Ander Campos, Gorka Azkune
- **Year/Venue:** 2024, arXiv (RANLP 2025)
- **Ref:** arXiv:2404.19705
- **Mécanisme:** Le LLM est fine-tuné pour générer un **token spécial `<RET>`** quand il ne connaît pas la réponse. Si `<RET>` → IR appelé. Sinon → réponse directe depuis la mémoire paramétrique.
- **Résultats:** Surpasse 3 baselines (toujours retriever, toujours mémoire, seuil popularité) sur PopQA.
- **Pertinence code:** **LE papier le plus directement pertinent.** Le mécanisme `<RET>` = la décision "should I search or should I code?"
- **URL:** https://arxiv.org/abs/2404.19705

### 5.2 SKR (Self-Knowledge Guided Retrieval)
- **Titre:** Self-Knowledge Guided Retrieval Augmentation for Large Language Models
- **Auteurs:** Yile Wang, Peng Li, Maosong Sun, Yang Liu
- **Year/Venue:** 2023, Findings of EMNLP 2023
- **Ref:** arXiv:2310.05002
- **Mécanisme:** Le LLM **reconnaît ce qu'il sait et ce qu'il ne sait pas** (self-knowledge). Décide adaptativement s'il faut des ressources externes.
- **Pertinence code:** L'idée de "self-knowledge" = savoir si on connaît ce repo ou s'il faut chercher.
- **URL:** https://arxiv.org/abs/2310.05002

---

## 6. Tool-Use Decision Making

### 6.1 Toolformer (papier fondateur)
- **Titre:** Toolformer: Language Models Can Teach Themselves to Use Tools
- **Auteurs:** Timo Schick, Jane Dwivedi-Yu et al. (Meta AI)
- **Year/Venue:** 2023, NeurIPS 2023
- **Ref:** arXiv:2302.04761
- **Mécanisme:** Fine-tuning auto-supervisé pour insérer des appels API. Critère : l'appel est gardé seulement s'il **réduit la perplexité sur les tokens futurs**.
- **Résultats:** GPT-J 6.7B + Toolformer surpasse GPT-3 (175B) en zero-shot.
- **Pertinence code:** Le critère de perplexité = signal pour "chercher du contexte réduit mon incertitude".
- **URL:** https://arxiv.org/abs/2302.04761

### 6.2 MeCo (Meta-Cognition Trigger for Adaptive Tool Use)
- **Titre:** Adaptive Tool Use in Large Language Models with Meta-Cognition Trigger
- **Year/Venue:** 2025, ACL 2025
- **Ref:** arXiv:2502.12961
- **Mécanisme:** Quantifie un **score métacognitif** à partir des représentations internes du LLM. Guide la décision d'invoquer un outil. Zero fine-tuning, coût minimal.
- **Résultats:** Détecte de manière fiable les signaux cognitifs internes.
- **Pertinence code:** **Très pertinent.** Détecte si le LLM "sait qu'il ne sait pas" — sans fine-tuning.
- **URL:** https://arxiv.org/abs/2502.12961

### 6.3 Gorilla (APIs massives)
- **Titre:** Gorilla: Large Language Model Connected with Massive APIs
- **Auteurs:** Shishir Patil et al. (UC Berkeley)
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2305.15334
- **Mécanisme:** LLaMA fine-tuné avec Retriever Aware Training (RAT) pour 1600+ APIs.
- **URL:** https://arxiv.org/abs/2305.15334

---

## 7. Calibration, Incertitude et Abstention

### 7.1 Know Your Limits (survey abstention)
- **Titre:** Know Your Limits: A Survey of Abstention in Large Language Models
- **Auteurs:** Bingbing Wen, Jihan Yao, Shangbin Feng et al.
- **Year/Venue:** 2025, TACL vol. 13
- **Ref:** arXiv:2407.18418
- **Contribution:** Survey exhaustif sur les méthodes d'abstention. Framework 3 perspectives : query, modèle, valeurs humaines.
- **Pertinence code:** Quand un agent devrait dire "je ne sais pas, laisse-moi chercher" plutôt que halluciner du code.
- **URL:** https://arxiv.org/abs/2407.18418

### 7.2 Do RALMs Know When They Don't Know?
- **Year/Venue:** 2024, arXiv
- **Ref:** arXiv:2509.01476
- **Contribution:** Quand tous les documents récupérés sont irrelevants, les RALMs tendent à **refuser des questions qu'ils auraient pu correctement répondre** (sur-refus).
- **Pertinence code:** Risque que l'agent cherche trop et devienne moins performant.
- **URL:** https://arxiv.org/abs/2509.01476

### 7.3 CalibRAG (Calibration-Oriented RAG)
- **Year/Venue:** 2024, arXiv (soumis ICLR 2025)
- **Ref:** arXiv:2411.08891
- **Contribution:** Retrieval qui assure des décisions **bien calibrées**.
- **URL:** https://arxiv.org/abs/2411.08891

### 7.4 Uncertainty Quantification in RAG
- **Year/Venue:** 2025, ICLR 2025
- **Contribution:** Jugements d'utilité de passages pour prédire la correction des réponses.
- **URL:** https://openreview.net/pdf?id=8r8H4gbFXf

---

## 8. Selective Retrieval Spécifique au Code

### 8.1 Repoformer — LE papier clé
- **Titre:** Repoformer: Selective Retrieval for Repository-Level Code Completion
- **Auteurs:** Di Wu, Wasi Uddin Ahmad, Dejiao Zhang, Murali Krishna Ramanathan, Xiaofei Ma (Amazon)
- **Year/Venue:** 2024, ICML 2024 (Oral)
- **Ref:** arXiv:2403.10059
- **Mécanisme:** Le code LM **auto-évalue** si le retrieval repo-level peut améliorer sa sortie. Si oui → retrieval. Sinon → abstention. Robuste au contexte bruité.
- **Résultats:** **>85% de précision dans les décisions de retrieval. Jusqu'à 70% d'accélération d'inférence** sans dégradation.
- **Pertinence code:** **C'est LE papier qui répond à "should I search or should I code?"** La démonstration que 70% des retrievals sont inutiles est un argument fort pour le retrieval sélectif.
- **URL:** https://arxiv.org/abs/2403.10059

### 8.2 RepoCoder (retrieval itératif)
- **Titre:** RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation
- **Auteurs:** Fengji Zhang et al. (Microsoft)
- **Year/Venue:** 2023, EMNLP 2023
- **Ref:** arXiv:2303.12570
- **Résultats:** +10% sur la baseline In-File.
- **URL:** https://arxiv.org/abs/2303.12570

### 8.3 CodeAgent (outils intégrés pour le code)
- **Year/Venue:** 2024, ACL 2024
- **Ref:** arXiv:2401.07339
- **Contribution:** Framework agent avec 5 outils de programmation. L'agent décide quel outil à chaque étape.
- **Résultats:** +18.1% à +250% selon les modèles.
- **URL:** https://arxiv.org/abs/2401.07339

---

## 9. Compression et Augmentation Sélective

### 9.1 RECOMP
- **Titre:** RECOMP: Improving Retrieval-Augmented LMs with Compression and Selective Augmentation
- **Auteurs:** Fangyuan Xu, Weijia Shi, Eunsol Choi
- **Year/Venue:** 2024, ICLR 2024
- **Ref:** arXiv:2310.04408
- **Mécanisme:** Compresse les documents récupérés en résumés. **Quand les documents sont irrelevants → chaîne vide** = augmentation sélective.
- **Résultats:** Compression jusqu'à 6% avec perte minimale.
- **Pertinence code:** Metadata-only search + expand on demand = exactement cette philosophie.
- **URL:** https://arxiv.org/abs/2310.04408

---

## 10. Papiers Fondateurs (Pré-2023)

### 10.1 RETRO
- **Auteurs:** Borgeaud et al. (DeepMind)
- **Year/Venue:** 2022, ICML 2022
- **Ref:** arXiv:2112.04426
- **Contribution:** Retrieval depuis 2 trillion tokens. Performance comparable à GPT-3 avec 25x moins de paramètres.
- **URL:** https://arxiv.org/abs/2112.04426

### 10.2 REALM
- **Auteurs:** Guu et al. (Google)
- **Year/Venue:** 2020, ICML 2020
- **Ref:** arXiv:2002.08909
- **Contribution:** Premier modèle RAG dynamique : retriever + générateur entraînés conjointement.
- **URL:** https://arxiv.org/abs/2002.08909

---

## Synthèse : Les 5 papiers les plus pertinents pour la thèse "savoir quand chercher"

| # | Papier | Pourquoi |
|---|--------|----------|
| 1 | **Repoformer** (Wu et al., ICML 2024) | Selective retrieval spécifique code ; 85% précision ; 70% speedup ; prouve que 70% des retrievals sont inutiles |
| 2 | **When to Retrieve / Adapt-LLM** (Labruna et al., 2024) | Token `<RET>` = exactement "should I search or should I code?" |
| 3 | **Self-RAG** (Asai et al., ICLR 2024) | Framework général : le modèle décide à chaque segment s'il doit chercher |
| 4 | **MeCo** (ACL 2025) | Méta-cognition sans fine-tuning : détecter si le LLM "sait qu'il ne sait pas" |
| 5 | **Adaptive-RAG** (Jeong et al., NAACL 2024) | Routing par complexité : no retrieval / single / multi-step |

### L'argument central pour le paper :
La littérature montre que le **retrieval systématique dégrade la performance** (bruit, latence, sur-refus) tandis que le **retrieval sélectif** améliore qualité ET efficacité. Repoformer démontre que **70% des retrievals en contexte code sont inutiles**. La thèse RTFM : au lieu de fine-tuner le modèle pour décider quand chercher, on lui **donne l'outil de recherche** et on observe s'il apprend à l'utiliser de manière sélective — et s'il performe mieux avec qu'avec la navigation à l'aveugle.

---

## Références bibliographiques

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
