"""Location conformance runner (spec/locations.md): importers and framing conversion.

Centers, budgets, references, formats and warnings must match exactly; the
half-height and the viewport zooms within the case's relative epsilon (they go through
log10). Strict: an unknown key fails the case.
"""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from heaton_life.fractal import locations

ROOT = Path(__file__).resolve().parents[2] / "vectors" / "locations"
CASES = sorted(ROOT.glob("*/params.json"))
PARSERS = {
    "kfr": locations.parse_kfr,
    "f3": locations.parse_fraktaler3,
    "hf-preset": locations.parse_hf_preset,
    "hf-result": locations.parse_hf_result,
    "hf-journal": locations.parse_hf_journal,
}
KEYS = {"spec_version", "family", "tier", "epsilon", "format", "input"}


def _close(got: float, want: float, epsilon: float) -> bool:
    return abs(got - want) <= epsilon * max(1.0, abs(want))


def test_every_format_has_vectors() -> None:
    formats = {json.loads(case.read_text())["format"] for case in CASES}
    assert formats == set(PARSERS)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_location_vector(case: Path) -> None:
    meta: dict[str, Any] = json.loads(case.read_text())
    assert (meta["family"], meta["tier"], meta["spec_version"]) == ("locations", "epsilon", "0.5.0")
    extra = {"error"} if meta.get("error") else {"expected", "viewports"}
    assert set(meta) == KEYS | extra, (
        f"{case}: unexpected keys {sorted(set(meta) ^ (KEYS | extra))}"
    )
    text = (case.parent / meta["input"]).read_bytes().decode("utf-8")
    parse = PARSERS[meta["format"]]
    if meta.get("error"):
        with pytest.raises(ValueError):
            parse(text)
        return
    loc = parse(text)
    want = meta["expected"]
    assert (loc.center_re, loc.center_im, loc.format) == (
        want["center_re"],
        want["center_im"],
        want["format"],
    )
    assert loc.max_iter == want["max_iter"]
    assert (list(loc.reference) if loc.reference else None) == want["reference"]
    assert list(loc.warnings) == want["warnings"]
    epsilon = meta["epsilon"]
    if want["half_height_log10"] is None:
        assert loc.half_height_log10 is None and meta["viewports"] == []
        with pytest.raises(ValueError):
            loc.viewport((64, 64))
        return
    assert loc.half_height_log10 is not None
    assert _close(loc.half_height_log10, want["half_height_log10"], epsilon)
    assert meta["viewports"], "a scaled location lists its viewports"
    for entry in meta["viewports"]:
        vp = loc.viewport((entry["size"][0], entry["size"][1]))
        assert (vp.center_re, vp.center_im) == (loc.center_re, loc.center_im)
        assert math.isfinite(vp.zoom_log10)
        assert _close(vp.zoom_log10, entry["zoom_log10"], epsilon)
