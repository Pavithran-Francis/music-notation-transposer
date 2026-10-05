"""Score OMR output against ground truth, element by element.

    .venv/bin/python -m benchmarks.score_omr TRUTH.musicxml RECOGNIZED.(musicxml|mxl)
"""

from __future__ import annotations

import sys
from difflib import SequenceMatcher
from pathlib import Path

from core.analysis import analyze
from core.musicxml.document import parse_musicxml, walk


def _events(tree):
    pw = walk(tree)[0]
    per = {}
    for e in pw.notes:
        if e.is_grace:
            continue
        name = e.pitch.name() if e.pitch else "r"
        per.setdefault(e.measure_index, []).append((name, round(e.duration / e.divisions, 4)))
    return pw, per


def _count(tree, tag, attr=None, val=None):
    return sum(1 for el in tree.getroot().iter(tag) if attr is None or el.get(attr) == val)


def _texts(tree) -> str:
    root = tree.getroot()
    parts = [root.findtext("work/work-title") or "", root.findtext("movement-title") or ""]
    parts += [(c.text or "") for c in root.iter("credit-words")]
    parts += [(w.text or "") for w in root.iter("words")]
    return " | ".join(p.strip() for p in parts if p and p.strip())


def score(truth_path: Path, rec_path: Path) -> dict:
    truth = parse_musicxml(truth_path.read_bytes())
    rec = parse_musicxml(rec_path.read_bytes())
    tw, te = _events(truth)
    rw, re_ = _events(rec)
    n = len(tw.measures)
    ts_ok = key_ok = 0
    pitch_hits = rhythm_hits = total = 0
    acc_total = acc_hits = 0
    bad = []
    for i in range(n):
        tm = tw.measures[i]
        rm = rw.measures[i] if i < len(rw.measures) else None
        if rm and rm.time == tm.time:
            ts_ok += 1
        if rm and rm.key.fifths == tm.key.fifths:
            key_ok += 1
        a = te.get(i, [])
        b = re_.get(i, [])
        total += len(a)
        sm = SequenceMatcher(a=[x[0] for x in a], b=[x[0] for x in b], autojunk=False)
        pitch_hits += sum(bl.size for bl in sm.get_matching_blocks())
        sm2 = SequenceMatcher(a=a, b=b, autojunk=False)
        rhythm_hits += sum(bl.size for bl in sm2.get_matching_blocks())
        for (pa, _), (pb, _) in zip(a, b):
            if pa != "r" and ("#" in pa or "b" in pa[1:]):
                acc_total += 1
                acc_hits += pa == pb
        if a != b:
            bad.append((i + 1, " ".join(f"{p}/{d:g}" for p, d in a), " ".join(f"{p}/{d:g}" for p, d in b),
                        f"{tm.time}", f"{rm.time if rm else None}", tm.key.fifths, rm.key.fifths if rm else None))
    texts = _texts(rec)
    ta = analyze(truth)
    result = {
        "measures": f"{len(rw.measures)}/{n}",
        "time_signatures": f"{ts_ok}/{n}",
        "key_signatures": f"{key_ok}/{n}",
        "pitches": f"{pitch_hits}/{total} ({100 * pitch_hits / max(1, total):.1f}%)",
        "pitch+rhythm": f"{rhythm_hits}/{total} ({100 * rhythm_hits / max(1, total):.1f}%)",
        "altered notes": f"{acc_hits}/{acc_total}",
        "title found": "Benchmark" in texts,
        "composer found": "Tester" in texts,
        "tempo text found": "Allegro" in texts,
        "tempo (bpm)": analyze(rec)["tempo"],
        "dynamics": f"{_count(rec, 'dynamics')}/{_count(truth, 'dynamics')}",
        "hairpins": f"{_count(rec, 'wedge', 'type', 'crescendo') + _count(rec, 'wedge', 'type', 'diminuendo')}"
                    f"/{_count(truth, 'wedge', 'type', 'crescendo') + _count(truth, 'wedge', 'type', 'diminuendo')}",
        "slurs": f"{_count(rec, 'slur', 'type', 'start')}/{_count(truth, 'slur', 'type', 'start')}",
        "staccato/accent": f"{_count(rec, 'staccato') + _count(rec, 'accent')}/{_count(truth, 'staccato') + _count(truth, 'accent')}",
        "rehearsal marks": f"{_count(rec, 'rehearsal')}/{_count(truth, 'rehearsal')}",
        "texts": texts[:160],
        "truth_notes": ta["notes"],
    }
    result["_bad_measures"] = bad
    return result


def report(r: dict) -> None:
    for k, v in r.items():
        if not k.startswith("_"):
            print(f"  {k:18} {v}")
    if r["_bad_measures"]:
        print("  mismatched measures:")
        for m, a, b, ta, tb, ka, kb in r["_bad_measures"]:
            print(f"    m{m:<3} time {ta}->{tb} key {ka}->{kb}\n         truth: {a}\n         omr:   {b}")


if __name__ == "__main__":
    report(score(Path(sys.argv[1]), Path(sys.argv[2])))
