"""A binary nothing can read is neither indexed nor tracked.

Tracked, it cost a job every time it changed — a small database inside one
project was read 240 times a day for nothing — and it sat in the audit as a
file with nothing behind it, burying the genuine losses that check exists to
find (one project reported 670 of them). It is now left out at the scan, and
the ones recorded before are taken out on the next start.

Formats that are binary but readable — PDF, spreadsheets, ebooks, SQLite —
have a parser and are not concerned.
"""
from __future__ import annotations

import sqlite3

import pytest

from rtfm.core.audit import check_mute_files
from rtfm.core.repair import forget_tracked_binaries
from rtfm.core.sniff import unreadable_binary


def _job(root, rel, kind="ingest"):
    from rtfm.core.queue import Job
    payload = {"root": str(root), "corpus": "default"}
    if kind == "ingest":
        payload["filepath"] = rel
    return Job(id=1, type=kind, priority=10, payload=payload,
               status="running", created_at="", started_at=None,
               finished_at=None, error=None, attempts=1)


class _Worker:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lines: list[str] = []

    def _log(self, msg):
        self.lines.append(msg)


@pytest.fixture
def project(tmp_path):
    from rtfm.core.library import Library
    root = tmp_path / "projet"
    (root / ".rtfm").mkdir(parents=True)
    Library(str(root / ".rtfm" / "library.db")).close()
    (root / "moteur.blob").write_bytes(b"\x7fELF\x00\x00\x01" * 400)
    (root / "notes.md").write_text("# Notes\n\nDu texte lisible.\n" * 10,
                                   encoding="utf-8")
    return root


def _tracked(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT filepath FROM indexed_files")}
    finally:
        conn.close()


def _queued(db, kind):
    from rtfm.core.queue import Queue
    q = Queue(str(db))
    try:
        return [j.payload.get("filepath") for j in q.list_pending(limit=1000)
                if j.type == kind]
    finally:
        q.close()


def test_what_counts_as_unreadable(project, tmp_path):
    assert unreadable_binary(project / "moteur.blob")
    assert not unreadable_binary(project / "notes.md")
    fake_pdf = tmp_path / "scan.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\x00\x00binary body")
    assert not unreadable_binary(fake_pdf), "a PDF has its reader"


class TestTheScan:

    def test_a_new_binary_is_not_offered(self, project):
        from rtfm.core.handlers import handle_scan
        db = project / ".rtfm" / "library.db"
        handle_scan(_job(project, None, "scan"), _Worker(db))
        assert _queued(db, "ingest") == ["notes.md"]

    def test_a_tracked_binary_that_changes_leaves(self, project):
        from rtfm.core.handlers import handle_scan
        from rtfm.core.library import Library
        db = project / ".rtfm" / "library.db"
        lib = Library(str(db))
        lib.update_indexed_file("moteur.blob", "ancien", "default", None,
                                file_size=1, root_path=str(project))
        lib.close()
        handle_scan(_job(project, None, "scan"), _Worker(db))
        assert _queued(db, "remove") == ["moteur.blob"]
        assert "moteur.blob" not in _queued(db, "ingest")


class TestTheIngest:

    def test_a_binary_reaching_the_ingest_is_not_tracked(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        handle_ingest(_job(project, "moteur.blob"), _Worker(db))
        assert _tracked(db) == set()

    def test_a_binary_is_not_reported_as_damaged_text(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        worker = _Worker(db)
        handle_ingest(_job(project, "moteur.blob"), worker)
        assert not any("not valid text" in ln for ln in worker.lines)

    def test_the_direct_sync_leaves_it_out_the_same_way(self, project):
        from rtfm.core.library import Library
        from rtfm.core.sync import sync
        db = project / ".rtfm" / "library.db"
        lib = Library(str(db))
        try:
            result = sync(library=lib, root=project, corpus="default",
                          generate_embeddings=False)
        finally:
            lib.close()
        assert _tracked(db) == {"notes.md"}
        assert "moteur.blob" not in result.empty_files

    def test_a_text_file_is_tracked_as_before(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        handle_ingest(_job(project, "notes.md"), _Worker(db))
        assert _tracked(db) == {"notes.md"}


class TestWhatTheChecksSee:

    def test_the_audit_does_not_count_it(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        handle_ingest(_job(project, "moteur.blob"), _Worker(db))
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            assert check_mute_files(conn) is None
        finally:
            conn.close()

    def test_coverage_does_not_count_it_as_a_gap(self, project):
        from rtfm.core.coverage import measure
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        for rel in ("moteur.blob", "notes.md"):
            handle_ingest(_job(project, rel), _Worker(db))
        cov = measure(project)
        assert cov.readable == cov.indexable == 1
        assert cov.sources[0].skipped == 1


class TestRowsWrittenBefore:

    @pytest.fixture
    def legacy(self, project):
        """Tracked both ways binaries were recorded before: with an identity
        and no document, and without one."""
        from rtfm.core.library import Library
        db = project / ".rtfm" / "library.db"
        (project / "autre.bin").write_bytes(b"\x00\x01\x02" * 100)
        lib = Library(str(db))
        lib.set_sync_root("default", str(project))
        for rel, slug in (("moteur.blob", "moteur-blob"), ("autre.bin", None),
                          ("notes.md", "notes-md")):
            lib.update_indexed_file(rel, "h", "default", slug,
                                    file_size=(project / rel).stat().st_size,
                                    root_path=str(project))
        lib.close()
        return db

    def test_present_binaries_leave(self, project, legacy):
        assert forget_tracked_binaries(legacy) == 2
        assert _tracked(legacy) == {"notes.md"}

    def test_a_mute_text_file_stays_visible(self, project, legacy):
        """That one is a genuine loss — the reason the check exists."""
        forget_tracked_binaries(legacy)
        assert "notes.md" in _tracked(legacy)

    def test_a_missing_file_is_left_alone(self, project, legacy):
        (project / "moteur.blob").unlink()
        assert forget_tracked_binaries(legacy) == 1
        assert "moteur.blob" in _tracked(legacy)

    def test_a_second_pass_finds_nothing(self, project, legacy):
        forget_tracked_binaries(legacy)
        assert forget_tracked_binaries(legacy) == 0

    def test_a_row_without_its_directory_uses_the_corpus_one(self, project):
        from rtfm.core.library import Library
        db = project / ".rtfm" / "library.db"
        lib = Library(str(db))
        lib.set_sync_root("default", str(project))
        lib.update_indexed_file("moteur.blob", "h", "default", "moteur-blob",
                                file_size=(project / "moteur.blob").stat().st_size)
        lib.close()
        assert forget_tracked_binaries(db) == 1
