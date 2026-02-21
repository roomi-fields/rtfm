"""CLAUDE.md injection — adds RTFM instructions to a project's CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

RTFM_MARKER = "## RTFM"

RTFM_TEMPLATE = """## RTFM — Project Knowledge Base

This project has an indexed knowledge base. RTFM indexes docs, code, specs, and past learnings.

### Workflow: RTFM first, then Read

**Step 1 — Ask RTFM** (always start here for any research):
```
rtfm_context("subject")   → metadata with file paths
rtfm_search("query")      → same, different ranking
```
To find ANY file or document, ALWAYS use rtfm_search — never Glob.

**Step 2 — Read the files** (RTFM gave you the paths):
```
Read(file_path)            → use the absolute path from Step 1
```

**Step 3 — Edit** (only when you know exactly which file/line):
Use Grep to find the exact line, then Edit.

**When to use `rtfm_expand` instead of Read:**
Only for sources with no file path (e.g. learned corpus entries with a `slug:` instead of `file:`).

### Rules (IMPORTANT)
- To find files: rtfm_search. NEVER Glob for research.
- After Read: do NOT rtfm_expand the same source.
- Never Read the same file twice in one session.
- Glob/Grep: ONLY for editing (finding a line to change). Not for research.
- Save any significant finding (web search, external API, decision) to a scratch file — it will be auto-indexed.
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
