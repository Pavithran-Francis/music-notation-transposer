"""OMRService: document → pages → recognized MusicXML, independent of the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
import logging
from concurrent.futures import ThreadPoolExecutor

from app.services.omr.audiveris import AudiverisEngine
from app.services.omr.homr import HomrEngine
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
    source_pdf: Path | None = None  # original PDF, kept when pages need no image edits
    warnings: list[str] = field(default_factory=list)

    @property
    def usable_pages(self) -> list[PageInfo]:
        return [p for p in self.pages if not p.blank]


log = logging.getLogger("smt.omr")


def default_engine() -> OMREngine:
    s = get_settings()
    return AudiverisEngine(s.resolved_audiveris(), s.audiveris_timeout_per_page)


def secondary_engine() -> OMREngine | None:
    s = get_settings()
    if not s.omr_ensemble:
        return None
    engine = HomrEngine(s.resolved_homr(), s.homr_timeout_per_page)
    return engine if engine.is_available() else None


class OMRService:
    def __init__(self, engine: OMREngine | None = None, secondary: OMREngine | None | bool = True):
        self.engine = engine or default_engine()
        # secondary=True → use the configured second engine if installed; None/False → primary only
        self.secondary = secondary_engine() if secondary is True else (secondary or None)

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
                if len(files) == 1:
                    doc.source_pdf = raw_dir / "original.pdf"
                    doc.source_pdf.write_bytes(data)
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
        """Recognize with the primary engine and, when available, a second engine in
        parallel; the two readings are merged measure by measure (core.omr_merge)."""
        pages = [p.path for p in doc.usable_pages]
        if not pages:
            raise OMRError("There are no pages with music to recognize.")
        untouched = doc.source_pdf is not None and all(not p.actions and not p.blank for p in doc.pages)
        source_pdf = doc.source_pdf if untouched else None
        second = None
        if self.secondary is None:
            result = self.engine.recognize(pages, workdir / "omr", progress, source_pdf=source_pdf)
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                primary_future = pool.submit(self.engine.recognize, pages, workdir / "omr", progress, source_pdf)
                secondary_future = pool.submit(self.secondary.recognize, pages, workdir / "omr2", lambda *a: None)
                result = primary_future.result()
                progress("recognizing", "Cross-checking with the second recognition engine…", 0.99)
                try:
                    second = secondary_future.result()
                except Exception as e:  # the second engine is an improvement, never a requirement
                    log.warning("secondary OMR failed: %s", e)
        result.warnings = doc.warnings + result.warnings
        self._postprocess(result, second, pages)
        return result

    def _postprocess(self, result: OMRResult, second: OMRResult | None, pages: list[Path]) -> None:
        """Merge the readings and fix multi-measure rest counts from the page images."""
        from core import multirest
        from core.musicxml.document import parse_musicxml, to_bytes
        from core.omr_merge import merge_readings

        try:
            tree = multirest.collapse(parse_musicxml(result.musicxml))
        except Exception as e:
            log.warning("could not normalise OMR output: %s", e)
            return
        if second is not None:
            try:
                merged, report = merge_readings(tree, multirest.collapse(parse_musicxml(second.musicxml)))
            except Exception as e:
                log.warning("OMR merge failed: %s", e)
            else:
                result.merge = report.to_dict()
                if report.applied:
                    tree = merged
                    result.engine = f"{self.engine.name} + {self.secondary.name}"

        # Multi-measure rest counts: engines misread multi-digit numbers, so read them from the page.
        try:
            from app.services.omr.multirest import detect_on_pages

            detections = detect_on_pages(pages)
        except Exception as e:
            log.warning("multi-measure rest detection failed: %s", e)
            detections = []
        toks = multirest.tokens(tree)
        token_index = {id(m): i for i, m in enumerate(tree.getroot().find("part").findall("measure"))}
        aligned = len(detections) == len(toks)
        for k, m in enumerate(toks):
            engine_count = multirest._count(m)
            det = detections[k] if aligned else None
            entry = {"index": token_index[id(m)], "engine_count": engine_count, "count": engine_count,
                     "source": "engine", "confidence": None, "flagged": True}
            if det is not None and det.count:
                multirest.set_count(m, det.count)
                entry.update(count=det.count, source="page image", confidence=det.confidence,
                             flagged=det.confidence < 0.6)
            result.multirests.append(entry)
        index_map = multirest.expand(tree)
        for entry in result.multirests:
            entry["index"] = index_map[entry["index"]]
        if result.merge:
            for d in result.merge.get("measures", []):
                if d.get("out_index") is not None:
                    d["out_index"] = index_map[d["out_index"]]
        numbers = [m.get("number") for m in tree.getroot().find("part").findall("measure")]
        for entry in result.multirests:
            entry["measure"] = numbers[entry["index"]]
        if result.merge:
            for d in result.merge.get("measures", []):
                if d.get("out_index") is not None:
                    d["number"] = numbers[d["out_index"]]
        result.musicxml = to_bytes(tree)

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
