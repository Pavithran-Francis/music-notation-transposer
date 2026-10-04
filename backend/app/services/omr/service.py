"""OMRService: document → pages → recognized MusicXML, independent of the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.services.omr.audiveris import AudiverisEngine
from app.services.omr.base import OMREngine, OMRError, OMRResult, ProgressCallback
from app.services.omr.preprocess import (
    PageInfo,
    load_image,
    make_thumbnail,
    pdf_embedded_musicxml,
    preprocess_page,
    rasterize_pdf,
)


@dataclass
class ParsedDocument:
    kind: str  # "pdf" | "image"
    pages: list[PageInfo] = field(default_factory=list)
    embedded_musicxml: bytes | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def usable_pages(self) -> list[PageInfo]:
        return [p for p in self.pages if not p.blank]


def default_engine() -> OMREngine:
    s = get_settings()
    return AudiverisEngine(s.resolved_audiveris(), s.audiveris_timeout_per_page)


class OMRService:
    def __init__(self, engine: OMREngine | None = None):
        self.engine = engine or default_engine()

    def parse_document(
        self,
        files: list[tuple[str, bytes]],
        workdir: Path,
        rotations: list[int] | None = None,
        crops: list[dict | None] | None = None,
        progress: ProgressCallback | None = None,
    ) -> ParsedDocument:
        """Turn uploaded PDF/images into preprocessed page images.

        `files` are (kind, bytes) with kind "pdf" or "image" (multi-image uploads
        become a multi-page score in upload order).
        """
        s = get_settings()
        progress = progress or (lambda *a: None)
        raw_dir = workdir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_pages: list[tuple[Path, bool]] = []  # (path, is_photo)
        doc = ParsedDocument(kind=files[0][0] if files else "image")
        for i, (kind, data) in enumerate(files):
            if kind == "pdf":
                emb = pdf_embedded_musicxml(data)
                if emb and len(files) == 1:
                    doc.embedded_musicxml = emb
                progress("preprocessing", "Reading PDF pages…", 0.02)
                for p in rasterize_pdf(data, raw_dir / f"f{i}", s.render_dpi, s.max_pdf_pages):
                    raw_pages.append((p, False))
            else:
                p = load_image(data, raw_dir / f"img-{i}.png", s.max_image_pixels)
                raw_pages.append((p, _looks_like_photo(p)))
        if len(raw_pages) > s.max_pdf_pages:
            raise OMRError(f"Too many pages ({len(raw_pages)}); the limit is {s.max_pdf_pages}.")
        rotations = rotations or []
        crops = crops or []
        for idx, (p, is_photo) in enumerate(raw_pages):
            progress("preprocessing", f"Preparing page {idx + 1} of {len(raw_pages)}…", 0.05)
            info = preprocess_page(
                p, workdir / "pages" / f"page-{idx + 1}.png", idx,
                user_rotation=rotations[idx] if idx < len(rotations) else 0,
                is_photo=is_photo,
                crop=crops[idx] if idx < len(crops) else None,
            )
            make_thumbnail(info.path, workdir / "thumbs" / f"page-{idx + 1}.png")
            doc.pages.append(info)
            doc.warnings.extend(info.warnings)
        if not doc.usable_pages and not doc.embedded_musicxml:
            raise OMRError("All pages appear to be blank.")
        return doc

    def recognize_pages(self, doc: ParsedDocument, workdir: Path, progress: ProgressCallback) -> OMRResult:
        pages = [p.path for p in doc.usable_pages]
        if not pages:
            raise OMRError("There are no pages with music to recognize.")
        result = self.engine.recognize(pages, workdir / "omr", progress)
        result.warnings = doc.warnings + result.warnings
        return result

    @staticmethod
    def export_musicxml(result: OMRResult) -> bytes:
        return result.musicxml


def _looks_like_photo(path: Path) -> bool:
    """Heuristic: photos have colour/grey backgrounds; scans/renders are mostly pure white."""
    import cv2
    import numpy as np

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return False
    small = cv2.resize(img, (400, int(400 * img.shape[0] / max(1, img.shape[1]))))
    white = float((small > 235).mean())
    return white < 0.5
