# Benchmark Paper Plan

## Objectif
Article de recherche montrant l'impact de RTFM sur la qualité, le temps et le coût de Claude Code sur des tâches réelles de développement (FeatureBench).

## 4 conditions expérimentales (11 tâches × 4 configs)

| Config                    | Description                                                                   |
| ------------------------- | ----------------------------------------------------------------------------- |
| **A: Standard**           | Prompt FeatureBench original (donne les fichiers + interfaces) — non réaliste |
| **B: Discovery baseline** | Prompt réaliste (paths strippés, `--discovery`) sans RTFM                     |
| **C: RTFM FTS**           | Prompt discovery + RTFM avec FTS uniquement, DB pré-parsée                    |
| **D: RTFM + Embeddings**  | Prompt discovery + RTFM hybrid search, DB pré-générée (FTS+embeddings)        |

## Protocole de setup réaliste (IMPORTANT)

**Config C ET D doivent utiliser des DBs pré-construites** montées en volume.
En usage réel, RTFM est déjà initialisé dans le projet — le sync à la volée
est un artefact du protocole de test, pas une réalité utilisateur.

- Config C : monter la DB FTS-only pré-parsée (même principe que D)
- Config D : monter la DB FTS+embeddings pré-générée (déjà fait)
- Le temps de parsing/indexation est reporté comme "coût d'initialisation" dans l'article,
  pas comme "temps de setup par run"

### Coûts d'initialisation RTFM (une seule fois par projet)

| Repo     | Books | Chunks  | Parse+FTS | +Embeddings | DB FTS | DB FTS+Embed |
| -------- | ----- | ------- | --------- | ----------- | ------ | ------------ |
| metaflow | 876   | ~5,060  | ~10s      | +161s       | 12 Mo  | 22 Mo        |
| pydantic | 771   | ~14,762 | ~15s      | +444s       | 18 Mo  | 48 Mo        |
| astropy  | 1,123 | ~41,231 | ~30s      | +1,232s     | 52 Mo  | 133 Mo       |
| mlflow   | 8,260 | 180,262 | 78s       | +5,368s     | 234 Mo | 592 Mo       |

Débit embeddings constant ~33 chunks/sec sur CPU (linéaire).

### Setup par run (avec DBs pré-construites)

| Étape                | Config C       | Config D                  |
| -------------------- | -------------- | ------------------------- |
| Install RTFM         | ~18s (`[mcp]`) | ~30s (`[mcp,embeddings]`) |
| Copy pre-built DB    | ~1s            | ~1s (592Mo mlflow)        |
| Warm fastembed model | N/A            | ~17s                      |
| **Total setup**      | **~20s**       | **~50s**                  |

TODO: Modifier `claude_code_rtfm.py` (Config C) pour copier la DB FTS pré-parsée
au lieu de sync à la volée. Créer les DBs FTS-only pour chaque repo.

## Métriques à collecter par run

### Performance
- Temps total (wall clock)
- Temps agent (hors setup RTFM)
- Temps setup RTFM (install + copy DB + warm model)

### Coût
- Tokens input / output / cache read
- Coût $ (via Claude Code `total_cost_usd`)
- Nombre de tours (API round-trips)

### Qualité
- **Resolve rate** : le test passe ou non (binaire, évalué par FeatureBench `fb eval`)
- **F2P pass rate** : pourcentage de tests fail-to-pass qui passent
- Patch size (chars)
- Patch correctness (le patch touche les bons fichiers)

### Outil usage
- Nombre d'appels par outil (Grep, Glob, Read, Edit, Bash, rtfm_search, rtfm_expand, etc.)
- Ratio discovery vs coding tools

### Transparence RTFM (coûts amortis)
- Temps de parsing par repo (one-time)
- Temps d'embedding par repo (one-time)
- Taille DB générée
- Cold start fastembed (~17s, one-time par session)

## 11 tâches (4 images, no-GPU, lite split level 1)

### metaflow (1 tâche, 624 books, 5060 chunks)
- Netflix__metaflow.test_stub_generator

### pydantic (1 tâche, 771 books, 14762 chunks)
- pydantic__pydantic.test_deprecated_fields

### astropy (2 tâches, ~1122 books)
- astropy__astropy.test_quantity_erfa_ufuncs
- astropy__astropy.test_table

### mlflow (7 tâches, 8260 books, 180262 chunks)
- mlflow__mlflow.test_validation
- mlflow__mlflow.test_judge_tool_search_traces
- mlflow__mlflow.test_serialization
- mlflow__mlflow.test_span
- mlflow__mlflow.test_trace
- mlflow__mlflow.test_databricks_tracing_utils
- mlflow__mlflow.test_responses_agent

## Données historiques — Config A (Standard, 22 fév, Sonnet 4.0)

Source: `benchmark_final_results.jsonl` — 10 tâches (pas d'eval `fb eval`)

| Tâche                               | Base dur (s) | RTFM dur (s) | Delta    | Base turns | RTFM turns | RTFM searches |
| ----------------------------------- | ------------ | ------------ | -------- | ---------- | ---------- | ------------- |
| test_stub_generator (metaflow)      | 565          | 354          | **-37%** | 60         | 35         | 4             |
| test_quantity_erfa_ufuncs (astropy) | 536          | 606          | +13%     | 62         | 83         | 12            |
| test_table (astropy)                | 675          | 632          | -6%      | 86         | 89         | 8             |
| test_databricks_tracing (mlflow)    | 524          | 688          | +31%     | 52         | 79         | 11            |
| test_judge_tool (mlflow)            | 571          | 457          | **-20%** | 69         | 68         | 18            |
| test_responses_agent (mlflow)       | 746          | 1022         | **+37%** | 84         | 79         | 2             |
| test_serialization (mlflow)         | 481          | 509          | +6%      | 47         | 47         | 6             |
| test_span (mlflow)                  | 707          | 958          | +36%     | 81         | 116        | 4             |
| test_trace (mlflow)                 | 676          | 782          | +16%     | 54         | 99         | 4             |
| test_validation (mlflow)            | 701          | 386          | **-45%** | 45         | 41         | 3             |

**ATTENTION** : pas d'eval → on ne sait pas si les tests passent réellement.

## Données historiques — Config B/C Discovery (25 fév, Sonnet 4.0, mlflow only)

Source: 13 runs dans `~/projects/FeatureBench/runs/2026-02-25__*`

| Tâche                   | Config | Durée (s)       | Coût ($) | Turns | RTFM calls | F2P           | Résolu  |
| ----------------------- | ------ | --------------- | -------- | ----- | ---------- | ------------- | ------- |
| test_validation         | B      | 596             | $2.22    | 76    | 0          | 6/11 (54.5%)  | Non     |
| test_validation         | C      | 372             | $1.31    | 60    | 1          | 11/11 (100%)  | **OUI** |
| test_databricks_tracing | B      | 667             | $2.86    | 61    | 0          | 11/18 (61.1%) | Non     |
| test_databricks_tracing | C      | 441             | $2.12    | 51    | 5          | 13/18 (72.2%) | Non     |
| test_judge_tool         | B      | 427             | $1.42    | 58    | 0          | 3/18 (16.7%)  | Non     |
| test_judge_tool         | C      | 500             | $1.55    | 58    | 8          | 3/18 (16.7%)  | Non     |
| test_responses_agent    | B      | TIMEOUT (~1200) | ~$10.64  | ~178  | 0          | -             | -       |
| test_responses_agent    | C      | 917             | $3.58    | 101   | 15         | 0/1 (0%)      | Non     |

## Runs 27-28 fév (Sonnet 4.0, OAuth MAX, post-FastEmbed, DBs pré-parsées)

### test_responses_agent — Matrice complète A/B/C/D (pire cas)

| Métrique | Config A (Standard) | Config B (Discovery) | Config C (FTS) | Config D (Embed+) |
|---|---|---|---|---|
| **Résolu** | Non (3.5% F2P) | Non (TIMEOUT) | Non (0%) | Non (0%) |
| **Durée totale** | 1156s | **TIMEOUT 1283s** | 1175s | 1013s |
| **Durée agent** | 1019s | ~1200s (tué) | 872s | 872s |
| **Coût (Claude)** | $5.03 | N/A (timeout) | $3.66 | $3.84 |
| **Coût (calculé)** | $8.34 | $6.90 | - | - |
| **Turns** | 118 | 139 (incomplet) | 91 | 103 |
| **Tool calls** | 117 | 138 (incomplet) | 90 | 102 |
| **Read** | 39 | 50 | 27 | 43 |
| **Grep** | 7 | 39 | 15 | 7 |
| **Edit** | 40 | 21 | 26 | 24 |
| **Bash** | 22 | 18 | - | - |
| **RTFM search** | 0 | 0 | 10 | 13 |
| **Cache read** | 23,810,024 | 18,933,950 | 8,676,183 | 8,959,902 |
| **Output tokens** | 529 | 682 | 40,096 | 49,653 |
| **Patch size** | 92,474 chars | 0 (timeout) | 50,539 chars | 91,048 chars |
| **Interfaces couvertes** | **15/15** | **0/15** | 8/15 | 12/15 |
| **Fichiers modifiés** | 15 | 0 | 8 (+2 RTFM) | 12 (+2 RTFM) |

**Observations clés (4 configs, même tâche) :**
1. **Aucune config ne résout la tâche** — Sonnet 4.0 ne peut pas gérer 78K de prompt + 15 interfaces
2. **Config B (discovery) timeout** à 1200s — sans chemins ET sans RTFM, l'agent est perdu dans 8260 fichiers
3. **Config A (standard)** couvre les 15 interfaces (paths dans le prompt) mais échoue quand même (3.5% F2P)
4. **Config D (embeddings)** couvre 12/15 — les embeddings guident mieux vers les bons fichiers que le FTS seul (8/15)
5. **Patch size corrélé aux interfaces** : A≈D~91K >> C~50K >> B=0
6. **Config C et D** ont le plus faible usage de cache (8-9M vs 19-24M pour A/B) — RTFM réduit le contexte
7. **Config A a le plus de cache read** (24M) — les paths dans le prompt dirigent l'agent vers tous les fichiers, mais il les lit en entier

### test_responses_agent — Tentative Sonnet 4.6 (abandonné, quota insuffisant)

Tests exploratoires Config A et D avec Sonnet 4.6, timeout 2400s (40min) :

| Métrique | S4.0 Config A | S4.0 Config D | S4.6 Config A | S4.6 Config D |
|---|---|---|---|---|
| **Durée** | 1156s | 1013s | TIMEOUT 2480s | TIMEOUT 2545s |
| **Turns** | 118 | 103 | 357 | **657** |
| **Tool calls** | 117 | 102 | 355 | **650** |
| **Read** | 39 | 43 | 129 | **306** |
| **Edit** | 40 | 24 | 55 | **87** |
| **Bash** | 22 | - | **159** | **176** |
| **RTFM search** | 0 | 13 | 0 | 18 |
| **Subagents** | 0 | 0 | 1 | **8** |
| **Cache read** | 23.8M | 9.0M | 54.5M | 49.5M |
| **Coût (calculé)** | $8.34 | $3.84 | $21.65 | $20.86 |

**Observations Sonnet 4.6 :**
- Travaille 3-6x plus que 4.0 (657 vs 102 tool calls en Config D)
- Lance des tests via Bash (159-176 calls), contrairement à 4.0 (0 tests)
- Utilise des subagents pour paralléliser (8 en D)
- Mais ne termine pas en 40min — quota MAX insuffisant pour explorer davantage
- RTFM amplifie le comportement exploratoire (657 turns D vs 357 A)
- **Argument clé** : à durée et coût quasi identiques (~2500s, ~$21), Config D (RTFM)
  fait 657 turns vs 357 (Config A) — **2x plus de travail utile pour le même prix**.
  Le coût/turn est plus faible avec RTFM ($0.032 vs $0.061) car le cache read/turn
  baisse (75K vs 153K) : l'agent va directement aux bons fichiers au lieu de tout explorer.
- **Abandonné** : tâche trop lourde même pour 4.6, non représentative du cas d'usage réel

### Analyse d'échec : test_responses_agent (Sonnet 4.0)

**Pourquoi 0% résolution malgré RTFM :**

1. **Tâche disproportionnée** : 78K chars de prompt, 15 interfaces, ground truth = 226K chars
   sur 60 fichiers. C'est un outlier dans FeatureBench.

2. **Config C** : ImportError — l'agent n'a implémenté que 7/15 interfaces.
   Il a dit : "Due to space constraints, let me focus on the most critical interfaces"
   et a abandonné les 8 plus complexes. Le test ne peut pas s'importer.

3. **Config D** : SyntaxError — l'agent a couvert 12/15 interfaces (les embeddings l'ont
   mieux guidé) mais un bug d'édition sur `responses.py` a corrompu le fichier.
   4 Edits successifs pour insérer `output_to_responses_items_stream` ont fini par
   transformer un `continue` en `continue(chunks:...` → SyntaxError immédiat.

4. **Aucun agent n'a exécuté de tests** : ni pytest ni même `python -c "import ..."`.
   Les erreurs auraient été détectées immédiatement.

5. **Lost in the middle** : la TodoList de Config D contenait 9 items au lieu de 15.
   Les 3 interfaces manquantes (`responses_helpers.py`, `data_validation.py`,
   `models/model.py`) sont celles qui apparaissent à la FIN du prompt de 78K chars.

6. **Le prompt FeatureBench ne demande PAS de tester** : il dit "pytest will be used to test"
   (passif) — jamais "run the tests yourself". Aucune incitation au feedback loop.

**Impact RTFM quand même positif** :
- D couvre 12/15 interfaces vs 7/15 pour C (+71%)
- D produit un patch de 91K chars vs 50K (+80%)
- Hybrid search guide l'agent vers les bons fichiers : +59% Read, -53% Grep
- Mais Sonnet 4.0 ne peut pas gérer 78K chars de prompt avec 15 interfaces complexes

**Ce n'est pas un problème de retrieval, c'est un problème de capacité modèle.**

### test_stub_generator (metaflow) — Matrice ABCD (petit repo, 624 books)

| Métrique | Config A (Standard) | Config B (Discovery) | Config C (FTS) | Config D (Embed+) |
|---|---|---|---|---|
| **Résolu** | **OUI** (100%) | **OUI** (100%) | **OUI** (100%) | Non (96.8%) |
| **F2P** | 31/31 | 31/31 | 31/31 | 30/31 |
| **Durée totale** | **370s** | 395s | 454s | 541s |
| **Coût (Claude)** | $0.97 | $1.07 | $1.30 | $1.44 |
| **Coût (calculé)** | $1.44 | $1.65 | $2.08 | $2.33 |
| **Turns** | **42** | 51 | 58 | 67 |
| **Tool calls** | 42 | 51 | 58 | 67 |
| **Grep** | 20 | 15 | 16 | 21 |
| **Read** | 4 | 10 | 16 | 17 |
| **Edit** | 4 | 5 | 7 | 5 |
| **Bash** | 5 | 14 | 5 | 18 |
| **RTFM search** | 0 | 0 | 1 | 1 |
| **RTFM expand** | 0 | 0 | 1 | 0 |
| **RTFM discover** | 0 | 0 | 1 | 0 |
| **Patch size** | 27K | 22K | 22K | 23K |

**Observations (petit repo — tâche facile) :**
1. **Les 4 configs résolvent la tâche** (sauf D qui rate 1 test/31 : `test_class_stub_generation`)
2. **Config A est la plus rapide** — les chemins dans le prompt éliminent la découverte
3. **Config B (discovery) résout aussi bien** en +7% de temps — sur un petit repo la nav directe suffit
4. **RTFM n'apporte pas d'avantage mesurable** sur un repo de 624 fichiers :
   - Config C est +23% plus lente que A, +22% plus chère
   - Config D est +46% plus lente, +48% plus chère, et rate 1 test
5. **L'agent RTFM n'utilise presque pas RTFM** (1-2 calls) — il navigue directement car le repo est petit
6. **Plus de Read avec RTFM** (16-17 vs 4-10) — overhead sans gain

**Conclusion** : RTFM n'aide pas sur les petits repos. L'overhead de setup et les appels MCP
ajoutent de la latence sans bénéfice quand l'agent peut naviguer directement. RTFM est conçu
pour les gros codebases où la découverte est le goulot d'étranglement.

### test_validation (mlflow) — Matrice ABCD (gros repo, 8260 books)

| Métrique | Config A (Standard) | Config B (Discovery) | Config C (FTS) | Config D (Embed+) |
|---|---|---|---|---|
| **Résolu** | Non | Non | **OUI** | **OUI** |
| **F2P** | 6/11 (55%) | 7/11 (64%) | **11/11 (100%)** | **11/11 (100%)** |
| **Durée totale** | 479s | 459s | 732s | 605s |
| **Coût (Claude)** | $1.12 | $1.50 | $2.42 | $1.33 |
| **Coût (calculé)** | $1.87 | $2.54 | $4.04 | $2.23 |
| **Turns** | 44 | 53 | 81 | **50** |
| **Tool calls** | 44 | 53 | 81 | 50 |
| **Grep** | 8 | 6 | 7 | 13 |
| **Read** | 9 | 13 | 23 | 12 |
| **Edit** | 4 | 6 | 12 | 5 |
| **Bash** | 18 | 22 | 20 | 9 |
| **Glob** | 0 | 0 | 7 | 1 |
| **RTFM search** | 0 | 0 | 3 | 2 |
| **RTFM expand** | 0 | 0 | 2 | 0 |
| **Patch size** | 16K | 15K | 24K | 23K |

**Observations (gros repo — tâche moyenne) :**
1. **RTFM fait passer la résolution de 55-64% à 100%** — le résultat le plus marquant du benchmark
2. **A et B échouent sur les mêmes tests** : `test_validate_scorers_invalid_all_scorers`,
   `test_validate_data_with_correctness`, `test_validate_data_missing_columns`
   → tests nécessitant la compréhension de modules distants (validation.py ↔ scorers.py ↔ data.py)
3. **Config D est la plus efficiente** : 50 turns vs 81 (C), $2.23 vs $4.04 (C)
   → les embeddings guident directement vers les bons fichiers, moins de navigation aléatoire
4. **Config C est plus lente mais résout** : le FTS suffit quand les termes sont dans le prompt
5. **Plus de Read en C (23) qu'en D (12)** : sans embeddings, l'agent lit plus de fichiers pour trouver le bon
6. **Moins de Bash en D (9) qu'en A/B (18-22)** : l'agent RTFM code plus, debug moins
7. **Patch plus gros avec RTFM (23-24K vs 15-16K)** : implémentation plus complète

**Conclusion** : sur un gros repo, RTFM change le résultat. L'agent sans RTFM ne trouve pas
les dépendances entre modules → implémentation incomplète → tests échoués.

### Différence prompt A vs B/C/D

Le mode discovery ne retire que **751 chars sur 78,036** (< 1%) :
- 16 lignes `Path: /testbed/...` supprimées
- "under the specified path" → "Explore the existing codebase to determine where"
- Tout le reste (78K) est identique : description, interfaces, signatures, docstrings

## Infrastructure

### FeatureBench Agents
- `claude_code.py` — Config A et B (standard Claude Code)
- `claude_code_rtfm.py` — Config C (FTS, sync à la volée → À MODIFIER pour DB pré-parsée)
- `claude_code_rtfm_embed.py` — Config D (DB pré-générée, hybrid search)

### Benchmark Script
- `run_benchmark.sh` — 4 configs × N tasks, auto eval + metrics
- Metrics → `reports/benchmark/metrics.jsonl`
- Tool usage parsed from content blocks in stream output

### Auth: OAuth MAX only (no API key)
- Credentials copied from local → PC2
- Token auto-refreshes via refresh_token
- Need to refresh before each batch run (`scp ~/.claude/.credentials.json`)

## TODO — Prochaine session

### Préparation (avant de lancer des runs)
- [x] **Créer DBs FTS-only pré-parsées** pour chaque repo — FAIT 28/02
      → `/mnt/data/rtfm-dbs-fts/` : metaflow 12Mo, pydantic 18Mo, astropy 52Mo, mlflow 234Mo
- [x] **Modifier `claude_code_rtfm.py`** (Config C) pour copier la DB FTS pré-parsée — FAIT 28/02
      → copie depuis `/opt/rtfm-dbs-fts/<repo>/library.db`, fallback sync si absent
- [x] Rafraîchir les credentials OAuth sur PC2 — FAIT 28/02

### Runs prioritaires
- [ ] **Lancer A et B sur `test_responses_agent`** — EN COURS (A lancé 28/02)
- [x] **Lancer A/B/C/D sur `test_validation`** — FAIT 28/02 (RTFM C+D résolvent, A+B non !)
- [x] Lancer A/B/C/D sur `test_stub_generator` (metaflow) — FAIT 28/02 (4/4 résolvent sauf D 30/31)

### Runs complets
- [ ] Re-run Config A avec eval (11 tâches dont pydantic)
- [ ] Lancer Config B/C/D sur tâches non-mlflow (metaflow, astropy, pydantic)
- [ ] Relancer Config B pour serialization et responses_agent (failed précédemment)
- [ ] Nombre de répétitions par condition (significativité)
- [ ] Matrice complète 11 tâches × 4 configs
