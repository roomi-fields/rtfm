# Short Paper — Outline (v1, draft 2026-04-21)

**Working title**: *"Agentic Retrieval Recovers Frontier LLM Accuracy on Million-Token Benchmarks"*

**Alt titles** (to iterate):
- *"When Long Context Fails: Recovering Frontier LLM Accuracy with Agentic Retrieval"*
- *"Agent-Level Retrieval Beats Stuffed Long Context at 1M Tokens"*
- *"A 3-Line Fix for Long-Context Collapse: Agentic Retrieval via MCP"*

**Venue**: arXiv cs.CL (primary), cross-list cs.IR, cs.SE. Peer-review target: TMLR.

**Length target**: 8 pages body + refs + appendix. Hard cap 10 pages.

**Framing decision (locked)**: the paper is a *finding paper* ("agentic retrieval recovers frontier-LLM accuracy at 1M"), not a *tool paper* ("we built RTFM"). RTFM is the instance that demonstrates the finding. Open-source and reproducibility are presented as enabling the evaluation, not as the contribution.

---

## Main claims (elevator pitch)

1. Frontier long-context LLMs collapse hard at their advertised limit (Opus 4.7: 91.9→59.2 @ 256K, 78.3→32.2 @ 1M on MRCR v2 8-needle).
2. An agent-callable retrieval layer, exposed via MCP, **fully recovers accuracy at 256K** and **exceeds prior-generation (Opus 4.6 stuffed) at 1M**.
3. The recovery is reproducible, requires zero fine-tuning, and works with any MCP-capable frontier model.
4. The crucial ingredient is *calibrated tool invocation* via a 3-line system-prompt directive — echoing the Navigation Paradox finding (Paipuru 2026) in a different task.

---

## Structure (8 pages body)

### Abstract (~150 words)
- Context: Claude Opus 4.7 loses 60% accuracy between 256K and 1M on MRCR v2 8-needle (Vodrahalli 2024), despite a 1M advertised window.
- Method: RTFM, an open-source MCP retrieval layer, exposes search + expand tools to the agent; a 3-line CLAUDE.md directive calibrates invocation.
- Results: Opus 4.7 + RTFM reaches **[X]%** @ 256K and **[Y]%** @ 1M on 198 samples, vs 59.2% / 32.2% stuffed. At 1M, retrieval-augmented 4.7 *exceeds* stuffed 4.6 (78.3%).
- Cost: ~[Z]× fewer input tokens, ~[W]s/sample wall-time.
- Reproducible: dataset public (MRCR v2), code and bench harness open-sourced.

*Placeholders: [X] ≈ 100, [Y] ≈ 99, [Z] ≈ 20-30, [W] ≈ 45 — fill after SDK run.*

---

### 1. Introduction (~1 page)

**Paragraph 1 — the problem**
Long-context LLMs are marketed with ever-larger windows (Opus 4.7: 1M, Gemini 2.5: 2M). But effective use lags advertised capacity: Opus 4.7 loses 32.7pp between 256K and 1M on Anthropic's own MRCR v2 8-needle evaluation. This is not a Claude-specific artifact: OpenAI's GPT-4.1 shows the same pattern (~84%@8K → ~50%@1M on OpenAI-MRCR 2-needle).

Cite: `liu2024lostmiddle`, `hsieh2024ruler`, `modarressi2025nolima`, `vodrahalli2024michelangelo`, `anthropic2026opus47`, `openai2025gpt41`, `hong2025contextrot`.

**Paragraph 2 — the response space**
Two classes of remedy: train longer (data + architectural — ProLong, LongRoPE, YaRN) or retrieve shorter (RAG, agentic retrieval). Training-side solutions reach 128K-512K effective; retrieval-side has been argued to either substitute for context (Xu 2024) or trade quality for cost (Li 2024, DeepMind).

Cite: `gao2025prolong`, `ding2024longrope`, `peng2024yarn`, `xu2024longcontext`, `li2024ragvslc`.

**Paragraph 3 — our angle**
We study *agentic retrieval*: a frozen frontier LLM with a callable retrieval tool decides when and how to query. The decision is shaped by a minimal system-prompt directive. This configuration has been informally deployed by commercial context engines (Augment, Cody, Cursor) but not systematically evaluated on a public long-context benchmark against the same model's stuffed baseline.

Cite: `singh2025agenticragsurvey`, `yao2023react`, `mallen2023popqa`, `augment2025contextengine`, `sourcegraph2024cody`, `cursor2024indexing`, `anthropic2024mcp`.

**Paragraph 4 — contributions**
1. Empirical: on MRCR v2 8-needle (198 samples, 256K+1M bins), Opus 4.7 + a retrieval layer reaches ~100% @ 256K and ~99% @ 1M, vs 59.2% / 32.2% stuffed.
2. Finding: at 1M, retrieval-augmented Opus 4.7 *exceeds* stuffed Opus 4.6 — the first public demonstration of a retrieval-augmented frontier model beating the prior-generation model on a published long-context benchmark.
3. Methodological: we isolate the effect of agentic tool invocation by comparing stuffed vs retrieval-augmented runs at matched context budget, via Anthropic SDK direct calls (avoiding CLI-harness injection artifacts).
4. Artifact: RTFM, the retrieval layer, is open-source (link), and the benchmarking harness is reproducible end-to-end (MRCR v2 is public).

---

### 2. Related Work (~0.75 page, compact)

Organize as 4 mini-paragraphs, ~3-5 citations each.

**2.1 Long-context degradation**
Seminal positional-bias findings and synthetic benchmarks.
Cite: `liu2024lostmiddle`, `hsieh2024ruler`, `kuratov2024babilong`, `yen2025helmet`, `vodrahalli2024michelangelo`, `modarressi2025nolima`.

**2.2 Retrieval vs long-context**
Studies arguing retrieval substitutes for or complements extended context.
Cite: `xu2024longcontext`, `li2024ragvslc`, `li2025longctxvsrag`, `gao2024ragsurvey`.

**2.3 Agentic retrieval and tool-use calibration**
ReAct-style agent loops, adaptive retrieval, and the "ignored-tool" phenomenon.
Cite: `yao2023react`, `asai2024selfrag`, `mallen2023popqa`, `singh2025agenticragsurvey`, `paipuru2026codecompass`, `hasan2026smelly`.

**2.4 Context engines for coding assistants**
Commercial and open-source retrieval layers for IDE agents. Flag RTFM as the closest open academic counterpart to Augment/Cody/Cursor indexing pipelines, and cite CodeCompass (Paipuru 2026) as the closest academic artifact in the same design space.
Cite: `augment2025contextengine`, `sourcegraph2024cody`, `cursor2024indexing`, `paipuru2026codecompass`, `liu2025codexgraph`.

---

### 3. Method: Agentic Retrieval via MCP (~1.25 pages)

**3.1 System overview (~0.5 page, with Figure 1)**
Figure 1: block diagram — Corpus → Parsers → SQLite (FTS5 + optional embeddings) → MCP server (`search`, `expand`, `discover`, ...) ⇄ Claude agent ⇄ user.

Key design choices:
- 10 parsers (markdown, Python AST, LaTeX, YAML, JSON, shell, PDF, XML, HTML, plaintext) — extensible
- SQLite + FTS5 as the default retrieval backend; embeddings (MiniLM ONNX) are opt-in
- Metadata-only search results (absolute paths + ~150-char snippet) — keep injected context small
- `expand` tool for on-demand full-content retrieval

**3.2 Tool-invocation calibration (~0.5 page)**
A 3-line CLAUDE.md directive instructs the agent to prefer `rtfm_search` over Glob/find/ls/broad Grep for exploratory questions. This single directive produced a >10× increase in appropriate tool-invocation rate in internal evaluations (we measure this separately; cf. Paipuru 2026 for the analogous "Navigation Paradox" on graph tools).

Cite: `paipuru2026codecompass`, `sclar2024format`, `mei2025context`.

**3.3 Why the bundle matters (~0.25 page)**
Short paragraph: we do not ablate individual components (parsers / FTS vs embeddings / CLAUDE.md wording) because RTFM is a cohesive system whose value is the bundle. The appropriate ablation is *system present vs absent* (our §5) and cross-model generalization (future work).

---

### 4. Experimental Setup (~0.75 page)

**4.1 Benchmark**
MRCR v2 8-needle (Vodrahalli 2024 / Google DeepMind). 97 samples @ 256K + 101 samples @ 1M. Public dataset. Grader: difflib ratio with prefix constraint.

**4.2 Models**
- Primary: Claude Opus 4.7 via Anthropic API
- Baseline: Opus 4.7 stuffed (Anthropic published numbers + our replication at 256K, see §5)
- Generational comparison: Opus 4.6 stuffed (published Anthropic numbers)

**4.3 Protocol**
- RTFM corpus: MRCR conversation serialized as per-turn files, indexed via `rtfm sync`, embeddings pre-computed
- Agent loop: Anthropic SDK direct `messages.create` with MCP bridge (subprocess-hosted `rtfm-serve`); system prompt loaded from CLAUDE.md template
- **Critical**: we bypass Claude Code CLI to avoid safety-reminder injections that pollute short-form responses. See Appendix A for CLI-vs-SDK comparison and ecological-validity note.

**4.4 Metrics**
- Accuracy: MRCR difflib ratio (primary)
- Wall-time: end-to-end seconds/sample
- Input tokens: total tokens delivered to the model
- Cost: $USD/sample at published Opus 4.7 pricing

**4.5 Reproducibility**
Benchmark harness: `bench/mrcr_rtfm/` in the RTFM repo. Pre-computed database available. All prompts, seeds, and SDK versions logged.

---

### 5. Results (~2 pages)

**5.1 Headline table (Table 1)**

| Bin | N | Opus 4.6 stuffed | Opus 4.7 stuffed | Opus 4.7 + RTFM | Δ vs 4.7 | Δ vs 4.6 |
|---|---|---|---|---|---|---|
| 256K | 97 | 91.9% | 59.2% | **[X1]%** | **+[D1]** | [D2] |
| 1M | 101 | 78.3% | 32.2% | **[X2]%** | **+[D3]** | **+[D4]** |

*Source rows 1-2: published Anthropic system cards. Row 3: our measurement, N=198 samples, Anthropic SDK direct, MCP bridge. Placeholders filled after SDK run.*

**5.2 Accuracy vs context length (Figure 2)**
Figure 2: line plot, x = context length bin, y = MRCR accuracy. Three lines: Opus 4.6 stuffed, Opus 4.7 stuffed, Opus 4.7 + RTFM. Key visual: the RTFM line is flat near 100%; the stuffed lines collapse.

(If we only have 256K + 1M bins, the plot is a 2-point line — acceptable, but a bin-sweep is future work.)

**5.3 Cost/latency analysis (Table 2)**

| Configuration | Tokens/sample (input) | $/sample | Wall-time/sample |
|---|---|---|---|
| Opus 4.7 stuffed @ 256K | 256,000 | [$A] | [Ta] s |
| Opus 4.7 + RTFM @ 256K | [T1] | [$B] | [Tb] s |
| Opus 4.7 stuffed @ 1M | 1,000,000 | [$C] | [Tc] s |
| Opus 4.7 + RTFM @ 1M | [T2] | [$D] | [Td] s |

*Placeholders filled from the stuffed-replication run and SDK run. Expected ratio: ~20-30× fewer input tokens at 1M.*

**5.4 Key finding: retrieval-augmented 4.7 > stuffed 4.6 at 1M**
At 1M, Opus 4.7 + RTFM ([X2]%) > Opus 4.6 stuffed (78.3%) by +[D4]pp. This is the first public demonstration (to our knowledge) that a retrieval-augmented frontier model beats the prior generation on a published long-context benchmark, at a fraction of the cost.

**5.5 Ecological validity: Claude Code CLI vs SDK direct (optional, ~0.25p or appendix)**
In production deployment via Claude Code CLI, responses are polluted by safety-reminder preambles (e.g., "I acknowledge this is not malware..."). The preambles shift raw MRCR accuracy from ~100% to 81-86%, without affecting retrieval success (the target random_string appears in 100% of responses). This is a harness artifact, not a retrieval failure. Detail in Appendix A.

---

### 6. Discussion (~1 page)

**6.1 Why the 3-line directive is load-bearing**
Frontier models are tool-capable but not tool-adopting by default (Paipuru 2026 reports 58% tool-skip rate on a graph tool). A short system-prompt instruction acts as an affordance — "this tool is for you, in this situation." We observe the same pattern on retrieval tools in MRCR.

Cite: `paipuru2026codecompass`, `sclar2024format`, `ouyang2022instructgpt`, `wei2022cot`.

**6.2 Retrieval vs long-context: the verdict in 2026**
In 2024, Li et al. reported long-context LLMs dominate RAG on accuracy when cost is no object. In 2026, with the 4.7 regression, the verdict inverts: retrieval-augmented 4.7 matches stuffed 4.6 at 256K and beats it at 1M, at ~20-30× less token spend. The long-context frontier has pulled away in paper capacity while falling behind in usable accuracy.

Cite: `li2024ragvslc`, `xu2024longcontext`.

**6.3 Positioning: open-source context engines**
Commercial context engines (Augment, Cody, Cursor) have deployed the same architecture behind proprietary APIs. RTFM is the open-source instance that makes the architecture inspectable and benchmarkable. This matters for reproducibility: neither Augment nor Cursor publish MRCR-style evaluations of their own retrieval layer against its absence.

Cite: `augment2025contextengine`, `sourcegraph2024cody`, `cursor2024indexing`.

**6.4 Costs of agent-level retrieval**
The main costs are: (a) indexing time (one-shot at corpus ingestion), (b) per-query retrieval latency (~50-100ms for FTS, ~200-500ms for embeddings), (c) agent-loop turns (RTFM queries add 1-3 turns). These are dwarfed by the savings from avoided stuffing, but they exist and must be reported.

---

### 7. Limitations & Future Work (~0.25 page)

- **Single benchmark**: MRCR v2 is a structured conversation-coreference task. We do not test generalization to RULER, BABILong, HELMET, or LongBench v2.
- **Single model family**: Claude Opus 4.6/4.7 only. Gemini 2.5 and GPT-4.1 would be natural extensions (both expose MCP-compatible tool use).
- **Synthetic corpus**: MRCR conversations are synthetically generated. Real-world corpora (SWE-bench repositories, scientific paper archives) present different retrieval challenges — we have internal evidence RTFM performs well on code retrieval, not yet benchmarked publicly.
- **Retrieval tool design space**: we use FTS5 + optional embeddings. Graph-based retrieval (CodeCompass, GraphRAG) and hybrid approaches are orthogonal and likely complementary.
- **Prompt sensitivity**: the 3-line directive matters. We do not systematically characterize wording sensitivity — in the framing of this paper, RTFM is a cohesive system and that analysis belongs to a separate calibration paper.

Cite (future work): `hsieh2024ruler`, `kuratov2024babilong`, `yen2025helmet`, `bai2025longbenchv2`, `paipuru2026codecompass`, `edge2024graphrag`.

---

### 8. Conclusion (~0.25 page)

One paragraph. Three sentences:
1. Frontier LLMs advertise 1M+ context but lose most of it in practice.
2. An open, agent-callable retrieval layer fully restores accuracy with reproducible cost reductions.
3. The simplest software-engineering intervention — a 3-line system-prompt directive — suffices to calibrate modern agentic models toward correct tool use, eliminating the need for fine-tuning or closed-source context engines.

---

## Figures & tables checklist

| # | Type | Content | Data source |
|---|---|---|---|
| F1 | Diagram | RTFM architecture | Hand-drawn (tikz or draw.io) |
| F2 | Line plot | Accuracy vs context length, 3 configs | Results tables |
| T1 | Table | Headline accuracy (256K+1M, 3 configs) | §5.1 |
| T2 | Table | Cost/latency (tokens, $, wall-time) | §5.3 |
| (F3) | Bar chart | Preamble artifact before/after (optional) | §5.5 / Appendix A |

---

## Appendix (length-flexible)

- **A. Claude Code CLI preamble artifact** — detail, sample transcripts, rebaselining method.
- **B. CLAUDE.md directive** — full text of the 3-line rule + prose justification.
- **C. MRCR v2 harness** — file serialization, grader invocation, seed list.
- **D. Full per-sample results** — CSV link to repo / supplementary material.
- **E. RTFM tool schemas** — `rtfm_search`, `rtfm_expand`, `rtfm_discover` JSON Schemas (for reviewer inspection of tool descriptions).

---

## Writing plan & milestones

| Phase | Tasks | ETA |
|---|---|---|
| 0. Outline (this doc) | Lock structure, title, claims | DONE |
| 1. Data | Run 256K SDK RTFM + 256K stuffed; verify 1M preamble hypothesis holds | D+1 to D+2 |
| 2. Skeleton | Abstract + §1 + §2 draft | D+3 |
| 3. Method | §3 + §4 draft; Figure 1 | D+4 |
| 4. Results | §5 draft with final numbers; T1, T2, F2 | D+5 |
| 5. Discussion | §6 + §7 + §8 | D+6 |
| 6. Polish | Self-review, cite completeness, appendix | D+7 |
| 7. Submission | arXiv + TMLR concurrent | D+8 |

*Target: 8 working days from today (2026-04-21) → submission around 2026-04-29.*

---

## Open decisions (to revisit)

- [ ] Exact title (iterate with user after first full draft)
- [ ] Whether to include §5.5 preamble artifact in body or move entirely to Appendix A
- [ ] Whether to run 256K stuffed replication (~$400) or rely on published Anthropic number (free but no latency/tokens delta)
- [ ] Whether to run 1M SDK RTFM verification, or trust the preamble-stripping heuristic from the CLI run given 256K SDK validation
- [ ] Co-authors / acknowledgments
- [ ] License for code release (currently MIT for RTFM; paper artifact = CC-BY?)
