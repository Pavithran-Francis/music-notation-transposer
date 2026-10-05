"""homr (https://github.com/liebharc/homr) secondary OMR engine adapter.

homr is a transformer-based recognizer that reads each staff independently.
It is very accurate on notes, rhythms and accidentals (also on photographed
pages) but ignores most text and expression markings, and only its
time-signature denominator is reliable. It is therefore used as a second
reading that `core.omr_merge` combines with the primary (Audiveris) result.

It runs as a separate process from its own virtualenv (tools/homr-venv) so its
machine-learning dependencies never conflict with the backend's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app.services.omr.base import OMREngine, OMRError, OMRResult, ProgressCallback


class HomrEngine(OMREngine):
    name = "homr"

    def __init__(self, executable: str | None, timeout_per_page: int = 300):
        self.executable = executable
        self.timeout_per_page = timeout_per_page

    def is_available(self) -> bool:
        return bool(self.executable) and Path(self.executable).exists()

    def recognize(self, pages: list[Path], workdir: Path, progress: ProgressCallback,
                  source_pdf: Path | None = None) -> OMRResult:
        if not self.is_available():
            raise OMRError("homr is not installed.")
        workdir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.setdefault("PYTHONWARNINGS", "ignore")
        page_xml: list[bytes] = []
        for i, page in enumerate(pages):
            progress("recognizing", f"Second recognition engine: page {i + 1} of {len(pages)}…", i / max(1, len(pages)))
            img = workdir / f"page-{i + 1}.png"
            shutil.copyfile(page, img)
            try:
                r = subprocess.run([self.executable, str(img)], cwd=str(workdir), capture_output=True, text=True,
                                   timeout=self.timeout_per_page, env=env)
            except subprocess.TimeoutExpired as e:
                raise OMRError(f"The second recognition engine timed out on page {i + 1}.") from e
            out = img.with_suffix(".musicxml")
            (workdir / f"page-{i + 1}.log").write_text((r.stdout or "")[-20000:] + (r.stderr or "")[-20000:])
            if not out.exists():
                raise OMRError(f"The second recognition engine produced no result for page {i + 1}.")
            page_xml.append(out.read_bytes())
        return OMRResult(musicxml=_concat_pages(page_xml), engine=self.name, page_count=len(pages))


def _concat_pages(pages: list[bytes]) -> bytes:
    """Append the measures of every page to the first page's single part."""
    from core.musicxml.document import parse_musicxml, to_bytes

    trees = [parse_musicxml(p) for p in pages]
    base = trees[0].getroot()
    part = base.find("part")
    for t in trees[1:]:
        other = t.getroot().find("part")
        if other is not None:
            for m in other.findall("measure"):
                part.append(m)
    for i, m in enumerate(part.findall("measure")):
        m.set("number", str(i + 1))
    return to_bytes(base)
