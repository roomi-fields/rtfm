---
date: 2026-10-18
authors: [romain]
title: "Context7 for Your Own Docs: Indexing Private Documentation Locally"
description: >-
  Context7 serves public library docs to coding agents. This post shows how to give the agent
  the same kind of access to your internal docs, specs, ADRs and PDFs, indexed on your machine.
slug: context7-for-private-docs
---

# Context7 for Your Own Docs: Indexing Private Documentation Locally

Context7 is great at one thing: giving your coding agent current documentation for public libraries, so it stops inventing APIs that changed two versions ago. But the documents your agent misses most are usually not React's or Django's; they are yours: the internal API spec, the architecture decisions, the PDF from the vendor, the runbook. If you searched for "Context7 for private docs" or "Context7 alternative for internal documentation", this post covers how to get that kind of lookup for your own docs, locally, and when a hosted option is the better choice.

<!-- more -->

## What does Context7 do well?

[Context7](https://context7.com) (by Upstash) is an MCP server that fetches up-to-date, version-specific documentation and code examples for public libraries and hands them to the agent. You ask for "how do I configure middleware in Next.js 15", and the agent gets the current docs instead of whatever it remembers from training.

For public libraries, that is the right tool. Someone else maintains the index, it covers thousands of projects, and it stays current as libraries release. Nothing in this post replaces it. If your question is about a public package, keep using Context7.

Context7 also offers private repository indexing on its paid plans, hosted on their side. If your docs are in a Git repository, you are fine sending them to a hosted service, and you want the same interface for public and private docs, look at that first.

## Where do your own docs fit?

Most projects carry documentation that no public index will ever see:

- Internal API and data specs, often Markdown in `docs/` or exported from a wiki.
- Architecture decision records and design notes.
- PDFs: vendor manuals, standards, contracts, regulatory texts, research papers.
- Word and OpenDocument files from people who do not write Markdown.
- Notes in an Obsidian vault, or a folder of meeting minutes.

Some of these cannot leave your machine. Some are not in a Git repository at all. And a lot of them are not Markdown.

## Why not let the agent read the files directly?

For Markdown in the repository, the agent can already do it: list the folder, grep, open the likely files. It works.

What it costs is the search itself. Every listing and file read is a tool call, and every file opened to check relevance lands in the context window. That is cheap for ten files and expensive for a few hundred. And grep does not read PDFs, Word files or EPUBs, so for those the agent either needs a conversion step or simply does not look.

## How do you index private documentation locally?

[RTFM](https://github.com/roomi-fields/rtfm) builds a local full-text index (one SQLite file) of a project and its documents, and serves it to the agent over MCP. Nothing is sent anywhere; there is no account and no API key.

```bash
pip install rtfm-ai              # or: pipx install rtfm-ai
cd your-project
rtfm init                        # index file, MCP entry, CLAUDE.md section, auto-sync hook
rtfm sync
```

Docs that live outside the repository are added as their own corpus:

```bash
rtfm add ~/work/specs --corpus specs
rtfm add ~/work/vendor-manuals --corpus vendor --extensions pdf
rtfm sync
```

Each format is parsed by its structure rather than cut into fixed-size pieces: Markdown by headings, LaTeX by sections, PDFs by page, Python by class and function, YAML and JSON by keys. DOCX, ODT, RTF, EPUB, CSV and spreadsheets are supported too. Some formats need an optional extra (PDF, Office documents, ebooks); the [parsers guide](../../parsers.md) lists which. If you have an in-house format, you can add a parser in a short Python file, or describe a JSON format in a small YAML mapping (see [JSON mappings](../../json-mappings.md)).

## What does the agent see?

The same shape as a good docs lookup: first a short list of where the answer is, then the content of the one section it picks. An illustrative `rtfm_search` result (paths invented for the example):

```text
3 sources for "webhook signature verification":

/home/you/acme/docs/api/webhooks.md L40-96 (Verifying signatures)
/home/you/work/vendor-manuals/payment-gateway-v3.pdf L1-58 (p.27)
/home/you/acme/docs/adr/0009-hmac-rotation.md L1-35 (Decision)
```

That is metadata only: paths, line ranges, sections or pages. A handful of hits is a few hundred tokens. The agent then reads one of them with `rtfm_expand`, for example jumping straight to the "Verifying signatures" section, and nothing else from those files enters the context.

You can narrow a search to one corpus (`corpus="specs"`) when you know where the answer lives, and switch to semantic or hybrid search if you install the optional embeddings extra; full-text search works without it.

## How does this compare to Context7?

They answer different questions, so the comparison is mostly about scope:

| | Context7 | RTFM |
|---|---|---|
| Main use | Public library docs | Your project's own docs and files |
| Who builds the index | The service | You, on your machine |
| Where it runs | Hosted | Local SQLite file |
| Private content | Paid plans, Git repos | Any local folder, no account |
| Formats | Library docs and code examples | Markdown, code, PDF, Office files, ebooks, and more |
| Stays current with | Library releases | Your edits (incremental re-index) |

Used together, the agent asks Context7 about the framework and RTFM about your system. They do not overlap much.

## What other options are there?

If you prefer a hosted, managed setup, there are paid products aimed at private documentation for agents. Two examples:

- **[Docsie](https://www.docsie.io/solutions/claude-documentation-mcp-server/)** is a documentation platform that exposes its knowledge base to Claude through an MCP server, with team features such as access control. A good fit if your docs already live there or you want a managed docs portal.
- **Context7 Private Docs MCP**, listed on MCP directories under Clauxel, is a paid hosted MCP for private, version-pinned documentation with source citations.

Hosted tools make sense when a team needs one shared index, permissions, and nobody wants to run anything locally. RTFM is a local, single-machine tool: each developer indexes what they have on disk.

## When should you NOT use RTFM for this?

- **Public library docs.** Use Context7 or the library's own docs. RTFM does not fetch anything from the internet.
- **A shared team knowledge base with permissions.** RTFM has no users, roles or sharing. Each index is a file on one machine.
- **A small docs folder.** If your internal docs are a dozen Markdown files, the agent's own file tools are enough.
- **Scanned PDFs without OCR.** Image-only PDFs have no text to index until you run OCR, which needs a separate extra and the tesseract binary.

## Try it

With the Claude Code plugin:

```text
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
/rtfm:install-pdf          # optional: text extraction for PDFs
```

With pip (Claude Code, or Cursor, Codex and other MCP clients pointed at the `rtfm-serve` command):

```bash
pip install rtfm-ai
pip install "rtfm-ai[office]"       # optional: DOCX, ODT, RTF
pip install "rtfm-ai[pdf]"          # optional: PDF (includes marker-pdf, a large download)
cd your-project && rtfm init && rtfm sync
```

Keep Context7 for the libraries. Point RTFM at the folder of documents only your team has. For how the index is built and kept up to date, see the [architecture](../../architecture.md) page.
