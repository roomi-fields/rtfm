---
description: Read the full content of a specific file or section previously returned by rtfm_search. Use when the user wants to see the actual content of a search result, not just metadata.
---

# rtfm:expand

Expand the content of a result: **$ARGUMENTS**

Call `mcp__rtfm__rtfm_expand` with the source path (and optionally `target_section`) derived from $ARGUMENTS. Return the content verbatim with its marker.

If $ARGUMENTS is empty or ambiguous, ask the user which result to expand.
