"""Serialize an MRCR conversation into per-turn Markdown files for RTFM indexing.

Layout per sample:

    sample_<idx>/
    └── conv/
        ├── 0001_user.md
        ├── 0002_assistant.md
        └── ...

One file per turn keeps each turn an independent RTFM chunk parent and lets the
markdown parser's natural header-split create sub-chunks. Filenames are
zero-padded so alphabetical order matches conversation order.
"""

from pathlib import Path


def serialize_turns(turns: list[dict], out_dir: Path) -> int:
    """Write each turn to its own .md file under out_dir/conv/.

    Returns the number of files written.
    """
    conv_dir = out_dir / "conv"
    conv_dir.mkdir(parents=True, exist_ok=True)

    for i, turn in enumerate(turns, start=1):
        role = turn["role"]
        content = turn["content"]
        # Front-matter + header so markdown parser sees structure
        md = (
            f"---\nturn: {i}\nrole: {role}\n---\n\n"
            f"# Turn {i} ({role})\n\n"
            f"{content}\n"
        )
        (conv_dir / f"{i:04d}_{role}.md").write_text(md, encoding="utf-8")

    return len(turns)
