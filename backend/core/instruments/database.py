"""Instrument database.

Every instrument's transposition is the interval from WRITTEN pitch to
SOUNDING (concert) pitch, exactly as in MusicXML's <transpose> element:
a Bb trumpet's written C sounds a major second lower, so its transposition
is "-M2"; an Eb alto saxophone's written C sounds a major sixth lower ("-M6").

Ranges are given in WRITTEN pitch, the way players and orchestration
references usually quote them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from core.music.clefs import CLEFS
from core.music.pitch import Interval, Pitch


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    family: str
    clefs: tuple[str, ...]  # allowed clefs, first is the primary one
    transposition: str = "P1"  # written -> sounding interval
    range_low: str = "C0"  # typical written range
    range_high: str = "C8"
    ext_low: str | None = None  # extended / professional written range
    ext_high: str | None = None
    staves: int = 1
    midi_program: int = 1  # General MIDI program, 1-based as in MusicXML
    abbreviation: str = ""
    key_name: str = "C"  # nominal key ("Bb", "Eb", "F", ...) for grouping
    notes: str = ""
    staff_clefs: tuple[str, ...] = field(default=())  # primary clef per staff for multi-staff

    @property
    def interval(self) -> Interval:
        return Interval.from_name(self.transposition)

    @property
    def low(self) -> Pitch:
        return Pitch.parse(self.range_low)

    @property
    def high(self) -> Pitch:
        return Pitch.parse(self.range_high)

    @property
    def extended_low(self) -> Pitch:
        return Pitch.parse(self.ext_low or self.range_low)

    @property
    def extended_high(self) -> Pitch:
        return Pitch.parse(self.ext_high or self.range_high)

    def primary_clef_for_staff(self, staff_index: int) -> str:
        if self.staff_clefs and staff_index < len(self.staff_clefs):
            return self.staff_clefs[staff_index]
        return self.clefs[0]

    def to_dict(self) -> dict:
        d = asdict(self)
        iv = self.interval
        d["transposition_description"] = (
            "Non-transposing (sounds as written)"
            if iv.chromatic == 0 and iv.diatonic == 0
            else f"Sounds a {iv.describe()} from written pitch"
        )
        d["clef_labels"] = [CLEFS[c].label for c in self.clefs]
        return d


def _i(*args, **kwargs) -> Instrument:
    return Instrument(*args, **kwargs)


INSTRUMENTS: list[Instrument] = [
    # --- Generic / concert pitch ---
    _i("concert_treble", "Concert pitch (C, treble clef)", "Generic", ("treble", "bass"), "P1", "C3", "C7", midi_program=1, abbreviation="C"),
    _i("concert_bass", "Concert pitch (C, bass clef)", "Generic", ("bass", "tenor", "treble"), "P1", "C1", "C5", midi_program=1, abbreviation="C"),
    # --- Keyboards ---
    _i("piano", "Piano", "Keyboard", ("treble", "bass"), "P1", "A0", "C8", staves=2, midi_program=1, abbreviation="Pno.", staff_clefs=("treble", "bass")),
    _i("organ", "Organ (manuals)", "Keyboard", ("treble", "bass"), "P1", "C2", "C7", staves=2, midi_program=20, abbreviation="Org.", staff_clefs=("treble", "bass")),
    _i("harpsichord", "Harpsichord", "Keyboard", ("treble", "bass"), "P1", "F1", "F6", staves=2, midi_program=7, abbreviation="Hpschd.", staff_clefs=("treble", "bass")),
    _i("celesta", "Celesta", "Keyboard", ("treble", "bass"), "P8", "C3", "C7", staves=2, midi_program=9, abbreviation="Cel.", notes="Sounds an octave higher than written.", staff_clefs=("treble", "bass")),
    # --- Woodwinds ---
    _i("piccolo", "Piccolo", "Woodwind", ("treble",), "P8", "D4", "A6", "D4", "C7", midi_program=73, abbreviation="Picc.", notes="Sounds an octave higher than written."),
    _i("flute", "Flute", "Woodwind", ("treble",), "P1", "C4", "A6", "B3", "D7", midi_program=74, abbreviation="Fl."),
    _i("alto_flute", "Alto Flute in G", "Woodwind", ("treble",), "-P4", "C4", "G6", "C4", "C7", midi_program=74, abbreviation="A. Fl.", key_name="G"),
    _i("oboe", "Oboe", "Woodwind", ("treble",), "P1", "Bb3", "F6", "Bb3", "A6", midi_program=69, abbreviation="Ob."),
    _i("english_horn", "English Horn in F", "Woodwind", ("treble",), "-P5", "B3", "E6", "B3", "G6", midi_program=70, abbreviation="E. Hn.", key_name="F"),
    _i("clarinet_eb", "Clarinet in Eb", "Woodwind", ("treble",), "m3", "E3", "G6", "E3", "A6", midi_program=72, abbreviation="Eb Cl.", key_name="Eb"),
    _i("clarinet_bb", "Clarinet in Bb", "Woodwind", ("treble",), "-M2", "E3", "G6", "E3", "C7", midi_program=72, abbreviation="Cl.", key_name="Bb"),
    _i("clarinet_a", "Clarinet in A", "Woodwind", ("treble",), "-m3", "E3", "G6", "E3", "C7", midi_program=72, abbreviation="Cl. in A", key_name="A"),
    _i("alto_clarinet", "Alto Clarinet in Eb", "Woodwind", ("treble",), "-M6", "E3", "E6", "Eb3", "G6", midi_program=72, abbreviation="A. Cl.", key_name="Eb"),
    _i("bass_clarinet", "Bass Clarinet in Bb", "Woodwind", ("treble", "bass"), "-M9", "Eb3", "E6", "C3", "G6", midi_program=72, abbreviation="B. Cl.", key_name="Bb", notes="Treble-clef (French) notation, sounds a major ninth lower."),
    _i("bassoon", "Bassoon", "Woodwind", ("bass", "tenor", "treble"), "P1", "Bb1", "C5", "Bb1", "E5", midi_program=71, abbreviation="Bsn."),
    _i("contrabassoon", "Contrabassoon", "Woodwind", ("bass",), "-P8", "Bb1", "F4", "Bb1", "Bb4", midi_program=71, abbreviation="Cbsn.", notes="Sounds an octave lower than written."),
    _i("sopranino_sax", "Sopranino Saxophone in Eb", "Woodwind", ("treble",), "m3", "Bb3", "F6", "Bb3", "A6", midi_program=65, abbreviation="Sopranino Sax.", key_name="Eb"),
    _i("soprano_sax", "Soprano Saxophone in Bb", "Woodwind", ("treble",), "-M2", "Bb3", "F6", "Bb3", "A6", midi_program=65, abbreviation="S. Sax.", key_name="Bb"),
    _i("alto_sax", "Alto Saxophone in Eb", "Woodwind", ("treble",), "-M6", "Bb3", "F6", "Bb3", "A6", midi_program=66, abbreviation="A. Sax.", key_name="Eb"),
    _i("tenor_sax", "Tenor Saxophone in Bb", "Woodwind", ("treble",), "-M9", "Bb3", "F6", "Bb3", "A6", midi_program=67, abbreviation="T. Sax.", key_name="Bb"),
    _i("baritone_sax", "Baritone Saxophone in Eb", "Woodwind", ("treble",), "-M13", "Bb3", "F6", "A3", "A6", midi_program=68, abbreviation="B. Sax.", key_name="Eb"),
    _i("bass_sax", "Bass Saxophone in Bb", "Woodwind", ("treble",), "-M16", "Bb3", "F6", "Bb3", "F#6", midi_program=68, abbreviation="Bs. Sax.", key_name="Bb"),
    _i("recorder_soprano", "Soprano (Descant) Recorder", "Woodwind", ("treble",), "P8", "C4", "D6", "C4", "G6", midi_program=75, abbreviation="S. Rec.", notes="Sounds an octave higher than written."),
    _i("recorder_alto", "Alto (Treble) Recorder", "Woodwind", ("treble",), "P1", "F4", "G6", "F4", "C7", midi_program=75, abbreviation="A. Rec."),
    _i("recorder_tenor", "Tenor Recorder", "Woodwind", ("treble",), "P1", "C4", "D6", "C4", "G6", midi_program=75, abbreviation="T. Rec."),
    # --- Brass ---
    _i("trumpet_bb", "Trumpet in Bb", "Brass", ("treble",), "-M2", "F#3", "C6", "F#3", "E6", midi_program=57, abbreviation="Tpt.", key_name="Bb"),
    _i("trumpet_c", "Trumpet in C", "Brass", ("treble",), "P1", "F#3", "C6", "F#3", "E6", midi_program=57, abbreviation="C Tpt."),
    _i("trumpet_d", "Trumpet in D", "Brass", ("treble",), "M2", "F#3", "A5", "F#3", "D6", midi_program=57, abbreviation="D Tpt.", key_name="D"),
    _i("trumpet_eb", "Trumpet in Eb", "Brass", ("treble",), "m3", "F#3", "A5", "F#3", "C6", midi_program=57, abbreviation="Eb Tpt.", key_name="Eb"),
    _i("cornet_bb", "Cornet in Bb", "Brass", ("treble",), "-M2", "F#3", "C6", "E3", "E6", midi_program=57, abbreviation="Cor.", key_name="Bb"),
    _i("cornet_eb", "Soprano Cornet in Eb", "Brass", ("treble",), "m3", "F#3", "A5", "F#3", "C6", midi_program=57, abbreviation="Sop. Cor.", key_name="Eb"),
    _i("flugelhorn", "Flugelhorn in Bb", "Brass", ("treble",), "-M2", "E3", "C6", "E3", "D6", midi_program=57, abbreviation="Flghn.", key_name="Bb"),
    _i("horn_f", "French Horn in F", "Brass", ("treble", "bass"), "-P5", "C3", "G5", "F#2", "C6", midi_program=61, abbreviation="Hn.", key_name="F"),
    _i("horn_eb", "Horn in Eb", "Brass", ("treble",), "-M6", "C3", "G5", "F#2", "C6", midi_program=61, abbreviation="Hn. in Eb", key_name="Eb"),
    _i("tenor_horn", "Tenor (Alto) Horn in Eb", "Brass", ("treble",), "-M6", "F#3", "C6", "E3", "E6", midi_program=61, abbreviation="Ten. Hn.", key_name="Eb"),
    _i("mellophone", "Mellophone in F", "Brass", ("treble",), "-P5", "F#3", "C6", "F#3", "D6", midi_program=61, abbreviation="Mello.", key_name="F"),
    _i("trombone", "Trombone", "Brass", ("bass", "tenor", "alto"), "P1", "E2", "Bb4", "B1", "F5", midi_program=58, abbreviation="Tbn."),
    _i("trombone_treble", "Trombone in Bb (treble clef)", "Brass", ("treble",), "-M9", "F#3", "C6", "C#3", "G6", midi_program=58, abbreviation="Tbn.", key_name="Bb", notes="British brass-band notation."),
    _i("bass_trombone", "Bass Trombone", "Brass", ("bass",), "P1", "C2", "G4", "Bb0", "C5", midi_program=58, abbreviation="B. Tbn."),
    _i("euphonium", "Euphonium (bass clef)", "Brass", ("bass", "tenor"), "P1", "E2", "Bb4", "Bb1", "F5", midi_program=59, abbreviation="Euph."),
    _i("euphonium_treble", "Euphonium in Bb (treble clef)", "Brass", ("treble",), "-M9", "F#3", "C6", "C3", "G6", midi_program=59, abbreviation="Euph.", key_name="Bb"),
    _i("baritone_horn", "Baritone Horn (bass clef)", "Brass", ("bass", "tenor"), "P1", "E2", "Bb4", "Bb1", "F5", midi_program=59, abbreviation="Bar."),
    _i("baritone_horn_treble", "Baritone Horn in Bb (treble clef)", "Brass", ("treble",), "-M9", "F#3", "C6", "C3", "G6", midi_program=59, abbreviation="Bar.", key_name="Bb"),
    _i("tuba", "Tuba", "Brass", ("bass",), "P1", "F1", "F4", "D1", "Bb4", midi_program=59, abbreviation="Tba."),
    # --- Strings ---
    _i("violin", "Violin", "Strings", ("treble",), "P1", "G3", "A6", "G3", "E7", midi_program=41, abbreviation="Vln."),
    _i("viola", "Viola", "Strings", ("alto", "treble"), "P1", "C3", "A5", "C3", "E6", midi_program=42, abbreviation="Vla."),
    _i("cello", "Cello", "Strings", ("bass", "tenor", "treble"), "P1", "C2", "A4", "C2", "C6", midi_program=43, abbreviation="Vc."),
    _i("double_bass", "Double Bass", "Strings", ("bass", "tenor", "treble"), "-P8", "E2", "G4", "C2", "C5", midi_program=44, abbreviation="Cb.", notes="Sounds an octave lower than written."),
    _i("guitar", "Guitar", "Strings", ("treble_8vb",), "P1", "E2", "B4", "E2", "E5", midi_program=25, abbreviation="Gtr.", notes="Written in treble 8vb clef (sounds an octave below the treble clef)."),
    _i("electric_bass", "Bass Guitar", "Strings", ("bass",), "-P8", "E2", "G4", "B1", "C5", midi_program=34, abbreviation="B. Gtr.", notes="Sounds an octave lower than written."),
    _i("ukulele", "Ukulele", "Strings", ("treble",), "P1", "C4", "A5", "C4", "C6", midi_program=25, abbreviation="Uke."),
    _i("mandolin", "Mandolin", "Strings", ("treble",), "P1", "G3", "E6", "G3", "A6", midi_program=26, abbreviation="Mand."),
    _i("harp", "Harp", "Strings", ("treble", "bass"), "P1", "C1", "G#7", staves=2, midi_program=47, abbreviation="Hp.", staff_clefs=("treble", "bass")),
    # --- Pitched percussion ---
    _i("glockenspiel", "Glockenspiel", "Percussion", ("treble",), "P15", "G3", "C6", midi_program=10, abbreviation="Glock.", notes="Sounds two octaves higher than written."),
    _i("xylophone", "Xylophone", "Percussion", ("treble",), "P8", "F3", "C7", midi_program=14, abbreviation="Xyl.", notes="Sounds an octave higher than written."),
    _i("vibraphone", "Vibraphone", "Percussion", ("treble",), "P1", "F3", "F6", midi_program=12, abbreviation="Vib."),
    _i("marimba", "Marimba", "Percussion", ("treble", "bass"), "P1", "A2", "C7", "C2", "C7", staves=2, midi_program=13, abbreviation="Mar.", staff_clefs=("treble", "bass")),
    # --- Voices ---
    _i("soprano", "Soprano voice", "Voice", ("treble",), "P1", "C4", "A5", "B3", "C6", midi_program=53, abbreviation="S."),
    _i("alto_voice", "Alto voice", "Voice", ("treble",), "P1", "F3", "D5", "E3", "F5", midi_program=53, abbreviation="A."),
    _i("tenor_voice", "Tenor voice", "Voice", ("treble_8vb", "bass"), "P1", "C3", "A4", "B2", "C5", midi_program=53, abbreviation="T."),
    _i("bass_voice", "Bass voice", "Voice", ("bass",), "P1", "E2", "E4", "D2", "F4", midi_program=53, abbreviation="B."),
]

_BY_ID = {inst.id: inst for inst in INSTRUMENTS}


def get_instrument(instrument_id: str) -> Instrument:
    try:
        return _BY_ID[instrument_id]
    except KeyError:
        raise KeyError(f"Unknown instrument '{instrument_id}'") from None


def custom_instrument(
    name: str = "Custom instrument",
    interval: str = "P1",
    direction: str = "down",
    octave_displacement: int = 0,
    clef: str = "treble",
    range_low: str = "C3",
    range_high: str = "C7",
    staves: int = 1,
) -> Instrument:
    """Build an instrument from user-supplied transposition settings.

    `interval` is the size of the transposition (e.g. "M2"); `direction`
    says whether the instrument SOUNDS above or below written pitch;
    `octave_displacement` adds whole octaves (positive = sounds higher).
    """
    base = Interval.from_name(interval.lstrip("+-"))
    if direction == "down":
        base = -base
    base = base + Interval(7 * octave_displacement, 12 * octave_displacement)
    if clef not in CLEFS:
        raise ValueError(f"Unknown clef '{clef}'")
    # Validate ranges early so the user gets a clear error.
    lo, hi = Pitch.parse(range_low), Pitch.parse(range_high)
    if lo.semitones > hi.semitones:
        raise ValueError("Range low note must be below range high note")
    return Instrument(
        id="custom",
        name=name or "Custom instrument",
        family="Custom",
        clefs=(clef,) + tuple(c for c in ("treble", "bass") if c != clef),
        transposition=base.quality_name(),
        range_low=range_low,
        range_high=range_high,
        staves=max(1, min(int(staves), 4)),
        abbreviation=(name or "Custom")[:6] + ".",
    )


def resolve_instrument(spec: str | dict) -> Instrument:
    """Accept an instrument id or a custom-instrument dict."""
    if isinstance(spec, str):
        return get_instrument(spec)
    if spec.get("id") and spec.get("id") != "custom":
        return get_instrument(spec["id"])
    return custom_instrument(**{k: v for k, v in spec.items() if k != "id"})
