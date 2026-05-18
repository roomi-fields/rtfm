---
description: Show full RTFM index status (with pending-sync counts and health signals)
---

The user wants the current RTFM indexing status for this project.

Run `rtfm status --health` using the Bash tool. The `--health` flag adds
pending-sync counts on top of the default output:
- Books / chunks / corpora / embedding coverage
- Date of the last sync
- Registered parsers and optional extras (pdf, embeddings, ...)
- **Index health**:
  - `+ N new file(s) not yet indexed` (run `rtfm sync`)
  - `~ N modified file(s) since last sync` (run `rtfm sync`)
  - `- N file(s) in DB but missing on disk` (run `rtfm sync`)
  - `⚠ N PDF(s) flagged as likely scans` (run `/rtfm.ocr` or `rtfm sync --ocr`)

Note: `--health` walks every configured source and `stat()`s every tracked
file. On corpora that live on NTFS-via-WSL or network shares, this can take
tens of seconds per source — it's normal, just let it run.

If an **OCR daemon section** appears in the output (e.g. `OCR running
(PID X): 23/156 PDFs (15%), 1h20m elapsed, ETA ~6h`), highlight it
first — that's the most time-sensitive signal for the user.

After it completes, summarize the key signals:
- Is an OCR daemon currently running, and where is it in its progress?
  (If `OCR interrupted at K/N`, suggest `rtfm sync --ocr` to resume.)
- Is the index up to date or are there pending files?
- Are there scan suspects waiting for OCR?
- Anything that requires user action?
