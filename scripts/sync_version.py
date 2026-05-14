#!/usr/bin/env python3
"""Propagate the version from pyproject.toml to the distribution manifests.

``pyproject.toml`` ``[project].version`` is the single source of truth.
Mirrors kept in sync:
  - ``server.json``                 ("version" appears twice: root + packages[0])
  - ``.claude-plugin/plugin.json``   ("version" once)

The CHANGELOG is deliberately *not* a mirror — it is append-only history.

Usage:
  python scripts/sync_version.py          # rewrite the mirrors from pyproject
  python scripts/sync_version.py --check  # verify, exit 1 on drift (CI release gate)

Per the MCP project PLAYBOOK §2.4: regex-replace the target field, never
``json.load`` + ``json.dump`` — reformatting produces phantom drift on every run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
MIRRORS = [
    ROOT / "server.json",
    ROOT / ".claude-plugin" / "plugin.json",
]

# matches a JSON `"version": "x.y.z"` field, capturing the value
VERSION_FIELD = re.compile(r'("version":\s*")([^"]*)(")')


def source_version() -> str:
    """Read ``[project].version`` from pyproject.toml."""
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit("sync_version: could not find [project].version in pyproject.toml")
    return m.group(1)


def main() -> int:
    check = "--check" in sys.argv[1:]
    version = source_version()
    drift: list[tuple[Path, list[str]]] = []

    for path in MIRRORS:
        text = path.read_text(encoding="utf-8")
        found = [m.group(2) for m in VERSION_FIELD.finditer(text)]

        if check:
            if not found or any(v != version for v in found):
                drift.append((path, found))
        else:
            new = VERSION_FIELD.sub(rf"\g<1>{version}\g<3>", text)
            rel = path.relative_to(ROOT)
            if new != text:
                path.write_text(new, encoding="utf-8")
                print(f"sync_version: updated {rel} -> {version}")
            else:
                print(f"sync_version: {rel} already at {version}")

    if check:
        if drift:
            print(f"sync_version: DRIFT — pyproject.toml is {version}, but:")
            for path, found in drift:
                print(f"  {path.relative_to(ROOT)}: {found or '(no version field)'}")
            return 1
        print(f"sync_version: OK — all mirrors at {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
