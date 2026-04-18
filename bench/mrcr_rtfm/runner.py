"""Per-sample orchestration: serialize → sync → embed → claude -p → grade."""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from bench.mrcr_rtfm.grader import grade
from bench.mrcr_rtfm.loader import MrcrSample
from bench.mrcr_rtfm.serialize import serialize_turns


DEFAULT_CLAUDE_MODEL = "claude-opus-4-7"
DEFAULT_EMBED_MODEL = "quality"  # mxbai-embed-large-v1 alias
DEFAULT_SEARCH_MODE = "hybrid"   # hybrid = FTS + embeddings


def _resolve_rtfm_serve(rtfm_bin: str) -> str:
    """Return the best command for the MCP server — prefer an absolute path
    to the venv's rtfm-serve when rtfm_bin itself is a venv binary."""
    resolved = shutil.which("rtfm-serve")
    if resolved:
        return resolved
    # Derive from the rtfm CLI path if it's a venv entry
    rtfm_path = shutil.which(rtfm_bin) or rtfm_bin
    sibling = Path(rtfm_path).with_name("rtfm-serve")
    if sibling.exists():
        return str(sibling)
    return "rtfm-serve"  # Fallback — will fail loudly if unresolved

# Timeouts (seconds)
SYNC_TIMEOUT = 300
EMBED_TIMEOUT = 900
CLAUDE_TIMEOUT = 300


@dataclass
class SampleResult:
    idx: int
    n_chars: int
    approx_tokens: int
    score: float
    response: str
    random_string: str
    wall_time_sec: float
    embed_time_sec: float
    claude_time_sec: float
    n_turns_indexed: int
    error: Optional[str] = None


def _write_mcp_config(sample_dir: Path, db_path: Path, rtfm_serve_cmd: str) -> None:
    """Write a local .mcp.json so `claude -p` run inside sample_dir uses our DB."""
    mcp = {
        "mcpServers": {
            "rtfm": {
                "command": rtfm_serve_cmd,
                "args": [],
                "env": {"RTFM_DB": str(db_path.resolve())},
            }
        }
    }
    (sample_dir / ".mcp.json").write_text(json.dumps(mcp, indent=2))


def _write_claude_md(sample_dir: Path, template_path: Path) -> None:
    """Copy the CLAUDE.md template into the sample directory."""
    shutil.copy(template_path, sample_dir / "CLAUDE.md")


def _run(cmd: list[str], cwd: Path, timeout: int, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run a subprocess with a hard timeout. Returns the CompletedProcess; errors surface via returncode."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def run_sample(
    sample: MrcrSample,
    out_dir: Path,
    rtfm_bin: str = "rtfm",
    claude_bin: str = "claude",
    claude_model: str = DEFAULT_CLAUDE_MODEL,
    embed_model: str = DEFAULT_EMBED_MODEL,
    search_mode: str = DEFAULT_SEARCH_MODE,
    template_path: Optional[Path] = None,
    dry_run: bool = False,
    phase: str = "all",
) -> SampleResult:
    """Run one MRCR sample end-to-end and return its score.

    out_dir: where to create `sample_<idx>/`. Left behind for inspection.
    dry_run: only serialize + write configs, skip embed + claude (validates layout).
    phase: "all" (default) = sync+embed+claude+grade,
           "embed" = sync+embed only (no Claude call, no grading, score=-1).
           "claude" = assumes sample_dir already has an embedded DB, only runs
           Claude + grade (used for resume after Phase 1).
    """
    start = time.time()
    sample_dir = out_dir / f"sample_{sample.idx:05d}"
    sample_dir.mkdir(parents=True, exist_ok=True)
    db_path = sample_dir / ".rtfm" / "library.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if template_path is None:
        template_path = Path(__file__).parent / "CLAUDE_template.md"

    embed_time = 0.0
    claude_time = 0.0

    if phase not in ("all", "embed", "claude"):
        raise ValueError(f"Invalid phase: {phase}")

    # Phase 1 (embed) and "all" — serialize + sync + embed
    if phase in ("all", "embed"):
        # 1. Serialize conversation history to .md files
        n_turns = serialize_turns(sample.history_turns, sample_dir)

        # 2. Write MCP + CLAUDE.md configs
        _write_mcp_config(sample_dir, db_path, _resolve_rtfm_serve(rtfm_bin))
        _write_claude_md(sample_dir, template_path)

        if dry_run:
            return SampleResult(
                idx=sample.idx, n_chars=sample.n_chars,
                approx_tokens=sample.approx_tokens,
                score=-1.0, response="",
                random_string=sample.random_string,
                wall_time_sec=time.time() - start,
                embed_time_sec=0.0, claude_time_sec=0.0,
                n_turns_indexed=n_turns, error="dry_run",
            )

        # 3. Sync conversation into RTFM
        sync_proc = _run(
            [rtfm_bin, "sync", "conv", "--db", str(db_path),
             "--corpus", "mrcr", "--no-embeddings"],
            cwd=sample_dir,
            timeout=SYNC_TIMEOUT,
        )
        if sync_proc.returncode != 0:
            return SampleResult(
                idx=sample.idx, n_chars=sample.n_chars,
                approx_tokens=sample.approx_tokens,
                score=0.0, response="", random_string=sample.random_string,
                wall_time_sec=time.time() - start,
                embed_time_sec=0.0, claude_time_sec=0.0,
                n_turns_indexed=n_turns,
                error=f"sync failed: {sync_proc.stderr[:500]}",
            )

        # 4. Embed (slowest step for large samples)
        embed_start = time.time()
        embed_proc = _run(
            [rtfm_bin, "embed", "--db", str(db_path),
             "--embed-model", embed_model],
            cwd=sample_dir,
            timeout=EMBED_TIMEOUT,
        )
        embed_time = time.time() - embed_start
        if embed_proc.returncode != 0:
            return SampleResult(
                idx=sample.idx, n_chars=sample.n_chars,
                approx_tokens=sample.approx_tokens,
                score=0.0, response="", random_string=sample.random_string,
                wall_time_sec=time.time() - start,
                embed_time_sec=embed_time, claude_time_sec=0.0,
                n_turns_indexed=n_turns,
                error=f"embed failed: {embed_proc.stderr[:500]}",
            )

        if phase == "embed":
            return SampleResult(
                idx=sample.idx, n_chars=sample.n_chars,
                approx_tokens=sample.approx_tokens,
                score=-1.0, response="", random_string=sample.random_string,
                wall_time_sec=time.time() - start,
                embed_time_sec=embed_time, claude_time_sec=0.0,
                n_turns_indexed=n_turns, error="phase=embed",
            )

    # Phase 2 (claude) — assumes sync+embed already ran
    if phase == "claude":
        # Count existing files in conv/ so the result row has the right n_turns
        conv_dir = sample_dir / "conv"
        n_turns = len(list(conv_dir.glob("*.md"))) if conv_dir.exists() else 0
        if not db_path.exists() or n_turns == 0:
            return SampleResult(
                idx=sample.idx, n_chars=sample.n_chars,
                approx_tokens=sample.approx_tokens,
                score=0.0, response="", random_string=sample.random_string,
                wall_time_sec=time.time() - start,
                embed_time_sec=0.0, claude_time_sec=0.0,
                n_turns_indexed=n_turns,
                error="phase=claude but no pre-embedded sample_dir found",
            )

    # 5. Run Claude Code headless on the last user turn
    claude_start = time.time()
    claude_proc = _run(
        [claude_bin, "-p", sample.last_user_turn,
         "--model", claude_model,
         "--permission-mode", "acceptEdits"],
        cwd=sample_dir,
        timeout=CLAUDE_TIMEOUT,
    )
    claude_time = time.time() - claude_start
    if claude_proc.returncode != 0:
        return SampleResult(
            idx=sample.idx, n_chars=sample.n_chars,
            approx_tokens=sample.approx_tokens,
            score=0.0, response=claude_proc.stdout,
            random_string=sample.random_string,
            wall_time_sec=time.time() - start,
            embed_time_sec=embed_time, claude_time_sec=claude_time,
            n_turns_indexed=n_turns,
            error=f"claude failed (rc={claude_proc.returncode}): {claude_proc.stderr[:500]}",
        )

    response = claude_proc.stdout.strip()
    score = grade(response, sample.answer, sample.random_string)

    return SampleResult(
        idx=sample.idx, n_chars=sample.n_chars,
        approx_tokens=sample.approx_tokens,
        score=score, response=response,
        random_string=sample.random_string,
        wall_time_sec=time.time() - start,
        embed_time_sec=embed_time, claude_time_sec=claude_time,
        n_turns_indexed=n_turns,
    )
