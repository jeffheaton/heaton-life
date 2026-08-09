"""PNG grid I/O unit tests: the round-trip law and input validation (spec/png-io.md)."""

import numpy as np
import numpy.typing as npt
import pytest

from heaton_life.init import mergelife_from_png, mergelife_to_png


def _grid() -> npt.NDArray[np.uint8]:
    values = (np.arange(6 * 7 * 3, dtype=np.uint32) * 11 + 5) % 256
    return values.astype(np.uint8).reshape(6, 7, 3)


@pytest.mark.parametrize("scale", [1, 2, 3, 8])
def test_round_trip_law(scale: int) -> None:
    grid = _grid()
    assert np.array_equal(mergelife_from_png(mergelife_to_png(grid, scale), scale), grid)


def test_scale_must_divide_dimensions() -> None:
    with pytest.raises(ValueError, match="multiple of scale"):
        mergelife_from_png(mergelife_to_png(_grid(), 2), 4)


def test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="grid must be"):
        mergelife_to_png(np.zeros((3, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="not a PNG"):
        mergelife_from_png(b"definitely not a png")
    with pytest.raises(ValueError, match="scale must be"):
        mergelife_to_png(_grid(), 0)
