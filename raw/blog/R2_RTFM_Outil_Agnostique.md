---
type: article
title: "R2) RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit"
subtitle: "Un outil de retrieval agnostique — pas un outil de code. Cinq principes de design, et pourquoi l'architecture metadata-first change tout."
excerpt: "RTFM n'est pas un outil de code. C'est un outil de connaissance. Il indexe tout — code, docs, legal, research — et sert un contexte minimal à la demande. Voici ses principes de design et pourquoi ils importent."
slug: rtfm-outil-agnostique-retrieval
focus_keyword: RTFM retrieval agnostique
tags:
  - rtfm
  - retrieval
  - mcp
  - architecture
  - progressive-disclosure
  - metadata-first
  - parsers
  - agnostique
---

> [!abstract]- SPEC
> ## Brief — R2 : RTFM, l'outil agnostique
> ### Position dans la série
> - **Série** : R (Retrieval) — Does Retrieval Help? | **Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]]
> - Présente l'outil utilisé comme intervention expérimentale dans l'étude
> - Non pour revendiquer sa novelty architecturale, mais parce que ses choix de design influencent les résultats
> ### Sujets couverts
> - Les 5 principes de design (domain/format/protocol/model-agnostic + non-invasif)
> - Le pattern metadata-first → expand on demand
> - Stack technique (SQLite + FTS5 + FastEmbed)
> - Positionnement vs outils existants (Augment CE, Sourcegraph, Code-Index-MCP, CodeCompass)
> - Pourquoi l'évaluation rigoureuse est le vrai différenciateur
> ### SOTAs sources
> - `paper/sota/08_competitive_landscape.md`

# R2) RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit

## Cinq principes de design, et pourquoi l'architecture metadata-first change tout

> Il existe déjà des outils de retrieval pour agents codeurs. Ce qui manque, c'est une preuve que ça marche.

## Où se situe cet article ?

Dans [[R1_Le_Goulot_de_Localisation|R1]], nous avons posé le diagnostic : les agents codeurs passent 38% de leur temps à explorer, le gap oracle est de 9 à 50 points de pourcentage, et le context rot montre que trop de contexte est pire que pas assez. La conclusion : il faut un outil de recherche qui serve du contexte *minimal* et *pertinent*, pas un dump de tout le projet.

Cet article présente l'outil que nous avons construit pour tester cette thèse : RTFM. Non pas pour en faire la promotion — c'est open source, chacun jugera — mais parce que les choix de design ont des conséquences directes sur les résultats expérimentaux. Quand on mesure l'impact du retrieval ([[R4_Resultats|R4]]), il faut comprendre *quel* retrieval on mesure.

---

## Le problème des outils existants

Avant de construire quoi que ce soit, faisons le tour de ce qui existe.

### Les solutions commerciales

**Augment Context Engine** (février 2026) est le plus sérieux des concurrents commerciaux. C'est un moteur de contexte sémantique propriétaire exposé via MCP. Il indexe le code, la documentation, les tickets, les wikis internes, l'historique de commits. Il fonctionne avec Claude Code. Il coûte entre 20 et 200 dollars par mois.

Augment revendique "+80% de performance avec Claude Code + Opus 4.5". Le chiffre est impressionnant. Le problème : aucun protocole publié. Pas de benchmark standardisé. Pas d'intervalles de confiance. Pas de description de la méthodologie. "+80%" par rapport à quoi, sur quelles tâches, avec quel baseline ? On ne sait pas.

**Sourcegraph Cody** expose ses capacités de recherche de code via MCP en version enterprise. C'est un outil puissant — recherche cross-organisation, multi-repo, sémantique et lexicale. Mais c'est enterprise-only (à partir de 49$/utilisateur/mois), code-only, et là encore : aucun benchmark public mesurant l'impact sur la performance d'un agent.

**Greptile** offre une API d'analyse de codebase avec MCP. Valorisé à 180 millions de dollars. Code review focus. Cloud-only. Payant. Pas de benchmark non plus.

### Les solutions open source

**Code-Index-MCP** (johnhuang316, 793 stars) indexe du code dans 7 langages avec tree-sitter AST. C'est l'outil open source le plus populaire dans cette catégorie. Mais il est purement code — pas de documentation, pas de fichiers de configuration, pas de données structurées. Et surtout : zéro évaluation publiée.

**Code-Index-MCP** (ViperJuice, 38 stars) est architecturalement le plus proche de ce que nous avons construit — même stack SQLite + FTS5, même principe de recherche hybride. Mais là encore : code-first (Markdown/YAML en secondaire), pas de parsers extensibles, pas de multi-corpus. Et aucune évaluation.

**mcp-codebase-index** utilise Python AST pour l'indexation, avec un mécanisme incrémental via `git diff`. Élégant, zéro dépendances. Mais code-only.

**CodeCompass** (du papier Navigation Paradox) est un cas intéressant : c'est un graphe AST Neo4j exposé via MCP. Il fait de la navigation *structurelle*, pas de la recherche *textuelle*. C'est un outil complémentaire, pas concurrent.

### Le pattern commun

Tous ces outils partagent deux caractéristiques :

1. **Ils sont centrés sur le code.** Code, code, code. Le code est important, mais un projet réel contient aussi de la documentation, des fichiers de configuration, des spécifications, des données structurées, peut-être des documents légaux ou des notes de recherche.

2. **Aucun n'a publié d'évaluation rigoureuse.** Revendications marketing, micro-benchmarks internes, ou rien du tout. Personne n'a pris un benchmark standardisé, défini un protocole contrôlé avec une variable isolée, et mesuré l'impact du retrieval sur les performances d'un agent.

---

## Cinq principes pour un outil différent

RTFM est né d'un constat : si le facteur limitant est la capacité à trouver le bon contexte ([[R1_Le_Goulot_de_Localisation|R1]]), alors l'outil de recherche ne devrait pas présumer de la *nature* du contexte. Cinq principes guident sa conception.

### 1. Domain-agnostic — pas un outil de code, un outil de connaissance

RTFM indexe tout. Code Python (via l'AST), scripts shell (fonctions et commentaires), documentation Markdown (sections par en-têtes), articles LaTeX (structure `\section`/`\subsection`), configurations YAML et JSON (clés de premier niveau), documents PDF (texte extrait), textes juridiques XML (articles de loi Legifrance), pages HTML (BOFiP), et du texte brut en fallback.

Le même outil sert un développeur qui cherche une fonction, un juriste qui cherche un article de loi, un chercheur qui cherche une référence dans ses notes, un musicologue qui cherche un passage dans son corpus.

Ce n'est pas un caprice d'ingénierie. C'est une conséquence directe de la thèse. Un agent qui travaille sur un projet réel a besoin de trouver à la fois le code existant, la documentation des contraintes métier, les tests correspondants, et peut-être les spécifications — tout ça dans le même projet, avec le même outil, dans la même requête.

### 2. Format-agnostic — des parsers extensibles en 50 lignes

Ajouter un nouveau format à RTFM demande environ 50 lignes de Python. On hérite de `BaseParser`, on implémente `parse()`, on déclare les extensions supportées. C'est tout.

```python
class MonParser(BaseParser):
    extensions = {".monformat"}

    def parse(self, content: str, metadata: dict) -> list[Chunk]:
        # découper le contenu en chunks pertinents
        # retourner une liste de Chunk(title=..., content=..., metadata=...)
        ...
```

10 parsers sont embarqués. Mais la vraie valeur est dans l'extensibilité : n'importe qui peut ajouter le support de son format métier, de son format de données scientifiques, de son format de documentation interne — sans toucher au coeur du système.

Le système ne présume pas du format. Il s'adapte. C'est la différence entre un outil de *code* indexing et un outil de *knowledge* indexing.

### 3. Protocol-agnostic — MCP comme lingua franca

RTFM est exposé via MCP (Model Context Protocol), le standard ouvert d'Anthropic pour la communication entre agents IA et outils. MCP est au monde des agents ce que HTTP est au web : un protocole standard qui permet l'interopérabilité.

Concrètement : RTFM fonctionne avec tout agent MCP-compatible. Claude Code, Continue.dev, Cursor (via MCP), ou n'importe quel client MCP qu'on voudra écrire demain. Pas de lock-in à un IDE, pas de dépendance à un fournisseur de modèle.

L'outil expose 11 endpoints MCP, dont les principaux :
- `rtfm_search(query)` — recherche full-text et/ou sémantique
- `rtfm_context(subject)` — recherche ciblée sur un sujet
- `rtfm_expand(slug)` — récupération du contenu complet d'un chunk
- `rtfm_discover()` — scan rapide de la structure du projet

### 4. Model-agnostic — pur retrieval, zéro génération

RTFM ne contient aucun modèle de langage. Zéro. Il ne génère rien, n'interprète rien, ne résume rien. Il indexe des documents et retourne des résultats de recherche. Point.

Les embeddings (optionnels) utilisent FastEmbed (ONNX), un modèle d'encodage léger qui tourne sur CPU. Mais même les embeddings ne sont là que pour le *ranking* des résultats — pas pour la génération.

La conséquence : RTFM est compatible avec tout LLM. Que l'agent tourne sur Claude, GPT, Gemini, Llama, Mistral, ou un modèle open-source fine-tuné ne change rien au fonctionnement de RTFM. L'outil produit des données ; le modèle de l'agent décide quoi en faire.

### 5. Non-invasif — remplacer ce qui doit l'être, ne rien toucher au reste

C'est peut-être le principe le plus important, et celui qui demande le plus de discipline.

RTFM ne modifie pas le workflow de l'agent. Il *ajoute* des outils de recherche. L'agent peut les utiliser — ou les ignorer complètement. Il n'y a pas de retrieval forcé, pas de contexte injecté silencieusement dans le prompt, pas de modification du comportement de l'agent en arrière-plan.

Quand l'agent a besoin de chercher une dépendance dans un projet de 8 000 fichiers, il utilise `rtfm_search`. Quand il sait déjà où coder, il utilise `Read` et `Edit` directement — exactement comme avant. L'outil remplace la navigation aveugle (`grep`, `glob`, `find`) là où c'est pertinent, et ne touche pas au reste : édition, exécution, debug, tests — tout ça reste inchangé.

C'est un amplificateur, pas un remplacement. Et cette distinction va s'avérer cruciale dans les résultats ([[R4_Resultats|R4]]).

---

## Le pattern metadata-first

L'architecture centrale de RTFM est ce que nous appelons le **progressive disclosure** — ou plus précisément, **metadata-first → expand on demand**.

### Le problème du contexte

[[R1_Le_Goulot_de_Localisation|R1]] a montré que le context rot est réel : au-delà d'un seuil, ajouter du contexte *dégrade* la performance. ContextBench montre que les agents voient le contexte pertinent mais n'en retiennent que 50-70%. AgentDiet montre que 40-60% des tokens d'exploration sont du gaspillage.

La conclusion architecturale est claire : il faut servir le *minimum* de contexte pertinent, pas le maximum.

### La solution en deux étapes

**Étape 1 : la recherche renvoie des métadonnées.**

```
> rtfm_search("validation scorers mlflow")

1. mlflow/models/evaluation/validation.py
   Score: 0.89 | Chunks: 12 | 342 lines
2. mlflow/models/evaluation/scorers.py
   Score: 0.76 | Chunks: 8 | 218 lines
3. mlflow/models/evaluation/data.py
   Score: 0.71 | Chunks: 6 | 156 lines
```

~300 tokens. Pas de contenu. Juste les coordonnées : quel fichier, quelle pertinence, quelle taille. Assez pour que l'agent décide *si* le résultat vaut la peine d'être lu.

**Étape 2 : l'agent lit ce dont il a besoin.**

L'agent voit le chemin absolu dans les résultats. S'il décide que `validation.py` est pertinent, il fait un `Read("/testbed/mlflow/models/evaluation/validation.py")` — son outil standard, celui qu'il utilise de toute façon. Il charge le fichier *entier* dans son contexte, au moment précis où il en a besoin.

S'il décide que `data.py` n'est pas pertinent pour sa tâche, il ne le charge pas. Les 300 tokens de métadonnées n'ont pas pollué sa fenêtre de contexte avec du contenu inutile.

### Pourquoi c'est important

Sur 5 résultats de recherche, l'agent lit peut-être 2 fichiers. Avec une approche "dump tout le contenu dans les résultats", les 5 fichiers auraient été chargés — disons 3000 tokens de code × 5 = 15 000 tokens. Avec le pattern metadata-first, l'agent ne charge que ce qu'il utilise : 300 tokens de métadonnées + 2 fichiers lus à la demande. Le contexte effectif est 2 à 5 fois plus petit.

C'est l'exact opposé des systèmes qui envoient des pages entières de code dans les résultats de recherche. Et c'est cohérent avec ce que la littérature nous dit : du contexte minimal ciblé est plus efficace qu'un dump massif.

---

## Stack technique

Sous le capot, RTFM est simple :

**Stockage :** SQLite. Un seul fichier `.db`, portable, copié d'une machine à l'autre sans configuration.

**Recherche full-text :** FTS5, le moteur de recherche intégré de SQLite. Utilise BM25 pour le ranking. Zéro dépendance externe, zéro cold start, performances suffisantes pour des index de 180 000 chunks.

**Recherche sémantique (optionnelle) :** FastEmbed, un runtime ONNX léger. Le modèle `paraphrase-multilingual-MiniLM-L12-v2` encode les chunks et les requêtes en vecteurs de 384 dimensions. ~17 secondes de warm-up, puis recherche instantanée. L'hybride FTS + embeddings pondère les deux scores.

**Synchronisation :** incrémentale via hash SHA-256. À chaque sync, seuls les fichiers modifiés sont ré-indexés. Sur un projet stable, la sync est quasi-instantanée.

**Parsing :** chaque format a son parser dédié. Le parser Python utilise l'AST stdlib pour découper en classes et fonctions. Le parser Markdown découpe par en-têtes. Le parser LaTeX découpe par `\section`. Chaque parser produit des chunks — des unités de contenu indexables avec titre, contenu et métadonnées.

| Composant            | Technologie      | Dépendance    |
| -------------------- | ---------------- | ------------- |
| Base de données      | SQLite           | stdlib Python |
| Recherche lexicale   | FTS5 (BM25)      | stdlib Python |
| Recherche sémantique | FastEmbed (ONNX) | optionnel     |
| Parsing              | AST, regex, DOM  | stdlib Python |
| Protocole            | MCP (FastMCP)    | `mcp` package |
| Sync                 | SHA-256 hash     | stdlib Python |

Le core n'a qu'une seule dépendance requise : `pyyaml`. Le reste est optionnel. C'est un choix délibéré : un outil qui s'installe en 2 secondes est un outil qui sera effectivement utilisé.

---

## Positionnement : ce qui est novel et ce qui ne l'est pas

Soyons honnêtes sur ce que RTFM apporte et ce qu'il n'apporte pas.

### Ce qui N'EST PAS novel (ne le revendiquons pas)

- Pré-indexer un codebase et exposer l'index via MCP. Augment le fait. Code-Index-MCP le fait. D'autres aussi.
- FTS5 + SQLite pour l'indexation. ViperJuice utilise la même stack.
- Recherche sémantique via embeddings. Tout le monde en fait.
- Sync incrémental. mcp-codebase-index utilise `git diff`, c'est encore plus malin.

### Ce qui est différent (mais pas le sujet du papier)

- **Multi-domaine** : le seul outil open source qui indexe code + docs + legal + research + données structurées.
- **Parsers extensibles** : ~50 lignes pour un nouveau format. Aucun autre outil ne propose ça.
- **Metadata-first** : les résultats de recherche ne contiennent pas de contenu, juste des coordonnées.
- **Multi-corpus** : plusieurs sources dans la même base, avec recherche cross-source.

### Le vrai différenciateur

**L'évaluation.** Nous avons pris un benchmark standardisé (FeatureBench, ICLR 2026), défini un protocole à 4 conditions avec une variable isolée, et mesuré l'impact. C'est décrit en [[R3_Protocole_Experimental|R3]], les résultats sont en [[R4_Resultats|R4]].

Aucun des outils listés ci-dessus n'a fait ça. Le "+80%" d'Augment est une affirmation marketing. Le "+23.2 pp" de Navigation Paradox utilise 30 micro-tâches créées par les auteurs, pas un benchmark tiers. Les outils open source n'ont aucune évaluation.

| Propriété              | RTFM                      | Augment CE            | Code-Index-MCP  | CodeCompass     |
| ---------------------- | ------------------------- | --------------------- | --------------- | --------------- |
| Multi-domaine          | Code+docs+legal+research  | Code+docs+tickets     | Code uniquement | Code Python     |
| Parsers extensibles    | ~50 LOC                   | Non                   | Non             | Non             |
| Open source            | Oui                       | Non                   | Oui             | Oui             |
| Progressive disclosure | metadata-first            | N/A (propriétaire)    | contenu direct  | graphe AST      |
| **Évaluation publiée** | **Benchmark standardisé** | "+80%" sans protocole | Aucune          | 30 micro-tâches |
| Pricing                | Gratuit                   | $20-200/mo            | Gratuit         | Gratuit         |

La contribution de ce travail n'est pas l'outil. C'est la preuve empirique que ce *type* d'outil fonctionne — et dans quelles conditions.

---

## Références

- **Augment Code (2026)** — Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
- **Sourcegraph (2025)** — Cody MCP Integration. https://sourcegraph.com/docs/api/mcp
- **Greptile (2026)** — MCP Overview. https://www.greptile.com/docs/mcp/overview
- **johnhuang316** — Code-Index-MCP. https://github.com/johnhuang316/code-index-mcp
- **ViperJuice** — Code-Index-MCP. https://github.com/ViperJuice/Code-Index-MCP
- **mcp-codebase-index** — https://pypi.org/project/mcp-codebase-index/
- **Navigation Paradox (2026)** — CodeCompass MCP. arXiv:2602.20048.
- **Vasilopoulos, D. (2026)** — Codified Context. arXiv:2602.20478.
- **Hong, J. et al. (2025)** — Context Rot. Chroma Research.

---

## Glossaire

- **BM25** : *Best Match 25* — algorithme de ranking pour la recherche full-text, standard de l'industrie depuis les années 1990.
- **Chunk** : unité de contenu indexée par RTFM — une fonction Python, une section Markdown, un article de loi.
- **FastEmbed** : bibliothèque Python pour les embeddings via ONNX, sans dépendance à PyTorch/TensorFlow.
- **FTS5** : *Full-Text Search 5* — moteur de recherche intégré à SQLite, utilise BM25 pour le ranking.
- **Metadata-first** : pattern architectural où les résultats de recherche ne contiennent que des métadonnées (titre, chemin, score), pas le contenu des documents.
- **MCP** : *Model Context Protocol* — standard ouvert pour la communication entre agents IA et outils.
- **ONNX** : *Open Neural Network Exchange* — format portable pour les modèles de machine learning.
- **Parser** : composant qui découpe un document en chunks indexables selon les conventions du format.
- **Progressive disclosure** : fournir l'information par niveaux de détail croissants, à la demande.
- **SQLite** : base de données relationnelle embarquée, stockée dans un seul fichier.

---

## Liens dans la série

- [[R1_Le_Goulot_de_Localisation|R1]] — Le goulot de localisation — le problème fondamental
- **R2** (cet article) — RTFM : un outil de connaissance qui ne touche qu'à ce qu'il doit
- [[R3_Protocole_Experimental|R3]] — Le protocole : 4 conditions, 11 tâches, même modèle
- [[R4_Resultats|R4]] — Les résultats : quand la taille du repo change tout
- [[R5_Agent_Decide_Seul|R5]] — L'agent décide seul : retrieval sélectif sans entraînement
- [[R6_Perspectives|R6]] — Ce que ça change — et ce qu'il reste à prouver

---

**Prérequis** : [[R1_Le_Goulot_de_Localisation|R1]]
**Temps de lecture** : 14 min
**Tags** : #rtfm #retrieval #mcp #architecture #progressive-disclosure #metadata-first #agnostique

---

*Prochain article : [[R3_Protocole_Experimental|R3]] — Le protocole : 4 conditions, 11 tâches, même modèle*

---
