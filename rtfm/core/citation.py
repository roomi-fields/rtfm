"""What an indexed file needs before it can be quoted.

A search result says where a passage is. Quoting it needs more: who wrote it,
under what title, and — for a scanned book — between which pages the author's
own text runs, so a preface by someone else is never attributed to them. None
of that can be read from the file reliably, so someone records it once.

That record used to live beside each site, in a different shape per site: two
lists in one format for one, a third in another format for the next, and an
engine that had to read both. Two lists describing the same corpus drift, and
the one that drifts is the one nobody is looking at. So it lives here, next to
the index it describes.

Not on the document's own row: that row is deleted and rewritten every time
the file is re-indexed, which would erase the description on each pass. A
table of its own, keyed by corpus and path, survives re-indexing — and
outlives a file that is momentarily missing.

**No permission flag, and nothing to remember to set.** The only thing that
keeps a source out of a quotation is not knowing who wrote it: a card naming
an author and a title is attributed and may be quoted, one without is
background reading. That follows from what is recorded rather than from a
state kept beside it, so it is computed on the way out and cannot drift.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

#: What kind of document this is. Open list, closed on purpose: an unknown
#: value is almost always a typo, and a typo here silently changes how a
#: citation is rendered.
NATURES = ("livre", "livret", "article", "fiche", "recueil", "support",
           "document")

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_cards (
    corpus            TEXT NOT NULL,
    filepath          TEXT NOT NULL,
    author            TEXT,
    title             TEXT,
    nature            TEXT,
    language          TEXT,
    year              TEXT,
    edition           TEXT,
    translator        TEXT,
    range_start       INTEGER,
    range_end         INTEGER,
    note              TEXT,
    extra             TEXT,
    updated_at        TEXT,
    PRIMARY KEY (corpus, filepath)
);
"""

class InvalidCard(ValueError):
    """A card that would be wrong in a way a reader could not detect."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _row_to_card(row: sqlite3.Row) -> dict:
    extra = {}
    if row["extra"]:
        try:
            extra = json.loads(row["extra"])
        except ValueError:
            extra = {}
    rng = None
    if row["range_start"] is not None and row["range_end"] is not None:
        rng = [row["range_start"], row["range_end"]]
    return {
        "file": row["filepath"],
        "corpus": row["corpus"],
        "author": row["author"],
        "title": row["title"],
        "nature": row["nature"],
        "language": row["language"],
        "year": row["year"],
        "edition": row["edition"],
        "translator": row["translator"],
        "range": rng,
        "note": row["note"],
        # Derived, never stored: named author + title = quotable.
        "attributed": bool(row["author"] and row["title"]),
        "extra": extra,
        "updated_at": row["updated_at"],
    }


def validate(card: dict) -> None:
    """Refuse what a reader could not detect as wrong. Raises `InvalidCard`."""
    if not card.get("file"):
        raise InvalidCard("a card needs the file it describes")
    nature = card.get("nature")
    if nature and nature not in NATURES:
        raise InvalidCard(
            f"nature {nature!r} is not one of {', '.join(NATURES)}")
    rng = card.get("range")
    if rng is not None:
        if (not isinstance(rng, (list, tuple)) or len(rng) != 2
                or not all(isinstance(x, int) for x in rng)
                or not 1 <= rng[0] <= rng[1]):
            raise InvalidCard(
                "range must be [first, last] with 1 <= first <= last — "
                "pages of the file for a PDF, chapters for an EPUB")
    extra = card.get("extra")
    if extra is not None and not isinstance(extra, dict):
        raise InvalidCard("extra must be an object of the site's own fields")


def put(conn: sqlite3.Connection, card: dict, corpus: str = "default") -> dict:
    """Record one card, replacing any card for the same file. Returns it."""
    from datetime import datetime

    validate(card)
    ensure_schema(conn)
    rng = card.get("range") or (None, None)
    values = {
        "corpus": card.get("corpus") or corpus,
        "filepath": card["file"],
        "author": card.get("author"),
        "title": card.get("title"),
        "nature": card.get("nature"),
        "language": card.get("language"),
        "year": str(card["year"]) if card.get("year") is not None else None,
        "edition": card.get("edition"),
        "translator": card.get("translator"),
        "range_start": rng[0],
        "range_end": rng[1],
        "note": card.get("note"),
        "extra": json.dumps(card["extra"], ensure_ascii=False)
                 if card.get("extra") else None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    names = ", ".join(values)
    marks = ", ".join("?" * len(values))
    updates = ", ".join(f"{k} = excluded.{k}" for k in values
                        if k not in ("corpus", "filepath"))
    conn.execute(
        f"INSERT INTO source_cards ({names}) VALUES ({marks}) "
        f"ON CONFLICT(corpus, filepath) DO UPDATE SET {updates}",
        tuple(values.values()))
    conn.commit()
    return get(conn, values["filepath"], values["corpus"])


def put_many(conn: sqlite3.Connection, cards: Iterable[dict],
             corpus: str = "default") -> int:
    """Record a batch. All or nothing: one bad card writes none of them."""
    cards = list(cards)
    for card in cards:
        validate(card)
    for card in cards:
        put(conn, card, corpus)
    return len(cards)


def get(conn: sqlite3.Connection, filepath: str,
        corpus: Optional[str] = None) -> Optional[dict]:
    """The card for one file, or ``None``.

    Without a corpus, a file described in exactly one corpus is found; a path
    that exists in several is ambiguous and raises, because answering from
    the wrong corpus is worse than saying there are two.
    """
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    if corpus:
        row = conn.execute(
            "SELECT * FROM source_cards WHERE filepath = ? AND corpus = ?",
            (filepath, corpus)).fetchone()
        return _row_to_card(row) if row else None
    rows = conn.execute(
        "SELECT * FROM source_cards WHERE filepath = ?", (filepath,)).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        names = ", ".join(sorted(r["corpus"] for r in rows))
        raise InvalidCard(
            f"{filepath!r} is described in several corpora ({names}) — "
            f"say which one")
    return _row_to_card(rows[0])


def list_cards(conn: sqlite3.Connection,
               corpus: Optional[str] = None) -> list[dict]:
    """Every card, or every card of one corpus, by path."""
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    if corpus:
        rows = conn.execute(
            "SELECT * FROM source_cards WHERE corpus = ? ORDER BY filepath",
            (corpus,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM source_cards ORDER BY corpus, filepath").fetchall()
    return [_row_to_card(r) for r in rows]


def delete(conn: sqlite3.Connection, filepath: str,
           corpus: Optional[str] = None) -> bool:
    ensure_schema(conn)
    if corpus:
        cur = conn.execute(
            "DELETE FROM source_cards WHERE filepath = ? AND corpus = ?",
            (filepath, corpus))
    else:
        cur = conn.execute(
            "DELETE FROM source_cards WHERE filepath = ?", (filepath,))
    conn.commit()
    return bool(cur.rowcount)


def unknown_files(conn: sqlite3.Connection) -> list[dict]:
    """Cards describing a file this index does not track.

    A card is written by hand and the file it names can be renamed, moved or
    never indexed. Left unsaid, the description simply never applies and the
    file quietly falls back to "nothing is known about it".
    """
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT c.* FROM source_cards c
           WHERE NOT EXISTS (SELECT 1 FROM indexed_files i
                             WHERE i.filepath = c.filepath
                               AND i.corpus = c.corpus)
           ORDER BY c.corpus, c.filepath""").fetchall()
    return [_row_to_card(r) for r in rows]


def load_cards_file(path: Path | str) -> list[dict]:
    """Read cards from a JSON file: one object, or a list of them."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cards", data.get("sources", [data]))
    if not isinstance(data, list):
        raise InvalidCard("expected a list of cards, or one card")
    return data
