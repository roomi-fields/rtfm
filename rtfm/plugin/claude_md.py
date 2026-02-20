"""CLAUDE.md injection — adds RTFM instructions to a project's CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

RTFM_MARKER = "## RTFM"

RTFM_TEMPLATE = """## RTFM — Project Knowledge Base (MANDATORY)

IMPORTANT: This project has a fully indexed knowledge base via RTFM MCP server.

### MANDATORY workflow for EVERY task:

1. **BEFORE using Grep or Glob**, you MUST call `rtfm_context("subject")` or `rtfm_search("query")` first
2. RTFM returns relevant chunks from ALL project files (code, docs, data) in milliseconds
3. Only fall back to Grep/Glob if RTFM returns no results

### Rules (MUST follow):
- **NEVER** start a task with Grep/Glob searches. Always `rtfm_context` or `rtfm_search` first
- **NEVER** delegate context research to Explore/Task agents — they do NOT have access to RTFM. Do RTFM searches yourself directly
- When asked about a topic, concept, or file: `rtfm_context("topic")` FIRST
- When looking for how something works: `rtfm_search("how X works")` FIRST
- When exploring the project structure: `rtfm_discover(".")` FIRST
- After external searches (Grep, web, etc.), use `rtfm_remember(content, title)` to save useful findings into the knowledge base
- Grep/Glob are ONLY for: (a) RTFM returned nothing, or (b) you need exact line numbers for editing
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
