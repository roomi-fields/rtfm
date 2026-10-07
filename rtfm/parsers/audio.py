"""Audio files: what their tags and stream say.

A recording carries no text to read, but its tags do — title, artist,
album, composer, genre, year, comments, often lyrics — and its stream says
how long it lasts and how it was made. That is what an agent searching a
music project needs to find a file, and what it can quote about it. Each
file becomes one passage, plus one for its lyrics when it has them.

Speech is not transcribed: that is a different, much heavier job.

Install: pip install rtfm-ai[audio]   (mutagen, pure Python)
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers._chunking import (
    content_hash,
    extract_title_from_filename,
    slugify,
)
from rtfm.parsers.base import BaseParser, ParserRegistry


class AudioExtractionError(Exception):
    """The file cannot be read as audio."""


#: Tag fields, in the order they are written out, as mutagen's "easy"
#: interface names them across formats (ID3, Vorbis comments, MP4, ASF).
FIELDS = (
    ("title", "Title"), ("artist", "Artist"), ("albumartist", "Album artist"),
    ("album", "Album"), ("composer", "Composer"), ("conductor", "Conductor"),
    ("performer", "Performer"), ("lyricist", "Lyricist"),
    ("arranger", "Arranger"), ("genre", "Genre"), ("date", "Date"),
    ("originaldate", "Original date"), ("tracknumber", "Track"),
    ("discnumber", "Disc"), ("organization", "Label"), ("copyright", "Copyright"),
    ("language", "Language"), ("bpm", "BPM"), ("isrc", "ISRC"),
)

#: The same fields as ID3 frames, for formats that carry ID3 tags without
#: mutagen's easy interface (WAV, AIFF, DSF).
ID3_FRAMES = {
    "TIT2": "title", "TPE1": "artist", "TPE2": "albumartist", "TALB": "album",
    "TCOM": "composer", "TPE3": "conductor", "TEXT": "lyricist",
    "TPE4": "arranger", "TCON": "genre", "TDRC": "date",
    "TDOR": "originaldate", "TRCK": "tracknumber", "TPOS": "discnumber",
    "TPUB": "organization", "TCOP": "copyright", "TLAN": "language",
    "TBPM": "bpm", "TSRC": "isrc",
}

#: Free-text fields read from the raw tags, where the easy interface stops.
_COMMENT_KEYS = ("comment", "description", "©cmt", "WM/Comments", "Description")
_LYRICS_KEYS = ("lyrics", "unsyncedlyrics", "©lyr", "WM/Lyrics")


def _require_mutagen():
    try:
        import mutagen  # noqa: F401
    except ImportError:
        raise AudioExtractionError(
            "\n\n  Audio files need the audio extra.\n"
            "     Install with:  pip install rtfm-ai[audio]\n"
            "     (plugin: rtfm-install-extras audio)\n"
        )


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 \
        else f"{s // 60}:{s % 60:02d}"


def _values(value) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in items:
        text = getattr(item, "text", item)          # ID3 frames carry .text
        if isinstance(text, (list, tuple)):
            out.extend(str(t) for t in text)
        else:
            out.append(str(text))
    return [v.strip() for v in out if str(v).strip()]


def _raw_text(tags, keys) -> list[str]:
    """Comments or lyrics wherever the format keeps them."""
    if tags is None:
        return []
    found: list[str] = []
    for key in list(tags.keys()):
        k = str(key)
        if k.startswith("COMM") and keys is _COMMENT_KEYS \
                or k.startswith("USLT") and keys is _LYRICS_KEYS \
                or k in keys or k.lower() in keys:
            for v in _values(tags[key]):
                if v not in found:
                    found.append(v)
    return found


def read_audio(path: Path) -> tuple[list[tuple[str, str]], dict]:
    """``(label, value)`` lines and the stream's facts. Raises
    :class:`AudioExtractionError`."""
    _require_mutagen()
    import mutagen

    try:
        easy = mutagen.File(str(path), easy=True)
        raw = mutagen.File(str(path))
    except Exception as exc:
        raise AudioExtractionError(f"unreadable audio file: {exc}") from exc
    if raw is None:
        raise AudioExtractionError("not an audio format mutagen knows")

    found: dict[str, list[str]] = {}
    tags = getattr(easy, "tags", None) if easy is not None else None
    if tags is not None:
        for key, _ in FIELDS:
            try:
                values = _values(tags[key]) if key in tags else []
            except (KeyError, ValueError, TypeError):
                values = []
            if values:
                found[key] = values
    for frame, key in ID3_FRAMES.items():
        if key in found or raw.tags is None:
            continue
        try:
            values = _values(raw.tags[frame]) if frame in raw.tags else []
        except (KeyError, ValueError, TypeError):
            values = []
        if values:
            found[key] = values
    lines: list[tuple[str, str]] = [
        (label, " / ".join(dict.fromkeys(found[key])))
        for key, label in FIELDS if key in found]
    comments = _raw_text(raw.tags, _COMMENT_KEYS)
    if comments:
        lines.append(("Comment", " / ".join(comments)))

    info = raw.info
    facts = {
        "length": getattr(info, "length", 0) or 0,
        "sample_rate": getattr(info, "sample_rate", 0) or 0,
        "channels": getattr(info, "channels", 0) or 0,
        "bitrate": getattr(info, "bitrate", 0) or 0,
        "bits_per_sample": getattr(info, "bits_per_sample", 0) or 0,
        "format": type(raw).__name__,
        "lyrics": "\n\n".join(_raw_text(raw.tags, _LYRICS_KEYS)),
    }
    return lines, facts


def describe(path: Path, title: str, lines, facts) -> list[tuple[str, str]]:
    body = [f"Audio file: {title}"]
    body += [f"{label}: {value}" for label, value in lines if label != "Title"]
    stream = []
    if facts["length"]:
        stream.append(f"duration {_clock(facts['length'])}")
    if facts["sample_rate"]:
        stream.append(f"{facts['sample_rate'] / 1000:g} kHz")
    if facts["bits_per_sample"]:
        stream.append(f"{facts['bits_per_sample']}-bit")
    if facts["channels"]:
        stream.append({1: "mono", 2: "stereo"}.get(facts["channels"],
                                                   f"{facts['channels']} channels"))
    if facts["bitrate"]:
        stream.append(f"{round(facts['bitrate'] / 1000)} kbit/s")
    body.append(f"Format: {path.suffix.lstrip('.').upper()} ({facts['format']})"
                + (", " + ", ".join(stream) if stream else ""))
    passages = [("Overview", "\n".join(body))]
    if facts["lyrics"]:
        passages.append(("Lyrics", f"Lyrics — {title}\n\n{facts['lyrics']}"))
    return passages


@ParserRegistry.register
class AudioParser(BaseParser):
    """Tags and stream facts of common audio formats."""

    extensions = [".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b",
                  ".aac", ".wav", ".aif", ".aiff", ".aifc", ".wma", ".ape",
                  ".wv", ".mpc", ".dsf", ".tta"]
    name = "audio"

    def parse(self, path: Path, metadata: Optional[dict] = None) -> Iterator[Chunk]:
        metadata = metadata or {}
        lines, facts = read_audio(path)
        tagged = dict(lines).get("Title")
        book_title = metadata.get("title") if not tagged else tagged
        book_title = book_title or extract_title_from_filename(path.stem)
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name
        for idx, (heading, text) in enumerate(
                describe(path, book_title, lines, facts), 1):
            yield Chunk(
                id=f"{book_slug}-{idx:04d}",
                content=text,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=heading,
                chapter_num=idx,
                page_start=1,
                page_end=1,
                section_type="audio",
                content_chars=len(text),
                content_hash=content_hash(text),
                metadata=metadata.get("extended", {}),
            )

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
