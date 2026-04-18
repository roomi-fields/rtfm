"""Load the openai/mrcr 8-needle dataset and filter to Anthropic-comparable bins."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


# Bin thresholds in token count. Anthropic reports 8-needle scores at 256K and 1M.
# We approximate token count from n_chars (~4 chars/token for English).
# Bin ranges are widened slightly to catch samples whose tokenizer count falls
# near the boundary.
BINS: dict[str, tuple[int, int]] = {
    # alias → (min_tokens, max_tokens)
    "4K":   (0, 4_500),
    "8K":   (4_500, 9_000),
    "16K":  (9_000, 18_000),
    "32K":  (18_000, 36_000),
    "64K":  (36_000, 72_000),
    "128K": (72_000, 144_000),
    "256K": (144_000, 288_000),
    "512K": (288_000, 576_000),
    "1M":   (576_000, 1_200_000),
}


@dataclass
class MrcrSample:
    """One row from openai/mrcr."""
    idx: int                   # Global row index in the parquet
    prompt_turns: list[dict]   # Parsed JSON list of {"role", "content"}
    answer: str                # Expected model answer (includes random_string prefix)
    random_string: str         # The prefix that must appear at the start of the answer
    n_needles: int             # Always 8 for this subset
    desired_msg_index: int     # Index of the target needle in prompt_turns
    total_messages: int
    n_chars: int
    approx_tokens: int         # n_chars // 4

    @property
    def last_user_turn(self) -> str:
        """The final instruction — the only text we show Claude directly."""
        for turn in reversed(self.prompt_turns):
            if turn["role"] == "user":
                return turn["content"]
        raise ValueError(f"No user turn in sample {self.idx}")

    @property
    def history_turns(self) -> list[dict]:
        """All turns except the final user instruction (those that go into RTFM)."""
        # Find index of the last user turn and exclude it
        for i in range(len(self.prompt_turns) - 1, -1, -1):
            if self.prompt_turns[i]["role"] == "user":
                return self.prompt_turns[:i]
        raise ValueError(f"No user turn in sample {self.idx}")


def load_samples(
    bin_alias: str,
    max_samples: Optional[int] = None,
    cache_dir: Optional[Path] = None,
) -> Iterator[MrcrSample]:
    """Yield samples from openai/mrcr 8-needle matching the given token bin.

    Requires the `datasets` package. Downloads to the HF cache on first call.
    """
    try:
        from datasets import load_dataset
    except ImportError as err:
        raise ImportError(
            "Bench requires `datasets`: pip install datasets"
        ) from err

    if bin_alias not in BINS:
        raise ValueError(f"Unknown bin '{bin_alias}'. Valid: {list(BINS)}")
    min_tok, max_tok = BINS[bin_alias]

    ds = load_dataset(
        "openai/mrcr",
        data_files={"train": "8needle/*.parquet"},
        cache_dir=str(cache_dir) if cache_dir else None,
    )
    rows = ds["train"]

    yielded = 0
    for idx, row in enumerate(rows):
        approx_tokens = row["n_chars"] // 4
        if not (min_tok <= approx_tokens < max_tok):
            continue

        sample = MrcrSample(
            idx=idx,
            prompt_turns=json.loads(row["prompt"]),
            answer=row["answer"],
            random_string=row["random_string_to_prepend"],
            n_needles=row["n_needles"],
            desired_msg_index=row["desired_msg_index"],
            total_messages=row["total_messages"],
            n_chars=row["n_chars"],
            approx_tokens=approx_tokens,
        )
        yield sample
        yielded += 1
        if max_samples is not None and yielded >= max_samples:
            break
