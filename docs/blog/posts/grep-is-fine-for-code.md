---
date: 2026-10-18
authors: [romain]
title: Grep Is Fine for Code. It Struggles with Everything Else in Your Repo
description: >-
  Why Claude Code keeps grepping, where that habit is the right call, and where it burns tokens: docs, specs, PDFs and notes with no exact string to match.
slug: grep-is-fine-for-code
---

# Grep Is Fine for Code. It Struggles with Everything Else in Your Repo

If you have watched Claude Code grep the same folders again and again, you have probably wondered whether a smarter search tool would stop the agent burning tokens exploring your codebase. For code, often it would not: grep is very good at finding identifiers. The cost shows up elsewhere, on the docs, specs, PDFs, decision records and notes that sit next to the code, where there is no exact string to search for.

<!-- more -->

## Why does Claude Code keep grepping?

Because grep works, and the models know it. Coding agents are trained on countless sessions where `grep -rn "def authenticate"` gets straight to the answer. When an agent is unsure, it goes back to the tool it trusts. Several people pointed this out in the Hacker News threads about code-search MCP servers: give an agent a new search tool and it often falls back to grep anyway.

That fallback is reasonable for code. A function name, a class, an error message, a config key: each is an exact string that appears in the file you want. One grep call, a few lines of output, then a targeted read. It is hard to beat.

So this post is not "grep is broken". It is about where grep's assumption — *the thing you want contains the words you know* — stops holding.

## Where does the grep habit get expensive?

### When the knowledge is written in prose

Ask an agent "what did we decide about retrying failed webhooks?" The answer might be in `docs/adr/0012-delivery-guarantees.md`, under a heading called "Consequences", phrased as "at-least-once delivery with exponential backoff". The word "retry" may not appear at all.

The agent will still get there. It greps for `retry`, then `webhook`, then lists `docs/`, opens three or four files that look likely, and reads them in full. Each step is cheap on its own. Together they are a chain of calls, and every file read lands whole in the context window — including the large parts that had nothing to do with the question.

### When the text is not plain text

grep matches bytes. A PDF stores its text in compressed streams, and `.docx`, `.odt` and `.epub` files are zip archives. grep has nothing it can match inside them, so the agent has to open those files one by one to learn what they contain. In a repo with a `specs/` folder of PDFs, or a contract and a vendor manual next to the code, that is where tokens go.

### When the repo is large and mixed

In a big monorepo, or a project that holds code plus a notes vault plus datasets, even a good grep returns a long list of matches. The agent has to read through it, refine the pattern, and try again. The cost is not in finding the right file eventually — it does. It is in the number of steps and the volume of text it pulls in on the way.

## What do the code-search tools already cover?

This space is crowded, and for good reason. Serena gives agents symbol-level navigation through language servers: definitions, references, safe edits. Tools such as Semble, jCodeMunch and code-index-mcp index source code so agents can retrieve functions and symbols without reading whole files. If your problem is purely "the agent wastes time navigating a large codebase", start with one of them. For finding the callers of a function or renaming a symbol, a language-server tool is the better choice than RTFM.

RTFM aims at a different gap: **the non-code half of the repo**, and repos where code and documents live together.

## How does RTFM handle docs, specs and PDFs?

RTFM indexes the whole project into one local SQLite file. Each format has a parser that splits files along their own structure: Markdown by heading, Python by class and function, PDF by page, DOCX, ODT and EPUB by section, LaTeX by section, Jupyter notebooks by cell group, CSV and XLSX as tables. The [parsers guide](../../parsers.md) lists every format.

Search is full-text by default (SQLite FTS5 with BM25 ranking and stemming). A multi-word query matches any of its words, and sections that contain more of them rank higher. So "retry failed webhooks" can surface a section about "retried deliveries" even if no line contains the exact phrase. If you install the optional embeddings, semantic and hybrid modes also catch paraphrases that share no words at all.

The agent gets two main tools:

- `rtfm_search` returns ranked file paths, line ranges and section names — no content.
- `rtfm_expand` reads one file, and can jump straight to a section (`target="Consequences"` or `target="L120"`).

Here is what a search looks like. This is an illustrative example, not a recorded session:

```text
rtfm_search("retry policy for failed webhooks")

5 sources for "retry policy for failed webhooks":

/repo/docs/adr/0012-delivery-guarantees.md L41-78 (Consequences)
/repo/specs/partner-api-v3.pdf (Page 14)
/repo/src/webhooks/dispatcher.py L88-131 (WebhookDispatcher.schedule_retry)
  + L132-160 (WebhookDispatcher._backoff)
/repo/docs/runbooks/webhooks.md L12-40 (When deliveries pile up)
/repo/notes/2026-03-incident.md L1-25 (Timeline)
```

From there the agent expands only the ADR section and page 14 of the PDF. The code result sits in the same list, so it does not need a separate grep to connect the decision with the implementation.

## When should you stay with grep?

Be honest with yourself about your repo:

- **Medium-size code repos with obvious file names.** If `grep "class Table"` finds the file at once, RTFM adds calls without adding information. In our own FeatureBench runs on such a repo, the RTFM configurations made extra calls and cost more for no better result. The [benchmark results](../../benchmarks/benchmark_results.md) show this case in full.
- **Exact identifiers.** Searching for a symbol name is grep's home ground.
- **Code navigation.** References, call hierarchies and refactors belong to language-server tools.

RTFM earns its place when the answer lives in prose, in documents grep cannot read, or in a repo too large or too mixed to explore by hand. That is also where our measurements point: the gains we saw came from tasks whose knowledge sat outside the code, or from large repos where the right file was hard to find.

## How do you try it?

In Claude Code, install the plugin:

```text
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

The plugin indexes each project the first time you use it. For PDFs and semantic search, add the optional parts from inside Claude Code:

```text
/rtfm:install-pdf
/rtfm:install-embeddings
```

For Cursor, Codex or any other MCP client, install the package and index the project:

```bash
pip install rtfm-ai        # or: pipx install rtfm-ai
cd your-project
rtfm init
rtfm sync
```

Then point your client at the `rtfm-serve` command. Optional formats install as extras, for example `pip install "rtfm-ai[pdf,embeddings]"`.

`rtfm init` also adds a short section to your project's `CLAUDE.md` asking the agent to use `rtfm_search` for exploratory searches. The agent will still grep for identifiers — and that is fine.

If you want to see how RTFM compares with a vector database setup, read [RTFM vs vector RAG](../../comparisons/vs-vector-rag.md). The [architecture page](../../architecture.md) explains how indexing stays incremental.
