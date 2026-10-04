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
