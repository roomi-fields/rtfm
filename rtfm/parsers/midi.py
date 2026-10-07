"""Standard MIDI files (.mid, .midi, .kar).

A MIDI file holds no prose, but it says a lot that can be searched: what the
piece is called, its tempo, metre and key, how long it lasts, which
instruments play on which channel, the range each part covers, its markers
and — in karaoke files — its lyrics. Each file becomes one overview passage
and one passage per track that carries anything.

The format is small and stable (a header chunk, then track chunks of
delta-timed events), so it is read here with the standard library alone:
no extra to install. Damaged tracks are read up to the damage.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers._chunking import (
    content_hash,
    extract_title_from_filename,
    slugify,
)
from rtfm.parsers.base import BaseParser, ParserRegistry


class MIDIExtractionError(Exception):
    """The file is not a readable standard MIDI file."""


GM_PROGRAMS = (
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano",
    "Honky-tonk Piano", "Electric Piano 1", "Electric Piano 2", "Harpsichord",
    "Clavinet", "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer", "Drawbar Organ",
    "Percussive Organ", "Rock Organ", "Church Organ", "Reed Organ",
    "Accordion", "Harmonica", "Tango Accordion", "Acoustic Guitar (nylon)",
    "Acoustic Guitar (steel)", "Electric Guitar (jazz)",
    "Electric Guitar (clean)", "Electric Guitar (muted)", "Overdriven Guitar",
    "Distortion Guitar", "Guitar Harmonics", "Acoustic Bass",
    "Electric Bass (finger)", "Electric Bass (pick)", "Fretless Bass",
    "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2", "Violin",
    "Viola", "Cello", "Contrabass", "Tremolo Strings", "Pizzicato Strings",
    "Orchestral Harp", "Timpani", "String Ensemble 1", "String Ensemble 2",
    "Synth Strings 1", "Synth Strings 2", "Choir Aahs", "Voice Oohs",
    "Synth Voice", "Orchestra Hit", "Trumpet", "Trombone", "Tuba",
    "Muted Trumpet", "French Horn", "Brass Section", "Synth Brass 1",
    "Synth Brass 2", "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet", "Piccolo", "Flute",
    "Recorder", "Pan Flute", "Blown Bottle", "Shakuhachi", "Whistle",
    "Ocarina", "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)",
    "Lead 4 (chiff)", "Lead 5 (charang)", "Lead 6 (voice)", "Lead 7 (fifths)",
    "Lead 8 (bass + lead)", "Pad 1 (new age)", "Pad 2 (warm)",
    "Pad 3 (polysynth)", "Pad 4 (choir)", "Pad 5 (bowed)", "Pad 6 (metallic)",
    "Pad 7 (halo)", "Pad 8 (sweep)", "FX 1 (rain)", "FX 2 (soundtrack)",
    "FX 3 (crystal)", "FX 4 (atmosphere)", "FX 5 (brightness)",
    "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)", "Sitar", "Banjo",
    "Shamisen", "Koto", "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum",
    "Melodic Tom", "Synth Drum", "Reverse Cymbal", "Guitar Fret Noise",
    "Breath Noise", "Seashore", "Bird Tweet", "Telephone Ring", "Helicopter",
    "Applause", "Gunshot",
)

_NOTE_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
_MAJOR_KEYS = ("Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C",
               "G", "D", "A", "E", "B", "F#", "C#")
_MINOR_KEYS = ("Ab", "Eb", "Bb", "F", "C", "G", "D", "A",
               "E", "B", "F#", "C#", "G#", "D#", "A#")
PERCUSSION_CHANNEL = 9  # channel 10, counted from 1


def note_name(number: int) -> str:
    """Scientific pitch: middle C (60) is C4."""
    return f"{_NOTE_NAMES[number % 12]}{number // 12 - 1}"


def key_name(sharps: int, minor: bool) -> str:
    sharps = max(-7, min(7, sharps))
    names = _MINOR_KEYS if minor else _MAJOR_KEYS
    return f"{names[sharps + 7]} {'minor' if minor else 'major'}"


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 \
        else f"{s // 60}:{s % 60:02d}"


def _text(data: bytes, strip: bool = True) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.strip() if strip else text


@dataclass
class Track:
    number: int
    name: str = ""
    instruments: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    lyrics: list[tuple[int, str]] = field(default_factory=list)
    markers: list[tuple[int, str]] = field(default_factory=list)
    channels: set[int] = field(default_factory=set)
    programs: dict[int, list[int]] = field(default_factory=dict)
    notes: int = 0
    low: Optional[int] = None
    high: Optional[int] = None
    first_tick: Optional[int] = None
    last_tick: int = 0
    damaged: bool = False


@dataclass
class Song:
    format: int
    division: int
    tracks: list[Track]
    tempos: list[tuple[int, int]]          # (tick, microseconds per beat)
    time_signatures: list[tuple[int, str]]
    keys: list[tuple[int, str]]
    copyright: list[str]
    end_tick: int

    def seconds(self, tick: int) -> float:
        """Time of *tick*, following every tempo change before it."""
        if self.division & 0x8000:      # SMPTE: frames per second × ticks
            fps = 256 - (self.division >> 8)
            per_frame = self.division & 0xFF
            return tick / (fps * per_frame) if fps and per_frame else 0.0
        ppq = self.division or 480
        elapsed, last_tick, tempo = 0.0, 0, 500_000
        for at, value in sorted(self.tempos):
            if at >= tick:
                break
            elapsed += (at - last_tick) * tempo / ppq / 1e6
            last_tick, tempo = at, value
        return elapsed + (tick - last_tick) * tempo / ppq / 1e6


def _vlq(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise IndexError("truncated variable-length number")
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos
    raise ValueError("variable-length number longer than four bytes")


_DATA_BYTES = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


def read_midi(path: Path) -> Song:
    """Read a standard MIDI file. Raises :class:`MIDIExtractionError`."""
    data = Path(path).read_bytes()
    if not data:
        raise MIDIExtractionError("empty file")
    if data[:4] == b"RIFF" and data[8:12] == b"RMID":   # RIFF-wrapped (.rmi)
        start = data.find(b"MThd")
        data = data[start:] if start >= 0 else b""
    if data[:4] != b"MThd" or len(data) < 14:
        raise MIDIExtractionError("not a standard MIDI file (no MThd header)")
    header_len = struct.unpack(">I", data[4:8])[0]
    fmt, ntracks, division = struct.unpack(">HHH", data[8:14])
    pos = 8 + header_len

    song = Song(format=fmt, division=division, tracks=[], tempos=[],
                time_signatures=[], keys=[], copyright=[], end_tick=0)
    number = 0
    while pos + 8 <= len(data) and number < max(ntracks, 1) + 64:
        kind = data[pos:pos + 4]
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        start, end = pos + 8, pos + 8 + length
        if kind != b"MTrk":
            pos = end
            continue
        number += 1
        if not _length_is_believable(data, end):
            # Some writers leave the length at zero, or wrong, and let the
            # events run on. Read up to the end-of-track event instead.
            track, end = _read_track(number, data, start, len(data), song)
        else:
            track, _ = _read_track(number, data, start, end, song)
        song.tracks.append(track)
        pos = end
    if not song.tracks:
        raise MIDIExtractionError("no track in the file")
    return song


def _length_is_believable(data: bytes, end: int) -> bool:
    """A track's declared end is right when the file ends there, or when
    another chunk starts there (four ASCII letters)."""
    if end == len(data):
        return True
    if end > len(data):
        return False
    tag = data[end:end + 4]
    return len(tag) == 4 and all(65 <= b <= 90 or 97 <= b <= 122 for b in tag)


def _read_track(number: int, body: bytes, pos: int, limit: int,
                song: Song) -> tuple[Track, int]:
    """Read one track's events from ``body[pos:limit]``. Returns the track
    and where it ended (after its end-of-track event, when it has one)."""
    track = Track(number=number)
    tick, status = 0, 0
    channel_prefix: Optional[int] = None
    body = body[:limit]
    try:
        while pos < len(body):
            delta, pos = _vlq(body, pos)
            tick += delta
            byte = body[pos]
            if byte >= 0x80:
                pos += 1
                if byte < 0xF0:
                    status = byte
            elif not status:
                raise ValueError("data byte without a status")
            else:
                byte = status            # running status: reuse the last one
            if byte == 0xFF:
                kind = body[pos]
                length, pos = _vlq(body, pos + 1)
                payload = body[pos:pos + length]
                pos += length
                if kind == 0x2F:
                    song.end_tick = max(song.end_tick, tick)
                    return track, pos
                _meta(track, song, tick, kind, payload, channel_prefix)
                if kind == 0x20 and payload:
                    channel_prefix = payload[0] & 0x0F
                continue
            if byte in (0xF0, 0xF7):
                length, pos = _vlq(body, pos)
                pos += length
                continue
            high, channel = byte & 0xF0, byte & 0x0F
            size = _DATA_BYTES.get(high)
            if size is None:             # system common/real-time: no payload
                continue
            args = body[pos:pos + size]
            if len(args) < size:
                raise IndexError("event cut short")
            pos += size
            track.channels.add(channel)
            if high == 0xC0 and args:
                track.programs.setdefault(channel, [])
                if args[0] not in track.programs[channel]:
                    track.programs[channel].append(args[0])
            elif high == 0x90 and len(args) == 2 and args[1] > 0:
                pitch = args[0]
                track.notes += 1
                track.low = pitch if track.low is None else min(track.low, pitch)
                track.high = pitch if track.high is None else max(track.high, pitch)
                if track.first_tick is None:
                    track.first_tick = tick
                track.last_tick = tick
    except (IndexError, ValueError):
        track.damaged = True
    song.end_tick = max(song.end_tick, tick)
    return track, pos


def _meta(track: Track, song: Song, tick: int, kind: int, payload: bytes,
          channel_prefix: Optional[int]) -> None:
    if kind == 0x03:
        track.name = track.name or _text(payload)
    elif kind == 0x04:
        name = _text(payload)
        if name and name not in track.instruments:
            track.instruments.append(name)
    elif kind == 0x01:
        text = _text(payload)
        if text:
            track.texts.append(text)
    elif kind == 0x02:
        text = _text(payload)
        if text and text not in song.copyright:
            song.copyright.append(text)
    elif kind == 0x05:
        # Syllables keep their spaces: they are what separates the words.
        track.lyrics.append((tick, _text(payload, strip=False)))
    elif kind in (0x06, 0x07):
        text = _text(payload)
        if text:
            track.markers.append((tick, text))
    elif kind == 0x51 and len(payload) == 3:
        song.tempos.append((tick, int.from_bytes(payload, "big")))
    elif kind == 0x58 and len(payload) >= 2:
        song.time_signatures.append((tick, f"{payload[0]}/{2 ** payload[1]}"))
    elif kind == 0x59 and len(payload) >= 2:
        sharps = struct.unpack("b", payload[:1])[0]
        song.keys.append((tick, key_name(sharps, bool(payload[1]))))


def _instruments(track: Track) -> list[str]:
    out = []
    for channel in sorted(track.channels):
        if channel == PERCUSSION_CHANNEL:
            out.append("percussion (channel 10)")
            continue
        for program in track.programs.get(channel, []):
            out.append(f"{GM_PROGRAMS[program]} (channel {channel + 1})")
    return out


def _lyrics_text(lyrics: list[tuple[int, str]]) -> str:
    """Karaoke lyrics come syllable by syllable; ``/`` and ``\\`` start a
    line or a paragraph."""
    out = []
    for _, piece in lyrics:
        if piece.startswith("\\"):
            out.append("\n\n" + piece[1:])
        elif piece.startswith("/"):
            out.append("\n" + piece[1:])
        else:
            out.append(piece)
    return "".join(out).strip()


def describe(song: Song, title: str) -> list[tuple[str, str]]:
    """``(heading, text)`` passages for one file: an overview, then each
    track that carries anything."""
    lines = [f"MIDI file: {title}"]
    kind = {0: "single track", 1: "multitrack", 2: "independent sequences"}
    lines.append(f"Format {song.format} ({kind.get(song.format, 'unknown')}), "
                 f"{len(song.tracks)} track(s)")
    lines.append(f"Duration: {_clock(song.seconds(song.end_tick))}")
    if song.tempos:
        bpms = []
        for _, value in sorted(song.tempos):
            bpm = round(60_000_000 / value) if value else 0
            if not bpms or bpms[-1] != bpm:
                bpms.append(bpm)
        lines.append("Tempo: " + (f"{bpms[0]} BPM" if len(bpms) == 1 else
                                  f"{bpms[0]} BPM, {len(bpms) - 1} change(s), "
                                  f"from {min(bpms)} to {max(bpms)} BPM"))
    if song.time_signatures:
        sigs = list(dict.fromkeys(s for _, s in sorted(song.time_signatures)))
        lines.append("Time signature: " + ", ".join(sigs))
    if song.keys:
        keys = list(dict.fromkeys(k for _, k in sorted(song.keys)))
        lines.append("Key: " + ", ".join(keys))
    if song.copyright:
        lines.append("Copyright: " + " / ".join(song.copyright))
    instruments = list(dict.fromkeys(i for t in song.tracks for i in _instruments(t)))
    if instruments:
        lines.append("Instruments: " + ", ".join(instruments))
    named = [t.name for t in song.tracks if t.name]
    if named:
        lines.append("Tracks: " + ", ".join(named))
    notes = sum(t.notes for t in song.tracks)
    lows = [t.low for t in song.tracks if t.low is not None]
    highs = [t.high for t in song.tracks if t.high is not None]
    if notes:
        lines.append(f"Notes: {notes}, range {note_name(min(lows))}–"
                     f"{note_name(max(highs))}")
    markers = [m for t in song.tracks for m in t.markers]
    if markers:
        lines.append("Markers: " + ", ".join(
            f"{text} ({_clock(song.seconds(at))})" for at, text in sorted(markers)))
    if any(t.damaged for t in song.tracks):
        lines.append("Note: part of the file is damaged; read up to the damage.")
    passages = [("Overview", "\n".join(lines))]

    for t in song.tracks:
        body = []
        if t.instruments:
            body.append("Instrument: " + ", ".join(t.instruments))
        played = _instruments(t)
        if played:
            body.append("Plays: " + ", ".join(played))
        if t.notes:
            body.append(f"Notes: {t.notes}, range {note_name(t.low)}–"
                        f"{note_name(t.high)}, from "
                        f"{_clock(song.seconds(t.first_tick or 0))} to "
                        f"{_clock(song.seconds(t.last_tick))}")
        if t.texts:
            body.append("Text: " + " / ".join(t.texts))
        if t.markers:
            body.append("Markers: " + ", ".join(text for _, text in t.markers))
        lyrics = _lyrics_text(t.lyrics)
        if lyrics:
            body.append("Lyrics:\n" + lyrics)
        if not body:
            continue
        heading = f"Track {t.number}" + (f": {t.name}" if t.name else "")
        passages.append((heading, heading + "\n" + "\n".join(body)))
    return passages


@ParserRegistry.register
class MIDIParser(BaseParser):
    """Standard MIDI files, including karaoke and RIFF-wrapped ones."""

    extensions = [".mid", ".midi", ".kar", ".rmi"]
    name = "midi"

    def parse(self, path: Path, metadata: Optional[dict] = None) -> Iterator[Chunk]:
        metadata = metadata or {}
        song = read_midi(path)
        # A name the file gives itself wins over one made from its path.
        book_title = (self._title(song, path) if self._named(song)
                      else metadata.get("title") or self._title(song, path))
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name
        for idx, (heading, text) in enumerate(describe(song, book_title), 1):
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
                section_type="midi",
                content_chars=len(text),
                content_hash=content_hash(text),
                metadata=metadata.get("extended", {}),
            )

    @staticmethod
    def _named(song: Song) -> bool:
        return bool(song.format == 1 and song.tracks and song.tracks[0].name)

    @staticmethod
    def _title(song: Song, path: Path) -> str:
        # In a multitrack file the first track's name is the piece's name.
        first = song.tracks[0].name if song.tracks else ""
        if first and song.format == 1:
            return first
        return extract_title_from_filename(path.stem)

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
