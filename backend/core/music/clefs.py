"""Clef definitions and ledger-line cost used for automatic clef selection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Clef:
    id: str
    label: str
    sign: str
    line: int
    octave_change: int = 0
    # Diatonic index (C0 = 0) of the note sitting on the bottom staff line.
    bottom_line: int = 0

    def ledger_lines(self, diatonic: int) -> int:
        """Number of ledger lines needed to write a note at `diatonic`."""
        pos = diatonic - self.bottom_line  # 0..8 lies on the staff
        if pos < -1:
            return (-pos) // 2
        if pos > 9:
            return (pos - 8) // 2
        return 0


def _d(name: str) -> int:
    from .pitch import Pitch

    return Pitch.parse(name).diatonic


CLEFS: dict[str, Clef] = {
    c.id: c
    for c in [
        Clef("treble", "Treble", "G", 2, 0, _d("E4")),
        Clef("treble_8vb", "Treble 8vb", "G", 2, -1, _d("E3")),
        Clef("treble_8va", "Treble 8va", "G", 2, 1, _d("E5")),
        Clef("bass", "Bass", "F", 4, 0, _d("G2")),
        Clef("bass_8vb", "Bass 8vb", "F", 4, -1, _d("G1")),
        Clef("alto", "Alto", "C", 3, 0, _d("F3")),
        Clef("tenor", "Tenor", "C", 4, 0, _d("D3")),
        Clef("percussion", "Percussion", "percussion", 3, 0, _d("F3")),
    ]
}


def clef_from_musicxml(sign: str | None, line: int | None, octave_change: int = 0) -> Clef | None:
    sign = (sign or "").strip()
    default_lines = {"G": 2, "F": 4, "C": 3}
    line = line or default_lines.get(sign)
    for clef in CLEFS.values():
        if clef.sign == sign and clef.line == line and clef.octave_change == octave_change:
            return clef
    if sign == "percussion":
        return CLEFS["percussion"]
    # Unusual clefs (soprano, mezzo, baritone...): compute bottom line directly.
    if sign in ("G", "F", "C") and line:
        ref = {"G": _d("G4"), "F": _d("F3"), "C": _d("C4")}[sign]
        bottom = ref - (line - 1) * 2 + octave_change * 7
        return Clef(f"{sign.lower()}{line}", f"{sign} clef on line {line}", sign, line, octave_change, bottom)
    return None
