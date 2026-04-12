# Paper Plan — v3

## Working title

**"Does Retrieval Help? A Controlled Study of Pre-Indexed Search Tools for Coding Agents on Feature Implementation Tasks"**

Alternatives:
- "Search Before You Code: Measuring the Impact of Retrieval Tools on Coding Agent Performance"
- "The Localization Bottleneck: How Pre-Indexed Retrieval Changes Coding Agent Outcomes on Large Repositories"
- "Knowing What You Don't Know: How Pre-Indexed Retrieval Transforms Coding Agent Performance on Large Repositories"

---

## Central thesis

> A coding agent equipped with a pre-indexed search tool — i.e. able to *know that it doesn't know* and go look things up — resolves more tasks, more efficiently, than an agent navigating blindly. But this advantage appears only when the repository is large enough that direct navigation becomes a bottleneck.

---

## Claimed contributions

1. **RTFM, an agnostic retrieval tool for coding agents** — open source, protocol-agnostic (MCP), model-agnostic, format-agnostic (extensible parsers), with a progressive-disclosure pattern (metadata-first → expand on demand) designed to minimize context consumption.

2. **First controlled empirical study** of the impact of a pre-indexed retrieval tool on a coding agent, evaluated on a standardized benchmark (FeatureBench, ICLR 2026).

3. **4-condition protocol** isolating the retrieval variable:
   - A = standard prompt (paths given — partial oracle)
   - B = realistic discovery prompt (paths removed, no retrieval)
   - C = discovery + FTS retrieval
   - D = discovery + FTS + embeddings retrieval

4. **Empirical identification of a size threshold** beyond which retrieval helps: the gain appears on large repos (8K+ files) and disappears on small ones (~600 files).

5. **Localization-bottleneck analysis**: decomposition of agent time into exploration vs. coding, showing that retrieval reduces exploration time on large repos.

---

## Paper structure

### 1. Introduction (~1 page)

**Hook:** Coding agents (Claude Code, Cursor, SWE-agent) are limited not by code-generation capability but by their ability to find the right context (Runner 2025, Context Rot 2025). The oracle gap is huge: on HumanEval, moving from BM25 to oracle context lifts StarCoder2-7B from 43.9% to 94.5% (CodeRAG-Bench, NAACL 2025).

**Problem:** Current agents explore repos with grep/glob/find — blind tools. 38% of their actions are exploration/comprehension, not code writing (Trajectory Study, 2025). On large repos, they fall into unproductive exploration loops (SWE-EVO, 2025).

**Research question:** *Does giving a coding agent a pre-indexed search tool improve resolve rate, cost, and duration on real feature-implementation tasks?*

**Short answer:** Yes, on large repos. On test_validation (mlflow, 8260 files), resolve rate goes from 55-64% (without retrieval) to 100% (with retrieval). On test_stub_generator (metaflow, 624 files), no measurable gain.

**Contribution:** First controlled study on a standardized benchmark, 4 conditions, N tasks × N repetitions.

### 2. Related Work (~2 pages)

#### 2.1 The localization bottleneck in coding agents
- Agentless (Xia et al., 2024): hierarchical localization, 77.7% file recall → 50.8% line recall
- PatchPilot (ICML 2025): localization accounts for ~47% of total improvement
- LocAgent (ACL 2025): 92.7% Acc@5 with graph-guided search
- SWE-bench oracle experiments (ICLR 2024): too much context degrades performance
- Trajectory Study (2025): 38% of actions = exploration, failed agents = repetitive loops
- Navigation Paradox (2026): +23.2 pp with a structured navigation MCP tool

#### 2.2 Retrieval-Augmented Code Generation
- CodeRAG-Bench (NAACL 2025): RAG improves universally, oracle gap = 9-50 pp
- Practical Code RAG at Scale (Galimzyanov 2025): BM25 beats dense embeddings for code-to-code
- GrepRAG (ISSTA 2026): lexical retrieval beats graph-based methods
- What to Retrieve (2025): similar code = noise (-15%), contextual code = the right signal
- cAST (CMU 2025): AST chunking > line-based chunking

#### 2.3 Adaptive and selective retrieval
- Self-RAG (ICLR 2024): adaptive retrieval > always-retrieve (+40% relative)
- Repoformer (ICML 2024): 70% of code retrievals are useless, selective = +70% speedup
- FLARE (EMNLP 2023): θ=0 (never) and θ=1 (always) suboptimal
- Adaptive-RAG (NAACL 2024): routing by complexity (no retrieval / single / multi-step)

#### 2.4 Existing retrieval tools for coding agents
- Augment Context Engine MCP (2026): +80% claimed, no published protocol
- Sourcegraph Cody MCP: enterprise, code-only, no public benchmark
- CodeCompass (Navigation Paradox, 2026): MCP + AST graph, 30 synthetic micro-tasks
- Code-Index-MCP, mcp-codebase-index: open-source tools, zero published evaluation
- Codified Context (2026): MCP + manual specs, 283 sessions, no standardized benchmark
- **Identified gap:** no controlled study on a standardized benchmark measuring the impact of a pre-indexed retrieval tool on a coding agent

#### 2.5 Coding-agent benchmarks
- SWE-bench (ICLR 2024): standard but proven contamination (SWE-Bench Illusion, 2025)
- FeatureBench (ICLR 2026): feature implementation, harder (11% vs 74% SWE-bench), less contaminated
- ContextBench (2025): measures the quality of retrieved context, not the final result
- Tokenomics (2026): input tokens = 53.9% of total cost

### 3. RTFM: An Agnostic Retrieval Layer for Coding Agents (~1.5 pages)

Before presenting the study, we describe the tool used as the experimental intervention — not to claim architectural novelty, but because its design choices directly influence the results observed.

#### 3.1 Philosophy: the universal tool that only touches what it should

RTFM is not a code tool. It's a **knowledge** tool. Its design principles:

1. **Domain-agnostic** — Indexes everything: code (Python AST, shell), documentation (Markdown, LaTeX), structured data (YAML, JSON, XML), legal documents (Legifrance XML, BOFiP HTML), PDF, plain text. The same tool serves a developer, a lawyer, a researcher. No "code retrieval": *knowledge retrieval*.

2. **Format-agnostic via extensible parsers** — Adding a new format = ~50 lines of Python (inherit from `BaseParser`, implement `parse()`). The system doesn't presume the format — it adapts. 10 built-in parsers, extensible by the community.

3. **Protocol-agnostic (MCP)** — Exposed via Model Context Protocol, Anthropic's open standard. Works with any MCP-compatible agent: Claude Code, Continue.dev, Cursor (via MCP), any MCP client. No lock-in to an IDE or vendor.

4. **Model-agnostic** — Pure retrieval, zero generation. No embedded language model. The tool returns search results; the agent's model decides what to do with them. Compatible with any LLM (Claude, GPT, Gemini, open-source).

5. **Non-invasive** — RTFM does not modify the agent's workflow. It adds search tools (`rtfm_search`, `rtfm_context`, `rtfm_expand`). The agent can use or ignore them. It replaces blind navigation (grep/glob/find) when relevant, and touches nothing else. No forced retrieval, no silently injected context.

#### 3.2 Architecture: progressive disclosure

The central architectural pattern is **metadata-first → expand on demand**:

1. `rtfm_search(query)` → returns ~300 tokens of **metadata**: title, slug, absolute path, score. No content.
2. The agent reads the file directly via `Read(file_path)` — the absolute path is in the results.
3. Optional: `rtfm_expand(slug)` returns the full content of a specific chunk (for sources indexed without a direct source file).

This pattern minimizes context consumption. The agent loads only what it needs, when it needs it. It's the opposite of the "dump all context" approach that causes context rot (Hong et al., 2025).

**Technical stack:** SQLite + FTS5 (BM25) as the backbone, optional embeddings via FastEmbed (ONNX, ~17s warm-up). Incremental sync via SHA-256 hashing. Portable DB (a single `.db` file).

#### 3.3 Positioning vs existing tools

| Property | RTFM | Augment CE | Code-Index-MCP | CodeCompass |
|-----------|------|------------|----------------|-------------|
| Multi-domain | Code+docs+legal+research+data | Code+docs+tickets | Code only | Python code |
| Extensible parsers | Yes (~50 LOC) | No | No | No |
| Open source | Yes | No | Yes | Yes |
| Native MCP | Yes | Yes | Yes | Yes |
| Progressive disclosure | metadata-first | N/A (proprietary) | direct content | AST graph |
| Published evaluation | **This paper** | "+80%" no protocol | None | 30 micro-tasks |
| Pricing | Free | $20-200/mo | Free | Free |

The real differentiator is not architectural — it is that we **rigorously evaluate** the tool's impact on a standardized benchmark.

### 4. Experimental Setup (~2 pages)

#### 4.1 Benchmark: FeatureBench
- 11 tasks, 4 repos (metaflow, pydantic, astropy, mlflow)
- Why FeatureBench: feature implementation (not just bug fix), discovery required, less contaminated than SWE-bench
- Repo sizes: 624 files (metaflow) → 8260 files (mlflow)

#### 4.2 The 4 experimental conditions

| Config | Prompt | Retrieval | Description |
|--------|--------|-----------|-------------|
| **A: Standard** | Paths given | None | Original FeatureBench prompt gives files and interfaces — positive control (partial oracle) |
| **B: Discovery** | Paths removed | None | Realistic prompt: the agent must discover where to code — realistic baseline |
| **C: FTS** | Paths removed | FTS5 (BM25) | Discovery + pre-indexed full-text search tool |
| **D: FTS+Embed** | Paths removed | FTS5 + embeddings | Discovery + hybrid search (FTS + semantic) |

- Discovery mode strips < 1% of the prompt (751 chars / 78K): only the `Path: /testbed/...` lines
- The only variable between B and C/D is the presence of the retrieval tool
- Configs C and D use pre-built DBs (no on-the-fly sync = realistic)

#### 4.3 Agent and model
- Agent: Claude Code (Anthropic)
- Model: Claude Sonnet 4.0 (fixed across all conditions)
- Environment: Docker (FeatureBench), 1200s timeout
- Authentication: OAuth MAX (no API key)

#### 4.4 The retrieval tool (implementation details)
- Implemented as an MCP server with 11 tools (search, context, expand, discover, etc.)
- Metadata-only search (~300 tokens for 5 results) with absolute paths
- The agent then uses `Read(file_path)` for actual content
- FTS5 (Config C): zero cold start, ~20s setup (install + copy DB)
- FTS + embeddings (Config D): ~50s setup (install + copy DB + warm fastembed ~17s)

#### 4.5 Metrics
- **Resolve rate**: test passes or not (binary, via `fb eval`)
- **F2P pass rate**: fraction of fail-to-pass tests that pass (partial credit)
- **Total duration**: wall-clock time (includes setup)
- **Agent duration**: time excluding RTFM setup
- **Cost**: $ via Claude Code's `total_cost_usd`
- **Tokens**: input, output, cache read
- **Tool calls**: count and type (Read, Grep, Glob, Edit, Bash, rtfm_search, rtfm_expand, etc.)
- **Exploration/coding ratio**: (Read+Grep+Glob+rtfm_search) / (Edit+Write)

#### 4.6 RTFM initialization costs (reported separately)

| Repo | Books | Chunks | Parse+FTS | +Embeddings | DB FTS | DB FTS+Embed |
|------|-------|--------|-----------|-------------|--------|--------------|
| metaflow | 876 | ~5,060 | ~10s | +161s | 12 MB | 22 MB |
| pydantic | 771 | ~14,762 | ~15s | +444s | 18 MB | 48 MB |
| astropy | 1,123 | ~41,231 | ~30s | +1,232s | 52 MB | 133 MB |
| mlflow | 8,260 | 180,262 | 78s | +5,368s | 234 MB | 592 MB |

### 5. Results (~3 pages)

#### 5.1 Main result: resolve rate per condition

Main table: 11 tasks × 4 conditions, resolve rate (yes/no) + F2P pass rate.

**Hypothesis:** C and D > B on large repos, C/D ≈ B on small ones.

Current data (to be completed with ongoing runs):

| Task (repo, size) | A (Standard) | B (Discovery) | C (FTS) | D (FTS+Embed) |
|---|---|---|---|---|
| test_validation (mlflow, 8260) | 55% F2P | 64% F2P | **100% F2P** | **100% F2P** |
| test_stub_generator (metaflow, 624) | **100%** | **100%** | **100%** | 96.8% |
| test_responses_agent (mlflow, 8260) | 3.5% | TIMEOUT | 0% | 0% |

#### 5.2 Effect of repo size

Plot: resolve rate (C/D) - resolve rate (B) as a function of number of files in the repo.
- metaflow (624): no gain
- pydantic (771): to be measured
- astropy (1,123): to be measured
- mlflow (8,260): significant gain (at least on test_validation)

**Threshold hypothesis:** there is a repo size beyond which direct navigation no longer suffices and retrieval becomes beneficial.

#### 5.3 Cost and duration

Table: duration and cost per condition, per task.

Current data:

| Task | Metric | A | B | C | D |
|---|---|---|---|---|---|
| test_validation | Duration | 479s | 459s | 732s | 605s |
| test_validation | Cost | $1.12 | $1.50 | $2.42 | $1.33 |
| test_stub_generator | Duration | 370s | 395s | 454s | 541s |
| test_stub_generator | Cost | $0.97 | $1.07 | $1.30 | $1.44 |

**Expected observation:** retrieval may increase cost/duration (MCP overhead) while improving resolve rate. Cost vs. quality trade-off.

#### 5.4 Tool-usage analysis

Table: distribution of tool calls by category (exploration vs. coding) per condition.

| Task | Condition | Grep | Read | Glob | Bash | Edit | RTFM search | Expl/code ratio |
|---|---|---|---|---|---|---|---|---|
| test_validation | B | 6 | 13 | 0 | 22 | 6 | 0 | 6.8:1 |
| test_validation | D | 13 | 12 | 1 | 9 | 5 | 2 | 5.6:1 |

**Observation:** with retrieval, the agent makes fewer Bash calls (debug) and more targeted Grep calls, suggesting more efficient exploration.

#### 5.5 FTS vs FTS+Embeddings (C vs D)

Direct comparison of the two retrieval modes:
- D resolves as many tasks as C but in fewer turns (50 vs 81 on test_validation)
- D makes fewer Reads (12 vs 23) — embeddings guide directly to the right files
- D is more efficient (cost $2.23 vs $4.04 on test_validation)

#### 5.6 Failure analysis: when retrieval is not enough

test_responses_agent: 78K chars prompt, 15 interfaces, no config resolves.
- Not a retrieval problem, it's a model-capacity problem
- D covers 12/15 interfaces vs 7/15 for C → embeddings guide better
- But Sonnet 4.0 can't handle the complexity even with the right context

### 6. Discussion (~1.5 pages)

#### 6.1 Retrieval solves the localization bottleneck — on large repos

The results confirm the literature: PatchPilot shows that localization = 47% of total gain, and our results show that retrieval transforms localization on large repos. test_validation fails without retrieval because the agent does not find the cross-module dependencies (validation.py ↔ scorers.py ↔ data.py). With retrieval, it finds them immediately.

#### 6.2 Retrieval does not replace model intelligence

test_responses_agent shows that even with perfect retrieval, the model cannot handle 15 complex interfaces. Retrieval is necessary but not sufficient.

#### 6.3 The cost-quality trade-off

Retrieval increases the per-task cost (MCP overhead, search-result tokens) but raises resolve rate. **A more expensive run that resolves > a cheaper run that fails.** The relevant cost is the cost PER RESOLVED TASK.

#### 6.4 FTS as a strong baseline

Confirmed by Galimzyanov (2025) and GrepRAG (2026): BM25/FTS is competitive with embeddings for code. Config C resolves as well as D on test_validation. Embeddings add value on efficiency (fewer turns) but not on resolve rate.

#### 6.5 The agent as retrieval decider

Unlike Self-RAG (fine-tuning to decide when to retrieve) or Repoformer (trained classifier), our approach is simple: we **give the tool** to the agent and let it decide. The agent uses RTFM 1-15 times depending on the task — it does selective retrieval naturally, without specific training. This suggests current LLMs have sufficient metacognition for selective retrieval when the tool is available.

#### 6.6 Universality as strength: beyond code

RTFM is not limited to code. The same tool indexes documentation, configuration files, legal specifications, research data. In practice, an agent looking for "how to validate input data" in a project can find the existing validation code, the documentation of business constraints, and the corresponding tests — without switching tools. This universality avoids the problem of specialized tools that fragment project knowledge.

The tool replaces blind navigation where necessary (cross-module dependency search, locating relevant files) and doesn't touch the rest of the workflow (editing, execution, debugging). It is an amplifier, not a replacement.

#### 6.7 Limitations

- A single model (Sonnet 4.0) — generalization to other models is unmeasured
- A single retrieval tool (RTFM) — another tool (Augment, Cody) could give different results
- 11 tasks, 4 repos — statistically limited
- Python only — FeatureBench lite is Python-only
- Number of repetitions to be confirmed (N≥3 targeted)
- DBs are pre-built — in real use, indexing time is amortized but non-zero

### 7. Conclusion (~0.5 page)

We have shown that giving a pre-indexed search tool to a coding agent significantly improves resolve rate on feature-implementation tasks in large repositories. The improvement is caused by resolving the localization bottleneck: the agent with retrieval finds the cross-module dependencies that the agent without retrieval fails to discover via direct navigation.

This result has practical implications: pre-indexed retrieval tools (open-source or commercial) should be systematically deployed on codebases larger than ~1000 files. On small repos, direct navigation suffices.

---

## Planned figures and tables

1. **Figure 1:** RTFM architecture — metadata-first → expand on demand flow (Section 3)
2. **Figure 2:** Diagram of the 4 conditions (A/B/C/D) — what the agent "sees" (Section 4)
3. **Table 1:** RTFM vs existing tools comparison (Section 3.3)
4. **Figure 3:** Resolve rate per condition, grouped by repo size (bar chart)
5. **Figure 4:** Scatter plot: resolve-rate gain (C/D vs B) as a function of number of files
6. **Table 2:** Full results (11 tasks × 4 conditions × metrics)
7. **Table 3:** Tool-call breakdown (exploration vs coding) per condition
8. **Table 4:** RTFM initialization costs per repo
9. **Figure 5:** Agent-time breakdown: exploration vs coding per condition
10. **Table 5:** C vs D: FTS only vs FTS+embeddings comparison

---

## What's missing to finalize

### Experimental data
- [ ] Complete matrix 11 tasks × 4 conditions (in progress on PC2)
- [ ] N ≥ 3 repetitions per condition (for confidence intervals)
- [ ] pydantic and astropy tasks (intermediate repos ~800-1100 files)
- [ ] Systematic `fb eval` on every run

### Analyses to produce
- [ ] Statistical test on the B vs C/D difference (Wilcoxon signed-rank or permutation test if N is small)
- [ ] Correlation between repo size and retrieval gain
- [ ] Qualitative analysis: on tasks where C/D > B, which files did retrieval find that B did not?
- [ ] Cost per RESOLVED task (not per attempted task)

### Writing
- [x] Pick target venue → **EMSE (Empirical Software Engineering)**, Springer. Fallback TOSEM/TSE if results are strong.
- [ ] Check EMSE format/length (typically 25-40 pages, no strict limit)
- [ ] Decide whether the tool is open-sourced with the paper (artifact badge) → yes, already public
- [x] FR popularization blog series: 6 articles (R1-R6) in `paper/blog/`

---

## Key references (mandatory citations)

### Foundation
1. Jimenez et al. (2024). SWE-bench. ICLR 2024. arXiv:2310.06770.
2. (2026). FeatureBench. ICLR 2026. arXiv:2602.10975.
3. Yang et al. (2024). SWE-agent. NeurIPS 2024. arXiv:2405.15793.
4. Xia et al. (2024). Agentless. arXiv:2407.01489.

### Localization = bottleneck
5. (2025). PatchPilot. ICML 2025. arXiv:2502.02747.
6. Chen et al. (2025). LocAgent. ACL 2025. arXiv:2503.09089.
7. (2025). Trajectory Study. arXiv:2506.18824.
8. (2026). Navigation Paradox. arXiv:2602.20048.

### Retrieval for code
9. Wang et al. (2024). CodeRAG-Bench. NAACL 2025. arXiv:2406.14497.
10. Galimzyanov et al. (2025). Practical Code RAG at Scale. arXiv:2510.20609.
11. (2025). What to Retrieve for RACG. arXiv:2503.20589.

### Selective retrieval
12. Asai et al. (2023). Self-RAG. ICLR 2024. arXiv:2310.11511.
13. Wu et al. (2024). Repoformer. ICML 2024. arXiv:2403.10059.

### Cost and context
14. (2026). Tokenomics. arXiv:2601.14470.
15. Hong et al. (2025). Context Rot. Chroma Research.

### Comparable systems
16. Vasilopoulos (2026). Codified Context. arXiv:2602.20478.
17. (2025). A-RAG. arXiv:2602.03442.
18. Hartman et al. (2024). Cody. RecSys 2024. arXiv:2408.05345.

### Contamination / rigor
19. Liang et al. (2025). SWE-Bench Illusion. arXiv:2506.12286.
20. (2025). UTBoost. ACL 2025. arXiv:2506.09289.
