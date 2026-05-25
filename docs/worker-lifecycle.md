---
title: Worker lifecycle — how RTFM stays autonomous
description: >-
  How the background worker daemon manages itself: when it starts,
  when it exits, and the three layers that respawn it automatically
  so you never have to think about it.
---

# Worker lifecycle

RTFM is meant to be **install-once-forget**. The background worker that drains the priority queue manages its own lifecycle, and there are three independent layers that keep it alive across upgrades, memory issues, and inactivity. You should never need to run a worker command by hand.

## What the worker does

Every project that has been indexed (any `.rtfm/library.db`) gets its own worker process. The worker is the **only thing** that writes to the database. CLI commands, hooks and slash commands all enqueue jobs; the worker drains them by priority (P0 user-explicit → P6 OCR). See `docs/architecture.md` for the priority model.

One project = one worker. A `flock` on `.rtfm/worker.lock` enforces uniqueness.

## When the worker exits — and what happens next

The worker exits in three situations. **Two of them auto-respawn**; one is intentional and stays stopped.

### 1. The package was upgraded on disk

When you `pip install --force-reinstall rtfm-ai` (or `pipx install --force`), the wheel writes new Python modules, but the worker is still running with the *old* code in memory. Without intervention, your new feature would not take effect until the worker restarted — possibly hours later.

What happens:

- At every idle tick (~5 s), the worker compares `importlib.metadata.version("rtfm-ai")` with the version it captured at its own startup.
- If they differ, the worker logs `version changed on disk, exiting for restart` and exits cleanly.
- **Just before exiting, it forks a small detached helper.** That helper sleeps a few seconds (so the parent's lock is released), then calls `ensure_worker_running`, which spawns a fresh worker with the new code.
- In parallel, the **lazy check** in every CLI command also catches this: the next time you run any `rtfm` command, it notices the version mismatch and triggers `rtfm worker restart-all` for you. Both mechanisms are idempotent.

You don't have to do anything. Within ~10 seconds of an upgrade, every project's worker is back, running the new code.

### 2. Memory pressure (RSS over threshold)

A pathological file (a malformed PDF that loops inside the parser, a too-large embedding batch, a runaway library) once made the worker consume 13 GB of RSS and triggered the kernel OOM-killer. The kernel terminated the worker without a graceful exit, lost in-flight state, and contributed to broader system chaos.

What happens now:

- At startup the worker sets `RLIMIT_AS` (virtual-address-space cap, default 8 GB). The next allocation past this raises `MemoryError` — catchable, the per-job handler marks the job `failed` and continues.
- At every idle tick the worker reads its own RSS from `/proc/self/status`. Above 5 GB it logs `RSS …M exceeds threshold — exiting for restart` and exits cleanly.
- **Same fork-helper as above** schedules the respawn. Fresh worker, fresh memory, queue resumes.

You can opt out per-project (e.g. for marker-pdf, whose ML models legitimately need 3-8 GB) with `RTFM_WORKER_MEMORY_LIMIT_GB=0` in the environment.

### 3. You asked it to stop

`rtfm worker stop` sends `SIGTERM`. The worker finishes its current job and exits. **No respawn** in this case — you said stop, it stays stopped.

To start it again: `rtfm worker start`, or any session prompt with the RTFM hooks installed will revive it via `ensure_worker_running`.

## The three respawn layers (summary)

| Layer | When | Coverage |
|---|---|---|
| Fork-helper on clean exit | Worker decides to exit (drift / RSS) | Self-managed exits |
| Lazy check in every CLI command | Any `rtfm …` invocation, throttled to once per minute | First user action after `pip install` |
| Session hooks (`UserPromptSubmit`, `PostToolUse`) | Any prompt or file edit in Claude Code | Active sessions |

Each layer is idempotent: if two layers fire at the same time, only the first to acquire the lock wins; the other silently no-ops.

## The one case you may still hit (and how to recover)

A **hard `SIGKILL`** — kernel OOM-kill on a system under extreme pressure, or `kill -9` from a human — bypasses every layer above because the worker doesn't get a chance to fork its helper. The lazy CLI check will catch this the next time you run any `rtfm` command. If you've just `kill -9`-ed a worker and want it back immediately:

```sh
rtfm worker restart-all
```

That reads `~/.rtfm/workers.json` (a registry every spawn updates automatically) and brings every project's worker back. Works from any directory.

## Where to look when something feels off

- `rtfm worker status` — what the worker is doing right now (idle / busy + current job).
- `rtfm queue stats` — pending / running / done / failed counts per job type.
- `rtfm queue failed` (or `rtfm failed`) — flat list of files that errored out, with the reason.
- `.rtfm/rtfm.log` — chronological log of every worker event (start, scan, OCR done, version drift, RSS exit, …).
- `~/.rtfm/workers.json` — the cross-project registry. Edit only to remove a project that no longer exists.

## What you should never need to do

You should never have to:

- Manually `kill` and respawn the worker after an upgrade. The fork-helper + lazy CLI check covers it.
- Add a cron entry or systemd unit. The above three layers are sufficient for normal use.
- Remember to run `restart-all` after `pip install`. The lazy CLI check fires automatically the next time you run any `rtfm` command.

If any of these *does* become necessary, that's a bug. File an issue.
