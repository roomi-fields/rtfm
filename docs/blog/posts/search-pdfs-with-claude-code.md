---
date: 2026-10-18
authors: [romain]
title: How to Make Claude Code Search Your PDFs (Locally, Without a Vector DB)
description: >-
  A step-by-step guide to letting Claude Code search a folder of PDFs, scanned ones included, from a local index: setup, OCR, example output and limits.
slug: search-pdfs-with-claude-code
---

# How to Make Claude Code Search Your PDFs (Locally, Without a Vector DB)

You have a folder of PDFs (specs, datasheets, papers, contracts, a vendor manual) and you want Claude Code to answer questions from them without you copying text into the chat. The short answer: index them once into a local SQLite full-text index, expose that index to Claude Code through an MCP server, and let the agent search pages instead of opening whole files. This post shows how to do that with RTFM, including scanned PDFs.

<!-- more -->

## Why is searching PDFs with Claude Code awkward?

Claude Code can read a PDF you point it at, and for one file that is often all you need. The trouble starts with a folder of them. grep has nothing to match inside a PDF, because the text is stored in compressed streams. So the agent has to guess which file is relevant from its name, open it, and read it. With twenty PDFs that is a lot of reading, and every page it opens lands in the context window, including the pages that had nothing to do with the question.

The agent usually gets there. The cost is in the number of steps, the tokens, and the context space spent along the way.

## What are the usual options?

- **Paste or attach the PDF.** Fine for one document, not for a library.
- **A single-purpose PDF MCP server.** There are many, for example [`read_pdf_as_text_mcp`](https://glama.ai/mcp/servers/hancengiz/read_pdf_as_text_mcp) or servers built on `pdftotext`. They let the agent read or search inside a PDF it already knows about. If your need is "read this one file well", they are a good and light choice.
- **A RAG pipeline with a vector database.** Chunk, embed, store in Chroma or Qdrant, query. It works, but it is a service to run and keep in sync, and it usually covers the PDFs only, not the code and notes next to them.

What none of these gives you is one index where the PDFs sit next to your code, Markdown and other documents, so that a single search covers everything in the project.

## How do you set it up?

### With the Claude Code plugin

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
/rtfm:install-pdf
```

`/rtfm:install-pdf` installs the light PDF extractor (pdftext, about 50 MB) into an isolated environment. For tables, figures and complex layouts there is `/rtfm:install-pdf-full`, which adds marker-pdf with a CPU-only PyTorch (about 1.5 GB, no GPU needed). Restart Claude Code after installing an extra. The plugin indexes the project on your next prompt and keeps the index up to date as files change.

### With pip (Cursor, Codex, other MCP clients)

```bash
pip install "rtfm-ai[pdf]"
cd your-project
rtfm init
rtfm sync
```

`rtfm init` sets up the index and the MCP configuration; `rtfm sync` indexes the whole project. The `pdf` extra pulls both pdftext and marker-pdf. Then point your MCP client at `rtfm-serve`, as the [README](https://github.com/roomi-fields/rtfm#manual-install-cursor-codex-claude-desktop-chat-other-mcp-clients) describes.

### PDFs outside the project, or kept out of git

If the PDFs live elsewhere, register that folder as a separate collection (a "corpus"):

```bash
rtfm add ~/Documents/datasheets --corpus datasheets --extensions pdf
rtfm sync
```

PDFs are often listed in `.gitignore` because they are heavy or copyrighted. By default RTFM respects `.gitignore`. Add `--no-gitignore` to `rtfm add` (or `rtfm sync`) to index them anyway; the choice is recorded on the source, so later syncs keep doing it.

## What about scanned PDFs?

A scanned PDF is a stack of images with no text layer, so text extraction returns nothing. RTFM notices this (the file yields little or no text per page) and can run OCR on those files.

1. Install the OCR extra and the tesseract program:

    ```bash
    pip install "rtfm-ai[ocr]"          # pytesseract, pypdfium2, Pillow
    sudo apt install tesseract-ocr tesseract-ocr-fra
    ```

    With the Claude Code plugin, ask Claude to run the plugin's bundled installer with `ocr` (`bin/rtfm-install-extras ocr` in the plugin's folder); it installs into the plugin's own environment.

2. Turn OCR on for the project:

    ```bash
    rtfm sync --ocr
    ```

This writes `"ocr_fallback": true` to `.rtfm/config.json` and queues every PDF already flagged as a scan. From then on, new scans are OCR'd automatically on later syncs. The work runs in the background in 50-page batches, so a long book can be resumed where it stopped instead of starting over. `rtfm status` shows progress, and `rtfm doctor` reports which indexed PDFs look scanned, corrupt or mislabeled.

The default OCR languages are English and French (`eng+fra`). To change them, set `"ocr_langs"` in `.rtfm/config.json`, for example `"eng+deu"`, and install the matching tesseract language pack. Languages whose pack is missing are skipped. The [architecture page](../../architecture.md) describes how the OCR jobs are queued.

## What does the agent see?

The agent calls `rtfm_search` and gets back a short list of sources, with no content: the file path and the best-matching page. PDFs are split into chunks page by page, so results point at pages. Here is an illustrative example (file names invented):

```
rtfm_search("maximum SPI clock frequency", corpus="datasheets")

3 sources for "maximum SPI clock frequency":
/home/me/Documents/datasheets/stm32f4-reference-manual.pdf (Page 871)
/home/me/Documents/datasheets/w25q128-flash.pdf (Page 7)
/home/me/project/docs/hardware-notes.md L40-62 (SPI bus)
```

Notice the third hit: a Markdown note from the project itself, found by the same query. The agent then reads only what it needs:

```
rtfm_expand("/home/me/Documents/datasheets/w25q128-flash.pdf",
            query="SPI clock frequency")
```

`rtfm_expand` returns the matching chunks, not the whole PDF. That is the point of the design: a search costs a few hundred tokens of paths and page numbers, and the context only grows by the pages the agent decides to read.

Search is full-text (SQLite FTS5) by default, with no vector database involved. If you want matches on meaning rather than exact words, install the embeddings extra (`/rtfm:install-embeddings`, or `pip install "rtfm-ai[embeddings]"`, about 85 MB, runs on CPU) and the agent can pass `search_type="semantic"` or `"hybrid"`. The embeddings are stored in the same SQLite file.

## What are the limits?

- **Scanned PDFs take time.** OCR on a CPU is slow; a few hundred scanned pages can take a while. It runs in the background, but the content is not searchable until it is done. OCR quality also depends on the scan.
- **Complex layouts.** pdftext extracts the text layer in reading order as best it can. Multi-column pages, tables and formulas can come out flattened. marker-pdf (`/rtfm:install-pdf-full`) handles them better, at the cost of a 1.5 GB install and slower parsing.
- **Very large PDFs.** Each extraction runs in its own process with a time limit (ten minutes for text extraction), so one pathological file cannot block the rest. A huge or broken PDF may fail; `rtfm failed` lists failed jobs with the reason.
- **Text only.** Figures, diagrams and images are not described or indexed.

## When should you not use RTFM for this?

- You have one or two PDFs. Point Claude Code at the file and let it read it.
- You only ever need to read a PDF you already know about. A small PDF-reading MCP server does that with less setup.
- You need a hosted, multi-user search over millions of documents. That is a job for a search service, not a local SQLite file.

RTFM is worth it when PDFs are one part of a larger project and you want the agent to search them together with everything else.

## Try it

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
/rtfm:install-pdf
```

Or, outside Claude Code:

```bash
pip install "rtfm-ai[pdf]"
cd your-project && rtfm init && rtfm sync
```

The [parsers guide](../../parsers.md) lists the other formats indexed the same way (DOCX, EPUB, LaTeX, spreadsheets and more).
