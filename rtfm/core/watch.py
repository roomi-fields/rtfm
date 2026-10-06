"""Being told when a source changes, instead of looking every minute.

The periodic scan cannot know that a directory is idle: the only way it has
to find out is to list every file again. It did, every minute, on every
source of every project — a project nobody had touched for months cost as
much as an active one, and one with 48 sources never got past its own scans.

On Linux the kernel says when something changes (inotify). One watch covers
one directory, not a tree, so a source is watched directory by directory,
skipping what the scan skips — dependencies, version-control stores, agent
working copies, and what the project's ignore files exclude. A change marks
its source; the supervisor scans that source once the activity settles.

Not everything can be watched, and the supervisor falls back to looking:

- a network share — a change made on the other machine is never reported;
- a directory the kernel's watch budget cannot cover;
- any system without inotify.

Notifications can also be lost (the kernel drops them when its queue fills),
which is reported as an overflow: every watched source is then marked
changed, and a daily scan remains as the last safety net.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import select
import struct
import sys
import threading
from pathlib import Path
from typing import Callable, Hashable, Optional

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ONLYDIR = 0x01000000
IN_DONT_FOLLOW = 0x02000000
IN_EXCL_UNLINK = 0x04000000
IN_ISDIR = 0x40000000
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000

WATCH_MASK = (IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE
              | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF
              | IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK)

_EVENT = struct.Struct("iIII")

#: File systems where a change can come from another machine, which the
#: kernel then never reports. Looked at, not watched.
NETWORK_FILESYSTEMS = frozenset({
    "cifs", "smb3", "smbfs", "nfs", "nfs4", "9p", "afs", "ceph", "glusterfs",
    "lustre", "fuse.sshfs", "sshfs", "fuse.rclone", "davfs", "fuse.davfs2",
    "drvfs", "fuse.gvfsd-fuse", "virtiofs",
})


def filesystem_type(path: str,
                    mountinfo: str = "/proc/self/mountinfo") -> Optional[str]:
    """The type of the file system *path* lives on, from the mount table.

    Lexical on purpose: it never touches *path* itself, so a source on a
    share that has gone dark cannot block the caller.
    """
    try:
        with open(mountinfo, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    path = os.path.abspath(path)
    best, kind = "", None
    for line in lines:
        left, _, right = line.partition(" - ")
        fields = left.split()
        if len(fields) < 5 or not right:
            continue
        mount = fields[4].replace("\\040", " ")
        if (path == mount or path.startswith(mount.rstrip("/") + "/")) \
                and len(mount) >= len(best):
            # Equal length: a later line is mounted over an earlier one
            # (autofs, then the share it mounts on demand).
            best, kind = mount, right.split()[0]
    return kind


def is_network_path(path: str) -> bool:
    return filesystem_type(path) in NETWORK_FILESYSTEMS


class _Libc:
    def __init__(self) -> None:
        name = ctypes.util.find_library("c") or "libc.so.6"
        self.lib = ctypes.CDLL(name, use_errno=True)
        self.lib.inotify_init1.argtypes = [ctypes.c_int]
        self.lib.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p,
                                               ctypes.c_uint32]
        self.lib.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]


def watching_supported() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        return hasattr(_Libc().lib, "inotify_init1")
    except OSError:
        return False


class _Source:
    """What is known about one watched source: where it is and what it skips."""

    def __init__(self, root: str, exclude_dirs: frozenset, honor_gitignore: bool):
        from rtfm.core.sync import _load_gitignore_spec, _load_rtfmignore_spec
        self.root = root
        self.exclude_dirs = exclude_dirs
        self.honor_gitignore = honor_gitignore
        self.gitignore = _load_gitignore_spec(Path(root)) if honor_gitignore else None
        self.rtfmignore = _load_rtfmignore_spec(Path(root))
        self.wds: set[int] = set()

    def reload_ignores(self) -> None:
        from rtfm.core.sync import _load_gitignore_spec, _load_rtfmignore_spec
        self.gitignore = (_load_gitignore_spec(Path(self.root))
                          if self.honor_gitignore else None)
        self.rtfmignore = _load_rtfmignore_spec(Path(self.root))

    def ignores(self, rel: str, is_dir: bool) -> bool:
        """True for a path whose change the scan would not act on."""
        from rtfm.core.sync import TRANSIENT_SUFFIXES, _under_excluded_subpath
        parts = Path(rel).parts
        if any(p in self.exclude_dirs for p in parts) or _under_excluded_subpath(parts):
            return True
        if not is_dir and rel.endswith(TRANSIENT_SUFFIXES):
            return True
        probe = rel + "/" if is_dir else rel
        for spec in (self.gitignore, self.rtfmignore):
            if spec is not None and spec.match_file(probe):
                return True
        return False


class TreeWatcher:
    """Watches source trees and reports which source changed, and when.

    One inotify instance for the whole process; a directory shared by two
    sources (two projects indexing the same tree) is watched once and its
    events reach both. Watching a source walks its tree, so it happens on
    this object's own thread — never on the caller's.

    ``changed(key)`` is called from the watcher thread with the key given to
    :meth:`watch`; ``failed(key, reason)`` when a source cannot be watched.
    """

    def __init__(self, changed: Callable[[Hashable], None],
                 failed: Callable[[Hashable, str], None],
                 log: Callable[[str], None] = lambda m: None) -> None:
        self._changed = changed
        self._failed = failed
        self._log = log
        self._libc = _Libc()
        self._fd = self._libc.lib.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self._fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self._lock = threading.Lock()
        self._sources: dict[Hashable, _Source] = {}
        self._wd_keys: dict[int, set[Hashable]] = {}
        self._wd_path: dict[int, str] = {}
        self._requests: list[tuple[str, Hashable, tuple]] = []
        self._wake_r, self._wake_w = os.pipe()
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="rtfm-watch",
                                        daemon=True)
        self._thread.start()

    # ── requests from the supervisor (any thread) ────────────────────────

    def watch(self, key: Hashable, root: str, exclude_dirs: frozenset,
              honor_gitignore: bool = True) -> None:
        with self._lock:
            self._requests.append(("watch", key, (root, exclude_dirs, honor_gitignore)))
        os.write(self._wake_w, b"w")

    def unwatch(self, key: Hashable) -> None:
        with self._lock:
            self._requests.append(("unwatch", key, ()))
        os.write(self._wake_w, b"u")

    def watched_directories(self) -> int:
        return len(self._wd_path)

    def close(self) -> None:
        self._stop = True
        try:
            os.write(self._wake_w, b"x")
        except OSError:
            pass
        self._thread.join(timeout=5)
        for fd in (self._fd, self._wake_r, self._wake_w):
            try:
                os.close(fd)
            except OSError:
                pass

    # ── the watcher thread ───────────────────────────────────────────────

    def _run(self) -> None:
        poller = select.poll()
        poller.register(self._fd, select.POLLIN)
        poller.register(self._wake_r, select.POLLIN)
        while not self._stop:
            try:
                ready = poller.poll(1000)
            except InterruptedError:
                continue
            for fd, _ in ready:
                if fd == self._wake_r:
                    try:
                        os.read(self._wake_r, 4096)
                    except BlockingIOError:
                        pass
                    self._serve_requests()
                elif fd == self._fd:
                    self._read_events()

    def _serve_requests(self) -> None:
        with self._lock:
            requests, self._requests = self._requests, []
        for kind, key, args in requests:
            try:
                if kind == "watch":
                    self._unwatch(key)
                    self._watch(key, *args)
                else:
                    self._unwatch(key)
            except Exception as exc:  # a bad source must not stop the thread
                self._unwatch(key)
                self._failed(key, f"{type(exc).__name__}: {exc}")

    def _add(self, key: Hashable, path: str) -> bool:
        """Watch one directory for *key*. False when the budget is spent."""
        wd = self._libc.lib.inotify_add_watch(self._fd, os.fsencode(path), WATCH_MASK)
        if wd < 0:
            err = ctypes.get_errno()
            if err == errno.ENOSPC:
                return False
            return True  # vanished or unreadable: nothing to watch there
        self._wd_keys.setdefault(wd, set()).add(key)
        self._wd_path[wd] = path
        self._sources[key].wds.add(wd)
        return True

    def _add_tree(self, key: Hashable, top: str) -> bool:
        src = self._sources[key]
        for here, dirs, _ in os.walk(top):
            if not self._add(key, here):
                return False
            rel_here = os.path.relpath(here, src.root)
            rel_here = "" if rel_here == "." else rel_here
            dirs[:] = [d for d in dirs
                       if not src.ignores(os.path.join(rel_here, d), True)]
        return True

    def _watch(self, key: Hashable, root: str, exclude_dirs: frozenset,
               honor_gitignore: bool) -> None:
        if not os.path.isdir(root):
            self._failed(key, "not a directory")
            return
        self._sources[key] = _Source(root, exclude_dirs, honor_gitignore)
        if not self._add_tree(key, root):
            self._unwatch(key)
            self._failed(key, "the system's watch budget is spent "
                              "(fs.inotify.max_user_watches)")
            return
        self._log(f"watching {len(self._sources[key].wds)} director"
                  f"{'y' if len(self._sources[key].wds) == 1 else 'ies'} of {root}")

    def _unwatch(self, key: Hashable) -> None:
        src = self._sources.pop(key, None)
        if src is None:
            return
        for wd in src.wds:
            keys = self._wd_keys.get(wd)
            if keys is None:
                continue
            keys.discard(key)
            if not keys:
                self._wd_keys.pop(wd, None)
                self._wd_path.pop(wd, None)
                self._libc.lib.inotify_rm_watch(self._fd, wd)

    def _read_events(self) -> None:
        try:
            data = os.read(self._fd, 256 * 1024)
        except BlockingIOError:
            return
        except OSError as exc:
            self._log(f"watch: read failed ({exc})")
            return
        offset = 0
        hit: set[Hashable] = set()
        rewatch: set[Hashable] = set()
        while offset + _EVENT.size <= len(data):
            wd, mask, _cookie, length = _EVENT.unpack_from(data, offset)
            offset += _EVENT.size
            name = data[offset:offset + length].rstrip(b"\0").decode(
                "utf-8", errors="surrogateescape")
            offset += length
            if mask & IN_Q_OVERFLOW:
                hit.update(self._sources)
                continue
            if mask & IN_IGNORED:
                for key in self._wd_keys.pop(wd, set()):
                    if key in self._sources:
                        self._sources[key].wds.discard(wd)
                self._wd_path.pop(wd, None)
                continue
            here = self._wd_path.get(wd)
            if here is None:
                continue
            is_dir = bool(mask & IN_ISDIR)
            for key in list(self._wd_keys.get(wd, ())):
                src = self._sources.get(key)
                if src is None:
                    continue
                if mask & (IN_DELETE_SELF | IN_MOVE_SELF):
                    hit.add(key)
                    if here == src.root or mask & IN_MOVE_SELF:
                        rewatch.add(key)
                    continue
                rel = os.path.relpath(os.path.join(here, name), src.root)
                if name in (".gitignore", ".rtfmignore") and here == src.root:
                    src.reload_ignores()
                    hit.add(key)
                    continue
                if src.ignores(rel, is_dir):
                    continue
                hit.add(key)
                if is_dir and mask & (IN_CREATE | IN_MOVED_TO):
                    if not self._add_tree(key, os.path.join(here, name)):
                        self._unwatch(key)
                        self._failed(key, "the system's watch budget is spent "
                                          "(fs.inotify.max_user_watches)")
                elif is_dir and mask & IN_MOVED_FROM:
                    # Watches below keep the old path; rebuild them.
                    rewatch.add(key)
        for key in rewatch:
            src = self._sources.get(key)
            if src is not None:
                root, excl, honor = src.root, src.exclude_dirs, src.honor_gitignore
                self._unwatch(key)
                self._watch(key, root, excl, honor)
        for key in hit:
            self._changed(key)
