"""MusicXML loading, saving and contextual traversal.

The engine edits the MusicXML DOM in place rather than round-tripping through
an object model, so that everything we don't intentionally change (dynamics,
slurs, lyrics, layout, repeats, text...) survives byte-for-byte.
"""

from __future__ import annotations

import copy
import io
import zipfile
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterator

from lxml import etree

from core.music.clefs import CLEFS, Clef, clef_from_musicxml
from core.music.pitch import Pitch

MAX_XML_BYTES = 60 * 1024 * 1024
MAX_ZIP_ENTRIES = 200


class MusicXMLError(ValueError):
    """Raised for files that are not usable MusicXML."""


def _parser() -> etree.XMLParser:
    # Uploaded files are untrusted: never resolve entities, load DTDs or touch the network.
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def read_musicxml_bytes(data: bytes) -> bytes:
    """Return raw XML bytes from either plain MusicXML or compressed .mxl."""
    if data[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise MusicXMLError("The compressed MusicXML (.mxl) file is corrupt.") from e
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise MusicXMLError("The .mxl archive contains too many files.")
        total = sum(i.file_size for i in infos)
        if total > MAX_XML_BYTES * 2:
            raise MusicXMLError("The .mxl archive expands to an unreasonably large size.")
        target = None
        if "META-INF/container.xml" in zf.namelist():
            container = etree.fromstring(zf.read("META-INF/container.xml"), _parser())
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                rootfile = container.find(".//rootfile")
            if rootfile is not None:
                target = rootfile.get("full-path")
        if not target:
            candidates = [n for n in zf.namelist() if n.lower().endswith((".xml", ".musicxml")) and not n.startswith("META-INF")]
            if not candidates:
                raise MusicXMLError("No MusicXML score found inside the .mxl archive.")
            target = candidates[0]
        info = zf.getinfo(target)
        if info.file_size > MAX_XML_BYTES:
            raise MusicXMLError("The MusicXML score is too large.")
        return zf.read(target)
    return data


def parse_musicxml(data: bytes) -> etree._ElementTree:
    xml = read_musicxml_bytes(data)
    if len(xml) > MAX_XML_BYTES:
        raise MusicXMLError("The MusicXML score is too large.")
    try:
        root = etree.fromstring(xml, _parser())
    except etree.XMLSyntaxError as e:
        raise MusicXMLError(f"Invalid MusicXML: {e}") from e
    if root.tag == "score-timewise":
        root = _timewise_to_partwise(root)
    if root.tag != "score-partwise":
        raise MusicXMLError(f"Unsupported root element <{root.tag}>; expected <score-partwise>.")
    if root.find("part") is None:
        raise MusicXMLError("The MusicXML score has no parts.")
    return etree.ElementTree(root)


def _timewise_to_partwise(root: etree._Element) -> etree._Element:
    new = etree.Element("score-partwise", version=root.get("version", "4.0"))
    parts: dict[str, etree._Element] = {}
    for child in root:
        if child.tag != "measure":
            new.append(copy.deepcopy(child))
    for measure in root.findall("measure"):
        for part in measure.findall("part"):
            pid = part.get("id")
            if pid not in parts:
                parts[pid] = etree.SubElement(new, "part", id=pid)
            m = etree.SubElement(parts[pid], "measure", dict(measure.attrib))
            for c in part:
                m.append(copy.deepcopy(c))
    return new


def to_bytes(tree: etree._ElementTree | etree._Element, strip_ids: bool = False) -> bytes:
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    if strip_ids:
        root = copy.deepcopy(root)
        for el in root.iter("note"):
            el.attrib.pop("id", None)
            el.attrib.pop("color", None)
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype='<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">',
    )


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

NOTE_ORDER = [
    "grace", "cue", "chord", "pitch", "unpitched", "rest", "duration", "tie", "instrument",
    "footnote", "level", "voice", "type", "dot", "accidental", "time-modification", "stem",
    "notehead", "notehead-text", "staff", "beam", "notations", "lyric", "play", "listen",
]
ATTRIBUTES_ORDER = [
    "footnote", "level", "divisions", "key", "time", "staves", "part-symbol", "instruments",
    "clef", "staff-details", "transpose", "for-part", "directive", "measure-style",
]


def insert_ordered(parent: etree._Element, child: etree._Element, order: list[str]) -> None:
    """Insert `child` into `parent` respecting the schema's element order."""
    idx = order.index(child.tag)
    later = set(order[idx + 1 :])
    for i, existing in enumerate(parent):
        if existing.tag in later:
            parent.insert(i, child)
            return
    parent.append(child)


def text_int(el: etree._Element | None, default: int = 0) -> int:
    if el is None or el.text is None:
        return default
    try:
        return int(float(el.text.strip()))
    except ValueError:
        return default


def text_float(el: etree._Element | None, default: float = 0.0) -> float:
    if el is None or el.text is None:
        return default
    try:
        return float(el.text.strip())
    except ValueError:
        return default


def get_pitch(note: etree._Element) -> Pitch | None:
    p = note.find("pitch")
    if p is None:
        return None
    step = (p.findtext("step") or "C").strip().upper()
    alter = text_float(p.find("alter"), 0.0)
    if alter.is_integer():
        alter = int(alter)
    octave = text_int(p.find("octave"), 4)
    return Pitch(step, alter, octave)


def set_pitch(note: etree._Element, pitch: Pitch) -> None:
    p = note.find("pitch")
    if p is None:
        p = etree.Element("pitch")
        insert_ordered(note, p, NOTE_ORDER)
    for c in list(p):
        p.remove(c)
    etree.SubElement(p, "step").text = pitch.step
    if pitch.alter != 0:
        a = pitch.alter
        etree.SubElement(p, "alter").text = str(int(a)) if float(a).is_integer() else f"{a:g}"
    etree.SubElement(p, "octave").text = str(pitch.octave)


def note_staff(note: etree._Element) -> int:
    return text_int(note.find("staff"), 1)


def note_voice(note: etree._Element) -> str:
    return (note.findtext("voice") or "1").strip()


def is_tie_stop(note: etree._Element) -> bool:
    return any(t.get("type") == "stop" for t in note.findall("tie"))


def is_tie_start(note: etree._Element) -> bool:
    return any(t.get("type") == "start" for t in note.findall("tie"))


# ---------------------------------------------------------------------------
# Contextual walker
# ---------------------------------------------------------------------------


@dataclass
class KeyState:
    fifths: int = 0
    mode: str = "major"


@dataclass
class NoteEvent:
    element: etree._Element
    part_index: int
    part_id: str
    measure_index: int
    measure_number: str
    measure: etree._Element
    onset: Fraction  # in divisions, from start of measure
    divisions: int
    staff: int
    voice: str
    is_chord: bool  # true for 2nd+ notes of a chord
    is_grace: bool
    is_rest: bool
    pitch: Pitch | None
    duration: int
    key: KeyState
    clef: Clef | None
    time: tuple[int, int] | None
    doc_order: int = 0

    @property
    def id(self) -> str | None:
        return self.element.get("id")

    @property
    def quarter_offset(self) -> Fraction:
        return self.onset / self.divisions

    def beat(self) -> float:
        """1-based beat number within the measure in the time signature's beat unit."""
        beat_type = self.time[1] if self.time else 4
        return float(self.quarter_offset * Fraction(beat_type, 4)) + 1


@dataclass
class MeasureInfo:
    part_index: int
    measure_index: int
    number: str
    element: etree._Element
    divisions: int
    time: tuple[int, int] | None
    key: KeyState
    implicit: bool
    voice_durations: dict[tuple[int, str], int] = field(default_factory=dict)
    clefs: dict[int, Clef] = field(default_factory=dict)
    staves: int = 1


@dataclass
class PartWalk:
    part_index: int
    part_id: str
    notes: list[NoteEvent]
    measures: list[MeasureInfo]


def parse_clef_element(clef_el: etree._Element) -> Clef | None:
    return clef_from_musicxml(
        clef_el.findtext("sign"),
        text_int(clef_el.find("line"), 0) or None,
        text_int(clef_el.find("clef-octave-change"), 0),
    )


def walk_part(part: etree._Element, part_index: int) -> PartWalk:
    divisions = 1
    key = KeyState()
    time: tuple[int, int] | None = None
    clefs: dict[int, Clef] = {1: CLEFS["treble"]}
    staves = 1
    notes: list[NoteEvent] = []
    measures: list[MeasureInfo] = []
    order = 0
    for m_idx, measure in enumerate(part.findall("measure")):
        pos = Fraction(0)
        last_onset = Fraction(0)
        voice_end: dict[tuple[int, str], Fraction] = {}
        info: MeasureInfo | None = None
        for child in measure:
            tag = child.tag
            if tag == "attributes":
                d = child.find("divisions")
                if d is not None:
                    divisions = max(1, text_int(d, 1))
                k = child.find("key")
                if k is not None and k.find("fifths") is not None:
                    key = KeyState(text_int(k.find("fifths")), (k.findtext("mode") or "major").strip())
                t = child.find("time")
                if t is not None and t.find("beats") is not None:
                    try:
                        beats = sum(int(x) for x in (t.findtext("beats") or "4").split("+"))
                        time = (beats, text_int(t.find("beat-type"), 4))
                    except ValueError:
                        pass
                s = child.find("staves")
                if s is not None:
                    staves = max(1, text_int(s, 1))
                for c in child.findall("clef"):
                    parsed = parse_clef_element(c)
                    if parsed:
                        try:
                            clefs[int(c.get("number") or 1)] = parsed
                        except ValueError:
                            clefs[1] = parsed
            elif tag == "note":
                is_chord = child.find("chord") is not None
                is_grace = child.find("grace") is not None
                dur = text_int(child.find("duration"), 0)
                onset = last_onset if is_chord else pos
                staff = note_staff(child)
                voice = note_voice(child)
                ev = NoteEvent(
                    element=child, part_index=part_index, part_id=part.get("id", ""),
                    measure_index=m_idx, measure_number=measure.get("number", str(m_idx + 1)),
                    measure=measure, onset=onset, divisions=divisions, staff=staff, voice=voice,
                    is_chord=is_chord, is_grace=is_grace, is_rest=child.find("rest") is not None,
                    pitch=get_pitch(child), duration=dur, key=key,
                    clef=clefs.get(staff) or clefs.get(1), time=time, doc_order=order,
                )
                order += 1
                notes.append(ev)
                if not is_chord:
                    last_onset = pos
                    if not is_grace:
                        pos += dur
                        k2 = (staff, voice)
                        voice_end[k2] = voice_end.get(k2, Fraction(0)) + dur
            elif tag == "backup":
                pos -= text_int(child.find("duration"), 0)
                if pos < 0:
                    pos = Fraction(0)
            elif tag == "forward":
                fdur = text_int(child.find("duration"), 0)
                pos += fdur
                fv = (text_int(child.find("staff"), 1), (child.findtext("voice") or "1").strip())
                voice_end[fv] = voice_end.get(fv, Fraction(0)) + fdur
        info = MeasureInfo(
            part_index=part_index, measure_index=m_idx,
            number=measure.get("number", str(m_idx + 1)), element=measure,
            divisions=divisions, time=time, key=key,
            implicit=measure.get("implicit") == "yes",
            voice_durations={k: int(v) for k, v in voice_end.items()},
            clefs=dict(clefs), staves=staves,
        )
        measures.append(info)
    return PartWalk(part_index, part.get("id", ""), notes, measures)


def walk(tree: etree._ElementTree) -> list[PartWalk]:
    root = tree.getroot()
    return [walk_part(p, i) for i, p in enumerate(root.findall("part"))]


def ensure_note_ids(tree: etree._ElementTree) -> None:
    """Give every <note> a unique, stable id attribute (MusicXML 3.1+ allows it)."""
    root = tree.getroot()
    seen: set[str] = set()
    counter = 0
    for p_idx, part in enumerate(root.findall("part")):
        for m_idx, measure in enumerate(part.findall("measure")):
            n_idx = 0
            for note in measure.findall("note"):
                nid = note.get("id")
                if not nid or nid in seen:
                    nid = f"p{p_idx}m{m_idx}n{n_idx}"
                    while nid in seen:
                        counter += 1
                        nid = f"p{p_idx}m{m_idx}n{n_idx}_{counter}"
                    note.set("id", nid)
                seen.add(nid)
                n_idx += 1


def part_names(tree: etree._ElementTree) -> dict[str, str]:
    root = tree.getroot()
    names = {}
    for sp in root.findall("part-list/score-part"):
        names[sp.get("id", "")] = (sp.findtext("part-name") or "").strip()
    return names


def copy_tree(tree: etree._ElementTree) -> etree._ElementTree:
    return etree.ElementTree(copy.deepcopy(tree.getroot()))
