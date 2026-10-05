"""Multi-measure rests (collapse/expand, page detection) and score metadata."""

import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from lxml import etree
from PIL import Image, ImageDraw, ImageFont

from app.services.omr.multirest import FONT_DIR, find_multirests
from core import metadata, multirest
from core.corrections import apply_corrections
from core.musicxml.document import parse_musicxml, walk
from tests.fixtures.builder import build_score


def rests_as_audiveris(n_before=1, bars=12):
    """Audiveris style: N expanded rest measures, the first marked with multiple-rest."""
    t = parse_musicxml(build_score(["C4/w"] * n_before + ["r/w"] * bars + ["D4/w"]))
    first = t.getroot().find("part").findall("measure")[n_before]
    multirest.mark_token(first, bars)
    return t


def test_collapse_and_expand_audiveris_style():
    t = multirest.collapse(rests_as_audiveris(bars=12))
    ms = t.getroot().find("part").findall("measure")
    assert len(ms) == 3 and multirest._count(ms[1]) == 12
    index_map = multirest.expand(t)
    pw = walk(t)[0]
    assert len(pw.measures) == 14 and index_map == [0, 1, 13]
    assert [m.number for m in pw.measures] == [str(i) for i in range(1, 15)]
    rests = [e for e in pw.notes if e.is_rest]
    assert len(rests) == 12 and all(e.element.find("rest").get("measure") == "yes" for e in rests)
    assert all(e.duration == 48 for e in rests)  # full 4/4 measures (12 divisions per quarter)


def test_collapse_empty_measure_style_gets_full_rest():
    t = parse_musicxml(build_score(["C4/w", "D4/w", "E4/w"]))
    m = t.getroot().find("part").findall("measure")[1]
    for n in m.findall("note"):
        m.remove(n)
    multirest.mark_token(m, 7)
    c = multirest.collapse(t)
    pw = walk(c)[0]
    assert [e.is_rest for e in pw.notes] == [False, True, False]
    multirest.expand(c)
    assert len(walk(c)[0].measures) == 9


def _synthetic_page(count: int, il: int = 20) -> np.ndarray:
    """A staff with a multi-measure rest and its number in Bravura digits."""
    w, h = 1400, 400
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    top = 160
    for k in range(5):
        y = top + k * il
        d.line([(60, y), (w - 60, y)], fill=0, width=2)
    cy = top + 2 * il
    x0, x1 = 500, 760
    d.rectangle([x0, cy - 6, x1, cy + 6], fill=0)  # thick bar on the middle line
    for x in (x0, x1):
        d.rectangle([x - 1, cy - il, x + 2, cy + il], fill=0)  # serifs
    font = ImageFont.truetype(str(FONT_DIR / "Bravura.otf"), 4 * il)
    text = "".join(chr(0xE080 + int(ch)) for ch in str(count))
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    d.text(((x0 + x1) / 2 - tw / 2 - bbox[0], top - 2.6 * il - bbox[1]), text, font=font, fill=0)
    # a beamed pair elsewhere must not be mistaken for a rest
    d.rectangle([1000, top - 3 * il, 1100, top - 3 * il + 10], fill=0)
    d.line([(1000, top - 3 * il), (1000, top + 2 * il)], fill=0, width=3)
    d.line([(1100, top - 3 * il), (1100, top + 2 * il)], fill=0, width=3)
    return np.array(img)


@pytest.mark.parametrize("count", [2, 4, 7, 12, 16, 24, 38, 105])
def test_detector_reads_counts_of_any_length(count):
    found = find_multirests(_synthetic_page(count), 20)
    assert [m.count for m in found] == [count]
    assert found[0].confidence > 0.6


def test_metadata_from_credits_and_header():
    t = parse_musicxml(build_score(["C4/w"], part_name="Trumpet in Bb"))
    root = t.getroot()
    for text, size, ctype in (("Rest Study", "24", None), ("M. Composer", "11", "composer")):
        c = etree.Element("credit", page="1")
        if ctype:
            etree.SubElement(c, "credit-type").text = ctype
        etree.SubElement(c, "credit-words", {"font-size": size}).text = text
        root.find("part-list").addprevious(c)
    ident = etree.Element("identification")
    etree.SubElement(ident, "source").text = "/private/var/folders/secret/upload.pdf"
    root.find("part-list").addprevious(ident)
    metadata.normalize(t)
    assert metadata.read_metadata(t) == {"title": "Rest Study", "composer": "M. Composer"}
    assert root.find("identification/source") is None
    metadata.write_header(t, metadata.display_name("Alto Saxophone in Eb"))
    credits = {c.findtext("credit-type"): c.findtext("credit-words") for c in root.findall("credit")}
    assert credits == {"title": "Rest Study", "composer": "M. Composer", "part name": "Alto Saxophone in E♭"}
    assert root.find("part-list/score-part/part-name").get("print-object") == "no"


def test_title_composer_correction():
    t = parse_musicxml(build_score(["C4/w"]))
    out = apply_corrections(t, [{"op": "set_metadata", "title": "My Tune", "composer": "Me"}])
    assert metadata.read_metadata(out) == {"title": "My Tune", "composer": "Me"}


def test_display_name():
    assert metadata.display_name("Clarinet in Bb") == "Clarinet in B♭"
    assert metadata.display_name("Horn in F") == "Horn in F"
    assert metadata.display_name("Bassoon") == "Bassoon"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def test_multirest_part_end_to_end(client, tmp_path):
    """MuseScore-engraved part with 12/4/2-bar rests → recognized counts, transposed, header credits."""
    from app.config import get_settings
    from app.services.omr.service import default_engine

    mscore = get_settings().resolved_mscore()
    if not mscore or not default_engine().is_available():
        pytest.skip("needs MuseScore and Audiveris")
    from music21 import key, meter, metadata as m21meta, note, stream, tempo

    s = stream.Score()
    s.insert(0, m21meta.Metadata(title="Rest Study", composer="M. Composer"))
    p = stream.Part()
    p.partName = "Trumpet in Bb"
    plan = [("n", "D5 E5 F#5"), ("n", "G5/3"), ("r", 12), ("n", "A5 G5 F#5"), ("n", "E5/3"), ("r", 4),
            ("n", "D5 F#5 A5"), ("r", 2), ("n", "D5/3")]
    num = 1
    for kind, v in plan:
        for _ in range(v if kind == "r" else 1):
            m = stream.Measure(number=num)
            if num == 1:
                m.append([key.KeySignature(2), meter.TimeSignature("3/4"), tempo.MetronomeMark(number=97)])
            if kind == "r":
                r = note.Rest(quarterLength=3)
                r.fullMeasure = True
                m.append(r)
            else:
                for t in v.split():
                    n, _, dur = t.partition("/")
                    m.append(note.Note(n, quarterLength=float(dur or 1)))
            p.append(m)
            num += 1
    s.append(p)
    xml = tmp_path / "part.musicxml"
    s.write("musicxml", fp=str(xml))
    style = tmp_path / "s.mss"
    style.write_text('<museScore version="4.40"><Style><createMultiMeasureRests>1</createMultiMeasureRests></Style></museScore>')
    subprocess.run([mscore, "-S", str(style), "-o", str(tmp_path / "part.pdf"), str(xml)], capture_output=True, timeout=180)

    pid = client.post("/api/projects").json()["id"]
    client.post(f"/api/projects/{pid}/upload", files=[("files", ("part.pdf", (tmp_path / "part.pdf").read_bytes()))])

    def wait(job_id):
        while (j := client.get(f"/api/jobs/{job_id}").json())["status"] not in ("succeeded", "failed"):
            time.sleep(0.3)
        return j

    assert wait(client.post(f"/api/projects/{pid}/analyze").json()["job_id"])["status"] == "succeeded"
    a = client.get(f"/api/projects/{pid}/analysis").json()
    an = a["analysis"]
    assert an["measures"] == 24
    assert [r["bars"] for r in an["multirests"]] == [12, 4, 2]
    assert an["title"] == "Rest Study" and an["composer"] == "M. Composer"
    assert a["source_instrument"] == {"id": "trumpet_bb"}
    job = wait(client.post(f"/api/projects/{pid}/transpose", json={
        "source_instrument": {"id": "trumpet_bb"}, "target_instrument": {"id": "alto_sax"}}).json()["job_id"])
    assert job["status"] == "succeeded"
    res = client.get(f"/api/projects/{pid}/result").json()["result"]
    assert res["validation"]["passed"]
    mx = client.get(f"/api/projects/{pid}/export/musicxml").content
    assert b"Alto Saxophone in E\xe2\x99\xad" in mx and b"Rest Study" in mx and b"M. Composer" in mx
    assert mx.count(b"<multiple-rest>") == 3
