# SOTA 8 — Paysage Concurrentiel : Qui Fait Déjà Quoi ?

## Synthèse exécutive

**Pré-indexer un codebase et exposer la recherche via MCP n'est plus novel en 2026.** Augment le fait (payant), et plusieurs outils open-source aussi (Code-Index-MCP, mcp-codebase-index). La contribution ne peut donc PAS être "on propose un outil MCP de retrieval".

Ce qui reste différenciant : le **multi-domaine**, les **parsers extensibles**, et le **pattern metadata-first**. Mais surtout, l'angle du papier ne doit pas être l'outil — il doit être la **thèse empirique** : donner à un agent la capacité de chercher améliore ses performances sur les grands repos.

---

## 1. Concurrents Directs (MCP + indexation)

### 1.1 Augment Context Engine MCP — Le plus sérieux
- **Quoi :** Moteur de contexte sémantique propriétaire exposé via MCP (fév 2026)
- **Indexe :** Code + documentation + tickets + wikis internes + historique de commits
- **MCP :** Oui, outil `codebase-retrieval`. Modes local (CLI Auggie) et remote
- **Open source :** Non. Wrapper MCP open source seulement
- **Claude Code :** Oui
- **Pricing :** $20-200/mo. 40-70 crédits/requête. 1000 requêtes gratuites en fév 2026
- **Benchmark revendiqué :** +80% perf avec Claude Code + Opus 4.5, +71% avec Cursor
- **vs RTFM :** Multi-domaine mais propriétaire, cloud-first, payant, pas extensible par la communauté
- **URLs:**
  - https://www.augmentcode.com/blog/context-engine-mcp-now-live
  - https://docs.augmentcode.com/context-services/mcp/overview
  - https://www.augmentcode.com/pricing

### 1.2 Sourcegraph Cody MCP
- **Quoi :** Moteur de recherche de code Sourcegraph exposé via MCP (GA avec OAuth)
- **Indexe :** Code uniquement (multi-repos, cross-organisation)
- **MCP outils :** `keyword_search`, `nls_search` (sémantique), `go_to_definition`, `find_references`, `commit_search`, `diff_search`, `deepsearch`, `read_file`, `list_repos`
- **Open source :** Open-core. MCP = Enterprise-only
- **Claude Code :** Oui
- **Pricing :** Enterprise ($49+/user/month)
- **vs RTFM :** Infiniment plus puissant sur le code à grande échelle. Mais code-only, enterprise-only.
- **URLs:**
  - https://sourcegraph.com/docs/api/mcp
  - https://sourcegraph.com/blog/cody-supports-anthropic-model-context-protocol

### 1.3 Greptile
- **Quoi :** API d'analyse de codebase cloud + MCP server
- **Indexe :** Code (graphe de dépendances, historique git, PRs, code reviews). Aussi Jira/Docs/Notion via MCP
- **Open source :** Non. SaaS (YC, $180M valuation)
- **Claude Code :** Oui via MCP
- **Pricing :** $30/dev/month. API: $0.15/unité
- **vs RTFM :** Code review focus, cloud-only, payant
- **URLs:**
  - https://www.greptile.com/docs/mcp/overview
  - https://www.greptile.com/pricing

---

## 2. IDEs avec Indexation Intégrée (pas MCP)

### 2.1 Cursor
- **Indexe :** Code (chunking syntaxique, embeddings Turbopuffer, Merkle tree pour cache)
- **MCP :** Non — intégré à l'IDE uniquement
- **Open source :** Non
- **Claude Code :** Non compatible (IDE concurrent)
- **Pricing :** $20/mo
- **vs RTFM :** Approche similaire mais fermée dans l'IDE. Non accessible par agents externes.
- **URLs:**
  - https://cursor.com/docs/context/codebase-indexing

### 2.2 Windsurf (Codeium)
- **Indexe :** Code (background indexing)
- **MCP :** Non — intégré à Cascade uniquement
- **Open source :** Non
- **vs RTFM :** Fermé dans l'IDE. Code only.

---

## 3. Outils Open Source MCP pour l'Indexation de Code

### 3.1 Code-Index-MCP (johnhuang316) — 793 stars
- **Indexe :** Code (50+ types, 7 langages avec tree-sitter AST, fallback regex)
- **MCP :** Oui (`search_code_advanced`, `get_file_summary`)
- **Open source :** Oui
- **Claude Code :** Oui
- **vs RTFM :** Plus populaire mais purement code. Pas de docs, legal, research. Pas de sync incrémental hash-based.
- **URL:** https://github.com/johnhuang316/code-index-mcp

### 3.2 Code-Index-MCP (ViperJuice) — 38 stars
- **Indexe :** Code (48 langages tree-sitter) + Markdown/JSON/YAML/XML
- **Search :** FTS5 (SQLite) + sémantique optionnel (Voyage AI) + hybride
- **Open source :** Oui
- **Claude Code :** Oui
- **vs RTFM :** **Le plus proche architecturalement** — même stack SQLite+FTS5. Mais code-first, docs secondaires. Pas de parsers extensibles. Pas de multi-corpus. Pas de metadata-then-expand.
- **URL:** https://github.com/ViperJuice/Code-Index-MCP

### 3.3 mcp-codebase-index (PyPI) — v0.5.0
- **Indexe :** Code (Python AST, regex pour TS/JS/Go/Rust). Zero dependencies
- **MCP :** Oui (18 outils : fonctions, classes, imports, graphe de dépendances)
- **Technique :** Incrémental via `git diff`, cache pickle, startup instantané si HEAD inchangé
- **vs RTFM :** Très efficace pour le code. Zero deps. Mais code only, pas extensible.
- **URL:** https://pypi.org/project/mcp-codebase-index/

### 3.4 CodeCompass (Navigation Paradox paper)
- **Indexe :** Code Python uniquement (graphe AST → Neo4j)
- **MCP :** Oui (`get_architectural_context`, `semantic_search`)
- **Open source :** Oui
- **vs RTFM :** Navigation structurelle (graphe de dépendances), pas recherche textuelle. Complémentaire, pas concurrent.
- **URL:** https://github.com/TheAlchemist6/codecompass-mcp

---

## 4. Outils Complémentaires (pas concurrents)

### 4.1 Aider Repo Map
- **Quoi :** Carte de repo via tree-sitter + PageRank, injectée passivement dans le prompt
- **MCP :** Non natif (MCP wrapper tiers existe)
- **vs RTFM :** Injection statique, pas de recherche interactive. L'agent ne peut pas interroger.
- **URL:** https://aider.chat/docs/repomap.html

### 4.2 Continue.dev
- **Quoi :** Extension IDE open-source, **client** MCP (consomme des serveurs MCP)
- **vs RTFM :** Complémentaire — Continue pourrait utiliser RTFM comme context provider.
- **URL:** https://docs.continue.dev/customize/deep-dives/mcp

### 4.3 Context7
- **Quoi :** MCP server servant la doc de 500+ librairies externes (React, Next.js, etc.)
- **vs RTFM :** Complémentaire — Context7 sert la doc de libs tierces, RTFM sert le contenu du projet.
- **URL:** https://github.com/upstash/context7

### 4.4 Bloop
- **Quoi :** Moteur de recherche de code en Rust, app desktop
- **MCP :** Non
- **vs RTFM :** Pas d'exposition aux agents. Semble avoir pivoté.
- **URL:** https://github.com/BloopAI/bloop

---

## 5. Matrice de Comparaison

| Outil | Indexe | MCP | OSS | Claude Code | Multi-domaine | Parsers extensibles | Pricing |
|---|---|---|---|---|---|---|---|
| **RTFM** | Code+docs+legal+research | Oui | Oui | Oui | **Oui** | **Oui** | Gratuit |
| Augment CE | Code+docs+tickets+wikis | Oui | Non | Oui | Partiellement | Non | $20-200/mo |
| Sourcegraph | Code (multi-repo) | Oui | Enterprise | Oui | Non | Non | $$$/mo |
| Greptile | Code+PRs+reviews | Oui | Non | Oui | Non | Non | $30/dev/mo |
| Cursor | Code | Non (IDE) | Non | Non | Non | Non | $20/mo |
| Windsurf | Code | Non (IDE) | Non | Non | Non | Non | $15-60/mo |
| Code-Index (JH) | Code (50+ types) | Oui | Oui | Oui | Non | Non | Gratuit |
| Code-Index (VJ) | Code+MD/YAML | Oui | Oui | Oui | Limité | Non | Gratuit |
| mcp-codebase-index | Code (Py/TS/Go) | Oui | Oui | Oui | Non | Non | Gratuit |
| CodeCompass | Code Python (graphe) | Oui | Oui | Oui | Non | Non | Gratuit |
| Aider Map | Code (symboles) | Non natif | Oui | Non natif | Non | Non | Gratuit |
| Context7 | Docs libs tierces | Oui | Oui | Oui | Non | Non | Gratuit |

---

## 6. Conclusion : Implications pour le Paper

### Ce qui n'est PAS novel (ne pas revendiquer) :
- Pré-indexer un codebase et exposer via MCP
- FTS5 + SQLite pour l'indexation
- Recherche sémantique via embeddings
- Sync incrémental

### Ce qui reste différenciant pour RTFM (mais pas le sujet du paper) :
- Multi-domaine (seul OSS à indexer code + docs + legal + research)
- Architecture de parsers extensible (~50 lignes)
- Pattern metadata-search-then-expand
- Multi-corpus / multi-source
- Zero dependency core

### Le vrai angle du paper :
**Pas l'outil. La thèse empirique.** Aucun de ces outils n'a publié d'étude contrôlée montrant l'impact mesurable du retrieval pré-indexé sur les performances d'un agent codeur (resolve rate, coût, durée) sur un benchmark standardisé (FeatureBench).

Augment revendique "+80%" mais sans protocole publié. Sourcegraph n'a aucun benchmark public. Les MCP open-source n'ont pas d'évaluation. Le paper de RTFM serait le **premier à mesurer empiriquement, sur FeatureBench, l'impact de donner un outil de retrieval à un agent codeur** — en conditions contrôlées (4 configs, même tâches, même modèle).

---

## Références

1. Augment Code (2026). Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
2. Sourcegraph (2025). Cody MCP Integration. https://sourcegraph.com/docs/api/mcp
3. Greptile (2026). MCP Overview. https://www.greptile.com/docs/mcp/overview
4. Cursor (2025). Codebase Indexing. https://cursor.com/docs/context/codebase-indexing
5. johnhuang316. Code-Index-MCP. https://github.com/johnhuang316/code-index-mcp
6. ViperJuice. Code-Index-MCP. https://github.com/ViperJuice/Code-Index-MCP
7. mcp-codebase-index. https://pypi.org/project/mcp-codebase-index/
8. Navigation Paradox (2026). CodeCompass. arXiv:2602.20048.
9. Aider (2023). Repo Map. https://aider.chat/docs/repomap.html
10. Continue.dev. MCP Integration. https://docs.continue.dev/customize/deep-dives/mcp
11. Context7. https://github.com/upstash/context7
