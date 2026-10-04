"""Tiny DSL to write MusicXML test fixtures.

Token syntax inside a measure (space separated):
    C4/q        quarter note C4         F#4/8.   dotted eighth F#4
    r/h         half rest               Bb3/q~   quarter Bb3 tied to next note
    [C4 E4 G4]/q  chord                 C5/8t    eighth-note triplet member
Multiple voices in a measure are separated by ' || ' (voice 1 || voice 2).
For two-staff parts, staves are separated by ' ## ' (staff 1 ## staff 2).
"""

from __future__ import annotations

import re
from fractions import Fraction

from lxml import etree

DIVISIONS = 12
TYPES = {"w": ("whole", 4), "h": ("half", 2), "q": ("quarter", 1), "8": ("eighth", Fraction(1, 2)),
         "16": ("16th", Fraction(1, 4)), "32": ("32nd", Fraction(1, 8))}
CLEF_XML = {"treble": ("G", 2, 0), "bass": ("F", 4, 0), "alto": ("C", 3, 0), "tenor": ("C", 4, 0),
            "treble_8vb": ("G", 2, -1)}


def _parse_token(tok: str):
    pitch_part, dur = tok.rsplit("/", 1)
    tie = dur.endswith("~")
    dur = dur.rstrip("~")
    triplet = dur.endswith("t")
    dur = dur.rstrip("t")
    dots = len(dur) - len(dur.rstrip("."))
    dur = dur.rstrip(".")
    tname, q = TYPES[dur]
    q = Fraction(q) * (2 - Fraction(1, 2 ** dots))
    if triplet:
        q = q * Fraction(2, 3)
    if pitch_part.startswith("["):
        pitches = pitch_part.strip("[]").split()
    elif pitch_part == "r":
        pitches = []
    else:
        pitches = [pitch_part]
    return pitches, tname, dots, q, tie, triplet


def _pitch_el(parent, name):
    step = name[0]
    rest = name[1:]
    alter = 0
    while rest and rest[0] in "#b":
        alter += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    p = etree.SubElement(parent, "pitch")
    etree.SubElement(p, "step").text = step
    if alter:
        etree.SubElement(p, "alter").text = str(alter)
    etree.SubElement(p, "octave").text = rest


def build_score(
    measures: list[str],
    key: int = 0,
    time: tuple[int, int] = (4, 4),
    clefs: tuple[str, ...] = ("treble",),
    part_name: str = "Flute",
    transpose: tuple[int, int, int] | None = None,
    harmonies: dict[int, list[tuple[str, int, str]]] | None = None,
    mode: str = "major",
) -> bytes:
    """Return MusicXML bytes for one part."""
    root = etree.Element("score-partwise", version="4.0")
    pl = etree.SubElement(root, "part-list")
    sp = etree.SubElement(pl, "score-part", id="P1")
    etree.SubElement(sp, "part-name").text = part_name
    part = etree.SubElement(root, "part", id="P1")
    staves = len(clefs)
    tie_open: set[tuple[str, int, str]] = set()
    for m_idx, mtext in enumerate(measures):
        m = etree.SubElement(part, "measure", number=str(m_idx + 1))
        if m_idx == 0:
            a = etree.SubElement(m, "attributes")
            etree.SubElement(a, "divisions").text = str(DIVISIONS)
            k = etree.SubElement(a, "key")
            etree.SubElement(k, "fifths").text = str(key)
            etree.SubElement(k, "mode").text = mode
            t = etree.SubElement(a, "time")
            etree.SubElement(t, "beats").text = str(time[0])
            etree.SubElement(t, "beat-type").text = str(time[1])
            if staves > 1:
                etree.SubElement(a, "staves").text = str(staves)
            for i, c in enumerate(clefs):
                sign, line, oc = CLEF_XML[c]
                ce = etree.SubElement(a, "clef")
                if staves > 1:
                    ce.set("number", str(i + 1))
                etree.SubElement(ce, "sign").text = sign
                etree.SubElement(ce, "line").text = str(line)
                if oc:
                    etree.SubElement(ce, "clef-octave-change").text = str(oc)
            if transpose:
                tr = etree.SubElement(a, "transpose")
                etree.SubElement(tr, "diatonic").text = str(transpose[0])
                etree.SubElement(tr, "chromatic").text = str(transpose[1])
                if transpose[2]:
                    etree.SubElement(tr, "octave-change").text = str(transpose[2])
        for h in (harmonies or {}).get(m_idx, []):
            he = etree.SubElement(m, "harmony")
            r = etree.SubElement(he, "root")
            etree.SubElement(r, "root-step").text = h[0]
            if h[1]:
                etree.SubElement(r, "root-alter").text = str(h[1])
            etree.SubElement(he, "kind").text = h[2]
        staff_texts = mtext.split(" ## ")
        measure_len = Fraction(time[0] * 4, time[1]) * DIVISIONS
        first_block = True
        for s_idx, stext in enumerate(staff_texts):
            for v_idx, vtext in enumerate(stext.split(" || ")):
                if not first_block:
                    b = etree.SubElement(m, "backup")
                    etree.SubElement(b, "duration").text = str(int(measure_len))
                first_block = False
                voice = str(s_idx * 4 + v_idx + 1)
                for tok in re.findall(r"\[[^\]]*\]\S*|\S+", vtext):
                    pitches, tname, dots, q, tie, triplet = _parse_token(tok)
                    dur = int(q * DIVISIONS)
                    for i, pname in enumerate(pitches or [None]):
                        n = etree.SubElement(m, "note")
                        if i > 0:
                            etree.SubElement(n, "chord")
                        if pname is None:
                            etree.SubElement(n, "rest")
                        else:
                            _pitch_el(n, pname)
                        etree.SubElement(n, "duration").text = str(dur)
                        key_t = (voice, s_idx, pname)
                        if pname and key_t in tie_open:
                            etree.SubElement(n, "tie", type="stop")
                        if tie and pname:
                            etree.SubElement(n, "tie", type="start")
                        etree.SubElement(n, "voice").text = voice
                        etree.SubElement(n, "type").text = tname
                        for _ in range(dots):
                            etree.SubElement(n, "dot")
                        if triplet:
                            tm = etree.SubElement(n, "time-modification")
                            etree.SubElement(tm, "actual-notes").text = "3"
                            etree.SubElement(tm, "normal-notes").text = "2"
                        if staves > 1:
                            etree.SubElement(n, "staff").text = str(s_idx + 1)
                        if pname:
                            if key_t in tie_open:
                                tie_open.discard(key_t)
                            if tie:
                                tie_open.add(key_t)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
