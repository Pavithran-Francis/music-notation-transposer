"""Compare OMR engines on the benchmark scores: primary alone, secondary alone, merged.

    .venv/bin/python -m benchmarks.compare            # all benchmarks, clean + degraded scan
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np

from app.services.omr.service import OMRService, secondary_engine
from benchmarks.score_omr import score

OUT = Path(__file__).parent / "out"
KEYS = ["time_signatures", "key_signatures", "pitch+rhythm", "altered notes", "title found", "composer found", "tempo text found", "dynamics", "hairpins", "slurs", "staccato/accent", "rehearsal marks"]


def degrade(png: Path, dst: Path, seed: int = 1) -> Path:
    """Simulate a mediocre scan: 200 DPI, 1.5° skew, blur, grey paper, noise, heavy JPEG."""
    img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    img = cv2.resize(img, (int(w * 2 / 3), int(h * 2 / 3)), interpolation=cv2.INTER_AREA)
    m = cv2.getRotationMatrix2D((img.shape[1] / 2, img.shape[0] / 2), 1.5, 1)
    img = cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderValue=235)
    img = cv2.GaussianBlur(img, (3, 3), 0.8)
    rng = np.random.default_rng(seed)
    img = np.clip(img.astype(float) * 0.9 + 18 + rng.normal(0, 14, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 55])
    return dst


def run_one(doc: Path, truth: Path) -> dict[str, dict]:
    work = Path(tempfile.mkdtemp(prefix="omrcmp-"))
    primary = OMRService(secondary=None)
    kind = "pdf" if doc.suffix == ".pdf" else "image"
    parsed = primary.parse_document([(kind, doc.read_bytes())], work)
    a = primary.recognize_pages(parsed, work, lambda *x: None)
    out: dict[str, dict] = {}
    (work / "a.musicxml").write_bytes(a.musicxml)
    out["primary"] = score(truth, work / "a.musicxml")
    sec = secondary_engine()
    if sec is None:
        return out
    h = sec.recognize([p.path for p in parsed.usable_pages], work / "omr2", lambda *x: None)
    (work / "h.musicxml").write_bytes(h.musicxml)
    out["secondary"] = score(truth, work / "h.musicxml")
    full = OMRService()  # the app's real path: both engines, merge, multi-rest counts from the page
    m = full.recognize_pages(parsed, work / "full", lambda *x: None)
    (work / "m.musicxml").write_bytes(m.musicxml)
    out["merged"] = score(truth, work / "m.musicxml")
    out["merged"]["_report"] = (m.merge or {}).get("summary", "")
    return out


def main() -> None:
    for name in ("benchmark", "benchmark2", "benchmark3"):
        truth = OUT / f"{name}.musicxml"
        scan = degrade(OUT / f"{name}-1.png", OUT / f"{name}-scan.jpg")
        for label, doc in (("clean PDF", OUT / f"{name}.pdf"), ("degraded scan", scan)):
            print(f"\n== {name} / {label}")
            for engine, r in run_one(doc, truth).items():
                print(f"  {engine:9} " + " | ".join(f"{k}={r[k]}" for k in KEYS))
                if engine == "merged":
                    print(f"            {r['_report']}")
                    for b in r["_bad_measures"]:
                        print(f"            m{b[0]}: truth {b[1]}  ->  {b[2]}")


if __name__ == "__main__":
    main()
