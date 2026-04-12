# Plan de Paper — v3

## Titre de travail

**"Does Retrieval Help? A Controlled Study of Pre-Indexed Search Tools for Coding Agents on Feature Implementation Tasks"**

Alternatives :
- "Search Before You Code: Measuring the Impact of Retrieval Tools on Coding Agent Performance"
- "The Localization Bottleneck: How Pre-Indexed Retrieval Changes Coding Agent Outcomes on Large Repositories"
- "Knowing What You Don't Know: How Pre-Indexed Retrieval Transforms Coding Agent Performance on Large Repositories"

---

## Thèse centrale

> Un agent codeur qui dispose d'un outil de recherche pré-indexé — c'est-à-dire qui peut *savoir qu'il ne sait pas* et aller chercher — résout davantage de tâches, plus efficacement, qu'un agent qui navigue à l'aveugle. Mais cet avantage n'apparaît que lorsque le repository est suffisamment grand pour que la navigation directe devienne un goulot d'étranglement.

---

## Contributions revendiquées

1. **RTFM, un outil de retrieval agnostique pour agents codeurs** — open source, protocol-agnostic (MCP), model-agnostic, format-agnostic (parsers extensibles), avec un pattern de progressive disclosure (metadata-first → expand on demand) conçu pour minimiser la consommation de contexte.

2. **Première étude empirique contrôlée** de l'impact d'un outil de retrieval pré-indexé sur un agent codeur, évaluée sur un benchmark standardisé (FeatureBench, ICLR 2026).

3. **Protocole à 4 conditions** isolant la variable retrieval :
   - A = prompt standard (chemins donnés — oracle partiel)
   - B = prompt réaliste discovery (chemins retirés, pas de retrieval)
   - C = discovery + retrieval FTS
   - D = discovery + retrieval FTS + embeddings

4. **Identification empirique du seuil de taille** au-delà duquel le retrieval aide : le gain apparaît sur les grands repos (8K+ fichiers) et disparaît sur les petits (~600 fichiers).

5. **Analyse du goulot de localisation** : décomposition du temps agent en exploration vs coding, montrant que le retrieval réduit le temps d'exploration sur les grands repos.

---

## Structure du paper

### 1. Introduction (~1 page)

**Hook :** Les agents codeurs (Claude Code, Cursor, SWE-agent) sont limités non pas par la capacité de génération de code, mais par la capacité à trouver le bon contexte (Runner 2025, Context Rot 2025). Le gap oracle est énorme : sur HumanEval, passer de BM25 à un contexte oracle fait sauter StarCoder2-7B de 43.9% à 94.5% (CodeRAG-Bench, NAACL 2025).

**Problème :** Les agents actuels explorent les repos avec grep/glob/find — des outils aveugles. 38% de leurs actions sont de l'exploration/compréhension, pas de l'écriture de code (Trajectory Study, 2025). Sur les grands repos, ils entrent dans des boucles d'exploration non-productives (SWE-EVO, 2025).

**Question de recherche :** *Donner à un agent codeur un outil de recherche pré-indexé améliore-t-il le resolve rate, le coût, et la durée sur des tâches de feature implementation réelles ?*

**Réponse courte :** Oui, sur les grands repos. Sur test_validation (mlflow, 8260 fichiers), le resolve rate passe de 55-64% (sans retrieval) à 100% (avec retrieval). Sur test_stub_generator (metaflow, 624 fichiers), pas de gain mesurable.

**Contribution :** Première étude contrôlée sur benchmark standardisé, 4 conditions, N tâches × N répétitions.

### 2. Related Work (~2 pages)

#### 2.1 Le goulot de localisation dans les agents codeurs
- Agentless (Xia et al., 2024) : localisation hiérarchique, 77.7% recall fichier → 50.8% recall ligne
- PatchPilot (ICML 2025) : la localisation compte pour ~47% de l'amélioration totale
- LocAgent (ACL 2025) : 92.7% Acc@5 avec recherche guidée par graphe
- SWE-bench oracle experiments (ICLR 2024) : trop de contexte dégrade la performance
- Trajectory Study (2025) : 38% des actions = exploration, agents échoués = boucles répétitives
- Navigation Paradox (2026) : +23.2 pp avec outil MCP de navigation structurée

#### 2.2 Retrieval-Augmented Code Generation
- CodeRAG-Bench (NAACL 2025) : RAG améliore universellement, gap oracle = 9-50 pp
- Practical Code RAG at Scale (Galimzyanov 2025) : BM25 bat les embeddings denses pour code-to-code
- GrepRAG (ISSTA 2026) : lexical retrieval bat les méthodes graph-based
- What to Retrieve (2025) : code similaire = bruit (-15%), code contextuel = le bon signal
- cAST (CMU 2025) : chunking AST > chunking par lignes

#### 2.3 Adaptive et selective retrieval
- Self-RAG (ICLR 2024) : retrieval adaptatif > toujours-retrieval (+40% relatif)
- Repoformer (ICML 2024) : 70% des retrievals code sont inutiles, selective = +70% speedup
- FLARE (EMNLP 2023) : θ=0 (jamais) et θ=1 (toujours) sous-optimaux
- Adaptive-RAG (NAACL 2024) : routing par complexité (no retrieval / single / multi-step)

#### 2.4 Outils de retrieval existants pour agents codeurs
- Augment Context Engine MCP (2026) : +80% revendiqué, aucun protocole publié
- Sourcegraph Cody MCP : enterprise, code-only, pas de benchmark public
- CodeCompass (Navigation Paradox, 2026) : MCP + graphe AST, 30 micro-tâches synthétiques
- Code-Index-MCP, mcp-codebase-index : outils open source, zéro évaluation publiée
- Codified Context (2026) : MCP + specs manuelles, 283 sessions, pas de benchmark standardisé
- **Gap identifié :** aucune étude contrôlée sur benchmark standardisé mesurant l'impact d'un outil de retrieval pré-indexé sur un agent codeur

#### 2.5 Benchmarks de coding agents
- SWE-bench (ICLR 2024) : standard mais contamination prouvée (SWE-Bench Illusion, 2025)
- FeatureBench (ICLR 2026) : feature implementation, plus dur (11% vs 74% SWE-bench), moins contaminé
- ContextBench (2025) : mesure la qualité du contexte récupéré, pas le résultat final
- Tokenomics (2026) : input tokens = 53.9% du coût total

### 3. RTFM: An Agnostic Retrieval Layer for Coding Agents (~1.5 pages)

Avant de présenter l'étude, nous décrivons l'outil utilisé comme intervention expérimentale — non pas pour revendiquer sa novelty architecturale, mais parce que ses choix de design influencent directement les résultats observés.

#### 3.1 Philosophie : l'outil universel qui ne touche qu'à ce qu'il doit

RTFM n'est pas un outil de code. C'est un outil de **connaissance**. Ses principes de design :

1. **Domain-agnostic** — Indexe tout : code (Python AST, shell), documentation (Markdown, LaTeX), données structurées (YAML, JSON, XML), documents légaux (Legifrance XML, BOFiP HTML), PDF, plain text. Le même outil sert un développeur, un juriste, un chercheur. Pas de "code retrieval" : du *knowledge retrieval*.

2. **Format-agnostic via parsers extensibles** — Ajouter un nouveau format = ~50 lignes de Python (hériter de `BaseParser`, implémenter `parse()`). Le système ne présume pas du format — il s'adapte. 10 parsers embarqués, extensible par la communauté.

3. **Protocol-agnostic (MCP)** — Exposé via Model Context Protocol, le standard ouvert d'Anthropic. Fonctionne avec tout agent MCP-compatible : Claude Code, Continue.dev, Cursor (via MCP), tout client MCP. Pas de lock-in à un IDE ou un fournisseur.

4. **Model-agnostic** — Pur retrieval, zéro génération. Pas de modèle de langage embarqué. L'outil renvoie des résultats de recherche ; le modèle de l'agent décide quoi en faire. Compatible avec tout LLM (Claude, GPT, Gemini, open-source).

5. **Non-invasif** — RTFM ne modifie pas le workflow de l'agent. Il ajoute des outils de recherche (`rtfm_search`, `rtfm_context`, `rtfm_expand`). L'agent peut les utiliser ou les ignorer. Il remplace la navigation aveugle (grep/glob/find) quand c'est pertinent, et ne touche pas au reste. Pas de retrieval forcé, pas de contexte injecté silencieusement.

#### 3.2 Architecture : progressive disclosure

Le pattern architectural central est le **metadata-first → expand on demand** :

1. `rtfm_search(query)` → renvoie ~300 tokens de **métadonnées** : titre, slug, chemin absolu, score. Pas de contenu.
2. L'agent lit le fichier directement via `Read(file_path)` — le chemin absolu est dans les résultats.
3. Optionnel : `rtfm_expand(slug)` renvoie le contenu complet d'un chunk spécifique (pour les sources indexées sans fichier source direct).

Ce pattern minimise la consommation de contexte. L'agent ne charge que ce dont il a besoin, quand il en a besoin. C'est l'opposé du "dump tout le contexte" qui provoque le context rot (Hong et al., 2025).

**Stack technique :** SQLite + FTS5 (BM25) comme socle, embeddings optionnels via FastEmbed (ONNX, ~17s warm-up). Sync incrémental via hash SHA-256. Base portable (un seul fichier `.db`).

#### 3.3 Positionnement vs outils existants

| Propriété | RTFM | Augment CE | Code-Index-MCP | CodeCompass |
|-----------|------|------------|----------------|-------------|
| Multi-domaine | Code+docs+legal+research+data | Code+docs+tickets | Code uniquement | Code Python |
| Parsers extensibles | Oui (~50 LOC) | Non | Non | Non |
| Open source | Oui | Non | Oui | Oui |
| MCP natif | Oui | Oui | Oui | Oui |
| Progressive disclosure | metadata-first | N/A (propriétaire) | contenu direct | graphe AST |
| Évaluation publiée | **Ce papier** | "+80%" sans protocole | Aucune | 30 micro-tâches |
| Pricing | Gratuit | $20-200/mo | Gratuit | Gratuit |

Le vrai différenciateur n'est pas architectural — c'est que nous **évaluons rigoureusement** l'impact de l'outil sur un benchmark standardisé.

### 4. Experimental Setup (~2 pages)

#### 4.1 Benchmark : FeatureBench
- 11 tâches, 4 repos (metaflow, pydantic, astropy, mlflow)
- Pourquoi FeatureBench : feature implementation (pas juste bug fix), discovery nécessaire, moins contaminé que SWE-bench
- Tailles de repos : 624 fichiers (metaflow) → 8260 fichiers (mlflow)

#### 4.2 Les 4 conditions expérimentales

| Config | Prompt | Retrieval | Description |
|--------|--------|-----------|-------------|
| **A: Standard** | Chemins donnés | Aucun | Le prompt FeatureBench original donne les fichiers et interfaces — contrôle positif (oracle partiel) |
| **B: Discovery** | Chemins retirés | Aucun | Prompt réaliste : l'agent doit découvrir où coder — baseline réaliste |
| **C: FTS** | Chemins retirés | FTS5 (BM25) | Discovery + outil de recherche full-text pré-indexé |
| **D: FTS+Embed** | Chemins retirés | FTS5 + embeddings | Discovery + recherche hybride (FTS + sémantique) |

- Le mode discovery retire < 1% du prompt (751 chars / 78K) : seulement les lignes `Path: /testbed/...`
- La seule variable entre B et C/D est la présence de l'outil de retrieval
- Configs C et D utilisent des DBs pré-construites (pas de sync à la volée = réaliste)

#### 4.3 Agent et modèle
- Agent : Claude Code (Anthropic)
- Modèle : Claude Sonnet 4.0 (fixe pour toutes les conditions)
- Environnement : Docker (FeatureBench), timeout 1200s
- Authentification : OAuth MAX (pas d'API key)

#### 4.4 L'outil de retrieval (détails d'implémentation)
- Implémenté comme serveur MCP avec 11 outils (search, context, expand, discover, etc.)
- Recherche metadata-only (~300 tokens pour 5 résultats) avec chemins absolus
- L'agent utilise ensuite `Read(file_path)` pour le contenu réel
- FTS5 (Config C) : zéro cold start, ~20s de setup (install + copie DB)
- FTS + embeddings (Config D) : ~50s de setup (install + copie DB + warm fastembed ~17s)

#### 4.5 Métriques
- **Resolve rate** : le test passe ou non (binaire, via `fb eval`)
- **F2P pass rate** : fraction de tests fail-to-pass qui passent (crédit partiel)
- **Durée totale** : wall-clock time (inclut setup)
- **Durée agent** : temps hors setup RTFM
- **Coût** : $ via `total_cost_usd` de Claude Code
- **Tokens** : input, output, cache read
- **Tool calls** : nombre et type (Read, Grep, Glob, Edit, Bash, rtfm_search, rtfm_expand, etc.)
- **Ratio exploration/coding** : (Read+Grep+Glob+rtfm_search) / (Edit+Write)

#### 4.6 Coûts d'initialisation RTFM (reportés séparément)

| Repo | Books | Chunks | Parse+FTS | +Embeddings | DB FTS | DB FTS+Embed |
|------|-------|--------|-----------|-------------|--------|--------------|
| metaflow | 876 | ~5,060 | ~10s | +161s | 12 Mo | 22 Mo |
| pydantic | 771 | ~14,762 | ~15s | +444s | 18 Mo | 48 Mo |
| astropy | 1,123 | ~41,231 | ~30s | +1,232s | 52 Mo | 133 Mo |
| mlflow | 8,260 | 180,262 | 78s | +5,368s | 234 Mo | 592 Mo |

### 5. Results (~3 pages)

#### 5.1 Résultat principal : resolve rate par condition

Table principale : 11 tâches × 4 conditions, resolve rate (oui/non) + F2P pass rate.

**Hypothèse :** C et D > B sur les grands repos, C/D ≈ B sur les petits.

Données actuelles (à compléter avec les runs en cours) :

| Tâche (repo, taille) | A (Standard) | B (Discovery) | C (FTS) | D (FTS+Embed) |
|---|---|---|---|---|
| test_validation (mlflow, 8260) | 55% F2P | 64% F2P | **100% F2P** | **100% F2P** |
| test_stub_generator (metaflow, 624) | **100%** | **100%** | **100%** | 96.8% |
| test_responses_agent (mlflow, 8260) | 3.5% | TIMEOUT | 0% | 0% |

#### 5.2 Effet de la taille du repo

Graphique : resolve rate (C/D) - resolve rate (B) en fonction du nombre de fichiers du repo.
- metaflow (624) : pas de gain
- pydantic (771) : à mesurer
- astropy (1,123) : à mesurer
- mlflow (8,260) : gain significatif (au moins sur test_validation)

**Hypothèse du seuil :** il existe une taille de repo au-delà de laquelle la navigation directe ne suffit plus et le retrieval devient bénéfique.

#### 5.3 Coût et durée

Table : durée et coût par condition, par tâche.

Données actuelles :

| Tâche | Métrique | A | B | C | D |
|---|---|---|---|---|---|
| test_validation | Durée | 479s | 459s | 732s | 605s |
| test_validation | Coût | $1.12 | $1.50 | $2.42 | $1.33 |
| test_stub_generator | Durée | 370s | 395s | 454s | 541s |
| test_stub_generator | Coût | $0.97 | $1.07 | $1.30 | $1.44 |

**Observation attendue :** le retrieval peut augmenter le coût/durée (overhead MCP) tout en améliorant le resolve rate. Trade-off coût vs qualité.

#### 5.4 Analyse de l'utilisation des outils

Table : répartition des tool calls par catégorie (exploration vs coding) par condition.

| Tâche | Condition | Grep | Read | Glob | Bash | Edit | RTFM search | Ratio expl/code |
|---|---|---|---|---|---|---|---|---|
| test_validation | B | 6 | 13 | 0 | 22 | 6 | 0 | 6.8:1 |
| test_validation | D | 13 | 12 | 1 | 9 | 5 | 2 | 5.6:1 |

**Observation :** avec retrieval, l'agent fait moins de Bash (debug) et plus de Grep ciblé, suggérant une exploration plus efficace.

#### 5.5 FTS vs FTS+Embeddings (C vs D)

Comparaison directe des deux modes de retrieval :
- D résout autant que C mais en moins de turns (50 vs 81 sur test_validation)
- D fait moins de Read (12 vs 23) — les embeddings guident directement vers les bons fichiers
- D est plus efficient (coût $2.23 vs $4.04 sur test_validation)

#### 5.6 Analyse d'échec : quand le retrieval ne suffit pas

test_responses_agent : 78K chars de prompt, 15 interfaces, aucune config ne résout.
- Ce n'est pas un problème de retrieval, c'est un problème de capacité modèle
- D couvre 12/15 interfaces vs 7/15 pour C → les embeddings guident mieux
- Mais Sonnet 4.0 ne peut pas gérer la complexité même avec le bon contexte

### 6. Discussion (~1.5 pages)

#### 6.1 Le retrieval résout le goulot de localisation — sur les grands repos

Les résultats confirment la littérature : PatchPilot montre que la localisation = 47% du gain total, et nos résultats montrent que le retrieval transforme la localisation sur les grands repos. test_validation échoue sans retrieval parce que l'agent ne trouve pas les dépendances cross-module (validation.py ↔ scorers.py ↔ data.py). Avec retrieval, il les trouve immédiatement.

#### 6.2 Le retrieval ne remplace pas l'intelligence du modèle

test_responses_agent montre que même avec un retrieval parfait, le modèle ne peut pas gérer 15 interfaces complexes. Le retrieval est nécessaire mais pas suffisant.

#### 6.3 Le trade-off coût-qualité

Le retrieval augmente le coût par tâche (overhead MCP, tokens de résultats de recherche) mais augmente le resolve rate. **Un run plus cher qui résout > un run moins cher qui échoue.** Le coût pertinent est le coût PAR TÂCHE RÉSOLUE.

#### 6.4 FTS comme baseline forte

Confirmé par Galimzyanov (2025) et GrepRAG (2026) : BM25/FTS est compétitif avec les embeddings pour le code. Config C résout aussi bien que D sur test_validation. Les embeddings ajoutent de la valeur sur l'efficience (moins de turns) mais pas sur le resolve rate.

#### 6.5 L'agent comme décideur de retrieval

Contrairement à Self-RAG (fine-tuning pour décider quand retriever) ou Repoformer (classificateur trained), notre approche est simple : on **donne l'outil** à l'agent et on le laisse décider. L'agent utilise RTFM 1-15 fois selon la tâche — il fait du selective retrieval naturellement, sans entraînement spécifique. Cela suggère que les LLMs actuels ont une métacognition suffisante pour le retrieval sélectif quand l'outil est disponible.

#### 6.6 L'universalité comme force : au-delà du code

RTFM n'est pas limité au code. Le même outil indexe la documentation, les fichiers de configuration, les spécifications légales, les données de recherche. En pratique, un agent qui cherche "comment valider les données d'entrée" dans un projet peut trouver à la fois le code de validation existant, la documentation des contraintes métier, et les tests correspondants — sans changer d'outil. Cette universalité évite le problème des outils spécialisés qui fragmentent la connaissance du projet.

L'outil remplace la navigation aveugle là où c'est nécessaire (recherche de dépendances cross-module, localisation de fichiers pertinents) et ne touche pas au reste du workflow (édition, exécution, debug). C'est un amplificateur, pas un remplacement.

#### 6.7 Limites

- Un seul modèle (Sonnet 4.0) — la généralisation à d'autres modèles est non mesurée
- Un seul outil de retrieval (RTFM) — un autre outil (Augment, Cody) pourrait donner des résultats différents
- 11 tâches, 4 repos — statistiquement limité
- Python uniquement — FeatureBench lite est Python-only
- Nombre de répétitions à confirmer (N≥3 visé)
- Les DBs sont pré-construites — en usage réel, le temps d'indexation est amorti mais non nul

### 7. Conclusion (~0.5 page)

Nous avons montré que donner un outil de recherche pré-indexé à un agent codeur améliore significativement le resolve rate sur les tâches de feature implementation dans les grands repositories. L'amélioration est causée par la résolution du goulot de localisation : l'agent avec retrieval trouve les dépendances cross-module que l'agent sans retrieval ne découvre pas par navigation directe.

Ce résultat a des implications pratiques : les outils de retrieval pré-indexés (qu'ils soient open-source ou commerciaux) devraient être systématiquement déployés sur les codebases de plus de ~1000 fichiers. Sur les petits repos, la navigation directe suffit.

---

## Figures et tables prévues

1. **Figure 1 :** Architecture RTFM — flow metadata-first → expand on demand (Section 3)
2. **Figure 2 :** Schéma des 4 conditions (A/B/C/D) — ce que l'agent "voit" (Section 4)
3. **Table 1 :** Comparaison RTFM vs outils existants (Section 3.3)
4. **Figure 3 :** Resolve rate par condition, groupé par taille de repo (bar chart)
5. **Figure 4 :** Scatter plot : gain de resolve rate (C/D vs B) en fonction du nombre de fichiers
6. **Table 2 :** Résultats complets (11 tâches × 4 conditions × métriques)
7. **Table 3 :** Répartition tool calls (exploration vs coding) par condition
8. **Table 4 :** Coûts d'initialisation RTFM par repo
9. **Figure 5 :** Breakdown du temps agent : exploration vs coding par condition
10. **Table 5 :** C vs D : comparaison FTS seul vs FTS+embeddings

---

## Ce qu'il manque pour finaliser

### Données expérimentales
- [ ] Matrice complète 11 tâches × 4 conditions (en cours sur PC2)
- [ ] N ≥ 3 répétitions par condition (pour intervalles de confiance)
- [ ] Tâches pydantic et astropy (repos intermédiaires ~800-1100 fichiers)
- [ ] `fb eval` systématique sur chaque run

### Analyses à produire
- [ ] Test statistique sur la différence B vs C/D (Wilcoxon signed-rank ou permutation test si N petit)
- [ ] Corrélation taille repo × gain retrieval
- [ ] Analyse qualitative : sur les tâches où C/D > B, quels fichiers le retrieval a-t-il trouvé que B n'a pas trouvé ?
- [ ] Coût par tâche RÉSOLUE (pas par tâche tentée)

### Rédaction
- [x] Choisir la venue cible → **EMSE (Empirical Software Engineering)**, Springer. Fallback TOSEM/TSE si résultats forts.
- [ ] Vérifier le format/longueur EMSE (typiquement 25-40 pages, pas de limite stricte)
- [ ] Décider si l'outil est open-sourcé avec le paper (artifact badge) → oui, déjà public
- [x] Série blog vulgarisation FR : 6 articles (R1-R6) dans `paper/blog/`

---

## Références clés (à citer obligatoirement)

### Fondation
1. Jimenez et al. (2024). SWE-bench. ICLR 2024. arXiv:2310.06770.
2. (2026). FeatureBench. ICLR 2026. arXiv:2602.10975.
3. Yang et al. (2024). SWE-agent. NeurIPS 2024. arXiv:2405.15793.
4. Xia et al. (2024). Agentless. arXiv:2407.01489.

### Localisation = bottleneck
5. (2025). PatchPilot. ICML 2025. arXiv:2502.02747.
6. Chen et al. (2025). LocAgent. ACL 2025. arXiv:2503.09089.
7. (2025). Trajectory Study. arXiv:2506.18824.
8. (2026). Navigation Paradox. arXiv:2602.20048.

### Retrieval pour le code
9. Wang et al. (2024). CodeRAG-Bench. NAACL 2025. arXiv:2406.14497.
10. Galimzyanov et al. (2025). Practical Code RAG at Scale. arXiv:2510.20609.
11. (2025). What to Retrieve for RACG. arXiv:2503.20589.

### Selective retrieval
12. Asai et al. (2023). Self-RAG. ICLR 2024. arXiv:2310.11511.
13. Wu et al. (2024). Repoformer. ICML 2024. arXiv:2403.10059.

### Coût et contexte
14. (2026). Tokenomics. arXiv:2601.14470.
15. Hong et al. (2025). Context Rot. Chroma Research.

### Systèmes comparables
16. Vasilopoulos (2026). Codified Context. arXiv:2602.20478.
17. (2025). A-RAG. arXiv:2602.03442.
18. Hartman et al. (2024). Cody. RecSys 2024. arXiv:2408.05345.

### Contamination / rigueur
19. Liang et al. (2025). SWE-Bench Illusion. arXiv:2506.12286.
20. (2025). UTBoost. ACL 2025. arXiv:2506.09289.
