"""Engraving and export: MusicXML → SVG / PDF / PNG / MIDI.

* SVG previews: Verovio (fast, in-process, keeps MusicXML note ids so the UI
  can make notes clickable).
* PDF: MuseScore CLI when available (best engraving and identical to what the
  user sees when opening the MusicXML in MuseScore); otherwise Verovio SVG pages
  converted to vector PDF with MuPDF.
* MIDI: music21, after converting the score to sounding (concert) pitch.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pymupdf
import verovio

from app.config import get_settings
from core.musicxml.document import copy_tree, parse_musicxml, to_bytes

_verovio_lock = threading.Lock()
_VEROVIO_DATA = str(Path(verovio.__file__).parent / "data")


class RenderError(RuntimeError):
    pass


def _toolkit(page_width: int, page_height: int, scale: int, reflow: bool) -> verovio.toolkit:
    tk = verovio.toolkit(False)
    tk.setResourcePath(_VEROVIO_DATA)
    tk.setOptions({
        "pageWidth": page_width,
        "pageHeight": page_height,
        "scale": scale,
        "adjustPageHeight": reflow,
        "breaks": "auto" if reflow else "encoded",
        "footer": "none",
        "header": "auto",
        "pageMarginLeft": 100,
        "pageMarginRight": 100,
        "pageMarginTop": 80,
        "pageMarginBottom": 80,
        "svgViewBox": True,
        "svgRemoveXlink": True,
        "mnumInterval": 1,
        "multiRestStyle": "block",
    })
    return tk


def with_highlights(musicxml: bytes, colors: dict[str, str]) -> bytes:
    if not colors:
        return musicxml
    tree = copy_tree(parse_musicxml(musicxml))
    for note in tree.getroot().iter("note"):
        c = colors.get(note.get("id") or "")
        if c:
            note.set("color", c)
    return to_bytes(tree)


def render_svg_pages(musicxml: bytes, colors: dict[str, str] | None = None, width: int = 2100) -> list[str]:
    data = with_highlights(musicxml, colors or {})
    with _verovio_lock:
        tk = _toolkit(width, 2970, 40, reflow=True)
        if not tk.loadData(data.decode("utf-8")):
            raise RenderError("The score could not be rendered (Verovio rejected the MusicXML).")
        return [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]


def mscore_available() -> bool:
    return get_settings().resolved_mscore() is not None


def _mscore_env() -> dict:
    env = dict(os.environ)
    if sys.platform.startswith("linux"):
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


_MSCORE_STYLE = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.40">
  <Style>
    <createMultiMeasureRests>1</createMultiMeasureRests>
  </Style>
</museScore>
"""


def _run_mscore(src: Path, dst: Path, multirests: bool = False) -> None:
    exe = get_settings().resolved_mscore()
    if not exe:
        raise RenderError("MuseScore is not installed.")
    cmd = [exe, "-o", str(dst), str(src)]
    if multirests:
        # Engrave consecutive rest measures as multi-measure rests, as instrumental parts are printed.
        style = src.with_name("parts.mss")
        style.write_text(_MSCORE_STYLE)
        cmd = [exe, "-S", str(style), "-o", str(dst), str(src)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=get_settings().mscore_timeout, env=_mscore_env())
    except subprocess.TimeoutExpired as e:
        raise RenderError("MuseScore timed out while rendering.") from e
    if not dst.exists() or dst.stat().st_size == 0:
        raise RenderError(f"MuseScore failed to render: {(r.stderr or r.stdout)[-400:]}")


def render_pdf(musicxml: bytes, engine: str = "auto") -> tuple[bytes, str]:
    """Return (pdf_bytes, engine_used)."""
    tree = parse_musicxml(musicxml)
    clean = to_bytes(tree, strip_ids=True)
    multirests = tree.getroot().find(".//multiple-rest") is not None
    if engine in ("auto", "musescore") and mscore_available():
        try:
            with tempfile.TemporaryDirectory() as d:
                src, dst = Path(d) / "score.musicxml", Path(d) / "score.pdf"
                src.write_bytes(clean)
                _run_mscore(src, dst, multirests)
                return dst.read_bytes(), "MuseScore"
        except RenderError:
            if engine == "musescore":
                raise
    return _verovio_pdf(clean), "Verovio"


_SMUFL_TEXT = {
    "\ue1d2": "\U0001d15d", "\ue1d3": "\U0001d15e", "\ue1d5": "\u2669", "\ue1d7": "\u266a",
    "\ue1d9": "\u266c", "\ue1e7": ".", "\ue1fc": ".",
}


def _verovio_pdf(musicxml: bytes) -> bytes:
    """Fallback engraving: Verovio SVG pages → vector PDF via Cairo."""
    import re

    import cairosvg

    with _verovio_lock:
        tk = _toolkit(2100, 2970, 100, reflow=False)
        tk.setOptions({"breaks": "auto", "adjustPageHeight": False, "footer": "none"})
        if not tk.loadData(musicxml.decode("utf-8")):
            raise RenderError("The score could not be rendered.")
        svgs = [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]
    out = pymupdf.open()
    for svg in svgs:
        # SMuFL glyphs used inside text (e.g. tempo marks) need the music font; map to Unicode.
        svg = re.sub("[\ue000-\uf8ff]", lambda m: _SMUFL_TEXT.get(m.group(0), ""), svg)
        page_pdf = pymupdf.open("pdf", cairosvg.svg2pdf(bytestring=svg.encode("utf-8")))
        page = out.new_page(width=595, height=842)  # A4
        page.show_pdf_page(page.rect, page_pdf, 0)
        page_pdf.close()
    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    return data


def render_png(pdf_bytes: bytes, page: int = 1, dpi: int = 150) -> bytes:
    doc = pymupdf.open("pdf", pdf_bytes)
    try:
        if not 1 <= page <= doc.page_count:
            raise RenderError("Page out of range.")
        pix = doc[page - 1].get_pixmap(dpi=dpi, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def pdf_page_count(pdf_bytes: bytes) -> int:
    doc = pymupdf.open("pdf", pdf_bytes)
    try:
        return doc.page_count
    finally:
        doc.close()


def render_midi(musicxml: bytes) -> bytes:
    """MIDI at SOUNDING pitch (MusicXML <transpose> is applied)."""
    from music21 import converter

    clean = to_bytes(parse_musicxml(musicxml), strip_ids=True)
    score = converter.parseData(clean.decode("utf-8"), format="musicxml")
    sounding = score.toSoundingPitch(inPlace=False)
    for p in sounding.parts:
        p.atSoundingPitch = True
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "score.mid"
        sounding.write("midi", fp=str(out))
        return out.read_bytes()


def mscz_to_musicxml(data: bytes) -> bytes:
    """Convert a MuseScore file to MusicXML using the MuseScore CLI."""
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "score.mscz", Path(d) / "score.musicxml"
        src.write_bytes(data)
        _run_mscore(src, dst)
        return dst.read_bytes()
