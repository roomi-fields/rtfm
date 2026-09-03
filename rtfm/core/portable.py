"""The operating-system calls Unix and Windows disagree about.

Every one of them was written for Linux and left unguarded, and the result
was that 0.35.7 could not run a *single* command on native Windows: the CLI
imports the worker module, which imported ``fcntl`` at the top level, so even
``rtfm --version`` died before argument parsing ever ran (issue #8).

Guarding that one import is not enough. Four more calls behind it are
Unix-only, or — worse — mean something else entirely on Windows:

* ``os.pread`` does not exist there.
* ``os.kill(pid, 0)``, the liveness probe, does not probe on Windows: it
  calls ``TerminateProcess``. Asking "is the supervisor still alive?" would
  have killed it, and killed whatever process had recycled that PID.
* ``signal.SIGKILL`` is not defined, so the last-resort kill in
  ``restart-all`` raised ``AttributeError`` instead of killing anything.
* ``start_new_session`` is accepted and silently ignored, so the supervisor
  would have died with the console that spawned it.

They live here, together, so that a platform difference is a change to one
module and never a surprise in the middle of the indexer. A test asserts
that nothing else in the package reaches for them directly.

**The lock is the load-bearing part.** Exactly one supervisor may run, and
that is enforced by holding an exclusive lock for the process' entire life:
the kernel releases it when the holder dies, however it dies, which is what
lets "the lock is held" mean "a live supervisor exists" with no window where
a stale PID file lies about it. Both platforms give that guarantee, through
different calls — ``flock`` on Unix (whole file, advisory) and ``_locking``
on Windows (a byte range, mandatory).

That difference is why the lock file has a layout at all. A Windows byte
range lock is mandatory: a process would be *refused* the bytes another
process holds locked. So the lock byte and the PID stamped alongside it must
not overlap, and there byte 0 is the lock byte with the PID written from byte
1 on. On Unix ``flock`` ignores ranges entirely, so the PID stays at byte 0
and the file keeps exactly the format every earlier version wrote — no
release has to guess which layout it is reading.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    _fcntl = None

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

#: Where the PID starts in a lock file. Nonzero only where byte 0 has to be
#: reserved for the lock itself (see the module docstring).
PAYLOAD_OFFSET = 1 if _fcntl is None and _msvcrt is not None else 0

#: Bytes of PID stamp read back. A PID is at most 7 digits anywhere.
_STAMP_BYTES = 32


class LockUnavailable(RuntimeError):
    """This platform offers neither ``flock`` nor ``_locking``.

    Raised when a lock is actually attempted, never at import: every
    read-only command keeps working on such a platform, and only the one
    thing that genuinely cannot be made safe — running the supervisor —
    refuses, loudly.
    """


def open_lock_file(path: Path | str, create: bool = True) -> int:
    """Open *path* for locking and return the file descriptor.

    ``O_BINARY`` where it exists: on Windows a text-mode descriptor would
    translate the newline in the PID stamp and shift every offset.
    """
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    if create:
        flags |= os.O_CREAT
    return os.open(path, flags, 0o644)


def try_lock_exclusive(fd: int) -> bool:
    """Take the exclusive lock on *fd* without blocking.

    Returns ``True`` when acquired, ``False`` when another live process
    holds it. The lock is released by the kernel if this process dies.
    """
    if _fcntl is not None:
        # Only "someone else holds it" is caught. Anything else — a bad
        # descriptor, a filesystem with no lock daemon — must surface, not
        # read as contention: that is the behaviour Linux has always had
        # here and this change is not the place to alter it.
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    if _msvcrt is not None:
        # A byte range lock needs the byte to be inside the file. A lock
        # file starts out empty, so give it its one reserved byte first —
        # two processes racing here write the same byte and neither cares.
        try:
            if os.fstat(fd).st_size == 0:
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, b"\n")
        except OSError:
            return False
        return _with_position(fd, 0, lambda: _msvcrt_lock(fd))
    raise LockUnavailable(
        "no file locking on this platform (neither fcntl nor msvcrt): "
        "refusing to run a supervisor that cannot stay unique"
    )


def unlock(fd: int) -> None:
    """Release the lock held on *fd*. Never raises."""
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        except OSError:
            pass
        return
    if _msvcrt is not None:
        _with_position(fd, 0, lambda: _msvcrt_unlock(fd))


def stamp_pid(fd: int, pid: Optional[int] = None) -> None:
    """Write our PID into the lock file, for whoever reads it later.

    Observability only — liveness comes from the lock. Truncates to
    :data:`PAYLOAD_OFFSET`, never below, so the reserved lock byte survives
    a re-stamp while the lock is held on it.
    """
    text = f"{os.getpid() if pid is None else pid}\n".encode()
    try:
        os.ftruncate(fd, PAYLOAD_OFFSET)
        _with_position(fd, PAYLOAD_OFFSET, lambda: os.write(fd, text))
    except OSError:
        pass


def read_stamped_pid(fd: int) -> Optional[int]:
    """The PID stamped in the lock file, or ``None`` if there is none."""
    try:
        raw = _with_position(
            fd, PAYLOAD_OFFSET, lambda: os.read(fd, _STAMP_BYTES))
    except OSError:
        return None
    digits = raw.split(b"\n", 1)[0].strip()
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def _with_position(fd: int, offset: int, fn):
    """Run *fn* with the descriptor at *offset*, then put it back.

    ``os.pread``/``os.pwrite`` would do this in one call and do not exist on
    Windows. Restoring the position matters: the callers own the descriptor
    and write to it around these calls.
    """
    try:
        here = os.lseek(fd, 0, os.SEEK_CUR)
    except OSError:
        here = None
    os.lseek(fd, offset, os.SEEK_SET)
    try:
        return fn()
    finally:
        if here is not None:
            try:
                os.lseek(fd, here, os.SEEK_SET)
            except OSError:
                pass


def _msvcrt_lock(fd: int) -> bool:  # pragma: no cover - Windows only
    try:
        _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _msvcrt_unlock(fd: int) -> None:  # pragma: no cover - Windows only
    try:
        _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


# ── liveness ────────────────────────────────────────────────────────────

def pid_alive(pid: int) -> bool:
    """Is a process with this PID running?

    On Unix this is ``kill(pid, 0)``: no signal sent, an error raised if the
    PID is gone. On Windows the very same call **terminates** the process,
    so there it asks the process handle instead.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":  # pragma: no cover - Windows only
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists, it just isn't ours — alive enough that we must not
        # overwrite its state or reuse its slot.
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Same reading as PermissionError above: refused, therefore there.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


# ── process control ─────────────────────────────────────────────────────

def hard_kill_signal() -> int:
    """The signal for "stop now, no draining".

    ``SIGKILL`` where it exists. On Windows every signal but the two console
    events goes through ``TerminateProcess`` anyway, so ``SIGTERM`` *is* the
    hard kill there — which also means the graceful step before it is not
    graceful on Windows. Nothing here can change that: a cooperative stop
    needs the supervisor to be asked rather than signalled.
    """
    return getattr(signal, "SIGKILL", signal.SIGTERM)


def detached_popen_kwargs() -> dict:
    """Popen keywords that outlive the parent shell, hook or console.

    ``start_new_session`` is a POSIX ``setsid`` and is accepted-then-ignored
    on Windows, where detaching is a creation flag instead.
    """
    if sys.platform == "win32":  # pragma: no cover - Windows only
        return {"creationflags": (subprocess.DETACHED_PROCESS
                                  | subprocess.CREATE_NEW_PROCESS_GROUP)}
    return {"start_new_session": True}
