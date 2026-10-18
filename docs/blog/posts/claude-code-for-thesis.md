---
date: 2026-10-18
authors: [romain]
title: "Claude Code for Your Thesis: One Index for Papers, LaTeX and Notes"
description: >-
  How to give Claude Code one local search over your thesis: the PDFs you read, your LaTeX chapters and your Markdown or Obsidian notes, with setup, examples and limits.
slug: claude-code-for-thesis
---

# Claude Code for Your Thesis: One Index for Papers, LaTeX and Notes

If you write a thesis or a long paper with Claude Code, your material is spread across three places: a folder of PDFs you have read, the LaTeX source of your chapters, and your notes, often in Markdown or an Obsidian vault. You want to ask "where did I discuss this, and which paper said it first?" and have the agent answer from all three. The way to get there is one local index that covers papers, chapters and notes together, searched through an MCP server. This post shows how to set that up with RTFM, and what it does not do.

<!-- more -->

## Why is a thesis hard for a coding agent?

Claude Code is built around code: it greps, globs and reads files. A thesis project breaks that habit in two ways.

First, much of the material is not plain text. grep cannot match anything inside a PDF, so for the papers the agent has to guess from file names and open them one by one.

Second, the questions are about ideas, not identifiers. "What did I write about the limits of this method?" has no exact string to search for. The agent will still find the answer: it greps a few words, lists folders, opens a chapter, then another. Each step is reasonable. Together they cost many tool calls, a lot of tokens, and context space filled with pages that were not relevant.

## Isn't that what Zotero is for?

No, and the difference matters. A reference manager like Zotero knows your bibliography: authors, years, DOIs, collections, BibTeX keys. There are Zotero MCP servers that expose that library to an agent, and if your question is "give me the citation for this paper" or "list what I have filed under this tag", that is the right tool.

RTFM is not a reference manager. It does not manage citations, format a bibliography or read your `.bib` file (BibTeX files are not indexed). It does document retrieval: it splits the full text of your papers, chapters and notes into passages, and lets the agent find the passage that answers a question. The two work fine side by side.

## What goes into the index?

| Material | Format | How it is split |
|---|---|---|
| Papers you read | `.pdf` | Page by page (scans can be OCR'd) |
| Your chapters | `.tex` | By `\part`, `\chapter`, `\section`, `\subsection`... |
| Your notes | `.md` (Obsidian vaults too) | By heading, with YAML frontmatter kept |
| Analysis | `.ipynb`, `.csv`, `.py` | Notebook sections, tables, functions |
| Drafts and comments | `.docx`, `.odt` | By heading style |

Some links between files become graph edges the agent can follow:

- In LaTeX, `\input{...}` and `\include{...}` link the main file to its chapter files.
- In Markdown, links and Obsidian `[[wikilinks]]` link notes to each other.

`rtfm_graph` shows these links for a file, and `rtfm_search` can give a boost to files with many incoming links (`centrality_weight`), so your hub notes rank higher. One caveat: the LaTeX reader recognises `\cite`, `\citep`, `\citet` and `\autocite` keys, but those citations are not yet turned into links in the graph. Do not expect "which chapters cite this paper?" from the graph today; a full-text search for the citation key does that job.

The [parsers guide](../../parsers.md) describes each format in detail.

## How do you set it up?

### A thesis repository

Install the extras you need and index the project:

```bash
pip install "rtfm-ai[pdf,office]"
cd ~/thesis
rtfm init
rtfm sync
```

`rtfm init` creates the index (`.rtfm/library.db`) and the MCP configuration for Claude Code; `rtfm sync` indexes the project. With the Claude Code plugin, run `/plugin marketplace add roomi-fields/claude-plugins`, `/plugin install rtfm@roomi-fields` and `/rtfm:install-pdf`; the plugin indexes the project on your next prompt.

Paper PDFs are often kept out of git (heavy, copyrighted). RTFM respects `.gitignore` by default, so tell it to index that folder anyway. Registering it as its own collection (a "corpus") also lets the agent search the papers alone:

```bash
rtfm add ~/thesis/papers --corpus papers --no-gitignore
rtfm sync
```

Scanned papers need OCR: `pip install "rtfm-ai[ocr]"`, install tesseract (`apt install tesseract-ocr`), then `rtfm sync --ocr`. OCR runs in the background; the [PDF post](search-pdfs-with-claude-code.md) covers it.

### An Obsidian vault

If your notes live in an Obsidian vault, `rtfm vault` sets it up in one step: it maps top-level folders to collections, indexes them, resolves wikilinks, and writes navigation pages inside the vault. The vault can then be added as a source of your thesis project so one search covers both. The [Obsidian guide](../../obsidian-vault-guide.md) describes the possible layouts.

### Semantic search

Full-text search finds the words you type. Research questions are often phrased differently from the text that answers them, so semantic search helps here more than in code. Install the embeddings extra (`pip install "rtfm-ai[embeddings]"` or `/rtfm:install-embeddings`, about 85 MB, runs on CPU) and the agent can use `search_type="hybrid"`. The default model is multilingual, which helps when your sources are not all in English.

## What does it look like in practice?

The agent searches first and gets back paths and locations, with no content. An illustrative example, file names invented:

```
rtfm_search("criticism of the tonal hierarchy model", search_type="hybrid")

4 sources for "criticism of the tonal hierarchy model":
/home/me/thesis/chapters/ch3-methods.tex L210-264 (Limitations)
/home/me/thesis/papers/Smith2019-tonal-cognition.pdf (Page 14)
/home/me/vault/Reading notes/Smith 2019.md L1-38 (Main argument)
/home/me/thesis/papers/Lee2021-corpus-study.pdf (Page 3)
```

One query, three kinds of material: your own chapter, the paper, and your reading note on it. The agent then reads only the passage it needs:

```
rtfm_expand("/home/me/thesis/papers/Smith2019-tonal-cognition.pdf",
            query="tonal hierarchy")
```

Typical uses:

- "Have I already defined this term somewhere in the chapters?"
- "Which of the papers I read discuss this method, and on which page?"
- "Check that chapter 4 does not contradict what I wrote in my notes on Lee 2021."
- "Find the passage I am paraphrasing here, so I can check the quote."

The agent works from your own sources and can point to the file and page it used, which makes its claims checkable.

## What are the limits?

- **Not a reference manager.** No bibliography, no BibTeX, no DOI lookup. Use Zotero (and a Zotero MCP server) for that.
- **Citations are not graph links yet.** `\cite` keys are recognised in LaTeX but not linked to papers in the graph.
- **PDF quality varies.** Two-column layouts, formulas and tables can come out flattened. marker-pdf (`/rtfm:install-pdf-full`, about 1.5 GB) does better on complex layouts, at the cost of size and speed. Scans need OCR, which takes time on a CPU.
- **Text only.** Figures and plots are not described.
- **It retrieves, it does not judge.** The agent finds passages; whether a paper supports your argument is still your reading.

## Try it

```bash
pip install "rtfm-ai[pdf]"
cd ~/thesis && rtfm init && rtfm sync
```

Or, in Claude Code:

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
/rtfm:install-pdf
```

Then ask your agent about your own thesis, and check which file and page it answers from.
