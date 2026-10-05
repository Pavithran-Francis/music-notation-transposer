"""Multi-measure rests in MusicXML.

MusicXML writes a multi-measure rest as N real measures of whole-measure rests,
the first carrying <measure-style><multiple-rest>N</multiple-rest></measure-style>.
OMR engines differ: Audiveris writes the N measures, homr writes a single empty
measure. To compare and merge readings, each rest block is first collapsed to a
single "token" measure; after merging, tokens are expanded again with the count
read from the page.
"""

from __future__ import annotations

import copy
from fractions import Fraction

from lxml import etree

from core.musicxml.document import ATTRIBUTES_ORDER, insert_ordered, walk


def _count(measure: etree._Element) -> int | None:
    el = measure.find("attributes/measure-style/multiple-rest")
    if el is None:
        return None
    try:
        return int(el.text.strip())
    except (AttributeError, ValueError):
        return None


def _is_rest_only(measure: etree._Element) -> bool:
    notes = measure.findall("note")
    return bool(notes) and all(n.find("rest") is not None for n in notes)


def _full_rest(duration: int) -> etree._Element:
    n = etree.Element("note")
    etree.SubElement(n, "rest", measure="yes")
    etree.SubElement(n, "duration").text = str(duration)
    etree.SubElement(n, "voice").text = "1"
    return n


def _measure_durations(tree: etree._ElementTree) -> list[int]:
    """Full-measure duration (in divisions) for every measure of the first part."""
    out = []
    for m in walk(tree)[0].measures:
        if m.time:
            d = Fraction(m.time[0] * 4, m.time[1]) * m.divisions
            out.append(int(d) if d.denominator == 1 else 4 * m.divisions)
        else:
            out.append(4 * m.divisions)
    return out


def collapse(tree: etree._ElementTree) -> etree._ElementTree:
    """Return a copy where every multi-measure rest is a single token measure."""
    out = copy.deepcopy(tree)
    durations = _measure_durations(out)
    for part in out.getroot().findall("part"):
        measures = part.findall("measure")
        i = 0
        while i < len(measures):
            m = measures[i]
            n = _count(m)
            if n is None:
                i += 1
                continue
            # Engines that expand the rest write n-1 more rest-only measures: fold them in.
            j = i + 1
            while j < len(measures) and j < i + n and _is_rest_only(measures[j]) and _count(measures[j]) is None:
                for child in measures[j]:
                    if child.tag == "direction":
                        m.append(copy.deepcopy(child))
                part.remove(measures[j])
                j += 1
            # Engines that write an empty measure: give it a full-measure rest so readings compare equal.
            if m.find("note") is None:
                insert_at = len(m)
                for k, child in enumerate(m):
                    if child.tag == "barline" and child.get("location") != "left":
                        insert_at = k
                        break
                m.insert(insert_at, _full_rest(durations[i] if i < len(durations) else 4))
            else:
                for note in m.findall("note"):
                    if note.find("rest") is not None:
                        note.find("rest").set("measure", "yes")
            measures = part.findall("measure")
            i += 1
    return out


def tokens(tree: etree._ElementTree) -> list[etree._Element]:
    """Token measures (in score order) of the first part."""
    part = tree.getroot().find("part")
    return [m for m in part.findall("measure") if _count(m) is not None] if part is not None else []


def set_count(measure: etree._Element, count: int) -> None:
    el = measure.find("attributes/measure-style/multiple-rest")
    if el is not None:
        el.text = str(count)


def mark_token(measure: etree._Element, count: int) -> None:
    """Turn a measure into a multi-measure rest token."""
    attrs = measure.find("attributes")
    if attrs is None:
        attrs = etree.Element("attributes")
        measure.insert(0, attrs)
    ms = attrs.find("measure-style")
    if ms is None:
        ms = etree.Element("measure-style")
        insert_ordered(attrs, ms, ATTRIBUTES_ORDER)
    for old in ms.findall("multiple-rest"):
        ms.remove(old)
    etree.SubElement(ms, "multiple-rest").text = str(count)


def expand(tree: etree._ElementTree) -> list[int]:
    """Expand token measures into N measures and renumber, in place.

    Returns, for every measure index before expansion, its index afterwards.
    """
    durations = _measure_durations(tree)
    first_part = tree.getroot().find("part")
    index_map: list[int] = []
    if first_part is not None:
        pos = 0
        for m in first_part.findall("measure"):
            index_map.append(pos)
            n = _count(m)
            pos += n if n and n >= 2 else 1
    for part in tree.getroot().findall("part"):
        measures = part.findall("measure")
        for idx in range(len(measures) - 1, -1, -1):
            m = measures[idx]
            n = _count(m)
            if not n or n < 2:
                continue
            dur = durations[idx] if idx < len(durations) else 4
            anchor = m
            for _ in range(n - 1):
                extra = etree.Element("measure")
                extra.append(_full_rest(dur))
                anchor.addnext(extra)
                anchor = extra
        first = part.find("measure")
        start_no = first.get("number", "1") if first is not None else "1"
        start = int(start_no) if start_no.isdigit() else 1
        for k, m in enumerate(part.findall("measure")):
            m.set("number", str(start + k))
            if m.get("implicit") == "yes" and k > 0:
                m.attrib.pop("implicit")
    return index_map


def count_measures_rests(tree: etree._ElementTree) -> list[dict]:
    """Summary of multi-measure rests (for analysis display)."""
    out = []
    for part in tree.getroot().findall("part"):
        for m in part.findall("measure"):
            n = _count(m)
            if n:
                out.append({"part_id": part.get("id"), "measure": m.get("number"), "bars": n})
    return out


def has_multirests(tree: etree._ElementTree) -> bool:
    return tree.getroot().find(".//multiple-rest") is not None

