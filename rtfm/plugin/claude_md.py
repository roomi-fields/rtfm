"""CLAUDE.md injection — adds RTFM instructions to a project's CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

RTFM_MARKER = "## RTFM"

RTFM_TEMPLATE = """## RTFM — Indexed Knowledge Base

This project has been indexed with RTFM.

For any **exploratory search** (finding which files/modules/classes are relevant
to a topic), use `rtfm_search` instead of Glob, find, ls, or broad Grep.

This returns file paths + context metadata. Then continue normally — Read the
files, Grep for exact patterns within them, Edit to modify.
"""


def inject_claude_md(project_root: str | Path) -> str:
    """Inject RTFM instructions into the project's CLAUDE.md.

    Creates the file if it doesn't exist. Appends the RTFM section if not
    already present. Skips if the marker is already found.

    Args:
        project_root: Path to the project root.

    Returns:
        One of "created", "appended", or "skipped".
    """
    project_root = Path(project_root)
    claude_md = project_root / "CLAUDE.md"

    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")

        # Already injected?
        if RTFM_MARKER in content:
            return "skipped"

        # Append
        separator = "\n" if content.endswith("\n") else "\n\n"
        claude_md.write_text(
            content + separator + RTFM_TEMPLATE,
            encoding="utf-8",
        )
        return "appended"
    else:
        claude_md.write_text(RTFM_TEMPLATE, encoding="utf-8")
        return "created"
