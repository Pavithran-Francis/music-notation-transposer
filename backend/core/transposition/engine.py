"""Instrument-to-instrument transposition on a MusicXML DOM.

Conceptual pipeline for every note:

    source written pitch --(source transposition)--> concert pitch
    concert pitch --(inverse target transposition)--> target written pitch

Both steps are diatonic intervals, so they compose into a single interval
(source.transposition - target.transposition). Applying that one interval
uniformly preserves every spelling relationship of the original (melodic
direction of chromatic notes, chord spellings, leading tones...). The only
spelling decision left is which enharmonic version of the interval to use,
chosen per key-signature region so the new key signature stays readable.

The process is split in two phases so that range adjustments can sit between
them without re-running the pitch transposition:

    transpose_pitches()  -> pitches, keys, chord symbols, instrument metadata
    finalize()           -> displayed accidentals and clefs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from lxml import etree

from core.instruments.database import Instrument
from core.metadata import display_name, write_header
from core.music.clefs import CLEFS
from core.music.pitch import Interval, Pitch, choose_spelling, key_alterations, key_name
from core.musicxml.document import (
    ATTRIBUTES_ORDER,
    NOTE_ORDER,
    copy_tree,
    get_pitch,
    insert_ordered,
    is_tie_stop,
    set_pitch,
    text_int,
    walk_part,
)


@dataclass
class TranspositionOptions:
    key_preference: str = "auto"  # auto | sharps | flats
    courtesy_accidentals: bool = True
    part_ids: list[str] | None = None  # None = all parts
    simplify_double_accidentals: bool = False
    auto_clef: bool = True


@dataclass
class TranspositionInfo:
    interval: Interval
    interval_name: str
    interval_description: str
    semitones: int
    key_changes: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    respelled_notes: int = 0

    def to_dict(self) -> dict:
        return {
            "interval": self.interval_name,
            "interval_description": self.interval_description,
            "semitones": self.semitones,
            "key_changes": self.key_changes,
            "warnings": self.warnings,
            "respelled_notes": self.respelled_notes,
        }


def written_interval(source: Instrument, target: Instrument) -> Interval:
    """Interval that maps source written pitch to target written pitch."""
    return source.interval - target.interval


def _selected_parts(root: etree._Element, part_ids: Iterable[str] | None) -> list[etree._Element]:
    parts = root.findall("part")
    if part_ids is None:
        return parts
    wanted = set(part_ids)
    return [p for p in parts if p.get("id") in wanted]


def _remove_unselected_parts(root: etree._Element, keep: list[etree._Element]) -> None:
    keep_ids = {p.get("id") for p in keep}
    for p in root.findall("part"):
        if p.get("id") not in keep_ids:
            root.remove(p)
    pl = root.find("part-list")
    if pl is not None:
        for sp in pl.findall("score-part"):
            if sp.get("id") not in keep_ids:
                pl.remove(sp)


def _transpose_harmony(h: etree._Element, interval: Interval) -> None:
    for tag in ("root", "bass"):
        el = h.find(tag)
        if el is None:
            continue
        step_el = el.find(f"{tag}-step")
        if step_el is None or not (step_el.text or "").strip():
            continue
        alter_el = el.find(f"{tag}-alter")
        alter = int(float(alter_el.text)) if alter_el is not None and alter_el.text else 0
        p = Pitch(step_el.text.strip().upper(), alter, 4).transpose(interval)
        if abs(p.alter) > 1:
            p = p.enharmonic_simplified()
        step_el.text = p.step
        if p.alter == 0:
            if alter_el is not None:
                el.remove(alter_el)
        else:
            if alter_el is None:
                alter_el = etree.Element(f"{tag}-alter")
                step_el.addnext(alter_el)
            alter_el.text = str(int(p.alter))


def _musicxml_transpose_element(interval: Interval) -> etree._Element | None:
    d, c = interval.diatonic, interval.chromatic
    if d == 0 and c == 0:
        return None
    sign = 1 if (d > 0 or (d == 0 and c > 0)) else -1
    octaves = sign * (abs(d) // 7)
    el = etree.Element("transpose")
    etree.SubElement(el, "diatonic").text = str(d - 7 * octaves)
    etree.SubElement(el, "chromatic").text = str(c - 12 * octaves)
    if octaves:
        etree.SubElement(el, "octave-change").text = str(octaves)
    return el


def _first_attributes(measure: etree._Element) -> etree._Element:
    """Return (creating if needed) the <attributes> at the very start of a measure."""
    insert_at = 0
    for i, child in enumerate(measure):
        if child.tag == "attributes":
            return child
        if child.tag in ("print",) or (child.tag == "barline" and child.get("location") == "left"):
            insert_at = i + 1
            continue
        break
    attrs = etree.Element("attributes")
    measure.insert(insert_at, attrs)
    return attrs


def _update_part_metadata(root: etree._Element, part: etree._Element, target: Instrument) -> None:
    pid = part.get("id")
    sp = root.find(f"part-list/score-part[@id='{pid}']")
    if sp is not None:
        name = sp.find("part-name")
        if name is None:
            name = etree.SubElement(sp, "part-name")
        name.text = display_name(target.name)
        for tag in ("part-name-display", "part-abbreviation-display"):
            for el in sp.findall(tag):
                sp.remove(el)
        abbr = sp.find("part-abbreviation")
        if target.abbreviation:
            if abbr is None:
                abbr = etree.Element("part-abbreviation")
                name.addnext(abbr)
            abbr.text = target.abbreviation
        for si in sp.findall("score-instrument"):
            iname = si.find("instrument-name")
            if iname is not None:
                iname.text = display_name(target.name)
            for el in si.findall("instrument-sound"):
                si.remove(el)
        for mi in sp.findall("midi-instrument"):
            prog = mi.find("midi-program")
            if prog is not None:
                prog.text = str(target.midi_program)

    # Replace transposition info in the part body.
    for attrs in part.iter("attributes"):
        for t in attrs.findall("transpose"):
            attrs.remove(t)
    first_measure = part.find("measure")
    if first_measure is not None:
        tr = _musicxml_transpose_element(target.interval)
        if tr is not None:
            insert_ordered(_first_attributes(first_measure), tr, ATTRIBUTES_ORDER)


def _ensure_initial_key(part: etree._Element) -> None:
    """Scores without a key signature are in C (fifths 0); make that explicit so the
    transposed part receives a real key signature instead of accidentals on every note."""
    first = part.find("measure")
    if first is None:
        return
    for el in first:
        if el.tag == "note":
            break
        if el.tag == "attributes" and el.find("key") is not None:
            return
    key = etree.Element("key")
    etree.SubElement(key, "fifths").text = "0"
    insert_ordered(_first_attributes(first), key, ATTRIBUTES_ORDER)


def transpose_pitches(
    tree: etree._ElementTree,
    source: Instrument,
    target: Instrument,
    options: TranspositionOptions | None = None,
) -> tuple[etree._ElementTree, TranspositionInfo]:
    """Phase 1: transpose pitches, keys and chord symbols; update instrument data.

    Returns a new tree; the input is never modified.
    """
    options = options or TranspositionOptions()
    out = copy_tree(tree)
    root = out.getroot()
    base = written_interval(source, target)
    info = TranspositionInfo(
        interval=base,
        interval_name=base.quality_name(),
        interval_description=base.describe(),
        semitones=base.chromatic,
    )
    parts = _selected_parts(root, options.part_ids)
    if not parts:
        raise ValueError("No parts selected for transposition.")
    _remove_unselected_parts(root, parts)

    seen_key_measures: set[tuple] = set()
    warned_ornament = False
    warned_unpitched = False
    for part in parts:
        _ensure_initial_key(part)
        current = choose_spelling(base, 0, options.key_preference)
        for m_idx, measure in enumerate(part.findall("measure")):
            for el in list(measure.iter("key", "note", "harmony")):
                tag = el.tag
                if tag == "key":
                    fifths_el = el.find("fifths")
                    if fifths_el is None:
                        if not any(w.startswith("Non-traditional") for w in info.warnings):
                            info.warnings.append(
                                "Non-traditional key signatures were kept unchanged; notes are still transposed."
                            )
                        continue
                    old = text_int(fifths_el)
                    current = choose_spelling(base, old, options.key_preference)
                    new = old + current.fifths_delta
                    fifths_el.text = str(new)
                    for cancel in el.findall("cancel"):
                        el.remove(cancel)
                    mode = (el.findtext("mode") or "major").strip()
                    mkey = (part.get("id"), measure.get("number", str(m_idx + 1)))
                    if mkey not in seen_key_measures:
                        seen_key_measures.add(mkey)
                        info.key_changes.append({
                            "part_id": part.get("id"),
                            "measure": measure.get("number", str(m_idx + 1)),
                            "from": key_name(old, mode),
                            "to": key_name(new, mode),
                            "from_fifths": old,
                            "to_fifths": new,
                        })
                elif tag == "note":
                    p = get_pitch(el)
                    if p is not None:
                        q = p.transpose(current)
                        if abs(q.alter) >= 3 or (options.simplify_double_accidentals and abs(q.alter) == 2):
                            q = q.enharmonic_simplified()
                            info.respelled_notes += 1
                        set_pitch(el, q)
                    elif el.find("unpitched") is not None and not warned_unpitched:
                        info.warnings.append("Unpitched (percussion) notes were left unchanged.")
                        warned_unpitched = True
                    rest = el.find("rest")
                    if rest is not None:
                        # Rest vertical positions refer to the old clef/pitch; let the engraver place them.
                        for t in ("display-step", "display-octave"):
                            for d in rest.findall(t):
                                rest.remove(d)
                    if el.find(".//accidental-mark") is not None and not warned_ornament:
                        info.warnings.append(
                            "Some ornaments carry their own accidentals (e.g. trills); these were kept as in the "
                            "original and should be checked."
                        )
                        warned_ornament = True
                elif tag == "harmony":
                    _transpose_harmony(el, current)
        _update_part_metadata(root, part, target)
    write_header(out, display_name(target.name))
    return out, info


# ---------------------------------------------------------------------------
# Phase 2: accidentals and clefs
# ---------------------------------------------------------------------------

_ACC_TEXT = {2: "double-sharp", 1: "sharp", 0: "natural", -1: "flat", -2: "flat-flat"}


def _set_accidental(note: etree._Element, alter: int, cautionary: bool, keep_attrs: dict | None = None) -> None:
    acc = etree.Element("accidental")
    acc.text = _ACC_TEXT.get(alter, "natural")
    if keep_attrs:
        for k, v in keep_attrs.items():
            acc.set(k, v)
    elif cautionary:
        acc.set("cautionary", "yes")
    insert_ordered(note, acc, NOTE_ORDER)


def recompute_accidentals(tree: etree._ElementTree, courtesy: bool = True) -> None:
    """Rewrite <accidental> elements from scratch for the current pitches and keys.

    Standard rules: an accidental lasts until the end of the measure for the
    same staff position (step + octave) on the same staff; tied continuation
    notes do not repeat it. Courtesy accidentals present in the source are kept
    (as courtesy accidentals); optionally a courtesy accidental is added in the
    measure following a chromatic alteration.
    """
    root = tree.getroot()
    for p_idx, part in enumerate(root.findall("part")):
        pw = walk_part(part, p_idx)
        by_measure: dict[int, list] = {}
        for ev in pw.notes:
            by_measure.setdefault(ev.measure_index, []).append(ev)
        prev_altered: dict[int, dict[tuple[str, int], int]] = {}
        for m_idx in range(len(pw.measures)):
            events = sorted(by_measure.get(m_idx, []), key=lambda e: (e.staff, e.onset, e.doc_order))
            state: dict[int, dict[tuple[str, int], int]] = {}
            courtesy_done: set[tuple[int, str, int]] = set()
            for ev in events:
                note = ev.element
                p = get_pitch(note)
                if p is None:
                    continue
                old_acc = note.find("accidental")
                if p.alter != int(p.alter):
                    continue  # microtonal: leave the source accidental untouched
                keep_attrs = None
                if old_acc is not None and any(
                    old_acc.get(a) == "yes" for a in ("cautionary", "parentheses", "editorial", "bracket")
                ):
                    keep_attrs = {
                        a: old_acc.get(a) for a in ("cautionary", "parentheses", "editorial", "bracket")
                        if old_acc.get(a)
                    }
                if old_acc is not None:
                    note.remove(old_acc)
                alter = int(p.alter)
                staff_state = state.setdefault(ev.staff, {})
                key_alter = key_alterations(ev.key.fifths).get(p.step, 0)
                pos = (p.step, p.octave)
                current = staff_state.get(pos, key_alter)
                if is_tie_stop(note) and (ev.onset == 0 or current == alter):
                    # Continuation of a tied note: never re-displays its accidental.
                    if ev.onset != 0:
                        staff_state[pos] = alter
                    continue
                if alter != current:
                    _set_accidental(note, alter, False)
                    staff_state[pos] = alter
                    continue
                prev = prev_altered.get(ev.staff, {}).get(pos)
                cid = (ev.staff, p.step, p.octave)
                if keep_attrs:
                    _set_accidental(note, alter, True, keep_attrs)
                elif courtesy and prev is not None and prev != alter and cid not in courtesy_done:
                    _set_accidental(note, alter, True)
                courtesy_done.add(cid)
            prev_altered = {}
            for staff, st in state.items():
                for pos, alt in st.items():
                    prev_altered.setdefault(staff, {})[pos] = alt


def choose_clefs(tree: etree._ElementTree, target: Instrument) -> dict[str, dict[int, list[str]]]:
    """Choose a clef per staff per measure minimising ledger lines.

    Dynamic programming over measures: cost = ledger lines of all notes in the
    measure written in that clef, + a small bias against non-primary clefs,
    + a penalty for every clef change. This yields stable, idiomatic clef
    usage (e.g. a cello part moving to tenor clef only for sustained high
    passages).
    """
    SWITCH_PENALTY = 6.0
    NON_PRIMARY_BIAS = 1.0
    root = tree.getroot()
    plan: dict[str, dict[int, list[str]]] = {}
    for p_idx, part in enumerate(root.findall("part")):
        pw = walk_part(part, p_idx)
        n_measures = len(pw.measures)
        staves = max((m.staves for m in pw.measures), default=1)
        notes_by: dict[tuple[int, int], list[int]] = {}
        for ev in pw.notes:
            if ev.pitch is not None and not ev.is_rest:
                notes_by.setdefault((ev.staff, ev.measure_index), []).append(ev.pitch.diatonic)
        part_plan: dict[int, list[str]] = {}
        for staff in range(1, staves + 1):
            primary = target.primary_clef_for_staff(staff - 1)
            cands = list(target.clefs)
            if staff > target.staves:
                for extra in ("treble", "bass"):
                    if extra not in cands:
                        cands.append(extra)
                if staff == 2 and "bass" in cands:
                    primary = "bass"
            if primary not in cands:
                cands.insert(0, primary)
            # Cost table
            inf = float("inf")
            dp = [[inf] * len(cands) for _ in range(n_measures)]
            back = [[0] * len(cands) for _ in range(n_measures)]
            for m in range(n_measures):
                pitches = notes_by.get((staff, m), [])
                for ci, cid in enumerate(cands):
                    clef = CLEFS[cid]
                    # Triangular cost: 1 ledger = 1, 2 = 3, 3 = 6, 4 = 10 ... far notes weigh much more.
                    cost = sum((L * (L + 1)) // 2 for L in (clef.ledger_lines(d) for d in pitches))
                    if cid != primary and pitches:
                        cost += NON_PRIMARY_BIAS
                    if m == 0:
                        dp[m][ci] = cost + (0 if cid == primary else NON_PRIMARY_BIAS * 0.5)
                        continue
                    best, arg = inf, 0
                    for pj in range(len(cands)):
                        v = dp[m - 1][pj] + (SWITCH_PENALTY if pj != ci else 0)
                        if v < best:
                            best, arg = v, pj
                    dp[m][ci] = best + cost
                    back[m][ci] = arg
            if n_measures == 0:
                part_plan[staff] = []
                continue
            ci = min(range(len(cands)), key=lambda i: dp[-1][i])
            seq = [0] * n_measures
            for m in range(n_measures - 1, -1, -1):
                seq[m] = ci
                ci = back[m][ci]
            part_plan[staff] = [cands[i] for i in seq]
        plan[part.get("id", str(p_idx))] = part_plan
    return plan


def apply_clefs(tree: etree._ElementTree, plan: dict[str, dict[int, list[str]]]) -> list[dict]:
    """Replace all clefs in the parts with the planned ones. Returns clef changes."""
    root = tree.getroot()
    changes = []
    for part in root.findall("part"):
        pid = part.get("id", "")
        part_plan = plan.get(pid)
        if not part_plan:
            continue
        multi = len(part_plan) > 1
        for attrs in list(part.iter("attributes")):
            for c in attrs.findall("clef"):
                attrs.remove(c)
            if len(attrs) == 0:
                attrs.getparent().remove(attrs)
        measures = part.findall("measure")
        for staff, seq in part_plan.items():
            prev = None
            for m_idx, clef_id in enumerate(seq):
                if clef_id == prev:
                    continue
                clef = CLEFS[clef_id]
                el = etree.Element("clef")
                if multi:
                    el.set("number", str(staff))
                etree.SubElement(el, "sign").text = clef.sign
                etree.SubElement(el, "line").text = str(clef.line)
                if clef.octave_change:
                    etree.SubElement(el, "clef-octave-change").text = str(clef.octave_change)
                attrs = _first_attributes(measures[m_idx])
                # keep clefs ordered by staff number
                existing = attrs.findall("clef")
                if existing:
                    before = [c for c in existing if int(c.get("number", "1")) < staff]
                    if before:
                        before[-1].addnext(el)
                    else:
                        existing[0].addprevious(el)
                else:
                    insert_ordered(attrs, el, ATTRIBUTES_ORDER)
                changes.append({
                    "part_id": pid,
                    "measure": measures[m_idx].get("number", str(m_idx + 1)),
                    "staff": staff,
                    "clef": clef_id,
                    "label": clef.label,
                })
                prev = clef_id
    return changes


def finalize(
    tree: etree._ElementTree,
    target: Instrument,
    options: TranspositionOptions | None = None,
) -> tuple[etree._ElementTree, list[dict]]:
    """Phase 2: recompute accidentals and clefs on a copy of `tree`."""
    options = options or TranspositionOptions()
    out = copy_tree(tree)
    recompute_accidentals(out, courtesy=options.courtesy_accidentals)
    clef_changes: list[dict] = []
    if options.auto_clef:
        clef_changes = apply_clefs(out, choose_clefs(out, target))
    return out, clef_changes


def transpose_score(
    tree: etree._ElementTree,
    source: Instrument,
    target: Instrument,
    options: TranspositionOptions | None = None,
) -> tuple[etree._ElementTree, TranspositionInfo, list[dict]]:
    """Convenience: both phases with no range adjustments."""
    options = options or TranspositionOptions()
    raw, info = transpose_pitches(tree, source, target, options)
    final, clefs = finalize(raw, target, options)
    return final, info, clefs
