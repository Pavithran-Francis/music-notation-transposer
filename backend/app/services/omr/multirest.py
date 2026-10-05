"""Multi-measure rest detection and count reading.

Both OMR engines recognize the H-shaped multi-measure rest bar but misread the
number printed above it (Audiveris only reads single digits, so "12" becomes
"2"; homr guesses). This module finds the bars directly on the page image and
reads the count by template matching against real music-font digits.

A multi-measure rest is:
  * a thick horizontal bar (≈0.5–0.9 staff spaces tall, several spaces wide)
    centred on the staff's middle line,
  * with short vertical serifs at both ends spanning about two staff spaces,
  * and a number centred above the staff.
Beams are told apart by their stems (much longer vertical strokes) and by not
sitting on the middle staff line.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "fonts"
TEMPLATE_SIZE = (24, 36)  # w, h


@dataclass
class MultiRest:
    page: int
    x: int
    y: int  # bar centre
    width: int
    count: int | None
    confidence: float  # digit match quality 0..1 (0 when unreadable)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# digit templates
# ---------------------------------------------------------------------------


def _text_fonts() -> list[Path]:
    candidates = [
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
    ]
    return [Path(c) for c in candidates if Path(c).exists()]


def _normalize(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.zeros(TEMPLATE_SIZE[::-1], np.float32)
    crop = mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.uint8) * 255
    out = cv2.resize(crop, TEMPLATE_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return out


@lru_cache(maxsize=1)
def digit_templates() -> list[tuple[int, np.ndarray, float]]:
    """(digit, normalized glyph, aspect ratio) for every available font."""
    templates = []
    sources: list[tuple[Path, int]] = [(FONT_DIR / "Bravura.otf", 0xE080), (FONT_DIR / "Leland.otf", 0xE080)]
    sources += [(p, ord("0")) for p in _text_fonts()]
    for path, base in sources:
        try:
            font = ImageFont.truetype(str(path), 160)
        except OSError:
            continue
        for d in range(10):
            ch = chr(base + d)
            img = Image.new("L", (260, 420), 0)
            ImageDraw.Draw(img).text((40, 40), ch, font=font, fill=255)
            mask = np.array(img) > 127
            ys, xs = np.nonzero(mask)
            if len(xs) < 50:
                continue  # glyph missing in this font
            aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
            templates.append((d, _normalize(mask), aspect))
    return templates


def classify_digit(mask: np.ndarray) -> tuple[int, float]:
    """Best matching digit for a binary glyph mask, with a 0..1 similarity."""
    ys, xs = np.nonzero(mask)
    aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
    g = _normalize(mask)
    best, best_score = -1, -1.0
    for d, t, t_aspect in digit_templates():
        inter = np.minimum(g, t).sum()
        union = np.maximum(g, t).sum() + 1e-6
        score = inter / union - 0.25 * abs(aspect - t_aspect)
        if score > best_score:
            best, best_score = d, score
    return best, max(0.0, float(best_score))


def read_number(region: np.ndarray, interline: float) -> tuple[int | None, float]:
    """Read a (possibly multi-digit) number from a binary region."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(region.astype(np.uint8), connectivity=8)
    glyphs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h < 0.9 * interline or h > 3.2 * interline or area < 0.15 * interline ** 2:
            continue
        glyphs.append((x, y, w, h, labels[y:y + h, x:x + w] == i))
    if not glyphs:
        return None, 0.0
    # keep the row of glyphs sharing the tallest glyph's vertical band
    ref = max(glyphs, key=lambda g: g[3])
    row = sorted((g for g in glyphs if abs((g[1] + g[3] / 2) - (ref[1] + ref[3] / 2)) < 0.5 * ref[3]), key=lambda g: g[0])
    digits, scores = [], []
    for x, y, w, h, mask in row:
        pieces = [mask]
        if w > 1.15 * h:  # touching digits: split at the weakest column
            k = max(2, round(w / (0.7 * h)))
            cols = mask.sum(axis=0)
            cuts = []
            for j in range(1, k):
                c = int(w * j / k)
                lo, hi = max(1, c - int(0.15 * w)), min(w - 1, c + int(0.15 * w))
                cuts.append(lo + int(np.argmin(cols[lo:hi])))
            bounds = [0] + cuts + [w]
            pieces = [mask[:, a:b] for a, b in zip(bounds, bounds[1:]) if b - a > 2]
        for p in pieces:
            if p.sum() == 0:
                continue
            d, s = classify_digit(p)
            digits.append(d)
            scores.append(s)
    if not digits or any(d < 0 for d in digits):
        return None, 0.0
    value = int("".join(map(str, digits)))
    return (value if value > 0 else None), float(min(scores))


# ---------------------------------------------------------------------------
# bar detection
# ---------------------------------------------------------------------------


def _staff_lines(binary: np.ndarray, interline: float) -> list[int]:
    """Rows that are staff lines (long horizontal runs), anywhere on the page."""
    h, w = binary.shape
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(6 * interline)), 1))
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    rows = np.flatnonzero(lines.sum(axis=1) > 6 * interline * 255)
    # merge adjacent rows (thick lines)
    out: list[int] = []
    for r in rows:
        if out and r - out[-1] <= 2:
            continue
        out.append(int(r))
    return out


def find_multirests(gray: np.ndarray, interline: float, page: int = 0) -> list[MultiRest]:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    il = float(interline)
    # thick horizontal material: survives a horizontal AND a vertical opening thicker than staff lines
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(2.5 * il)), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(0.38 * il))))
    thick = cv2.morphologyEx(cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk), cv2.MORPH_OPEN, vk)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(thick, connectivity=8)
    staff_rows = _staff_lines(binary, il)
    found: list[MultiRest] = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if w < 2.5 * il or not (0.35 * il <= h <= 1.1 * il):
            continue
        cy = y + h / 2
        # must sit on a staff's middle line: staff lines at cy±il and cy±2il
        def near(row: float) -> bool:
            return any(abs(r - row) <= max(2, 0.2 * il) for r in staff_rows)
        if not (near(cy - il) and near(cy + il) and near(cy - 2 * il) and near(cy + 2 * il)):
            continue
        # serifs: short vertical strokes at both ends, no long stems
        ok = True
        for ex in (x, x + w - 1):
            x0, x1 = max(0, ex - int(0.25 * il)), min(binary.shape[1], ex + int(0.25 * il) + 1)
            col = binary[:, x0:x1].max(axis=1) > 0
            top = int(cy)
            while top > 0 and col[top - 1]:
                top -= 1
            bot = int(cy)
            while bot < len(col) - 1 and col[bot + 1]:
                bot += 1
            run = bot - top + 1
            if not (1.0 * il <= run <= 2.7 * il):
                ok = False
                break
        if not ok:
            continue
        # number above the staff (top line at cy - 2il)
        top_line = int(cy - 2 * il)
        ry0, ry1 = max(0, int(top_line - 3.6 * il)), max(0, int(top_line - 0.15 * il))
        rx0, rx1 = max(0, int(x - 0.5 * il)), min(binary.shape[1], int(x + w + 0.5 * il))
        region = binary[ry0:ry1, rx0:rx1] > 0
        count, conf = read_number(region, il) if region.size else (None, 0.0)
        found.append(MultiRest(page, int(x), int(cy), int(w), count, round(conf, 3)))
    # reading order: by staff band, then left to right
    found.sort(key=lambda m: (round(m.y / (6 * il)), m.x))
    return found


def detect_on_pages(pages: list[Path], interline_hint: float | None = None) -> list[MultiRest]:
    from app.services.omr.preprocess import estimate_interline

    out: list[MultiRest] = []
    for i, p in enumerate(pages):
        gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        il = estimate_interline(gray) or interline_hint
        if not il:
            continue
        out.extend(find_multirests(gray, il, page=i))
    return out
