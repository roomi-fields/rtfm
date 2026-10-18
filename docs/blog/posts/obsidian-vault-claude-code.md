---
date: 2026-10-18
authors: [romain]
title: Make Your Obsidian Vault Searchable by Claude Code — No API Key, No Plugin
description: >-
  How to index an Obsidian vault for Claude Code with one local command: wikilinks become graph edges, hubs and
  orphans are listed, and no API key or Obsidian plugin is needed.
slug: obsidian-vault-claude-code
---

# Make Your Obsidian Vault Searchable by Claude Code — No API Key, No Plugin

You have a few hundred (or a few thousand) notes in Obsidian and you want Claude Code to use them: answer from your
research notes, follow your `[[wikilinks]]`, stop re-reading the same folders every session. The short answer: run
`pip install rtfm-ai`, then `rtfm vault` inside the vault. It builds a local search index in one SQLite file, wires
it into Claude Code, and needs no API key and no Obsidian plugin.

<!-- more -->

## How do I connect my Obsidian vault to Claude Code?

This is one of the most common beginner questions in the Claude Code and Obsidian communities, and there are three
families of answers:

1. **Open Claude Code inside the vault and let it read files.** This works. The agent lists folders, greps for
   keywords and reads notes. On a small vault, that's all you need.
2. **An MCP server that talks to Obsidian itself**, usually through the Local REST API community plugin. Good when
   you want the agent to *edit* notes through Obsidian, but Obsidian has to be running and the plugin installed.
3. **A RAG server built for vaults**, such as `obsidian-rag-mcp`, which embeds your notes into ChromaDB using the
   OpenAI API. Good semantic recall, but every note you index goes through a paid, remote embedding API, and you
   need an `OPENAI_API_KEY`.

RTFM is a fourth option: a local index that the agent searches before reading anything, built from the files on
disk. Obsidian doesn't need to be open, and nothing leaves your machine.

## Why not just let the agent grep the vault?

Grep finds things. The cost is how it gets there. On a large vault, a question like "what did I write about modal
logic and music?" turns into several rounds of listing, searching and reading whole notes, and each round
fills the context window. Andrej Karpathy's
[LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern solves this with a
hand-maintained `index.md` that the model reads first, and it works well up to a few hundred notes. Past that, the
index itself becomes something the model has to read in full.

What changes with a search index is that the agent asks one question and gets back a short list of matching notes
and sections, with line ranges, before it reads anything.

## How do I index the vault?

```bash
pip install rtfm-ai          # or: pipx install rtfm-ai
cd /path/to/your-vault
rtfm vault
```

`rtfm vault` does the following, in order:

- **Checks** for the `.obsidian/` folder to confirm it's a vault.
- **Proposes corpora** from your top-level folders: each folder with more than five Markdown files becomes a
  searchable corpus (`Research/` becomes `research`), and notes at the root go into a `root` corpus. Folders like
  `templates`, `archive`, `.trash` and `_assets` are skipped.
- **Creates** `.rtfm/library.db`, a single SQLite file holding the full-text index.
- **Indexes** every corpus, then resolves `[[wikilinks]]` into links between notes.
- **Writes** `.mcp.json` and a short section in `CLAUDE.md`, so Claude Code finds the search tools on its next start.
- **Adds** `.rtfm/` and `_rtfm/` to `.gitignore`, if you version your vault.
- **Generates** an `_rtfm/` folder of navigation notes you can open in Obsidian.

Useful flags: `--no-embeddings` skips semantic vectors, `--no-output` skips the `_rtfm/` folder, and
`--regenerate` rebuilds `_rtfm/` without re-indexing.

## How are wikilinks handled?

Every `[[Note]]` and `[[Note|alias]]` in your Markdown is recorded as a link, then resolved the way Obsidian
resolves it:

1. Anything after `#` is dropped (`[[Note#Section]]` points to `Note`).
2. An exact path match wins.
3. Otherwise, a case-insensitive file-name match, or a path-suffix match for `[[folder/Note]]`.
4. When several notes share a name, the one closest to the linking note in the folder tree wins.

The resolved links are stored as edges of a graph, alongside the text. That graph gives you two things. In
Obsidian, the `_rtfm/` notes list your most-linked notes and your unlinked ones. For the agent, `rtfm_search` takes
a `centrality_weight` parameter (0 to 0.5) that pushes heavily linked notes up the ranking, and `rtfm_graph` shows
what a given note links to and what links back to it.

## What do I get in Obsidian?

```
_rtfm/
├── index.md          # stats, corpus list, most connected notes
├── graph.md          # hub notes, orphan notes, link types, Mermaid diagram
├── recent.md         # most recently modified notes
└── corpus/
    ├── research.md   # one index per corpus
    └── ...
```

These are ordinary Obsidian notes: they use wikilinks, so you can click through, YAML frontmatter tagged `rtfm`, so
Dataview can query them, callouts for the stats, and a Mermaid diagram that Obsidian renders natively. `graph.md`
is the one I open most: the **hub** list (the 20 notes with the most backlinks) shows what your vault is actually
organised around, and the **orphan** list shows notes nothing links to, which is a to-do list for linking.

They are generated, never hand-edited: delete the folder and run `rtfm vault --regenerate` to rebuild it.

## What does the agent see?

In Claude Code, the agent now calls `rtfm_search` before opening files. An illustrative exchange (paths and
sections invented for the example):

```text
rtfm_search("modal logic in music theory", limit=3)

3 sources for "modal logic in music theory":
/home/me/vault/Research/Modal harmony.md L12-48 (Modes as constraint systems)
/home/me/vault/Notes/Logic reading list.md L1-30 (Kripke frames)
/home/me/vault/Publications/Draft chapter 3.md L210-265 (Formal models)
```

No note content comes back, only where to look. The agent then calls `rtfm_expand` on the one source it wants,
optionally jumping to a section, and reads only that. If you split the vault into corpora, it can also narrow a
search: `rtfm_search("auth flow", corpus="app")`.

## Do I need embeddings or an API key?

No. The default search is SQLite's built-in full-text search, which ranks notes by how well they match the words
in the query. It needs no model and no network.

If your notes and your questions often use different words for the same thing, you can add semantic search. It
runs on your CPU with a small local model (about 85 MB, multilingual), still without any key:

```bash
pip install "rtfm-ai[embeddings]"
rtfm embed
```

With embeddings installed, the agent can ask for `search_type="semantic"` or `"hybrid"`.

## Can my code project search my vault too?

Yes. If your code lives in a separate repository, run `rtfm init` there and register the vault folder you need as an
extra source, so one search covers both code and notes. The [Obsidian guide](../../obsidian-vault-guide.md)
describes the three layouts (one vault per project, one vault with several corpora, code project plus vault).

## When is RTFM not the right tool?

- **Small vaults.** Under a hundred notes or so, a good `index.md` and plain file reading are enough. An index adds
  a step you don't need.
- **You want the agent to write through Obsidian.** RTFM reads files; it doesn't drive Obsidian. An MCP server built
  on the Local REST API plugin is the better choice for creating and editing notes inside the app.
- **Paraphrase-heavy questions with no embeddings.** Full-text search matches words (with stemming). If you want
  "car" to find "vehicle", install the embeddings extra or use a vector-based tool.
- **You already pay for OpenAI embeddings and like the results.** `obsidian-rag-mcp` and similar tools are a
  reasonable choice; the trade-off is the API key and sending your notes to a remote service.

## Try it

```bash
pip install rtfm-ai
cd /path/to/your-vault
rtfm vault
```

Then restart Claude Code in the vault and ask it something you know is in your notes. If you prefer Claude Code's
plugin system, the plugin indexes each folder you open on first use, with no `pip install`; the `_rtfm/`
navigation notes still come from `rtfm vault`.

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

More detail: the [Obsidian vault guide](../../obsidian-vault-guide.md) and the
[architecture overview](../../architecture.md).
