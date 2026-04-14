# RTFM — Backlog

Everything identified as a future direction, sorted by priority.

---

## P0 — Benchmark in progress (EMSE paper)

### Missing runs
- [ ] Complete matrix 11 tasks × 4 conditions (A/B/C/D)
- [ ] N ≥ 3 repetitions per condition (statistical significance)
- [ ] pydantic (771 files) and astropy (1,123 files) tasks — intermediate repos to locate the threshold
- [ ] Systematic `fb eval` on every run
- [ ] Re-run Config B for serialization and responses_agent (previously failed)

### Analyses to produce
- [ ] Statistical tests (Wilcoxon signed-rank or permutation test)
- [ ] Confidence intervals on resolve rate, cost, duration
- [ ] Correlation repo size × retrieval gain (scatter plot)
- [ ] Qualitative analysis: on every task where C/D > B, which files did retrieval find that B did not?
- [ ] Cost per RESOLVED task (not per attempt)

### Paper writing
- [ ] Check EMSE format/length (typically 25-40 pages)
- [ ] Full writing (v3 plan in `paper/paper_plan.md`)
- [ ] Figures and tables (10 planned, see paper_plan.md §Figures)
- [ ] Artifact badge (RTFM already public on PyPI/GitHub)

---

## P1 — Product features (next version)

### Dependency-graph navigation
- `edges(source_slug, target_slug, relation_type)` table in SQLite
- Each parser extracts relations at `sync` time:
  - Python: `import`, `from ... import`
  - LaTeX: `\cite{}`, `\ref{}`, `\input{}`
  - Legifrance XML: `<LIEN>`
  - Markdown: `[[wikilinks]]`, `[links](relative.md)`
  - YAML/JSON: `$ref`
- Enriched `rtfm_search` mode: "also give me the files linked to this result"
- Zero Neo4j — everything in the same SQLite
- Inspired by Navigation Paradox (arXiv:2602.20048): graph = +23.2pp on hidden dependencies, FTS = zero benefit on this type
- Graph and embeddings are complementary: embeddings = semantic similarity between chunks, graph = structural links between files

### Smart filtering at indexing time
- Exclude vendored, tests, generated code, node_modules, .git
- Selectively index large repos (> 2000 files) — only key directories
- Would reduce noise on large repos (issue identified in the 10-task benchmark)

### Performance: `rtfm_expand` with `count=0`
- When `count=0` (all chunks), `_render_chunk` is called N times, each re-reading the entire file via `_read_raw_lines` then slicing it
- Optimization: read the file once and slice for each chunk
- Not critical for files < 1 MB, but perf issue on large files (> 1 MB, > 50 chunks)
- Identified in the technical debt analysis of `mcp.py`

### Search-results improvements
- Limit default results (top 3 instead of top 5+)
- Dedup by filename (deployed but not stress-tested)
- Better ranking: weight by freshness, centrality in the graph

### Retrieval quality improvements (identified during MemPalace analysis)
- **Better default embedding model**: current `paraphrase-multilingual-MiniLM-L12-v2` is light but limited. Switching to `BAAI/bge-small-en` or `nomic-embed-text-v1.5` = measured +10-15pp on retrieval benchmarks
- **Cross-encoder reranking**: after FTS+embeddings, rescore the top-20 with a more precise model = +5-10pp
- **Query expansion**: reformulate the query into variants via LLM before search, then merge results
- Benchmark on LongMemEval to measure honestly against MemPalace (96.6% recall@5 baseline)

---

## P2 — Cross-project indexing of Claude memories

### Index the full memory directory of each project
- `~/.claude/projects/*/memory/` (the whole directory, not just MEMORY.md)
- Contains: MEMORY.md + thematic files (benchmark_paper.md, featurebench.md, worknotes, analyses...)
- Also: each project's `CLAUDE.md` (conventions, architecture, decisions)
- Cross-project search: "how did I handle OAuth?" → searches across all projects
- Auto-discovery of Claude projects via `~/.claude/projects/`

### Versioning of all memory files
- On every sync, if content has changed, keep the previous version
- `file_versions(slug, version_num, content_hash, timestamp, content)` table
- Enables: "what did we know about X three weeks ago?"
- Also enables: "what changed in benchmark_paper.md between yesterday and today?"
- No competing tool does this — differentiating feature
- The diff between versions could be exposed via MCP: `rtfm_history(slug)`

### Dedicated command
- `rtfm memory`: indexes + versions all `~/.claude/projects/*/memory/` cross-project
- `rtfm memory --history <slug>`: view the history of a memory file

---

## P3 — Extended benchmark (mid term)

### Multi-model
- [ ] Test with GPT-4, Gemini 2.5 Pro, Claude Opus, open-source models
- [ ] Measure whether selective retrieval capability varies by model
- [ ] Do more capable models benefit more or less from retrieval?

### Multi-tool
- [ ] Test with Augment Context Engine, Sourcegraph Cody (if API available)
- [ ] Is the metadata-first pattern crucial, or would any tool do?

### Multi-language
- [ ] Full FeatureBench (GPU tasks) — not just Python
- [ ] Does the localization bottleneck exist the same way in Java, TypeScript, Rust?

### Standardized benchmark
- [ ] Extend to SWE-bench for comparability with the literature
- [ ] SWE-bench Verified (500 instances, ground truth validated by humans)

### Real-world conditions
- [ ] Measure impact outside a benchmark, on daily development tasks
- [ ] Longitudinal study: does the agent improve as the index grows?

---

## P4 — Exploratory research (long term)

### Proactive retrieval
- The tool could pre-load relevant context before the agent even searches
- Automatic context injection at session start based on the prompt
- Risk: context rot if poorly calibrated (Hong et al. 2025)

### Retrieval × context-size interaction
- Do wider context windows (1M+ tokens) make retrieval obsolete?
- Navigation Paradox says no: the problem is salience, not capacity
- Measure empirically with 200K vs 1M token models

### Multi-source retrieval
- Combine project content (code, docs) with external docs (Context7, official docs)
- RTFM for the project, Context7 for third-party libs — automatic orchestration

### Community parsers
- Extensible architecture already in place (~50 lines per parser)
- Missing parsers identified: TypeScript/JSX, Rust, Go, Java, C/C++, SQL, Jupyter notebooks, DOCX, CSV/Excel
- Marketplace or registry of community parsers

### Multi-tool agent
- Combine graph (structural dependencies) + FTS (text search) + embeddings (semantic similarity) in a single smart `rtfm_search`
- The agent doesn't need to choose the mode — the system routes automatically
- Cf. Adaptive-RAG (Jeong et al., NAACL 2024) but without a trained classifier

---

## P5 — Blog articles fixes (R series)

### R5 — Done (2026-03-01)
- [x] Fixed the false statement "nothing in the prompt tells it to use RTFM"
- [x] Reframed: light guidance (3 lines of CLAUDE.md) + emergent calibration of intensity

### R6 — To update
- [ ] §5 "The agent naturally does selective retrieval" → align with corrected R5 (light guidance, not zero instruction)
- [ ] "Do not add an 'ALWAYS use RTFM' instruction" → nuance (3 lines of orientation ≠ forcing systematic retrieval)
- [ ] "It's not a GPS that dictates the route" → keep the metaphor but add "we show it the map"

### Integrate Navigation Paradox into R2
- [ ] Complete the CodeCompass vs RTFM comparison: graph vs text, mono-domain vs multi
- [ ] Mention that their tool is not distributed (0 stars, research prototype)
- [ ] Add the 58% zero-call finding → RTFM solves it with 3 lines of CLAUDE.md

---

## Loose ideas

- CLAUDE.md template: add "search once, then code" instead of "search on every doubt" (would reduce overhead on large repos)
- Usage metrics: how many `rtfm_search` calls per session in real use (not benchmark)
- Dashboard: visualize the index (files, chunks, relations, coverage) via a local web page
- `rtfm why <file>`: explain why a file is in the results (score breakdown)
- `rtfm graph <file>`: show a file's dependencies (once the graph is implemented)
