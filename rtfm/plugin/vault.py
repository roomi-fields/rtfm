"""Obsidian vault integration — first-class vault support for RTFM."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional


# Folders to never propose as corpora
_EXCLUDE_DIRS = {
    "templates", "archive", ".trash", "_assets", ".obsidian",
    "_rtfm", ".rtfm", ".claude", ".git", ".stfolder", ".smart-env",
    "node_modules", ".venv", "venv", "__pycache__",
}


def _slugify(name: str) -> str:
    """Convert a folder name to a corpus slug."""
    s = name.lower().strip("_").replace(" ", "-")
    s = re.sub(r"[^\w\-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def detect_obsidian_vault(path: Path) -> dict | None:
    """Check if path is an Obsidian vault.

    Args:
        path: Directory to check.

    Returns:
        Vault info dict or None if not a vault.
    """
    path = Path(path).resolve()
    if (path / ".obsidian").is_dir():
        return {"root": path, "name": path.name}
    return None


def propose_corpus_mapping(vault_path: Path) -> list[dict]:
    """Analyze vault folder structure and propose corpus mappings.

    Each top-level folder with >5 .md files becomes a corpus candidate.
    Root-level .md files become a "root" corpus if there are any.

    Args:
        vault_path: Path to the Obsidian vault root.

    Returns:
        List of dicts with path, corpus, file_count.
    """
    vault_path = Path(vault_path).resolve()
    mapping: list[dict] = []

    # Root-level .md files
    root_md = [f for f in vault_path.iterdir()
               if f.is_file() and f.suffix.lower() == ".md"]
    if len(root_md) > 0:
        mapping.append({
            "path": str(vault_path),
            "corpus": "root",
            "file_count": len(root_md),
        })

    # Top-level directories
    for item in sorted(vault_path.iterdir()):
        if not item.is_dir():
            continue
        if item.name.lower() in _EXCLUDE_DIRS or item.name.startswith("."):
            continue

        md_count = sum(1 for _ in item.rglob("*.md"))
        if md_count >= 5:
            mapping.append({
                "path": str(item),
                "corpus": _slugify(item.name),
                "file_count": md_count,
            })

    return mapping


def init_vault(
    vault_path: Path,
    corpus_mapping: list[dict] | None = None,
    no_embeddings: bool = False,
    generate_output: bool = True,
) -> dict:
    """Initialize RTFM in an Obsidian vault.

    Steps:
    1. Validate .obsidian/ exists
    2. Create .rtfm/ in vault root
    3. Auto-detect corpus mapping (or use provided)
    4. Register each corpus as a source in config.json
    5. Set vault_type: "obsidian" in config.json
    6. Write .mcp.json
    7. Inject CLAUDE.md (vault mode with wikilinks)
    8. Add _rtfm/ and .rtfm/ to .gitignore
    9. Initial sync of all corpora
    10. Generate _rtfm/ output files

    Args:
        vault_path: Path to the Obsidian vault root.
        corpus_mapping: Override auto-detected corpus mapping.
        no_embeddings: Skip embedding generation.
        generate_output: Generate _rtfm/ output files.

    Returns:
        Summary dict with results of each step.
    """
    from rtfm.config import add_source, load_config, save_config
    from rtfm.core.library import Library
    from rtfm.core.sync import sync
    from rtfm.plugin.claude_md import inject_claude_md
    from rtfm.plugin.install import write_mcp_json, _enable_mcp_in_settings

    vault_path = Path(vault_path).resolve()
    summary: dict = {"vault_root": str(vault_path)}

    # 1. Validate
    if not (vault_path / ".obsidian").is_dir():
        summary["error"] = "No .obsidian/ directory found"
        return summary

    # 2. Create .rtfm/
    db_path = vault_path / ".rtfm" / "library.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lib = Library(db_path)
    summary["db_path"] = str(db_path)

    # 3. Corpus mapping
    if corpus_mapping is None:
        corpus_mapping = propose_corpus_mapping(vault_path)
    summary["corpora"] = [
        {"corpus": m["corpus"], "file_count": m["file_count"]}
        for m in corpus_mapping
    ]

    # 4. Register sources + set vault_type
    config = load_config(vault_path)
    config["vault_type"] = "obsidian"
    save_config(vault_path, config)

    for m in corpus_mapping:
        add_source(vault_path, m["path"], corpus=m["corpus"])

    # 5. Write .mcp.json
    mcp_result = write_mcp_json(vault_path, ".rtfm/library.db")
    summary["mcp_json"] = mcp_result

    # 5b. Enable in Claude Code settings
    settings_result = _enable_mcp_in_settings(vault_path)
    summary["claude_settings"] = settings_result

    # 6. Inject CLAUDE.md (vault mode)
    claude_result = inject_claude_md(vault_path, vault_mode=True)
    summary["claude_md"] = claude_result

    # 7. Add to .gitignore
    gitignore_path = vault_path / ".gitignore"
    patterns = [".rtfm/", "_rtfm/"]
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        added = []
        for pat in patterns:
            if pat not in content:
                added.append(pat)
        if added:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                f.write("\n# RTFM\n")
                for pat in added:
                    f.write(f"{pat}\n")
            summary["gitignore"] = f"appended {added}"
        else:
            summary["gitignore"] = "already present"
    else:
        gitignore_path.write_text(
            "# RTFM\n" + "\n".join(patterns) + "\n",
            encoding="utf-8",
        )
        summary["gitignore"] = "created"

    # 8. Sync all corpora
    sync_summary = {}
    for m in corpus_mapping:
        src_path = Path(m["path"])
        try:
            result = sync(
                library=lib,
                root=src_path,
                corpus=m["corpus"],
                generate_embeddings=not no_embeddings,
            )
            sync_summary[m["corpus"]] = {
                "added": result.added,
                "errors": len(result.errors),
            }
        except Exception as exc:
            sync_summary[m["corpus"]] = {"error": str(exc)}
            print(f"[vault] sync error for {m['corpus']}: {exc}", file=sys.stderr)
    summary["sync"] = sync_summary

    # 9. Generate _rtfm/ output
    if generate_output:
        try:
            from rtfm.plugin.vault_output import generate_vault_output
            config = load_config(vault_path)
            output_result = generate_vault_output(lib, vault_path, config)
            summary["output"] = output_result
        except Exception as exc:
            summary["output"] = {"error": str(exc)}
            print(f"[vault] output generation error: {exc}", file=sys.stderr)

    lib.close()
    return summary
