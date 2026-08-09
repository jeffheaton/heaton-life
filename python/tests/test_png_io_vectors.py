"""PNG I/O conformance: replay vectors/png-io/ decode pins (bit-exact grids)."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.init import mergelife_from_png

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "png-io"

CASES = sorted(VECTOR_ROOT.glob("*/params.json"))


def test_png_io_vectors_exist() -> None:
    assert len(CASES) >= 3


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_png_io_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    assert meta["tier"] == "bit-exact"
    decoded = mergelife_from_png(
        (case.parent / meta["input"]).read_bytes(), meta["scale"]
    )
    with Image.open(case.parent / meta["grid"]["file"]) as img:
        expected = np.asarray(img.convert("RGB"))
    assert np.array_equal(decoded, expected)
