# RTFM — Backlog

Tout ce qui a été identifié comme piste future, classé par priorité.

---

## P0 — Benchmark en cours (papier EMSE)

### Runs manquants
- [ ] Matrice complète 11 tâches × 4 conditions (A/B/C/D)
- [ ] N ≥ 3 répétitions par condition (significativité statistique)
- [ ] Tâches pydantic (771 fichiers) et astropy (1 123 fichiers) — repos intermédiaires pour localiser le seuil
- [ ] `fb eval` systématique sur chaque run
- [ ] Relancer Config B pour serialization et responses_agent (failed précédemment)

### Analyses à produire
- [ ] Tests statistiques (Wilcoxon signed-rank ou permutation test)
- [ ] Intervalles de confiance sur resolve rate, coût, durée
- [ ] Corrélation taille repo × gain retrieval (scatter plot)
- [ ] Analyse qualitative : sur chaque tâche où C/D > B, quels fichiers le retrieval a trouvé que B n'a pas trouvé ?
- [ ] Coût par tâche RÉSOLUE (pas par tentative)

### Rédaction papier
- [ ] Vérifier format/longueur EMSE (typiquement 25-40 pages)
- [ ] Rédaction complète (plan v3 dans `paper/paper_plan.md`)
- [ ] Figures et tables (10 prévues, voir paper_plan.md §Figures)
- [ ] Artifact badge (RTFM déjà public sur PyPI/GitHub)

---

## P1 — Fonctionnalités produit (prochaine version)

### Navigation par graphe de dépendances
- Table `edges(source_slug, target_slug, relation_type)` dans SQLite
- Chaque parser extrait les relations au moment du `sync` :
  - Python : `import`, `from ... import`
  - LaTeX : `\cite{}`, `\ref{}`, `\input{}`
  - XML Légifrance : `<LIEN>`
  - Markdown : `[[wikilinks]]`, `[liens](relatifs.md)`
  - YAML/JSON : `$ref`
- Mode `rtfm_search` enrichi : "donne-moi aussi les fichiers liés à ce résultat"
- Zéro Neo4j — tout dans le même SQLite
- Inspiré par Navigation Paradox (arXiv:2602.20048) : graphe = +23.2pp sur dépendances cachées, FTS = zéro bénéfice sur ce type
- Graphe et embeddings sont complémentaires : embeddings = similarité sémantique entre chunks, graphe = liens structurels entre fichiers

### Filtrage intelligent à l'indexation
- Exclure vendored, tests, generated code, node_modules, .git
- Indexer sélectivement les grands repos (> 2000 fichiers) — seulement les répertoires clés
- Réduirait le bruit sur les grands repos (problème identifié dans le benchmark 10 tâches)

### Performance : `rtfm_expand` avec `count=0`
- Quand `count=0` (tous les chunks), `_render_chunk` est appelé N fois, chacun relisant le fichier entier via `_read_raw_lines` puis le slicant
- Optimisation : lire le fichier une seule fois et slicer pour chaque chunk
- Pas critique pour les fichiers < 1 Mo, mais problème de perf sur les gros fichiers (> 1 Mo, > 50 chunks)
- Identifié dans l'analyse de dette technique de `mcp.py`

### Amélioration des résultats de recherche
- Limiter les résultats par défaut (top 3 au lieu de top 5+)
- Dedup par filename (déployé mais pas stress-testé)
- Meilleur ranking : pondérer par fraîcheur, centralité dans le graphe

---

## P2 — Indexation cross-projet des mémoires Claude

### Indexer le répertoire mémoire complet de chaque projet
- `~/.claude/projects/*/memory/` (tout le répertoire, pas juste MEMORY.md)
- Contient : MEMORY.md + fichiers thématiques (benchmark_paper.md, featurebench.md, worknotes, analyses...)
- Aussi : les `CLAUDE.md` de chaque projet (conventions, architecture, décisions)
- Recherche cross-projet : "comment j'ai géré l'OAuth ?" → cherche dans tous les projets
- Auto-découverte des projets Claude via `~/.claude/projects/`

### Versioning de tous les fichiers mémoire
- À chaque sync, si le contenu a changé, conserver la version précédente
- Table `file_versions(slug, version_num, content_hash, timestamp, content)`
- Permet : "qu'est-ce qu'on savait sur X il y a 3 semaines ?"
- Permet aussi : "qu'est-ce qui a changé dans le benchmark_paper.md entre hier et aujourd'hui ?"
- Aucun outil concurrent ne fait ça — feature différenciante
- Le diff entre versions pourrait être exposé via MCP : `rtfm_history(slug)`

### Commande dédiée
- `rtfm memory` : indexe + versionne tout `~/.claude/projects/*/memory/` cross-projet
- `rtfm memory --history <slug>` : voir l'historique d'un fichier mémoire

---

## P3 — Benchmark étendu (moyen terme)

### Multi-modèle
- [ ] Tester avec GPT-4, Gemini 2.5 Pro, Claude Opus, modèles open-source
- [ ] Mesurer si la capacité de retrieval sélectif varie par modèle
- [ ] Est-ce que les modèles plus puissants bénéficient plus ou moins du retrieval ?

### Multi-outil
- [ ] Tester avec Augment Context Engine, Sourcegraph Cody (si API disponible)
- [ ] Le pattern metadata-first est-il crucial, ou n'importe quel outil ferait l'affaire ?

### Multi-langage
- [ ] FeatureBench full (tasks GPU) — pas seulement Python
- [ ] Le goulot de localisation existe-t-il de la même manière en Java, TypeScript, Rust ?

### Benchmark standardisé
- [ ] Étendre à SWE-bench pour comparabilité avec la littérature
- [ ] SWE-bench Verified (500 instances, ground truth validé par humains)

### Conditions réelles
- [ ] Mesurer l'impact en dehors d'un benchmark, sur des tâches de développement quotidiennes
- [ ] Étude longitudinale : est-ce que l'agent s'améliore avec un index qui grossit ?

---

## P4 — Recherche exploratoire (long terme)

### Retrieval proactif
- L'outil pourrait pré-charger du contexte pertinent avant même que l'agent ne cherche
- Injection automatique de contexte au début de session basée sur le prompt
- Risque : context rot si mal calibré (Hong et al. 2025)

### Interaction retrieval × taille de contexte
- Est-ce que les fenêtres de contexte plus larges (1M+ tokens) rendent le retrieval obsolète ?
- Navigation Paradox dit non : le problème est la saillance, pas la capacité
- Mesurer empiriquement avec des modèles 200K vs 1M tokens

### Retrieval multi-source
- Combiner le contenu du projet (code, docs) avec la doc externe (Context7, docs officielles)
- RTFM pour le projet, Context7 pour les libs tierces — orchestration automatique

### Parsers communautaires
- Architecture extensible déjà en place (~50 lignes par parser)
- Parsers manquants identifiés : TypeScript/JSX, Rust, Go, Java, C/C++, SQL, Jupyter notebooks, DOCX, CSV/Excel
- Marketplace ou registry de parsers communautaires

### Agent multi-outil
- Combiner graphe (dépendances structurelles) + FTS (recherche textuelle) + embeddings (similarité sémantique) en un seul `rtfm_search` intelligent
- L'agent n'a pas besoin de choisir le mode — le système route automatiquement
- Cf. Adaptive-RAG (Jeong et al., NAACL 2024) mais sans classificateur entraîné

---

## P5 — Corrections articles blog (série R)

### R5 — Fait (2026-03-01)
- [x] Corrigé la fausse affirmation "rien dans le prompt ne dit d'utiliser RTFM"
- [x] Reframé : guidage léger (3 lignes CLAUDE.md) + calibration émergente de l'intensité

### R6 — À mettre à jour
- [ ] §5 "L'agent fait du retrieval sélectif naturellement" → aligner avec R5 corrigé (guidage léger, pas zéro instruction)
- [ ] "Ne mettez pas d'instruction 'utilise TOUJOURS RTFM'" → nuancer (3 lignes d'orientation ≠ forcer le retrieval systématique)
- [ ] "Ce n'est pas un GPS qui dicte le chemin" → garder la métaphore mais ajouter "on lui montre la carte"

### Intégrer Navigation Paradox dans R2
- [ ] Compléter la comparaison CodeCompass vs RTFM : graphe vs texte, mono-domaine vs multi
- [ ] Mentionner que leur outil n'est pas distribué (0 stars, prototype recherche)
- [ ] Ajouter le finding 58% zero-call → RTFM résout ça avec 3 lignes CLAUDE.md

---

## Idées en vrac

- Template CLAUDE.md : ajouter "cherche une fois, puis code" au lieu de "cherche à chaque doute" (réduirait l'overhead sur grands repos)
- Métriques d'usage : combien de `rtfm_search` par session en usage réel (pas benchmark)
- Dashboard : visualiser l'index (fichiers, chunks, relations, couverture) via une page web locale
- `rtfm why <file>` : expliquer pourquoi un fichier est dans les résultats (score breakdown)
- `rtfm graph <file>` : afficher les dépendances d'un fichier (quand le graphe sera implémenté)
