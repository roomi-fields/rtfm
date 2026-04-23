# Related Work — SOTA survey (draft, unselected)

> Consolidated from a 5-axis literature sweep (2026-04-21). ~115 unique
> entries in `refs.bib`. Each paper lists a 2-line contribution + a 1-line
> *"how we connect"* tag. **Nothing here has been selected for the short
> paper yet** — this is the candidate pool.
>
> Papers that naturally sit in multiple axes are filed in their primary
> axis with cross-refs noted (→ Axis X) at the end.

---

## Axis 1 — Long-context degradation (the problem)

### 1.1 Canonical degradation findings

- **`liu2024lostmiddle`** — Lost in the Middle: How Language Models Use Long
  Contexts (TACL 2024). *U-shaped positional bias: accuracy peaks at start/end,
  collapses mid-context, even on long-context-trained models.*
  **Connect**: the foundational "long ≠ effectively used" citation.

- **`levy2024same`** — Same Task, More Tokens (ACL 2024). *FLenQA isolates
  length from content: reasoning degrades monotonically between 250 and 3000
  tokens, far below advertised context windows.*
  **Connect**: justifies keeping RTFM-injected context short (<5K) even on a
  1M-capable model.

- **`peysakhovich2023attention`** — Attention Sorting Combats Recency Bias
  (2023). *RoPE-based models exhibit recency bias; iterative attention-
  weighted re-sorting counteracts.*
  **Connect**: motivates why stuffing at 1M fails while short ordered
  retrieval works.

- **`hong2025contextrot`** — Context Rot (Chroma Research tech-report, Jul
  2025). *18 frontier models (incl. Opus 4, Gemini 2.5, GPT-4.1) all degrade
  well before nominal limits. Coins "context rot".*
  **Connect**: industry-facing citation; non-peer-reviewed but covers Opus 4
  directly.

- **`chiang2024foundmiddle`** — Found in the Middle (2024). *Inference-time
  attention-calibration partially closes the LitM gap.*
  **Connect**: positions RTFM as retrieval-based alternative to attention
  surgery. *Optional.*

### 1.2 Synthetic long-context benchmarks

- **`kamradt2023niah`** — Needle in a Haystack (GitHub, Nov 2023). *Single-
  needle recall smoke test; de facto long-context sanity check since 2023.*
  **Connect**: direct ancestor of MRCR.

- **`hsieh2024ruler`** — RULER (COLM 2024). *Multi-key/value/hop/aggregation
  NIAH; half of "32K+" models fail at 32K.*
  **Connect**: sibling benchmark; we adopt MRCR for strictness but RULER is
  the obvious methodological comparator.

- **`kuratov2024babilong`** — BABILong (NeurIPS DB 2024). *bAbI reasoning
  embedded in up to 10M PG19 tokens; LLMs effectively use 10-20% of context.*
  **Connect**: quantifies the "effective context" ceiling we hit on Opus 4.7.

- **`yen2025helmet`** — HELMET (ICLR 2025). *7 application-centric categories
  up to 128K; NIAH does NOT predict downstream long-context performance.*
  **Connect**: justifies moving beyond single-task NIAH-style tests.

- **`bai2024longbench`** — LongBench v1 (ACL 2024). *21 datasets × 6 tasks
  bilingual EN/ZH, avg 6.7K words.*
  **Connect**: lineage citation for multi-task long-context evaluation.

- **`bai2025longbenchv2`** — LongBench v2 (ACL 2025). *503 MCQs 8K-2M words;
  best model 50.1%, humans 53.7%.*
  **Connect**: reasoning-over-retrieval complement to MRCR.

- **`zhang2024infinitebench`** — ∞Bench / InfiniteBench (ACL 2024). *First
  benchmark with avg length >100K.*
  **Connect**: "beyond-100K" generation benchmark, part of the family.

- **`yuan2024lveval`** — LV-Eval (2024). *5 length tiers 16K→256K with
  confusing-fact insertion.*
  **Connect**: covers the exact 256K regime of our Opus 4.7 cliff.

- **`an2024leval`** — L-Eval (ACL 2024, Outstanding Paper). *20 sub-tasks,
  508 long docs, 2K+ human-labeled 3K-200K pairs.*
  **Connect**: historical comparator; advocates LIE evaluation over n-gram.

- **`song2024countingstars`** — Counting-Stars (2024). *Multi-evidence,
  position-aware, scalable; explicitly designed against NIAH saturation.*
  **Connect**: direct intellectual ancestor of multi-needle MRCR.

- **`modarressi2025nolima`** — NoLiMa (ICML 2025). *NIAH without lexical
  overlap; 10/12 models drop to half short-context accuracy at 32K.*
  **Connect**: strongest 2025 evidence that degradation ≠ solved by scale.

- **`shaham2023zeroscrolls`** — ZeroSCROLLS (Findings EMNLP 2023). *10 tasks
  over SCROLLS + aggregation; zero-shot only.* *Optional — tangential.*

- **`dong2023bamboo`** — BAMBOO (2023). *10 datasets × 5 tasks, 4K/16K tiers,
  contamination-controlled.* *Optional — tangential.*

- **`karpinska2024nocha`** — NoCha (2024). *1001 true/false claim pairs over
  67 recent novels; GPT-4o 55.8%.*
  **Connect**: global narrative reasoning complement. *Optional.*

- **`li2024needlebench`** — NeedleBench (2024). *Decouples retrieval from
  reasoning at 1M.* *Optional.*

### 1.3 MRCR specifically

- **`vodrahalli2024michelangelo`** — Michelangelo (Google DeepMind, NeurIPS
  2024). *Introduces Latent Structure Queries (LSQ) framework; MRCR v1 is one
  of three LSQ tasks.*
  **Connect**: **cornerstone citation — defines our benchmark**.

- **`openai2025mrcr`** — OpenAI-MRCR dataset (HuggingFace, 2025). *OpenAI's
  public 2/4/8-needle variant used at GPT-4.1 launch. GPT-4.1 drops ~84%@8K
  to ~50%@1M on 2-needle.*
  **Connect**: cross-lab evidence that MRCR degradation generalizes beyond
  Anthropic models.

### 1.4 System cards / technical reports

- **`anthropic2026opus47`** — Claude Opus 4.7 System Card (Anthropic, Apr
  2026). *Reports the 91.9→59.2 @ 256K and 78.3→32.2 @ 1M regressions we
  study.*
  **Connect**: primary data source for the paper.

- **`anthropic2026opus46`** — Claude Opus/Sonnet 4.6 System Card (Anthropic,
  Feb 2026). *Prior-generation baseline.*
  **Connect**: required for Δ computation.

- **`gemini2024v15`** — Gemini 1.5 technical report (Google, 2024). *Near-
  perfect NIAH to 10M tokens — pioneering million-token claim.*
  **Connect**: framing citation (industry narrative that MRCR rebuts).

- **`openai2025gpt41`** — GPT-4.1 launch (OpenAI, Apr 2025). *Documents
  MRCR-shaped degradation on OpenAI models.*
  **Connect**: cross-vendor confirmation. *Supporting.*

### 1.5 Theoretical / architectural analyses

- **`xiao2024streamingllm`** — Streaming LLMs / attention sinks (ICLR 2024).
  *Attention-sink phenomenon: disproportionate attention on initial tokens.*
  **Connect**: architectural explanation for middle-token under-attention.

- **`chen2023pi`** — Positional Interpolation (Meta, 2023). *Seminal RoPE
  interpolation; extends LLaMA to 32K with minimal fine-tuning.*
  **Connect**: "make the window bigger" lineage.

- **`peng2024yarn`** — YaRN (ICLR 2024). *Improved RoPE extension.*
  **Connect**: same lineage.

- **`ding2024longrope`** — LongRoPE (ICML 2024, Microsoft). *Non-uniform
  RoPE rescaling to 2M+ tokens.*
  **Connect**: shows hardware-feasible 2M+ windows exist — quality, not
  capacity, is the binding constraint.

- **`fu2024dataengineering`** — Data Engineering for 128K (2024). *500M-5B
  tokens with domain balance + length upsampling suffice for 128K.*
  **Connect**: training-side remedies exist but orthogonal to inference
  degradation.

- **`gao2025prolong`** — ProLong (ACL 2025). *ProLong-8B; SOTA 128K with
  effective use to 512K.*
  **Connect**: best-practice long-context training, complements retrieval.

---

## Axis 2 — Retrieval-augmented & agentic retrieval (the solution class)

### 2.1 Seminal RAG

- **`lewis2020rag`** — RAG (NeurIPS 2020). *Introduces term; end-to-end DPR +
  seq2seq fine-tuned jointly.*
  **Connect**: canonical paradigm reference. RTFM is *agentic tool-level RAG*
  — frozen model, retrieval as callable tool.

- **`guu2020realm`** — REALM (ICML 2020). *Retrieval-augmented pretraining
  with learnable knowledge retriever.*
  **Connect**: opposite pole from RTFM (baked-in vs swappable-tool).

- **`izacard2021fid`** — Fusion-in-Decoder (EACL 2021). *Encode N passages
  independently; concat in decoder.*
  **Connect**: "static k" baseline; motivates dynamic agent-controlled k.

- **`borgeaud2022retro`** — RETRO (DeepMind, ICML 2022). *Chunk retrieval
  into frozen BERT; 7.5B matches GPT-3 175B.*
  **Connect**: retrieval-as-scale-replacement evidence.

- **`khattab2020colbert`** — ColBERT (SIGIR 2020). *Late-interaction neural
  IR; token-level BERT + MaxSim.*
  **Connect**: justifies lightweight bi-encoder + BM25 default.

- **`izacard2023atlas`** — Atlas (JMLR 2023). *Joint retriever-encoder-decoder
  pretraining; 11B beats PaLM 540B on NQ with 64 shots.*
  **Connect**: another "retrieval baked into training" baseline.

- **`ram2023incontextralm`** — In-Context RALM (TACL 2023). *Prepend retrieved
  docs with no fine-tuning; off-the-shelf retrievers + frozen LM.*
  **Connect**: mechanically closest baseline — RTFM is "agentic
  In-Context RALM."

### 2.2 Tool use & ReAct lineage

- **`yao2023react`** — ReAct (ICLR 2023). *Interleaved thought/action/
  observation trace.*
  **Connect**: **Claude Code's execution paradigm**. Our CLAUDE.md biases
  the "action" choice at each ReAct step.

- **`schick2023toolformer`** — Toolformer (NeurIPS 2023, Meta). *Self-
  supervised training to insert API calls.*
  **Connect**: training-time tool-learning; contrast to RTFM's inference-
  time prompt approach.

- **`qin2024toolllm`** — ToolLLM (ICLR 2024 Spotlight). *ToolBench (16k
  RapidAPI APIs) + ToolLLaMA.*
  **Connect**: broad-tool-selection upper bound; RTFM argues for small well-
  documented toolset instead.

- **`patil2024gorilla`** — Gorilla (NeurIPS 2024). *Fine-tunes LLaMA on
  HuggingFace/TorchHub/TensorFlow APIs with retrieval-awareness.*
  **Connect**: "retrieval helps tool invocation" on the API side; `rtfm_discover`
  is the corpus analogue.

- **`tang2023toolalpaca`** — ToolAlpaca (2023). *Multi-agent simulation to
  synthesize tool-use traces.* *Optional.*

- **`mialon2023augmented`** — Augmented Language Models Survey (TMLR 2023,
  Meta). *Defines Augmented LMs; heuristic vs learned augmentation.*
  **Connect**: anchors RTFM in heuristic-augmentation branch.

### 2.3 Advanced RAG

- **`asai2024selfrag`** — Self-RAG (ICLR 2024 Oral). *Reflection tokens
  decide when to retrieve and rate utility.*
  **Connect**: same intuition as CLAUDE.md calibration but via training.
  Contrast section.

- **`yan2024crag`** — CRAG (2024). *Retrieval evaluator with web-fallback;
  plug-and-play on any RAG.*
  **Connect**: RTFM pushes correction earlier via agent-in-the-loop —
  subsumes CRAG's evaluator.

- **`yu2024chainofnote`** — Chain-of-Note (EMNLP 2024). *Per-document notes
  before answering; +7.9 EM on noisy retrievals.*
  **Connect**: RTFM's metadata-only results let agent note-and-skip cheaply.

- **`gao2023hyde`** — HyDE (ACL 2023). *Generate hypothetical answer, embed,
  retrieve; beats Contriever zero-shot.*
  **Connect**: future-work query-rewriting for discovery searches.

- **`sarthi2024raptor`** — RAPTOR (ICLR 2024). *Recursive cluster+summarize
  tree; multi-resolution retrieval; +20pp QuALITY.*
  **Connect**: hierarchy-via-summarization vs RTFM's hierarchy-via-syntax.

- **`edge2024graphrag`** — GraphRAG (Microsoft, 2024). *Entity graph +
  community summaries for global sensemaking.*
  **Connect**: `rtfm_graph` roadmap mirrors intuition — structural edges
  complement FTS/embeddings.

- **`gao2024ragsurvey`** — RAG Survey (2024). *Dominant survey; Naive/
  Advanced/Modular RAG taxonomy.*
  **Connect**: positions RTFM as Modular RAG with agent orchestration.

### 2.4 Agentic retrieval & "when to call tools"

- **`singh2025agenticragsurvey`** — Agentic RAG Survey (2025). *First
  comprehensive agentic-RAG survey; taxonomy by cardinality/control/autonomy.*
  **Connect**: **primary positioning reference** — RTFM sits in the single-
  agent/tool-based/autonomous quadrant.

- **`jin2025searchr1`** — Search-R1 (2025). *RL-trained LM interleaves
  queries with reasoning; +41% vs RAG (Qwen2.5-7B).*
  **Connect**: direct training-cost vs prompt-cost contrast.

- **`jiang2023flare`** — FLARE (EMNLP 2023). *Retrieve on confidence drop;
  next-sentence probability as trigger.*
  **Connect**: "implicit" when-to-retrieve vs RTFM's explicit agent decision.

- **`mallen2023popqa`** — PopQA / When Not to Trust LMs (ACL 2023).
  *Retrieval helps on long-tail, hurts on head entities — empirical basis
  for adaptive retrieval.*
  **Connect**: **foundational "don't always retrieve" citation** —
  justifies CLAUDE.md calibration.

### 2.5 Hybrid retrieval & evaluation

- **`bruch2023fusion`** — Fusion Functions for Hybrid Retrieval (TOIS 2023).
  *Formal RRF vs convex combination; convex often wins.*
  **Connect**: supports RTFM's FTS-first + opt-in dense stance.

- **`thakur2021beir`** — BEIR (NeurIPS DB 2021). *18-dataset zero-shot IR;
  BM25 remarkably robust out-of-domain.*
  **Connect**: **canonical BM25-is-fine citation** — defends RTFM's
  FTS5 default.

- **`es2024ragas`** — Ragas (EACL 2024 Demo). *Reference-free RAG eval:
  faithfulness/answer-relevance/context-precision-recall.*
  **Connect**: standard RAG eval stack we chose not to use (MRCR is
  oracle-based, cleaner causal claims).

- **`saadfalcon2024ares`** — ARES (NAACL 2024). *Lightweight LM judges +
  prediction-powered inference.*
  **Connect**: counterpoint to MRCR objective grading.

### 2.6 Long-context vs retrieval (contra)

- **`xu2024longcontext`** — Retrieval meets Long Context LLMs (ICLR 2024,
  NVIDIA). *RA 4K-ctx matches 16K-ctx on long-doc; RA Llama2-70B-32K beats
  GPT-3.5-16K.*
  **Connect**: **directly supports our thesis** — RA stays competitive as
  windows grow.

- **`li2024ragvslc`** — RAG or Long-Context LLMs? (EMNLP Industry 2024,
  Google DeepMind). *LC wins on quality when affordable; RAG cuts cost -65%
  (Gemini-1.5-Pro) / -39% (GPT-4o) via Self-Route.*
  **Connect**: **flagship "retrieval saves cost at negligible loss"
  citation** — the Pareto claim RTFM makes.

- **`li2025longctxvsrag`** — Long Context vs RAG: Revisits (2025). *Second-
  gen head-to-head; LC > chunk-RAG on Wiki QA, but summarization-RAG ≈ LC;
  RAG still wins on dialogue & cost.*
  **Connect**: positions RTFM in the LC-vs-RAG frame. *Supporting.*

### 2.7 MCP & tool protocols

- **`anthropic2024mcp`** — MCP announcement (Anthropic, Nov 2024).
  *Open protocol for tool/data integration, LSP-inspired.*
  **Connect**: **RTFM is an MCP server** — foundational protocol citation.

- **`hou2025mcplandscape`** — MCP Landscape/Security (2025). *First
  systematic MCP ecosystem study.*
  **Connect**: citable academic reference for "MCP as a protocol."

- **`patil2025bfcl`** — BFCL (ICML 2025, Berkeley). *AST-based eval of
  parallel/nested/multi-turn tool calls; "irrelevance detection" (when NOT
  to call).*
  **Connect**: function-calling protocol reference; our metric complements
  BFCL's synthetic-skeleton eval.

---

## Axis 3 — Code/doc retrieval in coding agents (commercial & academic)

### 3.1 Classic code retrieval (pre-LLM-agent era)

- **`husain2019codesearchnet`** — CodeSearchNet Challenge (2019). *6M
  functions × 6 langs + 99 expert queries; MRR standard.*
  **Connect**: foundational benchmark establishing the paradigm.

- **`feng2020codebert`** — CodeBERT (Findings EMNLP 2020). *Bimodal
  (NL-PL) Transformer pretrained on CodeSearchNet.*
  **Connect**: historical dense-retriever lineage.

- **`guo2021graphcodebert`** — GraphCodeBERT (ICLR 2021). *First code LM to
  inject data-flow graph into pretraining.*
  **Connect**: early structure-matters evidence.

- **`guo2022unixcoder`** — UniXcoder (ACL 2022). *Unifies enc/dec/enc-dec
  via prefix adapters; flattens ASTs; zero-shot code-to-code search.*
  **Connect**: AST-aware encoder alternative to FTS.

- **`wang2021codet5`** — CodeT5 (EMNLP 2021). *Identifier-aware; bimodal
  dual generation; 8 languages.*
  **Connect**: canonical seq2seq code model.

- **`wang2023codet5plus`** — CodeT5+ (EMNLP 2023). *Flexible enc-dec code
  LLMs up to 16B.*
  **Connect**: generative-code-LLM shift that re-created retrieval demand.

- **`li2023starcoder`** — StarCoder (TMLR 2023, BigCode). *15.5B open code
  LLM, 8K context, MQA, The Stack.*
  **Connect**: pre-1M-context world where retrieval was inevitable.

- **`gotmare2023efficient`** — Efficient Text-to-Code Retrieval (ESEC/FSE
  2023). *Cascaded fast + slow transformer, 0.7795 MRR.*
  **Connect**: architectural analogue for RTFM's FTS-first + optional
  reranker.

- **`huang2021cosqa`** — CoSQA (ACL 2021). *20,604 real web queries + Python
  code; contrastive CoCLR.*
  **Connect**: real queries are short/imprecise — justifies CLAUDE.md nudge.

### 3.2 Repository-level retrieval

- **`shrivastava2023rlpg`** — Repository-Level Prompt Generation (ICML 2023,
  DeepMind). *Learned classifier selects prompt proposals from imports/
  parent classes; +17% over Codex.*
  **Connect**: early proof that repo-scale beats in-file context — the
  thesis RTFM generalizes across domains.

- **`zhang2023repocoder`** — RepoCoder (EMNLP 2023). *Iterative retrieve-
  then-generate; RepoEval; +10% over in-file.*
  **Connect**: methodological precursor to iterative `rtfm_search` calls.

- **`shrivastava2023repofusion`** — RepoFusion (ServiceNow, 2023). *FiD on
  multi-context repo prompts; matches StarCoderBase at 1/70th size.*
  **Connect**: **retrieval can substitute for scale** — consistent with our
  "RTFM restores older model" framing.

- **`ding2022cocomic`** — CoCoMIC (Amazon, 2022). *CCFINDER tool + joint
  in-file/cross-file; +33.9% EM.*
  **Connect**: cross-file discovery = hard part of code completion.

- **`ding2023crosscodeeval`** — CrossCodeEval (NeurIPS DB 2023). *Static-
  analysis-filtered cross-file required benchmark.*
  **Connect**: gold standard for code-side retriever quality.

- **`phan2024repohyper`** — RepoHyper (2024). *RSG + GNN link-predictor
  reranker; SOTA RepoBench.*
  **Connect**: graph-augmented retrieval precedent for RTFM graph roadmap.

### 3.3 Graph-based navigation & Navigation Paradox

- **`paipuru2026codecompass`** — CodeCompass / Navigation Paradox (2026,
  arXiv:2602.20048). ***58% of trials skip the tool despite explicit
  instructions; when invoked (42%), accuracy jumps 80.2%→99.5%.***
  **Connect**: **the foundational motivating citation**. Our CLAUDE.md
  template is the response to this phenomenon.

- **`liu2025codexgraph`** — CodexGraph (NAACL 2025). *Static-analysis Neo4j
  queried via Cypher by agent; CrossCodeEval/SWE-bench/EvoCodeBench.*
  **Connect**: graph-DB retrieval competitive with embeddings; RTFM is
  lighter (SQLite, no Neo4j).

- **`shah2025ranger`** — RANGER (2025). *Dual-stage: Cypher + MCTS graph
  exploration; BM25+graph wins CrossCodeEval.*
  **Connect**: recent evidence BM25+graph beats pure dense — supports
  FTS-default.

- **`tao2025prometheus`** — Prometheus (2025). *Memory-centric KG agent;
  74.4%/33.8% on two SWE benches (Top-1 open-source, GPT-5).*
  **Connect**: cites same Needle-in-a-Haystack persistence problem.

### 3.4 SWE-bench & agentic coding infrastructure

- **`jimenez2024swebench`** — SWE-bench (ICLR 2024 Oral). *2,294 real GitHub
  issues; execution-based eval.*
  **Connect**: de facto benchmark we contextualize against. We explain why
  MRCR isolates retrieval from code-edit noise.

- **`openai2024swebenchverified`** — SWE-bench Verified (OpenAI, Aug 2024).
  *500 human-validated instances.*
  **Connect**: cleaner eval agents target in 2025-26.

- **`yang2024sweagent`** — SWE-agent (NeurIPS 2024). *Agent-Computer
  Interfaces as first-class perf lever; 12.5% pass@1.*
  **Connect**: same thesis as RTFM at the retrieval layer — interface
  ergonomics unlocks agent capability.

- **`xia2024agentless`** — Agentless (2024). *3-phase localize-repair-
  validate, no autonomous tools; 32% SWE-bench Lite at $0.70/issue.*
  **Connect**: **critical counterpoint** — localization (retrieval) matters
  more than agent scaffolding.

- **`wang2025openhands`** — OpenHands / OpenDevin (ICLR 2025). *Open
  platform, sandboxed exec, multi-agent.*
  **Connect**: environment where RTFM plugs in as MCP server.

### 3.5 Commercial context engines (blogs/whitepapers)

- **`augment2025contextengine`** — Augment Code Context Engine. *Proprietary;
  claims 30-80% uplift; dep graph + git-history embeddings + vector; MCP-
  exposed.*
  **Connect**: **RTFM's closest commercial counterpart**. Position RTFM
  explicitly as "open-source Augment Context Engine."

- **`sourcegraph2024cody`** — Sourcegraph Cody. *BM25 + embeddings + SCIP
  code-graph (RSG); layered context.*
  **Connect**: enterprise hybrid-retrieval proof; RTFM replicates open-
  source.

- **`cursor2024indexing`** — Cursor codebase indexing. *Tree-sitter chunking
  → embeddings → Turbopuffer; Merkle-tree incremental sync.*
  **Connect**: Merkle-tree sync inspired RTFM's `core/sync.py`. RTFM keeps
  everything local (Cursor sends to cloud).

- **`continuedev2025`** — Continue.dev. *Open-source IDE assistant,
  embeddings + reranker, MCP-compatible.*
  **Connect**: fellow OSS project; RTFM can serve Continue as MCP backend.

- **`greptile2024`** — Greptile (YC). *File/function/dependency graph for
  PR-review agents; per-team embedding taste.*
  **Connect**: another commercial graph variant in the design space.

### 3.6 Retrieval-augmented code generation

- **`wang2025coderagbench`** — CodeRAG-Bench (NAACL Findings 2025). *8 tasks
  × 5 retrieval sources; retrievers frequently fail to fetch useful context.*
  **Connect**: empirical anchor for "retrieval quality is the bottleneck."

- **`jain2024livecodebench`** — LiveCodeBench (2024). *Contamination-free,
  continuously updated from LeetCode/AtCoder/CodeForces.*
  **Connect**: contamination concerns that also motivated synthetic MRCR.

---

## Axis 4 — Context engineering & tool-use instructions (the *how* of RTFM)

### 4.1 Seminal instruction-tuning

- **`ouyang2022instructgpt`** — InstructGPT (OpenAI, NeurIPS 2022). *RLHF;
  1.3B preferred over 175B GPT-3.*
  **Connect**: **reason a 3-line CLAUDE.md works at all**. Without RLHF
  substrate the directive would be ignored.

- **`bai2022constitutional`** — Constitutional AI (Anthropic, 2022). *Models
  trained on textual constitution via self-critique + RLAIF.*
  **Connect**: Claude Code's obedience to user CLAUDE.md is downstream of
  constitutional training.

- **`wei2022cot`** — Chain-of-Thought (Google Brain, NeurIPS 2022). *Few-
  shot "let's think step-by-step" unlocks latent reasoning.*
  **Connect**: precedent for "a single textual instruction flips whether a
  capability is exercised."

- **`kojima2022zeroshot`** — Zero-Shot CoT (NeurIPS 2022). *"Let's think step
  by step" alone, no exemplars.*
  **Connect**: our 3-line rule is same lineage — minimalist prompt, non-
  trivial shift.

### 4.2 Prompt sensitivity & format

- **`sclar2024format`** — Quantifying Prompt-Format Sensitivity (ICLR 2024).
  *Trivial formatting swings LLaMA-2-13B by up to 76pp.*
  **Connect**: motivates that CLAUDE.md wording is an empirical lever, not
  cosmetic — supports a wording ablation.

- **`battle2024eccentric`** — Eccentric Automatic Prompts (2024). *Bizarre
  system prompts ("Star Trek") beat hand-crafted on GSM8K.*
  **Connect**: cautionary — our hand-tuned 3-line form is likely sub-
  optimal. Future work: APE-style optimization.

- **`zhou2023ape`** — APE (ICLR 2023). *Automated prompt engineering; LLMs
  as prompt engineers, match/beat humans on 19/24 tasks.*
  **Connect**: methodological template for auto-tuning CLAUDE.md.

### 4.3 Surveys

- **`liu2023prompt`** — Pre-train, Prompt, Predict (CSUR 2023). *Canonical
  prompt-based-learning taxonomy.*
  **Connect**: positioning reference (prompt / system prompt / tool
  instruction).

- **`schulhoff2024promptreport`** — The Prompt Report (2024). *PRISMA survey
  of 1565 papers; 58 techniques, 33 terms.*
  **Connect**: CLAUDE.md fits Role + Style Prompting; adopt their
  vocabulary.

- **`mei2025context`** — Context Engineering Survey (2025). *1400+ papers;
  retrieval/memory/tool-integrated reasoning/multi-agent.*
  **Connect**: **direct framing vehicle** — RTFM is a concrete instance of
  context engineering.

### 4.4 Ignored-tool phenomenon (directly load-bearing for RTFM)

- **`paipuru2026codecompass`** — CodeCompass (2026, cross-ref Axis 3).
  **58%→100% adoption shift** via checklist-at-END prompting.
  **Connect**: **the citation**. CLAUDE.md is our answer to this paradox.

- **`hasan2026smelly`** — MCP Tool Descriptions Are Smelly (2026). *Audits
  856 tools across 103 MCP servers; **97% have quality defects**.*
  **Connect**: must-cite. We audit RTFM's own MCP tool descriptions against
  their rubric.

- **`li2026misleading`** — Don't Believe MCP Descriptions (2026). *10,240
  MCP servers; ~13% have description-code mismatches.*
  **Connect**: security-flavored evidence tool descriptions are behaviorally
  load-bearing.

### 4.5 Tool use benchmarks

- **`yao2024taubench`** — τ-bench (NeurIPS 2024, cross-ref Axes 2+5). *Pass^k
  reliability metric; GPT-4o <50%, pass^8 <25% retail.*
  **Connect**: tool-use variance is first-order. Mirror their pass^k
  methodology for RTFM adoption rate.

- **`zhou2023ifeval`** — IFEval (2023). *25 types of verifiable instructions,
  ~500 prompts.*
  **Connect**: methodological blueprint — define a "tool-use instruction-
  following" analogue per CLAUDE.md wording.

### 4.6 Optional / tangential

- **`khattab2024dspy`** — DSPy (ICLR 2024). *Prompts compiled from
  declarative signatures.* *Optional — alternative philosophy.*

- **`perez2022promptinject`** — Ignore Previous Prompt (NeurIPS Safety 2022).
  *First systematic prompt-injection attack.* *Optional — relevant to
  Claude Code's system-reminder injection that polluted our MRCR responses.*

- **`madaan2023selfrefine`** — Self-Refine (NeurIPS 2023). *Single LM as
  generator/critic/refiner.* *Optional — future work: self-refining
  CLAUDE.md.*

---

## Axis 5 — Beyond-accuracy evaluation (methodology)

### 5.1 Seminal: efficiency as first-class axis

- **`liang2022helm`** — HELM (Stanford, TMLR 2023). *7 metric axes incl.
  efficiency; single-metric eval is incomplete.*
  **Connect**: **canonical citation** for multi-metric eval. We report MRCR
  accuracy AND wall-time following HELM.

- **`schwartz2019greenai`** — Green AI (CACM 2020). *Red vs Green AI;
  efficiency + "price tag" should be reported.*
  **Connect**: RTFM's 45s/sample and avoided 1M stuffing are the price tag
  Schwartz advocates.

- **`strubell2019energy`** — Energy & Policy (ACL 2019 Best Paper RU).
  *First rigorous $/CO2e quantification.*
  **Connect**: 1M-token prefill is measurable in kWh.

- **`dehghani2022efficiency`** — Efficiency Misnomer (ICLR 2022, Google).
  *Single efficiency indicator misleads; must report multi-indicator.*
  **Connect**: **critical methodology citation** — we report wall-time AND
  tokens.

- **`patterson2021carbon`** — Carbon Emissions of Large NN Training (Google,
  2021). *Refines Strubell with Google DC data; 100-1000x variation.*
  **Connect**: "efficiency reporting standard practice" — RTFM does this
  inference-side.

### 5.2 Agent benchmarks with cost tracking

- **`kapoor2024agents`** — AI Agents That Matter (Princeton, 2024). *Agent
  benchmarks optimize only accuracy; cost-accuracy Pareto frontiers; simple
  baselines dominate Reflexion/LDB/LATS.*
  **Connect**: **single most important methodology citation**. RTFM's
  retrieval vs 1M is literally a Pareto argument.

- **`kapoor2025hal`** — Holistic Agent Leaderboard / HAL (Princeton, ICLR
  2026). *21,730 rollouts × 9 models × 9 benches at ~$40K; cost/task as
  first-class.*
  **Connect**: infrastructure-level follow-up. Our per-sample wall-time log
  is lightweight instance.

- **`stroebl2026efficient`** — Efficient Benchmarking of AI Agents (2026).
  *44-70% task-set reduction while preserving rank; IRT-motivated.*
  **Connect**: justifies subsampling MRCR if needed.

- **`yao2024taubench`** — τ-bench (cross-ref Axis 4). *Reflexion uses ~2000
  API calls/task.*
  **Connect**: concrete example of "accuracy OK, cost explodes."

- **`liu2024agentbench`** — AgentBench (Tsinghua, ICLR 2024). *8-environment;
  29 models.*
  **Connect**: *contrast* — seminal agent bench that did NOT track cost.

- **`zhou2024webarena`** — WebArena (CMU, ICLR 2024). *Realistic web agent
  bench; 50× cost variation at similar accuracy (per Kapoor 2024 analysis).*
  **Connect**: cost axis invisible until third-party surfaces it.

- **`mialon2024gaia`** — GAIA (Meta/HF, ICLR 2024). *466 tool-using Qs;
  humans 92% vs GPT-4 15%.*
  **Connect**: canonical "agents need retrieval+tools" citation.

- **`trivedi2024appworld`** — AppWorld (ACL 2024 Best Resource). *750-task
  interactive coding on 9 apps / 457 APIs.* *Optional — tangential.*

### 5.3 Human-preference & production eval

- **`chiang2024arena`** — Chatbot Arena (LMSYS, ICML 2024). *>240K votes;
  de facto production-quality leaderboard.*
  **Connect**: "real-world quality involves latency+cost."

- **`zheng2023mtbench`** — MT-Bench + LLM-as-Judge (NeurIPS DB 2023).
  *Multi-turn + LLM-judge validation.* *Optional.*

- **`dubois2024alpacaeval`** — Length-Controlled AlpacaEval (COLM 2024).
  *Verbosity bias inflates win rates; LC-metric raises Arena correlation
  0.94→0.98.*
  **Connect**: tokens-out is a cost axis; benchmarks reward verbosity=cost.

### 5.4 Benchmark critique

- **`dehghani2021benchmark`** — Benchmark Lottery (Google Brain, 2021).
  *Rankings change by swapping tasks; benchmarks aren't neutral.*
  **Connect**: grounds "explicit about what MRCR measures" methodology.

- **`sainz2023contamination`** — Data Contamination (Findings EMNLP 2023).
  *Classical eval compromised by train-test contamination.*
  **Connect**: pairs with Benchmark Lottery — accuracy numbers alone
  untrustworthy.

### 5.5 Test-time compute & inference economics

- **`snell2025scaling`** — Scaling Test-Time Compute (DeepMind, ICLR 2025).
  *Small models + more test-time compute beat larger models.*
  **Connect**: RTFM trades extra retrieval-time compute for reduced model-
  side compute — a point on Snell's frontier.

- **`erdil2025inference`** — Inference Economics of LMs (Epoch AI, 2025).
  *Theoretical cost/speed model accounting for arithmetic/memory/network/
  latency.* *Optional — deeper latency discussion.*

- **`chen2023frugalgpt`** — FrugalGPT (2023). *LLM cascades at 98% cost
  reduction.* *Optional — different axis (model selection, not retrieval).*

---

## Cross-references (papers spanning multiple axes)

| Paper | Primary | Also relevant to |
|---|---|---|
| `liu2024lostmiddle` | Axis 1 | Axes 2, 5 |
| `hsieh2024ruler` | Axis 1 | Axes 3, 5 |
| `vodrahalli2024michelangelo` | Axis 1 | Axes 3, 5 (MRCR benchmark definition) |
| `li2024ragvslc` | Axis 2 | Axes 1, 5 |
| `xu2024longcontext` | Axis 2 | Axis 1 |
| `yao2023react` | Axis 2 | Axis 4 |
| `schick2023toolformer` | Axis 2 | Axis 4 |
| `qin2024toolllm` | Axis 2 | Axis 4 |
| `paipuru2026codecompass` | Axis 3 | Axes 2, 4 (Navigation Paradox) |
| `jimenez2024swebench` | Axis 3 | Axes 2, 5 |
| `xia2024agentless` | Axis 3 | Axis 5 |
| `yao2024taubench` | Axis 4 | Axes 2, 5 |
| `thakur2021beir` | Axis 2 | Axis 5 |

---

## Quick-pick shortlist for short paper (6-8 pages)

If we're brutally space-constrained, a ~20-citation skeleton:

**Problem framing**: `vodrahalli2024michelangelo` (MRCR), `liu2024lostmiddle`
(LitM), `hsieh2024ruler` (RULER), `modarressi2025nolima` (NoLiMa 2025),
`anthropic2026opus47` + `anthropic2026opus46` (system cards),
`hong2025contextrot` (industry context).

**Solution class**: `lewis2020rag` (RAG canon), `xu2024longcontext` (RA
beats stuff), `li2024ragvslc` (cost -65%), `singh2025agenticragsurvey`
(agentic-RAG framing), `mallen2023popqa` (when to retrieve),
`yao2023react` (ReAct loop), `anthropic2024mcp` (MCP).

**Method / calibration**: `paipuru2026codecompass` (Navigation Paradox +
58%→100% adoption), `hasan2026smelly` (97% MCP tools defective),
`sclar2024format` (format sensitivity), `mei2025context` (context
engineering survey).

**Methodology**: `kapoor2024agents` (Pareto eval), `liang2022helm` (HELM),
`dehghani2022efficiency` (multi-metric).

**Adjacent / open-source positioning**: `augment2025contextengine`,
`sourcegraph2024cody`, `paipuru2026codecompass` (as the closest open
academic analogue).
