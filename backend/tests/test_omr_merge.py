"""Two-engine OMR merge (core.omr_merge) on small synthetic readings."""

from lxml import etree

from core.musicxml.document import parse_musicxml, walk
from core.omr_merge import merge_readings
from tests.fixtures.builder import build_score


def tree(measures, **kw):
    return parse_musicxml(build_score(measures, **kw))


def names(t):
    pw = walk(t)[0]
    out = []
    for i in range(len(pw.measures)):
        out.append(" ".join((e.pitch.name() if e.pitch else "r") for e in pw.notes if e.measure_index == i))
    return out


def set_time(t, measure_index, beats, beat_type):
    m = t.getroot().find("part").findall("measure")[measure_index]
    attrs = m.find("attributes")
    if attrs is None:
        attrs = etree.Element("attributes")
        m.insert(0, attrs)
    for x in attrs.findall("time"):
        attrs.remove(x)
    tm = etree.SubElement(attrs, "time")
    etree.SubElement(tm, "beats").text = str(beats)
    etree.SubElement(tm, "beat-type").text = str(beat_type)


def set_key(t, measure_index, fifths):
    m = t.getroot().find("part").findall("measure")[measure_index]
    attrs = m.find("attributes")
    if attrs is None:
        attrs = etree.Element("attributes")
        m.insert(0, attrs)
    for x in attrs.findall("key"):
        attrs.remove(x)
    k = etree.Element("key")
    etree.SubElement(k, "fifths").text = str(fifths)
    attrs.insert(0, k)


def test_identical_readings_agree():
    a = tree(["C4/q D4/q E4/q F4/q", "G4/w"])
    merged, rep = merge_readings(a, tree(["C4/q D4/q E4/q F4/q", "G4/w"]))
    assert rep.applied and all(m.source == "agree" and not m.disputed for m in rep.measures)
    assert names(merged) == ["C4 D4 E4 F4", "G4"]


def test_dropped_notes_under_wrong_meter_are_restored():
    # Truth: 4/4 then 5/4. Primary missed the 5/4 and dropped notes to fit 4/4.
    a = tree(["C4/q D4/q E4/q F4/q", "G4/q A4/q B4/q C5/q", "C5/q B4/q A4/q G4/q"])
    h = tree(["C4/q D4/q E4/q F4/q", "G4/q A4/q B4/q C5/q D5/q", "C5/q B4/q A4/q G4/q F4/q"])
    set_time(h, 1, 3, 4)  # second engine: right denominator, unreliable numerator
    merged, rep = merge_readings(a, h)
    pw = walk(merged)[0]
    assert names(merged)[1:] == ["G4 A4 B4 C5 D5", "C5 B4 A4 G4 F4"]
    assert [m.time for m in pw.measures] == [(4, 4), (5, 4), (5, 4)]
    assert rep.measures[1].source == "secondary" and rep.measures[1].disputed


def test_measure_missed_by_primary_is_inserted():
    a = tree(["C4/q D4/q E4/q F4/q", "A4/q B4/q C5/q D5/q"])
    h = tree(["C4/q D4/q E4/q F4/q", "G4/w", "A4/q B4/q C5/q D5/q"])
    merged, rep = merge_readings(a, h)
    assert names(merged) == ["C4 D4 E4 F4", "G4", "A4 B4 C5 D5"]
    assert [m.get("number") for m in merged.getroot().iter("measure")] == ["1", "2", "3"]


def test_empty_phantom_measure_is_removed_and_directions_kept():
    a = tree(["C4/q D4/q E4/q F4/q", "G4/w", "A4/q B4/q C5/q D5/q"])
    # make measure 2 an empty artifact carrying a rehearsal mark
    m2 = a.getroot().find("part").findall("measure")[1]
    for n in m2.findall("note"):
        m2.remove(n)
    d = etree.SubElement(m2, "direction")
    etree.SubElement(etree.SubElement(d, "direction-type"), "rehearsal").text = "B"
    h = tree(["C4/q D4/q E4/q F4/q", "A4/q B4/q C5/q D5/q"])
    merged, rep = merge_readings(a, h)
    assert names(merged) == ["C4 D4 E4 F4", "A4 B4 C5 D5"]
    assert merged.getroot().find(".//rehearsal").text == "B"
    assert any(m.source == "removed" for m in rep.measures)


def test_key_change_seen_only_by_second_engine():
    a = tree(["C4/q D4/q E4/q F4/q", "D4/q E4/q F4/q G4/q"])  # primary missed the key change (and the sharp)
    h = tree(["C4/q D4/q E4/q F4/q", "D4/q E4/q F#4/q G4/q"])
    set_key(h, 1, 1)
    merged, rep = merge_readings(a, h)
    pw = walk(merged)[0]
    assert [m.key.fifths for m in pw.measures] == [0, 1]
    assert names(merged)[1] == "D4 E4 F#4 G4"  # second reading fits G major better


def test_clef_misread_resolved_by_pitch_context():
    a = tree(["G4/q A4/q B4/q C5/q", "C3/q D3/q E3/q F3/q", "G4/q F4/q E4/q D4/q"])  # m2 read in the wrong clef
    h = tree(["G4/q A4/q B4/q C5/q", "A4/q B4/q C5/q D5/q", "G4/q F4/q E4/q D4/q"])
    merged, rep = merge_readings(a, h)
    assert names(merged)[1] == "A4 B4 C5 D5"
    assert "clef" in rep.measures[1].reason


def test_primary_markings_survive_content_replacement():
    a = tree(["C4/q D4/q E4/q F4/q", "G4/q A4/q B4/q"])  # dropped a note
    m2 = a.getroot().find("part").findall("measure")[1]
    d = etree.Element("direction")
    etree.SubElement(etree.SubElement(d, "direction-type"), "dynamics").append(etree.Element("f"))
    m2.insert(0, d)
    h = tree(["C4/q D4/q E4/q F4/q", "G4/q A4/q B4/q C5/q"])
    merged, _ = merge_readings(a, h)
    assert names(merged)[1] == "G4 A4 B4 C5"
    assert merged.getroot().find(".//dynamics/f") is not None


def test_multi_staff_is_not_merged():
    a = tree(["C5/w ## C3/w"], clefs=("treble", "bass"))
    merged, rep = merge_readings(a, tree(["C5/w"]))
    assert not rep.applied and "multi-staff" in rep.reason
    assert names(merged) == names(a)
