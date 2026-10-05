"""Combine two OMR readings of the same single-staff score.

The primary engine (Audiveris) recognizes text, dynamics, hairpins, slurs and
rehearsal marks well, but sometimes misses symbols (whole notes, mid-system
time signatures) and then *drops* notes to make measures fit. The secondary
engine (homr) is very accurate on notes and rhythms but ignores most other
markings and only reliably knows the time-signature denominator.

Merging rules, per aligned measure:

* Time signature: keep the primary's when its own content fills it. Otherwise,
  when the secondary's content is longer, infer the signature from that
  content (e.g. five quarter notes with a /4 denominator → 5/4). Runs of
  measures where both engines agree on a content length that contradicts the
  declared signature are corrected the same way.
* Key signature: an explicit key change seen by either engine beats the other
  engine's silence (missed detections are far more common than invented ones);
  if both report different keys, the key under which the notes are most
  diatonic wins, ties going to the primary.
* Notes: identical readings are accepted with high confidence. Otherwise the
  reading that exactly fills the measure wins; if both do, the one with fewer
  notes outside the key wins (ties → primary). Every such measure is reported
  so it can be shown for review.

The primary score is the base: its directions, dynamics, text, barlines and
layout are kept, and only the note content of measures where the secondary
reading won is replaced.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from fractions import Fraction
from math import lcm

from lxml import etree

from core.music.pitch import key_alterations
from core.musicxml.document import ATTRIBUTES_ORDER, MeasureInfo, PartWalk, insert_ordered, text_int, walk

CONTENT_TAGS = {"note", "backup", "forward"}


@dataclass
class MeasureDecision:
    index: int
    number: str
    source: str  # "agree" | "primary" | "secondary" | "primary-only"
    reason: str
    time_changed: bool = False
    key_changed: bool = False
    out_index: int | None = None  # index of this measure in the merged score (None if removed)

    # Resolutions backed by hard evidence (a reading that alone fills the measure, notes one
    # engine dropped, a measure one engine missed, an artifact) are trusted; the rest are
    # judgement calls a person should glance at.
    WEAK_REASONS = ("clef", "fits the key better", "primary reading kept", "neither reading")

    @property
    def weak(self) -> bool:
        return self.source in ("primary", "secondary") and any(w in self.reason for w in self.WEAK_REASONS)

    @property
    def disputed(self) -> bool:
        return self.source in ("primary", "secondary", "removed") or self.time_changed or self.key_changed


@dataclass
class MergeReport:
    applied: bool
    reason: str = ""
    measures: list[MeasureDecision] = field(default_factory=list)
    secondary_only_measures: int = 0

    def summary(self) -> str:
        if not self.applied:
            return f"Second recognition engine not used: {self.reason}"
        agree = sum(1 for m in self.measures if m.source == "agree" and not m.disputed)
        disputed = [m for m in self.measures if m.disputed]
        live = [m for m in self.measures if m.source != "removed"]
        s = f"Two recognition engines agreed on {agree} of {len(live)} measures"
        fixed = [m for m in disputed if not m.weak]
        weak = [m for m in disputed if m.weak]
        if fixed:
            s += f"; {len(fixed)} were corrected automatically"
        if weak:
            s += f"; {len(weak)} need a quick check"
        removed = len(self.measures) - len(live)
        if removed:
            s += f"; {removed} recognition artifact(s) removed"
        return s + "."

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "reason": self.reason,
            "summary": self.summary(),
            "secondary_only_measures": self.secondary_only_measures,
            "measures": [m.__dict__ | {"disputed": m.disputed, "weak": m.weak} for m in self.measures],
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def rescale_divisions(tree: etree._ElementTree, target: int) -> None:
    """Express all durations with `target` divisions per quarter (must be a multiple)."""
    for part in tree.getroot().findall("part"):
        current = 1
        for measure in part.findall("measure"):
            for el in measure.iter():
                if el.tag == "divisions":
                    current = max(1, text_int(el, 1))
                    el.text = str(target)
            factor = Fraction(target, current)
            for el in measure.iter("duration", "offset"):
                try:
                    el.text = str(int(Fraction(el.text.strip()) * factor))
                except (ValueError, AttributeError):
                    pass


def _all_divisions(tree: etree._ElementTree) -> list[int]:
    return [max(1, text_int(d, 1)) for d in tree.getroot().iter("divisions")] or [1]


def _length_q(m: MeasureInfo) -> Fraction:
    if not m.voice_durations:
        return Fraction(0)
    return Fraction(max(m.voice_durations.values()), m.divisions)


def _sig_len(sig: tuple[int, int] | None) -> Fraction | None:
    return None if sig is None else Fraction(sig[0] * 4, sig[1])


def _events(pw: PartWalk) -> dict[int, list[tuple]]:
    out: dict[int, list[tuple]] = {}
    for e in pw.notes:
        if e.is_grace:
            continue
        name = (e.pitch.step, int(e.pitch.alter), e.pitch.octave) if e.pitch else ("r",)
        out.setdefault(e.measure_index, []).append((Fraction(e.onset, e.divisions), name, Fraction(e.duration, e.divisions)))
    return {k: sorted(v) for k, v in out.items()}


def _out_of_key(events: list[tuple], fifths: int) -> int:
    alters = key_alterations(fifths)
    return sum(1 for _, name, _ in events if len(name) == 3 and name[1] != alters[name[0]])


def _is_strict_subsequence(short: list[tuple], long: list[tuple]) -> bool:
    """True when `short`'s pitches appear in order inside `long`, which has more notes:
    the typical footprint of a primary engine that dropped notes to fit a wrong meter."""
    a = [e[1] for e in short]
    b = [e[1] for e in long]
    if len(a) >= len(b):
        return False
    it = iter(b)
    return all(x in it for x in a)


def _explicit_time(measure: etree._Element) -> tuple[int, int] | None:
    for t in measure.iter("time"):
        try:
            beats = sum(int(x) for x in (t.findtext("beats") or "").split("+"))
            return beats, int(t.findtext("beat-type") or 4)
        except ValueError:
            return None
    return None


def _sig_from(length_q: Fraction, den: int) -> tuple[int, int] | None:
    """Time signature with denominator `den` whose measure lasts `length_q` quarters."""
    num = length_q * den / 4
    return (int(num), den) if num.denominator == 1 and 1 <= num <= 32 else None


def _explicit_key(measure: etree._Element) -> int | None:
    for k in measure.iter("key"):
        f = k.find("fifths")
        if f is not None:
            return text_int(f)
    return None


def _align(a: list[list], b: list[list]) -> list[tuple[int | None, int | None]]:
    """Needleman–Wunsch alignment of measures by note-sequence similarity."""
    n, m = len(a), len(b)
    if n == m and all(bool(a[i]) == bool(b[i]) for i in range(n)):
        return [(i, i) for i in range(n)]
    gap = -0.6

    def sim(i: int, j: int) -> float:
        # Compare letter + octave only, so a misread key signature doesn't break alignment.
        x = [e[1][::2] for e in a[i]]
        y = [e[1][::2] for e in b[j]]
        if not x and not y:
            return 0.0  # empty measures are OMR artifacts: no evidence either way
        if not x or not y:
            return -0.3
        ratio = SequenceMatcher(a=x, b=y, autojunk=False).ratio()
        # Interval contour is immune to clef misreads (everything shifted by a constant).
        dx = [p[1] * 7 + "CDEFGAB".index(p[0]) for p in x if p[0] != "r"]
        dy = [p[1] * 7 + "CDEFGAB".index(p[0]) for p in y if p[0] != "r"]
        cx = [b - a for a, b in zip(dx, dx[1:])]
        cy = [b - a for a, b in zip(dy, dy[1:])]
        if len(cx) >= 2 and len(cy) >= 2:
            ratio = max(ratio, 0.9 * SequenceMatcher(a=cx, b=cy, autojunk=False).ratio())
        return 2 * ratio - 1

    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap
    for j in range(1, m + 1):
        dp[0][j] = j * gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(dp[i - 1][j - 1] + sim(i - 1, j - 1), dp[i - 1][j] + gap, dp[i][j - 1] + gap)
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(dp[i][j] - (dp[i - 1][j - 1] + sim(i - 1, j - 1))) < 1e-9:
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and abs(dp[i][j] - (dp[i - 1][j] + gap)) < 1e-9:
            pairs.append((i - 1, None)); i -= 1
        else:
            pairs.append((None, j - 1)); j -= 1
    return pairs[::-1]


def _onsets(measure: etree._Element, divisions: int) -> list[tuple[etree._Element, Fraction]]:
    """Every child of a measure with its onset (in divisions)."""
    pos = Fraction(0)
    last = Fraction(0)
    out = []
    for child in measure:
        if child.tag == "note":
            if child.find("chord") is not None:
                out.append((child, last))
                continue
            out.append((child, pos))
            last = pos
            if child.find("grace") is None:
                pos += text_int(child.find("duration"), 0)
        elif child.tag == "backup":
            out.append((child, pos))
            pos = max(Fraction(0), pos - text_int(child.find("duration"), 0))
        elif child.tag == "forward":
            out.append((child, pos))
            pos += text_int(child.find("duration"), 0)
        else:
            off = child.find("offset")
            out.append((child, pos + (text_int(off, 0) if off is not None else 0)))
    return out


def _replace_content(target: etree._Element, source: etree._Element, divisions: int) -> None:
    """Swap the notes of `target` for those of `source`, keeping target's other elements in time order."""
    keep = [(el, t) for el, t in _onsets(target, divisions) if el.tag not in CONTENT_TAGS]
    new_notes = [(copy.deepcopy(el), t) for el, t in _onsets(source, divisions) if el.tag in CONTENT_TAGS]
    for el in list(target):
        target.remove(el)
    head = [el for el, t in keep if el.tag in ("attributes", "print") or (el.tag == "barline" and el.get("location") == "left")]
    tail = [el for el, t in keep if el.tag == "barline" and el.get("location") != "left"]
    middle = [(el, t) for el, t in keep if el not in head and el not in tail]
    for el in head:
        target.append(el)
    mi = 0
    for note, t in new_notes:
        while mi < len(middle) and middle[mi][1] <= t:
            target.append(middle[mi][0]); mi += 1
        note.attrib.pop("id", None)
        target.append(note)
    for el, _ in middle[mi:]:
        target.append(el)
    for el in tail:
        target.append(el)


def _set_attr(measure: etree._Element, tag: str, value_el: etree._Element | None) -> None:
    """Replace (or remove, when value_el is None) the key/time at the start of a measure."""
    attrs = None
    for child in measure:
        if child.tag == "attributes":
            attrs = child
            break
        if child.tag in CONTENT_TAGS:
            break
    if attrs is not None:
        for el in attrs.findall(tag):
            attrs.remove(el)
    if value_el is None:
        return
    if attrs is None:
        attrs = etree.Element("attributes")
        idx = 0
        for i, child in enumerate(measure):
            if child.tag == "print" or (child.tag == "barline" and child.get("location") == "left"):
                idx = i + 1
            else:
                break
        measure.insert(idx, attrs)
    insert_ordered(attrs, value_el, ATTRIBUTES_ORDER)


def _time_el(sig: tuple[int, int]) -> etree._Element:
    t = etree.Element("time")
    etree.SubElement(t, "beats").text = str(sig[0])
    etree.SubElement(t, "beat-type").text = str(sig[1])
    return t


def _key_el(fifths: int) -> etree._Element:
    k = etree.Element("key")
    etree.SubElement(k, "fifths").text = str(fifths)
    return k


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


def merge_readings(primary: etree._ElementTree, secondary: etree._ElementTree | None) -> tuple[etree._ElementTree, MergeReport]:
    out = copy.deepcopy(primary)
    if secondary is None:
        return out, MergeReport(False, "no second reading available")
    sec = copy.deepcopy(secondary)
    if len(out.getroot().findall("part")) != 1 or len(sec.getroot().findall("part")) != 1:
        return out, MergeReport(False, "only single-part scores are merged")
    if max((m.staves for m in walk(out)[0].measures), default=1) > 1:
        return out, MergeReport(False, "multi-staff parts (e.g. piano) are recognized by the primary engine only")

    common = lcm(*_all_divisions(out), *_all_divisions(sec))
    rescale_divisions(out, common)
    rescale_divisions(sec, common)
    A, H = walk(out)[0], walk(sec)[0]
    ev_a, ev_h = _events(A), _events(H)
    a_meas = [ev_a.get(i, []) for i in range(len(A.measures))]
    h_meas = [ev_h.get(i, []) for i in range(len(H.measures))]
    slots = _align(a_meas, h_meas)
    if sum(1 for a, h in slots if a is not None and h is not None) < 0.6 * max(1, len(A.measures)):
        return out, MergeReport(False, "the two readings could not be aligned reliably")

    part = out.getroot().find("part")
    a_elems = part.findall("measure")
    h_elems = sec.getroot().find("part").findall("measure")
    n = len(slots)

    def len_a(k: int) -> Fraction:
        ai = slots[k][0]
        return _length_q(A.measures[ai]) if ai is not None else Fraction(0)

    def len_h(k: int) -> Fraction:
        hi = slots[k][1]
        return _length_q(H.measures[hi]) if hi is not None else Fraction(0)

    def ea(k: int) -> list:
        return a_meas[slots[k][0]] if slots[k][0] is not None else []

    def eh(k: int) -> list:
        return h_meas[slots[k][1]] if slots[k][1] is not None else []

    def explicit_change(k: int) -> bool:
        ai, hi = slots[k]
        return any(x is not None for x in (
            _explicit_key(a_elems[ai]) if ai is not None else None,
            _explicit_time(a_elems[ai]) if ai is not None else None,
            _explicit_key(h_elems[hi]) if hi is not None else None,
            _explicit_time(h_elems[hi]) if hi is not None else None,
        ))

    # ---- phantom measures ----------------------------------------------------
    # Printed measures always contain notes or rests. Empty measures, and short
    # disagreeing "measures" right before a key/time change (a courtesy signature at
    # the end of a line read as music), are recognition artifacts.
    phantom: set[int] = set()
    # Line (system) boundaries of the primary reading: courtesy signatures sit at the end
    # of a line, and line headers (clef/key/time) are sometimes read as notes.
    starts = {0} | {i for i, m in enumerate(a_elems)
                    if any(pr.get("new-system") == "yes" or pr.get("new-page") == "yes" for pr in m.iter("print"))}
    boundary = starts | {i - 1 for i in starts if i > 0}

    def onsets(events: list) -> int:
        return len({e[0] for e in events})

    def has_sig(k: int) -> bool:
        ai, hi = slots[k]
        return any(x is not None for x in (
            _explicit_key(a_elems[ai]) if ai is not None else None,
            _explicit_time(a_elems[ai]) if ai is not None else None,
            _explicit_key(h_elems[hi]) if hi is not None else None,
            _explicit_time(h_elems[hi]) if hi is not None else None,
        ))

    prev_L: Fraction | None = None
    for k, (ai, hi) in enumerate(slots):
        if ai is not None and A.measures[ai].time:
            prev_L = _sig_len(A.measures[ai].time)
        L = prev_L or Fraction(4)
        nxt = k + 1 < n and explicit_change(k + 1)
        a_short = len_a(k) < L and onsets(ea(k)) <= 2
        h_short = len_h(k) < L and onsets(eh(k)) <= 2
        if ai is not None and hi is None:
            if not ea(k) or (a_short and nxt):
                phantom.add(k)
        elif hi is not None and ai is None:
            if not eh(k) or (h_short and nxt):
                phantom.add(k)
        elif ea(k) != eh(k) and 0 < k < n - 1:
            at_boundary = ai in boundary and has_sig(k)
            fragment = (not ea(k) or not eh(k) or a_short or h_short)
            if (at_boundary and fragment) or (a_short and h_short and nxt):
                phantom.add(k)
    live = [k for k in range(n) if k not in phantom]
    if not live:
        return out, MergeReport(False, "nothing left after alignment")
    first_live, last_live = live[0], live[-1]

    # ---- time signatures (stateful sweep: a corrected signature persists) ----
    times: dict[int, tuple[int, int] | None] = {}
    current: tuple[int, int] | None = None
    for k in range(n):
        ai, hi = slots[k]
        a_exp = _explicit_time(a_elems[ai]) if ai is not None else None
        h_exp = _explicit_time(h_elems[hi]) if hi is not None else None
        la, lh = len_a(k), len_h(k)
        if a_exp is not None:
            current = a_exp
        elif current is None:
            current = A.measures[ai].time if ai is not None else h_exp
        if k in phantom:
            continue  # a removed measure's explicit signature still carries forward
        # The second engine saw a meter change (its denominator is reliable) the primary missed.
        if a_exp is None and h_exp is not None and current is not None and h_exp[1] != current[1]:
            current = _sig_from(lh or la, h_exp[1]) or current
        L = _sig_len(current)
        if current is not None and hi is not None and L is not None:
            edge = k in (first_live, last_live)
            truncated = _is_strict_subsequence(ea(k), eh(k)) and lh > la
            content = None
            if truncated and lh != L:
                content = lh  # primary dropped notes to fit a wrong meter
            elif lh > la and la != L and lh != L:
                content = lh
            elif la == lh and la != L and la > 0:
                content = la  # both engines agree the measure contradicts the signature
            if content is not None and not (edge and content < L):
                h_den = h_exp[1] if h_exp else (H.measures[hi].time[1] if H.measures[hi].time else None)
                current = (_sig_from(content, h_den) if h_den else None) or _sig_from(content, current[1]) or current
        times[k] = current

    # ---- key signatures --------------------------------------------------
    keys: dict[int, int] = {}
    key_now = A.measures[0].key.fifths if A.measures else 0
    for k in range(n):
        ai, hi = slots[k]
        ka = _explicit_key(a_elems[ai]) if ai is not None else None
        kh = _explicit_key(h_elems[hi]) if hi is not None else None
        if ka is not None and kh is not None and ka != kh:
            following = [kk for kk in live if kk >= k][:4]
            window = [e for kk in following for e in (ea(kk) or eh(kk))]
            key_now = kh if _out_of_key(window, kh) < _out_of_key(window, ka) else ka
        elif ka is not None:
            key_now = ka
        elif kh is not None and k > 0:
            key_now = kh
        if k not in phantom:
            keys[k] = key_now

    # Pitch centre of the measures both engines agree on, used to settle clef misreads.
    agreed = [_diatonic(e) for k in live if ea(k) and ea(k) == eh(k) for e in ea(k) if len(e[1]) == 3]
    centre = sorted(agreed)[len(agreed) // 2] if agreed else None

    # ---- note content ----------------------------------------------------
    report = MergeReport(True)
    report.secondary_only_measures = sum(1 for k in live if slots[k][0] is None)
    out_measures: list[etree._Element] = []
    clefs: list[etree._Element | None] = []
    pending: list[etree._Element] = []  # directions rescued from phantom measures
    a_clef = _clef_seq(a_elems)
    h_clef = _clef_seq(h_elems)
    for k in range(n):
        ai, hi = slots[k]
        number = A.measures[ai].number if ai is not None else "?"
        if k in phantom:
            if ai is not None:
                pending += [c for c in a_elems[ai] if c.tag not in CONTENT_TAGS | {"barline", "attributes"}]
            report.measures.append(MeasureDecision(k, number, "removed", "recognition artifact (empty measure or "
                                                   "courtesy signature read as a measure)"))
            continue
        a_time = A.measures[ai].time if ai is not None else None
        a_key = A.measures[ai].key.fifths if ai is not None else None
        dec = MeasureDecision(k, number, "primary-only", "no matching measure in second reading")
        dec.time_changed = ai is None or times[k] != a_time
        dec.key_changed = ai is None or keys[k] != a_key
        source = "primary"
        if ai is None:
            source = "secondary"
            dec.source, dec.reason = "secondary", "measure missed by the primary engine"
        elif hi is not None:
            x, y = ea(k), eh(k)
            L = _sig_len(times[k])
            edge = k in (first_live, last_live)
            valid_a = L is not None and (len_a(k) == L or (edge and len_a(k) == len_h(k) and len_a(k) > 0))
            valid_h = L is not None and (len_h(k) == L or (edge and len_a(k) == len_h(k) and len_h(k) > 0))
            shift = _constant_shift(x, y)
            if x == y:
                dec.source, dec.reason = "agree", "both engines read the same notes"
            elif shift and centre is not None and valid_h:
                # Same contour, different staff placement: one engine misread the clef.
                da = abs(_mean_diatonic(x) - centre)
                dh = abs(_mean_diatonic(y) - centre)
                source = "secondary" if dh < da else "primary"
                dec.source, dec.reason = source, "engines disagreed on the clef; the reading that fits the rest of the part was kept"
            elif valid_h and _is_strict_subsequence(x, y):
                source = "secondary"
                dec.source, dec.reason = source, "primary reading is missing notes the second reading found"
            elif valid_h and not valid_a:
                source = "secondary"
                dec.source, dec.reason = source, "only the second reading fills the measure"
            elif valid_a and not valid_h:
                dec.source, dec.reason = "primary", "only the primary reading fills the measure"
            elif valid_a and valid_h:
                if _out_of_key(y, keys[k]) < _out_of_key(x, keys[k]):
                    source = "secondary"
                    dec.source, dec.reason = source, "readings differ; second reading fits the key better"
                else:
                    dec.source, dec.reason = "primary", "readings differ; primary reading kept"
            else:
                if L is not None and abs(len_h(k) - L) < abs(len_a(k) - L):
                    source = "secondary"
                    dec.source, dec.reason = source, "neither reading fills the measure; second is closer"
                else:
                    dec.source, dec.reason = "primary", "neither reading fills the measure"
        if ai is None:
            elem = copy.deepcopy(h_elems[hi])
            for attrs in elem.findall("attributes"):
                for tag in ("key", "time", "clef"):
                    for el in attrs.findall(tag):
                        attrs.remove(el)
            for note in elem.iter("note"):
                note.attrib.pop("id", None)
        else:
            elem = a_elems[ai]
            if source == "secondary":
                _replace_content(elem, h_elems[hi], common)
        if pending:
            for child in reversed(pending):
                elem.insert(0, child)
            pending = []
        clefs.append(h_clef[hi] if (source == "secondary" and hi is not None) else (a_clef[ai] if ai is not None else None))
        out_measures.append(elem)
        dec.out_index = len(out_measures) - 1
        report.measures.append(dec)

    # ---- rebuild the part -----------------------------------------------------
    for m in part.findall("measure"):
        part.remove(m)
    first_no = A.measures[0].number if A.measures else "1"
    start = int(first_no) if str(first_no).isdigit() else 1
    for idx, m in enumerate(out_measures):
        m.set("number", str(start + idx))
        part.append(m)
    for dec in report.measures:
        if dec.out_index is not None:
            dec.number = out_measures[dec.out_index].get("number")

    # ---- write clefs, time and key signatures ----------------------------------
    for m in out_measures:
        for attrs in m.findall("attributes"):
            for c in attrs.findall("clef"):
                attrs.remove(c)
    prev_clef = None
    for idx, (k, m) in enumerate(zip([k for k in live], out_measures)):
        c = clefs[idx] if clefs[idx] is not None else prev_clef
        if c is not None and (prev_clef is None or etree.tostring(c) != etree.tostring(prev_clef)):
            _set_attr(m, "clef", copy.deepcopy(c))
        prev_clef = c
        t_prev = times[live[idx - 1]] if idx else None
        k_prev = keys[live[idx - 1]] if idx else None
        if idx == 0 or times[k] != t_prev:
            if times[k] is not None:
                _set_attr(m, "time", _time_el(times[k]))
        else:
            _set_attr(m, "time", None)
        if idx == 0 or keys[k] != k_prev:
            _set_attr(m, "key", _key_el(keys[k]))
        else:
            _set_attr(m, "key", None)
    return out, report


def _diatonic(e: tuple) -> int:
    step, _, octave = e[1]
    return octave * 7 + "CDEFGAB".index(step)


def _mean_diatonic(events: list[tuple]) -> float:
    vals = [_diatonic(e) for e in events if len(e[1]) == 3]
    return sum(vals) / len(vals) if vals else 0.0


def _constant_shift(x: list[tuple], y: list[tuple]) -> int:
    """Diatonic offset between two readings with identical rhythm and contour (0 if none)."""
    px = [e for e in x if len(e[1]) == 3]
    py = [e for e in y if len(e[1]) == 3]
    if not px or len(px) != len(py) or [e[2] for e in x] != [e[2] for e in y]:
        return 0
    shifts = {_diatonic(b) - _diatonic(a) for a, b in zip(px, py)}
    return shifts.pop() if len(shifts) == 1 else 0


def _clef_seq(measures: list[etree._Element]) -> list[etree._Element | None]:
    """Effective staff-1 clef element at every measure."""
    out, cur = [], None
    for m in measures:
        for c in m.iter("clef"):
            if c.get("number", "1") == "1":
                cur = c
        out.append(cur)
    return out
