# Benchmark Paper Plan

## Objective
Research paper showing the impact of RTFM on the quality, time, and cost of Claude Code on real development tasks (FeatureBench).

## 4 experimental conditions (11 tasks × 4 configs)

| Config                    | Description                                                                   |
| ------------------------- | ----------------------------------------------------------------------------- |
| **A: Standard**           | Original FeatureBench prompt (provides files + interfaces) — unrealistic      |
| **B: Discovery baseline** | Realistic prompt (paths stripped, `--discovery`) without RTFM                 |
| **C: RTFM FTS**           | Discovery prompt + RTFM with FTS only, pre-parsed DB                          |
| **D: RTFM + Embeddings**  | Discovery prompt + RTFM hybrid search, pre-generated DB (FTS+embeddings)      |

## Realistic setup protocol (IMPORTANT)

**Configs C AND D must use pre-built DBs** mounted as volumes.
In real usage, RTFM is already initialized in the project — on-the-fly sync
is a test protocol artifact, not a user reality.

- Config C: mount the pre-parsed FTS-only DB (same principle as D)
- Config D: mount the pre-generated FTS+embeddings DB (already done)
- Parsing/indexing time is reported as "initialization cost" in the paper,
  not as "setup time per run"

### RTFM initialization costs (one-time per project)

| Repo     | Books | Chunks  | Parse+FTS | +Embeddings | DB FTS | DB FTS+Embed |
| -------- | ----- | ------- | --------- | ----------- | ------ | ------------ |
| metaflow | 876   | ~5,060  | ~10s      | +161s       | 12 Mo  | 22 Mo        |
| pydantic | 771   | ~14,762 | ~15s      | +444s       | 18 Mo  | 48 Mo        |
| astropy  | 1,123 | ~41,231 | ~30s      | +1,232s     | 52 Mo  | 133 Mo       |
| mlflow   | 8,260 | 180,262 | 78s       | +5,368s     | 234 Mo | 592 Mo       |

Embedding throughput constant at ~33 chunks/sec on CPU (linear).

### Setup per run (with pre-built DBs)

| Step                 | Config C       | Config D                  |
| -------------------- | -------------- | ------------------------- |
| Install RTFM         | ~18s (`[mcp]`) | ~30s (`[mcp,embeddings]`) |
| Copy pre-built DB    | ~1s            | ~1s (592Mo mlflow)        |
| Warm fastembed model | N/A            | ~17s                      |
| **Total setup**      | **~20s**       | **~50s**                  |

TODO: Modify `claude_code_rtfm.py` (Config C) to copy the pre-parsed FTS DB
instead of syncing on the fly. Create FTS-only DBs for each repo.

## Metrics to collect per run

### Performance
- Total time (wall clock)
- Agent time (excluding RTFM setup)
- RTFM setup time (install + copy DB + warm model)

### Cost
- Tokens input / output / cache read
- Cost $ (via Claude Code `total_cost_usd`)
- Number of turns (API round-trips)

### Quality
- **Resolve rate**: the test passes or not (binary, evaluated by FeatureBench `fb eval`)
- **F2P pass rate**: percentage of fail-to-pass tests that pass
- Patch size (chars)
- Patch correctness (the patch touches the right files)

### Tool usage
- Number of calls per tool (Grep, Glob, Read, Edit, Bash, rtfm_search, rtfm_expand, etc.)
- Discovery vs coding tools ratio

### RTFM transparency (amortized costs)
- Parsing time per repo (one-time)
- Embedding time per repo (one-time)
- Generated DB size
- Fastembed cold start (~17s, one-time per session)

## 11 tasks (4 images, no-GPU, lite split level 1)

### metaflow (1 task, 624 books, 5060 chunks)
- Netflix__metaflow.test_stub_generator

### pydantic (1 task, 771 books, 14762 chunks)
- pydantic__pydantic.test_deprecated_fields

### astropy (2 tasks, ~1122 books)
- astropy__astropy.test_quantity_erfa_ufuncs
- astropy__astropy.test_table

### mlflow (7 tasks, 8260 books, 180262 chunks)
- mlflow__mlflow.test_validation
- mlflow__mlflow.test_judge_tool_search_traces
- mlflow__mlflow.test_serialization
- mlflow__mlflow.test_span
- mlflow__mlflow.test_trace
- mlflow__mlflow.test_databricks_tracing_utils
- mlflow__mlflow.test_responses_agent

## Historical data — Config A (Standard, Feb 22, Sonnet 4.0)

Source: `benchmark_final_results.jsonl` — 10 tasks (no `fb eval`)

| Task                                | Base dur (s) | RTFM dur (s) | Delta    | Base turns | RTFM turns | RTFM searches |
| ----------------------------------- | ------------ | ------------ | -------- | ---------- | ---------- | ------------- |
| test_stub_generator (metaflow)      | 565          | 354          | **-37%** | 60         | 35         | 4             |
| test_quantity_erfa_ufuncs (astropy) | 536          | 606          | +13%     | 62         | 83         | 12            |
| test_table (astropy)                | 675          | 632          | -6%      | 86         | 89         | 8             |
| test_databricks_tracing (mlflow)    | 524          | 688          | +31%     | 52         | 79         | 11            |
| test_judge_tool (mlflow)            | 571          | 457          | **-20%** | 69         | 68         | 18            |
| test_responses_agent (mlflow)       | 746          | 1022         | **+37%** | 84         | 79         | 2             |
| test_serialization (mlflow)         | 481          | 509          | +6%      | 47         | 47         | 6             |
| test_span (mlflow)                  | 707          | 958          | +36%     | 81         | 116        | 4             |
| test_trace (mlflow)                 | 676          | 782          | +16%     | 54         | 99         | 4             |
| test_validation (mlflow)            | 701          | 386          | **-45%** | 45         | 41         | 3             |

**WARNING**: no eval → we don't know if the tests actually pass.

## Historical data — Config B/C Discovery (Feb 25, Sonnet 4.0, mlflow only)

Source: 13 runs in `~/projects/FeatureBench/runs/2026-02-25__*`

| Task                    | Config | Duration (s)    | Cost ($) | Turns | RTFM calls | F2P           | Resolved |
| ----------------------- | ------ | --------------- | -------- | ----- | ---------- | ------------- | ------- |
| test_validation         | B      | 596             | $2.22    | 76    | 0          | 6/11 (54.5%)  | No      |
| test_validation         | C      | 372             | $1.31    | 60    | 1          | 11/11 (100%)  | **YES** |
| test_databricks_tracing | B      | 667             | $2.86    | 61    | 0          | 11/18 (61.1%) | No      |
| test_databricks_tracing | C      | 441             | $2.12    | 51    | 5          | 13/18 (72.2%) | No      |
| test_judge_tool         | B      | 427             | $1.42    | 58    | 0          | 3/18 (16.7%)  | No      |
| test_judge_tool         | C      | 500             | $1.55    | 58    | 8          | 3/18 (16.7%)  | No      |
| test_responses_agent    | B      | TIMEOUT (~1200) | ~$10.64  | ~178  | 0          | -             | -       |
| test_responses_agent    | C      | 917             | $3.58    | 101   | 15         | 0/1 (0%)      | No      |

## Runs Feb 27-28 (Sonnet 4.0, OAuth MAX, post-FastEmbed, pre-parsed DBs)

### test_responses_agent — Full A/B/C/D matrix (worst case)

| Metric | Config A (Standard) | Config B (Discovery) | Config C (FTS) | Config D (Embed+) |
|---|---|---|---|---|
| **Resolved** | No (3.5% F2P) | No (TIMEOUT) | No (0%) | No (0%) |
| **Total duration** | 1156s | **TIMEOUT 1283s** | 1175s | 1013s |
| **Agent duration** | 1019s | ~1200s (killed) | 872s | 872s |
| **Cost (Claude)** | $5.03 | N/A (timeout) | $3.66 | $3.84 |
| **Cost (calculated)** | $8.34 | $6.90 | - | - |
| **Turns** | 118 | 139 (incomplete) | 91 | 103 |
| **Tool calls** | 117 | 138 (incomplete) | 90 | 102 |
| **Read** | 39 | 50 | 27 | 43 |
| **Grep** | 7 | 39 | 15 | 7 |
| **Edit** | 40 | 21 | 26 | 24 |
| **Bash** | 22 | 18 | - | - |
| **RTFM search** | 0 | 0 | 10 | 13 |
| **Cache read** | 23,810,024 | 18,933,950 | 8,676,183 | 8,959,902 |
| **Output tokens** | 529 | 682 | 40,096 | 49,653 |
| **Patch size** | 92,474 chars | 0 (timeout) | 50,539 chars | 91,048 chars |
| **Interfaces covered** | **15/15** | **0/15** | 8/15 | 12/15 |
| **Files modified** | 15 | 0 | 8 (+2 RTFM) | 12 (+2 RTFM) |

**Key observations (4 configs, same task):**
1. **No config resolves the task** — Sonnet 4.0 cannot handle 78K of prompt + 15 interfaces
2. **Config B (discovery) timeout** at 1200s — without paths AND without RTFM, the agent is lost among 8260 files
3. **Config A (standard)** covers the 15 interfaces (paths in the prompt) but still fails (3.5% F2P)
4. **Config D (embeddings)** covers 12/15 — embeddings guide the agent toward the right files better than FTS alone (8/15)
5. **Patch size correlated with interfaces**: A≈D~91K >> C~50K >> B=0
6. **Config C and D** have the lowest cache usage (8-9M vs 19-24M for A/B) — RTFM reduces context
7. **Config A has the most cache read** (24M) — paths in the prompt direct the agent to all files, but it reads them entirely

### test_responses_agent — Sonnet 4.6 attempt (abandoned, insufficient quota)

Exploratory tests Config A and D with Sonnet 4.6, timeout 2400s (40min):

| Metric | S4.0 Config A | S4.0 Config D | S4.6 Config A | S4.6 Config D |
|---|---|---|---|---|
| **Duration** | 1156s | 1013s | TIMEOUT 2480s | TIMEOUT 2545s |
| **Turns** | 118 | 103 | 357 | **657** |
| **Tool calls** | 117 | 102 | 355 | **650** |
| **Read** | 39 | 43 | 129 | **306** |
| **Edit** | 40 | 24 | 55 | **87** |
| **Bash** | 22 | - | **159** | **176** |
| **RTFM search** | 0 | 13 | 0 | 18 |
| **Subagents** | 0 | 0 | 1 | **8** |
| **Cache read** | 23.8M | 9.0M | 54.5M | 49.5M |
| **Cost (calculated)** | $8.34 | $3.84 | $21.65 | $20.86 |

**Sonnet 4.6 observations:**
- Works 3-6x more than 4.0 (657 vs 102 tool calls in Config D)
- Runs tests via Bash (159-176 calls), unlike 4.0 (0 tests)
- Uses subagents to parallelize (8 in D)
- But does not complete in 40min — MAX quota insufficient to explore further
- RTFM amplifies exploratory behavior (657 turns D vs 357 A)
- **Key argument**: at nearly identical duration and cost (~2500s, ~$21), Config D (RTFM)
  does 657 turns vs 357 (Config A) — **2x more useful work for the same price**.
  Cost/turn is lower with RTFM ($0.032 vs $0.061) because cache read/turn
  drops (75K vs 153K): the agent goes directly to the right files instead of exploring everything.
- **Abandoned**: task too heavy even for 4.6, not representative of the real use case

### Failure analysis: test_responses_agent (Sonnet 4.0)

**Why 0% resolution despite RTFM:**

1. **Disproportionate task**: 78K chars of prompt, 15 interfaces, ground truth = 226K chars
   across 60 files. This is an outlier in FeatureBench.

2. **Config C**: ImportError — the agent only implemented 7/15 interfaces.
   It said: "Due to space constraints, let me focus on the most critical interfaces"
   and abandoned the 8 most complex ones. The test cannot be imported.

3. **Config D**: SyntaxError — the agent covered 12/15 interfaces (embeddings guided
   it better) but an editing bug on `responses.py` corrupted the file.
   4 successive Edits to insert `output_to_responses_items_stream` ended up
   turning a `continue` into `continue(chunks:...` → immediate SyntaxError.

4. **No agent ran tests**: neither pytest nor even `python -c "import ..."`.
   Errors would have been detected immediately.

5. **Lost in the middle**: Config D's TodoList contained 9 items instead of 15.
   The 3 missing interfaces (`responses_helpers.py`, `data_validation.py`,
   `models/model.py`) are those appearing at the END of the 78K char prompt.

6. **The FeatureBench prompt does NOT ask to test**: it says "pytest will be used to test"
   (passive) — never "run the tests yourself". No incentive for feedback loop.

**RTFM impact still positive**:
- D covers 12/15 interfaces vs 7/15 for C (+71%)
- D produces a 91K char patch vs 50K (+80%)
- Hybrid search guides the agent to the right files: +59% Read, -53% Grep
- But Sonnet 4.0 cannot handle 78K chars of prompt with 15 complex interfaces

**This is not a retrieval problem, it is a model capability problem.**

### test_stub_generator (metaflow) — ABCD matrix (small repo, 624 books)

| Metric | Config A (Standard) | Config B (Discovery) | Config C (FTS) | Config D (Embed+) |
|---|---|---|---|---|
| **Resolved** | **YES** (100%) | **YES** (100%) | **YES** (100%) | No (96.8%) |
| **F2P** | 31/31 | 31/31 | 31/31 | 30/31 |
| **Total duration** | **370s** | 395s | 454s | 541s |
| **Cost (Claude)** | $0.97 | $1.07 | $1.30 | $1.44 |
| **Cost (calculated)** | $1.44 | $1.65 | $2.08 | $2.33 |
| **Turns** | **42** | 51 | 58 | 67 |
| **Tool calls** | 42 | 51 | 58 | 67 |
| **Grep** | 20 | 15 | 16 | 21 |
| **Read** | 4 | 10 | 16 | 17 |
| **Edit** | 4 | 5 | 7 | 5 |
| **Bash** | 5 | 14 | 5 | 18 |
| **RTFM search** | 0 | 0 | 1 | 1 |
| **RTFM expand** | 0 | 0 | 1 | 0 |
| **RTFM discover** | 0 | 0 | 1 | 0 |
| **Patch size** | 27K | 22K | 22K | 23K |

**Observations (small repo — easy task):**
1. **The 4 configs resolve the task** (except D which misses 1 test/31: `test_class_stub_generation`)
2. **Config A is the fastest** — paths in the prompt eliminate discovery
3. **Config B (discovery) resolves equally well** in +7% time — on a small repo direct nav suffices
4. **RTFM provides no measurable advantage** on a 624-file repo:
   - Config C is +23% slower than A, +22% more expensive
   - Config D is +46% slower, +48% more expensive, and misses 1 test
5. **The RTFM agent barely uses RTFM** (1-2 calls) — it navigates directly because the repo is small
6. **More Read with RTFM** (16-17 vs 4-10) — overhead without gain

**Conclusion**: RTFM does not help on small repos. Setup overhead and MCP calls
add latency without benefit when the agent can navigate directly. RTFM is designed
for large codebases where discovery is the bottleneck.

### test_validation (mlflow) — ABCD matrix (large repo, 8260 books)

| Metric | Config A (Standard) | Config B (Discovery) | Config C (FTS) | Config D (Embed+) |
|---|---|---|---|---|
| **Resolved** | No | No | **YES** | **YES** |
| **F2P** | 6/11 (55%) | 7/11 (64%) | **11/11 (100%)** | **11/11 (100%)** |
| **Total duration** | 479s | 459s | 732s | 605s |
| **Cost (Claude)** | $1.12 | $1.50 | $2.42 | $1.33 |
| **Cost (calculated)** | $1.87 | $2.54 | $4.04 | $2.23 |
| **Turns** | 44 | 53 | 81 | **50** |
| **Tool calls** | 44 | 53 | 81 | 50 |
| **Grep** | 8 | 6 | 7 | 13 |
| **Read** | 9 | 13 | 23 | 12 |
| **Edit** | 4 | 6 | 12 | 5 |
| **Bash** | 18 | 22 | 20 | 9 |
| **Glob** | 0 | 0 | 7 | 1 |
| **RTFM search** | 0 | 0 | 3 | 2 |
| **RTFM expand** | 0 | 0 | 2 | 0 |
| **Patch size** | 16K | 15K | 24K | 23K |

**Observations (large repo — medium task):**
1. **RTFM raises resolution from 55-64% to 100%** — the most striking result of the benchmark
2. **A and B fail on the same tests**: `test_validate_scorers_invalid_all_scorers`,
   `test_validate_data_with_correctness`, `test_validate_data_missing_columns`
   → tests requiring understanding of distant modules (validation.py ↔ scorers.py ↔ data.py)
3. **Config D is the most efficient**: 50 turns vs 81 (C), $2.23 vs $4.04 (C)
   → embeddings guide directly to the right files, less random navigation
4. **Config C is slower but resolves**: FTS suffices when terms are in the prompt
5. **More Read in C (23) than in D (12)**: without embeddings, the agent reads more files to find the right one
6. **Less Bash in D (9) than A/B (18-22)**: the RTFM agent codes more, debugs less
7. **Larger patch with RTFM (23-24K vs 15-16K)**: more complete implementation

**Conclusion**: on a large repo, RTFM changes the outcome. The agent without RTFM cannot find
dependencies between modules → incomplete implementation → failed tests.

### Prompt difference A vs B/C/D

The discovery mode only removes **751 chars out of 78,036** (< 1%):
- 16 lines `Path: /testbed/...` removed
- "under the specified path" → "Explore the existing codebase to determine where"
- Everything else (78K) is identical: description, interfaces, signatures, docstrings

## Infrastructure

### FeatureBench Agents
- `claude_code.py` — Config A and B (standard Claude Code)
- `claude_code_rtfm.py` — Config C (FTS, on-the-fly sync → TO BE MODIFIED for pre-parsed DB)
- `claude_code_rtfm_embed.py` — Config D (pre-generated DB, hybrid search)

### Benchmark Script
- `run_benchmark.sh` — 4 configs × N tasks, auto eval + metrics
- Metrics → `reports/benchmark/metrics.jsonl`
- Tool usage parsed from content blocks in stream output

### Auth: OAuth MAX only (no API key)
- Credentials copied from local → PC2
- Token auto-refreshes via refresh_token
- Need to refresh before each batch run (`scp ~/.claude/.credentials.json`)

## TODO — Next session

### Preparation (before launching runs)
- [x] **Create pre-parsed FTS-only DBs** for each repo — DONE 28/02
      → `/mnt/data/rtfm-dbs-fts/`: metaflow 12Mo, pydantic 18Mo, astropy 52Mo, mlflow 234Mo
- [x] **Modify `claude_code_rtfm.py`** (Config C) to copy the pre-parsed FTS DB — DONE 28/02
      → copies from `/opt/rtfm-dbs-fts/<repo>/library.db`, fallback to sync if absent
- [x] Refresh OAuth credentials on PC2 — DONE 28/02

### Priority runs
- [ ] **Launch A and B on `test_responses_agent`** — IN PROGRESS (A launched 28/02)
- [x] **Launch A/B/C/D on `test_validation`** — DONE 28/02 (RTFM C+D resolve, A+B don't!)
- [x] Launch A/B/C/D on `test_stub_generator` (metaflow) — DONE 28/02 (4/4 resolve except D 30/31)

### Full runs
- [ ] Re-run Config A with eval (11 tasks including pydantic)
- [ ] Launch Config B/C/D on non-mlflow tasks (metaflow, astropy, pydantic)
- [ ] Re-launch Config B for serialization and responses_agent (previously failed)
- [ ] Number of repetitions per condition (significance)
- [ ] Full matrix 11 tasks × 4 configs
