"""Audiveris (https://github.com/Audiveris/audiveris) OMR engine adapter.

Audiveris is run as a separate process in batch mode:

    Audiveris -batch -export -save -output <dir> -- <book.pdf>

It writes <book>.mxl (MusicXML) and <book>.omr (its project file). The .omr
project contains every recognized symbol with a recognition grade, which we
use as per-note confidence.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from lxml import etree

from app.services.omr.base import OMREngine, OMRError, OMRResult, ProgressCallback
from app.services.omr.preprocess import images_to_pdf

STEP_LABELS = {
    "LOAD": "Loading page", "BINARY": "Binarizing", "SCALE": "Measuring staff spacing",
    "GRID": "Finding staves and barlines", "HEADERS": "Reading clefs, keys and time signatures",
    "STEM_SEEDS": "Finding stems", "BEAMS": "Recognizing beams", "LEDGERS": "Recognizing ledger lines",
    "HEADS": "Recognizing noteheads", "STEMS": "Connecting stems", "REDUCTION": "Resolving conflicts",
    "CUE_BEAMS": "Recognizing cue notes", "TEXTS": "Reading text", "MEASURES": "Building measures",
    "CHORDS": "Grouping chords", "CURVES": "Recognizing slurs, hairpins and endings",
    "SYMBOLS": "Recognizing symbols", "LINKS": "Linking symbols", "RHYTHMS": "Checking rhythms",
    "PAGE": "Assembling page",
}
STEP_ORDER = list(STEP_LABELS)


class AudiverisEngine(OMREngine):
    name = "Audiveris"

    def __init__(self, executable: str | None, timeout_per_page: int = 180):
        self.executable = executable
        self.timeout_per_page = timeout_per_page

    def is_available(self) -> bool:
        return bool(self.executable) and Path(self.executable).exists()

    def version(self) -> str | None:
        if not self.is_available():
            return None
        try:
            out = subprocess.run([self.executable, "-batch", "-version"], capture_output=True, text=True, timeout=60)
            m = re.search(r"(\d+\.\d+(\.\d+)?)", out.stdout + out.stderr)
            return m.group(1) if m else None
        except Exception:
            return None

    def recognize(self, pages: list[Path], workdir: Path, progress: ProgressCallback) -> OMRResult:
        if not self.is_available():
            raise OMRError(
                "The Audiveris OMR engine is not installed. Install it (see README) or upload MusicXML instead."
            )
        workdir.mkdir(parents=True, exist_ok=True)
        book = images_to_pdf(pages, workdir / "book.pdf")
        out_dir = workdir / "out"
        out_dir.mkdir(exist_ok=True)
        cmd = [self.executable, "-batch", "-export", "-save", "-output", str(out_dir), "--", str(book)]
        env = dict(os.environ)
        env.setdefault("JAVA_TOOL_OPTIONS", "-Djava.awt.headless=true")
        timeout = self.timeout_per_page * max(1, len(pages)) + 60
        n = len(pages)
        progress("recognizing", f"Analyzing page 1 of {n}…", 0.0)

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                                cwd=str(workdir))
        log_lines: list[str] = []
        sheet = 1
        timed_out = threading.Event()

        def killer():
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, killer)
        timer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                log_lines.append(line.rstrip())
                if len(log_lines) > 4000:
                    log_lines = log_lines[-2000:]
                m = re.search(r"\[[^\]#]+#(\d+)\]|Sheet#(\d+)|Stub#(\d+)", line)
                if m:
                    sheet = int(next(g for g in m.groups() if g))
                m = re.search(r"StepMonitoring\s+\d+\s*\|\s*([A-Z_]+)", line)
                if m and m.group(1) in STEP_LABELS:
                    step = m.group(1)
                    frac = ((sheet - 1) + (STEP_ORDER.index(step) + 1) / len(STEP_ORDER)) / max(1, n)
                    progress("recognizing", f"Analyzing page {min(sheet, n)} of {n}: {STEP_LABELS[step]}…", min(frac, 0.99))
                if "Exporting" in line:
                    progress("exporting", "Exporting MusicXML…", 0.99)
            proc.wait()
        finally:
            timer.cancel()
        (workdir / "audiveris.log").write_text("\n".join(log_lines))
        if timed_out.is_set():
            raise OMRError("Recognition took too long and was stopped. Try fewer pages or a cleaner scan.")

        mxls = sorted(out_dir.glob("*.mxl"), key=_movement_order)
        if not mxls:
            hint = _diagnose(log_lines)
            raise OMRError("No music could be recognized in this document." + (f" {hint}" if hint else ""))
        musicxml = mxls[0].read_bytes() if len(mxls) == 1 else _merge_movements(mxls)
        omr_files = list(out_dir.glob("*.omr"))
        raw = parse_omr_project(omr_files[0]) if omr_files else {}
        warnings = []
        if len(mxls) > 1:
            warnings.append(f"Audiveris split the score into {len(mxls)} movements; they were joined in order.")
        warnings += _invalid_sheet_warnings(log_lines)
        return OMRResult(musicxml=musicxml, engine=self.name, page_count=n, raw_confidence=raw, warnings=warnings)


def _movement_order(p: Path) -> tuple:
    m = re.search(r"\.mvt(\d+)", p.name)
    return (int(m.group(1)) if m else 0, p.name)


def _diagnose(lines: list[str]) -> str:
    text = "\n".join(lines[-300:])
    if re.search(r"too low interline|interline.*too", text, re.I):
        return "The image resolution appears too low; try a scan at 300 DPI or higher."
    if re.search(r"no staves|No staff", text, re.I):
        return "No staff lines were found; the page may not contain printed sheet music."
    if "OutOfMemory" in text:
        return "The document is too large to process."
    return ""


def _invalid_sheet_warnings(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        if "invalid" in line.lower() and "sheet" in line.lower():
            m = re.search(r"#(\d+)", line)
            out.append(f"Page {m.group(1) if m else '?'} could not be recognized reliably.")
    return sorted(set(out))


def _explicit_key(part) -> None:
    """Audiveris omits <key> for C major; once movements are joined that would silently
    inherit the previous movement's key, so make it explicit."""
    from core.musicxml.document import ATTRIBUTES_ORDER, insert_ordered

    first = part.find("measure")
    if first is None:
        return
    attrs = first.find("attributes")
    if attrs is not None and attrs.find("key") is not None:
        return
    if attrs is None:
        attrs = etree.Element("attributes")
        first.insert(0, attrs)
    key = etree.Element("key")
    etree.SubElement(key, "fifths").text = "0"
    insert_ordered(attrs, key, ATTRIBUTES_ORDER)


def _merge_movements(mxls: list[Path]) -> bytes:
    """Concatenate multi-movement output (same part structure) into one score."""
    from core.musicxml.document import parse_musicxml, to_bytes

    trees = [parse_musicxml(p.read_bytes()) for p in mxls]
    base = trees[0].getroot()
    base_parts = base.findall("part")
    for t in trees[1:]:
        for i, part in enumerate(t.getroot().findall("part")):
            if i < len(base_parts):
                _explicit_key(part)
                for m in part.findall("measure"):
                    base_parts[i].append(m)
    # renumber measures
    for part in base_parts:
        for i, m in enumerate(part.findall("measure")):
            m.set("number", str(i + 1))
    return to_bytes(base)


# ---------------------------------------------------------------------------
# .omr project parsing (confidence data)
# ---------------------------------------------------------------------------


def _grade(el: etree._Element) -> float:
    g = el.get("ctx-grade") or el.get("grade")
    try:
        return float(g) if g is not None else 1.0
    except ValueError:
        return 1.0


def parse_omr_project(omr_path: Path) -> dict:
    """Extract per-measure, per-voice chord confidence from an Audiveris .omr file.

    Returns {"pages": [{"parts": {part_index: [measure_record, ...]}, "header": {...}}]}
    where measure_record = {"voices": [[conf_of_event, ...], ...], "min": float}
    """
    result: dict = {"pages": []}
    try:
        zf = zipfile.ZipFile(omr_path)
    except Exception:
        return result
    sheet_files = sorted(
        (n for n in zf.namelist() if re.match(r"sheet#\d+/sheet#\d+\.xml$", n)),
        key=lambda n: int(re.search(r"#(\d+)", n).group(1)),
    )
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    for name in sheet_files:
        try:
            root = etree.fromstring(zf.read(name), parser)
        except Exception:
            result["pages"].append({"parts": {}, "header": {}})
            continue
        result["pages"].append(_parse_sheet(root))
    return result


def _parse_sheet(root: etree._Element) -> dict:
    page: dict = {"parts": {}, "header": {"clef": [], "key": [], "time": []}}
    for system in root.iter("system"):
        inters: dict[str, etree._Element] = {}
        sig = system.find("sig")
        contains: dict[str, list[str]] = {}
        alters_of: dict[str, list[str]] = {}
        if sig is not None:
            inters_el = sig.find("inters")
            if inters_el is not None:
                for el in inters_el:
                    if el.get("id"):
                        inters[el.get("id")] = el
                    if el.tag == "clef":
                        page["header"]["clef"].append(_grade(el))
                    elif el.tag in ("key", "key-alter"):
                        page["header"]["key"].append(_grade(el))
                    elif el.tag in ("time-pair", "time-whole"):
                        page["header"]["time"].append(_grade(el))
            rel_el = sig.find("relations")
            if rel_el is not None:
                for rel in rel_el.findall("relation"):
                    kind = rel[0].tag if len(rel) else ""
                    src, tgt = rel.get("source"), rel.get("target")
                    if kind == "containment":
                        contains.setdefault(src, []).append(tgt)
                    elif kind == "alter-head":
                        alters_of.setdefault(tgt, []).append(src)

        def event_conf(chord_id: str) -> float:
            el = inters.get(chord_id)
            confs = [_grade(el)] if el is not None else [1.0]
            for member in contains.get(chord_id, []):
                m = inters.get(member)
                if m is not None:
                    confs.append(_grade(m))
                for a in alters_of.get(member, []):
                    if a in inters:
                        confs.append(_grade(inters[a]))
            return round(min(confs), 3)

        for p_idx, part in enumerate(system.findall("part")):
            records = page["parts"].setdefault(p_idx, [])
            for measure in part.findall("measure"):
                voices = []
                for voice in measure.findall("voice"):
                    seen: list[str] = []
                    for entry in voice.iter("value"):
                        cid = entry.get("chord")
                        if cid and cid not in seen:
                            seen.append(cid)
                    voices.append([event_conf(c) for c in seen])
                flat = [c for v in voices for c in v]
                records.append({"voices": voices, "min": min(flat) if flat else 1.0})
    return page
