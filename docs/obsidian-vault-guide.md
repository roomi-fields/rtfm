# RTFM × Obsidian — Vault Integration Guide

## The Problem

Andrej Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern transforms Obsidian vaults into AI-readable knowledge bases with three layers: raw sources, a compiled wiki, and a schema. Projects like Claudesidian, claude-obsidian, and obsidian-second-brain implement this pattern — and they all hit the same wall.

When the wiki is small (~100 notes), the LLM reads `index.md` and finds what it needs. When the wiki grows past 500 notes, `index.md` becomes unmanageable, the LLM reads everything into context, and tokens explode.

**RTFM is the retrieval layer that removes this ceiling.** FTS5 full-text search, semantic search, graph-based ranking, and progressive disclosure — all generating Obsidian-native navigation files your vault can read.

## Quick Start

```bash
pip install rtfm-ai[mcp]
cd /path/to/your-obsidian-vault
rtfm vault
```

RTFM detects the vault, proposes corpus mappings from your folder structure, indexes everything, and generates `_rtfm/` navigation files. Open Obsidian — the index is already there.

## How It Works

### What `rtfm vault` does

1. **Detects** `.obsidian/` to confirm it's a vault
2. **Scans** top-level folders, proposes each as a corpus (Research → `research`, Publications → `publications`, etc.)
3. **Creates** `.rtfm/library.db` — the search index
4. **Syncs** all corpora with incremental indexing
5. **Resolves** `[[wikilinks]]` into graph edges (follows Obsidian resolution rules)
6. **Generates** `_rtfm/` — Obsidian-native navigation files with wikilinks, frontmatter, Mermaid diagrams
7. **Configures** `.mcp.json` and `CLAUDE.md` so Claude Code works immediately

### What you get in Obsidian

```
_rtfm/
├── index.md          # Hub: stats, corpus list, top connected documents
├── graph.md          # Hub documents, orphans, broken links, Mermaid diagram
├── recent.md         # 20 most recently modified files
└── corpus/
    ├── research.md   # Per-corpus index
    ├── notes.md
    └── ...
```

Every file uses:
- **Wikilinks** `[[path/to/note]]` — click to navigate
- **YAML frontmatter** — queryable by Dataview (`TABLE generated_at FROM #rtfm`)
- **Callouts** `> [!info]` — Obsidian-native stats blocks
- **Mermaid diagrams** — rendered natively by Obsidian

### What the agent gets

In Claude Code, the agent uses `rtfm_search` instead of grepping your vault:

```
rtfm_search("formal grammars")     → 5 results with scores, no content (300 tokens)
rtfm_expand("research--paper-42")  → reads only the relevant section
```

Progressive disclosure: the context grows only by what's actually useful.

## Architecture: RTFM vs Karpathy

### Karpathy's model

```
raw/        ← Human drops sources here (immutable)
wiki/       ← LLM compiles structured notes
index.md    ← LLM maintains a flat navigation catalog
CLAUDE.md   ← Schema: conventions, workflows
```

**Limitation**: `index.md` is maintained by the LLM, doesn't scale past ~500 notes, and the LLM reads everything into context.

### RTFM-augmented model

```
raw/        ← Human drops sources here (unchanged)
wiki/       ← LLM compiles structured notes (unchanged)
_rtfm/      ← RTFM generates intelligent navigation (replaces index.md)
CLAUDE.md   ← Schema: references rtfm_search for retrieval
.rtfm/      ← Search index (SQLite + FTS5, invisible to Obsidian)
```

**What changes**: The LLM still writes the wiki. But instead of reading a flat `index.md`, it searches via RTFM. And instead of a manually maintained catalog, `_rtfm/` provides auto-generated navigation based on actual content analysis, link graphs, and relevance scoring.

### Why RTFM scales where index.md doesn't

| | Karpathy `index.md` | RTFM |
|---|---|---|
| Navigation | Flat catalog, LLM-maintained | Auto-generated, graph-aware |
| Search | Read index → scan pages | FTS5 + semantic + hybrid |
| Token cost | Grows with wiki size | Constant (~300 tokens per search) |
| Wikilinks | Written by LLM | Resolved and indexed as graph edges |
| Multi-format | Markdown only | 10 parsers (MD, Python, PDF, LaTeX, ...) |
| Metrics | None | Backlink counts, hub detection, orphan detection |

## Topologies: One Vault or Many?

Karpathy recommends one vault per project. RTFM's **corpus** system makes this a choice, not a constraint.

### Option 1: One vault per project (Karpathy-style)

Each project is its own Obsidian vault with its own `rtfm vault`.

```
~/projects/my-research/     ← Vault + rtfm vault
~/projects/my-app/          ← Vault + rtfm vault
```

**Best for**: Isolated projects with distinct knowledge domains.

### Option 2: One vault, multiple corpora

A single vault with folders mapped to corpora. RTFM scopes searches by corpus.

```
~/vault/
├── Research/          → corpus "research"
├── Projects/App/      → corpus "app"
├── Publications/      → corpus "publications"
└── _rtfm/             → navigation for everything
```

The agent searches with `rtfm_search("auth flow", corpus="app")` — only sees what's relevant.

**Best for**: Cross-domain work where connections between topics matter.

### Option 3: Code project + vault as external source

The code lives in a git repo. The vault is separate. RTFM bridges them.

```
~/code/my-app/              ← Git repo (Claude Code CWD)
├── src/
├── .rtfm/config.json       ← sources: [project, vault/Research]
└── CLAUDE.md

~/vault/                    ← Obsidian vault (rtfm vault)
├── Research/
├── _rtfm/
└── ...
```

The agent in `my-app` searches code AND vault notes in one query.

**Best for**: Code projects that need domain knowledge from a vault.

### The rule of thumb

| The project is... | Recommended setup |
|---|---|
| Pure knowledge (research, wiki, notes) | `rtfm vault` in the vault directly |
| Pure code (app, library, tool) | `rtfm init` in the repo, vault as external source |
| Both (research + code) | Either works — vault with code as corpus, or separate + linked |

## Wikilink Resolution

RTFM resolves `[[wikilinks]]` following Obsidian's rules:

1. **Exact filename match** (case-insensitive, `.md` optional)
2. **Path-suffix match**: `[[folder/Note]]` matches `some/folder/Note.md`
3. **Disambiguation**: when multiple files share a name, prefer the closest to the source file

Resolved links become **graph edges** in the database. This powers:
- **Hub detection** — notes with many backlinks rank higher in search
- **Orphan detection** — notes with no links (shown in `_rtfm/graph.md`)
- **Centrality boost** — `rtfm_search` can weight results by link density

## Recommended Obsidian Plugins

- **Dataview** — Query RTFM-generated frontmatter across the vault
  ```
  TABLE generated_at, total_documents FROM #rtfm
  ```
- **Graph View** (core) — `_rtfm/` pages appear as connected nodes in the graph
- **Obsidian Web Clipper** — Save web articles as markdown into `raw/` (Karpathy recommends this)

## CLI Reference

```bash
# Initialize vault
rtfm vault /path/to/vault                  # Auto-detect corpora, index, generate _rtfm/
rtfm vault /path/to/vault --no-embeddings  # Skip semantic embeddings
rtfm vault /path/to/vault --no-output      # Skip _rtfm/ generation
rtfm vault /path/to/vault --regenerate     # Regenerate _rtfm/ without re-syncing

# After initialization, standard RTFM commands work
rtfm search "query"                         # Search across all corpora
rtfm search "query" --corpus research       # Search specific corpus
rtfm sync                                   # Re-sync all sources
rtfm status                                 # Check index health
```

## Regeneration

- **Full**: `rtfm vault --regenerate` rebuilds all `_rtfm/` files from the database
- **Lightweight**: after each sync, `_rtfm/recent.md` updates automatically (single SQL query)
- **Manual**: delete `_rtfm/` and run `rtfm vault --regenerate` for a clean rebuild

`_rtfm/` files are never edited manually — they're always regenerable.
