---
description: Install the light PDF parser (pdftext, ~50 MB) into an isolated venv. Covers most PDFs with fast, accurate text extraction. For complex layouts (tables, figures, scanned docs), use /rtfm:install-pdf-full instead.
---

Install RTFM's light PDF parser by running this command via the Bash tool:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/rtfm-install-extras" pdf
```

After it completes, tell the user to restart Claude Code so the MCP server picks up the new extras venv, then run `rtfm_sync` (or wait for the next UserPromptSubmit hook) to actually index any PDFs in the project.

If the user has complex PDFs (tables, figures, scanned layouts), suggest `/rtfm:install-pdf-full` instead — that one pulls marker-pdf with a CPU-only torch build (~1.5 GB).
