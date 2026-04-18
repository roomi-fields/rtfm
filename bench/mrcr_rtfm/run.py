"""MRCR v2 8-needle bench runner — RTFM configuration.

Example:
    # Dry-run (no embedding, no Claude call) to validate layout + costs
    python -m bench.mrcr_rtfm.run --bin 256K --max-samples 3 --dry-run

    # Real run: 10 samples from the 256K bin
    python -m bench.mrcr_rtfm.run --bin 256K --max-samples 10 \\
        --out-dir bench/runs/mrcr-256K

    # Full bin run
    python -m bench.mrcr_rtfm.run --bin 1M --out-dir bench/runs/mrcr-1M
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from bench.mrcr_rtfm.loader import BINS, load_samples
from bench.mrcr_rtfm.runner import (
    DEFAULT_CLAUDE_MODEL, DEFAULT_EMBED_MODEL, DEFAULT_SEARCH_MODE,
    run_sample,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MRCR v2 8-needle bench (RTFM)")
    parser.add_argument("--bin", required=True, choices=list(BINS),
                        help="Token-count bin to evaluate")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Stop after N samples (default: all in bin)")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Run directory — will contain sample_*/ and results.jsonl")
    parser.add_argument("--rtfm-bin", default="rtfm")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--search-mode", default=DEFAULT_SEARCH_MODE,
                        choices=["fts", "semantic", "hybrid"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip embed + Claude; only validate layout")
    parser.add_argument("--resume", action="store_true",
                        help="Skip samples already recorded in results.jsonl")
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.out_dir / "results.jsonl"

    completed_idx: set[int] = set()
    if args.resume and results_path.exists():
        with results_path.open() as f:
            for line in f:
                try:
                    completed_idx.add(json.loads(line)["idx"])
                except (KeyError, json.JSONDecodeError):
                    continue
        print(f"[resume] skipping {len(completed_idx)} completed samples")

    scores: list[float] = []
    n = 0
    with results_path.open("a") as results_f:
        for sample in load_samples(args.bin, max_samples=args.max_samples):
            if sample.idx in completed_idx:
                continue
            n += 1
            print(
                f"[{n}] sample {sample.idx} "
                f"(tokens~{sample.approx_tokens:,}, {sample.total_messages} turns)..."
            )
            try:
                result = run_sample(
                    sample=sample,
                    out_dir=args.out_dir,
                    rtfm_bin=args.rtfm_bin,
                    claude_bin=args.claude_bin,
                    claude_model=args.claude_model,
                    embed_model=args.embed_model,
                    search_mode=args.search_mode,
                    dry_run=args.dry_run,
                )
            except Exception as err:
                print(f"  unexpected exception: {err}", file=sys.stderr)
                continue

            results_f.write(json.dumps(asdict(result)) + "\n")
            results_f.flush()

            if result.score >= 0:
                scores.append(result.score)
                running = sum(scores) / len(scores)
                print(
                    f"  score={result.score:.3f} "
                    f"(running mean={running:.3f} over {len(scores)}) "
                    f"t={result.wall_time_sec:.1f}s "
                    f"(embed={result.embed_time_sec:.1f}s, "
                    f"claude={result.claude_time_sec:.1f}s)"
                )
            if result.error:
                print(f"  error: {result.error}", file=sys.stderr)

    if scores:
        print(f"\n=== {args.bin} bin ===")
        print(f"Samples:       {len(scores)}")
        print(f"Mean score:    {sum(scores)/len(scores):.4f}")
        print(f"Results file:  {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
