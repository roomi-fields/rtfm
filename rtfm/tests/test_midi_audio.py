"""MIDI and audio files are read for what they can say.

A recording or a MIDI score has no prose, but an agent working on a music
project needs to find "the piece in D minor at 90 BPM with a cello", or a
take by its artist and title. Until now these files were skipped as
unreadable binaries.
"""
from __future__ import annotations

import struct

import pytest

from rtfm.parsers.midi import MIDIExtractionError, MIDIParser, note_name, read_midi


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _meta(kind: int, data: bytes, delta: int = 0) -> bytes:
    return _vlq(delta) + bytes([0xFF, kind]) + _vlq(len(data)) + data


def _track(events: bytes, declared: int | None = None) -> bytes:
    body = events
    return b"MTrk" + struct.pack(">I", len(body) if declared is None else declared) + body


def _song(tracks: list[bytes], fmt: int = 1, ppq: int = 480) -> bytes:
    return b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), ppq) + b"".join(tracks)


END = _meta(0x2F, b"")


def _cello_piece() -> bytes:
    conductor = _track(
        _meta(0x03, "Sarabande".encode()) +
        _meta(0x51, (666_667).to_bytes(3, "big")) +        # 90 BPM
        _meta(0x58, bytes([3, 2, 24, 8])) +                # 3/4
        _meta(0x59, struct.pack("b", -1) + b"\x01") +      # D minor
        _meta(0x02, "© Anonyme".encode()) +
        _meta(0x06, b"Reprise", delta=960) + END)
    notes = b""
    for pitch in (50, 53, 57, 62):                         # D3 F3 A3 D4
        notes += _vlq(0) + bytes([0x90, pitch, 80]) + _vlq(480) + bytes([0x80, pitch, 0])
    cello = _track(_meta(0x03, b"Violoncelle") +
                   _vlq(0) + bytes([0xC0, 42]) + notes + END)
    return _song([conductor, cello])


@pytest.fixture
def piece(tmp_path):
    path = tmp_path / "sarabande.mid"
    path.write_bytes(_cello_piece())
    return path


def _text(path) -> str:
    return "\n".join(c.content for c in MIDIParser().parse(path, {}))


def test_what_an_agent_would_search_for(piece):
    text = _text(piece)
    for fact in ("90 BPM", "3/4", "D minor", "Cello (channel 1)", "Violoncelle",
                 "Notes: 4, range D3–D4", "© Anonyme", "Reprise"):
        assert fact in text, fact


def test_the_piece_is_named_by_its_own_title(piece):
    chunks = list(MIDIParser().parse(piece, {"title": "sarabande"}))
    assert chunks[0].book_title == "Sarabande"


def test_the_duration_follows_the_tempo(piece):
    song = read_midi(piece)
    assert round(song.seconds(song.end_tick), 2) == round(4 * 480 * 666_667 / 480 / 1e6, 2)


def test_karaoke_lyrics_come_back_as_lines(tmp_path):
    words = b"".join(_meta(0x05, w.encode()) for w in ("\\Au ", "clair ", "/de ", "la ", "lune"))
    path = tmp_path / "chanson.kar"
    path.write_bytes(_song([_track(words + END)], fmt=0))
    assert "Au clair \nde la lune" in _text(path)


def test_running_status_is_understood(tmp_path):
    events = (_vlq(0) + bytes([0x90, 60, 90]) + _vlq(10) + bytes([64, 90]) +
              _vlq(10) + bytes([67, 90]) + END)
    path = tmp_path / "accord.mid"
    path.write_bytes(_song([_track(events)], fmt=0))
    assert "Notes: 3, range C4–G4" in _text(path)


def test_a_track_whose_length_is_wrong_is_read_to_its_end(tmp_path):
    """Found in real files: a track declared empty, its events running on."""
    events = _vlq(0) + bytes([0x90, 60, 90]) + _vlq(10) + bytes([0x80, 60, 0]) + END
    path = tmp_path / "longueur.mid"
    path.write_bytes(_song([_track(events, declared=0)], fmt=0))
    assert "Notes: 1" in _text(path)


def test_a_cut_file_is_read_up_to_the_cut(tmp_path):
    events = _vlq(0) + bytes([0x90, 60, 90]) + _vlq(10) + bytes([0x90])
    path = tmp_path / "coupe.mid"
    path.write_bytes(_song([_track(events)], fmt=0))
    text = _text(path)
    assert "Notes: 1" in text and "damaged" in text


def test_a_riff_wrapped_file_is_read(tmp_path):
    inner = _cello_piece()
    riff = b"RIFF" + struct.pack("<I", len(inner) + 12) + b"RMID" + b"data" + \
        struct.pack("<I", len(inner)) + inner
    path = tmp_path / "piece.rmi"
    path.write_bytes(riff)
    assert "D minor" in _text(path)


def test_an_empty_or_foreign_file_is_refused(tmp_path):
    empty = tmp_path / "vide.mid"
    empty.write_bytes(b"")
    with pytest.raises(MIDIExtractionError, match="empty"):
        read_midi(empty)
    other = tmp_path / "autre.mid"
    other.write_bytes(b"ID3\x03\x00 not midi")
    with pytest.raises(MIDIExtractionError):
        read_midi(other)


def test_note_names_follow_scientific_pitch():
    assert note_name(60) == "C4" and note_name(21) == "A0" and note_name(69) == "A4"


def test_a_midi_file_is_no_longer_an_unreadable_binary(piece):
    from rtfm.core.sniff import unreadable_binary
    assert not unreadable_binary(piece)


# ── audio ────────────────────────────────────────────────────────────────

@pytest.fixture
def tagged_wav(tmp_path):
    mutagen = pytest.importorskip("mutagen")
    import wave
    from mutagen.id3 import COMM, ID3, TCOM, TIT2, TPE1, USLT
    from mutagen.wave import WAVE

    path = tmp_path / "prise-3.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00\x00\x00" * 48000 * 2)     # two seconds
    audio = WAVE(str(path))
    audio.add_tags()
    audio.tags.add(TIT2(encoding=3, text="Raga du soir"))
    audio.tags.add(TPE1(encoding=3, text="Ensemble Kanopi"))
    audio.tags.add(TCOM(encoding=3, text="R. Fields"))
    audio.tags.add(COMM(encoding=3, lang="fra", desc="", text="Prise de référence"))
    audio.tags.add(USLT(encoding=3, lang="fra", desc="", text="Première ligne\nDeuxième ligne"))
    audio.save()
    assert mutagen
    return path


def _audio_chunks(path):
    from rtfm.parsers.audio import AudioParser
    return list(AudioParser().parse(path, {"title": path.stem}))


def test_tags_and_stream_are_read(tagged_wav):
    chunks = _audio_chunks(tagged_wav)
    overview = chunks[0].content
    assert chunks[0].book_title == "Raga du soir"
    for fact in ("Artist: Ensemble Kanopi", "Composer: R. Fields",
                 "Comment: Prise de référence", "duration 0:02", "48 kHz",
                 "16-bit", "stereo"):
        assert fact in overview, fact


def test_lyrics_get_a_passage_of_their_own(tagged_wav):
    chunks = _audio_chunks(tagged_wav)
    assert chunks[1].chapter_title == "Lyrics"
    assert "Deuxième ligne" in chunks[1].content


def test_an_untagged_file_still_says_what_it_is(tmp_path):
    pytest.importorskip("mutagen")
    import wave
    path = tmp_path / "kick-01.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 4410)
    text = _audio_chunks(path)[0].content
    assert "Audio file: kick-01" in text and "mono" in text and "44.1 kHz" in text


def test_without_the_extra_the_reason_is_given(tmp_path, monkeypatch):
    import builtins
    from rtfm.parsers.audio import AudioExtractionError, read_audio
    real_import = builtins.__import__

    def no_mutagen(name, *a, **k):
        if name == "mutagen":
            raise ImportError("absent")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_mutagen)
    path = tmp_path / "x.mp3"
    path.write_bytes(b"ID3")
    with pytest.raises(AudioExtractionError, match="rtfm-ai\\[audio\\]"):
        read_audio(path)
