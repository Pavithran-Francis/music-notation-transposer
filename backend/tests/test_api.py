import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.omr.service import default_engine
from app.services.rendering import service as render
from tests.fixtures.builder import build_score


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def wait(client, job_id, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.2)
    raise TimeoutError(job_id)


def new_project(client, name="Test"):
    r = client.post("/api/projects", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


def upload(client, pid, name, data):
    return client.post(f"/api/projects/{pid}/upload", files=[("files", (name, data))])


MELODY = ["C5/q D5/q E5/q F5/q", "G5/h. r/q", "[C5 E5]/q B4/8 A4/8 G4/h", "C5/w"]


def test_health_and_instruments(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    inst = client.get("/api/instruments").json()["instruments"]
    assert any(i["id"] == "trumpet_bb" for i in inst)


def test_full_musicxml_workflow(client):
    pid = new_project(client)
    r = upload(client, pid, "tune.musicxml", build_score(MELODY, key=-1, part_name="Flute"))
    assert r.status_code == 200, r.text
    assert r.json()["source_kind"] == "musicxml"
    job = wait(client, client.post(f"/api/projects/{pid}/analyze").json()["job_id"])
    assert job["status"] == "succeeded", job
    a = client.get(f"/api/projects/{pid}/analysis").json()
    assert a["analysis"]["key"] == "F major"
    assert a["analysis"]["measures"] == 4
    assert a["source_instrument"] == {"id": "flute"}  # guessed from part name

    r = client.post(f"/api/projects/{pid}/transpose", json={
        "source_instrument": {"id": "flute"}, "target_instrument": {"id": "alto_sax"}})
    job = wait(client, r.json()["job_id"])
    assert job["status"] == "succeeded", job
    res = client.get(f"/api/projects/{pid}/result").json()["result"]
    assert res["transposition"]["interval"] == "M6"
    assert res["transposition"]["key_changes"][0]["to"] == "D major"
    assert res["validation"]["passed"], res["validation"]
    # alto sax written range tops out at F6: G5+M6 = E6 fits; nothing out of range
    assert res["range"]["outside_typical"] == 0

    # previews
    info = client.get(f"/api/projects/{pid}/preview", params={"which": "result"}).json()
    assert info["pages"] >= 1
    svg = client.get(f"/api/projects/{pid}/preview/result/1")
    assert svg.status_code == 200 and b"<svg" in svg.content
    # exports
    pdf = client.get(f"/api/projects/{pid}/export/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    mx = client.get(f"/api/projects/{pid}/export/musicxml")
    assert mx.status_code == 200 and b"Alto Saxophone" in mx.content and b'<note id=' not in mx.content
    png = client.get(f"/api/projects/{pid}/export/png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    mid = client.get(f"/api/projects/{pid}/export/midi")
    assert mid.status_code == 200 and mid.content.startswith(b"MThd")

    # MIDI must contain SOUNDING pitch: the alto part sounds exactly like the flute original
    from music21 import converter
    s = converter.parseData(mid.content, format="midi")
    midi_pitches = [p.midi for n in s.recurse().notes for p in n.pitches]
    from music21 import converter as c2
    orig = c2.parseData(build_score(MELODY, key=-1).decode())
    assert midi_pitches == [p.midi for n in orig.recurse().notes for p in n.pitches]

    hist = client.get(f"/api/projects/{pid}/history").json()["history"]
    assert [h["action"] for h in hist][:2] == ["created", "uploaded"]


def test_range_actions_and_undo(client):
    pid = new_project(client)
    upload(client, pid, "cello.musicxml", build_score(["C3/q E3/q G3/q C4/q", "C4/w"], clefs=("bass",), part_name="Cello"))
    wait(client, client.post(f"/api/projects/{pid}/analyze").json()["job_id"])
    job = wait(client, client.post(f"/api/projects/{pid}/transpose", json={
        "source_instrument": {"id": "cello"}, "target_instrument": {"id": "violin"}}).json()["job_id"])
    assert job["status"] == "succeeded"
    res = client.get(f"/api/projects/{pid}/result").json()["result"]
    assert res["range"]["outside_typical"] == 2
    # pitches were NOT silently changed
    assert res["octave_shifts"] == 0
    res = client.post(f"/api/projects/{pid}/range", json={"action": "auto"}).json()["result"]
    assert res["range"]["outside_typical"] == 0
    assert res["adjustments"][0]["kind"] == "global"
    assert res["validation"]["passed"]
    res = client.delete(f"/api/projects/{pid}/range/last").json()["result"]
    assert res["range"]["outside_typical"] == 2
    nid = res["range"]["issues"][0]["note_id"]
    res = client.post(f"/api/projects/{pid}/range", json={"action": "move", "note_ids": [nid], "octaves": 1}).json()["result"]
    assert res["range"]["outside_typical"] == 1
    res = client.post(f"/api/projects/{pid}/range", json={"action": "keep"}).json()["result"]
    assert res["range"]["unacknowledged"] == 0


def test_corrections_flow(client):
    pid = new_project(client)
    upload(client, pid, "t.musicxml", build_score(["C4/q D4/q E4/q F4/q"]))
    wait(client, client.post(f"/api/projects/{pid}/analyze").json()["job_id"])
    nid = "p0m0n1"
    r = client.patch(f"/api/projects/{pid}/corrections", json={"op": "set_pitch", "note_id": nid, "step": "D", "alter": 1, "octave": 4})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/projects/{pid}/notes/{nid}").json()["pitch"] == "D#4"
    bad = client.patch(f"/api/projects/{pid}/corrections", json={"op": "set_pitch", "note_id": "nope", "step": "D", "octave": 4})
    assert bad.status_code == 400
    r = client.delete(f"/api/projects/{pid}/corrections/last")
    assert client.get(f"/api/projects/{pid}/notes/{nid}").json()["pitch"] == "D4"


def test_rejects_bad_uploads(client):
    pid = new_project(client)
    assert upload(client, pid, "x.exe", b"MZ\x90\x00garbage").status_code == 400
    assert upload(client, pid, "fake.pdf", b"%PDF-1.4 this is not really a pdf").status_code == 400
    assert upload(client, pid, "x.gif", b"GIF89a....").status_code == 400
    assert upload(client, pid, "empty.png", b"").status_code == 400


def test_project_crud(client):
    pid = new_project(client, "Original")
    assert client.patch(f"/api/projects/{pid}", json={"name": "Renamed", "saved": True}).json()["name"] == "Renamed"
    dup = client.post(f"/api/projects/{pid}/duplicate").json()
    assert dup["name"] == "Renamed (copy)"
    assert client.delete(f"/api/projects/{dup['id']}").status_code == 204
    assert client.get(f"/api/projects/{dup['id']}").status_code == 404
    assert client.patch(f"/api/projects/{pid}", json={"settings": {"evil": 1}}).status_code == 400


@pytest.mark.skipif(not default_engine().is_available() or not render.mscore_available(),
                    reason="needs Audiveris and MuseScore")
def test_omr_png_end_to_end(client, tmp_path):
    """Render a known score to PNG with MuseScore, recognize it, transpose it, compare."""
    import subprocess
    from app.config import get_settings
    xml = build_score(["D4/q E4/q F#4/q G4/q", "A4/q B4/q C#5/q D5/q", "D5/q A4/q F#4/q D4/q", "D4/w"],
                      key=2, part_name="Trumpet")
    src = tmp_path / "in.musicxml"
    src.write_bytes(xml)
    subprocess.run([get_settings().resolved_mscore(), "-o", str(tmp_path / "in.png"), "-r", "300", str(src)],
                   capture_output=True, timeout=120)
    png = (tmp_path / "in-1.png").read_bytes()
    pid = new_project(client)
    assert upload(client, pid, "page.png", png).status_code == 200
    job = wait(client, client.post(f"/api/projects/{pid}/analyze").json()["job_id"])
    assert job["status"] == "succeeded", job
    a = client.get(f"/api/projects/{pid}/analysis").json()
    assert a["analysis"]["key"] == "D major" and a["analysis"]["notes"] == 13
    assert a["recognition"]["review"]["summary"]["overall"] > 0.7
    job = wait(client, client.post(f"/api/projects/{pid}/transpose", json={
        "source_instrument": {"id": "trumpet_bb"}, "target_instrument": {"id": "alto_sax"}}).json()["job_id"])
    assert job["status"] == "succeeded", job
    res = client.get(f"/api/projects/{pid}/result").json()["result"]
    assert res["transposition"]["key_changes"][0]["to"] == "A major"
    assert res["validation"]["passed"]
