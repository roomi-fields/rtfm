"""The disk and the index change under a running job.

A scan lists a directory, then reads each file: between the two, an editor's
atomic save or a build step can take a file away, and the whole scan died on
it. An embedding job reads its passages, spends seconds in the model, then
writes: in those seconds a re-index of the same file replaced every passage,
and the write hit a foreign key and failed the job. Twenty-eight such
failures in one night, all of them non-events.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from rtfm.core.library import Library
from rtfm.core.sync import compute_diff, sync


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestAFileVanishingMidScan:
    def test_a_newcomer_that_is_gone_is_simply_not_there(self, tmp_path):
        ghost = tmp_path / "ghost.png"
        diff = compute_diff([ghost], {}, tmp_path)
        assert diff.added == []

    def test_a_tracked_file_that_is_gone_is_proposed_for_removal(
            self, tmp_path):
        """It is absent — the removal path will check the disk once more
        before believing that, which is where a blink is told from a
        deletion."""
        gone = tmp_path / "gone.md"
        diff = compute_diff(
            [gone], {"gone.md": {"file_hash": "h", "file_size": 1}}, tmp_path)
        assert diff.removed == ["gone.md"]

    def test_the_other_files_of_the_scan_are_still_processed(self, tmp_path):
        kept = _write(tmp_path / "kept.md", "still here")
        diff = compute_diff([tmp_path / "ghost.md", kept], {}, tmp_path)
        assert diff.added == [kept]


class TestPassagesReplacedWhileTheModelRuns:
    def test_the_job_succeeds_and_writes_nothing_for_them(
            self, tmp_path, monkeypatch):
        _write(tmp_path / "src" / "note.md", "A passage. " * 40)
        lib = Library(str(tmp_path / "library.db"))
        try:
            sync(library=lib, root=tmp_path / "src", corpus="c",
                 extensions={".md"}, generate_embeddings=False)
            slug = lib.list_indexed_files(corpus="c")["note.md"]["book_slug"]
            ids = lib.chunk_ids_for_book(slug)
            assert ids

            def model_that_takes_a_while(texts, *a, **k):
                # Meanwhile, the file is re-indexed: every passage replaced.
                lib._get_conn().execute("DELETE FROM chunks WHERE book_id IN "
                                        "(SELECT id FROM books WHERE slug = ?)",
                                        (slug,))
                return [np.zeros(3) for _ in texts]

            import rtfm.core.embeddings as emb
            monkeypatch.setattr(emb, "embed_texts", model_that_takes_a_while)

            result = lib.embed_chunks_by_id(ids)
            assert result["embedded"] == 0
            assert result["skipped"] == len(ids)
            assert lib._get_conn().execute(
                "SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0] == 0
        finally:
            lib.close()

    def test_passages_still_there_are_embedded_as_before(
            self, tmp_path, monkeypatch):
        _write(tmp_path / "src" / "note.md", "A passage. " * 40)
        lib = Library(str(tmp_path / "library.db"))
        try:
            sync(library=lib, root=tmp_path / "src", corpus="c",
                 extensions={".md"}, generate_embeddings=False)
            slug = lib.list_indexed_files(corpus="c")["note.md"]["book_slug"]
            ids = lib.chunk_ids_for_book(slug)

            import rtfm.core.embeddings as emb
            monkeypatch.setattr(emb, "embed_texts",
                                lambda texts, *a, **k: [np.zeros(3) for _ in texts])

            result = lib.embed_chunks_by_id(ids)
            assert result["embedded"] == len(ids)
            assert result["skipped"] == 0
        finally:
            lib.close()
