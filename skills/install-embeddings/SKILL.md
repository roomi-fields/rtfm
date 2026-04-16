---
description: Install the embeddings extra (fastembed, ~85 MB ONNX model) into an isolated venv. Required for semantic and hybrid search modes. The model runs on CPU, no GPU needed.
---

Install RTFM's embeddings extra by running this command via the Bash tool:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/rtfm-install-extras" embeddings
```

After it completes, tell the user to restart Claude Code so the MCP server picks up the new extras venv. Then `rtfm_search` with `search_type="semantic"` or `"hybrid"` will work.
