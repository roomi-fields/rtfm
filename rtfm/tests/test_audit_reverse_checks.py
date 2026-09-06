"""The two directions the audit was not looking in.

Every check it had asked the same question: is there an entry in the
catalogue that nothing accounts for? That direction finds a catalogue with
too much in it. It cannot find the opposite, and the opposite is what the
two worst defects this index has had both looked like — a file the scan has
seen, recorded, and marked up to date, with nothing readable behind it.

The failure mode is what makes it worth a check of its own: nothing errors,
the counts stay plausible, and the tracking says the work is done, so
nothing will ever retry. A search returns no result and the agent concludes
the subject does not exist.
"""
from __future__ import annotations

import sqlite3

import pytest

from rtfm.core.audit import (
    audit_project, check_mute_files, check_shared_identities,
)


def _index(tmp_path, files, books):
    """A minimal index: *files* is (path, slug, size), *books* is slugs."""
    db = tmp_path / ".rtfm" / "library.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE indexed_files (
        filepath TEXT, book_slug TEXT, corpus TEXT, file_size INTEGER)""")
    conn.execute("""CREATE TABLE books (
        slug TEXT, corpus TEXT, filename TEXT)""")
    conn.executemany(
        "INSERT INTO indexed_files VALUES (?,?,'default',?)", files)
    conn.executemany("INSERT INTO books VALUES (?,'default',?)",
                     [(s, s) for s in books])
    conn.commit()
    return db, conn


class TestAFileWithNothingBehindIt:

    def test_it_is_reported(self, tmp_path):
        _, conn = _index(tmp_path,
                         [("guide.md", "guide", 900)], books=[])
        result = check_mute_files(conn)
        assert result and result[0] == 1

    def test_a_healthy_index_says_nothing(self, tmp_path):
        _, conn = _index(tmp_path,
                         [("guide.md", "guide", 900)], books=["guide"])
        assert check_mute_files(conn) is None

    @pytest.mark.parametrize("path", [
        "assets/logo.png", "fonts/Inter.woff2", "samples/loop.mid",
        "vendor/lib.so", "package-lock.lock",
    ])
    def test_a_file_that_carries_no_text_is_not_a_defect(self, tmp_path, path):
        """A scan must track these to tell them from deleted files, but
        nothing readable can come out of them."""
        _, conn = _index(tmp_path, [(path, "x", 4096)], books=[])
        assert check_mute_files(conn) is None

    def test_an_empty_file_is_not_a_defect(self, tmp_path):
        _, conn = _index(tmp_path, [("notes.md", "notes", 0)], books=[])
        assert check_mute_files(conn) is None

    def test_the_html_case_in_the_shape_it_had(self, tmp_path):
        """5 738 tracked, none readable, and every count plausible."""
        files = [(f"pages/p{i}.html", f"pages-p{i}", 5000) for i in range(5738)]
        _, conn = _index(tmp_path, files, books=[])
        result = check_mute_files(conn)
        assert result and result[0] == 5738


class TestTwoFilesUnderOneIdentity:

    def test_the_hidden_ones_are_counted(self, tmp_path):
        files = [("d/-se.Alan", "d--se", 100),
                 ("d/-se.Alarm", "d--se", 100),
                 ("d/-se.Ames", "d--se", 100)]
        _, conn = _index(tmp_path, files, books=["d--se"])
        result = check_shared_identities(conn)
        assert result and result[0] == 2, "only the last file is readable"
        assert "3 files answering to one" in result[1]

    def test_distinct_identities_say_nothing(self, tmp_path):
        files = [("d/-se.Alan", "d--se-alan", 100),
                 ("d/-se.Alarm", "d--se-alarm", 100)]
        _, conn = _index(tmp_path, files, books=["d--se-alan", "d--se-alarm"])
        assert check_shared_identities(conn) is None

    def test_the_same_name_in_two_corpora_is_not_a_collision(self, tmp_path):
        db, conn = _index(tmp_path, [("guide.md", "guide", 100)], ["guide"])
        conn.execute("INSERT INTO indexed_files VALUES ('guide.md','guide','autre',100)")
        conn.commit()
        assert check_shared_identities(conn) is None

    def test_an_untracked_identity_is_not_a_collision(self, tmp_path):
        _, conn = _index(tmp_path,
                         [("a.md", None, 100), ("b.md", None, 100)], books=[])
        assert check_shared_identities(conn) is None


class TestBothRunUnderTheAudit:

    def test_they_are_part_of_a_project_audit(self, tmp_path):
        db, _ = _index(tmp_path,
                       [("a/-se.Alan", "se", 100), ("a/-se.Ames", "se", 100),
                        ("guide.md", "guide", 900)],
                       books=["se"])
        checks = {f.check for f in audit_project(db, tmp_path)}
        assert "shared-identities" in checks
        assert "mute-files" in checks

    def test_an_index_with_no_tracking_is_not_an_error(self, tmp_path):
        """A database with no tracking table at all — the shape a project
        has for the seconds between ``rtfm init`` and its first scan."""
        db = tmp_path / ".rtfm" / "library.db"
        db.parent.mkdir(parents=True)
        sqlite3.connect(db).execute("CREATE TABLE t (x)")
        mine = {"shared-identities", "mute-files"}
        assert not [f for f in audit_project(db, tmp_path)
                    if f.check in mine]
