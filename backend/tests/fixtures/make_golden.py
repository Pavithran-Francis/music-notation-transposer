"""Write the golden corpus to tests/fixtures/golden/ (input + expected MusicXML)."""

from pathlib import Path

from core.instruments.database import get_instrument
from tests.fixtures.builder import build_score
from tests.fixtures.golden_cases import CASES

OUT = Path(__file__).parent / "golden"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for case in CASES:
        src, tgt = get_instrument(case["source"]), get_instrument(case["target"])
        inp = dict(case["input"])
        inp.setdefault("clefs", (src.clefs[0],) * (2 if "##" in inp["measures"][0] else 1))
        exp = dict(case["expected"])
        exp.setdefault("clefs", (tgt.clefs[0],))
        (OUT / f"{case['name']}.input.musicxml").write_bytes(build_score(part_name=src.name, **inp))
        (OUT / f"{case['name']}.expected.musicxml").write_bytes(build_score(part_name=tgt.name, **exp))
    print(f"wrote {len(CASES) * 2} files to {OUT}")


if __name__ == "__main__":
    main()
