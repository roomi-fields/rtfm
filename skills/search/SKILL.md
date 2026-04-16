---
description: Search the RTFM-indexed corpus of the current project (code, docs, data). Use for any exploratory search — finding relevant files, modules, symbols, or content. Faster and more precise than Glob/Grep/find for broad queries.
---

# rtfm:search

Search the RTFM index with the user's query: **$ARGUMENTS**

Call the `mcp__rtfm__rtfm_search` tool with `query="$ARGUMENTS"`. Return the metadata results (file paths, sections, scores). If the user wants to read specific content, follow up with `mcp__rtfm__rtfm_expand` on the most relevant result.

Prefer this over Glob/Grep for concept-level queries.
