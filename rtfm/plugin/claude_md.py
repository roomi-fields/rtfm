"""CLAUDE.md injection — adds RTFM instructions to a project's CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

RTFM_MARKER = "## RTFM"

RTFM_TEMPLATE = """## RTFM — Project Knowledge Base

This project uses RTFM for indexed project knowledge. Rules:
- For understanding a concept/module/feature, use rtfm_search BEFORE Grep/Glob
- When starting work on a file, use rtfm_context(subject) for relevant context
- DO NOT do broad grep searches to understand the project; search RTFM first
- If rtfm returns no results, THEN fallback to Grep/Glob
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
