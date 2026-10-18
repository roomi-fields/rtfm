---
date: 2026-10-18
authors: [romain]
title: "You Don't Need a Vector Database: Local RAG for Coding Agents with SQLite FTS5"
description: >-
  A practical look at local RAG for coding agents built on SQLite FTS5 and BM25 ranking, when local embeddings help,
  how hybrid search works, and where a real vector database still wins.
slug: local-rag-without-vector-database
---

# You Don't Need a Vector Database: Local RAG for Coding Agents with SQLite FTS5

If you want your coding agent to search your project locally, the default advice is "chunk, embed, store in a vector
database". For most of what a coding agent asks, you can skip the vector database entirely: SQLite's built-in
full-text search (FTS5) with BM25 ranking runs from a single file, needs no model, no server and no API key, and
handles the literal-term queries agents send most of the time. Embeddings are worth adding for one specific
job, and you can run them locally on a CPU too.

<!-- more -->

## Is "local RAG without a vector database" a real option?

Yes, and plenty of developers have arrived there on their own. In the Hacker News thread
[Ask HN: How are you doing RAG locally?](https://news.ycombinator.com/item?id=46616529), one developer described
building a plain SQLite FTS5 index with a short description per file: the agent checks the descriptions and loads
the whole document when one matches. They said it took about an hour and works well. Another commenter argued that
for code, keyword search (BM25 plus trigrams) gave them better and faster results than embeddings. PingCAP's write-up
on [local-first RAG with SQLite](https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/)
makes the same point from the infrastructure side: a single SQLite file is the right default for local, single-user
agent memory, and it keeps backups trivial.

RTFM is that idea packaged as an MCP server: it parses your project by format, stores chunks in SQLite with FTS5,
and gives the agent search tools that return locations, not walls of text.

## What do FTS5 and BM25 actually do?

FTS5 is SQLite's full-text search extension. It builds an inverted index, a map from each word to the chunks that
contain it, inside the same database file. RTFM creates its table with the `porter unicode61` tokenizer:
`unicode61` splits text into words and folds case and accents, and `porter` reduces English words to their stem,
so "authenticate", "authenticated" and "authenticating" match each other.

Ranking uses BM25, the standard scoring function behind most search engines. In plain terms, a chunk scores higher
when:

- it contains the query words, and more of them;
- those words are rare across the whole index (a match on `PaymentRetryPolicy` counts more than a match on
  `return`);
- the chunk is short, so the match isn't diluted in a long passage.

No training, no model, deterministic results: the same query on the same index gives the same ranking.

## Why does this fit coding agents so well?

Look at what agents actually search for: a class name, a function, an error message, a config key, a file name, an
article number in a regulation. The thing they want is named in the query. That is exactly what a full-text index is
good at, and it answers in milliseconds from a file on disk.

The alternative without any index is grep, glob and read. Agents find things that way too; the difference is cost.
Each search is a tool call, results arrive as raw lines, and the agent often reads whole files to decide whether
they matter. An index returns a ranked short list first. In RTFM, `rtfm_search` returns one line per matching file
with line ranges and section names, and `rtfm_expand` then reads only the section the agent picks. It also reaches
files grep handles badly: PDFs, Word and OpenDocument files, spreadsheets, notebooks, EPUBs.

## When does semantic search help?

Full-text search matches words. It has no idea that "car" and "vehicle" mean the same thing, or that "how does the
app remember who is logged in" is about session handling. Embedding models do: they map text to vectors so that
passages with similar meaning end up close together, even with no word in common. They help with:

- **synonyms and paraphrase**: the question uses different words from the document;
- **conceptual questions**: "where do we deal with rate limiting" when the code says `throttle`;
- **cross-language search**: a French question finding an English document, with a multilingual model.

For prose-heavy corpora (notes, research, support docs), this is a real gain. For identifier-heavy code queries, it
adds less.

## How do I add embeddings without a vector database or an API key?

RTFM's embeddings are optional and fully local. They use FastEmbed, which runs ONNX models on the CPU (no GPU, no
PyTorch), and the vectors are stored in the same SQLite file as the text. Three models are available by alias:

| Alias      | Model                                                         | Size    | Languages    |
| ---------- | ------------------------------------------------------------- | ------- | ------------ |
| `fast`     | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | ~85 MB  | multilingual |
| `balanced` | `BAAI/bge-base-en-v1.5`                                       | ~210 MB | English      |
| `quality`  | `mixedbread-ai/mxbai-embed-large-v1`                          | ~640 MB | English      |

```bash
pip install "rtfm-ai[embeddings]"
rtfm embed                          # default model: fast
rtfm embed --embed-model balanced   # or pick another
```

In Claude Code with the plugin, `/rtfm:install-embeddings` installs the same extra into an isolated environment.
The model downloads once and is cached.

## What does hybrid mode do?

`rtfm_search` takes `search_type="fts"` (the default), `"semantic"` or `"hybrid"`. From the command line:
`rtfm semantic-search "query"`, with `--hybrid` for the combined mode.

Hybrid in RTFM works like this:

1. Run the full-text search and keep three times as many candidates as requested.
2. Score each candidate by cosine similarity between its stored vector and the query's.
3. Combine the two: 30% normalised BM25 score, 70% semantic score, and re-sort.
4. If the full-text search finds nothing at all, fall back to pure semantic search.

So hybrid re-orders keyword matches by meaning. It is a good mode when your query has the right words but too many
chunks contain them. For a pure paraphrase with no shared words, use `search_type="semantic"` directly.

An illustrative comparison (made-up project, made-up results):

```text
rtfm_search("how do we keep users logged in", search_type="fts")
→ matches chunks containing "users" and "logged", e.g. a logging helper

rtfm_search("how do we keep users logged in", search_type="semantic")
2 sources for "how do we keep users logged in":
/home/me/app/src/auth/session.py L40-92 (class SessionStore)
/home/me/app/docs/adr/0004-refresh-tokens.md L1-35 (Decision)
```

## Where does a real vector database win?

Being fair matters here, because there are cases where Milvus, Qdrant, pgvector or a hosted service are the right
call:

- **Scale.** RTFM's semantic search compares the query against every stored vector, in Python. That is fine for a
  project or a personal knowledge base. It is not an approximate-nearest-neighbour index and won't serve tens of
  millions of vectors with low latency. Vector databases are built for exactly that.
- **Many users, one index.** A server-side vector store shared by a team or a product beats a file on each laptop.
- **Paraphrase is the main workload.** Customer support, FAQ matching, semantic question answering over prose:
  embeddings first, keywords second.
- **Better models.** Large hosted embedding models generally beat a CPU-sized local model on hard semantic queries.
  If you accept the cost and the data leaving your machine, you may get better recall.

And the limits of full-text search: no synonyms without embeddings, stemming is English-oriented, and a query full
of generic words ranks poorly. For more on the trade-offs, see [RTFM vs vector RAG](../../comparisons/vs-vector-rag.md)
and [RAG fundamentals](../../rag-fundamentals.md).

## Try it

```bash
pip install rtfm-ai
cd your-project
rtfm init                 # creates .rtfm/library.db and the MCP configuration
rtfm sync                 # indexes the project
rtfm search "PaymentError handling"
```

Add `pip install "rtfm-ai[embeddings]"` and `rtfm embed` when you want semantic or hybrid search. For Claude Code,
the plugin route needs no `pip install`:

```
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

For Cursor, Codex or other MCP clients, install with pip and point the client at the `rtfm-serve` command.
