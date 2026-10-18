---
date: 2026-10-18
authors: [romain]
title: "Your CLAUDE.md Is Too Long: Let the Agent Search Your Docs Instead"
description: >-
  Why a long CLAUDE.md costs you on every session, and how to keep it to a few lines
  while the agent finds your architecture notes, specs and decisions on demand.
slug: claude-md-too-long
---

# Your CLAUDE.md Is Too Long: Let the Agent Search Your Docs Instead

Your CLAUDE.md started as ten lines. Now it holds the architecture, the deploy steps, the naming rules, three past incidents and a glossary, and Claude Code still seems to ignore half of it. The fix is not a better-worded instructions file; it is a shorter one, with the rest of your docs made searchable so the agent pulls in the section it needs, when it needs it.

<!-- more -->

## Why does a long CLAUDE.md stop working?

Claude Code loads `CLAUDE.md` into the context at the start of every session. That is its job: standing instructions the agent should always have. Everything in it is paid for in every session, whether the task touches it or not.

As the file grows, three things happen:

- **Every session gets more expensive.** A few thousand tokens of reference material ride along on a one-line bug fix.
- **The important rules get diluted.** "Never push to main" sits between a paragraph on the build system and a table of environment variables. Instructions compete for attention with reference material.
- **It goes stale.** Docs copied into CLAUDE.md drift from the real docs in `docs/`, and now there are two versions of the truth.

Splitting the file with imports does not change the bill: imported files are loaded too. Moving text around inside the instructions file does not make it smaller.

## What should stay in CLAUDE.md?

A useful test: does the agent need this in *every* session, or only when it works on a specific area?

**Keep in CLAUDE.md:**

- Hard rules (what never to do, how to commit, which commands need approval).
- How to run tests and build.
- Where things live, in a few lines.
- How to find the rest.

**Move out to normal docs:**

- Architecture explanations, design decisions, ADRs.
- API references, data schemas, file formats.
- Runbooks, incident write-ups, onboarding notes.
- Anything longer than a screen that only matters for one part of the code.

Those docs probably already exist in `docs/`, a wiki export, or a folder of PDFs. The problem is that the agent does not know they are there, or has to open them one by one to find out.

## Why not just let the agent grep the docs?

It does, and it usually finds what it needs. An agent with file tools can list `docs/`, grep for a term, open a few candidates and read them.

The cost is the path to the answer. Each listing, grep and file read is a tool call, and each file it opens to check relevance goes into the context window, whether it turns out useful or not. On a handful of Markdown files that is negligible. On a few hundred files, or on PDFs and Word documents that grep cannot read at all, it adds up in calls, tokens and time.

## How do you make docs searchable for Claude Code?

[RTFM](https://github.com/roomi-fields/rtfm) builds a local search index of the project (one SQLite file in `.rtfm/`) and exposes it to the agent as MCP tools.

```bash
pip install rtfm-ai        # or: pipx install rtfm-ai
cd your-project
rtfm init
rtfm sync
```

`rtfm init` creates `.rtfm/library.db`, writes the MCP server entry to `.mcp.json`, installs an auto-sync hook so the index follows your edits, adds `.rtfm/` to `.gitignore`, and appends a short section to your `CLAUDE.md`. If you use the Claude Code plugin instead, the same setup happens automatically the first time you use it in a project.

If your docs live outside the repository, register them as a separate source:

```bash
rtfm add ~/company-wiki-export --corpus wiki
rtfm sync
```

Markdown is split by headings, so a search hit points at a section, not a whole file. PDFs, Word and OpenDocument files, EPUB, LaTeX, YAML, JSON, CSV and others are parsed too (some need an optional extra, see the [parsers guide](../../parsers.md)).

## What does `rtfm init` add to CLAUDE.md?

Exactly this, appended once (it is skipped if an `## RTFM` section is already there):

```markdown
## RTFM — Indexed Knowledge Base

This project has been indexed with RTFM.

For any **exploratory search** (finding which files/modules/classes are relevant
to a topic), use `rtfm_search` instead of Glob, find, ls, or broad Grep.
Then use `rtfm_expand` to read easily most relevant files/sections.
```

Seven lines. That is the whole point: the instructions file tells the agent *how to find* the documentation, instead of *containing* it. You can then cut the reference material out of your CLAUDE.md and keep it in `docs/`, where it belongs.

To be precise about what this is: it is an instruction, like everything else in CLAUDE.md. The agent follows it most of the time, and will still reach for grep when it already knows the exact file or string. That is fine; grep is the right tool for an exact identifier in a known place.

## What does the agent get back?

Search results are metadata first: paths, line ranges, section names. No content. An illustrative example of what `rtfm_search` returns on a project with architecture docs and ADRs (paths invented for the example):

```text
3 sources for "payment retry policy":

/home/you/acme/docs/architecture/payments.md L88-131 (Retries and idempotency)
/home/you/acme/docs/adr/0012-retry-backoff.md L1-42 (Decision)
/home/you/acme/src/payments/retry.py L14-67 (class RetryPolicy)
```

A handful of hits like this is in the order of a few hundred tokens. The agent picks one and reads just that section:

```text
rtfm_expand(source="/home/you/acme/docs/adr/0012-retry-backoff.md", target="Decision")
```

`rtfm_expand` can jump to a section by name or to a line (`"L120"`), and returns one chunk at a time unless asked for more. The rest of the ADR, and the other forty ADRs, never enter the context.

Compare that with the long CLAUDE.md, where the payments section, the deploy runbook and the glossary are all loaded before the agent even reads the task.

## A before and after

**Before:** a 600-line CLAUDE.md with the architecture overview, every ADR summarised, the full environment variable table and the release procedure.

**After:**

```markdown
# Acme API

## Rules
- Run `make test` before every commit. Never push to main.
- Database migrations need human review.

## Layout
- src/ service code, docs/ architecture and ADRs, ops/ runbooks.

## RTFM — Indexed Knowledge Base
(the section above, added by `rtfm init`)
```

The ADRs, the runbooks and the variable table still exist, in `docs/` and `ops/`, indexed. The agent gets to them through search when the task calls for it.

## When should you NOT do this?

- **Small projects.** If your docs fit in a few short files, a slightly longer CLAUDE.md or plain grep is fine. On a small codebase, RTFM is mostly overhead.
- **Rules the agent must always see.** Do not move a hard constraint into a doc and hope the agent searches for it. If breaking it is costly, it belongs in CLAUDE.md.
- **Docs that are wrong.** Search makes stale docs easier to find, not more correct. Indexing an outdated wiki gives the agent confident, outdated answers.
- **Exact-identifier lookups.** For "where is `RetryPolicy` defined", grep or the editor's symbol search is as good and needs nothing installed.

## Try it

With the Claude Code plugin:

```text
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

Or with pip, for Claude Code, Cursor, Codex or any MCP client:

```bash
pip install rtfm-ai
cd your-project && rtfm init && rtfm sync
```

Claude Code picks up the `.mcp.json` that `rtfm init` writes; for Cursor, Codex and other clients, point their MCP configuration at the `rtfm-serve` command. Cursor reads its own rules files rather than CLAUDE.md, so put the same short instruction there.

For PDFs and Office documents, add the matching extra (`/rtfm:install-pdf` in the plugin, or `pip install "rtfm-ai[pdf,office]"`; the pip `pdf` extra includes marker-pdf, a large download). Then trim your CLAUDE.md down to the rules, and let the docs be docs. For when full-text search is enough and when embeddings help, see [RTFM vs vector RAG](../../comparisons/vs-vector-rag.md).
