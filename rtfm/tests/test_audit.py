"""RTFM checks itself against the invariants a healthy index holds.

Every serious defect this index has had passed the whole test suite and was
plain in the data: a README re-ingested 82 000 times, 1 750 files that never
entered any index, a corpus of PDFs searchable but unreadable. Each was found
weeks late, by someone noticing a symptom and then querying live databases by
hand.

So each check here is written against the shape of the failure it would have
caught, and every test builds that failure and asserts the check fires.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rtfm.core.audit import (
    CHURN_THRESHOLD,
    audit_fleet,
    audit_project,
    check_churn,
    check_orphan_books,
    check_pagination,
    check_silent_drops,
    check_stranded,
    check_unreadable,
)
from rtfm.core.library import Library
from rtfm.core.queue import Queue


@pytest.fixture
def index(tmp_path):
    """A minimal but real project: .rtfm/library.db under a project root."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    db = rtfm_dir / "library.db"
    Library(str(db)).close()
    return db


def _ro(db: Path):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    return conn


class TestChurn:
    """The loop that ran for three weeks: two scans handing a file back and
    forth, each undoing the other, the queue never emptying and nothing in
    the ordinary output saying so."""

    def test_a_file_indexed_over_and_over_is_reported(self, index):
        q = Queue(str(index))
        for _ in range(CHURN_THRESHOLD + 3):
            conn = q._get_conn()
            conn.execute(
                "INSERT INTO work_queue (type, priority, payload, status, "
                "created_at) VALUES ('ingest', 10, ?, 'done', datetime('now'))",
                (json.dumps({"corpus": "c", "filepath": "README.md"}),))
            conn.commit()
        q.close()

        conn = _ro(index)
        try:
            result = check_churn(conn)
        finally:
            conn.close()
        assert result is not None
        count, detail = result
        assert count == 1
        assert "README.md" in detail

    def test_ordinary_re_indexing_is_not_reported(self, index):
        """A file edited a few times a day is normal and must stay quiet."""
        q = Queue(str(index))
        conn = q._get_conn()
        for _ in range(3):
            conn.execute(
                "INSERT INTO work_queue (type, priority, payload, status, "
                "created_at) VALUES ('ingest', 10, ?, 'done', datetime('now'))",
                (json.dumps({"corpus": "c", "filepath": "notes.md"}),))
        conn.commit()
        q.close()

        conn = _ro(index)
        try:
            assert check_churn(conn) is None
        finally:
            conn.close()

    def test_old_churn_falls_out_of_the_window(self, index):
        """The check reports what is happening, not what happened."""
        q = Queue(str(index))
        conn = q._get_conn()
        for _ in range(CHURN_THRESHOLD + 3):
            conn.execute(
                "INSERT INTO work_queue (type, priority, payload, status, "
                "created_at) VALUES ('ingest', 10, ?, 'done', "
                "datetime('now', '-8 days'))",
                (json.dumps({"corpus": "c", "filepath": "README.md"}),))
        conn.commit()
        q.close()

        conn = _ro(index)
        try:
            assert check_churn(conn) is None
        finally:
            conn.close()


class TestSilentDrops:
    """A file RTFM refuses to index is remembered so scans stop offering it —
    which also means nobody is ever told."""

    def test_held_out_files_are_reported(self, index):
        lib = Library(str(index))
        lib.record_ingest_failure("broken.pdf", "c", "h", 10, "boom")
        lib.close()

        conn = _ro(index)
        try:
            result = check_silent_drops(conn)
        finally:
            conn.close()
        assert result is not None and result[0] == 1
        assert "broken.pdf" in result[1]

    def test_a_clean_index_is_quiet(self, index):
        conn = _ro(index)
        try:
            assert check_silent_drops(conn) is None
        finally:
            conn.close()


class TestUnreadable:
    """Found by search, then impossible to display — the PDF corpus."""

    def test_a_passage_with_nothing_to_show_is_reported(self, index):
        conn = sqlite3.connect(str(index))
        conn.execute(
            "INSERT INTO books (slug, title, filename, corpus) "
            "VALUES ('b', 'B', 'doc.pdf', 'c')")
        conn.execute(
            "INSERT INTO chunks (chunk_id, book_id, content, line_start) "
            "VALUES ('b-1', 1, '', NULL)")
        conn.commit()
        conn.close()

        conn = _ro(index)
        try:
            result = check_unreadable(conn)
        finally:
            conn.close()
        assert result is not None and result[0] == 1


class TestPagination:
    def test_a_multi_passage_document_cannot_be_one_page(self, index):
        conn = sqlite3.connect(str(index))
        conn.execute(
            "INSERT INTO books (slug, title, filename, corpus, page_count, "
            "chunk_count) VALUES ('b', 'B', 'paper.pdf', 'c', 1, 45)")
        conn.commit()
        conn.close()

        conn = _ro(index)
        try:
            result = check_pagination(conn)
        finally:
            conn.close()
        assert result is not None and result[0] == 1

    def test_a_genuinely_short_document_is_fine(self, index):
        conn = sqlite3.connect(str(index))
        conn.execute(
            "INSERT INTO books (slug, title, filename, corpus, page_count, "
            "chunk_count) VALUES ('b', 'B', 'note.pdf', 'c', 1, 1)")
        conn.commit()
        conn.close()

        conn = _ro(index)
        try:
            assert check_pagination(conn) is None
        finally:
            conn.close()


class TestStranded:
    def test_a_claim_nobody_will_close_is_reported(self, index):
        q = Queue(str(index))
        conn = q._get_conn()
        conn.execute(
            "INSERT INTO work_queue (type, priority, payload, status, "
            "created_at, started_at) VALUES ('ingest', 10, '{}', 'running', "
            "datetime('now', '-2 days'), datetime('now', '-2 days'))")
        conn.commit()
        q.close()

        conn = _ro(index)
        try:
            result = check_stranded(conn)
        finally:
            conn.close()
        assert result is not None and result[0] == 1

    def test_a_job_that_started_a_minute_ago_is_just_working(self, index):
        q = Queue(str(index))
        conn = q._get_conn()
        conn.execute(
            "INSERT INTO work_queue (type, priority, payload, status, "
            "created_at, started_at) VALUES ('ingest', 10, '{}', 'running', "
            "datetime('now'), datetime('now'))")
        conn.commit()
        q.close()

        conn = _ro(index)
        try:
            assert check_stranded(conn) is None
        finally:
            conn.close()


class TestOrphanBooks:
    """A book no scan tracks is never refreshed and never removed. It keeps
    answering searches with content that may have left the disk long ago."""

    def test_an_untracked_book_is_reported(self, index):
        conn = sqlite3.connect(str(index))
        conn.execute(
            "INSERT INTO books (slug, title, filename, corpus) "
            "VALUES ('ghost', 'Ghost', 'gone.md', 'c')")
        conn.commit()
        conn.close()

        conn = _ro(index)
        try:
            result = check_orphan_books(conn)
        finally:
            conn.close()
        assert result is not None and result[0] == 1

    def test_a_tracked_book_is_fine(self, index):
        lib = Library(str(index))
        conn = lib._get_conn()
        conn.execute(
            "INSERT INTO books (slug, title, filename, corpus) "
            "VALUES ('b', 'B', 'doc.md', 'c')")
        conn.commit()
        lib.update_indexed_file(filepath="doc.md", file_hash="h",
                                corpus="c", book_slug="b")
        lib.close()

        conn = _ro(index)
        try:
            assert check_orphan_books(conn) is None
        finally:
            conn.close()


class TestTheWholeFleet:
    def test_a_clean_index_reports_nothing(self, index):
        assert audit_project(index, index.parent.parent) == []

    def test_findings_name_their_project(self, index):
        lib = Library(str(index))
        lib.record_ingest_failure("broken.pdf", "c", "h", 10, "boom")
        lib.close()

        findings = audit_project(index, index.parent.parent)
        assert findings
        assert findings[0].project == index.parent.parent.name

    def test_an_unopenable_index_is_a_finding_not_a_crash(self, tmp_path):
        """The audit must survive anything it meets: it runs unattended."""
        broken = tmp_path / "library.db"
        broken.write_text("this is not a database")
        findings = audit_project(broken, tmp_path)
        assert isinstance(findings, list)

    def test_the_fleet_walk_skips_what_does_not_exist(self, tmp_path):
        report = audit_fleet(registry=[str(tmp_path / "nowhere" / ".rtfm")])
        assert report.projects == 0
        assert report.clean
