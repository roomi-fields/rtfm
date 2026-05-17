---
description: Enable persistent OCR fallback for scanned PDFs in the current RTFM project
---

The user wants to enable OCR for scanned PDFs in this project.

Run `rtfm sync --ocr` using the Bash tool. This command:
- Writes `"ocr_fallback": true` to `.rtfm/config.json`, so every future
  sync (CLI or auto-sync hook) automatically OCRs scans.
- Re-indexes existing PDFs immediately. PDFs that already have a text
  layer go through `pdftext` (fast); only true scans trigger the slow
  `marker` OCR backend.
- Is a **one-shot** command — the user only needs to run it once per
  project. New scanned PDFs added later are OCR'd automatically.

The first run can take several minutes per scanned PDF (model download
on first invocation, OCR per page after that). The CLI prints a
progress line every 10 minutes during long runs.

Before running, warn the user briefly that the first invocation may take
several minutes and ask for confirmation if there are many scans.

After completion, summarize:
- How many PDFs were successfully OCR-extracted this run
- How many remain in `seen_scans.json` (truly broken — image-only with no
  recoverable text, or corrupt)
- Confirm OCR fallback is now persistent and future scans will be handled
  automatically without re-running this command.
