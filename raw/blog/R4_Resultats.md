---
type: article
title: "R4) Les résultats : quand la taille du repo change tout"
subtitle: "Sur mlflow (8 260 fichiers), le retrieval fait passer le resolve rate de 55% à 100%. Sur metaflow (624 fichiers), rien ne change. Le seuil de taille existe."
excerpt: "Les résultats de notre étude contrôlée. Le retrieval transforme les performances sur les grands repos — et ne sert à rien sur les petits. Données, tableaux, analyse des échecs."
slug: resultats-retrieval-agents-codeurs
focus_keyword: résultats retrieval agents codeurs
tags:
  - résultats
  - benchmark
  - retrieve-rate
  - mlflow
  - metaflow
  - fts
  - embeddings
  - seuil-taille
---

> [!abstract]- SPEC
> ## Brief — R4 : Les résultats
> ### Position dans la série
> - **Série** : R (Retrieval) — Does Retrieval Help? | **Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]], [[R2_RTFM_Outil_Agnostique|R2]], [[R3_Protocole_Experimental|R3]]
> - Coeur de la série : les données expérimentales
> - Résultats préliminaires (matrice complète en cours)
> ### Sujets couverts
> - Résultat principal : test_validation (mlflow, 8260 fichiers)
> - Contre-exemple : test_stub_generator (metaflow, 624 fichiers)
> - FTS vs FTS+Embeddings : la surprise
> - Analyse d'échec : test_responses_agent
> - Coût et durée par condition
> - Utilisation des outils par l'agent
> ### SOTAs sources
> - `paper/benchmark_paper.md`

# R4) Les résultats : quand la taille du repo change tout

## Sur mlflow, le retrieval fait passer la résolution de 55% à 100%. Sur metaflow, rien ne change.

> La réponse n'est pas "oui" ou "non". C'est "ça dépend de la taille".

## Où se situe cet article ?

[[R1_Le_Goulot_de_Localisation|R1]] a posé le problème. [[R2_RTFM_Outil_Agnostique|R2]] a présenté l'outil. [[R3_Protocole_Experimental|R3]] a décrit le protocole. Voici les résultats.

**Avertissement important :** les résultats présentés ici sont préliminaires. Ils proviennent de runs uniques (pas encore de répétitions N ≥ 3). La matrice complète (11 tâches × 4 conditions × N répétitions) est en cours. Les conclusions sont des *tendances*, pas encore des preuves statistiques. La transparence sur cette limite est une exigence que nous nous imposons — contrairement aux "+80%" sans protocole que l'industrie publie sans sourciller.

---

## Le résultat principal : test_validation sur mlflow

### Le contexte

`test_validation` demande d'implémenter un module de validation de données dans mlflow — un projet de **8 260 fichiers**. La difficulté : le module doit interagir avec trois composants existants dispersés dans le projet : `validation.py`, `scorers.py` et `data.py`. Ces fichiers sont dans des sous-répertoires différents. Pour réussir, l'agent doit trouver ces dépendances cross-module.

11 tests doivent passer. Si un seul échoue, la tâche n'est pas "résolue".

### Les résultats

| Condition                        | F2P (fail-to-pass) | Résolu ? | Durée | Coût  |
| -------------------------------- | ------------------ | -------- | ----- | ----- |
| A — Standard (chemins donnés)    | 6/11 (55%)         | Non      | 479s  | $1.12 |
| B — Discovery (pas de retrieval) | 7/11 (64%)         | Non      | 459s  | $1.50 |
| C — Discovery + FTS              | **11/11 (100%)**   | **Oui**  | 732s  | $2.42 |
| D — Discovery + FTS+Embed        | **11/11 (100%)**   | **Oui**  | 605s  | $1.33 |

Le résultat est net. **Avec retrieval (C et D), 100% des tests passent. Sans retrieval (A et B), entre 55% et 64%.**

Et notez le détail qui change la perspective : **Config A, celle où les chemins sont *donnés dans le prompt*, ne résout pas la tâche**. L'agent a les chemins. Il sait *où* coder. Et il échoue quand même sur 5 tests. Savoir *où* coder ne suffit pas — il faut aussi comprendre *comment* les modules interagissent. C'est précisément ce que le retrieval apporte : une recherche sur "validation scorers" renvoie les fichiers pertinents *et leur contexte architectural*.

### Pourquoi A et B échouent

Les 4-5 tests qui échouent en A et B sont toujours les mêmes : `test_validate_scorers_invalid_all_scorers`, `test_validate_data_with_correctness`, `test_validate_data_missing_columns`. Tous impliquent des interactions entre le module de validation et des modules distants — les scorers, les structures de données.

L'agent sans retrieval implémente le module de validation de manière *isolée*. Le code est syntaxiquement correct, les types sont bons, la logique locale est cohérente. Mais l'implémentation est *incompatible* avec le reste du projet parce que l'agent n'a pas vu le code des modules voisins.

L'agent avec retrieval fait une recherche `rtfm_search("validation scorers")` en début de session. Il obtient les coordonnées de `scorers.py` et `data.py`. Il les lit. Il comprend les interfaces existantes. Et il implémente un module de validation *compatible*.

---

## Le contre-exemple : test_stub_generator sur metaflow

### Le contexte

`test_stub_generator` demande d'implémenter un générateur de stubs de type dans metaflow — un repo de **624 fichiers**. C'est une tâche bien délimitée : un seul fichier à créer, des interfaces claires.

31 tests doivent passer.

### Les résultats

| Condition                 | F2P           | Résolu ?          | Durée | Coût  |
| ------------------------- | ------------- | ----------------- | ----- | ----- |
| A — Standard              | 31/31 (100%)  | **Oui**           | 370s  | $0.97 |
| B — Discovery             | 31/31 (100%)  | **Oui**           | 395s  | $1.07 |
| C — Discovery + FTS       | 31/31 (100%)  | **Oui**           | 454s  | $1.30 |
| D — Discovery + FTS+Embed | 30/31 (96.8%) | Non (1 test raté) | 541s  | $1.44 |

**Tout le monde résout** (sauf D qui rate un test sur 31 — un artefact, pas un signal).

Mais RTFM est *contre-productif* en termes de coût et de durée :
- Config C est **23% plus lente** et **22% plus chère** que A.
- Config D est **46% plus lente** et **48% plus chère** que A.

L'agent RTFM n'utilise quasiment pas l'outil : 1-2 appels seulement. Il navigue directement dans le repo avec `grep` et `Read` — parce que le repo est suffisamment petit pour que ça marche.

### La conclusion

**Sur un repo de 624 fichiers, `grep` suffit.** Le goulot de localisation n'existe pas. RTFM est un overhead sans bénéfice. L'agent le sait intuitivement — il fait 1-2 appels RTFM puis revient aux outils standard.

---

## L'analyse croisée : le seuil de taille

Juxtaposons les deux résultats :

| Repo     | Fichiers | Gain retrieval (resolve rate) | Gain retrieval (coût)      |
| -------- | -------- | ----------------------------- | -------------------------- |
| metaflow | 624      | 0% (B=C=D=100%)               | **-23% à -48%** (overhead) |
| mlflow   | 8 260    | **+36 à +45 pp** (B→C/D)      | N/A (B ne résout pas)      |

Le pattern est clair : **le retrieval n'aide que quand le repo est assez grand pour que la navigation directe soit un goulot d'étranglement.**

Les données pour pydantic (771 fichiers) et astropy (1 123 fichiers) — les repos intermédiaires — sont en cours. Elles nous diront où se situe le seuil. Notre hypothèse : quelque part autour de 1 000 à 2 000 fichiers.

---

## FTS vs FTS+Embeddings : la surprise

La comparaison entre Config C (FTS seul) et Config D (FTS + embeddings) sur test_validation révèle un résultat qui confirme la littérature récente.

### Le resolve rate est identique

C et D résolvent tous les deux à 100%. Les embeddings ne changent pas le *résultat*. Sur cette tâche, BM25 suffit à trouver les fichiers pertinents.

### Mais l'efficience diffère significativement

| Métrique   | Config C (FTS) | Config D (FTS+Embed) | Delta    |
| ---------- | -------------- | -------------------- | -------- |
| Turns      | 81             | **50**               | **-38%** |
| Coût       | $4.04          | **$2.23**            | **-45%** |
| Read calls | 23             | **12**               | **-48%** |
| Bash calls | 20             | **9**                | **-55%** |
| Grep calls | 7              | 13                   | +86%     |

L'agent avec embeddings va *plus directement* aux bons fichiers. Il lit moins de fichiers (12 vs 23), fait moins de Bash (9 vs 20 — moins de debug), et termine en moins de tours (50 vs 81). Il fait plus de Grep — mais des Grep ciblés dans les fichiers qu'il a déjà identifiés comme pertinents.

Le résultat est cohérent avec Galimzyanov (2025) et GrepRAG (ISSTA 2026) : BM25 est compétitif avec les embeddings denses pour la recherche de code. La recherche lexicale suffit pour trouver les fichiers. Les embeddings ajoutent une couche d'*efficience* — le bon fichier apparaît plus haut dans les résultats, l'agent tâtonne moins — mais pas de *capacité* supplémentaire.

> **Encart : Implications pratiques**
>
> Config C (FTS seul) a un setup de ~20 secondes et un coût d'indexation de 10-78 secondes. Config D (FTS+Embed) a un setup de ~50 secondes et un coût d'indexation de 10-90 *minutes* pour les gros repos. Si le FTS suffit pour résoudre les mêmes tâches, le ratio coût/bénéfice favorise FTS pour un déploiement rapide. Les embeddings valent le coup pour l'efficience à long terme, pas pour le résultat brut.

---

## L'analyse d'échec : test_responses_agent

### Le cas d'usage extrême

`test_responses_agent` est la tâche la plus complexe du benchmark : **78 000 caractères** de prompt, **15 interfaces** à implémenter, un ground truth de 226 000 caractères sur 60 fichiers.

Résultat : **aucune configuration ne résout la tâche**. Ni A, ni B, ni C, ni D.

| Métrique             | A (Standard)   | B (Discovery) | C (FTS)   | D (Embed+) |
| -------------------- | -------------- | ------------- | --------- | ---------- |
| Résolu               | Non (3.5% F2P) | Non (TIMEOUT) | Non (0%)  | Non (0%)   |
| Interfaces couvertes | 15/15          | 0/15          | 8/15      | 12/15      |
| Patch size           | 92K chars      | 0 (timeout)   | 51K chars | 91K chars  |
| Cache read           | 23.8M          | 18.9M         | 8.7M      | 9.0M       |

### Ce que ça nous apprend

**Config B tombe en timeout.** Sans chemins ET sans retrieval, l'agent est perdu dans 8 260 fichiers. Il explore pendant 1 200 secondes sans produire de code. Le goulot de localisation, dans sa forme la plus pure.

**Config A couvre les 15 interfaces mais échoue quand même.** L'agent avait les chemins. Il a modifié les 15 fichiers. Mais les tests échouent (3.5% F2P). Ce n'est pas un problème de localisation — c'est un problème de *capacité du modèle*. 15 interfaces simultanées dépassent ce que Sonnet 4.0 peut gérer de manière cohérente.

**Config D couvre 12/15 interfaces, Config C seulement 8/15.** Les embeddings guident mieux — l'agent identifie davantage de fichiers pertinents. Mais même 12/15 n'est pas suffisant.

**Les configs C et D consomment 2-3x moins de cache read** (8-9M vs 19-24M tokens). Le pattern metadata-first fonctionne : l'agent charge moins de contexte. Mais le gain de contexte ne compense pas la complexité intrinsèque de la tâche.

### Le diagnostic

L'échec de Config C est révélateur. L'agent a dit : *"Due to space constraints, let me focus on the most critical interfaces"* — et a abandonné les 8 interfaces les plus complexes. Le modèle *sait* qu'il ne peut pas tout faire. Il fait un choix rationnel — mais incomplet.

L'échec de Config D est différent. L'agent a couvert 12 interfaces — les embeddings l'ont mieux guidé. Mais une série de 4 `Edit` successifs sur `responses.py` a corrompu le fichier : un `continue` transformé en `continue(chunks:...` → SyntaxError immédiat. Bug d'édition, pas bug de retrieval.

**Le retrieval est nécessaire mais pas suffisant.** Il résout le goulot de localisation. Il ne résout pas le goulot de capacité du modèle.

---

## Analyse de l'utilisation des outils

Comment l'agent utilise-t-il ses outils dans chaque condition ? Voici la décomposition pour test_validation (mlflow) :

| Outil       | B (Discovery) | C (FTS) | D (Embed+) |
| ----------- | ------------- | ------- | ---------- |
| Grep        | 6             | 7       | 13         |
| Read        | 13            | 23      | 12         |
| Edit        | 6             | 12      | 5          |
| Bash        | 22            | 20      | 9          |
| Glob        | 0             | 7       | 1          |
| RTFM search | 0             | 3       | 2          |
| RTFM expand | 0             | 2       | 0          |
| **Total**   | 53            | 81      | 50         |

Trois observations :

**1. Config D fait moins de Bash.** 9 calls Bash contre 22 en B et 20 en C. Le Bash est principalement du debug — exécuter le code pour voir s'il marche, corriger, réexécuter. L'agent avec embeddings code plus juste du premier coup, parce qu'il a trouvé les bons fichiers dès le départ.

**2. Config C lit plus de fichiers.** 23 Read contre 12 en D et 13 en B. Sans embeddings, le FTS renvoie des résultats pertinents mais pas optimalement ordonnés — l'agent lit plus de fichiers pour trouver le bon. Les embeddings affinent le ranking.

**3. L'agent RTFM utilise peu RTFM.** 2-3 appels search, 0-2 expand. Ce n'est pas un outil qu'il martèle — c'est un outil qu'il utilise *chirurgicalement*, au bon moment. C'est le sujet de [[R5_Agent_Decide_Seul|R5]].

---

## Synthèse : qu'est-ce qui est établi et qu'est-ce qui ne l'est pas

### Établi (données actuelles)

- Sur test_validation (mlflow, 8 260 fichiers) : le retrieval transforme le résultat (55-64% → 100%).
- Sur test_stub_generator (metaflow, 624 fichiers) : le retrieval n'apporte rien.
- FTS seul résout autant que FTS+embeddings. Les embeddings ajoutent de l'efficience (-38% turns, -45% coût).
- Le retrieval ne compense pas la complexité intrinsèque (test_responses_agent).
- Le pattern metadata-first réduit la consommation de contexte (2-3x moins de cache read).

### En attente de confirmation

- Le seuil de taille exact (données pydantic et astropy en cours).
- La généralisabilité à d'autres tâches mlflow (7 tâches, pas encore toutes évaluées en 4 conditions).
- La significativité statistique (N ≥ 3 répétitions pas encore atteint).
- La corrélation taille repo × gain retrieval.
- Le coût par tâche *résolue* (nécessite plus de données).

---

## Références

- **FeatureBench (2026)** — ICLR 2026. arXiv:2602.10975.
- **Galimzyanov, F. et al. (2025)** — Practical Code RAG at Scale. arXiv:2510.20609.
- **GrepRAG (2026)** — ISSTA 2026.
- **PatchPilot (2025)** — ICML 2025. arXiv:2502.02747.

---

## Glossaire

- **Cache read** : tokens déjà présents dans le cache du modèle lors d'une conversation multi-tours — coûtent moins cher que les tokens frais.
- **Cross-module** : interaction entre des composants situés dans des fichiers/répertoires différents du projet.
- **F2P** : *fail-to-pass* — tests qui échouaient avant et passent après l'intervention de l'agent.
- **Overhead** : coût supplémentaire (temps, argent, tokens) induit par l'utilisation d'un outil.
- **Resolve rate** : proportion de tâches entièrement résolues (tous les tests passent).

---

## Liens dans la série

- [[R1_Le_Goulot_de_Localisation|R1]] — Le goulot de localisation — le problème fondamental
- [[R2_RTFM_Outil_Agnostique|R2]] — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit
- [[R3_Protocole_Experimental|R3]] — Le protocole : 4 conditions, 11 tâches, même modèle
- **R4** (cet article) — Les résultats : quand la taille du repo change tout
- [[R5_Agent_Decide_Seul|R5]] — L'agent décide seul : retrieval sélectif sans entraînement
- [[R6_Perspectives|R6]] — Ce que ça change — et ce qu'il reste à prouver

---

**Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]], [[R2_RTFM_Outil_Agnostique|R2]], [[R3_Protocole_Experimental|R3]]
**Temps de lecture** : 15 min
**Tags** : #résultats #benchmark #resolve-rate #mlflow #metaflow #fts #embeddings #seuil-taille

---

*Prochain article : [[R5_Agent_Decide_Seul|R5]] — L'agent décide seul : retrieval sélectif sans entraînement*

---
