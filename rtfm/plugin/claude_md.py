"""CLAUDE.md injection — adds RTFM instructions to a project's CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

RTFM_MARKER = "## RTFM"

RTFM_TEMPLATE = """## RTFM — Indexed Knowledge Base

This project has been indexed with RTFM.

For any **exploratory search** (finding which files/modules/classes are relevant
to a topic), use `rtfm_search` instead of Glob, find, ls, or broad Grep.
Then use `rtfm_expand` to read easily most relevant files/sections.
"""

RTFM_VAULT_TEMPLATE = """## RTFM — Indexed Knowledge Base

This vault is indexed by RTFM. See [[_rtfm/index]] for navigation.

Use `rtfm_search` for exploratory search, `rtfm_expand` to read sections.
Browse the knowledge graph at [[_rtfm/graph]].
"""


def inject_claude_md(project_root: str | Path, vault_mode: bool = False) -> str:
    """Inject RTFM instructions into the project's CLAUDE.md.

    Creates the file if it doesn't exist. Appends the RTFM section if not
    already present. Skips if the marker is already found.

    Args:
        project_root: Path to the project root.
        vault_mode: If True, use vault template with wikilinks.

    Returns:
        One of "created", "appended", or "skipped".
    """
    project_root = Path(project_root)
    claude_md = project_root / "CLAUDE.md"
    template = RTFM_VAULT_TEMPLATE if vault_mode else RTFM_TEMPLATE

    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")

        # Already injected?
        if RTFM_MARKER in content:
            return "skipped"

        # Append
        separator = "\n" if content.endswith("\n") else "\n\n"
        claude_md.write_text(
            content + separator + template,
            encoding="utf-8",
        )
        return "appended"
    else:
        claude_md.write_text(template, encoding="utf-8")
        return "created"
