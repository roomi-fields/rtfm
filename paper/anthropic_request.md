# Anthropic External Researcher Access — Form-ready answers

**Form URL**: https://forms.gle/pZYC8f6qYqSKvRWn9
**Review cycle**: first Monday of each month → next **Monday 2026-05-04**
**Default allocation**: $1,000; *"rare cases"* may be higher

---

## Field 1 — Candidate/team description (≤ 200 words, **expertise required**)

> I am an independent researcher (Romain Peyrichou, France) working at the intersection of retrieval systems and frontier LLM evaluation. My technical expertise covers information retrieval (SQLite/FTS5 + embedding backends), LLM tooling (MCP servers, agent loops), and empirical evaluation of long-context models.
>
> I am the author and maintainer of RTFM (https://github.com/roomi-fields/rtfm), an open-source MCP retrieval layer for AI coding agents. RTFM ships parsers for ten document formats, a hybrid FTS + embeddings backend, and a reproducible benchmarking harness. A prior arXiv publication in cs.CL (arXiv:2603.10139, March 2026) demonstrates formal-methods rigor in an adjacent area and establishes a track record of writing publishable research.
>
> No institutional affiliation; all work is conducted independently. This status shapes what I can contribute: independent replications of lab-published benchmarks, open-source tooling external labs can audit, and evaluation protocols that do not inherit a single lab's priors. I am currently drafting a short paper (arXiv + TMLR target) evaluating an agentic-retrieval mitigation for Opus 4.7's long-context regression on MRCR v2 — the subject of this credit request.

*(~195 words.)*

---

## Field 2 — Research / credits request (≤ 300 words)

> **Project.** The short paper evaluates how an open-source MCP retrieval layer (RTFM) restores Claude Opus 4.7 accuracy on MRCR v2 8-needle (Vodrahalli et al. 2024, *Michelangelo*) — the benchmark reported in Anthropic's Opus 4.7 system card. Anthropic publishes a drop from 91.9 % (Opus 4.6) to 59.2 % at 256K, and from 78.3 % to 32.2 % at 1M.
>
> Preliminary runs on 198 samples show Opus 4.7 + RTFM reaches near-ceiling accuracy (~100 % at 256K, ~99 % at 1M), apparently exceeding stuffed Opus 4.6 at 1M — to our knowledge a first public demonstration of a retrieval-augmented frontier model surpassing the prior generation on a published long-context benchmark.
>
> **Why the credits matter.** Preliminary numbers were collected via Claude Code CLI and are contaminated by its system-reminder injections (harness artifact, not retrieval failure — the target string appears in 100 % of responses). Clean measurements via the Anthropic SDK direct are the prerequisite for submission.
>
> Minimum-viable budget ~$700:
> - $50: SDK-clean RTFM replication (198 samples × 2 bins)
> - $155: 25-sample stuffed 256K + 5-sample stuffed 1M for variance and latency
> - $495: reviewer-requested revision buffer
>
> If Anthropic can share per-sample logs from its own system-card MRCR v2 runs on Opus 4.6 / 4.7, the budget drops to ~$300 and the paper gains rigor (citing first-party measurements rather than re-runs).
>
> Without credits, defensible numbers cannot be measured and the paper cannot be submitted. All experiment logs, prompts, seeds, and grader outputs will be released as supplementary material. Raw data will be shared with Anthropic's model evaluation team before arXiv posting on request.

*(~290 words.)*

---

## Other likely form fields

| Field | Proposed answer |
|---|---|
| Name | Romain Peyrichou |
| Email | claude@liance.art (confirm) |
| Country | France |
| Institution | *Independent researcher* |
| Google Scholar URL | **→ see note below** |
| GitHub URL | https://github.com/roomi-fields |
| Project URL (if asked) | https://github.com/roomi-fields/rtfm |
| Prior publications | arXiv:2603.10139 — *The Generation-Recognition Asymmetry*, Peyrichou, March 2026, cs.CL |
| Requested amount | $700 (minimum viable); $300 if Anthropic shares system-card logs |
| Credit usage timeframe | 6 months from approval |

### On the Google Scholar URL

You likely don't have a Scholar profile yet (1 arXiv paper, recent, unrelated area). Two options:
1. **Create one in 5 minutes** at https://scholar.google.com/citations?hl=en — log in with Google, add affiliation (can stay "Independent researcher"), Scholar auto-indexes arXiv papers within hours. Empty profile is still better than no profile.
2. **If the form accepts, put the arXiv abstract URL directly**: https://arxiv.org/a/peyrichou_r_1 (check this resolves to your author page — arXiv auto-generates one per author).

Recommended: do option 1 tonight if the form is soft-required on Scholar. It signals that you're indexable / locatable in the academic graph.

---

## Honest sanity check (from prior exchange)

The selection AI faces thousands of apps/month and filters on strong signals: institutional affiliation, Scholar track record, thematic fit with alignment. Our dossier is weaker on all three. The revised answers above do what we can:
- lead with concrete technical expertise (RTFM as shipping artifact);
- quantify the preliminary finding up-front;
- be transparent about CLI contamination (methodological honesty);
- offer a collaboration path (share logs, reduce spend) rather than just ask.

**Probability of selection in current form**: low but non-zero. The argument accepted elsewhere in this conversation — *post the preprint first, then apply* — still stands as the strongest move. If you can push a draft to arXiv with the CLI-cleaned numbers before submitting, the application becomes *"author of arXiv:260X.XXXXX, applying to finalize baselines,"* which materially changes the read.

---

## Supplementary material (NOT for the form — background kept for reference)

### Project rationale (long form)

This is external evaluation of a deployed frontier model's failure mode and a practical mitigation. It fits the spirit of the External Researcher Access Program along three safety-relevant axes:

1. Documenting a deployment-relevant failure that the high-level system-card numbers alone do not fully expose.
2. Independent, reproducible measurement on an open benchmark (MRCR v2) with all code, prompts, and logs released.
3. A mitigation that requires no retraining and generalizes across model versions and vendors (any MCP-capable frontier LLM).

### Stretch budget ($3,000, "rare case")

Would fund:
- Full stuffed Opus 4.7 replication (97 samples @ 256K + 101 @ 1M) — ~$1,900
- Variance analysis (3 seeds × key configurations) — ~$400
- Bin sweep (32K, 64K, 128K, 512K) for the accuracy-vs-length figure — ~$700

### Deliverables and commitments

- Short paper on arXiv (primary cs.CL, cross-list cs.IR / cs.SE), 8 pages, target submission May 2026.
- Concurrent TMLR submission.
- All experiment logs released as supplementary material.
- Full benchmark harness reproducibility from `rtfm` repository (MIT license).
- Acknowledgement of Anthropic API Credits in the paper.
- Raw data shared with Anthropic model evaluation team before posting on request.

### Alternative short email (if direct contact found later)

> **Subject**: External Researcher Access: MRCR v2 replication + retrieval mitigation for Opus 4.7
>
> Hi,
>
> I've submitted an application to the External Researcher Access Program (review cycle 2026-05-04). The project is an independent replication of Anthropic's published MRCR v2 8-needle numbers for Opus 4.6 and 4.7, plus evaluation of a retrieval-based mitigation.
>
> Preliminary CLI-harness results on 198 samples: Opus 4.7 + an open-source MCP retrieval layer (RTFM) reaches ~100 % / ~99 % (256K / 1M), versus the 59.2 % / 32.2 % stuffed numbers in the 4.7 system card. At 1M, retrieval-augmented 4.7 appears to exceed stuffed Opus 4.6. The credit request is specifically to obtain clean SDK-direct measurements before arXiv / TMLR submission.
>
> One note: if the per-sample logs from your own system-card MRCR v2 runs on Opus 4.6 / 4.7 could be shared, it would spare ~$1.9k of tokens replicating work you've already done, and the paper would actually be more rigorous (citing Anthropic's own measurements rather than an external re-run). We'd credit the logs explicitly, and could restrict use to aggregates if preferred.
>
> Prior arXiv publication: arXiv:2603.10139 (cs.CL, March 2026). Retrieval layer: https://github.com/roomi-fields/rtfm. Happy to share raw data with your model evaluation team before posting.
>
> Best,
> Romain Peyrichou
