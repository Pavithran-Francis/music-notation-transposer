"""REST API (OpenAPI docs at /docs)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import HistoryEntry, Job, Project, add_history, new_id, session
from app.services import jobs, pipeline, storage
from app.services.omr.service import default_engine, secondary_engine
from app.services.pipeline import PipelineError
from app.services.rendering import service as render
from core.corrections import CorrectionError, note_details, validate_operation
from core.instruments.database import INSTRUMENTS, resolve_instrument
from core.music.clefs import CLEFS
from core.musicxml.document import parse_musicxml, to_bytes

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _get(s, project_id: str) -> Project:
    project = s.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found.")
    return project


def _latest_job(s, project_id: str) -> dict | None:
    job = s.scalars(select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())).first()
    return _job_dict(job) if job else None


def _job_dict(job: Job) -> dict:
    return {"id": job.id, "project_id": job.project_id, "kind": job.kind, "status": job.status,
            "step": job.step, "message": job.message, "progress": job.progress, "error": job.error}


def _project_dict(p: Project, s=None, full: bool = True) -> dict:
    d = {
        "id": p.id, "name": p.name, "saved": p.saved, "status": p.status,
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
        "source_kind": p.source_kind, "original_filename": p.original_filename,
        "page_count": p.page_count, "source_instrument": p.source_instrument,
        "target_instrument": p.target_instrument, "error": p.error,
        "has_result": p.result is not None, "result_stale": p.result_stale,
    }
    if full:
        d.update({
            "settings": p.settings or {}, "page_rotations": p.page_rotations or [],
            "corrections": p.corrections or [], "analysis": p.analysis, "recognition": p.recognition,
            "result": p.result, "job": _latest_job(s, p.id) if s is not None else None,
        })
    return d


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PipelineError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# system / instruments
# ---------------------------------------------------------------------------


@router.get("/health", tags=["system"])
def health() -> dict:
    engine = default_engine()
    second = secondary_engine()
    s = get_settings()
    return {
        "status": "ok",
        "omr": {
            "engine": engine.name + (f" + {second.name}" if second else ""),
            "available": engine.is_available(),
            "secondary": second.name if second else None,
            "ocr_languages": s.ocr_languages(),
        },
        "musescore": {"available": render.mscore_available(), "path": s.resolved_mscore()},
        "renderer": "MuseScore" if render.mscore_available() else "Verovio",
        "limits": {"max_upload_mb": s.max_upload_mb, "max_pdf_pages": s.max_pdf_pages},
        "retention_hours": s.retention_hours,
    }


@router.get("/instruments", tags=["instruments"])
def instruments() -> dict:
    return {
        "instruments": [i.to_dict() for i in INSTRUMENTS],
        "clefs": [{"id": c.id, "label": c.label} for c in CLEFS.values() if c.id != "percussion"],
    }


class CustomInstrument(BaseModel):
    id: Literal["custom"] = "custom"
    name: str = "Custom instrument"
    interval: str = "P1"
    direction: Literal["up", "down"] = "down"
    octave_displacement: int = Field(0, ge=-3, le=3)
    clef: str = "treble"
    range_low: str = "C3"
    range_high: str = "C7"
    staves: int = Field(1, ge=1, le=4)


@router.post("/instruments/validate", tags=["instruments"])
def validate_instrument(spec: CustomInstrument) -> dict:
    try:
        return resolve_instrument(spec.model_dump()).to_dict()
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Invalid custom instrument: {e}")


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field("Untitled score", max_length=200)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    saved: bool | None = None
    source_instrument: dict[str, Any] | None = None
    target_instrument: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


ALLOWED_SETTINGS = {"key_preference", "courtesy_accidentals", "part_ids", "simplify_double_accidentals",
                    "optimize_range"}


@router.post("/projects", tags=["projects"], status_code=201)
def create_project(body: ProjectCreate | None = None) -> dict:
    with session() as s:
        p = Project(name=(body.name if body else "Untitled score") or "Untitled score")
        s.add(p)
        s.flush()
        add_history(s, p.id, "created")
        return _project_dict(p, s)


@router.get("/projects", tags=["projects"])
def list_projects() -> dict:
    with session() as s:
        items = s.scalars(select(Project).order_by(Project.updated_at.desc())).all()
        return {"projects": [_project_dict(p, full=False) for p in items]}


@router.get("/projects/{project_id}", tags=["projects"])
def get_project(project_id: str) -> dict:
    with session() as s:
        return _project_dict(_get(s, project_id), s)


@router.patch("/projects/{project_id}", tags=["projects"])
def update_project(project_id: str, body: ProjectUpdate) -> dict:
    with session() as s:
        p = _get(s, project_id)
        if body.name is not None:
            p.name = body.name.strip() or "Untitled score"
            add_history(s, p.id, "renamed", name=p.name)
        if body.saved is not None:
            p.saved = body.saved
            add_history(s, p.id, "saved" if body.saved else "unsaved")
        for field in ("source_instrument", "target_instrument"):
            spec = getattr(body, field)
            if spec is not None:
                try:
                    inst = resolve_instrument(spec)
                except (KeyError, ValueError, TypeError) as e:
                    raise HTTPException(400, f"Invalid instrument: {e}")
                if getattr(p, field) != spec:
                    setattr(p, field, spec)
                    if p.result is not None:
                        p.result_stale = True
                    add_history(s, p.id, f"{field}_set", instrument=inst.name)
        if body.settings is not None:
            unknown = set(body.settings) - ALLOWED_SETTINGS
            if unknown:
                raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")
            p.settings = {**(p.settings or {}), **body.settings}
            if p.result is not None:
                p.result_stale = True
        s.flush()
        return _project_dict(p, s)


@router.delete("/projects/{project_id}", tags=["projects"], status_code=204)
def delete_project(project_id: str) -> Response:
    with session() as s:
        p = _get(s, project_id)
        s.delete(p)
    storage.delete_project_files(project_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/duplicate", tags=["projects"], status_code=201)
def duplicate_project(project_id: str) -> dict:
    with session() as s:
        src = _get(s, project_id)
        if src.status in ("analyzing", "transposing"):
            raise HTTPException(409, "Wait for processing to finish before duplicating.")
        dst = Project(id=new_id())
        for col in ("source_kind", "original_filename", "page_count", "page_rotations", "source_instrument",
                    "target_instrument", "settings", "corrections", "range_actions", "analysis", "recognition",
                    "result", "result_stale", "status", "saved"):
            setattr(dst, col, getattr(src, col))
        dst.name = f"{src.name} (copy)"
        s.add(dst)
        s.flush()
        add_history(s, dst.id, "duplicated", source=src.id)
        storage.copy_project_files(src.id, dst.id)
        return _project_dict(dst, s)


@router.get("/projects/{project_id}/history", tags=["projects"])
def history(project_id: str) -> dict:
    with session() as s:
        _get(s, project_id)
        rows = s.scalars(select(HistoryEntry).where(HistoryEntry.project_id == project_id)
                         .order_by(HistoryEntry.at)).all()
        return {"history": [{"at": h.at.isoformat(), "action": h.action, "detail": h.detail} for h in rows]}


# ---------------------------------------------------------------------------
# upload & pages
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/upload", tags=["upload"])
async def upload(project_id: str, files: list[UploadFile] = File(...)) -> dict:
    limit = get_settings().max_upload_mb * 1024 * 1024
    payload = []
    for f in files[:50]:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"'{f.filename}' exceeds the {get_settings().max_upload_mb} MB limit.")
        if not data:
            raise HTTPException(400, f"'{f.filename}' is empty.")
        payload.append((f.filename or "upload", data))
    with session() as s:
        p = _get(s, project_id)
        if p.status in ("analyzing", "transposing"):
            raise HTTPException(409, "Processing is in progress.")
    fields = await run_in_threadpool(_guard, pipeline.store_upload, project_id, payload)
    with session() as s:
        p = _get(s, project_id)
        for k, v in fields.items():
            setattr(p, k, v)
        p.status = "uploaded"
        p.analysis = p.recognition = p.result = None
        p.corrections, p.range_actions = [], []
        p.error = None
        if p.name in ("Untitled score", "") and payload:
            p.name = payload[0][0].rsplit(".", 1)[0][:200] or p.name
        add_history(s, p.id, "uploaded", files=[n for n, _ in payload], kind=fields["source_kind"])
        s.flush()
        return _project_dict(p, s)


@router.get("/projects/{project_id}/pages/{page}/thumbnail", tags=["upload"])
def page_thumbnail(project_id: str, page: int) -> Response:
    data = storage.read_bytes(project_id, f"thumbs/page-{page}.png")
    if data is None:
        raise HTTPException(404, "No preview for this page.")
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-cache"})


class Rotate(BaseModel):
    degrees: Literal[90, 180, 270, -90]


@router.post("/projects/{project_id}/pages/{page}/rotate", tags=["upload"])
def rotate_page(project_id: str, page: int, body: Rotate) -> dict:
    with session() as s:
        p = _get(s, project_id)
        if not 1 <= page <= p.page_count:
            raise HTTPException(404, "Page not found.")
        rot = list(p.page_rotations or [0] * p.page_count)
        rot[page - 1] = (rot[page - 1] + body.degrees) % 360
        p.page_rotations = rot
        pipeline.rotate_thumbnail(project_id, page, body.degrees)
        return {"page_rotations": rot}


# ---------------------------------------------------------------------------
# analysis & corrections
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/analyze", tags=["analysis"], status_code=202)
def start_analyze(project_id: str) -> dict:
    with session() as s:
        p = _get(s, project_id)
        if not p.source_kind:
            raise HTTPException(400, "Upload a score first.")
    job_id = jobs.submit(project_id, "analyze", pipeline.run_analyze)
    return {"job_id": job_id}


@router.get("/projects/{project_id}/analysis", tags=["analysis"])
def get_analysis(project_id: str) -> dict:
    with session() as s:
        p = _get(s, project_id)
        if p.analysis is None:
            raise HTTPException(404, "The score has not been analyzed yet.")
        return {"analysis": p.analysis, "recognition": p.recognition, "corrections": p.corrections or [],
                "source_instrument": p.source_instrument}


class Correction(BaseModel):
    op: Literal["set_pitch", "to_rest", "to_note", "delete_chord_note", "set_duration", "set_key", "set_time",
                "set_clef", "set_metadata"]
    title: str | None = Field(None, max_length=300)
    composer: str | None = Field(None, max_length=300)
    note_id: str | None = None
    step: str | None = None
    alter: int | None = None
    octave: int | None = None
    type: str | None = None
    dots: int | None = None
    measure_index: int | None = None
    part_id: str | None = None
    staff: int | None = None
    fifths: int | None = None
    mode: str | None = None
    beats: int | None = None
    beat_type: int | None = None
    clef: str | None = None


@router.patch("/projects/{project_id}/corrections", tags=["analysis"])
def add_correction(project_id: str, body: Correction) -> dict:
    op = body.model_dump(exclude_none=True)
    corrected = storage.read_bytes(project_id, "corrected.musicxml")
    if corrected is None:
        raise HTTPException(400, "Analyze the score first.")
    try:
        validate_operation(parse_musicxml(corrected), op)
    except CorrectionError as e:
        raise HTTPException(400, str(e))
    with session() as s:
        p = _get(s, project_id)
        p.corrections = list(p.corrections or []) + [op]
        add_history(s, project_id, "correction", **op)
    _guard(pipeline.rebuild_corrected, project_id)
    return get_analysis(project_id)


@router.delete("/projects/{project_id}/corrections/last", tags=["analysis"])
def undo_correction(project_id: str) -> dict:
    with session() as s:
        p = _get(s, project_id)
        if not p.corrections:
            raise HTTPException(400, "Nothing to undo.")
        p.corrections = list(p.corrections)[:-1]
        add_history(s, project_id, "correction_undo")
    _guard(pipeline.rebuild_corrected, project_id)
    return get_analysis(project_id)


@router.get("/projects/{project_id}/notes/{note_id}", tags=["analysis"])
def get_note(project_id: str, note_id: str, which: Literal["original", "result"] = "original") -> dict:
    rel = "corrected.musicxml" if which == "original" else "final.musicxml"
    data = storage.read_bytes(project_id, rel)
    if data is None:
        raise HTTPException(404, "Score not available.")
    details = note_details(parse_musicxml(data), note_id)
    if details is None:
        raise HTTPException(404, "Note not found.")
    conf = (storage.read_json(project_id, "confidence.json") or {}).get("notes", {})
    details["confidence"] = conf.get(note_id)
    return details


# ---------------------------------------------------------------------------
# transposition & range
# ---------------------------------------------------------------------------


class TransposeRequest(BaseModel):
    source_instrument: dict[str, Any] | None = None
    target_instrument: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


@router.post("/projects/{project_id}/transpose", tags=["transposition"], status_code=202)
def start_transpose(project_id: str, body: TransposeRequest | None = None) -> dict:
    if body:
        update_project(project_id, ProjectUpdate(source_instrument=body.source_instrument,
                                                 target_instrument=body.target_instrument,
                                                 settings=body.settings))
    with session() as s:
        p = _get(s, project_id)
        if p.analysis is None:
            raise HTTPException(400, "Analyze the score first.")
        if not p.source_instrument or not p.target_instrument:
            raise HTTPException(400, "Select both the original and the target instrument.")
    return {"job_id": jobs.submit(project_id, "transpose", pipeline.run_transpose)}


@router.get("/projects/{project_id}/result", tags=["transposition"])
def get_result(project_id: str) -> dict:
    with session() as s:
        p = _get(s, project_id)
        if p.result is None or not storage.exists(project_id, "final.musicxml"):
            raise HTTPException(404, "No transposed score yet.")
        return {"result": p.result, "stale": p.result_stale}


class RangeAction(BaseModel):
    action: Literal["auto", "move", "keep"]
    note_ids: list[str] | None = None
    octaves: int = 0


@router.post("/projects/{project_id}/range", tags=["transposition"])
def range_action(project_id: str, body: RangeAction) -> dict:
    _guard(pipeline.add_range_action, project_id, body.action, body.note_ids, body.octaves)
    return get_result(project_id)


@router.delete("/projects/{project_id}/range/last", tags=["transposition"])
def undo_range(project_id: str) -> dict:
    _guard(pipeline.undo_range_action, project_id)
    return get_result(project_id)


# ---------------------------------------------------------------------------
# preview & export
# ---------------------------------------------------------------------------


def _score_bytes(project_id: str, which: str) -> bytes:
    rel = {"original": "corrected.musicxml", "result": "final.musicxml"}[which]
    data = storage.read_bytes(project_id, rel)
    if data is None:
        raise HTTPException(404, "This score is not available yet.")
    return data


def _colors(project_id: str, which: str) -> dict:
    return pipeline.original_colors(project_id) if which == "original" else pipeline.result_colors(project_id)


@router.get("/projects/{project_id}/preview", tags=["preview"])
def preview_info(project_id: str, which: Literal["original", "result"] = "result") -> dict:
    data = _score_bytes(project_id, which)
    pages = _guard(pipeline.svg_pages, project_id, data, _colors(project_id, which))
    return {"pages": len(pages)}


@router.get("/projects/{project_id}/preview/{which}/{page}", tags=["preview"])
def preview_page(project_id: str, which: Literal["original", "result"], page: int) -> Response:
    data = _score_bytes(project_id, which)
    pages = _guard(pipeline.svg_pages, project_id, data, _colors(project_id, which))
    if not 1 <= page <= len(pages):
        raise HTTPException(404, "Page out of range.")
    return Response(pages[page - 1], media_type="image/svg+xml")


def _filename(project_id: str, ext: str) -> str:
    with session() as s:
        p = _get(s, project_id)
        target = (p.result or {}).get("target", {}).get("name", "transposed")
        base = f"{p.name} - {target}"
    safe = "".join(c if c.isalnum() or c in " -_()." else "_" for c in base).strip() or "score"
    return f"{safe}.{ext}"


def _download(data: bytes, media: str, filename: str) -> Response:
    from urllib.parse import quote

    return Response(data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"score\"; filename*=UTF-8''{quote(filename)}"
    })


@router.get("/projects/{project_id}/export/musicxml", tags=["export"])
def export_musicxml(project_id: str, which: Literal["original", "result"] = "result") -> Response:
    data = to_bytes(parse_musicxml(_score_bytes(project_id, which)), strip_ids=True)
    name = _filename(project_id, "musicxml") if which == "result" else "recognized.musicxml"
    return _download(data, "application/vnd.recordare.musicxml+xml", name)


@router.get("/projects/{project_id}/export/pdf", tags=["export"])
async def export_pdf(project_id: str, which: Literal["original", "result"] = "result") -> Response:
    data = _score_bytes(project_id, which)
    pdf, _ = await run_in_threadpool(_guard, pipeline.pdf_for, project_id, data)
    return _download(pdf, "application/pdf", _filename(project_id, "pdf"))


@router.get("/projects/{project_id}/export/midi", tags=["export"])
async def export_midi(project_id: str, which: Literal["original", "result"] = "result") -> Response:
    data = _score_bytes(project_id, which)
    mid = await run_in_threadpool(_guard, pipeline.midi_for, project_id, data)
    return _download(mid, "audio/midi", _filename(project_id, "mid"))


@router.get("/projects/{project_id}/export/png", tags=["export"])
async def export_png(project_id: str, page: int = Query(1, ge=1)) -> Response:
    data = _score_bytes(project_id, "result")
    pdf, _ = await run_in_threadpool(_guard, pipeline.pdf_for, project_id, data)
    try:
        png = render.render_png(pdf, page, dpi=200)
    except render.RenderError as e:
        raise HTTPException(404, str(e))
    return _download(png, "image/png", _filename(project_id, f"p{page}.png"))


@router.get("/projects/{project_id}/export/svg", tags=["export"])
def export_svg(project_id: str, page: int = Query(1, ge=1)) -> Response:
    data = _score_bytes(project_id, "result")
    pages = render.render_svg_pages(to_bytes(parse_musicxml(data), strip_ids=True))
    if page > len(pages):
        raise HTTPException(404, "Page out of range.")
    return _download(pages[page - 1].encode(), "image/svg+xml", _filename(project_id, f"p{page}.svg"))


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str) -> dict:
    with session() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        return _job_dict(job)
