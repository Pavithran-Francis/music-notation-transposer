"""Range checking and explicit, logged octave adjustments.

Nothing here changes pitches silently: `check_range` only reports, and every
octave move is an explicit adjustment record that the caller stores (and can
undo) before calling `apply_adjustments`.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from core.instruments.database import Instrument
from core.musicxml.document import NoteEvent, get_pitch, is_tie_start, is_tie_stop, set_pitch, walk


@dataclass
class RangeIssue:
    note_id: str
    part_id: str
    measure: str
    measure_index: int
    beat: float
    pitch: str
    direction: str  # "high" | "low"
    severity: str  # "outside_typical" | "outside_extended"
    suggested_octaves: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _pitched(events: list[NoteEvent]) -> list[NoteEvent]:
    return [e for e in events if e.pitch is not None and not e.is_rest and e.id]


def _suggest(midi: float, lo: float, hi: float) -> int:
    for k in (1, -1, 2, -2, 3, -3):
        if lo <= midi + 12 * k <= hi:
            return k
    return 0


def check_range(tree: etree._ElementTree, target: Instrument) -> list[RangeIssue]:
    lo, hi = target.low.semitones, target.high.semitones
    elo, ehi = target.extended_low.semitones, target.extended_high.semitones
    issues: list[RangeIssue] = []
    for pw in walk(tree):
        for ev in _pitched(pw.notes):
            s = ev.pitch.semitones
            if lo <= s <= hi:
                continue
            direction = "high" if s > hi else "low"
            severity = "outside_extended" if (s < elo or s > ehi) else "outside_typical"
            issues.append(RangeIssue(
                note_id=ev.id, part_id=pw.part_id, measure=ev.measure_number,
                measure_index=ev.measure_index, beat=round(ev.beat(), 3), pitch=ev.pitch.name(),
                direction=direction, severity=severity, suggested_octaves=_suggest(s, lo, hi),
            ))
    return issues


def tie_chains(tree: etree._ElementTree) -> dict[str, list[str]]:
    """Map every note id to the ids of all notes in its tie chain (incl. itself)."""
    chains: dict[str, list[str]] = {}
    for pw in walk(tree):
        open_ties: dict[tuple, list[str]] = {}
        for ev in sorted(pw.notes, key=lambda e: (e.measure_index, e.onset, e.doc_order)):
            if ev.pitch is None or not ev.id:
                continue
            k = (ev.staff, ev.voice, ev.pitch.midi)
            chain = None
            if is_tie_stop(ev.element) and k in open_ties:
                chain = open_ties.pop(k)
                chain.append(ev.id)
            else:
                chain = [ev.id]
            if is_tie_start(ev.element):
                open_ties[k] = chain
            for nid in chain:
                chains[nid] = chain
    return chains


def auto_correct_range(tree: etree._ElementTree, target: Instrument) -> list[dict]:
    """Propose octave adjustments that bring notes into the typical range.

    Strategy (in order, stopping when everything fits):
      1. Move the whole part by whole octaves if that reduces out-of-range notes
         (keeps the musical line intact).
      2. Move the remaining individual notes (with their tie chains) by the
         smallest octave shift that fits.
    """
    lo, hi = target.low.semitones, target.high.semitones
    events = [e for pw in walk(tree) for e in _pitched(pw.notes)]
    if not events:
        return []

    def count_out(shift: int) -> int:
        return sum(1 for e in events if not (lo <= e.pitch.semitones + 12 * shift <= hi))

    base = count_out(0)
    if base == 0:
        return []
    best = min(range(-3, 4), key=lambda k: (count_out(k), abs(k)))
    adjustments: list[dict] = []
    global_shift = 0
    if best != 0 and count_out(best) < base:
        global_shift = best
        word = "up" if best > 0 else "down"
        n = abs(best)
        adjustments.append({
            "kind": "global",
            "octaves": best,
            "description": f"Moved the whole part {word} {n} octave{'s' if n > 1 else ''} "
                           f"({base} → {count_out(best)} notes outside the typical range).",
        })
    chains = tie_chains(tree)
    done: set[str] = set()
    for e in events:
        if e.id in done:
            continue
        s = e.pitch.semitones + 12 * global_shift
        if lo <= s <= hi:
            continue
        k = _suggest(s, lo, hi)
        if k == 0:
            continue
        chain = chains.get(e.id, [e.id])
        done.update(chain)
        new = e.pitch.shift_octaves(global_shift + k)
        adjustments.append({
            "kind": "note",
            "note_ids": chain,
            "octaves": k,
            "measure": e.measure_number,
            "beat": round(e.beat(), 3),
            "description": f"m. {e.measure_number}, beat {round(e.beat(), 2):g}: "
                           f"{e.pitch.shift_octaves(global_shift).name()} → {new.name()}",
        })
    return adjustments


def note_adjustments(tree: etree._ElementTree, note_ids: list[str], octaves: int) -> list[dict]:
    """User-requested octave move for specific notes (tie chains included)."""
    chains = tie_chains(tree)
    by_id = {e.id: e for pw in walk(tree) for e in pw.notes if e.id}
    out, done = [], set()
    for nid in note_ids:
        if nid in done or nid not in by_id or by_id[nid].pitch is None:
            continue
        chain = chains.get(nid, [nid])
        done.update(chain)
        e = by_id[nid]
        out.append({
            "kind": "note",
            "note_ids": chain,
            "octaves": octaves,
            "measure": e.measure_number,
            "beat": round(e.beat(), 3),
            "description": f"m. {e.measure_number}, beat {round(e.beat(), 2):g}: "
                           f"{e.pitch.name()} moved {'up' if octaves > 0 else 'down'} {abs(octaves)} octave(s)",
        })
    return out


def apply_adjustments(tree: etree._ElementTree, adjustments: list[dict]) -> dict[str, int]:
    """Apply octave adjustments in place. Returns net octave shift per note id."""
    shifts: dict[str, int] = {}
    all_ids = [n.get("id") for n in tree.getroot().iter("note") if n.get("id")]
    for adj in adjustments:
        if adj["kind"] == "global":
            for nid in all_ids:
                shifts[nid] = shifts.get(nid, 0) + adj["octaves"]
        elif adj["kind"] == "note":
            for nid in adj["note_ids"]:
                shifts[nid] = shifts.get(nid, 0) + adj["octaves"]
    if not shifts:
        return shifts
    for note in tree.getroot().iter("note"):
        k = shifts.get(note.get("id") or "", 0)
        if k:
            p = get_pitch(note)
            if p is not None:
                set_pitch(note, p.shift_octaves(k))
    return {k: v for k, v in shifts.items() if v}
