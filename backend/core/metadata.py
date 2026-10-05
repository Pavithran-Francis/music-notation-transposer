"""Score metadata: title, composer, instrument name and page header credits."""

from __future__ import annotations

import re

from lxml import etree

DEFAULT_SCALING = ("6.99912", "40")  # MuseScore's default staff size, in mm per 40 tenths
A4 = {"page-height": 1696.94, "page-width": 1200.48, "margin": 85.7143}


def display_name(name: str) -> str:
    """'Trumpet in Bb' -> 'Trumpet in B♭', 'Horn in F#' -> 'Horn in F♯'."""
    name = re.sub(r"\b([A-G])b\b", "\\1♭", name)
    return re.sub(r"\b([A-G])#", "\\1♯", name)


def _credits(root: etree._Element) -> list[tuple[str | None, etree._Element]]:
    out = []
    for c in root.findall("credit"):
        ctype = c.findtext("credit-type")
        for w in c.findall("credit-words"):
            if (w.text or "").strip():
                out.append((ctype, w))
    return out


def read_metadata(tree: etree._ElementTree) -> dict:
    root = tree.getroot()
    title = (root.findtext("work/work-title") or root.findtext("movement-title") or "").strip()
    composer = ""
    for cr in root.findall("identification/creator"):
        if cr.get("type") == "composer" and (cr.text or "").strip():
            composer = cr.text.strip()
    credits = _credits(root)
    if not title:
        typed = [w for t, w in credits if t == "title"]
        if typed:
            title = typed[0].text.strip()
        elif credits:  # largest text near the top of page 1 is the title
            def size(w: etree._Element) -> float:
                try:
                    return float(w.get("font-size", "0"))
                except ValueError:
                    return 0.0
            biggest = max((w for t, w in credits if t is None), key=size, default=None)
            if biggest is not None and size(biggest) >= 16:
                title = biggest.text.strip()
    if not composer:
        typed = [w for t, w in credits if t == "composer"]
        if typed:
            composer = typed[0].text.strip()
    return {"title": title, "composer": composer}


def normalize(tree: etree._ElementTree) -> None:
    """Make title/composer explicit and drop engine details that leak local paths."""
    root = tree.getroot()
    meta = read_metadata(tree)
    set_metadata(tree, meta["title"], meta["composer"])
    ident = root.find("identification")
    if ident is not None:
        for el in ident.findall("source"):
            ident.remove(el)
        misc = ident.find("miscellaneous")
        if misc is not None:
            for f in misc.findall("miscellaneous-field"):
                if (f.get("name") or "").startswith("source"):
                    misc.remove(f)
            if len(misc) == 0:
                ident.remove(misc)


def _ensure(root: etree._Element, tag: str, before: list[str]) -> etree._Element:
    el = root.find(tag)
    if el is not None:
        return el
    el = etree.Element(tag)
    for i, child in enumerate(root):
        if child.tag in before:
            root.insert(i, el)
            return el
    root.append(el)
    return el


_HEADER_ORDER = ["work", "movement-number", "movement-title", "identification", "defaults", "credit", "part-list"]


def set_metadata(tree: etree._ElementTree, title: str | None, composer: str | None) -> None:
    root = tree.getroot()
    if title is not None:
        title = title.strip()
        work = _ensure(root, "work", _HEADER_ORDER[1:])
        wt = work.find("work-title")
        if wt is None:
            wt = etree.SubElement(work, "work-title")
        wt.text = title
        mt = root.find("movement-title")
        if mt is not None:
            mt.text = title
        if not title:
            root.remove(work)
    if composer is not None:
        composer = composer.strip()
        ident = _ensure(root, "identification", _HEADER_ORDER[4:])
        creators = [c for c in ident.findall("creator") if c.get("type") == "composer"]
        if composer:
            if creators:
                creators[0].text = composer
            else:
                c = etree.Element("creator", type="composer")
                c.text = composer
                ident.insert(0, c)
        else:
            for c in creators:
                ident.remove(c)


def write_header(tree: etree._ElementTree, instrument: str | None) -> None:
    """Replace page credits with a clean header: title, composer, instrument name.

    Page size and staff scaling inherited from a scan are replaced by standard
    A4 values so the engraver lays the part out like a normal edition.
    """
    root = tree.getroot()
    meta = read_metadata(tree)
    for c in root.findall("credit"):
        root.remove(c)
    defaults = root.find("defaults")
    if defaults is not None:
        root.remove(defaults)
    defaults = etree.Element("defaults")
    sc = etree.SubElement(defaults, "scaling")
    etree.SubElement(sc, "millimeters").text = DEFAULT_SCALING[0]
    etree.SubElement(sc, "tenths").text = DEFAULT_SCALING[1]
    pl = etree.SubElement(defaults, "page-layout")
    etree.SubElement(pl, "page-height").text = f"{A4['page-height']:g}"
    etree.SubElement(pl, "page-width").text = f"{A4['page-width']:g}"
    pm = etree.SubElement(pl, "page-margins", type="both")
    for side in ("left", "right", "top", "bottom"):
        etree.SubElement(pm, f"{side}-margin").text = f"{A4['margin']:g}"
    anchor = root.find("part-list")
    anchor.addprevious(defaults)

    # A single-part score is an instrumental part: its name goes in the header, not
    # beside the staff (as in printed parts).
    score_parts = root.findall("part-list/score-part")
    if instrument and len(score_parts) == 1:
        for tag in ("part-name", "part-abbreviation"):
            el = score_parts[0].find(tag)
            if el is not None:
                el.set("print-object", "no")

    h, w, m = A4["page-height"], A4["page-width"], A4["margin"]
    entries = []
    if meta["title"]:
        entries.append(("title", meta["title"], w / 2, h - m - 30, "center", "top", 22))
    if meta["composer"]:
        entries.append(("composer", meta["composer"], w - m, h - m - 120, "right", "bottom", 10))
    if instrument:
        entries.append(("part name", instrument, m, h - m - 120, "left", "bottom", 12))
    for ctype, text, x, y, justify, valign, size in entries:
        credit = etree.Element("credit", page="1")
        etree.SubElement(credit, "credit-type").text = ctype
        cw = etree.SubElement(credit, "credit-words", {
            "default-x": f"{x:.2f}", "default-y": f"{y:.2f}", "justify": justify, "valign": valign,
            "font-size": str(size),
        })
        cw.text = text
        anchor.addprevious(credit)


def strip_scan_layout(tree: etree._ElementTree) -> None:
    """Remove layout measured on a scan (spacing, line and page breaks).

    The engraved output uses standard page and staff sizes, and multi-measure
    rests change measure widths, so the scan's breaks would force awkward lines;
    the engraver lays the part out afresh instead.
    """
    for pr in list(tree.getroot().iter("print")):
        for tag in ("system-layout", "staff-layout", "page-layout", "measure-layout"):
            for el in pr.findall(tag):
                pr.remove(el)
        for attr in ("new-system", "new-page", "blank-page", "page-number"):
            pr.attrib.pop(attr, None)
        if len(pr) == 0 and not pr.attrib:
            pr.getparent().remove(pr)
    for m in tree.getroot().iter("measure"):
        m.attrib.pop("width", None)
