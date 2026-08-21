"""Tests for rtfm.core.freshness — read-time index/disk agreement."""

import os
import time
from datetime import datetime, timedelta

import pytest

from rtfm.core import freshness
from rtfm.core.freshness import GONE, NEW, STALE, check_file, probably_unchanged


def _tracked(path, indexed_at=None, file_hash=None):
    """A tracking row as ``indexed_files`` would hold it for *path*."""
    from rtfm.core.sync import compute_file_hash
    st = os.stat(path)
    return {
        "file_size": st.st_size,
        "file_hash": file_hash if file_hash is not None else compute_file_hash(path),
        "corpus": "default",
        "indexed_at": (indexed_at or datetime.now()).isoformat(),
    }


@pytest.fixture
def indexed_file(tmp_path):
    """A file written a while ago and indexed since — the ordinary state of
    a corpus, where ``mtime`` sits clearly before ``indexed_at``."""
    f = tmp_path / "notes.md"
    f.write_text("original content\n")
    written_at = time.time() - 10
    os.utime(f, (written_at, written_at))
    return f, _tracked(f, indexed_at=datetime.now())


class TestCheckFile:
    def test_untouched_file_is_fresh(self, indexed_file):
        path, tracked = indexed_file
        assert check_file(str(path), tracked) is None

    def test_modified_content_same_length_is_stale(self, indexed_file):
        """The case a size check alone misses — and the most common one:
        an agent rewriting a line in place."""
        path, tracked = indexed_file
        time.sleep(0.01)
        path.write_text("modified content\n")
        assert len("modified content\n") == len("original content\n")
        assert check_file(str(path), tracked) == STALE

    def test_grown_file_is_stale(self, indexed_file):
        path, tracked = indexed_file
        path.write_text("original content\nplus a new line\n")
        assert check_file(str(path), tracked) == STALE

    def test_touched_but_identical_is_fresh(self, indexed_file):
        """A newer mtime alone is not a change — the hash settles it, so a
        `touch` or a rewrite of identical bytes raises no false alarm."""
        path, tracked = indexed_file
        os.utime(path, (time.time() + 10, time.time() + 10))
        assert check_file(str(path), tracked) is None

    def test_deleted_file(self, indexed_file):
        path, tracked = indexed_file
        path.unlink()
        assert check_file(str(path), tracked) == GONE

    def test_never_indexed_file(self, tmp_path):
        f = tmp_path / "brand-new.md"
        f.write_text("x")
        assert check_file(str(f), None) == NEW

    def test_unknown_and_absent_is_not_reported(self, tmp_path):
        assert check_file(str(tmp_path / "nope.md"), None) is None


class TestProbablyUnchanged:
    def test_untouched(self, indexed_file):
        path, tracked = indexed_file
        assert probably_unchanged(os.stat(path), tracked) is True

    def test_same_size_newer_mtime_is_not_trusted(self, indexed_file):
        """Must fall through to hashing — this is exactly the in-place edit
        that a lax mtime window would hide."""
        path, tracked = indexed_file
        path.write_text("modified content\n")
        assert probably_unchanged(os.stat(path), tracked) is False

    def test_no_tracking_row(self, indexed_file):
        path, _ = indexed_file
        assert probably_unchanged(os.stat(path), None) is False

    def test_legacy_row_without_size_is_not_trusted(self, indexed_file):
        path, tracked = indexed_file
        tracked["file_size"] = 0
        assert probably_unchanged(os.stat(path), tracked) is False

    def test_unparseable_timestamp_is_not_trusted(self, indexed_file):
        path, tracked = indexed_file
        tracked["indexed_at"] = "not a date"
        assert probably_unchanged(os.stat(path), tracked) is False


class TestVerify:
    def test_reports_only_drifting_files(self, tmp_path):
        from rtfm.core.library import Library
        from rtfm.core.sync import sync

        (tmp_path / "src").mkdir()
        stable = tmp_path / "src" / "stable.md"
        drifting = tmp_path / "src" / "drifting.md"
        stable.write_text("unchanged\n")
        drifting.write_text("before\n")

        lib = Library(tmp_path / "lib.db")
        sync(lib, tmp_path / "src", corpus="default", generate_embeddings=False)

        time.sleep(0.01)
        drifting.write_text("after!\n")  # same length on purpose

        verdicts = freshness.verify(lib, [
            (str(stable), "stable.md"),
            (str(drifting), "drifting.md"),
        ])
        assert str(stable) not in verdicts
        assert verdicts[str(drifting)]["verdict"] == STALE
        assert verdicts[str(drifting)]["corpus"] == "default"
        lib.close()


class TestRequeue:
    def test_queues_reingest_at_user_priority(self, tmp_path):
        from rtfm.core.library import Library
        from rtfm.core.queue import P_USER, Queue

        db = tmp_path / "lib.db"
        Library(db).close()
        n = freshness.requeue(str(db), [("/root", "default", "a.md")])
        assert n == 1

        q = Queue(str(db))
        job = q.dequeue()
        q.close()
        assert job.type == "ingest"
        assert job.priority == P_USER

    def test_empty_input_is_a_noop(self, tmp_path):
        assert freshness.requeue(str(tmp_path / "nothing.db"), []) == 0
