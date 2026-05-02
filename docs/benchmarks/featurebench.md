# FeatureBench Integration Notes

## Setup
- Repo: `/mnt/d/Claude/FeatureBench/`
- Installed via `uv sync` (Python 3.12+)
- Config: `config.toml` (gitignored, contains no API keys)
- CLI: `fb infer`, `fb eval`, `fb pull`
- Extract metrics: `python extract_metrics.py <run_dir> <task_id>`

## OAuth/MAX Integration (custom patch)
- Modified `run_infer.py` → `_build_volumes()` method
- When `ANTHROPIC_API_KEY` is empty, mounts `~/.claude/` → `/root/.claude/` in Docker
- Claude Code CLI inside Docker uses the host's OAuth session (MAX subscription)

## RTFM Integration
- Agent: `ClaudeCodeRTFMAgent` in `agents/claude_code_rtfm.py`
- Extends `ClaudeCodeAgent` with `pre_run_setup()` hook
- Steps: `python -m pip install /opt/rtfm[mcp]` → rtfm init → rtfm sync → write CLAUDE.md → gitignore
- RTFM source auto-detected: `_find_rtfm_source()` checks RTFM_SRC env, ~/projects/rtfm, ~/projects/biblirag, /mnt/d/Claude/RTFM, /mnt/d/Claude/biblirag
- **Key fix (2026-02-25)**: must use `python -m pip install` (not `pip install`) for conda env targeting
- **Key fix (2026-02-25)**: volume mount path was hardcoded to WSL path, now auto-detected

## A/B Benchmark Results (2026-02-22) — 10 tasks

**RTFM LOSES in aggregate: +3.4% duration, +15% turns, +20% cache read tokens**
**Win rate: 4/10 tasks**

| Task | Base dur | RTFM dur | Delta | Indexed |
|------|----------|----------|-------|---------|
| metaflow/stub_generator | 565s | 354s | **-37%** | 623 |
| astropy/erfa_ufuncs | 536s | 606s | +13% | 1122 |
| astropy/table | 675s | 632s | -6% | 1122 |
| mlflow/databricks_tracing | 524s | 688s | +31% | 8258 |
| mlflow/judge_tool | 571s | 457s | **-20%** | 8259 |
| mlflow/responses_agent | 746s | 1022s | +37% | 8258 |
| mlflow/serialization | 481s | 509s | +6% | 8259 |
| mlflow/span | 707s | 958s | +36% | 8259 |
| mlflow/trace | 676s | 782s | +16% | 8259 |
| mlflow/validation | 701s | 386s | **-45%** | 8259 |

### Key Findings
- RTFM wins on small repos (metaflow 623 files: -37%)
- RTFM loses on large repos (mlflow 8259 files: most tasks slower)
- Problem: on large repos, RTFM search adds noise → agent spends more time searching than coding
- Grep reduced by -57 calls, but replaced by +116 Bash calls (rtfm search) which are slower
- No `rtfm context` used, almost no `rtfm expand` — agent only uses `rtfm search`

### Improvement Ideas
1. Filter indexed files (skip vendored, tests, generated code)
2. Limit RTFM search results (top 3 instead of top 5+)
3. Better CLAUDE.md template: "search once, then code" not "search repeatedly"
4. Hybrid mode: RTFM for discovery, Grep for precision
5. Don't index repos > 2000 files in full — index only key directories

## Task Availability (lite split = 30 tasks)
- 11 tasks WITHOUT GPU requirement
- 19 tasks WITH GPU requirement
- pydantic image failed to download (Docker WSL2 SIGBUS bug)
- All valid results: `benchmark_final_results.jsonl`

## FeatureBench-Discovery Mode (2026-02-23)

Original FeatureBench prompts give exact file paths + interfaces. This makes
discovery tools useless. Discovery mode (`--discovery` flag) strips `Path:` lines
but keeps interface signatures. Agent must explore codebase to find correct locations.

**Implementation**: `_strip_interface_paths()` in `run_infer.py`
- Removes all `Path: /testbed/...` lines via regex
- Replaces boilerplate "The value of Path declares..." with "Explore the codebase..."
- CLI: `fb infer --discovery -a claude_code_rtfm ...`
- Stored in `run_metadata.json` as `discovery_mode: true`

**Benchmark plan**: Run 2 configs on the 11 no-GPU tasks:
1. `claude_code --discovery` (baseline with open prompts)
2. `claude_code_rtfm --discovery` (RTFM with open prompts)

Compare: solve rate, duration, tool calls.

### First Discovery A/B Result (2026-02-25, mlflow/validation, Sonnet 4)
| | Baseline | RTFM |
|---|---|---|
| Total time | 11m24s | 9m27s |
| Setup (RTFM) | 0 | 108s (install+init+sync 8259 books) |
| Agent work | ~10m | ~6m15s |
| Patch size | 16,927 chars | 22,485 chars |
| RTFM tool calls | 0 | 15 |
| **Gain** | - | **-17% total, -37% agent time** |

PC2: roomi@192.168.1.28, runs stored in `~/projects/FeatureBench/runs/`

**Methodology justification**: Same repos, same tests, same interfaces.
Only variable = whether agent has RTFM search tools. Evaluates whether
pre-indexed search reduces discovery overhead on large codebases.

## Discovery A/B Batch (2026-02-25, in progress)
- 6 mlflow tasks running via `run_mlflow_ab.sh` on PC2 (PID started ~11:52)
- Script: baseline → RTFM → eval both → generate_report.py → markdown report
- Reports → `~/projects/FeatureBench/reports/discovery-ab/`
- Docker on PC2: NTFS partition cannot host overlay2, must stay on ext4 root
- Strategy for remaining 4 tasks: one image at a time (pull, run, remove)
  - metaflow (1 task), astropy (2 tasks), pydantic (1 task)

## Files Modified in FeatureBench
- `featurebench/infer/run_infer.py` — `_build_volumes()`, CLI choices, `_strip_interface_paths()`
- `featurebench/infer/models.py` — `discovery_mode` field on InferConfig + RunMetadata
- `featurebench/infer/agents/claude_code_rtfm.py` — new agent (MCP tools in ALLOWED_TOOLS)
- `featurebench/infer/agents/__init__.py` — agent registration
- `config.toml` — `[infer_config.claude_code_rtfm]` section
- `extract_metrics.py` — metrics extraction script
- `benchmark_final_results.jsonl` — clean results for all 10 pairs
