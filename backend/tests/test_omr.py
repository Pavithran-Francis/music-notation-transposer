import re
from pathlib import Path

from lxml import etree

from app.services.omr.audiveris import _merge_movements
from core.musicxml.document import parse_musicxml, walk
from tests.fixtures.builder import build_score


def test_merge_movements_keeps_c_major_explicit(tmp_path: Path):
    a = build_score(["Bb4/w"], key=-2)
    root = etree.fromstring(build_score(["C4/w"], key=0))
    k = root.find(".//key"); k.getparent().remove(k)  # Audiveris omits C major keys
    (tmp_path / "s.mvt1.mxl").write_bytes(a)
    (tmp_path / "s.mvt2.mxl").write_bytes(etree.tostring(root))
    merged = parse_musicxml(_merge_movements([tmp_path / "s.mvt1.mxl", tmp_path / "s.mvt2.mxl"]))
    pw = walk(merged)[0]
    assert [m.key.fifths for m in pw.measures] == [-2, 0]
    assert [m.number for m in pw.measures] == ["1", "2"]


def test_progress_sheet_regex():
    pat = r"\[[^\]#]+#(\d+)\]|Sheet#(\d+)|Stub#(\d+)"
    m = re.search(pat, "INFO  [book#2]            StepMonitoring 98   | LOAD")
    assert m and m.group(1) == "2"
