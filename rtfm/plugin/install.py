"""Orchestration for `rtfm init` — sets up RTFM in a project."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from rtfm.plugin.discover import discover
from rtfm.plugin.claude_md import inject_claude_md


def generate_mcp_json(db_path: str = ".rtfm/library.db") -> dict:
    """Generate the MCP server configuration block for RTFM.

    Args:
        db_path: Relative path to the database file.

    Returns:
        Dict suitable for merging into .mcp.json.
    """
    python = sys.executable
    return {
        "mcpServers": {
            "rtfm": {
                "command": python,
                "args": ["-m", "rtfm.mcp"],
                "env": {
                    "RTFM_DB": db_path,
                },
            }
        }
    }


def write_mcp_json(project_root: str | Path, db_path: str = ".rtfm/library.db") -> str:
    """Write or merge the RTFM entry into the project's .mcp.json.

    If .mcp.json exists, merges the rtfm server into the existing
    mcpServers dict without overwriting other entries.

    Args:
        project_root: Project root directory.
        db_path: Relative path to the database.

    Returns:
        One of "created", "merged", or "skipped".
    """
    project_root = Path(project_root)
    mcp_path = project_root / ".mcp.json"
    new_block = generate_mcp_json(db_path)

    if mcp_path.exists():
        existing = json.loads(mcp_path.read_text(encoding="utf-8"))

        servers = existing.get("mcpServers", {})
        if "rtfm" in servers:
            return "skipped"

        servers.update(new_block["mcpServers"])
        existing["mcpServers"] = servers
        mcp_path.write_text(
            json.dumps(existing, indent=2) + "\n",
            encoding="utf-8",
        )
        return "merged"
    else:
        mcp_path.write_text(
            json.dumps(new_block, indent=2) + "\n",
            encoding="utf-8",
        )
        return "created"


def init_project(
    project_root: str | Path,
    db_path: Optional[str] = None,
    corpus: str = "default",
    install_hook: bool = False,
    no_embeddings: bool = False,
) -> dict:
    """Initialize RTFM in a project.

    Sequence:
    1. Create DB in .rtfm/library.db (default)
    2. Run discover() for a quick project map
    3. Write/merge .mcp.json
    4. Inject instructions into CLAUDE.md
    5. Optionally install Claude Code hook
    6. Sync entry-point docs (README, CLAUDE.md — not the whole project)

    Args:
        project_root: Project root directory.
        db_path: Override database path (default: .rtfm/library.db).
        corpus: Corpus name for indexed documents.
        install_hook: Install Claude Code UserPromptSubmit hook.
        no_embeddings: Skip embedding generation during sync.

    Returns:
        Summary dict with results of each step.
    """
    from rtfm.core.library import Library
    from rtfm.core.sync import sync

    project_root = Path(project_root).resolve()
    rel_db = db_path or ".rtfm/library.db"
    abs_db = project_root / rel_db

    summary: dict = {"project_root": str(project_root)}

    # 1. Create library
    abs_db.parent.mkdir(parents=True, exist_ok=True)
    lib = Library(abs_db)
    summary["db_path"] = str(abs_db)

    # 2. Discover project
    project_info = discover(project_root)
    summary["discover"] = {
        "total_files": project_info["total_files"],
        "languages": project_info["languages"],
        "entry_points": project_info["entry_points"],
    }

    # 3. Write .mcp.json
    mcp_result = write_mcp_json(project_root, rel_db)
    summary["mcp_json"] = mcp_result

    # 4. Inject CLAUDE.md
    claude_result = inject_claude_md(project_root)
    summary["claude_md"] = claude_result

    # 5. Optionally install hook
    if install_hook:
        from rtfm.plugin.hooks import install_hook as _install
        hook_result = _install(project_root)
        summary["hook"] = hook_result
    else:
        summary["hook"] = "skipped"

    # 6. Sync entry-point docs
    entry_files = []
    for ep in project_info["entry_points"]:
        ep_path = project_root / ep
        if ep_path.exists() and ep_path.suffix in {".md", ".txt", ".toml"}:
            entry_files.append(str(ep_path))

    if entry_files:
        result = sync(
            library=lib,
            root=project_root,
            corpus=corpus,
            files=entry_files,
            generate_embeddings=not no_embeddings,
        )
        summary["sync"] = {
            "added": result.added,
            "files": entry_files,
        }
    else:
        summary["sync"] = {"added": 0, "files": []}

    lib.close()
    return summary
