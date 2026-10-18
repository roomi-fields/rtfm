---
date: 2026-10-18
authors: [romain]
title: "Claude Code Memory Is Per-Repo. Here's How to Search It Across All Your Projects"
description: >-
  How to search Claude Code's memory files across every project on your machine,
  with a single local index, full version history, and an automatic snapshot at the end of each session.
slug: claude-code-memory-across-projects
---

# Claude Code Memory Is Per-Repo. Here's How to Search It Across All Your Projects

Claude Code keeps a memory folder for each project, so a decision you recorded in one repository is invisible from the next. If you have ever typed "search Claude Code memory files" or "Claude Code memory across projects", the short answer is: index every project's memory folder into one local search index, and let the agent query it. This post shows how to do that with two commands, and what it does not cover.

<!-- more -->

## Where does Claude Code keep its memory?

Claude Code writes its auto memory under `~/.claude/projects/<project>/memory/`, one folder per project, usually with a `MEMORY.md` index and a set of small Markdown notes next to it. Each session loads the memory of the project you are working in. That is the right default: you do not want a client project's quirks leaking into a side project.

It also means the knowledge stays where it was written. Some examples of what gets stuck:

- You worked out how to configure an OAuth flow in project A. Three weeks later, project B needs the same thing.
- You told the agent "never run the full sync from a hook" in one repo, after it cost you an afternoon. The other repos never heard about it.
- You want to know when a rule changed, and what it said before.

## Why not just grep `~/.claude/projects`?

You can, and it works. `grep -ri oauth ~/.claude/projects/*/memory/` finds the notes. An agent can do the same with its own file tools.

The cost is in what happens next. Grep returns every matching line from every project, with no ranking, so either you read through the pile or the agent pulls it into its context window and spends tokens sorting it. Grep also only sees the current state of each file: when a memory note gets rewritten, the previous version is gone unless you happen to have it in git.

So the question is not "can it be found" but "how cheaply, and with what history".

## How do you index Claude Code memory across all projects?

[RTFM](https://github.com/roomi-fields/rtfm) has a dedicated command for this:

```bash
pip install rtfm-ai          # or: pipx install rtfm-ai
rtfm memory                  # index every project's memory folder now
rtfm memory --install-hook   # re-index automatically at the end of each session
```

What `rtfm memory` does:

- **One global index.** It writes to `~/.rtfm/memory.db`, outside any project, so every project's memory lands in the same searchable file.
- **One corpus per project.** Each `~/.claude/projects/<project>/memory/` folder becomes a corpus named `claude-memory/<project>` (for example `claude-memory/home-you-dev-billing-api`), so you can search everything or filter to one project.
- **Unlimited version history.** Memory files are indexed with history retention switched off, which means every change is kept as a version. Nothing is pruned.
- **Markdown and text only.** It reads the `.md` and `.txt` files in those folders.

If two projects share a memory folder through a link, it is indexed once, under the project that really holds it.

## What does the end-of-session hook do?

`rtfm memory --install-hook` writes a small script to `~/.claude/hooks/rtfm_memory_sync.py` and registers it as a `SessionEnd` hook in `~/.claude/settings.json`. From then on, every Claude Code session you close triggers a pass over all memory folders.

A few details that matter in practice:

- It runs **in the background**, so it never delays the end of a session.
- If several sessions end at the same moment, the first one takes a lock and the others skip, since one pass reads every project anyway.
- It is silent and best-effort: where RTFM cannot run (inside a sandbox, for example), it does nothing instead of printing errors.
- The hook pass is keyword search only. If you installed the optional embeddings and want semantic search over your memory too, run `rtfm memory` by hand now and then; it generates embeddings unless you pass `--no-embeddings`.

## How do you search it?

From the terminal:

```bash
rtfm search "oauth token refresh" --db ~/.rtfm/memory.db --limit 5
rtfm search "release checklist" --db ~/.rtfm/memory.db --corpus claude-memory/home-you-dev-billing-api
rtfm corpora --db ~/.rtfm/memory.db    # list the per-project corpora
```

From inside Claude Code, the RTFM tools accept a `project` argument that points at another index by path. So in any project where RTFM is set up, the agent can call:

```text
rtfm_search(query="oauth token refresh", project="~/.rtfm/memory.db")
```

An illustrative answer (paths and project names invented for the example):

```text
3 sources for "oauth token refresh":

/home/you/.claude/projects/-home-you-dev-billing-api/memory/oauth_refresh_gotcha.md L1-18 (Refresh tokens expire on scope change)
/home/you/.claude/projects/-home-you-dev-dashboard/memory/MEMORY.md L12 (Auth)
/home/you/.claude/projects/-home-you-dev-cli-tool/memory/feedback_no_tokens_in_logs.md L1-9
```

That is paths, line ranges and section names, not content. The agent then reads only the note it needs with `rtfm_expand`, passing the same `project` value. A handful of hits costs a few hundred tokens instead of a full grep dump.

You can tell the agent once, in your global `~/.claude/CLAUDE.md`, that past decisions from other projects live in `~/.rtfm/memory.db` and can be searched with `rtfm_search(..., project="~/.rtfm/memory.db")`. It is an instruction the agent follows, like any other in that file; it is not forced.

## How do you see how a memory note changed?

Because every version is kept, you can ask for the history of a single note:

```bash
rtfm history ~/.claude/projects/-home-you-dev-billing-api/memory/oauth_refresh_gotcha.md \
  --db ~/.rtfm/memory.db
rtfm history <same path> --db ~/.rtfm/memory.db --version 2   # read one version
```

The agent has the same thing through `rtfm_history`, which also takes the `project` argument. This is useful when a rule "suddenly" behaves differently and you want to know whether the note was edited, and what it said before.

## What does this NOT do?

Be clear about the scope before you install it:

- **It indexes memory files, not conversation transcripts.** RTFM reads `~/.claude/projects/*/memory/*.md` (and `.txt`). It does not read the session transcript files Claude Code keeps next to them. If you want to search what was *said* in past sessions, including failed attempts and the reasoning around them, use a transcript search tool instead.
- **It does not write memory.** Claude Code still decides what goes into those notes. RTFM makes them searchable and versioned; it does not summarise or extract anything.
- **It does not inject memory into every session.** Nothing gets loaded automatically. The agent searches when it decides to, or when you ask.
- **It is Claude Code only.** The folder layout it reads is Claude Code's. Cursor or Codex memories are not picked up.

The design choice is deliberate: memory notes are small, curated by the agent, and dense with decisions. Transcripts are large and noisy. Indexing the notes keeps the index small and the hits relevant, at the price of missing anything that never made it into a note.

## What are the alternatives?

Several tools work on the same problem from different angles, and some are a better fit depending on what you want:

- **[claude-find](https://glama.ai/mcp/servers/Cavinooo/claude-find)** searches past Claude Code *sessions*: it reads the raw transcripts and embeds them with a local model through Ollama. If your question is "what did we try last Tuesday and why did it fail", that is the better tool, because RTFM does not read transcripts.
- **[ccmem](https://lobehub.com/mcp/adestefa-ccmem)** is an MCP server that keeps structured project memory (architecture, tasks, lessons and so on) in a SQLite file inside each project. It is a memory store you write to, per project, rather than a search layer over Claude Code's own notes.
- **[MemoryPlugin](https://blog.memoryplugin.com/claude-code-memory/)** explains the per-repository limits of Claude Code memory well, and offers a hosted memory shared across tools (Claude Code, Codex, Cursor and others). If you need the same memory in several agents, or across machines, that is the problem it targets; RTFM is local and reads Claude Code's folders only.

These are not mutually exclusive. Indexing your memory notes with RTFM and searching transcripts with a session tool cover two different questions.

## Try it

```bash
pip install rtfm-ai              # or: pipx install rtfm-ai
rtfm memory                      # first index of all memory folders
rtfm memory --install-hook       # keep it fresh at the end of every session
rtfm search "your topic" --db ~/.rtfm/memory.db
```

If you use the Claude Code plugin for your projects:

```text
/plugin marketplace add roomi-fields/claude-plugins
/plugin install rtfm@roomi-fields
```

The memory index is a separate file from each project's own index, so it stays out of the way until you query it. For how indexes, corpora and version history fit together, see the [architecture](../../architecture.md) page.
