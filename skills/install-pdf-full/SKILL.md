---
description: Install the full PDF parser (pdftext + marker-pdf + CPU-only torch, ~1.5 GB) into an isolated venv. Needed for complex layouts — tables, figures, scanned documents. Skip this if /rtfm:install-pdf (~50 MB, text only) is enough.
---

Warn the user first: **this downloads ~1.5 GB** (torch CPU-only build is ~500 MB, marker-pdf and its deps add the rest). Confirm they want to proceed before running.

If confirmed, run this command via the Bash tool:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/rtfm-install-extras" pdf-full
```

After it completes, tell the user to restart Claude Code, then run `rtfm_sync` to re-index PDFs with the richer parser.

The install uses the PyTorch CPU index (`https://download.pytorch.org/whl/cpu`) to avoid pulling the default 5 GB CUDA build. No GPU required.
