"""Processing pipeline: upload → analyze (OMR) → corrections → transpose → range → render.

Versioning: every stage writes its own artifact and never modifies the
previous one:

    source.musicxml  →(corrections)→  corrected.musicxml
    corrected        →(transpose)→    transposed_raw.musicxml
    transposed_raw   →(range actions, accidentals, clefs)→ final.musicxml
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass

from app.config import get_settings
from app.db import Project, add_history, session
from app.services import storage
from app.services.omr.base import OMRError
from app.services.omr.confidence import confidence_for_score, review_items
from app.services.omr.service import OMRService
from app.services.rendering import service as render
from core.analysis import analyze
from core.corrections import apply_corrections
from core.instruments.database import resolve_instrument
from core.musicxml.document import MusicXMLError, ensure_note_ids, parse_musicxml, to_bytes
from core.transposition.engine import TranspositionOptions, finalize, transpose_pitches
from core.validation.range import apply_adjustments, auto_correct_range, check_range
from core.validation.validator import compare_transposition


class PipelineError(RuntimeError):
    """User-facing processing error."""


# ---------------------------------------------------------------------------
# Upload type detection (never trust the extension alone)
# ---------------------------------------------------------------------------


@dataclass
class UploadKind:
    kind: str  # pdf | image | musicxml | mscz
    ext: str


def detect_upload(filename: str, data: bytes) -> UploadKind:
    name = (filename or "").lower()
    head = data[:8]
    if head.startswith(b"%PDF-"):
        return UploadKind("pdf", "pdf")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return UploadKind("image", "png")
    if head.startswith(b"\xff\xd8\xff"):
        return UploadKind("image", "jpg")
    if head.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            raise PipelineError("The archive is corrupt.")
        if any(n.endswith(".mscx") for n in names):
            return UploadKind("mscz", "mscz")
        if "META-INF/container.xml" in names or any(n.endswith((".xml", ".musicxml")) for n in names):
            return UploadKind("musicxml", "mxl")
        raise PipelineError("Unsupported archive. Upload a .mxl (compressed MusicXML) or .mscz file.")
    text_head = data[:6000].lstrip(b"\xef\xbb\xbf \t\r\n")
    if text_head.startswith(b"<") and (b"score-partwise" in text_head or b"score-timewise" in text_head):
        return UploadKind("musicxml", "musicxml")
    if name.endswith((".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic")):
        raise PipelineError("Unsupported image format. Please upload PNG or JPEG images.")
    raise PipelineError("Unsupported file. Upload a PDF, PNG, JPEG, MusicXML (.musicxml/.xml/.mxl) or MuseScore (.mscz) file.")


def store_upload(project_id: str, files: list[tuple[str, bytes]]) -> dict:
    """Validate and store uploaded files; build quick previews. Returns project fields."""
    s = get_settings()
    if not files:
        raise PipelineError("No file uploaded.")
    kinds = [detect_upload(n, d) for n, d in files]
    for (n, d) in files:
        if len(d) > s.max_upload_mb * 1024 * 1024:
            raise PipelineError(f"'{n}' is larger than the {s.max_upload_mb} MB limit.")
    if len(files) > 1 and any(k.kind != "image" for k in kinds):
        raise PipelineError("Multiple files are only supported for image pages (PNG/JPEG). Upload a single PDF or MusicXML file.")

    # reset previous state
    for rel in ("upload", "pages", "thumbs", "raw", "omr", "cache", "source.musicxml", "corrected.musicxml",
                "transposed_raw.musicxml", "final.musicxml", "confidence.json", "pageinfo.json"):
        storage.remove(project_id, rel)
    for i, ((name, data), k) in enumerate(zip(files, kinds)):
        storage.write_bytes(project_id, f"upload/original-{i + 1}.{k.ext}", data)

    kind = kinds[0].kind
    page_count = 0
    if kind == "pdf":
        page_count = _quick_pdf_thumbs(project_id, files[0][1])
    elif kind == "image":
        from app.services.omr.preprocess import load_image, make_thumbnail
        for i, (_, data) in enumerate(files):
            try:
                p = load_image(data, storage.path(project_id, f"raw/upload-{i + 1}.png"), s.max_image_pixels)
            except OMRError as e:
                raise PipelineError(str(e))
            make_thumbnail(p, storage.path(project_id, f"thumbs/page-{i + 1}.png"))
        page_count = len(files)
    elif kind in ("musicxml", "mscz"):
        page_count = 0  # rendered preview via Verovio after analysis
    return {
        "source_kind": kind,
        "original_filename": ", ".join(n for n, _ in files)[:300],
        "page_count": page_count,
        "page_rotations": [0] * page_count,
    }


def _quick_pdf_thumbs(project_id: str, data: bytes) -> int:
    import pymupdf

    s = get_settings()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise PipelineError("The PDF could not be opened. It may be corrupt.")
    try:
        if doc.needs_pass:
            raise PipelineError("The PDF is password-protected.")
        if doc.page_count == 0:
            raise PipelineError("The PDF has no pages.")
        if doc.page_count > s.max_pdf_pages:
            raise PipelineError(f"The PDF has {doc.page_count} pages; the limit is {s.max_pdf_pages}.")
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=110, alpha=False)
            storage.write_bytes(project_id, f"thumbs/page-{i + 1}.png", pix.tobytes("png"))
        return doc.page_count
    finally:
        doc.close()


def rotate_thumbnail(project_id: str, page: int, degrees: int) -> None:
    from PIL import Image

    p = storage.path(project_id, f"thumbs/page-{page}.png")
    if p.exists():
        img = Image.open(p)
        img.rotate(-degrees, expand=True).save(p)


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


def run_analyze(project_id: str, progress) -> None:
    with session() as s:
        project = s.get(Project, project_id)
        kind = project.source_kind
        rotations = list(project.page_rotations or [])
    uploads = sorted((storage.project_dir(project_id) / "upload").glob("original-*"),
                     key=lambda p: int(p.stem.split("-")[1]))
    if not uploads:
        raise PipelineError("No uploaded file found. Please upload a score first.")

    recognition: dict = {"engine": None, "warnings": [], "pages": []}
    confidence = None
    if kind == "musicxml":
        progress("parsing", "Reading MusicXML…", 0.2)
        xml = uploads[0].read_bytes()
        recognition["engine"] = "MusicXML import (no OMR needed)"
    elif kind == "mscz":
        progress("parsing", "Converting MuseScore file…", 0.2)
        if not render.mscore_available():
            raise PipelineError("Reading .mscz files requires MuseScore. Export MusicXML from MuseScore instead.")
        xml = render.mscz_to_musicxml(uploads[0].read_bytes())
        recognition["engine"] = "MuseScore file import (no OMR needed)"
    else:
        omr = OMRService()
        workdir = storage.project_dir(project_id)
        files = [("pdf" if p.suffix == ".pdf" else "image", p.read_bytes()) for p in uploads]
        progress("preprocessing", "Preparing pages…", 0.02)
        try:
            doc = omr.parse_document(files, workdir, rotations=rotations, progress=progress)
        except OMRError as e:
            raise PipelineError(str(e))
        recognition["pages"] = [p.to_dict() for p in doc.pages]
        if doc.embedded_musicxml:
            xml = doc.embedded_musicxml
            recognition["engine"] = "MusicXML embedded in the PDF (no OMR needed)"
            recognition["warnings"] = doc.warnings
        else:
            try:
                result = omr.recognize_pages(doc, workdir, lambda st, msg, f: progress(st, msg, 0.05 + 0.85 * f))
            except OMRError as e:
                raise PipelineError(str(e))
            xml = OMRService.export_musicxml(result)
            recognition["engine"] = result.engine
            recognition["warnings"] = result.warnings
            confidence = result.raw_confidence

    progress("validating", "Checking musical structure…", 0.92)
    try:
        tree = parse_musicxml(xml)
    except MusicXMLError as e:
        raise PipelineError(str(e))
    ensure_note_ids(tree)
    storage.write_bytes(project_id, "source.musicxml", to_bytes(tree))
    if confidence is not None:
        storage.write_json(project_id, "confidence.json", confidence_for_score(tree, confidence))
    else:
        storage.remove(project_id, "confidence.json")

    with session() as s:
        project = s.get(Project, project_id)
        project.corrections = []
        project.range_actions = []
        project.result = None
        project.recognition = recognition
        if kind in ("musicxml", "mscz"):
            project.page_count = 0
        add_history(s, project_id, "analyzed", engine=recognition["engine"])
    rebuild_corrected(project_id)
    progress("rendering", "Rendering preview…", 0.97)


def rebuild_corrected(project_id: str) -> None:
    """source + corrections → corrected.musicxml, analysis and review items."""
    source = storage.read_bytes(project_id, "source.musicxml")
    if source is None:
        raise PipelineError("The score has not been analyzed yet.")
    with session() as s:
        project = s.get(Project, project_id)
        corrections = list(project.corrections or [])
        had_result = project.result is not None
    tree = parse_musicxml(source)
    corrected = apply_corrections(tree, corrections)
    data = to_bytes(corrected)
    storage.write_bytes(project_id, "corrected.musicxml", data)
    analysis = analyze(corrected)
    confidence = storage.read_json(project_id, "confidence.json")
    # Notes the user corrected are no longer uncertain.
    if confidence:
        fixed = {op.get("note_id") for op in corrections if op.get("note_id")}
        confidence = {**confidence, "notes": {k: (1.0 if k in fixed else v) for k, v in confidence["notes"].items()}}
    review = review_items(corrected, confidence, get_settings().omr_confidence_threshold)
    with session() as s:
        project = s.get(Project, project_id)
        project.analysis = analysis
        rec = dict(project.recognition or {})
        rec["review"] = review
        project.recognition = rec
        if had_result:
            project.result_stale = True
        if not project.source_instrument and analysis["parts"]:
            guess = analysis["parts"][0].get("instrument_guess")
            if guess:
                project.source_instrument = {"id": guess}


def original_colors(project_id: str) -> dict[str, str]:
    confidence = storage.read_json(project_id, "confidence.json")
    if not confidence:
        return {}
    with session() as s:
        corrections = s.get(Project, project_id).corrections or []
    fixed = {op.get("note_id") for op in corrections}
    thr = get_settings().omr_confidence_threshold
    colors = {}
    for nid, c in confidence.get("notes", {}).items():
        if nid in fixed:
            colors[nid] = "#2b8a3e"
        elif c < thr * 0.8:
            colors[nid] = "#e03131"
        elif c < thr:
            colors[nid] = "#f08c00"
    return colors


# ---------------------------------------------------------------------------
# Transpose
# ---------------------------------------------------------------------------


def _options(settings: dict) -> TranspositionOptions:
    return TranspositionOptions(
        key_preference=settings.get("key_preference", "auto"),
        courtesy_accidentals=bool(settings.get("courtesy_accidentals", True)),
        part_ids=settings.get("part_ids") or None,
        simplify_double_accidentals=bool(settings.get("simplify_double_accidentals", False)),
    )


def run_transpose(project_id: str, progress) -> None:
    corrected = storage.read_bytes(project_id, "corrected.musicxml")
    if corrected is None:
        raise PipelineError("Analyze the score before transposing.")
    with session() as s:
        project = s.get(Project, project_id)
        src_spec, tgt_spec = project.source_instrument, project.target_instrument
        settings = dict(project.settings or {})
    if not src_spec or not tgt_spec:
        raise PipelineError("Select both the original and the target instrument.")
    try:
        source, target = resolve_instrument(src_spec), resolve_instrument(tgt_spec)
    except (KeyError, ValueError) as e:
        raise PipelineError(str(e))

    progress("transposing", f"Transposing from {source.name} to {target.name}…", 0.15)
    tree = parse_musicxml(corrected)
    try:
        raw, info = transpose_pitches(tree, source, target, _options(settings))
    except ValueError as e:
        raise PipelineError(str(e))
    storage.write_bytes(project_id, "transposed_raw.musicxml", to_bytes(raw))

    actions = []
    if settings.get("optimize_range"):
        adj = auto_correct_range(raw, target)
        if adj:
            actions.append({"id": 1, "kind": "optimize", "label": "Optimize for target instrument (automatic)",
                            "adjustments": adj})
    with session() as s:
        project = s.get(Project, project_id)
        project.range_actions = actions
        project.result = {"transposition": info.to_dict(), "source": source.to_dict(), "target": target.to_dict()}
        add_history(s, project_id, "transposed", source=source.name, target=target.name,
                    interval=info.interval_name)
    progress("validating", "Checking the transposed score…", 0.4)
    rebuild_final(project_id)
    progress("rendering", "Rendering sheet music…", 0.6)
    final = storage.read_bytes(project_id, "final.musicxml")
    pdf_for(project_id, final)
    progress("rendering", "Rendering preview…", 0.9)
    svg_pages(project_id, final, result_colors(project_id))


def rebuild_final(project_id: str) -> None:
    """transposed_raw + range actions → final.musicxml, validation, range report."""
    raw_bytes = storage.read_bytes(project_id, "transposed_raw.musicxml")
    corrected = storage.read_bytes(project_id, "corrected.musicxml")
    if raw_bytes is None or corrected is None:
        raise PipelineError("The score has not been transposed yet.")
    with session() as s:
        project = s.get(Project, project_id)
        actions = list(project.range_actions or [])
        settings = dict(project.settings or {})
        result = dict(project.result or {})
        target = resolve_instrument(project.target_instrument)
    raw = parse_musicxml(raw_bytes)
    all_adj = [a for act in actions for a in act.get("adjustments", [])]
    shifts = apply_adjustments(raw, all_adj)
    final, clef_changes = finalize(raw, target, _options(settings))
    storage.write_bytes(project_id, "final.musicxml", to_bytes(final))

    issues = check_range(final, target)
    validation = compare_transposition(
        parse_musicxml(corrected), final, result["transposition"]["semitones"], shifts,
        part_ids=_options(settings).part_ids, target_name=target.name,
    )
    kept = {nid for act in actions if act["kind"] == "keep" for nid in act.get("note_ids", [])}
    result.update({
        "clef_changes": clef_changes,
        "range": {
            "issues": [i.to_dict() | {"acknowledged": i.note_id in kept} for i in issues],
            "outside_typical": len(issues),
            "outside_extended": sum(1 for i in issues if i.severity == "outside_extended"),
            "unacknowledged": sum(1 for i in issues if i.note_id not in kept),
            "target_range": f"{target.range_low}–{target.range_high}",
        },
        "adjustments": [
            {"action_id": act["id"], "action": act["label"], **a}
            for act in actions for a in act.get("adjustments", [])
        ],
        "actions": [{"id": a["id"], "kind": a["kind"], "label": a["label"]} for a in actions],
        "octave_shifts": len(shifts),
        "validation": validation.to_dict(),
        "analysis": analyze(final),
    })
    with session() as s:
        project = s.get(Project, project_id)
        project.result = result
        project.result_stale = False


def result_colors(project_id: str) -> dict[str, str]:
    with session() as s:
        project = s.get(Project, project_id)
        result = project.result or {}
    colors = {}
    for a in result.get("adjustments", []):
        for nid in a.get("note_ids", []):
            colors[nid] = "#1971c2"
    for i in (result.get("range") or {}).get("issues", []):
        colors[i["note_id"]] = "#e03131" if not i.get("acknowledged") else "#f08c00"
    return colors


def add_range_action(project_id: str, kind: str, note_ids: list[str] | None = None, octaves: int = 0) -> dict:
    from core.validation.range import note_adjustments

    raw_bytes = storage.read_bytes(project_id, "transposed_raw.musicxml")
    if raw_bytes is None:
        raise PipelineError("Transpose the score first.")
    with session() as s:
        project = s.get(Project, project_id)
        actions = list(project.range_actions or [])
        target = resolve_instrument(project.target_instrument)
    raw = parse_musicxml(raw_bytes)
    apply_adjustments(raw, [a for act in actions for a in act.get("adjustments", [])])
    next_id = max((a["id"] for a in actions), default=0) + 1
    if kind == "auto":
        adj = auto_correct_range(raw, target)
        if not adj:
            raise PipelineError("No automatic range correction is possible or needed.")
        action = {"id": next_id, "kind": "auto", "label": "Automatic range correction", "adjustments": adj}
    elif kind == "move":
        if octaves not in (-2, -1, 1, 2) or not note_ids:
            raise PipelineError("Choose notes and an octave direction.")
        adj = note_adjustments(raw, note_ids, octaves)
        if not adj:
            raise PipelineError("None of the selected notes can be moved.")
        word = "up" if octaves > 0 else "down"
        action = {"id": next_id, "kind": "move", "label": f"Moved {len(adj)} note(s) {word} an octave",
                  "adjustments": adj}
    elif kind == "keep":
        ids = note_ids or [i.note_id for i in check_range(finalize(raw, target)[0], target)]
        action = {"id": next_id, "kind": "keep", "label": f"Kept original pitch for {len(ids)} note(s)",
                  "adjustments": [], "note_ids": ids}
    else:
        raise PipelineError("Unknown range action.")
    actions.append(action)
    with session() as s:
        project = s.get(Project, project_id)
        project.range_actions = actions
        add_history(s, project_id, "range_action", label=action["label"])
    rebuild_final(project_id)
    return action


def undo_range_action(project_id: str) -> None:
    with session() as s:
        project = s.get(Project, project_id)
        actions = list(project.range_actions or [])
        if not actions:
            raise PipelineError("Nothing to undo.")
        removed = actions.pop()
        project.range_actions = actions
        add_history(s, project_id, "range_undo", label=removed["label"])
    rebuild_final(project_id)


# ---------------------------------------------------------------------------
# Rendering cache
# ---------------------------------------------------------------------------


def svg_pages(project_id: str, musicxml: bytes, colors: dict[str, str]) -> list[str]:
    key = storage.content_hash(musicxml + json.dumps(colors, sort_keys=True).encode())
    rel = f"cache/svg-{key}.json"
    cached = storage.read_json(project_id, rel)
    if cached is not None:
        return cached
    pages = render.render_svg_pages(musicxml, colors)
    storage.write_json(project_id, rel, pages)
    return pages


def pdf_for(project_id: str, musicxml: bytes) -> tuple[bytes, str]:
    key = storage.content_hash(musicxml)
    meta = storage.read_json(project_id, f"cache/pdf-{key}.json")
    data = storage.read_bytes(project_id, f"cache/pdf-{key}.pdf")
    if data and meta:
        return data, meta["engine"]
    try:
        data, engine = render.render_pdf(musicxml)
    except render.RenderError as e:
        raise PipelineError(f"Rendering failed: {e}")
    storage.write_bytes(project_id, f"cache/pdf-{key}.pdf", data)
    storage.write_json(project_id, f"cache/pdf-{key}.json", {"engine": engine})
    with session() as s:
        project = s.get(Project, project_id)
        if project.result is not None:
            project.result = {**project.result, "pdf_engine": engine, "pdf_pages": render.pdf_page_count(data)}
    return data, engine


def midi_for(project_id: str, musicxml: bytes) -> bytes:
    key = storage.content_hash(musicxml)
    data = storage.read_bytes(project_id, f"cache/midi-{key}.mid")
    if data:
        return data
    try:
        data = render.render_midi(musicxml)
    except Exception as e:  # music21 can fail on exotic input
        raise PipelineError(f"MIDI export failed: {e}")
    storage.write_bytes(project_id, f"cache/midi-{key}.mid", data)
    return data
