# A/B Test: Writing B10 with vs without RTFM

## Date: 2026-02-21

## Sessions analyzed
- **Session A (with RTFM)**: `66c7e81b-00e4-4bde-a9e4-d70e2cbb8a3d` in musicology-phd
- **Session B (without RTFM)**: `586966f3-50e0-41b6-be1e-1b7b9dc449be` in musicology-phd
- **Identical prompt**: "j'aimerai que tu me fasses la redaction de l'article B10"

---

## Overall results

| Metric | Session A (RTFM) | Session B (without) | Delta |
|----------|-------------------|-------------------|-------|
| Duration | **12 min** | 8 min 16s | **+45%** |
| Total tokens | **3.95M** | 1.70M | **+132%** |
| Cost | **~$13** | ~$6 | **+117%** |
| Direct tool calls | 38 | 37 | +3% |
| Total tool calls (subagents) | 38 | **85** | -55% |
| Output language | **English (WRONG)** | French (correct) | **regression** |
| Article size | 36K chars, 8 sections | 31K chars, 10 sections, glossary | |

**Finding: RTFM performs worse on all 4 axes** (duration, tokens, cost, quality).

---

## Behavioral analysis Session A (with RTFM)

### RTFM calls: 18 total (10 search + 8 expand)

| Category | Count | % |
|-----------|-------|---|
| Necessary (info used) | 7 | 39% |
| Redundant | 6 | 33% |
| Useless/poorly targeted | 5 | 28% |

### Necessary calls in detail:
1. `rtfm_expand(kanban, "B10")` → confirmed B10 = "EBNF of BP3"
2. `rtfm_expand(b10_ebnf_bp3, ...)` → existing draft/spec
3. `rtfm_search("B8 three directions")` → B8 in English (caused the language bug)
4. `rtfm_search("B4 flags weights")` → B4 in English (caused the language bug)
5. `rtfm_expand(paper1, "EBNF Appendix")` → **main EBNF content** (the real contribution)
6. `rtfm_expand(l3_ebnf, "notation")` → EBNF variants (content not on disk)
7. `rtfm_expand(b8, "article style")` → TikZ style and layout

### Redundant calls:
- 3 initial searches to find B10 (Kanban was sufficient)
- Search for BLOG_STRATEGY while it was read in parallel via Read
- Re-expand of B4 (same content as before)
- Search MOC while Glob would have sufficed

### Critical problem: language
- RTFM indexed articles B4 and B8 from the `_en/` directory (English translations)
- Corpus `published` = 39 articles, ALL with `lang: en`
- The agent saw `lang: en` in the metadata and concluded "the B articles are in English"
- The existing B10 draft was in French → ignored
- **Root cause**: indexing bug — same `book_slug` for FR and EN, EN overwrites FR

### Cost per RTFM call
Each search/expand injects ~2000-3000 tokens into the context (content + metadata + hints).
18 calls × ~2500 tokens = ~45000 tokens of RTFM context alone.

### rtfm_remember: never called
The instruction existed in CLAUDE.md but the agent ignored it. The `learned` corpus was empty.

---

## Behavioral analysis Session B (without RTFM)

### Tool call distribution (37 direct + 48 subagents = 85)

| Category | Count | % |
|-----------|-------|---|
| Necessary | 17 | 46% |
| Dead ends | 15 | 41% |
| Redundant | 3 | 8% |
| Partially useful | 2 | 5% |

### Strategy: parallelization via subagents
- **Subagent 1** (general-purpose, 2m14s, 22 calls): reading R2 + Paper 1
- **Subagent 2** (Explore, 1m04s, 26 calls): search for published articles + style
- Both in parallel → heavy research in ~2min
- The RTFM agent did all its searches sequentially

### Dead ends (15 calls, but FAST and FREE)
- 5 Globs in the wrong directory (git repo instead of Obsidian vault)
- 8 Globs for online published files (B1-B8, L3 not in the vault)
- 3 Reads with wrong filename (Formalisme vs Formalisation)
- Cost: <1s and 0 context tokens each

### Correct language: why?
- B9 (only complete article found on disk) is in French
- Project CLAUDE.md says "Writing language: French"
- The B10 draft was in French
- Without RTFM, the agent didn't see the English translations → no confusion

---

## Root cause diagnosis

| Cause | Impact | Detail |
|-------|--------|--------|
| RTFM calls expensive in tokens | +132% tokens | Each call injects ~2500 tokens vs ~0 for a failed Glob |
| No RTFM parallelization | +45% duration | MCP = main agent only, no subagents |
| RTFM surfaced misleading content | Quality ↓ | EN articles caused incorrect language choice |
| Slug collision FR/EN bug | Quality ↓ | `_en/B4.md` overwrites `B4.md` because same slug |
| rtfm_remember not used | Value = 0 | The only unique feature did not work |
| Instructions too aggressive | Overhead | "NEVER Grep/Glob" forced RTFM for everything |

---

## Fixes implemented (this session)

### 1. Progressive disclosure v2: metadata-only (DONE)
- `rtfm_search` and `rtfm_context` return ONLY metadata (title, file, score, chunk count, lang)
- Zero content in level-0 results
- ~300 tokens for 5 results instead of ~2500
- Content is read via `rtfm_expand` only when necessary

### 2. File paths in results (DONE)
- Each result shows `file: path/to/file.md`
- Eliminates redundant Globs to locate files

### 3. Language metadata in results (DONE)
- Each result shows `lang: en` or `lang: fr`
- The agent can distinguish FR/EN versions

### 4. CLI `context` and `expand` for subagents (DONE)
- `rtfm --db .rtfm/library.db context "subject"` via Bash
- `rtfm --db .rtfm/library.db expand "slug" "query"` via Bash
- Task/Explore subagents can use RTFM

### 5. CLAUDE.md template rewritten (DONE)
- No more "NEVER Grep/Glob"
- RTFM = knowledge/memory, Grep/Glob = code editing
- Subagents allowed via CLI
- Remember = MANDATORY dedicated section

### 6. Active reminder for remember (DONE)
- When the `learned` corpus is empty, search/context results display a reminder
- "⚠ Learned corpus is empty. Use rtfm_remember()"

### 7. Fix slug collision (IN PROGRESS)
- `_path_to_slug()` includes the parent directory in the slug
- `_en/B4.md` → `en--b4_flags` vs `B4.md` → `b4_flags`
- Sync passes the slug to the parser via metadata

---

## Tests: 33/33 MCP tests pass

---

## Session C: RTFM v2 post-fixes (2026-02-21)

- **Session C (RTFM v2)**: `268c7e8f-591a-4b52-ae59-10e668fb7d5b` in musicology-phd
- **Identical prompt**: "j'aimerai que tu me fasses la rédaction de l'article B10"

### Session C results

| Metric | Value |
|---|---|
| Duration | 11 min 23s |
| Total tokens | 5.87M (of which 4.91M cache read) |
| Estimated cost | ~$5.11 |
| Tool calls | 64 (37 main + 27 subagent) |
| RTFM calls | 7 (3 context + 3 expand + 1 remember) |
| Language | French (correct) |
| Article | 38.5K chars, 14 sections (including glossary + refs) |

### v2 fixes validated
- Correct language (FR/EN distinction visible in results)
- Metadata-only works (7 calls vs 18 in v1)
- rtfm_remember used (written B10 indexed in learned corpus)
- Cost divided by 2.5 vs v1 ($5.11 vs $13)
- Subagent used to parallelize research

### Remaining issues
- Duration +37% vs session B without RTFM (11m23 vs 8m16)
- Duplication: 15 Glob + 14 Read in parallel with RTFM calls
- Subagent fumbles (15 Bash) instead of relying on RTFM results
- Inflated tokens (5.87M vs 1.70M without RTFM) — cache read mitigates the cost

### A/B/C comparison table

| Metric | A (RTFM v1) | B (without) | C (RTFM v2) | Best |
|---|---|---|---|---|
| Duration | 12 min | **8m16s** | 11m23s | B |
| Cost | ~$13 | ~$6 | **~$5.11** | C |
| Language | ENGLISH (bug) | FR | **FR** | B/C |
| Size | 36K/8 sections | 31K/10 | **38.5K/14** | C |
| RTFM calls | 18 | 0 | **7** | C |
| remember | never | n/a | **yes** | C |

---

## Session D: RTFM v2+ refined template (2026-02-21)

- **Session D**: `1f783e5e-8d6f-4bff-be5d-d0e5d48fd95c` in musicology-phd
- **Identical prompt**

### Session D results

| Metric | Value |
|---|---|
| Duration | 15m48s (the worst) |
| Total tokens | 3.97M (of which 3.6M cache read) |
| Estimated cost | **$2.62** (the best) |
| Tool calls | 32 (0 subagents) |
| RTFM calls | 12 (3 context + 2 search + 7 expand) |
| Language | French (correct) |
| Article | 31.4K chars, 14+4 sections |
| remember | NO (regression) |

### Issues identified
- CLI `rtfm context` via Bash fails (venv not in PATH)
- Read after expand (B10 expand 27K then Read x3)
- Glob after context (5 redundant Glob Blog/B*)
- Duplicated expand (b11_ast_bp3 x2)
- remember forgotten despite instructions

### Fixes implemented post-D
1. CLAUDE.md template v3: explicit anti-duplication, CLI removed
2. Stop hook: blocks stopping if rtfm_remember not called
3. PostToolUse hook: stamp when rtfm_remember is called
4. SessionStart hook: clear the stamp at the start

### A/B/C/D comparison table

| Metric | A (v1) | B (without) | C (v2) | D (v2+) | Best |
|---|---|---|---|---|---|
| Duration | 12m | **8m16s** | 11m23s | 15m48s | B |
| Cost | ~$13 | ~$6 | ~$5.11 | **$2.62** | D |
| Language | BUG | FR | FR | FR | B/C/D |
| Article | 36K/8 | 31K/10 | **38.5K/14** | 31.4K/18 | C |
| Tool calls | 38 | 85 | 64 | **32** | D |
| Duplication | N/A | N/A | ~29 | **~10** | D |
| remember | no | n/a | yes | no | C |
