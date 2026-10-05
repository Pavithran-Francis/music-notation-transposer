"""Attach OMR confidence to MusicXML notes and derive review items."""

from __future__ import annotations

from statistics import mean

from lxml import etree

from core.musicxml.document import walk
from core.validation.validator import measure_rhythm_issues


def confidence_for_score(tree: etree._ElementTree, raw: dict) -> dict:
    """Map engine measure/voice/event confidences onto MusicXML note ids.

    Returns {"notes": {note_id: conf}, "measures": {f"{part}:{idx}": conf},
             "header": {...}, "mapping": "exact"|"partial"|"none"}.
    """
    pages = raw.get("pages") or []
    per_part: dict[int, list[dict]] = {}
    header: dict[str, list[float]] = {"clef": [], "key": [], "time": []}
    for page in pages:
        for p_idx, records in page.get("parts", {}).items():
            per_part.setdefault(int(p_idx), []).extend(records)
        for k in header:
            header[k].extend(page.get("header", {}).get(k, []))

    notes: dict[str, float] = {}
    measures: dict[str, float] = {}
    exact = total = 0
    for pw in walk(tree):
        records = per_part.get(pw.part_index, [])
        by_measure: dict[int, list] = {}
        for ev in pw.notes:
            by_measure.setdefault(ev.measure_index, []).append(ev)
        for m_idx, m_events in by_measure.items():
            total += 1
            rec = records[m_idx] if m_idx < len(records) else None
            if rec is None:
                continue
            measures[f"{pw.part_id}:{m_idx}"] = rec["min"]
            # group MusicXML events by voice in order of first appearance
            voices: dict[tuple, list] = {}
            for ev in m_events:
                if ev.is_chord or ev.is_grace:
                    continue
                voices.setdefault((ev.staff, ev.voice), []).append(ev)
            xml_voices = [sorted(v, key=lambda e: (e.onset, e.doc_order)) for v in voices.values()]
            eng_voices = rec["voices"]
            mapped = False
            if len(xml_voices) == len(eng_voices) and all(len(a) == len(b) for a, b in zip(xml_voices, eng_voices)):
                for xv, cv in zip(xml_voices, eng_voices):
                    for ev, c in zip(xv, cv):
                        if ev.id:
                            notes[ev.id] = c
                mapped = True
            else:
                flat_x = [e for v in xml_voices for e in v]
                flat_c = [c for v in eng_voices for c in v]
                if len(flat_x) == len(flat_c):
                    for ev, c in zip(flat_x, flat_c):
                        if ev.id:
                            notes[ev.id] = c
                    mapped = True
            if mapped:
                exact += 1
            # chord members, grace notes and unmapped notes inherit sensible values
            last_head: dict[tuple, float] = {}
            for ev in sorted(m_events, key=lambda e: e.doc_order):
                if not ev.id:
                    continue
                if ev.id in notes:
                    last_head[(ev.staff, ev.voice)] = notes[ev.id]
                elif ev.is_chord and (ev.staff, ev.voice) in last_head:
                    notes[ev.id] = last_head[(ev.staff, ev.voice)]
                else:
                    notes[ev.id] = rec["min"]

    mapping = "none" if not pages else ("exact" if exact == total else "partial")
    return {
        "notes": notes,
        "measures": measures,
        "header": {k: (round(min(v), 3) if v else None) for k, v in header.items()},
        "mapping": mapping,
    }


AGREED_CONFIDENCE = 0.97
RESOLVED_CONFIDENCE = 0.85  # disagreement settled by hard evidence
DISPUTED_CONFIDENCE = 0.6  # judgement call: shown for review


def apply_merge(confidence: dict, tree: etree._ElementTree, merge: dict | None) -> dict:
    """Fold the two-engine merge decisions into per-note confidence.

    Measures where both engines read identical notes are very likely right;
    measures that had to be resolved are capped below the review threshold so
    they always appear in the review list.
    """
    if not merge or not merge.get("applied"):
        return confidence
    decisions = {m["out_index"]: m for m in merge.get("measures", []) if m.get("out_index") is not None}
    notes = dict(confidence.get("notes", {}))
    for pw in walk(tree):
        for ev in pw.notes:
            d = decisions.get(ev.measure_index)
            if d is None or not ev.id:
                continue
            c = notes.get(ev.id, 1.0)
            if d.get("weak"):
                notes[ev.id] = min(c, DISPUTED_CONFIDENCE)
            elif d["source"] == "agree" and not d["disputed"]:
                notes[ev.id] = max(c, AGREED_CONFIDENCE)
            elif d["disputed"]:
                notes[ev.id] = max(c, RESOLVED_CONFIDENCE)
    return {**confidence, "notes": notes, "merge": merge}


def review_items(tree: etree._ElementTree, confidence: dict | None, threshold: float) -> dict:
    """Build the recognition summary and the list of items needing review."""
    items = []
    note_conf = (confidence or {}).get("notes", {})
    walks = walk(tree)
    for pw in walks:
        for ev in pw.notes:
            c = note_conf.get(ev.id or "")
            if c is not None and c < threshold:
                items.append({
                    "kind": "note",
                    "note_id": ev.id,
                    "part_id": pw.part_id,
                    "measure": ev.measure_number,
                    "measure_index": ev.measure_index,
                    "beat": round(ev.beat(), 3),
                    "detected": ev.pitch.name() if ev.pitch else "rest",
                    "duration": ev.element.findtext("type"),
                    "confidence": c,
                    "reason": "Low recognition confidence",
                })
        for issue in measure_rhythm_issues(pw):
            items.append({
                "kind": "measure",
                "part_id": pw.part_id,
                "measure": issue.measure,
                "measure_index": issue.measure_index,
                "confidence": None,
                "reason": issue.message,
                "severity": issue.severity,
            })
    merge = (confidence or {}).get("merge") or {}
    if merge.get("applied"):
        part_id = walks[0].part_id if walks else None
        weak_measures = set()
        prev = None
        for d in merge.get("measures", []):
            if d.get("out_index") is None:
                continue
            base = {"kind": "measure", "part_id": part_id, "measure": d["number"], "measure_index": d["out_index"]}
            if d.get("weak"):
                weak_measures.add(d["out_index"])
                items.append(base | {"confidence": DISPUTED_CONFIDENCE, "severity": "warning",
                                     "reason": "Recognition engines disagreed: " + d["reason"]})
            # signature corrections: listed once, where they begin
            for flag, label in (("time_changed", "Time signature"), ("key_changed", "Key signature")):
                if d.get(flag) and not (prev and prev.get(flag)):
                    items.append(base | {"confidence": None, "severity": "info",
                                         "reason": f"{label} corrected here by cross-checking both recognition engines"})
            prev = d
        # one item per uncertain measure instead of one per note
        items[:] = [i for i in items if not (i["kind"] == "note" and i.get("measure_index") in weak_measures)]
    for mr in (confidence or {}).get("multirests") or []:
        if mr.get("flagged"):
            items.append({"kind": "measure", "part_id": walks[0].part_id if walks else None,
                          "measure": mr.get("measure"), "measure_index": mr.get("index"),
                          "confidence": mr.get("confidence"), "severity": "warning",
                          "reason": f"Multi-measure rest: the number of bars ({mr.get('count')}) could not be "
                                    "read reliably from the page — please check"})
    hdr = (confidence or {}).get("header", {})
    for k, label in (("clef", "Clef"), ("key", "Key signature"), ("time", "Time signature")):
        v = hdr.get(k)
        if v is not None and v < threshold:
            items.append({"kind": "header", "field": k, "measure_index": 0, "confidence": v,
                          "reason": f"{label} recognized with low confidence"})

    summary = None
    if confidence and note_conf:
        vals = list(note_conf.values())
        rhythm_ok = 1 - (sum(1 for i in items if i["kind"] == "measure") /
                         max(1, sum(len(pw.measures) for pw in walks)))
        summary = {
            "overall": round(mean(vals), 3),
            "notes": round(mean(vals), 3),
            "rhythm": round(rhythm_ok, 3),
            "clef": hdr.get("clef"),
            "key": hdr.get("key"),
            "time": hdr.get("time"),
            "low_confidence_notes": sum(1 for v in vals if v < threshold),
            "mapping": confidence.get("mapping"),
        }
    return {"items": items, "summary": summary, "threshold": threshold}
