---
title: RTFM × NotebookLM — Break the 50 queries/day cap
description: >-
  Pair RTFM with notebooklm-mcp to index NotebookLM batch answers locally.
  Two integration paths: zero-config markdown, or typed JSON sidecar via
  declarative YAML mapping. Citations queryable, edges between answers
  and sources.
---

# RTFM × NotebookLM

NotebookLM caps you at 50 queries/day per notebook. RTFM removes that ceiling
by indexing the answers locally: ask once, retrieve forever, offline, in
milliseconds.

This guide shows how to plug
[`notebooklm-mcp`](https://github.com/roomi-fields/notebooklm-mcp) batch
outputs into RTFM. Two paths, both work:

- **Markdown path** — zero config, the default markdown parser already does
  the right thing
- **JSON path** — typed metadata + faceted source filtering via a one-time
  YAML mapping

## What `notebooklm-mcp` produces

Calling `POST /batch-to-vault` writes two files per question into a
directory of your choice:

```
vault/
├── what-is-the-osbd-process.md       # frontmatter + answer + cited excerpts
└── what-is-the-osbd-process.json     # structured nblm-answer-v1 sidecar
```

The markdown is the human-friendly artifact. The JSON sidecar conforms to
the **[nblm-answer-v1 JSON Schema](https://schemas.roomi-fields.com/nblm-answer-v1.json)**
(stable, semver-versioned — breaking changes ship as `nblm-answer-v2`).
Full integration notes:
[`notebooklm-mcp/deployment/docs/14-RTFM-INTEGRATION.md`](https://github.com/roomi-fields/notebooklm-mcp/blob/main/deployment/docs/14-RTFM-INTEGRATION.md).
Both files are guaranteed to coexist.

## Path A — Markdown (zero config)

```bash
cd /path/to/vault
rtfm init --no-embeddings
rtfm add . --corpus nblm
rtfm sync
```

That's it. RTFM's markdown parser groups by `## Answer` and `### [N] source`
headers, so:

| Search query lands on… | Chunk header path |
|---|---|
| Answer body keywords | `> Answer` |
| Cited excerpt content | `> [N] <source name>` |
| Source filename | `> [N] <source name>` |
| Asked question | `> Q: <question>` |

YAML frontmatter (notebook_url, sources array, asked_at) is also indexed as
plain text — full-text searchable but not typed.

## Path B — JSON sidecar (typed metadata + edges)

For typed metadata in `chunks.metadata` (queryable via SQL), faceted source
names, and `cites` edges between answer and source files, drop the
`nblm-answer.yaml` mapping into `.rtfm/mappings/`:

```yaml
# .rtfm/mappings/nblm-answer.yaml
# yaml-language-server: $schema=https://schemas.roomi-fields.com/rtfm-mapping-v1.json
name: nblm-answer-v1

match:
  schema_url: "https://schemas.roomi-fields.com/nblm-answer-v1.json"
  discriminator:
    type: nblm-answer

chunks:
  - title: "Q: {{ question }}"
    content: "{{ answer.text }}"
    metadata:
      notebook_id: "{{ notebook.id }}"
      notebook_url: "{{ notebook.url }}"
      asked_at: "{{ asked_at }}"

  - foreach: citations
    title: "{{ marker }} {{ source_name }}"
    content: "{{ source_text }}"
    metadata:
      source_name: "{{ source_name }}"
      citation_marker: "{{ marker }}"

edges:
  - relation: cites
    foreach: citations
    target: "{{ source_name }}"
    target_kind: literal
```

After re-syncing, every `.json` answer file produces:

- **1 chunk** for `question + answer.text` (typed metadata: notebook id, URL,
  date)
- **N chunks** for each citation, with `source_name` and `citation_marker` in
  typed metadata
- **`cites` edges** linking the answer to each citation source by name

Now you can write SQL like:

```sql
SELECT chunk_id, content
FROM chunks
WHERE json_extract(metadata, '$.source_name') LIKE '%Keller%';
```

…or use the answer file's `notebook_id` to group everything from the same
notebook.

> See the full [JSON Schema Mappings reference](json-mappings.md) for
> mapping syntax — `target_kind`, nested discriminators, multi-foreach
> chunks, etc.

## Recommended architecture

```
[Once per notebook, periodic]
  CLI agent generates exhaustive question set
    → notebooklm-mcp /batch-to-vault → vault/*.md + vault/*.json

[At will, unlimited, offline, ~ms]
  Agent → rtfm_search → rtfm_expand → answer
```

Generate batches when knowledge changes (new sources added to the notebook,
old answers stale). Query through RTFM the rest of the time. NotebookLM's
50/day quota becomes irrelevant.

## Which path should I use?

| If you… | Use |
|---|---|
| just want it to work | Path A (markdown) |
| want to filter results by source name | Path B (JSON + mapping) |
| want a graph of answers ↔ sources | Path B + index the cited PDFs too |
| are not sure | Path A first, then add Path B if you hit a limit |

Both paths can coexist — the markdown and JSON files are independent and
search results are deduplicated by content hash.

## Notes on the `cites` edge

The mapping above produces `cites` edge candidates. RTFM's edge resolver
currently materializes `import`, `link`, and `include` relations into the
`edges` table; custom relations like `cites` pass through `extract_edges`
but are not yet stored. If the cited PDFs are themselves indexed in RTFM,
the resolver will be extended to match `cites` targets by filename — track
[issue #TBD] for status.

In the meantime, citation source names are queryable via
`chunks.metadata.source_name`, which covers most retrieval needs without a
graph.
