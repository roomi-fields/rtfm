---
type: article
title: "R1) Le goulot de localisation : pourquoi les agents IA passent plus de temps à chercher qu'à produire"
subtitle: "Le facteur limitant des agents IA n'est pas leur intelligence — c'est leur capacité à trouver la bonne information dans un grand corpus. Que ce soit du code, du droit, de la recherche ou de la finance."
excerpt: "Les agents IA ne produisent pas la plupart du temps. Ils cherchent. Ils tâtonnent. Dès que le corpus dépasse quelques centaines de documents, ils se perdent. Ce problème touche tous les domaines — le code est juste celui où on sait le mesurer."
slug: goulot-localisation-agents-ia
focus_keyword: localisation agents IA
tags:
  - agents-ia
  - localisation
  - retrieval
  - context
  - exploration
  - connaissance
  - grands-corpus
---

> [!abstract]- SPEC
> ## Brief — R1 : Le goulot de localisation
> ### Position dans la série
> - **Série** : R (Retrieval) — Does Retrieval Help? | **Prérequis** : aucun
> - Premier article de la série : pose le problème fondamental
> - Cadrage universel (tous domaines), puis zoom sur le code comme terrain de mesure
> ### Sujets couverts
> - Le problème universel : tout utilisateur sérieux d'IA face à un grand corpus
> - Exemples concrets : chercheurs, juristes, développeurs, analystes financiers
> - Preuve empirique via les agents codeurs (littérature la plus avancée)
> - Le gap oracle, le context rot, le paradoxe métacognitif
> - La localisation comme goulot d'étranglement transversal
> ### SOTAs sources
> - `paper/sota/05_context_aware_retrieval_vs_exploration.md`
> - `paper/sota/06_localization_bottleneck.md`

# R1) Le goulot de localisation

## Pourquoi les agents IA passent plus de temps à chercher qu'à produire

> Les agents IA sont partout. Mais que font-ils *vraiment* de leur temps ?

## Où se situe cet article ?

Cet article ouvre une série de six billets consacrés à une question simple : **est-ce qu'un agent IA travaille mieux quand on lui donne un outil de recherche pré-indexé sur sa base de connaissances ?**

La question a l'air évidente — *bien sûr que oui*. Mais personne ne l'a mesurée rigoureusement. Et la question concerne tout le monde — pas seulement les développeurs.

Dans cette série, nous documentons notre démarche : comprendre le problème (cet article), concevoir un outil ([[R2_RTFM_Outil_Agnostique|R2]]), construire un protocole expérimental ([[R3_Protocole_Experimental|R3]]), analyser les résultats ([[R4_Resultats|R4]]), et en tirer les leçons ([[R5_Agent_Decide_Seul|R5]], [[R6_Perspectives|R6]]).

Commençons par le commencement : quel problème partagent un développeur, un juriste, un chercheur et un analyste financier quand ils utilisent un agent IA ?

---

## Le problème universel : chercher dans un grand corpus

### Ce n'est pas un problème de code. C'est un problème de connaissance.

Imaginez un juriste qui demande à un agent IA de rédiger une analyse sur la fiscalité des plus-values immobilières. Le corpus de travail : le Code général des impôts (3 000+ articles), le BOFiP (des milliers de pages de doctrine), la jurisprudence du Conseil d'État, les rescrits, les conventions internationales. L'agent connaît le droit fiscal *en général* — il l'a vu dans ses données d'entraînement. Mais connaît-il le rescrit n° 2024-12 publié en mars dernier qui change l'interprétation de l'article 150 VB ? Non. Cette information est dans le corpus local du cabinet, pas dans les données d'entraînement.

Que fait l'agent ? Il rédige avec ce qu'il sait — c'est-à-dire avec des connaissances potentiellement obsolètes ou incomplètes. Ou il cherche. Il navigue dans les fichiers, ouvre des documents, les referme, en ouvre d'autres. Il tâtonne.

Imaginez un chercheur en physique des particules qui demande à un agent de synthétiser l'état de l'art sur la masse du boson W. Le corpus : 500 articles dans son Zotero, ses notes Obsidian, les annexes de sa propre thèse, les données expérimentales du CERN. L'agent sait ce qu'est le boson W. Mais sait-il que la note interne ATLAS-CONF-2025-003 contredit le résultat CDF de 2022 ? Non. C'est dans le corpus du chercheur.

Imaginez un analyste financier qui demande à un agent de modéliser l'impact d'une hausse de taux sur un portefeuille. Le corpus : les rapports trimestriels de 200 entreprises, les notes de brokers, les minutes de la Fed, les modèles internes. L'agent connaît la théorie financière. Mais connaît-il la clause de covenants de l'émission obligataire de mars 2025 de la société X qui change la donne ? Non. C'est dans un PDF sur le drive de l'équipe.

Imaginez un développeur qui demande à un agent d'implémenter une fonctionnalité dans un projet de 8 000 fichiers. L'agent sait coder. Mais sait-il que `validation.py` dépend de `scorers.py` qui dépend de `data.py` — trois fichiers dispersés dans des sous-répertoires différents ? Non. C'est dans le codebase, pas dans sa mémoire.

**Le problème est le même dans tous les cas** : l'agent a besoin d'informations qui sont dans le corpus local, pas dans ses données d'entraînement. Et il n'a aucun moyen efficace de les trouver.

### Pourquoi c'est un problème *maintenant*

Ce problème n'est pas nouveau — les moteurs de recherche existent depuis 30 ans. Ce qui est nouveau, c'est l'**échelle d'utilisation des agents IA sur des corpus spécialisés**.

En 2024-2025, les agents IA sont passés du statut de curiosité à celui d'outil de travail quotidien. Claude Code écrit du code en production. Les cabinets d'avocats utilisent des agents pour la recherche juridique. Les analystes utilisent des agents pour synthétiser des rapports. Les chercheurs utilisent des agents pour la revue de littérature.

Et tous rencontrent le même mur : **dès que le corpus dépasse quelques centaines de documents, l'agent se perd**. Il ne sait pas ce qui est dans le corpus. Il ne sait pas *où* chercher. Il navigue à l'aveugle avec des outils rudimentaires — des `grep` et des `find` pour le code, des copier-coller manuels pour le reste.

---

## La preuve par le code : le domaine où on sait mesurer

Le problème est universel. Mais pour le *mesurer*, il faut un terrain de jeu avec des métriques objectives. C'est le code qui offre ce terrain.

Pourquoi le code ? Parce qu'il existe des benchmarks standardisés (SWE-bench, FeatureBench), des métriques binaires (le test passe ou non), des environnements reproductibles (Docker), et une littérature croissante qui analyse le comportement des agents. Aucun autre domaine n'a cet outillage.

Les résultats de la recherche en agents codeurs sont donc le meilleur *proxy* pour comprendre un problème qui touche tous les domaines.

### L'agent qui ne code pas

Une étude de trajectoires d'agents sur SWE-bench (Trajectory Study, 2025) a analysé des milliers de runs. Le constat : **38% des actions d'un agent codeur sont de l'exploration** — des `grep`, des `find`, des lectures de fichiers — pas de l'écriture de code. L'agent cherche. Il tâtonne. Il ouvre des fichiers, les referme, en ouvre d'autres. Et sur les agents qui *échouent*, ce ratio monte encore : ils tournent en boucle sans trouver ce qu'ils cherchent.

Transposez ce chiffre au juriste : 38% de son temps avec l'agent est passé à naviguer dans les fichiers du corpus au lieu de rédiger l'analyse. Au chercheur : 38% à ouvrir des PDFs au lieu de synthétiser. Au développeur : 38% à faire des `grep` au lieu de coder.

Le même type d'analyse révèle un ratio de tokens hallucinant : entre les agents les plus et les moins efficaces, le rapport de tokens consommés est de **52x** — cinquante-deux fois plus de tokens pour arriver au même résultat, ou ne pas y arriver du tout. La majorité de ces tokens sont du bruit d'exploration. Du gaspillage pur.

Ce phénomène porte un nom dans la littérature : **le goulot de localisation**. Avant de pouvoir *produire*, l'agent doit d'abord *trouver* l'information pertinente. Et c'est là que les choses se compliquent.

---

## La localisation, c'est la moitié du problème

PatchPilot (ICML 2025) a quantifié ce goulot de manière frappante dans le domaine du code. Les auteurs ont décomposé l'amélioration d'un agent codeur en composantes : localisation du code pertinent, génération du patch, validation. Résultat : **la capacité de localisation compte pour environ 47% de l'amélioration totale** d'un agent. Presque la moitié.

Dit autrement : si vous améliorez la capacité d'un agent à *trouver* la bonne information, vous améliorez presque autant ses résultats que si vous amélioriez sa capacité à *utiliser* cette information. Ce résultat est mesuré sur du code, mais l'intuition est transversale. Le juriste qui trouve immédiatement le bon article de loi rédige une meilleure analyse que celui qui tâtonne pendant vingt minutes.

Agentless (Xia et al., 2024) a montré qu'une approche hiérarchique — chercher d'abord le bon fichier, puis la bonne section, puis le bon passage — fonctionne remarquablement bien. Leur méthode atteint 77.7% de rappel au niveau fichier. Mais au niveau ligne ? 50.8%. Trouver le bon *document* est relativement facile. Trouver le bon *passage* dans ce document est deux fois plus dur.

LocAgent (ACL 2025) confirme : en guidant l'agent par un graphe de dépendances, on atteint 92.7% de précision. Et Navigation Paradox (2026) a donné à un agent un outil de navigation structurée exposé via MCP. Résultat : **+23.2 points de pourcentage** de résolution. Juste en donnant à l'agent un outil de navigation un peu plus intelligent que `grep`.

---

## Le gap oracle : la preuve que le contexte est le facteur limitant

Le résultat le plus frappant vient de CodeRAG-Bench (Wang et al., NAACL 2025 Findings). Les auteurs ont mesuré la performance de modèles dans trois conditions : sans contexte externe, avec du contexte récupéré par un système de recherche standard (BM25), et avec le *contexte parfait* — un oracle qui donne exactement les documents pertinents.

| Condition                | StarCoder2-7B sur HumanEval | GPT-4o sur SWE-bench Lite |
| ------------------------ | --------------------------- | ------------------------- |
| Sans contexte            | 31.7%                       | 2.3%                      |
| Avec BM25                | 43.9%                       | 21.7%                     |
| **Avec contexte oracle** | **94.5%**                   | **30.7%**                 |

De 31.7% à 94.5%. Le même modèle, la même tâche. La seule différence : la qualité du contexte fourni.

L'écart entre le meilleur retrieval actuel et l'oracle est de **9 à 50 points de pourcentage** selon le modèle et la tâche. Ce sont des points de performance "gratuits" qui attendent qu'on les prenne, simplement en améliorant la qualité du retrieval.

La conclusion est limpide : **le facteur limitant n'est pas le modèle, c'est le contexte qu'on lui fournit.** Cette conclusion est démontrée sur du code. Mais elle s'applique à tout domaine où l'agent doit travailler sur un corpus spécialisé. Le juriste avec le bon contexte juridique produit une meilleure analyse. Le chercheur avec les bonnes références produit une meilleure synthèse. Le modèle est le même — c'est le contexte qui fait la différence.

---

## Les outils aveugles

Comment un agent explore-t-il un corpus aujourd'hui ?

Pour le code : `grep`, `glob`, `find` et `cat`. Des outils de terminal conçus pour les humains dans les années 1970.

Pour le reste — droit, recherche, finance — c'est souvent *pire*. L'agent n'a même pas d'outil de recherche sur le corpus local. Il travaille avec ce qu'on lui colle dans le prompt : quelques documents copiés-collés, un RAG basique qui renvoie des chunks hors contexte, ou rien du tout.

Ces approches ont trois problèmes fondamentaux :

**Elles sont aveugles.** `grep` ne connaît pas la structure du projet. Le RAG basique ne connaît pas les relations entre documents. L'agent qui cherche "plus-values immobilières" dans un corpus juridique de 10 000 documents obtient 300 résultats — il n'est pas plus avancé qu'avant.

**Elles sont coûteuses en contexte.** Chaque résultat est chargé dans la fenêtre de contexte de l'agent. Et la littérature montre que trop de contexte *dégrade* la performance. Hong et al. (2025) ont démontré le phénomène du **context rot** : au-delà d'un certain seuil, ajouter du contexte fait *baisser* la qualité des réponses. Le bruit noie le signal. ContextBench (2025) ajoute que même quand les agents trouvent le bon contexte, seuls 50 à 70% de l'information est effectivement retenue — voir n'est pas utiliser.

**Elles ne savent pas quand s'arrêter.** AgentDiet (2025) a montré que **40 à 60% des tokens d'exploration sont du gaspillage pur** — on peut les retirer des trajectoires d'agents *sans affecter le résultat final*. L'agent explore, mais une grosse partie de cette exploration ne sert à rien.

> **Encart : Le juriste et le développeur ont le même problème**
>
> Un développeur qui fait `grep -r "validate" .` dans un repo de 8 000 fichiers et obtient 847 résultats est exactement dans la même situation qu'un juriste qui cherche "exonération" dans 3 000 articles du CGI et obtient 200 occurrences. L'outil ne comprend pas la *structure* du corpus, les *relations* entre documents, ni la *pertinence* contextuelle. Il cherche du texte dans des fichiers. C'est un outil des années 1970 utilisé par une IA de 2026.

---

## Le paradoxe métacognitif

Il y a un problème plus profond encore, et c'est celui qui motive le plus directement notre travail. Ce problème est le même quel que soit le domaine.

**Les LLMs ne savent pas ce qu'ils ne savent pas.**

Ackerman et al. (2025) ont étudié les capacités métacognitives des modèles de langage — leur capacité à évaluer ce qu'ils savent et ce qui leur manque. La conclusion : ces capacités sont "croissantes mais limitées en résolution, dépendantes du contexte, et qualitativement différentes de l'humain".

C'est un problème existentiel pour tout agent IA travaillant sur un corpus spécialisé :
- Le développeur : comment l'agent peut-il savoir qu'il doit chercher `scorers.py` s'il ignore que ce fichier existe ?
- Le juriste : comment l'agent peut-il savoir que le rescrit n° 2024-12 change l'analyse s'il n'a jamais vu ce rescrit ?
- Le chercheur : comment l'agent peut-il savoir que ATLAS-CONF-2025-003 contredit CDF si ce document est dans le corpus local ?
- L'analyste : comment l'agent peut-il savoir que la clause de covenants change le modèle si elle est dans un PDF qu'il n'a pas lu ?

Dans tous les cas, **l'agent ne sait pas ce qu'il ne sait pas**. Il produit avec ce qu'il a — des connaissances d'entraînement, potentiellement obsolètes ou incomplètes — au lieu de vérifier dans le corpus local.

Notre intuition : **l'agent n'a pas besoin de *savoir* ce qu'il ne sait pas. Il a besoin d'un moyen de *vérifier* à faible coût.**

Un outil de recherche pré-indexé sur le corpus local, c'est exactement ça : une **prothèse métacognitive**. L'agent peut se demander "est-ce que mon corpus contient quelque chose sur la validation des scorers ?" / "est-ce qu'il y a un rescrit récent sur le 150 VB ?" / "est-ce que ATLAS a publié une note contradictoire ?" — et obtenir une réponse en quelques centaines de tokens au lieu de naviguer pendant dix minutes.

La question n'est pas "l'agent sait-il qu'il ne sait pas ?". C'est "l'agent peut-il vérifier à moindre coût ce qu'il ne sait pas ?". Et si oui, est-ce que ça change les résultats ?

---

## Ce que la littérature suggère — et ne prouve pas

Résumons ce que nous savons — en gardant à l'esprit que ces résultats sont mesurés sur du code, mais que le mécanisme est transversal :

| Trouvaille                       | Source                     | Ce que ça implique                                         |
| -------------------------------- | -------------------------- | ---------------------------------------------------------- |
| 38% des actions = exploration    | Trajectory Study (2025)    | L'exploration est le poste principal de dépense d'un agent |
| Localisation = 47% du gain total | PatchPilot (ICML 2025)     | Mieux localiser ≈ mieux produire                           |
| Gap oracle = 9-50 pp             | CodeRAG-Bench (NAACL 2025) | Chaque point de retrieval = point de performance           |
| 40-60% des tokens gaspillés      | AgentDiet (2025)           | Beaucoup d'exploration est inutile                         |
| Context rot                      | Hong et al. (2025)         | Trop de contexte dégrade la performance                    |
| Voir ≠ utiliser                  | ContextBench (2025)        | Contexte minimal ciblé > dump massif                       |
| LLMs ≠ métacognition fine        | Ackerman et al. (2025)     | L'outil externe comme prothèse                             |
| Navigation MCP = +23.2 pp        | Navigation Paradox (2026)  | Un outil de navigation aide l'agent                        |

Tout pointe dans la même direction : donner un outil de recherche à un agent IA travaillant sur un grand corpus *devrait* améliorer ses résultats.

Mais personne ne l'a *prouvé* dans un protocole contrôlé sur un benchmark standardisé. Les études ci-dessus montrent des corrélations, des ablations, des analyses post-hoc. Elles ne montrent pas l'expérience directe : même agent, même tâche, même modèle — avec et sans outil de recherche.

C'est ce que nous avons fait. Nous avons choisi le code comme terrain de mesure — parce que c'est le seul domaine qui offre des benchmarks standardisés avec des métriques objectives. Mais l'outil que nous avons construit ([[R2_RTFM_Outil_Agnostique|R2]]) est agnostique : il indexe du code, de la documentation, du droit, de la recherche, des données — tout corpus textuel structuré. Et les leçons que nous en tirons ([[R5_Agent_Decide_Seul|R5]], [[R6_Perspectives|R6]]) s'appliquent à tout domaine.

Le protocole est décrit en [[R3_Protocole_Experimental|R3]]. Les résultats sont en [[R4_Resultats|R4]].

---

## Références

- **Trajectory Study (2025)** — Analyse de trajectoires d'agents codeurs sur SWE-bench. arXiv:2506.18824.
- **PatchPilot (2025)** — Décomposition des gains d'agents codeurs : localisation, génération, validation. ICML 2025. arXiv:2502.02747.
- **Xia, C.S. et al. (2024)** — Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489.
- **Chen, Y. et al. (2025)** — LocAgent: Graph-Guided LLM Agents for Code Localization. ACL 2025. arXiv:2503.09089.
- **Navigation Paradox (2026)** — CodeCompass MCP et le paradoxe de la navigation. arXiv:2602.20048.
- **Wang, Z. et al. (2024)** — CodeRAG-Bench: Can Retrieval Augment Code Generation? NAACL 2025 Findings. arXiv:2406.14497.
- **Hong, J. et al. (2025)** — Context Rot: Understanding the Impact of Context on Retrieval-Augmented Generation. Chroma Research.
- **ContextBench (2025)** — A Benchmark for Context Retrieval in Coding Agents. arXiv:2602.05892.
- **AgentDiet (2025)** — Trajectory Optimization for Coding Agents.
- **Ackerman et al. (2025)** — Metacognition in Large Language Models. arXiv.
- **Jimenez, C.E. et al. (2024)** — SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.

---

## Glossaire

- **Agent IA** : système autonome qui utilise un LLM pour accomplir des tâches complexes — rédaction, analyse, code, recherche.
- **Context rot** : dégradation de la performance d'un LLM quand le contexte fourni dépasse un seuil critique — le bruit noie le signal.
- **Corpus local** : l'ensemble des documents spécifiques à un projet, une entreprise, un chercheur — par opposition aux données d'entraînement du modèle.
- **Gap oracle** : différence de performance entre le meilleur retrieval actuel et un oracle fournissant le contexte parfait.
- **Goulot de localisation** : le fait que la capacité à *trouver* la bonne information est souvent le facteur limitant de la performance d'un agent, pas sa capacité à *utiliser* cette information.
- **LLM** : *Large Language Model* — modèle de langage de grande taille (Claude, GPT, Gemini, etc.).
- **MCP** : *Model Context Protocol* — standard ouvert d'Anthropic pour la communication entre agents IA et outils externes.
- **Métacognition** : capacité d'un système à évaluer ce qu'il sait et ce qui lui manque.
- **Prothèse métacognitive** : outil externe permettant à un agent de vérifier ce qu'il ne sait pas, compensant les limites de sa propre métacognition.
- **RAG** : *Retrieval-Augmented Generation* — technique consistant à enrichir le prompt d'un LLM avec des documents récupérés par un moteur de recherche.
- **Retrieval** : récupération d'information pertinente à partir d'un index — par opposition à la navigation séquentielle.

---

## Liens dans la série

- **R1** (cet article) — Le goulot de localisation — le problème fondamental
- [[R2_RTFM_Outil_Agnostique|R2]] — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit
- [[R3_Protocole_Experimental|R3]] — Le protocole : 4 conditions, 11 tâches, même modèle
- [[R4_Resultats|R4]] — Les résultats : quand la taille du repo change tout
- [[R5_Agent_Decide_Seul|R5]] — L'agent décide seul : retrieval sélectif sans entraînement
- [[R6_Perspectives|R6]] — Ce que ça change — et ce qu'il reste à prouver

---

**Prérequis** : aucun
**Temps de lecture** : 14 min
**Tags** : #agents-ia #localisation #retrieval #context #exploration #connaissance #grands-corpus

---

*Prochain article : [[R2_RTFM_Outil_Agnostique|R2]] — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit*

---
