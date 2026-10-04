"""Musical validation of a score and of a transposition result."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from lxml import etree

from core.musicxml.document import MeasureInfo, PartWalk, walk


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    part_id: str | None = None
    measure: str | None = None
    measure_index: int | None = None
    note_id: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ValidationReport:
    checks: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": ok, "detail": detail})

    def to_dict(self) -> dict:
        errors = sum(1 for i in self.issues if i.severity == "error")
        warnings = sum(1 for i in self.issues if i.severity == "warning")
        if errors:
            summary = f"{errors} issue{'s' if errors != 1 else ''} require{'s' if errors == 1 else ''} review."
        elif warnings:
            summary = f"Score validation passed with {warnings} warning{'s' if warnings != 1 else ''}."
        else:
            summary = "Score validation passed."
        return {
            "passed": self.passed,
            "summary": summary,
            "checks": self.checks,
            "issues": [i.to_dict() for i in self.issues],
        }


def expected_measure_duration(m: MeasureInfo) -> int | None:
    if not m.time:
        return None
    beats, beat_type = m.time
    d = Fraction(beats * 4, beat_type) * m.divisions
    return int(d) if d.denominator == 1 else None


def measure_rhythm_issues(pw: PartWalk) -> list[Issue]:
    issues = []
    last = len(pw.measures) - 1
    for m in pw.measures:
        exp = expected_measure_duration(m)
        if exp is None or not m.voice_durations:
            continue
        longest = max(m.voice_durations.values())
        over = [v for v, d in m.voice_durations.items() if d > exp]
        if over:
            issues.append(Issue(
                "error", "measure_overfull",
                f"Measure {m.number}: voice content is longer than the {m.time[0]}/{m.time[1]} time signature.",
                pw.part_id, m.number, m.measure_index,
            ))
        elif longest < exp and not (m.implicit or m.measure_index in (0, last)):
            issues.append(Issue(
                "warning", "measure_underfull",
                f"Measure {m.number}: contents are shorter than the {m.time[0]}/{m.time[1]} time signature.",
                pw.part_id, m.number, m.measure_index,
            ))
    return issues


def validate_score(tree: etree._ElementTree) -> ValidationReport:
    """Structural and rhythmic validation of a single score."""
    report = ValidationReport()
    walks = walk(tree)
    rhythm: list[Issue] = []
    bad_dur: list[Issue] = []
    bad_key: list[Issue] = []
    for pw in walks:
        rhythm += measure_rhythm_issues(pw)
        for ev in pw.notes:
            if not ev.is_grace and ev.duration <= 0:
                bad_dur.append(Issue("error", "invalid_duration",
                                     f"Measure {ev.measure_number}: a note has no valid duration.",
                                     pw.part_id, ev.measure_number, ev.measure_index, ev.id))
        for m in pw.measures:
            if abs(m.key.fifths) > 7:
                bad_key.append(Issue("error", "invalid_key",
                                     f"Measure {m.number}: key signature with {m.key.fifths} fifths is invalid.",
                                     pw.part_id, m.number, m.measure_index))
    report.check("Every measure is rhythmically valid", not any(i.severity == "error" for i in rhythm),
                 f"{len(rhythm)} measure(s) flagged" if rhythm else "")
    report.check("Notes have valid durations", not bad_dur)
    report.check("Key signatures are valid", not bad_key)
    report.issues += rhythm + bad_dur + bad_key
    return report


def compare_transposition(
    source: etree._ElementTree,
    result: etree._ElementTree,
    semitones: int,
    octave_shifts: dict[str, int] | None = None,
    part_ids: list[str] | None = None,
    target_name: str | None = None,
) -> ValidationReport:
    """Check that `result` is exactly `source` moved by `semitones` (plus logged octave shifts)."""
    octave_shifts = octave_shifts or {}
    report = validate_score(result)
    src_walks = [w for w in walk(source) if part_ids is None or w.part_id in part_ids]
    res_walks = walk(result)

    structure_ok = len(src_walks) == len(res_walks)
    measures_ok = True
    notes_ok = True
    rhythm_ok = True
    pitch_ok = True
    for sw, rw in zip(src_walks, res_walks):
        if len(sw.measures) != len(rw.measures):
            measures_ok = False
            report.issues.append(Issue("error", "measure_count",
                                       f"Part {sw.part_id}: measure count changed ({len(sw.measures)} → {len(rw.measures)}).",
                                       sw.part_id))
        if len(sw.notes) != len(rw.notes):
            notes_ok = False
            report.issues.append(Issue("error", "note_count",
                                       f"Part {sw.part_id}: number of notes changed ({len(sw.notes)} → {len(rw.notes)}).",
                                       sw.part_id))
            continue
        for a, b in zip(sw.notes, rw.notes):
            if (a.duration, a.is_rest, a.is_chord, a.is_grace, a.voice, a.onset) != (
                b.duration, b.is_rest, b.is_chord, b.is_grace, b.voice, b.onset
            ) or a.element.findtext("type") != b.element.findtext("type") or len(a.element.findall("dot")) != len(
                b.element.findall("dot")
            ) or len(a.element.findall("tie")) != len(b.element.findall("tie")):
                rhythm_ok = False
                report.issues.append(Issue("error", "rhythm_changed",
                                           f"Measure {b.measure_number}: rhythm differs from the original.",
                                           rw.part_id, b.measure_number, b.measure_index, b.id))
            if a.pitch is not None and b.pitch is not None:
                expected = semitones + 12 * octave_shifts.get(b.id or "", 0)
                if abs((b.pitch.semitones - a.pitch.semitones) - expected) > 1e-9:
                    pitch_ok = False
                    report.issues.append(Issue("error", "pitch_mismatch",
                                               f"Measure {b.measure_number}: {a.pitch.name()} became {b.pitch.name()} "
                                               f"(expected a shift of {expected} semitones).",
                                               rw.part_id, b.measure_number, b.measure_index, b.id))
            elif (a.pitch is None) != (b.pitch is None):
                pitch_ok = False
    report.check("Parts preserved", structure_ok)
    report.check("Number of measures is unchanged", measures_ok)
    report.check("No notes were added or deleted", notes_ok)
    report.check("Rhythmic structure is unchanged", rhythm_ok)
    report.check("Transposition is mathematically correct", pitch_ok,
                 f"Every pitch moved by {semitones:+d} semitones" + (" (plus logged octave adjustments)" if octave_shifts else ""))
    if target_name:
        names = [sp.findtext("part-name") for sp in result.getroot().findall("part-list/score-part")]
        report.check("Target instrument is correctly represented", all(n == target_name for n in names),
                     ", ".join(n or "?" for n in names))
    return report
