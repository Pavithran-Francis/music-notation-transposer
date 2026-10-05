"""Run OMR on a document and score it against ground truth.

    .venv/bin/python -m benchmarks.run [--raw] DOCUMENT TRUTH.musicxml

--raw feeds the document straight to Audiveris (no app preprocessing), to
measure whether preprocessing helps.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.config import get_settings
from app.services.omr.service import OMRService
from benchmarks.score_omr import report, score


def run(doc: Path, truth: Path, raw: bool) -> dict:
    work = Path(tempfile.mkdtemp(prefix="omrbench-"))
    t0 = time.time()
    if raw:
        out = work / "out"
        subprocess.run([get_settings().resolved_audiveris(), "-batch", "-export", "-output", str(out), "--", str(doc)],
                       capture_output=True, timeout=900)
        mxl = sorted(out.glob("*.mxl"))[0]
    else:
        svc = OMRService()
        kind = "pdf" if doc.suffix.lower() == ".pdf" else "image"
        parsed = svc.parse_document([(kind, doc.read_bytes())], work)
        for p in parsed.pages:
            print(f"  page {p.index + 1}: interline={p.interline} actions={p.actions} warnings={p.warnings}")
        res = svc.recognize_pages(parsed, work, lambda *a: None)
        mxl = work / "result.mxl"
        mxl.write_bytes(res.musicxml)
    print(f"  ({time.time() - t0:.1f}s, workdir {work})")
    return score(truth, mxl)


if __name__ == "__main__":
    args = sys.argv[1:]
    raw = "--raw" in args
    args = [a for a in args if a != "--raw"]
    report(run(Path(args[0]), Path(args[1]), raw))
