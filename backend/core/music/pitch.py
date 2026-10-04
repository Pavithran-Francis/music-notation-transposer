"""Pitch, interval and key-signature arithmetic.

Pitches are modelled the way notation models them: a diatonic step letter, a
chromatic alteration and an octave. Intervals carry both a diatonic size
(number of letter-name steps) and a chromatic size (semitones). Transposing a
pitch by such an interval preserves spelling relationships, which is what makes
"F# up a major second" come out as G# rather than Ab.
"""

from __future__ import annotations

from dataclasses import dataclass

STEPS = "CDEFGAB"
STEP_SEMITONES = (0, 2, 4, 5, 7, 9, 11)
# Position of each natural step on the line of fifths (C = 0).
STEP_FIFTHS = {"F": -1, "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5}
FIFTHS_ORDER = "FCGDAEB"
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"

ALTER_SYMBOL = {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}


@dataclass(frozen=True)
class Pitch:
    step: str
    alter: float
    octave: int

    def __post_init__(self) -> None:
        if self.step not in STEPS:
            raise ValueError(f"Invalid step {self.step!r}")

    @property
    def step_index(self) -> int:
        return STEPS.index(self.step)

    @property
    def diatonic(self) -> int:
        """Absolute diatonic index (C0 = 0)."""
        return self.octave * 7 + self.step_index

    @property
    def semitones(self) -> float:
        """MIDI-style number (C4 = 60). Microtonal alters stay fractional."""
        return (self.octave + 1) * 12 + STEP_SEMITONES[self.step_index] + self.alter

    @property
    def midi(self) -> int:
        return int(round(self.semitones))

    @property
    def fifths(self) -> int:
        """Line-of-fifths position (C=0, G=1, F=-1, F#=6, Bb=-2 ...)."""
        return STEP_FIFTHS[self.step] + 7 * int(round(self.alter))

    def transpose(self, interval: "Interval") -> "Pitch":
        new_diatonic = self.diatonic + interval.diatonic
        step_index = new_diatonic % 7
        octave = new_diatonic // 7
        natural = (octave + 1) * 12 + STEP_SEMITONES[step_index]
        alter = self.semitones + interval.chromatic - natural
        if float(alter).is_integer():
            alter = int(alter)
        return Pitch(STEPS[step_index], alter, octave)

    def shift_octaves(self, octaves: int) -> "Pitch":
        return Pitch(self.step, self.alter, self.octave + octaves)

    def name(self) -> str:
        a = int(round(self.alter))
        sym = ALTER_SYMBOL.get(a, f"({self.alter:+g})")
        if a != self.alter:  # microtone
            sym = f"({self.alter:+g})"
        return f"{self.step}{sym}{self.octave}"

    def enharmonic_simplified(self) -> "Pitch":
        """Respell with the smallest possible alteration (used for |alter| >= 3)."""
        target = self.semitones
        best = self
        for delta in (-1, 1, -2, 2):
            d = self.diatonic + delta
            step_index = d % 7
            octave = d // 7
            natural = (octave + 1) * 12 + STEP_SEMITONES[step_index]
            alter = target - natural
            if abs(alter) < abs(best.alter):
                best = Pitch(STEPS[step_index], int(alter) if float(alter).is_integer() else alter, octave)
        return best

    @classmethod
    def parse(cls, text: str) -> "Pitch":
        """Parse names like 'C4', 'F#3', 'Bb5', 'E##2'."""
        text = text.strip()
        step = text[0].upper()
        rest = text[1:]
        alter = 0
        while rest and rest[0] in "#b":
            alter += 1 if rest[0] == "#" else -1
            rest = rest[1:]
        return cls(step, alter, int(rest))


_PERFECT_CLASSES = {0, 3, 4}


@dataclass(frozen=True)
class Interval:
    """A directed interval: diatonic steps and chromatic semitones."""

    diatonic: int
    chromatic: int

    def __add__(self, other: "Interval") -> "Interval":
        return Interval(self.diatonic + other.diatonic, self.chromatic + other.chromatic)

    def __neg__(self) -> "Interval":
        return Interval(-self.diatonic, -self.chromatic)

    def __sub__(self, other: "Interval") -> "Interval":
        return self + (-other)

    @property
    def fifths_delta(self) -> int:
        """How far this interval moves a key along the line of fifths."""
        return Pitch("C", 0, 4).transpose(self).fifths

    @property
    def is_octave_multiple(self) -> bool:
        return self.diatonic % 7 == 0 and self.chromatic == 12 * (self.diatonic // 7)

    def enharmonic_alternatives(self) -> list["Interval"]:
        """Same sounding size, neighbouring letter distances (e.g. M2 vs d3)."""
        return [Interval(self.diatonic + d, self.chromatic) for d in (0, -1, 1)]

    def quality_name(self) -> str:
        direction = 1 if (self.diatonic > 0 or (self.diatonic == 0 and self.chromatic >= 0)) else -1
        d = abs(self.diatonic)
        c = self.chromatic * direction
        simple = d % 7
        octaves = d // 7
        base = STEP_SEMITONES[simple] + 12 * octaves
        diff = c - base
        if simple in _PERFECT_CLASSES:
            quality = {0: "P", 1: "A", -1: "d", 2: "AA", -2: "dd"}.get(diff, f"?{diff}")
        else:
            quality = {0: "M", -1: "m", 1: "A", -2: "d", 2: "AA", -3: "dd"}.get(diff, f"?{diff}")
        size = d + 1
        sign = "" if direction > 0 else "-"
        return f"{sign}{quality}{size}"

    def describe(self) -> str:
        names = {
            "P1": "perfect unison", "m2": "minor second", "M2": "major second",
            "m3": "minor third", "M3": "major third", "P4": "perfect fourth",
            "A4": "augmented fourth", "d5": "diminished fifth", "P5": "perfect fifth",
            "m6": "minor sixth", "M6": "major sixth", "m7": "minor seventh",
            "M7": "major seventh", "P8": "octave", "d3": "diminished third",
            "A1": "augmented unison", "A2": "augmented second", "d4": "diminished fourth",
            "A5": "augmented fifth", "d7": "diminished seventh", "A6": "augmented sixth",
        }
        q = self.quality_name()
        direction = "down" if q.startswith("-") else "up"
        q = q.lstrip("-")
        quality, size = q.rstrip("0123456789"), int(q.lstrip("APMmd?"))
        simple_size = (size - 1) % 7 + 1
        octaves = (size - 1) // 7
        key = f"{quality}{simple_size}"
        base = names.get(key, key)
        if size == 8 and quality == "P":
            base, octaves = "octave", 0
        if self.diatonic == 0 and self.chromatic == 0:
            return "no transposition (unison)"
        extra = "" if octaves == 0 else (" plus an octave" if octaves == 1 else f" plus {octaves} octaves")
        return f"{base}{extra} {direction}"

    @classmethod
    def from_name(cls, name: str) -> "Interval":
        """Parse 'M2', '-P5', 'm3', '-M13' style names."""
        name = name.strip()
        direction = -1 if name.startswith("-") else 1
        name = name.lstrip("+-")
        quality = name.rstrip("0123456789")
        size = int(name[len(quality):])
        d = size - 1
        simple = d % 7
        base = STEP_SEMITONES[simple] + 12 * (d // 7)
        if simple in _PERFECT_CLASSES:
            diff = {"P": 0, "A": 1, "d": -1, "AA": 2, "dd": -2}[quality]
        else:
            diff = {"M": 0, "m": -1, "A": 1, "d": -2, "AA": 2, "dd": -3}[quality]
        return cls(direction * d, direction * (base + diff))


def key_alterations(fifths: int) -> dict[str, int]:
    """Alteration for each step implied by a traditional key signature."""
    alters = {s: 0 for s in STEPS}
    if fifths > 0:
        for i in range(fifths):
            alters[SHARP_ORDER[i % 7]] += 1
    elif fifths < 0:
        for i in range(-fifths):
            alters[FLAT_ORDER[i % 7]] -= 1
    return alters


def fifths_to_name(fifths: int) -> str:
    idx = fifths + 1
    step = FIFTHS_ORDER[idx % 7]
    alter = idx // 7
    return step + {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}.get(alter, "?")


def key_name(fifths: int, mode: str | None = "major") -> str:
    mode = (mode or "major").lower()
    if mode == "minor":
        return f"{fifths_to_name(fifths + 3)} minor"
    if mode in ("major", "none", ""):
        return f"{fifths_to_name(fifths)} major"
    return f"{fifths_to_name(fifths)} major ({mode})"


def choose_spelling(interval: Interval, key_fifths: int, preference: str = "auto") -> Interval:
    """Pick the enharmonic spelling of `interval` that gives a readable key.

    Transposing every note by the same diatonic interval preserves the musical
    spelling relationships of the source. The only free choice is the letter
    distance for the interval as a whole (e.g. up a M2 vs up a d3), which
    determines the target key. We keep the natural spelling unless it produces
    a key with more than six sharps/flats, in which case we use the enharmonic
    equivalent with the fewest accidentals.
    """
    if interval.is_octave_multiple:
        return interval
    candidates = []
    for cand in interval.enharmonic_alternatives():
        new_key = key_fifths + cand.fifths_delta
        if abs(new_key) <= 7:
            candidates.append((cand, new_key))
    if not candidates:
        return interval
    natural, natural_key = candidates[0] if candidates[0][0] == interval else (None, None)

    if preference == "sharps":
        ok = [c for c in candidates if 0 <= c[1] <= 6]
        if ok:
            return min(ok, key=lambda c: c[1])[0]
    elif preference == "flats":
        ok = [c for c in candidates if -6 <= c[1] <= 0]
        if ok:
            return max(ok, key=lambda c: c[1])[0]

    if natural is not None and abs(natural_key) <= 6:
        return natural
    return min(candidates, key=lambda c: (abs(c[1]), c[0] != interval))[0]
