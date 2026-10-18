#!/usr/bin/env python3
"""Keep the countable claims in the docs equal to what the code does.

``sync_version.py`` keeps the version string in step; this keeps the facts:
how many parsers ship, how many MCP tools exist. Both drifted silently — the
same release said 10, 15, 22 and 24 parsers depending on the page, and AI
answer engines quote whichever figure they read first.

It also checks coverage: every built-in parser must have its section in the
parsers guide, every extension it reads must be named there, and every MCP
tool must be in the README's tool table. A new parser or tool that nobody
documents fails the tests instead of going unnoticed.

The facts are read from the source (AST), not by importing the parsers:
optional ones register only when their extra is installed, and the count
must not depend on the machine that runs the check.

Usage:
  python scripts/sync_facts.py          # rewrite drifted claims in place
  python scripts/sync_facts.py --check  # exit 1 on drift or a coverage gap
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def builtin_parsers() -> list[tuple[str, str, list[str]]]:
    """``[(class name, module path, extensions)]`` of every built-in parser."""
    found = []
    for path in sorted((ROOT / "rtfm" / "parsers").glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(ast.unparse(d) == "ParserRegistry.register"
                       for d in node.decorator_list):
                continue
            exts: list[str] = []
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign)
                        and any(getattr(t, "id", None) == "extensions" for t in stmt.targets)):
                    exts = [e.lower() for e in ast.literal_eval(stmt.value)]
            found.append((node.name, path.relative_to(ROOT).as_posix(),
                          sorted(set(exts))))
    return found


def mcp_tools() -> tuple[list[str], list[str]]:
    """``(every tool, the tools of the default runtime profile)``."""
    every, runtime = [], []
    for node in ast.parse((ROOT / "rtfm" / "mcp.py").read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        decorators = {ast.unparse(d) for d in node.decorator_list}
        if "mcp.tool()" in decorators:
            every.append(node.name)
            runtime.append(node.name)
        elif "_admin_tool()" in decorators:
            every.append(node.name)
    return sorted(every), sorted(runtime)


PARSERS = builtin_parsers()
TOOLS, RUNTIME_TOOLS = mcp_tools()
P, T, R = len(PARSERS), len(TOOLS), len(RUNTIME_TOOLS)

# Each rule rewrites the number inside a phrase, never the phrase itself.
TARGETS: dict[str, list[tuple[str, str]]] = {
    "README.md": [
        (r"\*\*\d+ parsers built-in\*\*", f"**{P} parsers built-in**"),
        (r"\*\*\d+ MCP tools\*\*", f"**{T} MCP tools**"),
    ],
    ".claude/CLAUDE.md": [
        (r"Ships with \d+ parsers", f"Ships with {P} parsers"),
        (r"— \d+ document parsers", f"— {P} document parsers"),
    ],
    "docs/index.md": [
        (r"Use \d+ built-in parsers", f"Use {P} built-in parsers"),
        (r"All\n  \d+ formats with parsing strategies", f"All\n  {P} formats with parsing strategies"),
    ],
    "docs/parsers.md": [
        (r"Parsers Guide — \d+ built-in formats", f"Parsers Guide — {P} built-in formats"),
        (r"RTFM's \d+ built-in parsers", f"RTFM's {P} built-in parsers"),
    ],
    "docs/positioning.md": [
        (r"- \d+ built-in format parsers", f"- {P} built-in format parsers"),
    ],
    "docs/architecture.md": [
        (r"^\d+ built-in parsers, extensible", f"{P} built-in parsers, extensible"),
    ],
    "docs/obsidian-vault-guide.md": [
        (r"\| \d+ parsers \(MD", f"| {P} parsers (MD"),
    ],
    "docs/rag-fundamentals.md": [
        (r"Structural \(\d+ parsers, AST-aware\)", f"Structural ({P} parsers, AST-aware)"),
    ],
    "docs/llms.txt": [
        (r"\d+ built-in parsers", f"{P} built-in parsers"),
        (r"\d+ MCP tools", f"{T} MCP tools"),
    ],
    "docs/PUBLISH_MCP_DIRECTORIES.md": [
        (r"\d+ built-in parsers", f"{P} built-in parsers"),
    ],
    "server.json": [
        (r"in SQLite; \d+ parsers, served via MCP", f"in SQLite; {P} parsers, served via MCP"),
    ],
    "rtfm/mcp.py": [
        (r'"runtime" \(default\) : \d+ retrieval tools', f'"runtime" (default) : {R} retrieval tools'),
        (r'"admin" / "all"     : all \d+ tools', f'"admin" / "all"     : all {T} tools'),
    ],
}


def coverage_gaps() -> list[str]:
    gaps = []
    guide = (ROOT / "docs" / "parsers.md").read_text(encoding="utf-8")
    sections = set(re.findall(r"^### .*\(`(rtfm/parsers/[\w/]+\.py)`\)", guide, re.MULTILINE))
    named = set(re.findall(r"`(\.\w+)`", guide))
    for cls, module, exts in PARSERS:
        if module not in sections:
            gaps.append(f"docs/parsers.md has no section for {cls} ({module})")
        missing = [e for e in exts if e not in named]
        if missing:
            gaps.append(f"docs/parsers.md does not name {cls}'s {', '.join(missing)}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table = set(re.findall(r"^\| `(rtfm_\w+)`", readme, re.MULTILINE))
    for tool in TOOLS:
        if tool not in table:
            gaps.append(f"README.md tool table lacks {tool}")
    return gaps


def main() -> int:
    check = "--check" in sys.argv[1:]
    drifted = []
    for rel, rules in TARGETS.items():
        path = ROOT / rel
        if not path.exists():
            continue        # a local-only note (git-ignored), absent in CI
        text = path.read_text(encoding="utf-8")
        new = text
        for pattern, repl in rules:
            new, n = re.subn(pattern, repl, new, flags=re.MULTILINE)
            if n == 0:
                # A rule that matches nothing guards nothing: the phrase was
                # reworded, and the claim is no longer watched.
                drifted.append(f"{rel}: no phrase matches {pattern!r}")
        if new != text:
            drifted.append(f"{rel}: figures out of date")
            if not check:
                path.write_text(new, encoding="utf-8")
                print(f"→ updated {rel}")

    gaps = coverage_gaps()
    for line in gaps:
        print(f"✗ {line}", file=sys.stderr)
    print(f"{P} parsers · {T} MCP tools ({R} by default)")

    if check and drifted:
        for line in drifted:
            print(f"✗ {line}", file=sys.stderr)
        print("Run: python scripts/sync_facts.py", file=sys.stderr)
        return 1
    if not check:
        lost = [d for d in drifted if "no phrase matches" in d]
        for line in lost:
            print(f"✗ {line}", file=sys.stderr)
        if lost:
            return 1
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
