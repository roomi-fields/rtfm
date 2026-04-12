# SOTA 5 — Context-Aware Retrieval vs Exploration à l'Aveugle

*Angle : un agent avec outils de recherche vs un agent qui navigue à l'aveugle. Preuves empiriques.*

---

## 1. L'outil de recherche EST le différenciateur de performance

### 1.1 SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering
- **Authors:** Yang, Jimenez et al. (Princeton)
- **Year/Venue:** 2024, NeurIPS 2024
- **Ref:** arXiv:2405.15793
- **Ablation clé:** Retirer les outils de recherche = **-10.7 points de pourcentage**. Shell-only ~2%, avec ACI de recherche 12.5%.
- **URL:** https://arxiv.org/abs/2405.15793

### 1.2 SWE-Search: Enhancing Software Agents with MCTS
- **Year/Venue:** 2025, ICLR 2025
- **Contribution:** Exploration structurée via Monte Carlo Tree Search = **+23% relatif** vs agents greedy standard.
- **URL:** https://openreview.net/forum?id=G7sIFXugTX

---

## 2. Le fossé oracle : combien reste-t-il à gagner ?

### 2.1 CodeRAG-Bench: Can Retrieval Augment Code Generation?
- **Authors:** Wang, Asai et al. (CMU)
- **Year/Venue:** 2024, NAACL 2025 Findings
- **Ref:** arXiv:2406.14497
- **Résultat frappant:**
  - HumanEval, StarCoder2-7B : sans retrieval 31.7% → BM25 43.9% → **contexte oracle 94.5%**
  - SWE-bench Lite, GPT-4o : sans retrieval 2.3% → meilleur retrieval 21.7% → **oracle 30.7%**
  - L'écart oracle-retrieval actuel = **9-50 pp selon le modèle**
- **Pertinence:** Chaque point de qualité de retrieval se traduit directement en performance. Le retrieval parfait triple les résultats.
- **URL:** https://arxiv.org/abs/2406.14497

---

## 3. ~40-60% des tokens d'exploration sont du gaspillage

### 3.1 AgentDiet: Trajectory Optimization for Coding Agents
- **Year/Venue:** 2025, arXiv
- **Contribution:** Réduction automatique des trajectoires = **-39.9% à -59.7% tokens d'input**, -21.1% à -35.9% de coût, **sans perte de performance**.
- **Pertinence:** Si 40-60% des tokens d'exploration sont inutiles, un outil qui front-load le contexte élimine ce gaspillage.

### 3.2 AGENTS.md Study
- **Year/Venue:** 2025, arXiv
- **Contribution:** Fournir un fichier de contexte structuré = **-28.64% runtime, -16.58% tokens de sortie**.
- **Pertinence:** Le simple fait de donner du contexte structuré à l'agent réduit significativement le temps et le coût.

---

## 4. Savoir QUAND chercher > toujours chercher

### 4.1 Self-RAG (voir SOTA 4 §1.1 pour détails complets)
- **Résultat clé pour cet angle:** Retrieval adaptatif vs toujours-retrieval = **+40% relatif** sur PopQA.
- **Le retrieval indiscriminé DÉGRADE la performance.**

### 4.2 UoT: Uncertainty of Thoughts
- **Year/Venue:** 2024, NeurIPS 2024
- **Contribution:** Modélisation explicite de l'incertitude = **+38.1% taux de complétion** vs prompting direct.
- **Pertinence:** Quand l'agent modélise son incertitude, il sait mieux quand chercher.

### 4.3 FLARE (voir SOTA 4 §2.1 pour détails complets)
- **Résultat clé:** θ=0 (jamais retriever) et θ=1 (toujours retriever) sont tous deux sous-optimaux. Le sweet spot est adaptatif.

---

## 5. Les LLMs ne savent PAS ce qu'ils ne savent pas

### 5.1 Ackerman et al. — Metacognition in LLMs
- **Year/Venue:** 2025, arXiv
- **Contribution:** Les LLMs montrent des capacités métacognitives croissantes mais **limitées en résolution, dépendantes du contexte, et qualitativement différentes de l'humain**. Ils échouent à l'auto-évaluation fine.
- **Implication RTFM:** L'agent n'a pas besoin de *savoir* ce qu'il ne sait pas s'il peut *vérifier* à faible coût via un outil de retrieval. L'outil externe = prothèse métacognitive.

---

## 6. Le gap de consolidation : voir ≠ utiliser

### 6.1 ContextBench: A Benchmark for Context Retrieval in Coding Agents
- **Year/Venue:** 2025, arXiv
- **Ref:** arXiv:2602.05892
- **Résultat frappant:** Même quand les agents trouvent le bon contexte (AUC-Cov > 0.70), seuls **50-70%** de l'evidence est retenue dans le contexte final.
  - Claude Sonnet 4.5 : **20% de perte**
  - Gemini 2.5 Pro : **43% de perte**
- **Implication:** Les agents "voient" le code critique mais ne l'*utilisent* pas. Un outil qui sert du contexte **minimal et ciblé** (metadata-first) pourrait outperformer un dump massif.
- **URL:** https://arxiv.org/abs/2602.05892

---

## 7. Connexion directe à la thèse du paper

| Trouvaille empirique | Source | Implication |
|---|---|---|
| Outil de recherche = +10.7 pp | SWE-agent (NeurIPS 2024) | Le retrieval en tant qu'outil MCP est le bon pattern |
| Gap oracle = 50+ pp (petits modèles) | CodeRAG-Bench (NAACL 2025) | Mieux retriever = impact direct sur la qualité |
| Localisation hiérarchique bat la navigation | Agentless (2024) | search → expand = exactement le bon pattern |
| 40-60% tokens gaspillés en exploration | AgentDiet (2025) | Metadata-first évite de charger du contexte inutile |
| Retrieval adaptatif > toujours-retrieval | Self-RAG (ICLR 2024) | Donner le choix > forcer l'usage |
| LLMs ne se connaissent pas (métacognition limitée) | Ackerman (2025) | Outil externe comme prothèse métacognitive |
| Gap de consolidation (voir ≠ utiliser) | ContextBench (2025) | Contexte minimal et précis > dump massif |

---

## Références bibliographiques

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
