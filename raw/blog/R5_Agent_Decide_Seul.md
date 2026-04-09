---
type: article
title: "R5) L'agent calibre seul : retrieval sélectif sans entraînement"
subtitle: "On guide l'agent vers l'outil. Mais c'est lui qui décide combien chercher — et il calibre l'intensité sans fine-tuning, sans classificateur, sans routeur."
excerpt: "La littérature dit que le retrieval systématique dégrade la performance. Notre approche : guider l'agent vers l'outil avec 3 lignes d'instructions, et le laisser calibrer l'intensité seul. L'agent fait du retrieval sélectif naturellement."
slug: retrieval-selectif-agent-autonome
focus_keyword: retrieval sélectif agent autonome
tags:
  - retrieval-selectif
  - self-rag
  - metacognition
  - agent-autonome
  - tool-use
  - repoformer
  - adaptive-rag
---

> [!abstract]- SPEC
> ## Brief — R5 : L'agent calibre seul
> ### Position dans la série
> - **Série** : R (Retrieval) — Does Retrieval Help? | **Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]] à [[R4_Resultats|R4]]
> - Analyse qualitative du comportement de l'agent
> - Connexion avec la littérature sur le retrieval adaptatif
> ### Sujets couverts
> - Self-RAG, Repoformer, FLARE : le retrieval systématique dégrade
> - Le pattern d'utilisation observé : chirurgical, pas systématique
> - Guidage léger + calibration émergente de l'intensité
> - L'universalité de l'outil : au-delà du code
> - Le trade-off coût-qualité : le coût par tâche résolue
> ### SOTAs sources
> - `paper/sota/04_adaptive_selective_retrieval.md`
> - `paper/sota/05_context_aware_retrieval_vs_exploration.md`

# R5) L'agent calibre seul

## Retrieval sélectif sans entraînement — ou pourquoi trois lignes d'instructions suffisent

> L'agent n'a pas besoin qu'on lui dise *combien* chercher. Il a besoin qu'on lui dise *où* chercher.

## Où se situe cet article ?

[[R4_Resultats|R4]] a montré les chiffres bruts. RTFM fait passer le resolve rate de 55-64% à 100% sur test_validation (mlflow, 8 260 fichiers), n'apporte rien sur test_stub_generator (metaflow, 624 fichiers), et ne compense pas la complexité intrinsèque de test_responses_agent.

Mais les chiffres seuls ne racontent pas toute l'histoire. Il y a un résultat qualitatif, peut-être plus important que les chiffres : **l'agent calibre l'intensité de sa recherche en fonction de la tâche — sans qu'on le lui ait prescrit**. On lui dit *d'utiliser* l'outil. Mais c'est lui qui décide *combien*. Et ce comportement a des implications profondes.

---

## Le piège du retrieval systématique

La littérature sur le retrieval augmenté a établi un résultat contre-intuitif : **chercher tout le temps est pire que ne jamais chercher**.

### Self-RAG : ne retriever que quand c'est utile

Self-RAG (Asai et al., ICLR 2024) a proposé un modèle qui décide lui-même quand retriever, via des "reflection tokens" spéciaux appris pendant le fine-tuning. Le résultat principal : un retrieval adaptatif surpasse le retrieval systématique de **+40% en relatif** sur PopQA. Quand on force le modèle à toujours chercher, il se noie dans du contexte non pertinent. Quand on le laisse choisir, il cherche uniquement quand il en a besoin.

### Repoformer : 70% des retrievals sont du gaspillage

Repoformer (Wu et al., ICML 2024) a mesuré le phénomène spécifiquement pour le code. Leur classificateur a identifié que **70% des retrievals de code sont inutiles** — le modèle aurait produit le même résultat sans eux. En filtrant ces retrievals inutiles, ils obtiennent un **speedup de 70%** sans perte de performance.

Soixante-dix pour cent. Sept retrievals sur dix ne servent à rien.

### FLARE : le sweet spot est adaptatif

FLARE (Jiang et al., EMNLP 2023) a exploré l'espace entre "jamais retriever" (θ=0) et "toujours retriever" (θ=1). Les deux extrêmes sont sous-optimaux. Le sweet spot est quelque part entre les deux — et il dépend du contexte.

### Adaptive-RAG : router par complexité

Adaptive-RAG (Jeong et al., NAACL 2024) va plus loin : il classifie les requêtes en trois niveaux de complexité (pas de retrieval / retrieval simple / retrieval multi-step) et route chaque requête vers le bon pipeline. La complexité de la question détermine l'intensité du retrieval.

### Le point commun

Tous ces travaux convergent vers la même conclusion : **le retrieval doit être adaptatif**. Ni toujours, ni jamais. Et pour être adaptatif, il faut un mécanisme de *décision* : quand chercher, quand ne pas chercher.

La question est : quel mécanisme ?

Self-RAG utilise du **fine-tuning** — des tokens spéciaux entraînés dans le modèle. Repoformer utilise un **classificateur** entraîné séparément. Adaptive-RAG utilise un **routeur** avec un petit modèle de classification.

Notre approche est radicalement plus simple.

---

## Notre approche : guider vers l'outil, laisser calibrer l'usage

Nous n'avons rien entraîné. Pas de fine-tuning, pas de classificateur, pas de routeur. Mais — soyons honnêtes — nous n'avons pas non plus "juste donné l'outil sans rien dire".

### Ce qu'on dit à l'agent

L'outil est déclaré dans la configuration MCP de l'agent. Il apparaît dans la liste des outils disponibles au même titre que `Read`, `Grep`, `Glob`, `Edit`, `Bash`. Jusque-là, rien de spécial.

Mais `rtfm init` injecte aussi **trois lignes d'instructions** dans le fichier `CLAUDE.md` du projet — le fichier de consignes que l'agent lit au démarrage de chaque session :

> *For any **exploratory search** (finding which files/modules/classes are relevant to a topic), use `rtfm_search` instead of Glob, find, ls, or broad Grep.*
>
> *This returns file paths + context metadata. Then continue normally — Read the files, Grep for exact patterns within them, Edit to modify.*

C'est tout. Trois lignes. Pas de règle sur *combien* chercher, pas de seuil, pas de condition "si le repo a plus de N fichiers alors cherche davantage". L'instruction dit *quoi utiliser* pour l'exploration. Elle ne dit pas *quand s'arrêter*.

### Ce que l'agent fait tout seul

Et c'est là que ça devient intéressant. Avec ces trois lignes identiques dans tous les projets, l'agent produit des comportements **radicalement différents** selon le contexte.

Sur `test_validation` (mlflow, 8 260 fichiers), l'agent fait **2-3 appels** `rtfm_search` — en début de session, pour localiser les modules pertinents. Puis il passe aux outils standard (`Read`, `Edit`) pour le reste de la tâche. Les 2-3 recherches suffisent à identifier `validation.py`, `scorers.py` et `data.py` — les trois fichiers critiques que l'agent sans retrieval ne trouve pas.

Sur `test_stub_generator` (metaflow, 624 fichiers), l'agent fait **1 appel** `rtfm_search`. Il voit que le repo est petit, que les résultats ne lui apprennent rien de plus que ce qu'il peut trouver directement. Il n'y revient pas.

Sur `test_responses_agent` (mlflow, 78K de prompt, 15 interfaces), l'agent fait **10-15 appels** `rtfm_search` — un par interface, ou presque. Il utilise l'outil intensivement parce que la tâche est massive et qu'il a besoin de localiser de nombreux fichiers.

| Tâche                | Repo     | Fichiers | Appels RTFM | Pattern                      |
| -------------------- | -------- | -------- | ----------- | ---------------------------- |
| test_stub_generator  | metaflow | 624      | 1-2         | Essai rapide, abandon        |
| test_validation      | mlflow   | 8 260    | 2-3         | Localisation ciblée en début |
| test_responses_agent | mlflow   | 8 260    | 10-15       | Utilisation intensive        |

L'instruction est la même dans les trois cas. Mais l'agent ajuste l'intensité du retrieval à la complexité de la tâche et à la taille du repo — **sans qu'aucune règle ne le prescrive**. C'est cette calibration qui est émergente, pas l'usage lui-même.

> **Encart : La différence entre guider et calibrer**
>
> Il faut distinguer deux niveaux de décision. Le premier : *utiliser ou non* l'outil de recherche. C'est guidé — les instructions CLAUDE.md disent explicitement de l'utiliser pour l'exploration. Le second : *combien* l'utiliser, avec quelle intensité, quand s'arrêter. C'est émergent — rien dans les instructions ne prescrit 1 appel plutôt que 15. Et c'est ce second niveau qui produit le retrieval sélectif.

---

## Métacognition suffisante

Ce résultat est en tension avec la littérature sur la métacognition des LLMs. Ackerman et al. (2025) ont montré que les capacités métacognitives des modèles sont "limitées en résolution et qualitativement différentes de l'humain". Les LLMs ne savent pas finement ce qu'ils savent et ce qu'ils ne savent pas.

Mais nos observations suggèrent une nuance : **les LLMs n'ont pas besoin d'une métacognition fine pour faire du retrieval sélectif**. Ils ont besoin de deux capacités beaucoup plus grossières :

1. **Détecter qu'il manque quelque chose.** "Je dois implémenter un module de validation, mais je ne vois pas de code de validation existant dans mon contexte." Ce n'est pas de la métacognition fine — c'est de la détection d'absence.

2. **Évaluer si un outil pourrait aider.** "J'ai un outil de recherche. Ma requête porte sur la validation dans un grand repo. L'outil pourrait m'aider." Ce n'est pas de la décision sophistiquée — c'est du pattern matching sur la disponibilité des outils.

La combinaison de ces deux capacités grossières, avec un outil qui coûte peu en contexte (~300 tokens par requête), produit un comportement qui *ressemble* au retrieval adaptatif — sans le mécanisme complexe.

> **Encart : La prothèse métacognitive revisitée**
>
> Dans [[R1_Le_Goulot_de_Localisation|R1]], nous avons décrit l'outil de recherche comme une "prothèse métacognitive". L'idée était que l'agent peut *vérifier* à moindre coût ce qu'il ne sait pas, sans avoir besoin de *savoir* qu'il ne sait pas. Les résultats confirment cette intuition : l'agent ne "sait" pas qu'il lui manque `scorers.py`. Mais il peut chercher "validation scorers" et obtenir la réponse en 300 tokens. Le coût de vérification est si bas que la question "est-ce que je sais ?" devient sans objet.

---

## Le trade-off coût-qualité

Un argument contre le retrieval est qu'il augmente le coût par tâche. Et c'est vrai.

Sur test_validation :

| Condition     | Coût  | Résolu ? | Coût par tâche résolue |
| ------------- | ----- | -------- | ---------------------- |
| B (Discovery) | $1.50 | Non      | ∞ (jamais résolu)      |
| C (FTS)       | $2.42 | Oui      | **$2.42**              |
| D (FTS+Embed) | $1.33 | Oui      | **$1.33**              |

Config B coûte moins cher *par tentative*. Mais elle ne résout jamais la tâche. En pratique, un développeur qui lance un agent sans succès va relancer, peut-être 2-3 fois, puis intervenir manuellement. Le coût réel de "pas de retrieval" n'est pas $1.50 — c'est $1.50 × N tentatives + le temps humain d'intervention.

Config D résout au premier essai pour $1.33. **Le coût pertinent n'est pas le coût par tentative — c'est le coût par tâche *résolue*.**

Sur test_stub_generator, le calcul est inverse :

| Condition | Coût  | Résolu ? |
| --------- | ----- | -------- |
| B         | $1.07 | Oui      |
| C         | $1.30 | Oui      |
| D         | $1.44 | Oui      |

B résout pour moins cher. L'overhead RTFM (+21% à +35%) est pur gaspillage sur un petit repo. D'où l'importance du retrieval *sélectif* : l'agent devrait utiliser RTFM intensivement sur les grands repos et l'ignorer sur les petits. Et c'est précisément ce qu'il fait — 1-2 appels sur metaflow, 2-3 sur mlflow.

---

## Au-delà du code : l'universalité comme force

Les résultats de cette étude portent sur du code. Mais la philosophie de RTFM ([[R2_RTFM_Outil_Agnostique|R2]]) est plus large : c'est un outil de *connaissance*, pas un outil de *code*.

Dans un test A/B séparé — une tâche de rédaction d'article académique, pas de code — nous avons mesuré l'impact de RTFM sur un corpus de musicologie (documents Markdown, articles publiés, notes de recherche). Après 3 itérations d'optimisation de l'outil :

| Métrique | Sans RTFM              | RTFM v3                  |
| -------- | ---------------------- | ------------------------ |
| Durée    | 8m16s                  | **6m58s** (-16%)         |
| Coût     | $22.61                 | **$11.14** (-51%)        |
| Qualité  | 10 sections, 31K chars | 14 sections, 38.5K chars |

**-51% de coût, -16% de durée, et un article plus complet.** Sur une tâche de documentation, pas de code.

L'outil remplace la navigation aveugle là où c'est nécessaire — que ce soit dans un repo de code ou dans un corpus de recherche — et ne touche pas au reste. Un `grep` dans un repo de 8 000 fichiers est aussi aveugle qu'un `grep` dans un corpus de 900 documents Markdown. Le problème est le même. La solution aussi.

---

## La leçon : guider légèrement, laisser calibrer

Résumons ce que cette série d'observations nous enseigne.

**Self-RAG, Repoformer, FLARE** nous disent que le retrieval systématique est sous-optimal. Le retrieval adaptatif est meilleur. Mais leurs mécanismes de décision (fine-tuning, classificateurs, routeurs) sont coûteux à construire et spécifiques à un modèle.

**Notre approche** tient en deux éléments : trois lignes d'instructions dans CLAUDE.md qui orientent l'agent vers l'outil pour l'exploration, et un outil bon marché qui coûte ~300 tokens par appel. Pas de mécanique de calibration. Pas de règle "si le repo dépasse N fichiers, cherche davantage". L'agent calibre seul.

Et ça marche. Pas parce que l'agent a une métacognition sophistiquée. Mais parce que :
- L'outil est **orienté** (les instructions disent "utilise-le pour l'exploration").
- L'outil est **bon marché** (~300 tokens par requête).
- L'outil est **non-invasif** (pas de contexte forcé, pas de retrieval automatique).
- L'agent a une capacité suffisante de **détection d'absence** ("il me manque quelque chose").
- **Rien ne prescrit l'intensité** — l'agent calibre seul entre 1 et 15 appels.

C'est peut-être le résultat le plus actionnable de cette étude : **il n'est pas nécessaire de construire des mécanismes sophistiqués de retrieval adaptatif. Il suffit d'orienter l'agent vers un outil bon marché et de le laisser calibrer l'intensité.**

Les agents actuels sont assez intelligents pour faire du retrieval sélectif — à condition qu'on leur montre l'outil, qu'on ne les force pas à un usage systématique, et qu'on les laisse ajuster.

---

## Références

- **Asai, A. et al. (2023)** — Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024. arXiv:2310.11511.
- **Wu, Y. et al. (2024)** — Repoformer: Selective Retrieval for Repository-Level Code Completion. ICML 2024. arXiv:2403.10059.
- **Jiang, Z. et al. (2023)** — Active Retrieval Augmented Generation (FLARE). EMNLP 2023. arXiv:2305.06983.
- **Jeong, S. et al. (2024)** — Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity. NAACL 2024.
- **Ackerman et al. (2025)** — Metacognition in Large Language Models. arXiv.
- **Galimzyanov, F. et al. (2025)** — Practical Code RAG at Scale. arXiv:2510.20609.

---

## Glossaire

- **Fine-tuning** : entraînement supplémentaire d'un modèle de langage sur des données spécialisées pour modifier son comportement.
- **Reflection token** : dans Self-RAG, token spécial appris pendant le fine-tuning qui encode la décision de retriever ou non.
- **Retrieval adaptatif/sélectif** : stratégie où le système décide au cas par cas s'il faut chercher dans un index, au lieu de toujours ou jamais chercher.
- **Routeur** : dans Adaptive-RAG, petit modèle qui classifie la complexité d'une requête pour choisir le pipeline approprié.
- **Tool use** : capacité d'un LLM à appeler des outils externes (fichiers, API, bases de données) en cours de génération.

---

## Liens dans la série

- [[R1_Le_Goulot_de_Localisation|R1]] — Le goulot de localisation — le problème fondamental
- [[R2_RTFM_Outil_Agnostique|R2]] — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit
- [[R3_Protocole_Experimental|R3]] — Le protocole : 4 conditions, 11 tâches, même modèle
- [[R4_Resultats|R4]] — Les résultats : quand la taille du repo change tout
- **R5** (cet article) — L'agent calibre seul : retrieval sélectif sans entraînement
- [[R6_Perspectives|R6]] — Ce que ça change — et ce qu'il reste à prouver

---

**Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]] à [[R4_Resultats|R4]]
**Temps de lecture** : 13 min
**Tags** : #retrieval-selectif #self-rag #metacognition #agent-autonome #tool-use #adaptive-rag

---

*Prochain article : [[R6_Perspectives|R6]] — Ce que ça change — et ce qu'il reste à prouver*

---
