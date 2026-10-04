"""Per-project file storage on the local filesystem.

Layout of data/projects/<id>/:
    upload/original.<ext>       the untouched uploaded file
    pages/page-<n>.png          preprocessed page images (OMR input)
    thumbs/page-<n>.png         small previews
    omr/                        OMR engine working directory
    source.musicxml             recognized / uploaded score (never modified afterwards)
    confidence.json             per-note recognition confidence
    corrected.musicxml          source + recognition corrections
    transposed_raw.musicxml     pitch-transposed (before range adjustments / clefs)
    final.musicxml              the result
    cache/<hash>/...            rendered SVG / PDF / MIDI keyed by content hash

The storage root can be swapped for an S3-compatible backend by replacing this
module; nothing else touches paths directly.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from app.config import get_settings


def project_dir(project_id: str) -> Path:
    if not project_id.isalnum():
        raise ValueError("invalid project id")
    d = get_settings().data_dir / "projects" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(project_id: str, *parts: str) -> Path:
    p = project_dir(project_id).joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_bytes(project_id: str, rel: str, data: bytes) -> Path:
    p = path(project_id, rel)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


def read_bytes(project_id: str, rel: str) -> bytes | None:
    p = project_dir(project_id) / rel
    return p.read_bytes() if p.exists() else None


def write_json(project_id: str, rel: str, obj) -> Path:
    return write_bytes(project_id, rel, json.dumps(obj).encode())


def read_json(project_id: str, rel: str, default=None):
    data = read_bytes(project_id, rel)
    return json.loads(data) if data else default


def exists(project_id: str, rel: str) -> bool:
    return (project_dir(project_id) / rel).exists()


def remove(project_id: str, rel: str) -> None:
    p = project_dir(project_id) / rel
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink()


def delete_project_files(project_id: str) -> None:
    d = get_settings().data_dir / "projects" / project_id
    shutil.rmtree(d, ignore_errors=True)


def copy_project_files(src_id: str, dst_id: str) -> None:
    src = get_settings().data_dir / "projects" / src_id
    dst = get_settings().data_dir / "projects" / dst_id
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("cache", "omr"))


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:24]
