"""Generate the OMR benchmark score (ground-truth MusicXML + MuseScore-engraved PDF).

The score deliberately packs in what real sheet music has and OMR finds hard:
title/composer/tempo text, time-signature changes (4/4, 3/4, 6/8, 2/2, 5/4),
key changes, dense accidentals (sharps, flats, naturals, cautionary), triplets,
16ths, dotted rhythms, ties across barlines, dynamics, hairpins, slurs,
articulations and rehearsal marks.

    .venv/bin/python -m benchmarks.make_benchmark   # writes benchmarks/out/benchmark.{musicxml,pdf}
"""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

from music21 import (articulations, dynamics, expressions, key, meter, metadata, note, spanner, stream,
                     tempo, tie)

OUT = Path(__file__).parent / "out"

DUR = {"w": 4, "h": 2, "q": 1, "e": Fraction(1, 2), "s": Fraction(1, 4), "x": Fraction(1, 8)}

# Sections: (time signature, key fifths, rehearsal mark, measures). Token: PITCH/DUR[.][t][~][!][>]
#   . dotted   t eighth-triplet member   ~ tie to next   ! staccato   > accent   r = rest
SECTIONS = [
    ("4/4", 1, "A", [
        "G4/q B4/q D5/q G5/q",
        "F#5/e E5/e D5/e C5/e B4/h",
        "C#5/q. D5/e E5/q F5/q",          # C#, F natural in G major
        "G5/h~ G5/e F#5/e E5/q",
        "D5/q! D5/q! Bb4/q> A4/q",        # Bb accidental, staccato/accent
        "G4/s A4/s B4/s C5/s D5/e E5/e F#5/q G5/q",
        "A5/q G5/q F5/q E5/q",            # F natural again
        "D5/w",
    ]),
    ("3/4", -3, "B", [
        "Eb5/q G5/q Bb5/q",
        "Ab5/e G5/e F5/e Eb5/e D5/q",
        "C5/et D5/et Eb5/et F5/q G5/q",   # triplets
        "Ab5/h. ",
        "G5/q E5/q F5/q",                 # E natural in Eb major
        "Eb5/q. D5/e C5/q",
        "B4/q C5/q Db5/q",                # B natural, D flat
        "Eb5/h r/q",
    ]),
    ("6/8", 1, "C", [
        "E5/q. B4/q.",
        "C5/e D5/e D#5/e E5/q.",
        "G5/e F#5/e E5/e D#5/q E5/e",
        "B4/q. r/q.",
        "A4/e B4/e C5/e B4/e A4/e G4/e",
        "F#4/q. D#5/q.",
        "E5/q. ~ E5/e r/e r/e".replace(" ~", "~"),
        "E4/q. r/q.",
    ]),
    ("2/2", -1, "D", [
        "F4/h A4/h",
        "C5/q Bb4/q A4/q G4/q",
        "F4/q G4/q A4/q B4/q",            # B natural in F major
        "C5/w",
    ]),
    ("5/4", 0, "E", [
        "C5/q D5/q E5/q F#5/q G5/q",
        "Ab5/q G5/q F5/q Eb5/q D5/q",
        "C5/w r/q",
    ]),
]

DYNAMICS = {0: "mf", 4: "f", 8: "p", 12: "ff", 16: "mp", 24: "f", 28: "pp"}
HAIRPINS = {(1, 2): "crescendo", (9, 10): "diminuendo", (17, 18): "crescendo"}
SLURS = {1: True, 9: True, 17: True, 25: True}


def parse_token(tok: str):
    pitch, d = tok.split("/")
    staccato, accent = d.endswith("!") or "!" in d, ">" in d
    d = d.replace("!", "").replace(">", "")
    tied = d.endswith("~")
    d = d.rstrip("~")
    triplet = d.endswith("t")
    d = d.rstrip("t")
    dotted = d.endswith(".")
    d = d.rstrip(".")
    q = Fraction(DUR[d])
    if dotted:
        q *= Fraction(3, 2)
    if triplet:
        q *= Fraction(2, 3)
    if pitch == "r":
        el = note.Rest(quarterLength=q)
    else:
        el = note.Note(pitch, quarterLength=q)
        if tied:
            el.tie = tie.Tie("start")
        if staccato:
            el.articulations.append(articulations.Staccato())
        if accent:
            el.articulations.append(articulations.Accent())
    return el


# Second benchmark: pickup measure, common/cut-time symbols, compound meters, 4-5 accidental keys,
# 32nds, dotted 16ths, extreme ledger lines, repeat with first/second endings.
SECTIONS_2 = [
    ("c", 4, "A", [
        "B4/q",                                   # pickup (anacrusis)
        "E5/q. F#5/e G#5/q A5/q",
        "B5/e. A5/s G#5/e F#5/e E5/h",            # dotted 16ths
        "C#6/q D#6/q E6/h",                       # ledger lines above
        "B4/x C#5/x D#5/x E5/x F#5/e G#5/e A5/h", # 32nds
    ]),
    ("9/8", -4, "B", [
        "Ab4/q. C5/q. Eb5/q.",
        "Db5/e C5/e Bb4/e Ab4/q. G4/q.",
        "F4/e G4/e Ab4/e Bb4/e C5/e Db5/e Eb5/q.",
        "Ab4/q. r/q. r/q.",
    ]),
    ("12/8", -5, "C", [
        "Bb3/q. Db4/q. F4/q. Bb4/q.",             # low register
        "Gb4/e F4/e Eb4/e Db4/e C4/e Bb3/e A3/q. Bb3/q.",
        "Bb3/w. ",
    ]),
    ("cut", 2, "D", [
        "D5/h F#5/h",
        "A5/q G5/q F#5/q E5/q",
        "D5/w",
    ]),
    ("3/8", 0, "E", [
        "C5/e E5/e G5/e",
        "C6/e. B5/s A5/e",
        "G5/q. ",
        "C5/q r/e",
    ]),
]


def build2() -> stream.Score:
    s = stream.Score()
    s.insert(0, metadata.Metadata(title="Etude in Shifting Meters", composer="A. Benchmark"))
    p = stream.Part()
    p.partName = "Violin"
    m_no = 0
    for ts, fifths, mark, bars in SECTIONS_2:
        for i, bar in enumerate(bars):
            m = stream.Measure(number=m_no)
            if i == 0:
                sig = meter.TimeSignature("4/4" if ts == "c" else "2/2" if ts == "cut" else ts)
                if ts == "c":
                    sig.symbol = "common"
                if ts == "cut":
                    sig.symbol = "cut"
                m.insert(0, sig)
                m.insert(0, key.KeySignature(fifths))
                m.insert(0, expressions.RehearsalMark(mark))
                if m_no == 0:
                    m.insert(0, tempo.MetronomeMark(text="Andante", number=76))
            for tok in bar.split():
                m.append(parse_token(tok))
            if m_no == 0:
                m.padAsAnacrusis()
            p.append(m)
            m_no += 1
    s.append(p)
    for n in p.recurse().notes:
        if n.tie and n.tie.type == "start":
            nxt = n.next("Note")
            if nxt is not None:
                nxt.tie = tie.Tie("stop")
    return s


def build3() -> stream.Score:
    """Instrumental part with multi-measure rests of 12, 4 and 2 bars (engraved as H-bars)."""
    s = stream.Score()
    s.insert(0, metadata.Metadata(title="Rest Study", composer="M. Composer"))
    p = stream.Part()
    p.partName = "Trumpet in Bb"
    plan = [("n", "D5/q E5/q F#5/q"), ("n", "G5/h."), ("r", 12), ("n", "A5/q G5/q F#5/q"), ("n", "E5/h."),
            ("r", 4), ("n", "D5/q F#5/q A5/q"), ("r", 2), ("n", "D5/h.")]
    num = 1
    for kind, v in plan:
        for _ in range(v if kind == "r" else 1):
            m = stream.Measure(number=num)
            if num == 1:
                m.insert(0, meter.TimeSignature("3/4"))
                m.insert(0, key.KeySignature(2))
                m.insert(0, tempo.MetronomeMark(number=97))
            if kind == "r":
                r = note.Rest(quarterLength=3)
                r.fullMeasure = True
                m.append(r)
            else:
                for tok in v.split():
                    m.append(parse_token(tok))
            p.append(m)
            num += 1
    s.append(p)
    return s


MULTIREST_STYLE = ('<museScore version="4.40"><Style><createMultiMeasureRests>1</createMultiMeasureRests>'
                   "</Style></museScore>")


def build() -> stream.Score:
    s = stream.Score()
    s.insert(0, metadata.Metadata(title="Benchmark Suite No. 1", composer="J. Tester"))
    p = stream.Part()
    p.partName = "Flute"
    m_no = 0
    for ts, fifths, mark, bars in SECTIONS:
        for i, bar in enumerate(bars):
            m = stream.Measure(number=m_no + 1)
            if i == 0:
                m.insert(0, meter.TimeSignature(ts))
                m.insert(0, key.KeySignature(fifths))
                m.insert(0, expressions.RehearsalMark(mark))
                if m_no == 0:
                    m.insert(0, tempo.MetronomeMark(text="Allegro moderato", number=112))
            if m_no in DYNAMICS:
                m.insert(0, dynamics.Dynamic(DYNAMICS[m_no]))
            for tok in bar.split():
                m.append(parse_token(tok))
            p.append(m)
            m_no += 1
    measures = list(p.getElementsByClass("Measure"))
    for (a, b), kind in HAIRPINS.items():
        notes = list(measures[a].notes) + list(measures[b].notes)
        sp = dynamics.Crescendo(notes[0], notes[-1]) if kind == "crescendo" else dynamics.Diminuendo(notes[0], notes[-1])
        p.insert(0, sp)
    for idx in SLURS:
        notes = list(measures[idx].notes)
        if len(notes) > 1:
            p.insert(0, spanner.Slur(notes[0], notes[-1]))
    s.append(p)
    # make ties consistent (stop on the following note)
    for n in p.recurse().notes:
        if n.tie and n.tie.type == "start":
            nxt = n.next("Note")
            if nxt is not None:
                nxt.tie = tie.Tie("stop")
    return s


def main() -> None:
    from app.config import get_settings

    OUT.mkdir(exist_ok=True)
    mscore = get_settings().resolved_mscore()
    style = OUT / "multirests.mss"
    style.write_text(MULTIREST_STYLE)
    for name, builder in (("benchmark", build), ("benchmark2", build2), ("benchmark3", build3)):
        xml = OUT / f"{name}.musicxml"
        builder().write("musicxml", fp=str(xml))
        opts = ["-S", str(style)] if name == "benchmark3" else []
        subprocess.run([mscore, *opts, "-o", str(OUT / f"{name}.pdf"), str(xml)], capture_output=True, timeout=180)
        subprocess.run([mscore, *opts, "-o", str(OUT / f"{name}.png"), "-r", "300", str(xml)], capture_output=True, timeout=180)
        print("wrote", xml, OUT / f"{name}.pdf")


if __name__ == "__main__":
    main()
