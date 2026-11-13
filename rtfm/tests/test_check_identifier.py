"""`rtfm check` finding a book by a path copied from disk.

Filenames are stored relative to their corpus root, so a path a user copies
from the tree ("corpus/ifs/Livres VO/foo.pdf") carries a prefix the stored
name lacks. The positional match used to require the whole string to appear
in the stored filename, so it found nothing and the caller had to hunt for
the bare filename. The last path segment is now matched on its own.
"""
from __future__ import annotations

import sqlite3
from argparse import Namespace

import pytest

from rtfm.core.library import Library


@pytest.fixture
def db_with_book(tmp_path):
    db = tmp_path / "library.db"
    Library(str(db))
    from rtfm.core.queue import Queue
    Queue(db).close()  # the work_queue table cmd_check reads pipeline state from
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO books (slug, title, filename, corpus) VALUES (?,?,?,?)",
        ("mosaic-mind", "The Mosaic Mind",
         "Livres VO/Regina A. Goulding - The Mosaic Mind.pdf", "ifs"))
    conn.commit()
    conn.close()
    return db


def _check(db, identifier):
    from rtfm.cli import cmd_check
    args = Namespace(db=str(db), slug=None, path=None,
                     identifier=identifier, corpus=None, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    return exc.value.code


def test_a_corpus_relative_path_finds_the_book(db_with_book):
    # The exact string a user copies from the tree, prefix and all.
    code = _check(db_with_book,
                  "corpus/ifs/Livres VO/Regina A. Goulding - The Mosaic Mind.pdf")
    # Found (code 1 = incomplete, no chunks) rather than 2 = no match.
    assert code != 2


def test_the_bare_filename_still_finds_it(db_with_book):
    assert _check(db_with_book, "The Mosaic Mind.pdf") != 2


def test_an_unrelated_path_does_not_match(db_with_book):
    assert _check(db_with_book, "corpus/other/nothing-like-it.pdf") == 2
