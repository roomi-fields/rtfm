---
description: Enable persistent OCR fallback for scanned PDFs and run the OCR pass in the background
---

The user wants to enable OCR for scanned PDFs in this project.

Run `rtfm sync --ocr` using the Bash tool. This command:
- Writes `"ocr_fallback": true` to `.rtfm/config.json`, so every future
  sync (CLI or auto-sync hook) automatically OCRs scans.
- Invalidates the tracked hash of every PDF currently flagged in
  `.rtfm/seen_scans.json`, so the next incremental sync re-ingests them
  through the `marker` backend.
- **Forks a detached background daemon** (`rtfm ocr-worker`) that does
  the actual OCR work. The command returns immediately with the daemon's
  PID — the user does **not** wait for OCR to finish at the prompt.
- Is **one-shot persistence**: the user only runs this once per project.
  New scanned PDFs added later are OCR'd automatically by the next sync.

The daemon survives terminal close and Claude Code hook timeouts because
it is launched with `start_new_session=True` (its own process session,
immune to parent SIGHUP). If it crashes, `.rtfm/ocr_state.json` stays on
disk so the next `rtfm sync --ocr` resumes from where it left off.

After running the command, briefly tell the user:
- The PID of the started daemon (read from the command's output)
- That OCR runs in the background and will not block them
- That they can check progress with `/rtfm.status` or `rtfm status`

Do **not** wait or poll. The daemon's output is silent (DEVNULL) — the
status file is the source of truth, surfaced by `rtfm status`.

If the command output says "An OCR daemon is already running", report
the existing progress to the user instead of relaunching.
