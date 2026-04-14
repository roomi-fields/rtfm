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


def _enable_mcp_in_settings(project_root: Path) -> str:
    """Ensure 'rtfm' is listed in enabledMcpjsonServers in Claude Code settings.

    Checks both .claude/settings.json and .claude/settings.local.json.
    Adds 'rtfm' to enabledMcpjsonServers if the key exists but rtfm is missing,
    or creates the key if the settings file exists without it.

    Returns:
        One of "enabled", "already enabled", or "no settings".
    """
    enabled_any = False
    already = True

    for filename in ("settings.json", "settings.local.json"):
        settings_path = project_root / ".claude" / filename
        if not settings_path.exists():
            continue

        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        servers = data.get("enabledMcpjsonServers")
        if servers is None:
            # Key doesn't exist yet — add it
            data["enabledMcpjsonServers"] = ["rtfm"]
            settings_path.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            enabled_any = True
            already = False
        elif "rtfm" not in servers:
            servers.insert(0, "rtfm")
            settings_path.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            enabled_any = True
            already = False

    if already and not enabled_any:
        # Check if rtfm was already in all existing settings
        for filename in ("settings.json", "settings.local.json"):
            settings_path = project_root / ".claude" / filename
            if settings_path.exists():
                try:
                    data = json.loads(settings_path.read_text(encoding="utf-8"))
                    if "rtfm" in data.get("enabledMcpjsonServers", []):
                        return "already enabled"
                except (json.JSONDecodeError, OSError):
                    pass
        return "no settings"

    return "enabled" if enabled_any else "no settings"


def init_project(
    project_root: str | Path,
    db_path: Optional[str] = None,
    corpus: str = "default",
    install_hook: bool = True,
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

    # 3b. Enable rtfm in Claude Code settings
    settings_result = _enable_mcp_in_settings(project_root)
    summary["claude_settings"] = settings_result

    # 4. Inject CLAUDE.md
    claude_result = inject_claude_md(project_root)
    summary["claude_md"] = claude_result

    # 5. Install auto-sync hook (default: yes)
    if not install_hook:
        summary["hook"] = "skipped"
    else:
        from rtfm.plugin.hooks import install_hook as _install
        hook_result = _install(project_root, corpus=corpus)
        summary["hook"] = hook_result

    # 6. Add .rtfm/ to .gitignore
    gitignore_path = project_root / ".gitignore"
    rtfm_pattern = ".rtfm/"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if rtfm_pattern not in content:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                f.write(f"\n# RTFM local database\n{rtfm_pattern}\n")
            summary["gitignore"] = "appended"
        else:
            summary["gitignore"] = "already present"
    else:
        gitignore_path.write_text(
            f"# RTFM local database\n{rtfm_pattern}\n",
            encoding="utf-8",
        )
        summary["gitignore"] = "created"

    # 7. Register project as a source in config
    from rtfm.config import add_source
    add_source(project_root, str(project_root), corpus=corpus)

    # 8. Sync entry-point docs
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

    # 9. Detect optional-extras opportunities and add hints to the summary
    summary["hints"] = _collect_extras_hints(project_root)

    lib.close()
    return summary


def _collect_extras_hints(project_root: Path) -> list[str]:
    """Look for signals that a user would benefit from an optional extra.

    Returns a list of human-readable hints (may be empty). Hints appear in
    the CLI output after `rtfm init` so the user learns about relevant extras
    at the moment they would actually use them.
    """
    hints: list[str] = []

    try:
        import fastembed  # noqa: F401
        has_embeddings = True
    except ImportError:
        has_embeddings = False

    try:
        import pdftext  # noqa: F401
        has_pdf = True
    except ImportError:
        has_pdf = False

    # PDF files → suggest [pdf] extra
    if not has_pdf:
        pdf_count = sum(1 for _ in project_root.rglob("*.pdf"))
        if pdf_count > 0:
            hints.append(
                f"💡 Found {pdf_count} PDF file{'s' if pdf_count > 1 else ''} — "
                f"install `pip install rtfm-ai[pdf]` to index them."
            )

    # Large corpus → suggest [embeddings] extra for semantic search
    if not has_embeddings:
        total = sum(1 for _ in project_root.rglob("*")
                    if _.is_file() and _.suffix in {".md", ".py", ".txt", ".rst"})
        if total > 200:
            hints.append(
                f"💡 Your project has {total}+ text files — `pip install rtfm-ai[embeddings]` "
                f"adds semantic search for paraphrase queries (FTS handles exact matches)."
            )

    return hints
