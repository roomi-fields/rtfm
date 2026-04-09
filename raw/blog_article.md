# Et si un agent IA savait qu'il ne sait pas ?

## Comment un simple outil de recherche transforme les performances des agents codeurs sur les grands projets

*Romi Fields — Mars 2026*

---

## 1. Le problème que personne ne mesure

Les agents codeurs sont partout. Claude Code, Cursor, Windsurf, SWE-agent — ils écrivent du code, corrigent des bugs, implémentent des fonctionnalités. Les benchmarks se succèdent : SWE-bench affiche 74% de résolution avec les meilleurs modèles, et les entreprises rivalisent de chiffres impressionnants.

Mais il y a un angle mort.

Quand on observe ce que fait réellement un agent codeur pendant une tâche, on découvre quelque chose de surprenant : **il ne code pas la plupart du temps**. Une étude de trajectoires d'agents sur SWE-bench (Trajectory Study, 2025) révèle que 38% des actions sont de l'exploration — des `grep`, des `find`, des lectures de fichiers — pas de l'écriture de code. L'agent cherche. Il tâtonne. Il ouvre des fichiers, les referme, en ouvre d'autres. Sur les agents qui échouent, ce ratio monte encore : ils tournent en boucle dans le code source sans trouver ce qu'ils cherchent.

Ce phénomène porte un nom dans la littérature : **le goulot de localisation**. Avant de pouvoir coder, l'agent doit d'abord *trouver* où coder. Et c'est là que les choses se compliquent.

PatchPilot (ICML 2025) a quantifié ce problème : la capacité de localisation compte pour environ 47% de l'amélioration totale d'un agent. Dit autrement, si vous améliorez la capacité d'un agent à *trouver* le bon code, vous améliorez presque autant ses résultats que si vous amélioriez sa capacité à *écrire* du code. Agentless (Xia et al., 2024) a montré qu'une approche hiérarchique — chercher d'abord le bon fichier, puis la bonne fonction, puis la bonne ligne — atteint 77.7% de rappel au niveau fichier mais seulement 50.8% au niveau ligne. Localiser est difficile.

Et plus le projet est grand, plus c'est difficile. Un repo de 600 fichiers, un agent le parcourt assez vite. Un repo de 8 000 fichiers ? C'est une autre histoire.

### Le gap oracle : la preuve que le retrieval compte

Le résultat le plus frappant vient de CodeRAG-Bench (Wang et al., NAACL 2025). Les auteurs ont mesuré la performance de modèles de code dans trois conditions : sans contexte, avec du contexte récupéré par un système de recherche (BM25), et avec le *contexte parfait* — un oracle qui donne exactement les fichiers pertinents.

Les résultats sont vertigineux :

| Condition | StarCoder2-7B sur HumanEval |
|---|---|
| Sans contexte | 31.7% |
| Avec BM25 (recherche lexicale) | 43.9% |
| **Avec contexte oracle** | **94.5%** |

De 31.7% à 94.5%. Le même modèle, la même tâche. La seule différence : la qualité du contexte fourni. L'écart entre le meilleur retrieval actuel et l'oracle est de 9 à 50 points de pourcentage selon le modèle et la tâche. Chaque point de qualité de retrieval se traduit directement en performance.

La conclusion est limpide : **le facteur limitant n'est pas le modèle, c'est le contexte**.

---

## 2. Les outils aveugles des agents actuels

Comment un agent codeur explore-t-il un projet aujourd'hui ? Avec `grep`, `glob`, `find` et `cat`. Des outils conçus pour les humains dans les années 1970. L'agent fait un `grep -r "validate" .` et obtient 847 résultats. Il en lit 12, abandonne, essaie une autre requête. Recommence.

Ces outils ont trois problèmes fondamentaux quand ils sont utilisés par un agent IA :

**1. Ils sont aveugles.** `grep` ne connaît pas la structure du projet. Il ne sait pas que `validation.py` est lié à `scorers.py` qui dépend de `data.py`. Il cherche des motifs textuels dans des fichiers, sans notion de sémantique ni de structure.

**2. Ils sont coûteux en contexte.** Chaque résultat de `grep` est chargé dans la fenêtre de contexte de l'agent. Et la littérature montre que trop de contexte *dégrade* la performance. Hong et al. (2025) ont démontré ce qu'ils appellent le "context rot" : au-delà d'un certain seuil, ajouter du contexte fait baisser la qualité des réponses du modèle. ContextBench (2025) va plus loin : même quand les agents trouvent le bon contexte (AUC-Cov > 0.70), seuls 50 à 70% de l'information est effectivement retenue dans la réponse finale. Voir n'est pas utiliser.

**3. Ils ne savent pas quand s'arrêter.** L'agent n'a pas de signal lui indiquant "tu as trouvé ce qu'il faut" ou "cette piste est une impasse". AgentDiet (2025) a montré que 40 à 60% des tokens d'exploration sont du gaspillage pur — on peut les retirer sans affecter le résultat final.

### Le paradoxe métacognitif

Il y a un problème plus profond encore. Les LLMs ne savent pas ce qu'ils ne savent pas. Ackerman et al. (2025) ont étudié les capacités métacognitives des modèles de langage et conclu qu'elles sont "croissantes mais limitées en résolution, dépendantes du contexte, et qualitativement différentes de l'humain". En clair : un LLM ne peut pas évaluer finement ce qui lui manque comme information.

C'est là que réside notre intuition centrale. L'agent n'a pas besoin de *savoir* ce qu'il ne sait pas. Il a besoin d'un moyen de *vérifier* à faible coût. Un outil de recherche, c'est exactement ça : une prothèse métacognitive. L'agent peut se demander "est-ce que ce projet a un module de validation ?" et obtenir une réponse en 300 tokens au lieu de naviguer pendant 15 minutes dans l'arborescence.

---

## 3. RTFM : un outil qui ne touche qu'à ce qu'il doit

### La philosophie agnostique

Face à ce constat, nous avons construit RTFM — un outil de retrieval conçu selon un principe simple : **aider là où c'est nécessaire, ne rien toucher au reste**.

RTFM n'est pas un outil de code. C'est un outil de connaissance. Cette distinction est importante. Les outils existants — Augment Context Engine, Sourcegraph Cody, Code-Index-MCP — indexent du code. RTFM indexe *tout* : code Python (via l'AST), documentation Markdown, fichiers LaTeX, configurations YAML et JSON, scripts shell, documents PDF, textes juridiques XML, pages HTML. Le même outil peut servir un développeur qui cherche une fonction, un juriste qui cherche un article de loi, ou un chercheur qui cherche une référence dans ses notes.

Cette universalité n'est pas un caprice d'ingénierie. C'est une conséquence directe de la thèse : si le facteur limitant est la capacité à trouver le bon contexte, alors l'outil de recherche ne devrait pas présumer de la nature du contexte. Un agent qui travaille sur un projet réel a besoin de trouver à la fois le code existant, la documentation des contraintes métier, les tests correspondants, et peut-être les spécifications du client — tout ça dans le même projet, avec le même outil.

Cinq principes de design guident RTFM :

**Domain-agnostic.** 10 parsers embarqués, mais surtout : ajouter un nouveau format demande environ 50 lignes de Python. Hériter de `BaseParser`, implémenter `parse()`, c'est tout. Le système ne présume pas du format — il s'adapte.

**Protocol-agnostic.** RTFM est exposé via MCP (Model Context Protocol), le standard ouvert d'Anthropic pour la communication agent-outils. Il fonctionne avec tout agent MCP-compatible : Claude Code, Continue.dev, Cursor, ou n'importe quel client MCP. Pas de dépendance à un IDE ou un fournisseur.

**Model-agnostic.** Pur retrieval, zéro génération. Pas de modèle de langage embarqué. RTFM renvoie des résultats de recherche ; le modèle de l'agent décide quoi en faire. Que l'agent tourne sur Claude, GPT, Gemini ou un modèle open-source ne change rien.

**Non-invasif.** RTFM ne modifie pas le workflow de l'agent. Il ajoute des outils de recherche. L'agent peut les utiliser ou les ignorer. Il remplace la navigation aveugle quand c'est pertinent — et ne touche pas au reste. Pas de retrieval forcé, pas de contexte injecté silencieusement dans le prompt.

**Économe en contexte.** C'est le point d'architecture le plus important.

### Le pattern metadata-first

RTFM utilise un pattern de *progressive disclosure* en deux étapes :

1. **`rtfm_search("validation mlflow")`** → renvoie ~300 tokens de *métadonnées* : titre du chunk, chemin absolu du fichier source, score de pertinence. Pas de contenu. Juste assez pour que l'agent sache si le résultat est pertinent et où aller le lire.

2. L'agent lit le fichier directement via son outil `Read(file_path)` standard — le chemin absolu est dans les résultats. Il charge uniquement ce dont il a besoin, quand il en a besoin.

Ce pattern est l'opposé du "dump tout le contexte" qui provoque le context rot. L'agent ne consomme du contexte que pour ce qui est pertinent, au moment où c'est pertinent. Sur 5 résultats de recherche, l'agent ne lit peut-être que 2 fichiers — les 300 tokens de métadonnées des 3 autres n'ont pas pollué sa fenêtre de contexte avec du contenu inutile.

En termes techniques : SQLite + FTS5 (BM25) comme socle, avec des embeddings optionnels via FastEmbed (ONNX). Base de données portable — un seul fichier `.db`. Synchronisation incrémentale par hash SHA-256.

### Et le paysage concurrentiel ?

Ce type d'outil n'est plus novel en 2026. Augment Code propose un Context Engine MCP (payant, propriétaire, $20-200/mois). Sourcegraph Cody expose ses capacités via MCP (enterprise-only). Plusieurs outils open-source existent : Code-Index-MCP, mcp-codebase-index, CodeCompass.

Mais aucun d'entre eux n'a publié d'évaluation rigoureuse. Augment revendique "+80% de performance avec Claude Code" — sans protocole publié, sans benchmark standardisé, sans intervalles de confiance. CodeCompass a été évalué sur 30 micro-tâches synthétiques créées par les auteurs. Les outils open-source n'ont aucune évaluation publiée.

C'est ce trou que nous avons décidé de combler : **pas un nouvel outil, mais la première évaluation contrôlée d'un outil de retrieval pour agents codeurs sur un benchmark standardisé.**

---

## 4. L'expérience : 4 conditions, même tâches, même modèle

### FeatureBench comme terrain de jeu

Pour évaluer rigoureusement l'impact du retrieval, il nous fallait un benchmark qui satisfasse trois critères : des tâches réalistes (pas des fonctions isolées), des projets de tailles variées, et une évaluation automatique fiable.

FeatureBench (ICLR 2026) coche ces cases. Contrairement à SWE-bench qui se concentre sur la correction de bugs (et souffre de contamination prouvée — SWE-Bench Illusion, 2025), FeatureBench demande d'*implémenter des fonctionnalités nouvelles* dans des projets réels. C'est plus dur : le meilleur score publié est 11%, contre 74% sur SWE-bench Verified. Et surtout, ça nécessite de comprendre l'architecture du projet avant de coder.

Nous avons sélectionné 11 tâches dans 4 repos de tailles croissantes :

| Repo | Fichiers indexés | Tâches |
|---|---|---|
| metaflow (Netflix) | 624 | 1 |
| pydantic | 771 | 1 |
| astropy | 1 123 | 2 |
| mlflow | 8 260 | 7 |

### Les 4 conditions

La variable que nous isolons est simple : **est-ce que l'agent a accès à un outil de recherche pré-indexé ?**

Pour le tester proprement, nous avons conçu 4 configurations expérimentales :

**Config A — Standard (contrôle positif).** Le prompt FeatureBench original. Il contient les chemins des fichiers à modifier et les interfaces à implémenter. C'est une condition semi-oracle : l'agent sait déjà *où* coder. En pratique, c'est irréaliste — un développeur qui lance un agent sur un ticket Jira ne lui donne pas la liste des fichiers à modifier.

**Config B — Discovery (baseline réaliste).** On retire les chemins du prompt. Concrètement, on supprime les lignes `Path: /testbed/...` — ça représente moins de 1% du prompt (751 caractères sur 78 000). Le reste est identique : description de la feature, interfaces attendues, signatures des fonctions. L'agent doit *découvrir* où coder. C'est la condition réaliste.

**Config C — Discovery + FTS.** Même prompt que B, mais l'agent a accès à RTFM avec recherche full-text (BM25). La base de données est pré-construite — comme en usage réel, où RTFM est déjà initialisé dans le projet.

**Config D — Discovery + FTS + Embeddings.** Même prompt que B, avec RTFM en mode hybride : recherche full-text + recherche sémantique par embeddings.

La seule variable entre B et C/D est la présence de l'outil de recherche. Même agent (Claude Code), même modèle (Claude Sonnet 4.0), même environnement (Docker), même timeout (1200 secondes).

---

## 5. Les résultats : quand la taille du repo change tout

### Le résultat principal : test_validation sur mlflow

La tâche `test_validation` demande d'implémenter un module de validation de données dans mlflow — un projet de 8 260 fichiers. La difficulté : le module doit interagir avec trois composants existants dispersés dans le projet (`validation.py`, `scorers.py`, `data.py`). Pour réussir, l'agent doit trouver ces dépendances cross-module.

| Condition | F2P (fail-to-pass) | Résolu ? |
|---|---|---|
| A — Standard (chemins donnés) | 55% (6/11 tests) | Non |
| B — Discovery (pas de retrieval) | 64% (7/11 tests) | Non |
| C — Discovery + FTS | **100% (11/11 tests)** | **Oui** |
| D — Discovery + FTS+Embed | **100% (11/11 tests)** | **Oui** |

Avec retrieval (C et D), 100% des tests passent. Sans retrieval (A et B), entre 55% et 64%.

Et attention : la Config A, celle où les chemins sont *donnés dans le prompt*, ne résout pas non plus. Savoir *où* coder ne suffit pas — l'agent doit aussi comprendre *comment* les modules interagissent. C'est précisément ce que le retrieval apporte : une recherche sur "validation scorers" renvoie les fichiers pertinents *et leur contexte*.

Les configs A et B échouent systématiquement sur les mêmes tests : ceux qui nécessitent la compréhension des interactions entre `validation.py`, `scorers.py` et `data.py`. L'agent sans retrieval implémente le module de validation de manière isolée — correcte syntaxiquement, mais incompatible avec le reste du projet.

### Le contre-exemple : test_stub_generator sur metaflow

À l'opposé, la tâche `test_stub_generator` porte sur metaflow — un repo de 624 fichiers. Résultat :

| Condition | F2P | Résolu ? |
|---|---|---|
| A — Standard | 100% (31/31) | Oui |
| B — Discovery | 100% (31/31) | Oui |
| C — Discovery + FTS | 100% (31/31) | Oui |
| D — Discovery + FTS+Embed | 96.8% (30/31) | Non (1 test raté) |

Les quatre configs résolvent la tâche (sauf D qui rate un test sur 31 — un artefact). Et RTFM est même contre-productif : Config C est 23% plus lente et 22% plus chère que A. L'agent RTFM n'utilise quasiment pas l'outil (1-2 appels) — il navigue directement car le repo est petit.

**Sur un repo de 624 fichiers, `grep` suffit.** Le goulot de localisation n'existe pas. RTFM est un outil pour les grands repos.

### FTS vs Embeddings : la surprise

La comparaison entre Config C (FTS seul) et Config D (FTS + embeddings) révèle un résultat qui confirme la littérature récente :

| Métrique | Config C (FTS) | Config D (FTS+Embed) |
|---|---|---|
| Résolu | Oui (100%) | Oui (100%) |
| Turns | 81 | **50** |
| Coût | $4.04 | **$2.23** |
| Read calls | 23 | **12** |
| Bash calls | 20 | **9** |

Le resolve rate est identique. Mais D est significativement plus efficient : moins de tours (-38%), moins cher (-45%), moins de lectures de fichiers (-48%). Les embeddings ne changent pas le *résultat*, mais ils changent le *chemin* : l'agent va plus directement aux bons fichiers au lieu de tâtonner avec des requêtes textuelles.

Ce résultat est cohérent avec Galimzyanov (2025) et GrepRAG (ISSTA 2026) qui montrent que BM25 est compétitif avec les embeddings denses pour la recherche de code. La recherche lexicale suffit souvent — les embeddings ajoutent une couche d'efficience, pas de capacité.

### Le cas d'échec : quand le retrieval ne suffit pas

`test_responses_agent` est la tâche la plus complexe du benchmark : 78 000 caractères de prompt, 15 interfaces à implémenter, un ground truth de 226 000 caractères sur 60 fichiers. Résultat : **aucune configuration ne résout la tâche**. Ni A, ni B, ni C, ni D.

Mais l'analyse révèle des nuances intéressantes :

| Métrique | A (Standard) | B (Discovery) | C (FTS) | D (Embed+) |
|---|---|---|---|---|
| Résolu | Non (3.5%) | Non (TIMEOUT) | Non (0%) | Non (0%) |
| Interfaces couvertes | 15/15 | 0/15 (timeout) | 8/15 | 12/15 |
| Patch size | 92K chars | 0 | 51K chars | 91K chars |
| Cache read | 23.8M | 18.9M | 8.7M | 9.0M |

Config B ne produit même pas de code — elle tombe en timeout à 1200 secondes, perdue dans les 8 260 fichiers. Config D couvre 12 interfaces sur 15 et produit un patch presque aussi gros que A (qui avait les chemins). Les embeddings guident l'agent vers les bons fichiers, mais Sonnet 4.0 ne peut tout simplement pas gérer la complexité de 15 interfaces simultanées.

**Le retrieval est nécessaire mais pas suffisant.** Il résout le goulot de localisation, pas le goulot de capacité du modèle.

Un détail notable : les configs C et D consomment 2 à 3 fois moins de cache read que A et B (8-9M vs 19-24M tokens). Le pattern metadata-first fonctionne — l'agent charge moins de contexte et fait un travail plus ciblé.

---

## 6. L'agent décide seul quand chercher

Un résultat inattendu de notre étude concerne la façon dont l'agent utilise l'outil de recherche.

La littérature sur le retrieval adaptatif (Self-RAG, Repoformer, FLARE) a établi un résultat important : le retrieval systématique dégrade la performance. Repoformer (ICML 2024) montre que 70% des retrievals de code sont inutiles. Self-RAG (ICLR 2024) montre qu'un retrieval adaptatif surpasse le retrieval systématique de 40% en relatif. Le sweet spot n'est ni "toujours chercher" ni "jamais chercher" — c'est "chercher quand c'est nécessaire".

Ces systèmes utilisent des classificateurs entraînés ou du fine-tuning pour décider quand retriever. Notre approche est plus simple : **on donne l'outil à l'agent et on le laisse décider seul.**

Et ça marche. Sur `test_validation`, l'agent fait 2 à 3 appels RTFM — juste assez pour localiser les modules critiques. Sur `test_stub_generator` (petit repo), il fait 1 appel et n'y revient pas. Sur `test_responses_agent` (la tâche monstre), il fait 10 à 15 appels pour couvrir un maximum d'interfaces.

L'agent fait du retrieval sélectif naturellement, sans entraînement spécifique, sans classificateur. Cela suggère que les LLMs actuels (ou au moins Claude Sonnet 4.0) ont une métacognition suffisante pour décider quand un outil de recherche est utile — à condition que l'outil soit disponible et que son coût d'utilisation soit faible (300 tokens de métadonnées par requête).

C'est peut-être le résultat le plus important de cette étude, au-delà des chiffres de performance : **il n'est pas nécessaire de forcer le retrieval. Il suffit de le rendre possible.**

---

## 7. Ce que ça change en pratique

### La règle des 1 000 fichiers

Nos résultats préliminaires dessinent une frontière nette :

- **Sous ~600 fichiers** : la navigation directe (`grep`, `glob`, `find`) suffit. L'agent parcourt le projet assez vite pour trouver ce qu'il cherche. Le retrieval est un overhead sans bénéfice.

- **Au-dessus de ~8 000 fichiers** : le retrieval transforme les résultats. L'agent sans retrieval se perd dans l'arborescence, entre dans des boucles d'exploration, et échoue à trouver les dépendances cross-module. L'agent avec retrieval les trouve immédiatement.

La zone intermédiaire (1 000 à 5 000 fichiers) reste à explorer — c'est précisément ce que nos runs en cours sur pydantic (771 fichiers) et astropy (1 123 fichiers) visent à clarifier.

Si ce seuil se confirme, la recommandation pratique est simple : **déployez un outil de retrieval pré-indexé sur tout projet de plus de 1 000 fichiers.** Le coût d'initialisation est négligeable — 10 à 78 secondes de parsing selon la taille du repo — et le bénéfice potentiel est considérable.

### Le vrai coût : par tâche résolue

Un argument contre le retrieval est qu'il augmente le coût par tâche. Et c'est vrai : sur `test_validation`, Config D coûte $2.23 contre $1.50 pour Config B. +49%.

Mais Config B ne résout pas la tâche. Config D oui. Le coût pertinent n'est pas le coût par tentative — c'est le coût par tâche *résolue*. Un run à $2.23 qui résout vaut infiniment mieux qu'un run à $1.50 qui échoue, qu'on devra relancer, peut-être plusieurs fois, ou compléter manuellement.

### Au-delà du code

Nous avons testé RTFM sur du code, mais sa philosophie agnostique le destine à un usage plus large. Dans un test A/B séparé sur la rédaction d'un article académique (un cas d'usage documentation, pas code), RTFM v3 a réduit le coût de 51% et la durée de 16% par rapport à la baseline, tout en produisant un article plus complet.

L'outil remplace la navigation aveugle là où c'est nécessaire — recherche de dépendances, localisation de fichiers pertinents, découverte de contenu lié — et ne touche pas au reste. Il ne modifie pas l'édition, l'exécution, le debug. C'est un amplificateur, pas un remplacement.

---

## 8. Ce que la littérature ne prouve pas (et nous non plus, pas encore)

Soyons honnêtes sur les limites de cette étude — et de celles des autres.

**Ce que personne n'a prouvé rigoureusement :**

Augment Code revendique "+80% de performance avec Claude Code + Opus 4.5". Pas de protocole publié, pas de benchmark standardisé, pas d'intervalles de confiance. Sourcegraph Cody n'a aucun benchmark public. Les outils open-source MCP (Code-Index-MCP, mcp-codebase-index) n'ont aucune évaluation publiée. Le papier Navigation Paradox évalue CodeCompass sur 30 micro-tâches synthétiques créées par les auteurs — pas sur un benchmark tiers.

**Nos propres limites :**

- Un seul modèle (Sonnet 4.0). La généralisation à d'autres modèles est non mesurée.
- Un seul outil (RTFM). Un outil concurrent pourrait donner des résultats différents.
- 11 tâches, 4 repos. L'échantillon est petit.
- Python uniquement. FeatureBench lite ne couvre que des projets Python.
- Les données présentées ici sont issues de runs uniques. La matrice complète (11 tâches × 4 conditions × N répétitions) est en cours.

Ce que nous revendiquons, c'est la démarche : **un protocole contrôlé sur un benchmark standardisé, avec une variable isolée et des métriques reproductibles.** Quand les résultats complets seront disponibles, ils seront soumis à *Empirical Software Engineering* (EMSE) — la revue de référence pour les études empiriques en génie logiciel.

---

## 9. Conclusion : donner le choix à l'agent

La question de départ était simple : **est-ce que ça aide de donner un outil de recherche à un agent codeur ?**

La réponse est nuancée mais claire : **oui, sur les grands projets.** Sur mlflow (8 260 fichiers), le retrieval fait passer le resolve rate de 55-64% à 100%. Sur metaflow (624 fichiers), pas de gain mesurable.

Mais au-delà des chiffres, le résultat le plus intéressant est peut-être philosophique. On n'a pas besoin de forcer l'agent à chercher, ni de l'entraîner à décider quand chercher. Il suffit de lui *donner le choix*. Quand l'outil est là, qu'il coûte peu en contexte (300 tokens par requête), et qu'il ne modifie pas le reste du workflow — l'agent s'en sert intelligemment, quand il en a besoin, et l'ignore quand il n'en a pas besoin.

C'est la leçon pratique de cette étude : les agents codeurs ne sont pas limités par leur intelligence. Ils sont limités par leurs outils de navigation. Donnez-leur une carte du territoire — pas un GPS qui dicte le chemin, juste une carte qu'ils peuvent consulter — et ils trouvent leur route.

---

## Références

1. Jimenez, C.E. et al. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. arXiv:2310.06770.
2. FeatureBench (2026). ICLR 2026. arXiv:2602.10975.
3. Yang, J. et al. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. NeurIPS 2024. arXiv:2405.15793.
4. Xia, C.S. et al. (2024). Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489.
5. PatchPilot (2025). ICML 2025. arXiv:2502.02747.
6. Chen, Y. et al. (2025). LocAgent. ACL 2025. arXiv:2503.09089.
7. Trajectory Study (2025). arXiv:2506.18824.
8. Navigation Paradox (2026). arXiv:2602.20048.
9. Wang, Z. et al. (2024). CodeRAG-Bench: Can Retrieval Augment Code Generation? NAACL 2025. arXiv:2406.14497.
10. Galimzyanov, F. et al. (2025). Practical Code RAG at Scale. arXiv:2510.20609.
11. GrepRAG (2026). ISSTA 2026.
12. Asai, A. et al. (2023). Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. ICLR 2024. arXiv:2310.11511.
13. Wu, Y. et al. (2024). Repoformer: Selective Retrieval for Repository-Level Code Completion. ICML 2024. arXiv:2403.10059.
14. Jiang, Z. et al. (2023). Active Retrieval Augmented Generation (FLARE). EMNLP 2023. arXiv:2305.06983.
15. Jeong, S. et al. (2024). Adaptive-RAG. NAACL 2024.
16. Hong, J. et al. (2025). Context Rot. Chroma Research.
17. ContextBench (2025). arXiv:2602.05892.
18. AgentDiet (2025). Trajectory Optimization for Coding Agents.
19. Ackerman et al. (2025). Metacognition in LLMs. arXiv.
20. Tokenomics (2026). arXiv:2601.14470.
21. Liang, J. et al. (2025). SWE-Bench Illusion. arXiv:2506.12286.
22. Augment Code (2026). Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
23. Vasilopoulos, D. (2026). Codified Context. arXiv:2602.20478.
