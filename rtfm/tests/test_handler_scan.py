"""Tests for the P1 ``scan`` job handler (``rtfm.core.handlers.handle_scan``).

The scan handler replaces the legacy inline ``_scan_once`` + the
destructive ``sync()`` removal block. Its contract:

* Discover diff vs the indexed_files table, then *fan out*: emit one
  child job per file. No parsing inside the handler.
* Apply moves (same- and cross-corpus) inline — those are cheap row
  updates.
* Removals → ``remove`` jobs, *but* the mass-removal circuit breaker
  refuses suspiciously large batches unless ``force_remove=True``.
* Auto-enqueue a one-shot ``vacuum`` when a single scan triggers more
  than ``AUTO_VACUUM_AFTER_REMOVES`` removals.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rtfm.core.handlers import (
    AUTO_VACUUM_AFTER_REMOVES,
    handle_scan,
)
from rtfm.core.library import Library
from rtfm.core.queue import Job, Queue
from rtfm.core.sync import _path_to_slug, compute_file_hash


def _fake_worker(db_path: Path):
    """Same shape as the worker fake used in ``test_handlers.py``: only
    ``db_path`` and ``_log`` are touched by the handler."""
    logs: list[str] = []
    return SimpleNamespace(
        db_path=db_path,
        _log=lambda msg: logs.append(msg),
        _logs=logs,
    )


def _write_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _seed_indexed(lib: Library, *, corpus: str, root: Path,
                  rels: list[str], real_hashes: bool = True) -> None:
    """Populate ``indexed_files`` so the diff considers these files
    already-tracked. Uses real MD5s when the file exists so a re-scan
    sees them as ``unchanged`` (not ``modified``)."""
    for rel in rels:
        abs_path = root / rel
        if real_hashes and abs_path.is_file():
            h = compute_file_hash(abs_path)
            size = abs_path.stat().st_size
        else:
            # Fake hash — file does not exist on disk (we want it
            # treated as ``removed``).
            h = "deadbeef" * 4
            size = 0
        lib.update_indexed_file(
            filepath=rel, file_hash=h, corpus=corpus,
            book_slug=_path_to_slug(rel, corpus), file_size=size,
        )


def _make_scan_job(root: Path, corpus: str, **extra) -> Job:
    payload: dict = {"root": str(root), "corpus": corpus}
    payload.update(extra)
    return Job(id=1, type="scan", priority=1, payload=payload,
               status="running", created_at="", started_at=None,
               finished_at=None, error=None, attempts=1)


def test_scan_enqueues_ingest_for_added_files(tmp_path: Path):
    """3 new .md files on disk, none indexed → 3 ingest jobs enqueued."""
    root = tmp_path / "src"
    _write_md(root / "a.md", "# A\n\nfirst.\n")
    _write_md(root / "b.md", "# B\n\nsecond.\n")
    _write_md(root / "sub" / "c.md", "# C\n\nthird.\n")
    db = tmp_path / "library.db"
    Library(str(db)).close()

    handle_scan(_make_scan_job(root, "test"), _fake_worker(db))

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        ingest_jobs = [j for j in pending if j.type == "ingest"]
        assert len(ingest_jobs) == 3, (
            f"expected 3 ingest jobs, got {len(ingest_jobs)}"
        )
        rels = sorted(j.payload["filepath"] for j in ingest_jobs)
        assert rels == ["a.md", "b.md", "sub/c.md"]
        for j in ingest_jobs:
            assert j.payload["root"] == str(root)
            assert j.payload["corpus"] == "test"
    finally:
        q.close()


def test_scan_enqueues_remove_for_disappeared_files(tmp_path: Path):
    """3 files indexed, only 2 on disk → 1 remove job (below circuit
    breaker thresholds: 1/3 = 33%, but absolute < REMOVE_CIRCUIT_MIN_FILES)."""
    root = tmp_path / "src"
    _write_md(root / "kept-a.md", "# A\n\ncontent.\n")
    _write_md(root / "kept-b.md", "# B\n\ncontent.\n")
    db = tmp_path / "library.db"
    lib = Library(str(db))
    try:
        # All three were once indexed; only two are still on disk.
        _seed_indexed(lib, corpus="test", root=root,
                      rels=["kept-a.md", "kept-b.md"])
        _seed_indexed(lib, corpus="test", root=root,
                      rels=["gone.md"], real_hashes=False)
    finally:
        lib.close()

    handle_scan(_make_scan_job(root, "test"), _fake_worker(db))

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        remove_jobs = [j for j in pending if j.type == "remove"]
        assert len(remove_jobs) == 1
        assert remove_jobs[0].payload == {"filepath": "gone.md",
                                          "corpus": "test"}
        # No spurious ingest jobs for files already indexed.
        assert not [j for j in pending if j.type == "ingest"]
    finally:
        q.close()


def test_scan_circuit_breaker_blocks_mass_removal(tmp_path: Path):
    """40 indexed files, only 5 on disk → batch hits both thresholds
    (>=25 absolute AND >=25% of corpus). Refuse to enqueue any remove."""
    root = tmp_path / "src"
    # 5 survivors
    survivor_rels = [f"survivor-{i:02d}.md" for i in range(5)]
    for rel in survivor_rels:
        _write_md(root / rel, f"# {rel}\n\ncontent here.\n")

    db = tmp_path / "library.db"
    lib = Library(str(db))
    try:
        # 5 real entries + 35 phantom-indexed = 40 tracked total
        _seed_indexed(lib, corpus="test", root=root, rels=survivor_rels)
        phantom_rels = [f"vanished-{i:02d}.md" for i in range(35)]
        _seed_indexed(lib, corpus="test", root=root,
                      rels=phantom_rels, real_hashes=False)
    finally:
        lib.close()

    worker = _fake_worker(db)
    handle_scan(_make_scan_job(root, "test"), worker)

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        remove_jobs = [j for j in pending if j.type == "remove"]
        assert remove_jobs == [], (
            f"circuit breaker should block all removes, got {len(remove_jobs)}"
        )
    finally:
        q.close()

    # And the handler logged a clear warning.
    assert any("refused to remove" in m for m in worker._logs), \
        f"missing 'refused to remove' warning in logs: {worker._logs!r}"


def test_scan_force_remove_bypasses_circuit_breaker(tmp_path: Path):
    """Same setup as the breaker test, but with ``force_remove=True``
    → all 35 remove jobs land."""
    root = tmp_path / "src"
    survivor_rels = [f"survivor-{i:02d}.md" for i in range(5)]
    for rel in survivor_rels:
        _write_md(root / rel, f"# {rel}\n\ncontent here.\n")

    db = tmp_path / "library.db"
    lib = Library(str(db))
    try:
        _seed_indexed(lib, corpus="test", root=root, rels=survivor_rels)
        phantom_rels = [f"vanished-{i:02d}.md" for i in range(35)]
        _seed_indexed(lib, corpus="test", root=root,
                      rels=phantom_rels, real_hashes=False)
    finally:
        lib.close()

    handle_scan(_make_scan_job(root, "test", force_remove=True),
                _fake_worker(db))

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        remove_jobs = [j for j in pending if j.type == "remove"]
        assert len(remove_jobs) == 35
        rels = sorted(j.payload["filepath"] for j in remove_jobs)
        assert rels == sorted(f"vanished-{i:02d}.md" for i in range(35))
        # Auto-vacuum was NOT triggered (35 < AUTO_VACUUM_AFTER_REMOVES=200).
        assert not [j for j in pending if j.type == "vacuum"]
    finally:
        q.close()


def test_scan_auto_enqueues_vacuum_after_big_remove(tmp_path: Path):
    """500 phantom-indexed files, 0 on disk, force_remove=True →
    500 remove jobs + 1 vacuum job (because 500 > AUTO_VACUUM_AFTER_REMOVES)."""
    root = tmp_path / "src"
    root.mkdir(parents=True)  # empty source tree

    db = tmp_path / "library.db"
    lib = Library(str(db))
    try:
        phantom_rels = [f"ghost-{i:04d}.md" for i in range(500)]
        _seed_indexed(lib, corpus="test", root=root,
                      rels=phantom_rels, real_hashes=False)
    finally:
        lib.close()

    handle_scan(_make_scan_job(root, "test", force_remove=True),
                _fake_worker(db))

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        remove_jobs = [j for j in pending if j.type == "remove"]
        vacuum_jobs = [j for j in pending if j.type == "vacuum"]
        assert len(remove_jobs) == 500
        assert len(vacuum_jobs) == 1
        assert (vacuum_jobs[0].payload or {}).get("reason") \
            == "auto-after-big-scan-remove"
        # Sanity: AUTO_VACUUM_AFTER_REMOVES is the documented threshold.
        assert 500 > AUTO_VACUUM_AFTER_REMOVES
    finally:
        q.close()


def test_scan_skips_silently_when_root_not_a_directory(tmp_path: Path):
    """Bad payload (path doesn't exist) → log + return, never raises."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    missing = tmp_path / "does-not-exist"
    worker = _fake_worker(db)
    handle_scan(_make_scan_job(missing, "test"), worker)

    q = Queue(db)
    try:
        assert q.list_pending() == []
    finally:
        q.close()
    assert any("not a directory" in m for m in worker._logs)
