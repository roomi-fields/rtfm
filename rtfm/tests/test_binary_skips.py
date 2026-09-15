"""A binary the ingest refuses is not a file that went silent.

The audit's most valuable check looks for files the scan has seen and
recorded, with nothing readable behind them — the shape of every serious
loss this index has had. Binaries broke it: the ingest refuses them, on
purpose, but recorded them exactly like a text file that produced nothing.
One project reported 670 "silent" files that were compiled libraries, CAD
drawings and scans awaiting OCR, and the genuine losses were buried among
them.

A refused binary is now recorded with no identity, and the rows written
before that are re-marked on the spot.
"""
from __future__ import annotations

import sqlite3

import pytest

from rtfm.core.audit import check_mute_files
from rtfm.core.repair import remark_skipped_binaries


def _job(root, rel):
    from rtfm.core.queue import Job
    return Job(id=1, type="ingest", priority=10,
               payload={"root": str(root), "corpus": "default", "filepath": rel},
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
    root = tmp_path / "projet"
    (root / ".rtfm").mkdir(parents=True)
    (root / "moteur.blob").write_bytes(b"\x7fELF\x00\x00\x01" * 400)
    (root / "notes.md").write_text("# Notes\n\nDu texte lisible.\n" * 10,
                                   encoding="utf-8")
    return root


def _slug(db, rel):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT book_slug FROM indexed_files WHERE filepath = ?",
                           (rel,)).fetchone()
        return row
    finally:
        conn.close()


class TestRecordingIt:

    def test_the_worker_records_a_refused_binary_without_identity(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        handle_ingest(_job(project, "moteur.blob"), _Worker(db))
        row = _slug(db, "moteur.blob")
        assert row is not None, "it must still be tracked, or every scan re-offers it"
        assert row[0] is None

    def test_a_binary_is_not_reported_as_damaged_text(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        worker = _Worker(db)
        handle_ingest(_job(project, "moteur.blob"), worker)
        assert not any("not valid text" in ln for ln in worker.lines)

    def test_the_direct_sync_records_it_the_same_way(self, project):
        from rtfm.core.library import Library
        from rtfm.core.sync import sync
        db = project / ".rtfm" / "library.db"
        lib = Library(str(db))
        try:
            result = sync(library=lib, root=project, corpus="default",
                          generate_embeddings=False)
        finally:
            lib.close()
        assert _slug(db, "moteur.blob")[0] is None
        assert "moteur.blob" not in result.empty_files, (
            "a refused binary is not an empty file to warn about")

    def test_a_text_file_keeps_its_identity(self, project):
        from rtfm.core.handlers import handle_ingest
        db = project / ".rtfm" / "library.db"
        handle_ingest(_job(project, "notes.md"), _Worker(db))
        assert _slug(db, "notes.md")[0]


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


class TestRowsWrittenTheOldWay:

    @pytest.fixture
    def legacy(self, project):
        """Both files tracked with an identity and no document — how every
        refused binary was recorded until now."""
        from rtfm.core.library import Library
        db = project / ".rtfm" / "library.db"
        lib = Library(str(db))
        lib.set_sync_root("default", str(project))
        for rel in ("moteur.blob", "notes.md"):
            lib.update_indexed_file(rel, "h", "default", rel.replace(".", "-"),
                                    file_size=(project / rel).stat().st_size,
                                    root_path=str(project))
        lib.close()
        return db

    def test_a_present_binary_is_re_marked(self, project, legacy):
        assert remark_skipped_binaries(legacy) == 1
        assert _slug(legacy, "moteur.blob")[0] is None

    def test_a_mute_text_file_stays_visible(self, project, legacy):
        """That one is a genuine loss — the reason the check exists."""
        remark_skipped_binaries(legacy)
        assert _slug(legacy, "notes.md")[0] == "notes-md"

    def test_a_missing_file_is_left_alone(self, project, legacy):
        (project / "moteur.blob").unlink()
        assert remark_skipped_binaries(legacy) == 0
        assert _slug(legacy, "moteur.blob")[0] == "moteur-blob"

    def test_a_second_pass_finds_nothing(self, project, legacy):
        remark_skipped_binaries(legacy)
        assert remark_skipped_binaries(legacy) == 0

    def test_a_row_without_its_directory_uses_the_corpus_one(self, project):
        from rtfm.core.library import Library
        db = project / ".rtfm" / "library.db"
        lib = Library(str(db))
        lib.set_sync_root("default", str(project))
        lib.update_indexed_file("moteur.blob", "h", "default", "moteur-blob",
                                file_size=(project / "moteur.blob").stat().st_size)
        lib.close()
        assert remark_skipped_binaries(db) == 1
