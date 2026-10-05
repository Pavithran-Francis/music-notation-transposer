from pathlib import Path

import pytest

from core.analysis import analyze
from core.corrections import CorrectionError, apply_corrections
from core.instruments.database import INSTRUMENTS, custom_instrument, get_instrument
from core.music.clefs import CLEFS
from core.music.pitch import Interval, Pitch, choose_spelling, key_name
from core.musicxml.document import (
    MusicXMLError,
    ensure_note_ids,
    get_pitch,
    parse_musicxml,
    to_bytes,
    walk,
)
from core.transposition.engine import TranspositionOptions, finalize, transpose_pitches, transpose_score
from core.validation.range import apply_adjustments, auto_correct_range, check_range, note_adjustments
from core.validation.validator import compare_transposition, validate_score
from tests.fixtures.builder import build_score
from tests.fixtures.golden_cases import CASES

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def load(data: bytes):
    t = parse_musicxml(data)
    ensure_note_ids(t)
    return t


def events(tree):
    """(pitch name or 'r', duration, type, dots, voice, staff, chord, ties) per note."""
    out = []
    for pw in walk(tree):
        for e in pw.notes:
            out.append((
                e.pitch.name() if e.pitch else "r", e.duration, e.element.findtext("type"),
                len(e.element.findall("dot")), e.voice, e.staff, e.is_chord,
                tuple(t.get("type") for t in e.element.findall("tie")), e.measure_index, e.onset,
            ))
    return out


def first_key(tree):
    return int(tree.getroot().find("part/measure/attributes/key/fifths").text)


def clefs_of(tree):
    out = []
    for c in tree.getroot().find("part/measure/attributes").findall("clef"):
        out.append((c.findtext("sign"), c.findtext("line"), c.findtext("clef-octave-change")))
    return out


# --------------------------------------------------------------------------- pitch


class TestPitch:
    def test_interval_names_roundtrip(self):
        for name in ["P1", "M2", "-M2", "m3", "-M6", "-M9", "-M13", "P8", "-P8", "P15", "d3", "A4", "-M16"]:
            assert Interval.from_name(name).quality_name() == name

    @pytest.mark.parametrize("p,iv,expected", [
        ("C4", "M2", "D4"), ("F#4", "M2", "G#4"), ("Bb3", "M2", "C4"), ("E4", "M2", "F#4"),
        ("B4", "m2", "C5"), ("C4", "-M2", "Bb3"), ("C4", "-M6", "Eb3"), ("C4", "-M9", "Bb2"),
        ("E#4", "d3", "G4"), ("Cb4", "-m3", "Ab3"), ("Cb4", "-M3", "Abb3"),
    ])
    def test_transpose(self, p, iv, expected):
        assert Pitch.parse(p).transpose(Interval.from_name(iv)).name() == expected

    def test_key_spelling_choice(self):
        m2 = Interval.from_name("M2")
        assert choose_spelling(m2, 0) == m2  # C -> D
        assert choose_spelling(m2, 5).quality_name() == "d3"  # B -> Db, not C#
        assert choose_spelling(m2, 6).quality_name() == "d3"  # F# -> Ab, not G#
        assert choose_spelling(Interval.from_name("-M2"), -5).quality_name() == "-d3"  # Db -> B, not Cb
        # octave transpositions never respell
        assert choose_spelling(Interval.from_name("P8"), 7) == Interval.from_name("P8")

    def test_key_names(self):
        assert key_name(0) == "C major"
        assert key_name(2) == "D major"
        assert key_name(-3) == "Eb major"
        assert key_name(-3, "minor") == "C minor"
        assert key_name(-5) == "Db major"

    def test_instrument_written_to_concert(self):
        # "Written C sounds Bb" for Bb trumpet; written C sounds Eb for alto sax; F for horn.
        c = Pitch.parse("C5")
        assert c.transpose(get_instrument("trumpet_bb").interval).name() == "Bb4"
        assert c.transpose(get_instrument("clarinet_bb").interval).name() == "Bb4"
        assert c.transpose(get_instrument("alto_sax").interval).name() == "Eb4"
        assert c.transpose(get_instrument("horn_f").interval).name() == "F4"
        assert c.transpose(get_instrument("tenor_sax").interval).name() == "Bb3"
        assert c.transpose(get_instrument("baritone_sax").interval).name() == "Eb3"

    def test_instrument_database_consistent(self):
        for inst in INSTRUMENTS:
            assert inst.low.semitones <= inst.high.semitones, inst.id
            assert inst.extended_low.semitones <= inst.low.semitones, inst.id
            assert inst.extended_high.semitones >= inst.high.semitones, inst.id
            for c in inst.clefs:
                assert c in CLEFS

    def test_custom_instrument(self):
        inst = custom_instrument("My horn in G", "P4", "down", 0, "treble", "C4", "C6")
        assert inst.interval == Interval.from_name("-P4")
        inst = custom_instrument("Bass thing", "M2", "down", -1, "bass", "C2", "C4")
        assert inst.interval == Interval.from_name("-M9")
        with pytest.raises(ValueError):
            custom_instrument("x", "M2", "down", 0, "nope")


# --------------------------------------------------------------------------- golden corpus


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden(case):
    src, tgt = get_instrument(case["source"]), get_instrument(case["target"])
    inp = load((GOLDEN / f"{case['name']}.input.musicxml").read_bytes())
    exp = load((GOLDEN / f"{case['name']}.expected.musicxml").read_bytes())
    out, info, _ = transpose_score(inp, src, tgt)
    # pitches + rhythms compared programmatically (not visually)
    assert events(out) == events(exp)
    assert first_key(out) == first_key(exp)
    assert clefs_of(out) == clefs_of(exp)
    # concert pitch is preserved exactly
    for a, b in zip(walk(inp)[0].notes, walk(out)[0].notes):
        if a.pitch:
            assert a.pitch.transpose(src.interval).semitones == b.pitch.transpose(tgt.interval).semitones
    from core.metadata import display_name
    report = compare_transposition(inp, out, info.semitones, target_name=display_name(tgt.name))
    assert report.passed, report.to_dict()


# --------------------------------------------------------------------------- engine details


def _accidentals(tree):
    return [(get_pitch(n).name(), n.findtext("accidental"), (n.find("accidental").get("cautionary") if n.find("accidental") is not None else None))
            for n in tree.getroot().iter("note") if n.find("pitch") is not None]


class TestEngine:
    def test_key_signature_avoids_needless_accidentals(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q", "G4/w"]))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        assert first_key(out) == 2
        # F# and C# come from the key signature: no accidentals should be printed
        assert all(acc is None for _, acc, _ in _accidentals(out))

    def test_explicit_accidentals_and_measure_scope(self):
        t = load(build_score(["F#4/q F#4/q F4/q F#4/q", "F#4/w"]))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        accs = _accidentals(out)
        assert [a[0] for a in accs] == ["G#4", "G#4", "G4", "G#4", "G#4"]
        assert [a[1] for a in accs] == ["sharp", None, "natural", "sharp", "sharp"]

    def test_courtesy_accidental_next_measure(self):
        t = load(build_score(["F#4/w", "F4/w"]))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("flute"))
        accs = _accidentals(out)
        assert accs[1] == ("F4", "natural", "yes")
        out2, _ = finalize(transpose_pitches(t, get_instrument("flute"), get_instrument("flute"))[0],
                           get_instrument("flute"), TranspositionOptions(courtesy_accidentals=False))
        assert _accidentals(out2)[1] == ("F4", None, None)

    def test_tied_note_across_barline_has_no_accidental(self):
        t = load(build_score(["C4/h. F#4/q~", "F#4/q F#4/q G4/h"]))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("flute"))
        accs = _accidentals(out)
        assert accs[1] == ("F#4", "sharp", None)
        assert accs[2] == ("F#4", None, None)  # tie continuation
        assert accs[3] == ("F#4", "sharp", None)  # accidental restated after tie

    def test_chord_symbols_transposed(self):
        t = load(build_score(["C4/w", "F4/w"], harmonies={0: [("C", 0, "major")], 1: [("B", -1, "dominant")]}))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("alto_sax"))
        roots = [(h.findtext("root/root-step"), h.findtext("root/root-alter")) for h in out.getroot().iter("harmony")]
        assert roots == [("A", None), ("G", None)]

    def test_transpose_element_and_metadata(self):
        t = load(build_score(["C4/w"]))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("tenor_sax"))
        tr = out.getroot().find("part/measure/attributes/transpose")
        assert (tr.findtext("diatonic"), tr.findtext("chromatic"), tr.findtext("octave-change")) == ("-1", "-2", "-1")
        assert out.getroot().findtext("part-list/score-part/part-name") == "Tenor Saxophone in B♭"
        # back to a C instrument: transpose element removed
        back, _, _ = transpose_score(out, get_instrument("tenor_sax"), get_instrument("flute"))
        assert back.getroot().find(".//transpose") is None

    def test_roundtrip_is_identity(self):
        t = load(build_score(["C4/q C#4/q Eb4/q F#4/q", "[C4 E4 G4]/w"], key=-2))
        a, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("alto_sax"))
        b, _, _ = transpose_score(a, get_instrument("alto_sax"), get_instrument("flute"))
        assert [e[0] for e in events(b)] == [e[0] for e in events(t)]
        assert first_key(b) == -2

    def test_original_tree_not_modified(self):
        t = load(build_score(["C4/w"]))
        before = to_bytes(t)
        transpose_score(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        assert to_bytes(t) == before

    def test_multi_part_selection(self):
        a = load(build_score(["C4/w"]))
        root = a.getroot()
        import copy
        p2 = copy.deepcopy(root.find("part")); p2.set("id", "P2"); root.append(p2)
        sp2 = copy.deepcopy(root.find("part-list/score-part")); sp2.set("id", "P2"); root.find("part-list").append(sp2)
        out, _, _ = transpose_score(a, get_instrument("flute"), get_instrument("trumpet_bb"),
                                    TranspositionOptions(part_ids=["P2"]))
        assert [p.get("id") for p in out.getroot().findall("part")] == ["P2"]

    def test_clef_changes_for_wide_range(self):
        # cello melody climbing high: should switch to tenor/treble and back
        t = load(build_score(["C3/w", "D3/w", "E5/q F5/q G5/q A5/q", "A5/q G5/q F5/q E5/q",
                              "E5/q D5/q C5/q B4/q", "C3/w"], clefs=("bass",)))
        out, _, clefs = transpose_score(t, get_instrument("cello"), get_instrument("cello"))
        labels = [c["clef"] for c in clefs]
        assert labels[0] == "bass" and labels[-1] == "bass" and len(labels) >= 3
        # pitches untouched
        assert [e[0] for e in events(out)] == [e[0] for e in events(t)]

    def test_microtones_preserved(self):
        data = build_score(["C4/w"]).replace(b"<octave>4</octave>", b"<alter>0.5</alter><octave>4</octave>")
        t = load(data)
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        p = get_pitch(out.getroot().find(".//note"))
        assert (p.step, p.alter, p.octave) == ("D", 0.5, 4)


# --------------------------------------------------------------------------- range


class TestRange:
    def test_detects_out_of_range(self):
        t = load(build_score(["C3/q E3/q G3/q C4/q", "C4/w"], clefs=("bass",)))
        out, _, _ = transpose_score(t, get_instrument("cello"), get_instrument("violin"))
        issues = check_range(out, get_instrument("violin"))
        assert [i.pitch for i in issues] == ["C3", "E3"]
        assert all(i.direction == "low" for i in issues)
        assert issues[0].suggested_octaves == 1

    def test_auto_correct_global_octave(self):
        t = load(build_score(["C3/q E3/q G3/q C4/q", "C4/w"], clefs=("bass",)))
        raw, info = transpose_pitches(t, get_instrument("cello"), get_instrument("violin"))
        adj = auto_correct_range(raw, get_instrument("violin"))
        assert adj[0]["kind"] == "global" and adj[0]["octaves"] == 1
        shifts = apply_adjustments(raw, adj)
        assert check_range(raw, get_instrument("violin")) == []
        report = compare_transposition(t, raw, info.semitones, shifts)
        assert report.passed, report.to_dict()

    def test_auto_correct_individual_notes_with_ties(self):
        t = load(build_score(["G3/q A3/q B3/q C6/q~", "C6/q B5/q A5/h"]))
        raw, _ = transpose_pitches(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        adj = auto_correct_range(raw, get_instrument("trumpet_bb"))
        # tie chain moved together
        notes_adj = [a for a in adj if a["kind"] == "note"]
        assert any(len(a["note_ids"]) == 2 for a in notes_adj)
        apply_adjustments(raw, adj)
        assert check_range(raw, get_instrument("trumpet_bb")) == []

    def test_manual_note_adjustment(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q"]))
        nid = walk(t)[0].notes[2].id
        adj = note_adjustments(t, [nid], 1)
        apply_adjustments(t, adj)
        assert walk(t)[0].notes[2].pitch.name() == "E5"


# --------------------------------------------------------------------------- validation


class TestValidation:
    def test_detects_overfull_measure(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q G4/q", "C4/w"]))
        r = validate_score(t)
        assert not r.passed
        assert r.to_dict()["issues"][0]["code"] == "measure_overfull"

    def test_detects_wrong_transposition(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q"]))
        out, info, _ = transpose_score(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        n = out.getroot().find(".//note/pitch/octave")
        n.text = str(int(n.text) + 1)
        r = compare_transposition(t, out, info.semitones)
        assert not r.passed
        assert any(i.code == "pitch_mismatch" for i in r.issues)

    def test_detects_deleted_note(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q"]))
        out, info, _ = transpose_score(t, get_instrument("flute"), get_instrument("trumpet_bb"))
        m = out.getroot().find(".//measure")
        m.remove(m.findall("note")[-1])
        r = compare_transposition(t, out, info.semitones)
        assert any(i.code == "note_count" for i in r.issues)


# --------------------------------------------------------------------------- musicxml io, analysis, corrections


class TestMusicXML:
    def test_rejects_garbage(self):
        with pytest.raises(MusicXMLError):
            parse_musicxml(b"not xml at all")
        with pytest.raises(MusicXMLError):
            parse_musicxml(b"<html></html>")

    def test_entities_not_expanded(self):
        evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><score-partwise><part-list/><part id="P1"><measure number="1"><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note></measure></part></score-partwise>'
        t = parse_musicxml(evil)
        assert b"root:" not in to_bytes(t)

    def test_mxl_roundtrip(self):
        import io, zipfile
        xml = build_score(["C4/w"])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>')
            z.writestr("score.xml", xml)
        t = parse_musicxml(buf.getvalue())
        assert t.getroot().tag == "score-partwise"

    def test_generated_xml_reparses_in_music21(self):
        from music21 import converter
        t = load(build_score(["[C4 E4 G4]/q. D4/8 E4/8t F4/8t G4/8t A4/q"]))
        out, _, _ = transpose_score(t, get_instrument("flute"), get_instrument("alto_sax"))
        s = converter.parseData(to_bytes(out, strip_ids=True).decode())
        names = [p.nameWithOctave for n in s.recurse().notes for p in n.pitches]
        assert names == ["A4", "C#5", "E5", "B4", "C#5", "D5", "E5", "F#5"]

    def test_analysis(self):
        t = load(build_score(["[C4 E4 G4]/q D4/q E4/q r/q", "C4/w"], key=-1, time=(4, 4), part_name="Trumpet in Bb",
                             transpose=(-1, -2, 0)))
        a = analyze(t)
        assert a["key"] == "F major" and a["time"] == "4/4" and a["measures"] == 2
        assert a["notes"] == 6 and a["rests"] == 1 and a["chords"] == 1
        assert a["parts"][0]["instrument_guess"] == "trumpet_bb"
        assert a["clef"] == "Treble"


class TestCorrections:
    def test_corrections_replay_and_original_untouched(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q"]))
        ids = [e.id for e in walk(t)[0].notes]
        ops = [
            {"op": "set_pitch", "note_id": ids[1], "step": "D", "alter": 1, "octave": 4},
            {"op": "to_rest", "note_id": ids[3]},
            {"op": "set_duration", "note_id": ids[0], "type": "eighth", "dots": 0},
        ]
        out = apply_corrections(t, ops)
        ev = walk(out)[0].notes
        assert ev[1].pitch.name() == "D#4" and ev[1].element.findtext("accidental") == "sharp"
        assert ev[3].is_rest
        assert ev[0].duration == 6 and ev[0].element.findtext("type") == "eighth"
        assert walk(t)[0].notes[1].pitch.name() == "D4"

    def test_key_time_clef_corrections(self):
        t = load(build_score(["C4/q D4/q E4/q F4/q"]))
        out = apply_corrections(t, [
            {"op": "set_key", "measure_index": 0, "fifths": 2},
            {"op": "set_time", "measure_index": 0, "beats": 3, "beat_type": 4},
            {"op": "set_clef", "measure_index": 0, "staff": 1, "clef": "alto"},
        ])
        attrs = out.getroot().find(".//attributes")
        assert attrs.findtext("key/fifths") == "2" and attrs.findtext("time/beats") == "3"
        assert attrs.findtext("clef/sign") == "C"

    def test_invalid_correction(self):
        t = load(build_score(["C4/w"]))
        with pytest.raises(CorrectionError):
            apply_corrections(t, [{"op": "set_pitch", "note_id": "nope", "step": "C", "octave": 4}])
        with pytest.raises(CorrectionError):
            apply_corrections(t, [{"op": "set_pitch", "note_id": walk(t)[0].notes[0].id, "step": "H", "octave": 4}])


def test_missing_key_signature_gets_one():
    data = build_score(["C4/q D4/q E4/q F4/q"])
    from lxml import etree
    root = etree.fromstring(data)
    k = root.find(".//key"); k.getparent().remove(k)
    t = load(etree.tostring(root))
    out, _, _ = transpose_score(t, get_instrument("trumpet_bb"), get_instrument("alto_sax"))
    assert first_key(out) == 1
    assert all(acc is None for _, acc, _ in _accidentals(out))
