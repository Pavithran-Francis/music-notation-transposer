"""Extract human-readable musical information from a MusicXML score."""

from __future__ import annotations

import re

from lxml import etree

from core.instruments.database import INSTRUMENTS
from core.music.pitch import Interval, key_name
from core.musicxml.document import parse_clef_element, part_names, text_int, walk

# Keyword -> instrument id, checked in order (more specific first).
_NAME_HINTS = [
    (r"bari(tone)?\s*sax", "baritone_sax"), (r"tenor\s*sax", "tenor_sax"), (r"alto\s*sax", "alto_sax"),
    (r"soprano\s*sax", "soprano_sax"), (r"bass\s*clar", "bass_clarinet"), (r"clarinet.*\bA\b", "clarinet_a"),
    (r"clarinet.*E\s*b|E\s*b.*clarinet", "clarinet_eb"), (r"clarinet", "clarinet_bb"),
    (r"piccolo", "piccolo"), (r"alto\s*flute", "alto_flute"), (r"flute", "flute"), (r"oboe", "oboe"),
    (r"english\s*horn|cor anglais", "english_horn"), (r"contra\s*bassoon", "contrabassoon"),
    (r"bassoon", "bassoon"), (r"flugel", "flugelhorn"), (r"cornet", "cornet_bb"),
    (r"trumpet.*\bC\b", "trumpet_c"), (r"trumpet", "trumpet_bb"), (r"horn", "horn_f"),
    (r"bass\s*trombone", "bass_trombone"), (r"trombone", "trombone"), (r"euphonium", "euphonium"),
    (r"baritone", "baritone_horn"), (r"tuba", "tuba"), (r"violin", "violin"), (r"viola", "viola"),
    (r"cello|violoncello", "cello"), (r"contrabass|double\s*bass", "double_bass"),
    (r"bass\s*guitar|electric\s*bass", "electric_bass"), (r"guitar", "guitar"), (r"piano", "piano"),
    (r"recorder", "recorder_soprano"), (r"organ", "organ"), (r"harp", "harp"), (r"ukulele", "ukulele"),
    (r"mandolin", "mandolin"), (r"marimba", "marimba"), (r"xylophone", "xylophone"),
    (r"glock", "glockenspiel"), (r"vibraphone", "vibraphone"),
    (r"soprano", "soprano"), (r"\balto\b", "alto_voice"), (r"\btenor\b", "tenor_voice"), (r"\bbass\b", "bass_voice"),
]


def _transpose_interval(part: etree._Element) -> Interval | None:
    t = part.find("measure/attributes/transpose")
    if t is None:
        return None
    d = text_int(t.find("diatonic"))
    c = text_int(t.find("chromatic"))
    o = text_int(t.find("octave-change"))
    return Interval(d + 7 * o, c + 12 * o)


def guess_instrument(name: str, interval: Interval | None, staves: int) -> str | None:
    lname = (name or "").lower()
    for pattern, iid in _NAME_HINTS:
        if re.search(pattern, lname, re.IGNORECASE):
            inst = next(i for i in INSTRUMENTS if i.id == iid)
            if interval is None or inst.interval.chromatic == interval.chromatic:
                return iid
    if interval is not None and interval.chromatic != 0:
        for inst in INSTRUMENTS:
            if inst.interval == interval:
                return inst.id
    if staves == 2:
        return "piano"
    return None


def analyze(tree: etree._ElementTree) -> dict:
    root = tree.getroot()
    names = part_names(tree)
    walks = walk(tree)
    parts_info = []
    total_notes = total_rests = total_chords = 0
    voices: set[str] = set()
    first_key = first_time = None
    first_clefs: list[str] = []
    key_changes, time_changes = [], []
    for pw, part in zip(walks, root.findall("part")):
        rests = sum(1 for e in pw.notes if e.is_rest)
        chord_onsets = {(e.measure_index, e.onset, e.staff, e.voice) for e in pw.notes if e.is_chord}
        total_notes += sum(1 for e in pw.notes if not e.is_rest)
        total_rests += rests
        total_chords += len(chord_onsets)
        voices.update(f"{e.staff}:{e.voice}" for e in pw.notes)
        staves = max((m.staves for m in pw.measures), default=1)
        interval = _transpose_interval(part)
        clefs = []
        first_measure = part.find("measure")
        if first_measure is not None:
            for c in first_measure.findall("attributes/clef"):
                parsed = parse_clef_element(c)
                if parsed:
                    clefs.append(parsed.label)
        if not clefs:
            clefs = ["Treble"]
        prev_key, prev_time = None, None
        for m in pw.measures:
            k = (m.key.fifths, m.key.mode)
            if prev_key is not None and k != prev_key:
                key_changes.append({"part_id": pw.part_id, "measure": m.number, "key": key_name(*k)})
            prev_key = k
            if prev_time is not None and m.time != prev_time:
                time_changes.append({"part_id": pw.part_id, "measure": m.number,
                                     "time": f"{m.time[0]}/{m.time[1]}" if m.time else None})
            prev_time = m.time
        if first_key is None and pw.measures:
            first_key = pw.measures[0].key
            first_time = pw.measures[0].time
            first_clefs = clefs
        pitched = [e.pitch for e in pw.notes if e.pitch is not None]
        lowest = min(pitched, key=lambda p: p.semitones).name() if pitched else None
        highest = max(pitched, key=lambda p: p.semitones).name() if pitched else None
        parts_info.append({
            "id": pw.part_id,
            "name": names.get(pw.part_id, ""),
            "staves": staves,
            "measures": len(pw.measures),
            "notes": sum(1 for e in pw.notes if not e.is_rest),
            "clefs": clefs,
            "transposition": interval.quality_name() if interval else "P1",
            "instrument_guess": guess_instrument(names.get(pw.part_id, ""), interval, staves),
            "lowest": lowest,
            "highest": highest,
        })

    tempo = None
    for s in root.iter("sound"):
        if s.get("tempo"):
            try:
                tempo = round(float(s.get("tempo")))
                break
            except ValueError:
                continue
    if tempo is None:
        for m in root.iter("metronome"):
            pm = m.findtext("per-minute")
            if pm:
                try:
                    tempo = round(float(re.findall(r"[\d.]+", pm)[0]))
                except (IndexError, ValueError):
                    pass
                break

    from core.metadata import read_metadata
    from core.multirest import count_measures_rests

    meta = read_metadata(tree)
    title, composer = meta["title"], meta["composer"]
    multirests = count_measures_rests(tree)

    lyrics = sum(1 for _ in root.iter("lyric"))
    harmonies = sum(1 for _ in root.iter("harmony"))
    dynamics = sum(1 for _ in root.iter("dynamics"))
    articulations = sum(1 for _ in root.iter("articulations"))
    slurs = sum(1 for s in root.iter("slur") if s.get("type") == "start")
    ties = sum(1 for t in root.iter("tie") if t.get("type") == "start")
    tuplets = sum(1 for t in root.iter("tuplet") if t.get("type") == "start")
    repeats = sum(1 for _ in root.iter("repeat"))
    endings = sum(1 for e in root.iter("ending") if e.get("type") == "start")

    return {
        "title": title,
        "composer": composer,
        "parts": parts_info,
        "key": key_name(first_key.fifths, first_key.mode) if first_key else "C major",
        "key_fifths": first_key.fifths if first_key else 0,
        "key_mode": first_key.mode if first_key else "major",
        "time": f"{first_time[0]}/{first_time[1]}" if first_time else None,
        "clef": ", ".join(first_clefs) if first_clefs else "Treble",
        "tempo": tempo,
        "measures": max((p["measures"] for p in parts_info), default=0),
        "notes": total_notes,
        "rests": total_rests,
        "chords": total_chords,
        "voices": len(voices),
        "key_changes": key_changes,
        "time_changes": time_changes,
        "multirests": multirests,
        "features": {
            "lyrics": lyrics, "chord_symbols": harmonies, "dynamics": dynamics,
            "articulations": articulations, "slurs": slurs, "ties": ties, "tuplets": tuplets,
            "repeats": repeats, "endings": endings,
        },
    }
