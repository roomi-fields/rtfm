---
type: article
title: "R3) Le protocole : 4 conditions, 11 tâches, même modèle"
subtitle: "Comment isoler la variable 'retrieval' dans une expérience sur des agents codeurs — et pourquoi FeatureBench est le bon terrain de jeu."
excerpt: "Pour mesurer l'impact du retrieval, il faut un protocole qui isole cette seule variable. 4 conditions expérimentales, 11 tâches, 4 repos de tailles croissantes, un seul modèle. Voici comment on a fait."
slug: protocole-experimental-retrieval-agents
focus_keyword: protocole expérimental agents codeurs
tags:
  - protocole
  - featurebench
  - benchmark
  - conditions-experimentales
  - claude-code
  - discovery
  - méthodologie
---

> [!abstract]- SPEC
> ## Brief — R3 : Le protocole expérimental
> ### Position dans la série
> - **Série** : R (Retrieval) — Does Retrieval Help? | **Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]], [[R2_RTFM_Outil_Agnostique|R2]]
> - Décrit le protocole expérimental en détail
> - Justifie chaque choix méthodologique
> ### Sujets couverts
> - Pourquoi FeatureBench et pas SWE-bench
> - Les 4 conditions (A/B/C/D) et ce qu'elles isolent
> - Le mode "discovery" et la manipulation du prompt
> - Les métriques collectées
> - Les coûts d'initialisation de l'index
> - L'agent et le modèle utilisés
> ### SOTAs sources
> - `paper/sota/02_benchmarks_coding_agents.md`
> - `paper/benchmark_paper.md`

# R3) Le protocole : 4 conditions, 11 tâches, même modèle

## Comment isoler la variable "retrieval" dans une expérience sur des agents codeurs

> Tout le monde affirme que son outil améliore les agents. Personne ne le prouve proprement. Nous essayons.

## Où se situe cet article ?

[[R1_Le_Goulot_de_Localisation|R1]] a posé le diagnostic : la localisation est le goulot d'étranglement des agents codeurs. [[R2_RTFM_Outil_Agnostique|R2]] a présenté l'outil que nous proposons comme solution : un outil de retrieval agnostique, metadata-first.

Reste la question centrale : **est-ce que ça marche ?**

Pour y répondre, il ne suffit pas de lancer un agent avec et sans RTFM et de comparer les résultats. Il faut un protocole qui isole la variable "retrieval" et contrôle tout le reste. Cet article décrit ce protocole — et les choix méthodologiques qui le sous-tendent.

---

## Pourquoi FeatureBench et pas SWE-bench

Le choix du benchmark est le premier choix méthodologique, et ce n'est pas anodin.

### Le problème SWE-bench

SWE-bench (Jimenez et al., ICLR 2024) est le benchmark de référence pour les agents codeurs. 2 294 tâches issues d'issues GitHub réelles, dans 12 repos Python. C'est le standard. C'est aussi un benchmark problématique.

SWE-Bench Illusion (Liang et al., 2025) a montré que de nombreuses tâches de SWE-bench souffrent de **contamination** : les solutions sont dans l'historique git, les descriptions d'issues contiennent des indices explicites, et certaines tâches se résolvent par pattern matching sur le diff plutôt que par compréhension du code. Les auteurs estiment qu'une proportion significative des résolutions "correctes" ne démontrent pas une vraie compréhension.

Plus fondamentalement pour notre étude, SWE-bench se concentre sur la **correction de bugs**. C'est un type de tâche spécifique : le code cassé existe déjà, il faut le trouver et le réparer. Ce n'est pas la même chose qu'*implémenter une fonctionnalité nouvelle* — qui demande de comprendre l'architecture du projet, d'identifier les points d'extension, et de produire du code compatible avec l'existant.

### FeatureBench : l'implémentation de fonctionnalités

FeatureBench (ICLR 2026) comble cette lacune. Au lieu de corriger des bugs, les tâches demandent d'**implémenter des fonctionnalités nouvelles** dans des projets réels. C'est plus difficile — le meilleur score publié est 11%, contre 74% sur SWE-bench Verified — et c'est plus réaliste.

Pourquoi FeatureBench est mieux adapté à notre étude :

1. **Discovery nécessaire.** Pour implémenter une feature, il faut comprendre l'architecture. Où ajouter le code ? Quels modules existants interagissent ? Quelles conventions suivre ? Ce sont exactement les questions auxquelles un outil de retrieval peut répondre.

2. **Moins contaminé.** FeatureBench est plus récent, les solutions ne sont pas dans l'historique git public au moment des tests.

3. **Projets de tailles variées.** La version lite inclut des repos de 624 à 8 260 fichiers — exactement l'éventail dont nous avons besoin pour tester l'hypothèse du seuil de taille.

4. **Évaluation fiable.** Chaque tâche a une suite de tests dédiée. La résolution est binaire : les tests passent ou non. Pas d'évaluation subjective.

---

## Les 4 repos et 11 tâches

Nous avons sélectionné 11 tâches du split lite (sans GPU) de FeatureBench, réparties sur 4 repos de tailles croissantes :

| Repo                   | Domaine               | Fichiers indexés | Chunks  | Tâches |
| ---------------------- | --------------------- | ---------------- | ------- | ------ |
| **metaflow** (Netflix) | Orchestration ML      | 624              | ~5 060  | 1      |
| **pydantic**           | Validation de données | 771              | ~14 762 | 1      |
| **astropy**            | Astronomie            | 1 123            | ~41 231 | 2      |
| **mlflow**             | MLOps                 | 8 260            | 180 262 | 7      |

La distribution n'est pas uniforme — 7 tâches sur 11 sont dans mlflow. C'est un biais de FeatureBench (les grands repos génèrent plus de tâches), mais c'est aussi un avantage pour notre étude : c'est précisément sur les grands repos que nous attendons un effet du retrieval.

### Diversité des tâches

Les tâches couvrent un spectre de complexité :

- **test_stub_generator** (metaflow) : implémenter un générateur de stubs de type — tâche bien délimitée, un seul fichier à créer.
- **test_validation** (mlflow) : implémenter un module de validation qui interagit avec les scorers et les données — nécessite de comprendre les dépendances cross-module.
- **test_responses_agent** (mlflow) : implémenter 15 interfaces pour un agent de réponses — la tâche monstre, 78K caractères de prompt.

---

## Les 4 conditions expérimentales

La variable que nous isolons est simple : **est-ce que l'agent a accès à un outil de recherche pré-indexé ?**

Pour le tester, nous avons conçu 4 configurations. Chacune fait varier un seul paramètre :

### Config A — Standard (contrôle semi-oracle)

Le prompt FeatureBench original, sans modification. Ce prompt contient les **chemins des fichiers** à modifier et les interfaces à implémenter :

```
Path: /testbed/mlflow/models/evaluation/validation.py
...implement the validate_data function...
```

L'agent sait *où* coder. C'est une condition semi-oracle — irréaliste, mais utile comme contrôle positif. Si même avec les chemins l'agent échoue, la tâche est trop difficile pour le modèle (pas un problème de localisation).

### Config B — Discovery (baseline réaliste)

Même prompt que A, mais on **retire les chemins**. Concrètement, on supprime les lignes `Path: /testbed/...` et on remplace "under the specified path" par "Explore the existing codebase to determine where".

Combien de prompt modifie-t-on ? **751 caractères sur 78 036** — moins de 1%. Le reste est identique : description de la feature, interfaces attendues, signatures de fonctions, docstrings. L'agent a toute l'information sauf une : *où* coder.

C'est la condition réaliste. Quand un développeur lance un agent sur un ticket Jira, il ne lui donne pas la liste des fichiers à modifier. Il lui donne la description de ce qu'il veut.

### Config C — Discovery + FTS

Même prompt que B, mais l'agent a accès à RTFM avec **recherche full-text** (BM25 via FTS5). La base de données est pré-construite — comme en usage réel, où l'outil est déjà initialisé dans le projet.

### Config D — Discovery + FTS + Embeddings

Même prompt que B, avec RTFM en mode **hybride** : recherche full-text + recherche sémantique par embeddings.

### Ce qui change et ce qui ne change pas

| Paramètre              | A           | B           | C           | D             |
| ---------------------- | ----------- | ----------- | ----------- | ------------- |
| Prompt                 | Original    | Discovery   | Discovery   | Discovery     |
| Chemins dans le prompt | Oui         | **Non**     | **Non**     | **Non**       |
| RTFM disponible        | Non         | Non         | **FTS**     | **FTS+Embed** |
| Agent                  | Claude Code | Claude Code | Claude Code | Claude Code   |
| Modèle                 | Sonnet 4.0  | Sonnet 4.0  | Sonnet 4.0  | Sonnet 4.0    |
| Timeout                | 1200s       | 1200s       | 1200s       | 1200s         |
| Environnement          | Docker      | Docker      | Docker      | Docker        |

La seule variable entre B et C est la présence de l'outil FTS. La seule variable entre C et D est l'ajout des embeddings. A est le contrôle semi-oracle. B est le baseline réaliste.

> **Encart : Pourquoi B est le vrai baseline**
>
> On pourrait penser que A (prompt standard) est le baseline naturel. Mais A donne les chemins — c'est une forme de triche. En condition réaliste, l'agent ne sait pas *où* coder. B est donc le baseline qui correspond au cas d'usage réel. La question expérimentale est : **C/D > B ?** — pas C/D > A.

---

## L'agent et le modèle

**Agent :** Claude Code (Anthropic). C'est un agent de production, pas un prototype de recherche. Il a accès aux outils standard : `Read`, `Edit`, `Write`, `Grep`, `Glob`, `Bash`. En configs C et D, il a accès en plus aux outils MCP de RTFM.

**Modèle :** Claude Sonnet 4.0, fixé pour toutes les conditions. Un seul modèle garantit que les différences observées sont dues à la variable expérimentale (retrieval), pas au modèle.

**Environnement :** Docker (conteneur FeatureBench standard). Timeout de 1200 secondes. Authentification via OAuth MAX.

### Pourquoi pas plusieurs modèles ?

C'est une limite assumée. Tester avec GPT-4, Gemini, ou Llama renforcerait la généralisabilité des résultats. Mais le coût de chaque run (compute + tokens) et la complexité du setup Docker rendent l'extension à N modèles prohibitive pour une première étude. Nous fixons le modèle et faisons varier le retrieval. La généralisation à d'autres modèles est un travail futur.

---

## Les métriques

### Performance

- **Resolve rate** : le test passe ou non. Binaire, évalué par `fb eval`. C'est la métrique principale — pas de demi-mesure.
- **F2P pass rate** : fraction des tests fail-to-pass qui passent. Donne un crédit partiel — un agent qui fait passer 7 tests sur 11 est mieux qu'un qui en passe 0, même si ni l'un ni l'autre ne "résout" la tâche.

### Coût

- **Coût ($)** : via `total_cost_usd` de Claude Code.
- **Tokens** : input, output, cache read — pour comprendre où va l'argent.

### Temps

- **Durée totale** : wall-clock time, setup RTFM inclus.
- **Durée agent** : temps hors setup — le temps que l'agent passe effectivement à travailler.

### Comportement

- **Tool calls** : nombre et type (Read, Grep, Glob, Edit, Bash, rtfm_search, rtfm_expand...).
- **Ratio exploration/coding** : (Read + Grep + Glob + rtfm_search) / (Edit + Write). Un ratio élevé = l'agent passe plus de temps à chercher qu'à coder.

---

## Les coûts d'initialisation RTFM

En usage réel, RTFM est initialisé une seule fois dans le projet (`rtfm init`). Le coût d'indexation est amorti sur toutes les sessions futures. Ce n'est pas un coût "par run".

Pour la transparence, voici les coûts d'initialisation mesurés :

| Repo     | Books | Chunks  | Parse + FTS | + Embeddings | DB FTS | DB FTS+Embed |
| -------- | ----- | ------- | ----------- | ------------ | ------ | ------------ |
| metaflow | 876   | ~5 060  | ~10s        | +161s        | 12 Mo  | 22 Mo        |
| pydantic | 771   | ~14 762 | ~15s        | +444s        | 18 Mo  | 48 Mo        |
| astropy  | 1 123 | ~41 231 | ~30s        | +1 232s      | 52 Mo  | 133 Mo       |
| mlflow   | 8 260 | 180 262 | 78s         | +5 368s      | 234 Mo | 592 Mo       |

Le parsing + FTS est rapide : 10 à 78 secondes. Les embeddings sont coûteux : le débit est constant à ~33 chunks/seconde sur CPU, ce qui donne ~90 minutes pour mlflow. C'est un argument en faveur de la Config C (FTS seul) pour un usage léger.

### Setup par run

Avec des DBs pré-construites (condition réaliste), le setup par run est minime :

| Étape           | Config C (FTS) | Config D (FTS+Embed) |
| --------------- | -------------- | -------------------- |
| Install RTFM    | ~18s           | ~30s                 |
| Copie DB        | ~1s            | ~1s                  |
| Warm FastEmbed  | N/A            | ~17s                 |
| **Total setup** | **~20s**       | **~50s**             |

20 à 50 secondes de setup — sur un run de 7 à 12 minutes. L'overhead est modeste.

---

## Significativité statistique

C'est le point le plus délicat. Les runs d'agents codeurs sont coûteux (1 à 5$ par run, 5 à 20 minutes par run), et les résultats sont stochastiques — le même agent sur la même tâche peut réussir ou échouer selon les choix du modèle.

Notre objectif est N ≥ 3 répétitions par condition. Avec 11 tâches × 4 conditions × 3 répétitions = 132 runs. À 10 minutes et ~2$ en moyenne, c'est ~22 heures de compute et ~264$ de tokens.

Pour les tests statistiques, nous prévoyons :
- **Wilcoxon signed-rank** pour les comparaisons appariées (B vs C, B vs D) si N est suffisant.
- **Test de permutation** si N est petit.
- **Intervalles de confiance à 95%** sur les taux de résolution.

Les résultats préliminaires (runs uniques) sont présentés en [[R4_Resultats|R4]]. La matrice complète est en cours.

---

## Récapitulatif du protocole

```
                    ┌──────────┐
                    │ 11 tâches│
                    │ 4 repos  │
                    └────┬─────┘
                         │
         ┌───────┬───────┼───────┬───────┐
         │       │       │       │       │
    ┌────▼───┐ ┌─▼──┐ ┌──▼──┐ ┌─▼───┐
    │Config A│ │ B  │ │  C  │ │  D  │
    │Standard│ │Disc│ │ FTS │ │Embed│
    │(oracle)│ │    │ │     │ │     │
    └────┬───┘ └─┬──┘ └──┬──┘ └─┬───┘
         │       │       │       │
         │  Même agent (Claude Code)
         │  Même modèle (Sonnet 4.0)
         │  Même env (Docker, 1200s)
         │       │       │       │
    ┌────▼───────▼───────▼───────▼───┐
    │  Métriques : resolve, F2P,     │
    │  coût, durée, tool calls,      │
    │  ratio exploration/coding      │
    └────────────────────────────────┘
```

La question : **C et D font-ils mieux que B sur les grands repos ?**

Les résultats sont en [[R4_Resultats|R4]].

---

## Références

- **Jimenez, C.E. et al. (2024)** — SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.
- **FeatureBench (2026)** — ICLR 2026. arXiv:2602.10975.
- **Liang, J. et al. (2025)** — SWE-Bench Illusion. arXiv:2506.12286.
- **Tokenomics (2026)** — arXiv:2601.14470.
- **UTBoost (2025)** — ACL 2025. arXiv:2506.09289.

---

## Glossaire

- **Config A/B/C/D** : les 4 conditions expérimentales de notre étude. A = prompt standard (chemins donnés), B = discovery (chemins retirés), C = discovery + FTS, D = discovery + FTS + embeddings.
- **Discovery mode** : mode où les chemins de fichiers sont retirés du prompt, forçant l'agent à localiser lui-même les fichiers pertinents.
- **FeatureBench** : benchmark pour les agents codeurs centré sur l'implémentation de fonctionnalités nouvelles (pas la correction de bugs). ICLR 2026.
- **F2P** : *fail-to-pass* — tests qui échouaient avant l'intervention de l'agent et qui passent après.
- **OAuth MAX** : mode d'authentification pour Claude Code utilisant le compte Anthropic directement (pas d'API key).
- **Split lite** : sous-ensemble de FeatureBench ne nécessitant pas de GPU, avec des tâches de difficulté modérée.
- **SWE-bench** : benchmark de référence pour les agents codeurs basé sur des issues GitHub réelles. ICLR 2024.
- **Wilcoxon signed-rank** : test statistique non-paramétrique pour comparer deux conditions appariées.

---

## Liens dans la série

- [[R1_Le_Goulot_de_Localisation|R1]] — Le goulot de localisation — le problème fondamental
- [[R2_RTFM_Outil_Agnostique|R2]] — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit
- **R3** (cet article) — Le protocole : 4 conditions, 11 tâches, même modèle
- [[R4_Resultats|R4]] — Les résultats : quand la taille du repo change tout
- [[R5_Agent_Decide_Seul|R5]] — L'agent décide seul : retrieval sélectif sans entraînement
- [[R6_Perspectives|R6]] — Ce que ça change — et ce qu'il reste à prouver

---

**Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]], [[R2_RTFM_Outil_Agnostique|R2]]
**Temps de lecture** : 12 min
**Tags** : #protocole #featurebench #benchmark #conditions-experimentales #méthodologie

---

*Prochain article : [[R4_Resultats|R4]] — Les résultats : quand la taille du repo change tout*

---
