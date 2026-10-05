"""Page extraction and image preprocessing for OMR.

PDF pages are rasterised at 300 DPI; images are loaded with EXIF orientation
applied. Every page then goes through: manual rotation (user), automatic 90°
rotation detection, perspective correction (photographs), deskew, grayscale,
denoise, contrast normalisation and resolution normalisation based on the
detected staff-line spacing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps

from app.services.omr.base import OMRError

# Audiveris works best with a staff interline of ~15-25 px (300 DPI print).
TARGET_INTERLINE = 20
MIN_INTERLINE = 9


@dataclass
class PageInfo:
    index: int
    path: Path
    width: int
    height: int
    interline: float | None
    blank: bool = False
    warnings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "index": self.index, "width": self.width, "height": self.height,
            "interline": self.interline, "blank": self.blank,
            "warnings": self.warnings, "actions": self.actions,
        }


def pdf_embedded_musicxml(pdf_bytes: bytes) -> bytes | None:
    """Return MusicXML embedded in a PDF as an attachment, if any."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None
    try:
        for name in doc.embfile_names():
            if name.lower().endswith((".musicxml", ".xml", ".mxl")):
                data = doc.embfile_get(name)
                if data[:2] == b"PK" or b"score-partwise" in data[:4000] or b"score-timewise" in data[:4000]:
                    return data
    finally:
        doc.close()
    return None


def rasterize_pdf(pdf_bytes: bytes, out_dir: Path, dpi: int, max_pages: int) -> list[Path]:
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise OMRError("The PDF could not be opened. It may be corrupt or not a PDF.") from e
    try:
        if doc.needs_pass:
            raise OMRError("The PDF is password-protected. Please upload an unprotected copy.")
        if doc.page_count == 0:
            raise OMRError("The PDF has no pages.")
        if doc.page_count > max_pages:
            raise OMRError(f"The PDF has {doc.page_count} pages; the limit is {max_pages}.")
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, page in enumerate(doc):
            # Cap the pixel count for very large page sizes.
            zoom = dpi / 72
            w, h = page.rect.width * zoom, page.rect.height * zoom
            if w * h > 60_000_000:
                zoom *= (60_000_000 / (w * h)) ** 0.5
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
            p = out_dir / f"raw-{i + 1}.png"
            pix.save(str(p))
            paths.append(p)
        return paths
    finally:
        doc.close()


def load_image(data: bytes, out: Path, max_pixels: int) -> Path:
    import io

    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as e:
        raise OMRError("The image is too large to process safely.") from e
    except Exception as e:
        raise OMRError("The image could not be read. Supported formats are PNG and JPEG.") from e
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")
    return out


# ---------------------------------------------------------------------------
# analysis helpers
# ---------------------------------------------------------------------------


def _binarize(gray: np.ndarray) -> np.ndarray:
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return bw


def estimate_interline(gray: np.ndarray) -> float | None:
    """Estimate staff-line spacing from vertical run lengths of white between black runs."""
    bw = _binarize(gray)
    h, w = bw.shape
    cols = np.linspace(w * 0.2, w * 0.8, 40).astype(int)
    gaps: list[int] = []
    for x in cols:
        col = bw[:, x] > 0
        # positions where black runs start
        changes = np.flatnonzero(np.diff(col.astype(np.int8)) == 1)
        if len(changes) > 4:
            d = np.diff(changes)
            gaps.extend(d[(d > 4) & (d < 80)].tolist())
    if len(gaps) < 20:
        return None
    hist = np.bincount(gaps)
    return float(np.argmax(hist))


def staff_line_strength(bw: np.ndarray) -> float:
    """How strongly the image contains long horizontal lines (0..1)."""
    h, w = bw.shape
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 8), 1))
    lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
    return float(lines.sum()) / max(1.0, float(bw.sum()))


def detect_skew_angle(bw: np.ndarray) -> float:
    """Dominant angle (degrees) of long near-horizontal lines."""
    h, w = bw.shape
    lines = cv2.HoughLinesP(bw, 1, np.pi / 1800, threshold=200, minLineLength=w // 4, maxLineGap=20)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) < 15:
            angles.append(a)
    if not angles:
        return 0.0
    return float(np.median(angles))


def rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(gray, m, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=255)


def perspective_correct(gray: np.ndarray) -> tuple[np.ndarray, bool]:
    """If the page is a photographed sheet on a darker background, warp it flat."""
    h, w = gray.shape
    small_scale = 1000 / max(h, w)
    small = cv2.resize(gray, (int(w * small_scale), int(h * small_scale)))
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray, False
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    sh, sw = small.shape
    if area < 0.3 * sh * sw or area > 0.97 * sh * sw:
        return gray, False
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(approx) != 4:
        return gray, False
    pts = approx.reshape(4, 2).astype(np.float32) / small_scale
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    tl, br = pts[np.argmin(s)], pts[np.argmax(s)]
    tr, bl = pts[np.argmin(d)], pts[np.argmax(d)]
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if width < 200 or height < 200:
        return gray, False
    src = np.array([tl, tr, br, bl], dtype=np.float32)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, m, (width, height), flags=cv2.INTER_CUBIC, borderValue=255), True


def preprocess_page(src: Path, dst: Path, index: int, user_rotation: int = 0, is_photo: bool = False,
                    crop: dict | None = None) -> PageInfo:
    gray = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise OMRError(f"Page {index + 1} could not be decoded.")
    actions: list[str] = []
    warnings: list[str] = []

    if user_rotation % 360:
        k = (user_rotation // 90) % 4
        gray = np.ascontiguousarray(np.rot90(gray, -k))
        actions.append(f"rotated {user_rotation}° (manual)")

    if crop:
        h, w = gray.shape
        x0, y0 = int(crop.get("x", 0) * w), int(crop.get("y", 0) * h)
        x1, y1 = int((crop.get("x", 0) + crop.get("w", 1)) * w), int((crop.get("y", 0) + crop.get("h", 1)) * h)
        if x1 - x0 > 100 and y1 - y0 > 100:
            gray = gray[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
            actions.append("cropped (manual)")

    if is_photo:
        gray, warped = perspective_correct(gray)
        if warped:
            actions.append("perspective corrected")

    bw = _binarize(gray)
    ink = float((bw > 0).mean())
    if ink < 0.003:
        info = PageInfo(index, dst, gray.shape[1], gray.shape[0], None, blank=True,
                        warnings=[f"Page {index + 1} appears to be blank and was skipped."], actions=actions)
        cv2.imwrite(str(dst), gray)
        return info

    # Automatic 90° rotation: staff lines must be horizontal.
    if user_rotation % 360 == 0:
        horiz = staff_line_strength(bw)
        vert = staff_line_strength(np.ascontiguousarray(bw.T))
        if vert > 2 * horiz and vert > 0.05:
            gray = np.ascontiguousarray(np.rot90(gray, -1))
            bw = _binarize(gray)
            actions.append("rotated 90° (staff lines were vertical)")

    angle = detect_skew_angle(bw)
    if abs(angle) > 0.15:
        gray = rotate(gray, angle)
        actions.append(f"deskewed by {angle:.2f}°")

    # Light denoise + contrast normalisation (helps photos/scans, harmless on clean PDFs).
    if is_photo or ink > 0.25:
        gray = cv2.fastNlMeansDenoising(gray, None, h=12, templateWindowSize=7, searchWindowSize=21)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        actions.append("denoised and contrast-normalised")
    if is_photo:
        gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)
        actions.append("adaptive binarisation (photo)")

    interline = estimate_interline(gray)
    if interline is None:
        warnings.append(f"No staff lines were detected on page {index + 1}. It may not contain sheet music.")
    else:
        if interline < MIN_INTERLINE:
            warnings.append(
                f"Page {index + 1} has a low resolution (staff spacing {interline:.0f}px). Recognition may be "
                "unreliable; try uploading a scan at 300 DPI or higher."
            )
        scale = TARGET_INTERLINE / interline
        if scale > 1.25 or scale < 0.6:
            scale = min(scale, 3.0)
            gray = cv2.resize(gray, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
            actions.append(f"resolution normalised ×{scale:.2f}")
            interline *= scale

    dst.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst), gray)
    return PageInfo(index, dst, gray.shape[1], gray.shape[0], interline, False, warnings, actions)


def make_thumbnail(src: Path, dst: Path, width: int = 1200) -> None:
    img = Image.open(src)
    img.thumbnail((width, width * 2))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, format="PNG", optimize=True)


def images_to_tiff(images: list[Path], out: Path, dpi: int = 300) -> Path:
    """Bundle page images into one lossless multi-page TIFF (one book for the OMR engine).

    Pixels reach the engine exactly as preprocessed; earlier versions wrapped the
    images in a PDF, which the engine re-rendered and which measurably hurt accuracy.
    """
    frames = [Image.open(p).convert("L") for p in images]
    frames[0].save(out, format="TIFF", save_all=True, append_images=frames[1:], compression="tiff_lzw", dpi=(dpi, dpi))
    return out
