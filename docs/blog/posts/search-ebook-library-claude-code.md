---
date: 2026-10-18
authors: [romain]
title: Search Your Ebook Library from Claude Code (EPUB, MOBI, FB2, DJVU)
description: >-
  How to index a folder of DRM-free ebooks (EPUB, MOBI/AZW, FB2, DJVU, PDF) locally and let Claude Code search them by chapter, with setup, example output and limits.
slug: search-ebook-library-claude-code
---

# Search Your Ebook Library from Claude Code (EPUB, MOBI, FB2, DJVU)

You have a few hundred ebooks on disk and you would like to ask Claude Code "which of my books discusses X, and what exactly does it say?" without opening them one by one. The way to do it: build a local full-text index of the books, chapter by chapter, and give Claude Code an MCP server that searches it. This post walks through that with RTFM, for EPUB, MOBI/AZW, FB2, DJVU and PDF.

<!-- more -->

## Why can't Claude Code just grep my books?

Because there is nothing to grep. An EPUB is a zip archive of XHTML files, a MOBI or AZW file is a packed binary format, a DJVU file keeps its text in a separate layer. grep sees compressed bytes. The agent can still get the text out, by unzipping, converting, or calling a tool on each file, but that means a chain of commands per book, and whole chapters landing in the context window before it knows whether they are relevant.

For one book that is fine. For a library, the cost is the number of steps and the volume of text read along the way, not whether the agent eventually finds the passage.

## What ebook MCP servers already exist?

Several, and some will suit you better than RTFM:

- **Calibre-based servers** such as [trieloff/calibre-mcp](https://mcpservers.org/servers/trieloff/calibre-mcp) and others built on `calibredb`. If Calibre is how you manage your library, these give the agent your Calibre metadata (authors, series, tags) and, depending on the server, editing and format conversion. RTFM does none of that; it does not read Calibre's catalogue, only the book files.
- **Ebook RAG servers** that chunk books and store embeddings in a vector database such as Chroma or Qdrant. They support semantic questions, but you run and maintain a separate database.

RTFM sits in between: it reads the files directly, needs no Calibre and no external database, and stores everything in one SQLite file. Full-text search works out of the box; semantic search is an optional add-on in the same file.

## Which formats are supported, and how is each one read?

| Format | Extensions | How it is split | Needs |
|---|---|---|---|
| EPUB | `.epub` | One unit per chapter, by paragraph | `epub` extra |
| MOBI / Kindle | `.mobi`, `.azw`, `.azw3` | Unpacked to HTML, by paragraph | `mobi` extra |
| FictionBook | `.fb2` | One unit per `<section>`, titled | nothing |
| DJVU | `.djvu`, `.djv` | Text layer, page by page | `djvulibre-bin` |
| PDF | `.pdf` | Page by page | `pdf` extra |

Titles and authors come from the book's own metadata where the format has it (the OPF file of an EPUB, the `title-info` of an FB2 file). The details are in the [parsers guide](../../parsers.md).

## How do you set it up?

The simplest layout is to make your library folder its own indexed project:

```bash
pip install "rtfm-ai[epub,mobi]"
sudo apt install djvulibre-bin     # only if you have DJVU files
cd ~/Books
rtfm init
rtfm sync
```

`rtfm init` creates `.rtfm/library.db` in that folder and writes the MCP configuration so Claude Code started in `~/Books` can search it; `rtfm sync` indexes the books. (RTFM refuses to create an index in your home directory itself, so use a dedicated folder.) Add the `pdf` extra too if your library has PDFs (`pip install "rtfm-ai[epub,mobi,pdf]"`).

With the Claude Code plugin (`/plugin marketplace add roomi-fields/claude-plugins`, then `/plugin install rtfm@roomi-fields`), the extras go into an isolated environment through the installer bundled in the plugin's folder: ask Claude to run `bin/rtfm-install-extras epub` and `bin/rtfm-install-extras mobi` there. Restart Claude Code afterwards.

### Searching the library from another project

If you would rather keep working in a code or writing project and pull in the books as a separate collection, register the folder there:

```bash
cd ~/my-project
rtfm add ~/Books --corpus books
rtfm sync
```

The agent can then search only the books with `corpus="books"`. Alternatively, keep the library as its own project and pass `project` to `rtfm_search`: it searches another project's index by name or path, without merging the two.

## What do you get?

The agent calls `rtfm_search` and gets back sources with the matching chapter (or page for PDF and DJVU), with no content. An illustrative example, file names invented:

```
rtfm_search("stoic view of anger", corpus="books")

3 sources for "stoic view of anger":
/home/me/Books/Seneca - Letters from a Stoic.epub (Letter XVIII)
/home/me/Books/Marcus Aurelius - Meditations.fb2 (Book XI)
/home/me/Books/Irvine - A Guide to the Good Life.mobi (Chapter 15)
```

It then reads only the passage it needs:

```
rtfm_expand("/home/me/Books/Marcus Aurelius - Meditations.fb2",
            query="anger")
```

`rtfm_expand` returns the matching chunks, not the whole book. `rtfm_books` lists everything indexed, with a per-collection summary, which is handy for "what do I have on this topic?".

By default the search is full-text: it finds the words you use. To match on meaning ("books about grief" finding a chapter that never uses the word), install the embeddings extra (`pip install "rtfm-ai[embeddings]"` or `/rtfm:install-embeddings`, about 85 MB, CPU only). The default model is multilingual, which helps if your library mixes languages. The agent then passes `search_type="hybrid"` or `"semantic"`.

## What are the limits?

- **DRM-free files only.** MOBI and AZW files with DRM are refused with a clear error. RTFM never removes DRM. A protected EPUB whose text cannot be read is not indexed either.
- **DJVU needs a system program.** The DJVU reader calls `djvutxt` from djvulibre (`apt install djvulibre-bin` on Debian/Ubuntu, `brew install djvulibre` on macOS). It reads the existing text layer; a DJVU scan without one gives nothing, and RTFM does not OCR DJVU files.
- **Text only.** Illustrations, maps and tables rendered as images are not indexed.
- **No catalogue management.** No series, shelves, ratings or metadata editing. If that is what you want the agent to work with, use a Calibre MCP server, or both side by side.
- **First indexing takes a while** on a large library. After that, only new or changed files are re-read.

Your books also stay on your machine: the index is a local SQLite file, and nothing is sent to an external service. What you then quote from copyrighted books is your call, not the tool's.

## When should you not use RTFM for this?

- You want to manage your library: tag, convert, fix metadata. Use Calibre and a Calibre MCP server.
- You only want to discuss one book. Give the agent that file.
- Your books are mostly DRM-protected purchases. RTFM cannot read them.

## Try it

```bash
pip install "rtfm-ai[epub,mobi]"
cd ~/Books && rtfm init && rtfm sync
```

Then open Claude Code in that folder and ask about your books. Using the plugin instead:

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```
