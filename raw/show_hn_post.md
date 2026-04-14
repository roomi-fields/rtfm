# Show HN Post — RTFM

## Title

Show HN: RTFM – Open-source retrieval layer for AI agents (MCP, SQLite, 10 parsers)

## URL

https://github.com/roomi-fields/rtfm

## Text (if no URL, or to add context — HN allows both)

I built RTFM because my coding agent kept getting lost in large projects. On an 8,260-file repo, Claude Code spent 38% of its actions just grepping and reading files — not coding. The bigger the project, the worse it gets.

RTFM is a retrieval layer that sits between your AI agent and your codebase (or any knowledge base). It uses SQLite + FTS5, runs locally, no cloud, no API keys.

How it works:

1. `pip install rtfm-ai && rtfm init` — indexes your project in 10-78 seconds
2. Agent calls `rtfm_search("validation module")` → gets 5 results with file paths and scores (~300 tokens)
3. Agent reads only the files it needs — progressive disclosure instead of dumping everything into context

What makes it different from code indexers (Augment, Sourcegraph, Code-Index-MCP):

- **10 parsers**: Markdown, Python (AST), LaTeX, PDF, YAML, JSON, Shell, XML, HTML, plaintext. Extensible in ~50 lines.
- **Not code-only**: indexes docs, specs, legal texts, research — same tool for everything in your project
- **Knowledge graph**: resolves [[wikilinks]] and Python imports as graph edges, hub detection, centrality ranking
- **Obsidian integration**: `rtfm vault` generates navigable `_rtfm/` files inside your vault

I ran a controlled benchmark on FeatureBench (ICLR 2026) — 11 tasks, 4 repos, 4 conditions (with/without retrieval, with/without file paths in prompts):

- On mlflow (8,260 files): resolve rate went from 55-64% → 100% with RTFM
- On metaflow (624 files): no measurable gain — grep is enough for small repos
- Token consumption: -61%, cost: -51% on real documentation tasks

The agent decides on its own when to search. No forced retrieval. Works with any MCP client (Claude Code, Cursor, Codex).

MIT licensed. Python 3.10+. Single SQLite file, no external dependencies.

---

## Posting notes

- **Best time**: Tuesday or Wednesday, 14:00-15:00 UTC (morning EST, US audience waking up)
- **Be online** for 2-3 hours after posting to reply to every comment
- **Don't** use marketing language. HN values technical depth and honesty about limitations
- **Do** mention the benchmark honestly including where RTFM doesn't help (small repos)
- **Do** engage with criticism constructively — HN rewards humility
- **Don't** ask friends to upvote — HN detects and penalizes vote rings
