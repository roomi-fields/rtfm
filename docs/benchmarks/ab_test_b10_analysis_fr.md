# A/B Test : Rédaction B10 avec vs sans RTFM

## Date : 2026-02-21

## Sessions analysées
- **Session A (avec RTFM)**: `66c7e81b-00e4-4bde-a9e4-d70e2cbb8a3d` dans musicology-phd
- **Session B (sans RTFM)**: `586966f3-50e0-41b6-be1e-1b7b9dc449be` dans musicology-phd
- **Prompt identique** : "j'aimerai que tu me fasses la redaction de l'article B10"

---

## Résultats globaux

| Métrique | Session A (RTFM) | Session B (sans) | Delta |
|----------|-------------------|-------------------|-------|
| Durée | **12 min** | 8 min 16s | **+45%** |
| Tokens totaux | **3.95M** | 1.70M | **+132%** |
| Coût | **~$13** | ~$6 | **+117%** |
| Tool calls directs | 38 | 37 | +3% |
| Tool calls total (subagents) | 38 | **85** | -55% |
| Langue produite | **Anglais (FAUX)** | Français (correct) | **régression** |
| Article taille | 36K chars, 8 sections | 31K chars, 10 sections, glossaire | |

**Constat : RTFM fait pire sur les 4 axes** (durée, tokens, coût, qualité).

---

## Analyse comportementale Session A (avec RTFM)

### Appels RTFM : 18 total (10 search + 8 expand)

| Catégorie | Count | % |
|-----------|-------|---|
| Nécessaires (info utilisée) | 7 | 39% |
| Redondants | 6 | 33% |
| Inutiles/mal ciblés | 5 | 28% |

### Appels nécessaires détaillés :
1. `rtfm_expand(kanban, "B10")` → confirmé B10 = "EBNF de BP3"
2. `rtfm_expand(b10_ebnf_bp3, ...)` → draft/spec existant
3. `rtfm_search("B8 trois directions")` → B8 en anglais (a causé le bug langue)
4. `rtfm_search("B4 flags poids")` → B4 en anglais (a causé le bug langue)
5. `rtfm_expand(paper1, "Annexe EBNF")` → **contenu EBNF principal** (le vrai apport)
6. `rtfm_expand(l3_ebnf, "notation")` → variants EBNF (contenu pas sur disque)
7. `rtfm_expand(b8, "style article")` → style TikZ et layout

### Appels redondants :
- 3 searches initiales pour trouver B10 (Kanban suffisait)
- Search de BLOG_STRATEGY alors qu'il était lu en parallèle via Read
- Re-expand de B4 (même contenu qu'avant)
- Search MOC alors que Glob suffisait

### Problème critique : la langue
- RTFM a indexé les articles B4 et B8 depuis le répertoire `_en/` (traductions anglaises)
- Corpus `published` = 39 articles, TOUS en `lang: en`
- L'agent a vu `lang: en` dans les métadonnées et conclu "les articles B sont en anglais"
- Le draft B10 existant était en français → ignoré
- **Cause racine** : bug d'indexation — même `book_slug` pour FR et EN, EN écrase FR

### Coût par appel RTFM
Chaque search/expand injecte ~2000-3000 tokens dans le contexte (contenu + metadata + hints).
18 appels × ~2500 tokens = ~45000 tokens de contexte RTFM seul.

### rtfm_remember : jamais appelé
L'instruction existait dans CLAUDE.md mais l'agent l'a ignorée. Le corpus `learned` était vide.

---

## Analyse comportementale Session B (sans RTFM)

### Répartition tool calls (37 directs + 48 subagents = 85)

| Catégorie | Count | % |
|-----------|-------|---|
| Nécessaires | 17 | 46% |
| Dead ends | 15 | 41% |
| Redondants | 3 | 8% |
| Partiellement utiles | 2 | 5% |

### Stratégie : parallélisation via subagents
- **Subagent 1** (general-purpose, 2m14s, 22 calls) : lecture R2 + Paper 1
- **Subagent 2** (Explore, 1m04s, 26 calls) : recherche articles publiés + style
- Les deux en parallèle → recherche lourde en ~2min
- L'agent RTFM a fait toutes ses recherches séquentiellement

### Dead ends (15 calls, mais RAPIDES et GRATUITES)
- 5 Glob dans le mauvais répertoire (repo git au lieu du vault Obsidian)
- 8 Glob pour fichiers publiés en ligne (B1-B8, L3 pas dans le vault)
- 3 Read avec mauvais nom de fichier (Formalisme vs Formalisation)
- Coût : <1s et 0 tokens de contexte chacun

### Langue correcte : pourquoi ?
- B9 (seul article complet trouvé sur disque) est en français
- CLAUDE.md du projet dit "Langue de rédaction : Français"
- Le draft B10 était en français
- Sans RTFM, l'agent n'a pas vu les traductions anglaises → pas de confusion

---

## Diagnostic des causes racines

| Cause | Impact | Détail |
|-------|--------|--------|
| Appels RTFM coûteux en tokens | +132% tokens | Chaque appel injecte ~2500 tokens vs ~0 pour un Glob raté |
| Pas de parallélisation RTFM | +45% durée | MCP = agent principal only, pas de subagents |
| RTFM a surfacé du contenu trompeur | Qualité ↓ | Articles EN ont causé le choix de langue erroné |
| Bug slug collision FR/EN | Qualité ↓ | `_en/B4.md` écrase `B4.md` car même slug |
| rtfm_remember pas utilisé | Valeur = 0 | La seule feature unique n'a pas fonctionné |
| Instructions trop agressives | Overhead | "NEVER Grep/Glob" forçait RTFM pour tout |

---

## Corrections implémentées (cette session)

### 1. Progressive disclosure v2 : metadata-only (FAIT)
- `rtfm_search` et `rtfm_context` retournent UNIQUEMENT les métadonnées (titre, fichier, score, nb chunks, lang)
- Zéro contenu dans les résultats de niveau 0
- ~300 tokens pour 5 résultats au lieu de ~2500
- Le contenu est lu via `rtfm_expand` uniquement quand nécessaire

### 2. File paths dans les résultats (FAIT)
- Chaque résultat montre `file: path/to/file.md`
- Élimine les Glob redondants pour localiser les fichiers

### 3. Language metadata dans les résultats (FAIT)
- Chaque résultat montre `lang: en` ou `lang: fr`
- L'agent peut distinguer les versions FR/EN

### 4. CLI `context` et `expand` pour subagents (FAIT)
- `rtfm --db .rtfm/library.db context "subject"` via Bash
- `rtfm --db .rtfm/library.db expand "slug" "query"` via Bash
- Les subagents Task/Explore peuvent utiliser RTFM

### 5. CLAUDE.md template réécrit (FAIT)
- Plus de "NEVER Grep/Glob"
- RTFM = knowledge/memory, Grep/Glob = code editing
- Subagents autorisés via CLI
- Remember = section dédiée MANDATORY

### 6. Rappel actif pour remember (FAIT)
- Quand le corpus `learned` est vide, les résultats search/context affichent un rappel
- "⚠ Learned corpus is empty. Use rtfm_remember()"

### 7. Fix slug collision (EN COURS)
- `_path_to_slug()` inclut le répertoire parent dans le slug
- `_en/B4.md` → `en--b4_flags` vs `B4.md` → `b4_flags`
- Le sync passe le slug au parser via metadata

---

## Tests : 33/33 MCP tests passent

---

## Session C : RTFM v2 post-corrections (2026-02-21)

- **Session C (RTFM v2)**: `268c7e8f-591a-4b52-ae59-10e668fb7d5b` dans musicology-phd
- **Prompt identique** : "j'aimerai que tu me fasses la rédaction de l'article B10"

### Résultats Session C

| Métrique | Valeur |
|---|---|
| Durée | 11 min 23s |
| Tokens totaux | 5.87M (dont 4.91M cache read) |
| Coût estimé | ~$5.11 |
| Tool calls | 64 (37 main + 27 subagent) |
| Appels RTFM | 7 (3 context + 3 expand + 1 remember) |
| Langue | Français (correct) |
| Article | 38.5K chars, 14 sections (dont glossaire + refs) |

### Corrections v2 validées
- Langue correcte (distinction FR/EN visible dans résultats)
- Metadata-only fonctionne (7 appels vs 18 en v1)
- rtfm_remember utilisé (B10 rédigé indexé dans corpus learned)
- Coût divisé par 2.5 vs v1 ($5.11 vs $13)
- Subagent utilisé pour paralléliser la recherche

### Problèmes restants
- Durée +37% vs session B sans RTFM (11m23 vs 8m16)
- Duplication : 15 Glob + 14 Read en parallèle des appels RTFM
- Subagent tâtonne (15 Bash) au lieu de se fier aux résultats RTFM
- Tokens gonflés (5.87M vs 1.70M sans RTFM) — cache read mitigue le coût

### Tableau comparatif A/B/C

| Métrique | A (RTFM v1) | B (sans) | C (RTFM v2) | Meilleur |
|---|---|---|---|---|
| Durée | 12 min | **8m16s** | 11m23s | B |
| Coût | ~$13 | ~$6 | **~$5.11** | C |
| Langue | ANGLAIS (bug) | FR | **FR** | B/C |
| Taille | 36K/8 sections | 31K/10 | **38.5K/14** | C |
| RTFM calls | 18 | 0 | **7** | C |
| remember | jamais | n/a | **oui** | C |

---

## Session D : RTFM v2+ template affiné (2026-02-21)

- **Session D**: `1f783e5e-8d6f-4bff-be5d-d0e5d48fd95c` dans musicology-phd
- **Prompt identique**

### Résultats Session D

| Métrique | Valeur |
|---|---|
| Durée | 15m48s (la pire) |
| Tokens totaux | 3.97M (dont 3.6M cache read) |
| Coût estimé | **$2.62** (le meilleur) |
| Tool calls | 32 (0 subagents) |
| Appels RTFM | 12 (3 context + 2 search + 7 expand) |
| Langue | Français (correct) |
| Article | 31.4K chars, 14+4 sections |
| remember | NON (régression) |

### Problèmes identifiés
- CLI `rtfm context` via Bash échoue (venv pas dans PATH)
- Read après expand (B10 expand 27K puis Read x3)
- Glob après context (5 Glob Blog/B* redondants)
- Expand dupliqué (b11_ast_bp3 x2)
- remember oublié malgré les instructions

### Corrections implémentées post-D
1. Template CLAUDE.md v3 : anti-duplication explicite, CLI retiré
2. Hook Stop : bloque l'arrêt si rtfm_remember pas appelé
3. Hook PostToolUse : stamp quand rtfm_remember est appelé
4. Hook SessionStart : clear le stamp au début

### Tableau comparatif A/B/C/D

| Métrique | A (v1) | B (sans) | C (v2) | D (v2+) | Meilleur |
|---|---|---|---|---|---|
| Durée | 12m | **8m16s** | 11m23s | 15m48s | B |
| Coût | ~$13 | ~$6 | ~$5.11 | **$2.62** | D |
| Langue | BUG | FR | FR | FR | B/C/D |
| Article | 36K/8 | 31K/10 | **38.5K/14** | 31.4K/18 | C |
| Tool calls | 38 | 85 | 64 | **32** | D |
| Duplication | N/A | N/A | ~29 | **~10** | D |
| remember | non | n/a | oui | non | C |
