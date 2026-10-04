"""Recognition corrections: a list of edit operations replayed on the original score.

The original MusicXML is never modified. Corrections are stored as an ordered
list of operations and replayed onto a copy, which makes undo trivial (drop the
last operation and replay).
"""

from __future__ import annotations

from fractions import Fraction

from lxml import etree

from core.music.clefs import CLEFS
from core.music.pitch import STEPS, Pitch
from core.musicxml.document import (
    ATTRIBUTES_ORDER,
    NOTE_ORDER,
    copy_tree,
    insert_ordered,
    set_pitch,
    text_int,
    walk,
)

TYPE_QUARTERS = {
    "maxima": Fraction(32), "long": Fraction(16), "breve": Fraction(8), "whole": Fraction(4),
    "half": Fraction(2), "quarter": Fraction(1), "eighth": Fraction(1, 2), "16th": Fraction(1, 4),
    "32nd": Fraction(1, 8), "64th": Fraction(1, 16), "128th": Fraction(1, 32),
}


class CorrectionError(ValueError):
    pass


def _find_note(root: etree._Element, note_id: str) -> etree._Element:
    for n in root.iter("note"):
        if n.get("id") == note_id:
            return n
    raise CorrectionError(f"Note '{note_id}' not found.")


def _pitch_from(op: dict) -> Pitch:
    step = str(op.get("step", "")).upper()
    if step not in STEPS:
        raise CorrectionError(f"Invalid step '{step}'.")
    alter = int(op.get("alter", 0))
    if abs(alter) > 2:
        raise CorrectionError("Alteration must be between -2 and 2.")
    octave = int(op.get("octave", 4))
    if not 0 <= octave <= 9:
        raise CorrectionError("Octave must be between 0 and 9.")
    return Pitch(step, alter, octave)


def _chord_members(note: etree._Element) -> list[etree._Element]:
    """The note plus following <chord/> notes (if `note` is a chord head)."""
    members = [note]
    nxt = note.getnext()
    while nxt is not None and nxt.tag == "note" and nxt.find("chord") is not None:
        members.append(nxt)
        nxt = nxt.getnext()
    return members


def _divisions_for(root: etree._Element, note: etree._Element) -> int:
    divisions = 1
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            for child in measure:
                if child.tag == "attributes" and child.find("divisions") is not None:
                    divisions = max(1, text_int(child.find("divisions"), 1))
                if child is note:
                    return divisions
    return divisions


def _measure_by_index(root: etree._Element, measure_index: int, part_id: str | None = None) -> list[etree._Element]:
    out = []
    for part in root.findall("part"):
        if part_id and part.get("id") != part_id:
            continue
        measures = part.findall("measure")
        if not 0 <= measure_index < len(measures):
            raise CorrectionError(f"Measure index {measure_index} out of range.")
        out.append(measures[measure_index])
    return out


def _start_attributes(measure: etree._Element) -> etree._Element:
    for i, child in enumerate(measure):
        if child.tag == "attributes":
            return child
        if child.tag in ("print",) or (child.tag == "barline" and child.get("location") == "left"):
            continue
        attrs = etree.Element("attributes")
        measure.insert(i, attrs)
        return attrs
    attrs = etree.SubElement(measure, "attributes")
    return attrs


def apply_operation(root: etree._Element, op: dict) -> None:
    kind = op.get("op")
    if kind == "set_pitch":
        note = _find_note(root, op["note_id"])
        if note.find("rest") is not None:
            raise CorrectionError("Cannot set the pitch of a rest; use 'to_note'.")
        set_pitch(note, _pitch_from(op))
        acc = note.find("accidental")
        if acc is not None:
            note.remove(acc)
    elif kind == "to_rest":
        note = _find_note(root, op["note_id"])
        if note.find("chord") is not None:
            # Removing a chord member: delete it outright.
            note.getparent().remove(note)
            return
        followers = _chord_members(note)[1:]
        for f in followers:
            f.getparent().remove(f)
        for tag in ("pitch", "unpitched", "accidental", "stem", "notehead", "beam", "tie"):
            for el in note.findall(tag):
                note.remove(el)
        for notations in note.findall("notations"):
            for t in notations.findall("tied"):
                notations.remove(t)
            if len(notations) == 0:
                note.remove(notations)
        if note.find("rest") is None:
            insert_ordered(note, etree.Element("rest"), NOTE_ORDER)
    elif kind == "to_note":
        note = _find_note(root, op["note_id"])
        rest = note.find("rest")
        if rest is not None:
            note.remove(rest)
        set_pitch(note, _pitch_from(op))
    elif kind == "delete_chord_note":
        note = _find_note(root, op["note_id"])
        if note.find("chord") is None:
            followers = _chord_members(note)[1:]
            if not followers:
                raise CorrectionError("Only notes inside a chord can be deleted; turn single notes into rests.")
            ch = followers[0].find("chord")
            followers[0].remove(ch)
        note.getparent().remove(note)
    elif kind == "set_duration":
        note = _find_note(root, op["note_id"])
        ntype = op.get("type")
        if ntype not in TYPE_QUARTERS:
            raise CorrectionError(f"Invalid note type '{ntype}'.")
        dots = int(op.get("dots", 0))
        if not 0 <= dots <= 3:
            raise CorrectionError("Dots must be between 0 and 3.")
        head = note
        if note.find("chord") is not None:
            prev = note.getprevious()
            while prev is not None and prev.tag == "note" and prev.find("chord") is not None:
                prev = prev.getprevious()
            if prev is not None and prev.tag == "note":
                head = prev
        quarters = TYPE_QUARTERS[ntype] * (2 - Fraction(1, 2 ** dots))
        tm = head.find("time-modification")
        if tm is not None:
            quarters = quarters * text_int(tm.find("normal-notes"), 1) / max(1, text_int(tm.find("actual-notes"), 1))
        divisions = _divisions_for(root, head)
        dur = quarters * divisions
        if dur.denominator != 1:
            # Scale divisions isn't attempted automatically; report clearly.
            raise CorrectionError(
                f"This duration cannot be expressed with the score's divisions ({divisions} per quarter)."
            )
        for member in _chord_members(head):
            d = member.find("duration")
            if d is None:
                d = etree.Element("duration")
                insert_ordered(member, d, NOTE_ORDER)
            d.text = str(int(dur))
            t = member.find("type")
            if t is None:
                t = etree.Element("type")
                insert_ordered(member, t, NOTE_ORDER)
            t.text = ntype
            for dot in member.findall("dot"):
                member.remove(dot)
            for _ in range(dots):
                insert_ordered(member, etree.Element("dot"), NOTE_ORDER)
    elif kind == "set_key":
        fifths = int(op["fifths"])
        if abs(fifths) > 7:
            raise CorrectionError("Key signature must have at most 7 sharps or flats.")
        for measure in _measure_by_index(root, int(op["measure_index"])):
            attrs = _start_attributes(measure)
            for k in attrs.findall("key"):
                attrs.remove(k)
            key = etree.Element("key")
            etree.SubElement(key, "fifths").text = str(fifths)
            if op.get("mode"):
                etree.SubElement(key, "mode").text = op["mode"]
            insert_ordered(attrs, key, ATTRIBUTES_ORDER)
    elif kind == "set_time":
        beats, beat_type = int(op["beats"]), int(op["beat_type"])
        if not (1 <= beats <= 32 and beat_type in (1, 2, 4, 8, 16, 32)):
            raise CorrectionError("Invalid time signature.")
        for measure in _measure_by_index(root, int(op["measure_index"])):
            attrs = _start_attributes(measure)
            for t in attrs.findall("time"):
                attrs.remove(t)
            time = etree.Element("time")
            etree.SubElement(time, "beats").text = str(beats)
            etree.SubElement(time, "beat-type").text = str(beat_type)
            insert_ordered(attrs, time, ATTRIBUTES_ORDER)
    elif kind == "set_clef":
        clef = CLEFS.get(op.get("clef", ""))
        if clef is None:
            raise CorrectionError(f"Unknown clef '{op.get('clef')}'.")
        staff = int(op.get("staff", 1))
        for measure in _measure_by_index(root, int(op["measure_index"]), op.get("part_id")):
            attrs = _start_attributes(measure)
            for c in attrs.findall("clef"):
                if int(c.get("number", "1")) == staff:
                    attrs.remove(c)
            el = etree.Element("clef")
            part = measure.getparent()
            staves = max((text_int(s, 1) for s in part.iter("staves")), default=1)
            if staves > 1:
                el.set("number", str(staff))
            etree.SubElement(el, "sign").text = clef.sign
            etree.SubElement(el, "line").text = str(clef.line)
            if clef.octave_change:
                etree.SubElement(el, "clef-octave-change").text = str(clef.octave_change)
            insert_ordered(attrs, el, ATTRIBUTES_ORDER)
    else:
        raise CorrectionError(f"Unknown correction operation '{kind}'.")


def apply_corrections(tree: etree._ElementTree, operations: list[dict]) -> etree._ElementTree:
    """Replay `operations` onto a copy of `tree`."""
    out = copy_tree(tree)
    root = out.getroot()
    for op in operations:
        apply_operation(root, op)
    if any(op.get("op") in ("set_pitch", "to_note", "set_key", "to_rest") for op in operations):
        # Displayed accidentals must reflect the corrected pitches.
        from core.transposition.engine import recompute_accidentals

        recompute_accidentals(out, courtesy=False)
    return out


def validate_operation(tree: etree._ElementTree, op: dict) -> None:
    """Dry-run an operation so the API can reject bad input before storing it."""
    apply_operation(copy_tree(tree).getroot(), op)


def note_details(tree: etree._ElementTree, note_id: str) -> dict | None:
    for pw in walk(tree):
        for ev in pw.notes:
            if ev.id == note_id:
                return {
                    "note_id": note_id,
                    "part_id": pw.part_id,
                    "measure": ev.measure_number,
                    "measure_index": ev.measure_index,
                    "beat": round(ev.beat(), 3),
                    "staff": ev.staff,
                    "voice": ev.voice,
                    "is_rest": ev.is_rest,
                    "is_chord": ev.is_chord,
                    "pitch": ev.pitch.name() if ev.pitch else None,
                    "step": ev.pitch.step if ev.pitch else None,
                    "alter": int(ev.pitch.alter) if ev.pitch else 0,
                    "octave": ev.pitch.octave if ev.pitch else None,
                    "type": ev.element.findtext("type"),
                    "dots": len(ev.element.findall("dot")),
                }
    return None
