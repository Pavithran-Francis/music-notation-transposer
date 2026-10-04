"""Golden transposition corpus.

Every expected score here was worked out by hand from instrument
transposition tables; it is NOT produced by the engine. Run
`python -m tests.fixtures.make_golden` to (re)write the .musicxml files.
"""

MELODY_C = ["C4/q D4/q E4/q F4/q", "G4/h. r/q", "A4/8 B4/8 C5/q~ C5/q G4/q", "C4/w"]

CASES = [
    # --- instrument family pairs ---
    dict(name="c_to_bb", source="flute", target="trumpet_bb",
         input=dict(measures=MELODY_C, key=0),
         expected=dict(measures=["D4/q E4/q F#4/q G4/q", "A4/h. r/q", "B4/8 C#5/8 D5/q~ D5/q A4/q", "D4/w"], key=2)),
    dict(name="c_to_eb", source="flute", target="alto_sax",
         input=dict(measures=MELODY_C, key=0),
         expected=dict(measures=["A4/q B4/q C#5/q D5/q", "E5/h. r/q", "F#5/8 G#5/8 A5/q~ A5/q E5/q", "A4/w"], key=3)),
    dict(name="bb_to_eb", source="trumpet_bb", target="alto_sax",
         input=dict(measures=["D4/q E4/q F#4/q G4/q", "A4/w"], key=2),
         expected=dict(measures=["A4/q B4/q C#5/q D5/q", "E5/w"], key=3)),
    dict(name="eb_to_bb", source="alto_sax", target="trumpet_bb",
         input=dict(measures=["A4/q B4/q C#5/q D5/q", "E5/w"], key=3),
         expected=dict(measures=["D4/q E4/q F#4/q G4/q", "A4/w"], key=2)),
    dict(name="f_to_bb", source="horn_f", target="trumpet_bb",
         input=dict(measures=["G4/q A4/q B4/q C5/q", "D5/w"], key=1),
         expected=dict(measures=["D4/q E4/q F#4/q G4/q", "A4/w"], key=2)),
    dict(name="bb_to_c", source="clarinet_bb", target="oboe",
         input=dict(measures=["D4/q E4/q F#4/q G4/q", "A4/w"], key=2),
         expected=dict(measures=["C4/q D4/q E4/q F4/q", "G4/w"], key=0)),
    dict(name="c_to_f", source="violin", target="horn_f",
         input=dict(measures=["C4/q D4/q E4/q F4/q", "G4/w"], key=0),
         expected=dict(measures=["G4/q A4/q B4/q C5/q", "D5/w"], key=1)),
    dict(name="tenor_sax_to_piano_treble", source="tenor_sax", target="concert_treble",
         input=dict(measures=["D5/q E5/q F#5/q G5/q", "A5/w"], key=2),
         expected=dict(measures=["C4/q D4/q E4/q F4/q", "G4/w"], key=0)),
    # --- key signatures (concert -> Bb) ---
    dict(name="key_F_to_G", source="flute", target="clarinet_bb",
         input=dict(measures=["F4/q G4/q A4/q Bb4/q", "C5/w"], key=-1),
         expected=dict(measures=["G4/q A4/q B4/q C5/q", "D5/w"], key=1)),
    dict(name="key_Bb_to_C", source="flute", target="clarinet_bb",
         input=dict(measures=["Bb4/q C5/q D5/q Eb5/q", "F5/w"], key=-2),
         expected=dict(measures=["C5/q D5/q E5/q F5/q", "G5/w"], key=0)),
    dict(name="key_Eb_to_F", source="flute", target="clarinet_bb",
         input=dict(measures=["Eb4/q F4/q G4/q Ab4/q", "Bb4/w"], key=-3),
         expected=dict(measures=["F4/q G4/q A4/q Bb4/q", "C5/w"], key=-1)),
    dict(name="key_G_to_A", source="flute", target="clarinet_bb",
         input=dict(measures=["G4/q A4/q B4/q C5/q", "D5/w"], key=1),
         expected=dict(measures=["A4/q B4/q C#5/q D5/q", "E5/w"], key=3)),
    # --- enharmonic key choice: B major +M2 would be C# major (7#) -> Db major (5b)
    dict(name="enharmonic_B_to_Db", source="flute", target="trumpet_bb",
         input=dict(measures=["B4/q C#5/q D#5/q E5/q", "F#5/q G#5/q A#5/q B5/q"], key=5),
         expected=dict(measures=["Db5/q Eb5/q F5/q Gb5/q", "Ab5/q Bb5/q C6/q Db6/q"], key=-5)),
    # --- chromatic notes keep their melodic spelling ---
    dict(name="chromatic_spelling", source="flute", target="trumpet_bb",
         input=dict(measures=["C4/q C#4/q D4/q D#4/q", "E4/q Eb4/q D4/q Db4/q", "C4/w"], key=0),
         expected=dict(measures=["D4/q D#4/q E4/q E#4/q", "F#4/q F4/q E4/q Eb4/q", "D4/w"], key=2)),
    # --- minor key ---
    dict(name="minor_key", source="flute", target="alto_sax",
         input=dict(measures=["D4/q E4/q F4/q G4/q", "A4/q Bb4/q C#5/q D5/q"], key=-1, mode="minor"),
         expected=dict(measures=["B4/q C#5/q D5/q E5/q", "F#5/q G5/q A#5/q B5/q"], key=2, mode="minor")),
    # --- clefs: cello (bass clef) -> violin (treble clef), same sounding pitch ---
    dict(name="cello_to_violin", source="cello", target="violin",
         input=dict(measures=["G3/q A3/q B3/q C4/q", "D4/q E4/q F#4/q G4/q", "A4/w"], key=1, clefs=("bass",)),
         expected=dict(measures=["G3/q A3/q B3/q C4/q", "D4/q E4/q F#4/q G4/q", "A4/w"], key=1, clefs=("treble",))),
    # --- bassoon -> tenor sax: concert G2.. -> written up M9 ---
    dict(name="bassoon_to_tenor_sax", source="bassoon", target="tenor_sax",
         input=dict(measures=["G2/q A2/q B2/q C3/q", "D3/w"], key=1, clefs=("bass",)),
         expected=dict(measures=["A3/q B3/q C#4/q D4/q", "E4/w"], key=3, clefs=("treble",))),
    # --- chords, dotted rhythms, triplets, ties ---
    dict(name="chords_and_rhythm", source="concert_treble", target="trumpet_bb",
         input=dict(measures=["[C4 E4 G4]/q. D4/8 E4/8t F4/8t G4/8t A4/q~", "A4/8 G4/16 F4/16 [F4 A4 C5]/h E4/q"], key=0),
         expected=dict(measures=["[D4 F#4 A4]/q. E4/8 F#4/8t G4/8t A4/8t B4/q~", "B4/8 A4/16 G4/16 [G4 B4 D5]/h F#4/q"], key=2)),
    # --- piano, two staves, two voices -> Bb instrument keeps both staves ---
    dict(name="piano_two_voices", source="piano", target="clarinet_bb",
         input=dict(measures=["E5/h D5/h || C5/q B4/q A4/h ## C3/w", "C5/w || G4/w ## [C3 G3]/w"], key=0, clefs=("treble", "bass")),
         expected=dict(measures=["F#5/h E5/h || D5/q C#5/q B4/h ## D3/w", "D5/w || A4/w ## [D3 A3]/w"], key=2, clefs=("treble", "bass"))),
]
