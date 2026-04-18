# MRCR v2 8-needle Bench — RTFM

Reproduces Anthropic's `Claude Opus 4.7` 8-needle MRCR evaluation but routes
retrieval through RTFM instead of stuffing the full context window.

## Baseline (published)

Anthropic's Opus 4.7 system card, 8-needle variant:

| Bin   | Opus 4.6 | Opus 4.7 |
|-------|----------|----------|
| 256K  | 91.9%    | 59.2%    |
| 1M    | 78.3%    | 32.2%    |

Our target: `Opus 4.7 + RTFM` at the same bins.

## Dataset

`openai/mrcr` on HuggingFace (MIT). Two parquet files under `8needle/`, 800
rows total. We filter by approximate token count (`n_chars // 4`) to bucket
samples into Anthropic's bins.

## Protocol

For each sample:

1. Serialize the conversation history (`prompt` JSON minus the final user turn)
   into one `.md` file per turn under `sample_<idx>/conv/`.
2. `rtfm sync conv --no-embeddings`
3. `rtfm embed --embed-model quality` (mxbai-embed-large-v1)
4. `claude -p "<last user turn>"` with a local `.mcp.json` pointing to the
   per-sample DB and a `CLAUDE.md` instructing hybrid-search retrieval.
5. Grade with the official `difflib` scorer — zero if the response does not
   start with the required `random_string_to_prepend`.

Each sample is self-contained under `sample_<idx>/` so runs can be resumed
and inspected.

## Usage

```bash
# Dry-run (no embed, no claude) — validates dataset load + layout
python -m bench.mrcr_rtfm.run --bin 256K --max-samples 3 \
    --out-dir bench/runs/smoke --dry-run

# Small real run — 5 samples
python -m bench.mrcr_rtfm.run --bin 256K --max-samples 5 \
    --out-dir bench/runs/mrcr-256K-smoke

# Full bin (estimated 100 samples / bin / hours on CPU)
python -m bench.mrcr_rtfm.run --bin 256K --out-dir bench/runs/mrcr-256K
python -m bench.mrcr_rtfm.run --bin 1M   --out-dir bench/runs/mrcr-1M
```

Results land in `<out-dir>/results.jsonl`, one line per sample.

## Caveats

- Conversation turns come from a multi-turn dialogue; we serialize them as
  files. This slightly changes the distribution vs. the original MRCR input
  format — to be declared in any reported number.
- Bin assignment is approximate (chars/4 ≈ tokens). A tiny fraction of samples
  may straddle the boundary of the official tokenizer bucket.
- `Opus 4.7` API currently rejects non-default `temperature`/`top_p`. The runner
  passes no sampling flag.
