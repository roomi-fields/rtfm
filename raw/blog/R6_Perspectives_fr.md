---
type: article
title: "R6) Ce que ça change — et ce qu'il reste à prouver"
subtitle: "La règle des 1 000 fichiers, les limites de notre étude, et pourquoi la barre est si basse dans ce domaine."
excerpt: "Déployez un outil de retrieval sur tout projet de plus de 1 000 fichiers. Mais ne nous croyez pas sur parole — voici exactement ce que nous avons prouvé et ce que nous n'avons pas prouvé."
slug: perspectives-retrieval-agents-codeurs
focus_keyword: perspectives retrieval agents
tags:
  - perspectives
  - limites
  - recommandations
  - rigueur
  - reproductibilité
  - emse
  - conclusion
---

> [!abstract]- SPEC
> ## Brief — R6 : Perspectives
> ### Position dans la série
> - **Série** : R (Retrieval) — Does Retrieval Help? | **Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]] à [[R5_Agent_Decide_Seul|R5]]
> - Dernier article de la série : synthèse, limites, recommandations
> ### Sujets couverts
> - Recommandations pratiques (la règle des 1 000 fichiers)
> - Limites méthodologiques (un modèle, un outil, 11 tâches)
> - L'état de la rigueur dans le domaine
> - Travaux futurs
> - Appel à la reproductibilité

# R6) Ce que ça change — et ce qu'il reste à prouver

## La règle des 1 000 fichiers, les limites, et pourquoi la barre est si basse

> La meilleure contribution de cette étude n'est peut-être pas ses résultats — c'est son protocole.

## Où se situe cet article ?

Cette série a traversé un arc complet : le problème ([[R1_Le_Goulot_de_Localisation|R1]]), l'outil ([[R2_RTFM_Outil_Agnostique|R2]]), le protocole ([[R3_Protocole_Experimental|R3]]), les résultats ([[R4_Resultats|R4]]), et l'analyse comportementale ([[R5_Agent_Decide_Seul|R5]]).

Il est temps de prendre du recul. Qu'est-ce qui est établi ? Qu'est-ce qui ne l'est pas ? Et surtout : qu'est-ce que ça change en pratique ?

---

## Ce qui est établi

### 1. Le retrieval transforme les résultats sur les grands repos

Sur test_validation (mlflow, 8 260 fichiers), le resolve rate passe de 55-64% sans retrieval à 100% avec retrieval. C'est un résultat fort : la même tâche, le même agent, le même modèle — la seule différence est l'accès à un outil de recherche pré-indexé.

Le mécanisme causal est identifié : l'agent sans retrieval ne trouve pas les dépendances cross-module (`validation.py` ↔ `scorers.py` ↔ `data.py`). L'agent avec retrieval les localise en 2-3 requêtes et implémente un module compatible.

### 2. Le retrieval ne sert à rien sur les petits repos

Sur test_stub_generator (metaflow, 624 fichiers), les 4 configs résolvent la tâche. Le retrieval est un overhead sans bénéfice : +23% de temps, +22% de coût. L'agent le sait intuitivement — il n'utilise quasiment pas l'outil.

### 3. FTS suffit, les embeddings ajoutent de l'efficience

Config C (FTS seul) et Config D (FTS+embeddings) résolvent les mêmes tâches. Les embeddings réduisent les tours (-38%), le coût (-45%) et les lectures de fichiers (-48%) — mais ne changent pas le résultat binaire. Le FTS, via BM25, est une baseline remarquablement forte pour la recherche de code.

### 4. Le retrieval ne compense pas la complexité intrinsèque

test_responses_agent (78K chars, 15 interfaces) n'est résolu par aucune config. Le retrieval aide à couvrir plus d'interfaces (12/15 avec embeddings vs 8/15 avec FTS seul), mais Sonnet 4.0 ne peut pas gérer la complexité de la tâche même avec un contexte parfait. Le retrieval est nécessaire mais pas suffisant.

### 5. L'agent fait du retrieval sélectif naturellement

Sans instruction spéciale, l'agent ajuste l'intensité du retrieval à la tâche : 1-2 appels sur un petit repo, 2-3 sur un grand repo simple, 10-15 sur une tâche complexe. Le retrieval adaptatif émerge de la disponibilité de l'outil, sans fine-tuning ni classificateur.

---

## Ce qui n'est PAS établi

### Le seuil de taille

Nous avons un point à 624 fichiers (pas de gain) et un point à 8 260 fichiers (gain fort). La zone entre 700 et 5 000 fichiers est terra incognita. Les runs sur pydantic (771) et astropy (1 123) sont en cours et nous diront si le seuil est autour de 1 000, 2 000 ou 5 000 fichiers.

### La significativité statistique

Les résultats présentés sont des runs uniques. Nous n'avons pas encore N ≥ 3 répétitions par condition pour calculer des intervalles de confiance et des p-values. La variabilité d'un agent codeur est substantielle — le même agent peut réussir ou échouer sur la même tâche selon les choix stochastiques du modèle.

### La généralisation à d'autres modèles

Nous avons testé un seul modèle : Claude Sonnet 4.0. GPT-4, Gemini 2.5 Pro, Llama, ou même Claude Opus pourraient montrer des résultats différents. La capacité métacognitive qui permet le retrieval sélectif pourrait varier d'un modèle à l'autre.

### La généralisation à d'autres outils

Nous avons testé un seul outil : RTFM. Augment Context Engine, Sourcegraph Cody, ou un autre outil de retrieval pourrait donner des résultats différents. Le pattern metadata-first est-il crucial, ou est-ce que n'importe quel outil de recherche ferait l'affaire ?

### La généralisation à d'autres langages

FeatureBench lite est Python-only. Le goulot de localisation existe-t-il de la même manière dans un projet Java, TypeScript, ou Rust ? La structure du langage (modules, imports, types) pourrait changer la dynamique.

---

## Recommandations pratiques

Malgré les limites, les résultats sont suffisamment clairs pour des recommandations provisoires.

### La règle des 1 000 fichiers

**Déployez un outil de retrieval pré-indexé sur tout projet de plus de 1 000 fichiers.** Le coût d'initialisation est négligeable (10-78 secondes de parsing pour le FTS) et le bénéfice potentiel est considérable.

Sur les projets de moins de 600 fichiers, l'overhead du retrieval n'est pas justifié. La navigation directe suffit.

Entre 600 et 1 000 : au cas par cas, selon la complexité du projet.

### FTS d'abord, embeddings ensuite

Le FTS (BM25 via SQLite FTS5) est la baseline forte. Il résout les mêmes tâches que FTS+embeddings, sans le coût d'indexation des embeddings (qui peut aller jusqu'à 90 minutes sur un grand repo). Commencez par FTS. Ajoutez les embeddings si vous avez besoin d'efficience (moins de tours, moins de coût par run).

### Ne forcez pas le retrieval

Ne mettez pas d'instruction "utilise TOUJOURS RTFM" dans le prompt de l'agent. L'agent fait du retrieval sélectif naturellement. Forcer le retrieval systématique est contre-productif — c'est exactement ce que Self-RAG et Repoformer ont démontré.

### Metadata-first

Si vous construisez ou choisissez un outil de retrieval, privilégiez un pattern qui renvoie des métadonnées (titre, chemin, score) plutôt que du contenu complet. Le context rot est réel. Moins de tokens dans les résultats de recherche = plus d'espace pour le code qui compte.

---

## L'éléphant dans la pièce : la barre de la rigueur

Un aspect de cette étude qui nous frappe : **la barre de la rigueur est incroyablement basse dans ce domaine.**

Augment Code revendique "+80% de performance" sans publier de protocole. Des centaines d'entreprises affirment que leurs outils "améliorent la productivité des développeurs" sans données contrôlées. Des papiers académiques évaluent leurs outils sur des micro-tâches créées par les auteurs eux-mêmes.

Notre étude n'est pas parfaite. Un seul modèle, un seul outil, 11 tâches, des runs uniques. Mais nous avons :
- Un benchmark **tiers** (FeatureBench, ICLR 2026) — pas des tâches que nous avons créées.
- Un protocole à **4 conditions** avec une variable isolée.
- Des **métriques reproductibles** (resolve rate, F2P, coût, durée).
- Une transparence sur les **limites** et les données manquantes.

Le fait que ce niveau minimal de rigueur soit *exceptionnel* dans le domaine des outils pour agents codeurs en dit long sur l'état du champ.

Nous ne prétendons pas avoir prouvé définitivement que le retrieval aide. Nous prétendons avoir posé la bonne question, avec le bon protocole. Les résultats complets, avec répétitions et significativité statistique, seront soumis à *Empirical Software Engineering* (EMSE).

---

## Travaux futurs

### Court terme (cette étude)

- Compléter la matrice 11 tâches × 4 conditions × N ≥ 3 répétitions.
- Évaluer les repos intermédiaires (pydantic 771, astropy 1 123) pour localiser le seuil.
- Tests statistiques (Wilcoxon signed-rank, intervalles de confiance).
- Analyse qualitative : sur chaque tâche où C/D > B, quels fichiers le retrieval a-t-il trouvé que B n'a pas trouvés ?

### Moyen terme

- Tester avec d'autres modèles (GPT-4, Gemini, Opus, modèles open-source).
- Tester avec d'autres outils de retrieval (Augment, Cody) — si les APIs le permettent.
- Étendre à SWE-bench pour la comparabilité.
- Mesurer l'impact sur des tâches non-Python (FeatureBench full).

### Long terme

- Étudier l'interaction retrieval × modèle : est-ce que les modèles plus puissants bénéficient plus ou moins du retrieval ?
- Explorer le retrieval *proactif* : l'outil pourrait-il pré-charger du contexte pertinent avant même que l'agent ne cherche ?
- Mesurer l'impact en conditions réelles (pas benchmark) sur des tâches de développement quotidiennes.

---

## Ce que cette série raconte, au fond

Nous sommes partis d'une intuition simple : les agents codeurs sont limités par leur capacité à trouver le bon contexte, pas par leur capacité à écrire du code. Nous avons construit un outil pour tester cette intuition. Et les résultats confirment : **donner à un agent un outil de recherche pré-indexé transforme ses performances sur les grands projets.**

Mais la leçon la plus profonde n'est pas technique. C'est une leçon sur le *design* des outils pour agents IA.

On n'a pas besoin de forcer l'agent. On n'a pas besoin de modifier son comportement. On n'a pas besoin de construire des mécanismes complexes de décision. Il suffit de lui **donner le choix** — un outil disponible, peu coûteux, non-invasif — et il choisit bien.

Ce n'est pas un GPS qui dicte le chemin. C'est une carte que l'agent peut consulter quand il le souhaite. Et cette distinction — entre l'outil qui commande et l'outil qui permet — fait toute la différence.

---

## Références

- **FeatureBench (2026)** — ICLR 2026. arXiv:2602.10975.
- **Jimenez, C.E. et al. (2024)** — SWE-bench. ICLR 2024. arXiv:2310.06770.
- **Asai, A. et al. (2023)** — Self-RAG. ICLR 2024. arXiv:2310.11511.
- **Wu, Y. et al. (2024)** — Repoformer. ICML 2024. arXiv:2403.10059.
- **Augment Code (2026)** — Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
- **Liang, J. et al. (2025)** — SWE-Bench Illusion. arXiv:2506.12286.
- **Tokenomics (2026)** — arXiv:2601.14470.

---

## Glossaire

- **EMSE** : *Empirical Software Engineering* — revue Springer spécialisée dans les études empiriques en génie logiciel. La cible de soumission pour la version académique complète de cette étude.
- **Matrice complète** : l'ensemble des 11 tâches × 4 conditions × N répétitions qui constitue le dataset complet de l'étude.
- **P-value** : probabilité d'observer les résultats (ou plus extrêmes) sous l'hypothèse nulle — mesure de significativité statistique.
- **Reproductibilité** : la capacité pour un tiers de reproduire les résultats de l'étude avec le même protocole.

---

## Liens dans la série

- [[R1_Le_Goulot_de_Localisation|R1]] — Le goulot de localisation — le problème fondamental
- [[R2_RTFM_Outil_Agnostique|R2]] — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit
- [[R3_Protocole_Experimental|R3]] — Le protocole : 4 conditions, 11 tâches, même modèle
- [[R4_Resultats|R4]] — Les résultats : quand la taille du repo change tout
- [[R5_Agent_Decide_Seul|R5]] — L'agent décide seul : retrieval sélectif sans entraînement
- **R6** (cet article) — Ce que ça change — et ce qu'il reste à prouver

---

**Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]] à [[R5_Agent_Decide_Seul|R5]]
**Temps de lecture** : 11 min
**Tags** : #perspectives #limites #recommandations #rigueur #reproductibilité #emse

---

*Fin de la série R — Does Retrieval Help?*

*RTFM est open source : [github.com/roomi-fields/rtfm](https://github.com/roomi-fields/rtfm)*

---
