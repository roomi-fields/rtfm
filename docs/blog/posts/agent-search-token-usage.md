---
date: 2026-10-18
authors: [romain]
title: Where Your Agent's Tokens Go When It Searches — and How to Spend Fewer
description: >-
  A step-by-step look at what a Claude Code search costs in tool calls and context, how metadata-first retrieval changes it, what we measured, and when it does not help.
slug: agent-search-token-usage
---

# Where Your Agent's Tokens Go When It Searches — and How to Spend Fewer

If you are trying to reduce Claude Code token usage, or your context window keeps filling up before the real work starts, look at how the agent searches. A large share of a session goes into finding things: listing folders, grepping, opening files to check whether they are the right ones. This post breaks down where those tokens go, how a metadata-first search tool changes the bill, and when it does not.

<!-- more -->

## Where do the tokens go during a search?

Take a plain question: "how does this project handle expired sessions?" With the built-in tools, a typical sequence looks like this:

1. A glob or `ls` to see the layout. The output lists dozens of paths.
2. A grep for `session` or `expire`. It returns every matching line in every file, often many screens of them.
3. A read of the most promising file — in full, or a large slice of it.
4. That file was close but not it. A second grep, a second read.

Every step is a tool call, and every tool result stays in the context window for the rest of the session. The expensive parts are the reads: a 600-line file pulled in to confirm one 30-line function is mostly noise, and the agent pays for that noise again on every later turn, because the whole conversation is sent back each time.

None of this means the agent fails. It usually finds the answer. The cost is in the number of calls and in the volume of text that comes along.

## What changes with metadata-first search?

RTFM splits a lookup into two steps and keeps the first one small.

**Step 1 — `rtfm_search` returns metadata only.** Ranked file paths, line ranges and section names. No file content. By default it returns five sources, one line each. RTFM's README puts a handful of hits at around 300 tokens. Here is an illustrative result:

```text
rtfm_search("expired session handling")

5 sources for "expired session handling":

/app/src/auth/session.py L140-188 (SessionStore.purge_expired)
  + L52-77 (SessionStore.get)
/app/docs/architecture/auth.md L30-61 (Session lifecycle)
/app/docs/adr/0009-session-ttl.md L1-40 (Decision)
/app/src/auth/middleware.py L12-45 (require_session)
/app/tests/auth/test_session.py L80-120 (test_expired_session_redirects)
```

Code, design notes and a decision record come back in one list. The agent has a map before it reads anything.

**Step 2 — `rtfm_expand` reads one section.** The agent asks for a file and, optionally, a section: `rtfm_expand(source="/app/src/auth/session.py", target="SessionStore.purge_expired")`. It gets that function with line numbers, not the whole file. It can also jump to a line (`target="L140"`) or page through the next chunks (`count`, `offset`).

So for a lookup, **one search call replaces the glob, grep and trial reads**, and the reading that follows is limited to the section that matters. That is the mechanism, and it holds whatever the repo: fewer tool results, smaller tool results.

This is what people mean by MCP progressive disclosure: show a short summary first, and let the agent ask for more only where it needs it.

## Does that make whole sessions cheaper?

Not always, and this is where it gets honest. A lookup is only part of a task. The agent still has to read the code it will change, run tests and iterate. And if the agent searches with RTFM *and then* greps for the same thing anyway, you pay twice.

We have measured this on real tasks. The [benchmark results](../../benchmarks/benchmark_results.md) give the full data. The short version:

- **Knowledge outside the code.** On a writing task over an Obsidian vault of research notes and drafts, the RTFM session used noticeably fewer tokens and less money than the session without it. Without RTFM, the agent spread its discovery over dozens of tool calls, many of them in subagents. These were single runs, not averages.
- **Large code repo, file hard to find.** On a task in a repository of more than 8,000 files, the RTFM configurations were the only ones that ever solved it. They did not cost less per run — slightly more on average. Here the gain was in finding the right file at all, not in saving tokens.
- **Medium-size code repo, obvious file names.** On a task where `grep "class Table"` finds the file at once, RTFM brought no gain. The agent made extra RTFM calls on top of its usual grep and read calls, and the total cost went up. With semantic search turned on, one run made dozens of RTFM calls and cost far more for the same result.

Sample sizes are small (one to nine runs per setup), so read these as directions, not as proof. The pattern is consistent though: savings appear when the knowledge is outside the code or the repo is unfamiliar. They disappear on a codebase that grep already handles well.

## When will RTFM not save you tokens?

- **The file is easy to find.** If a single grep for a class or function name lands on the right file, there is nothing to save.
- **You are navigating code structure.** Finding every caller of a function or renaming a symbol is a job for language-server tools such as Serena.
- **The agent uses both.** If it searches with RTFM and then re-explores with grep out of habit, you add calls instead of replacing them.
- **Semantic search on code identifiers.** In our runs, full-text search beat semantic search on code tasks: identifiers are exact strings, and semantic matches added noise and extra calls. RTFM uses full-text search by default for this reason.

## How do you spend fewer tokens on search in practice?

These tips help whether or not you use RTFM:

**Keep `CLAUDE.md` short.** It is loaded into every session. Put the rules there, and keep long explanations in docs the agent can search when it needs them.

**Read sections, not files.** With RTFM, use `rtfm_expand` with a `target` (a section name or a line like `L120`) instead of reading the whole file. Without RTFM, ask the agent to read line ranges once it knows where to look.

**Look at metadata first.** Let the agent see a ranked list before it opens anything. A five-line result costs little. A wrong 800-line read costs a lot.

**Lower the result count when you know what you want.** `rtfm_search` takes a `limit` parameter; the default is five sources.

**Expose fewer tools.** Every MCP tool's description is part of the context. RTFM's server reads `RTFM_MCP_PROFILE`: the default, `runtime`, exposes only the retrieval tools (search, expand, context and the like). `admin` or `all` adds maintenance tools such as sync, ingest, remove and tagging. Leave it on `runtime` — sync already runs from the command line and the Claude Code hooks, so the agent does not need those tools.

**Stay with full-text search for code.** Turn on semantic or hybrid search for prose-heavy corpora where people describe the same idea in different words, not by default for code.

**Let grep do what it is good at.** For an exact identifier, grep is cheap and fine. `rtfm init` adds a short section to your `CLAUDE.md` that points the agent to `rtfm_search` for *exploratory* searches, which is the right split.

## How do you try it?

In Claude Code:

```text
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

The plugin indexes each project on first use and re-indexes changed files as you work. Optional parts install from inside Claude Code: `/rtfm:install-pdf` for PDFs, `/rtfm:install-embeddings` for semantic search.

For Cursor, Codex or another MCP client:

```bash
pip install rtfm-ai        # or: pipx install rtfm-ai
cd your-project
rtfm init
rtfm sync
```

Then point your client at the `rtfm-serve` command.

To check what the index holds against what is on disk, run `rtfm coverage`. For the design behind incremental indexing, see the [architecture page](../../architecture.md), and for every supported format, the [parsers guide](../../parsers.md).
