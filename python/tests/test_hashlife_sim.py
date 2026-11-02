"""The playground's HashLife adapter (Qt-free): loading fits the view, hot fields change the
sim in place, Reset returns to the starting snapshot (audit finding 10-01), painting
edits and navigates with the spec's exact view arithmetic, and Save picks the format."""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pytest

from heaton_life.ca.hashlife import (
    EDIT_LIMIT,
    HashLife,
    cell_at,
    center_cell,
    fit,
    zoom_at,
)
from heaton_life.playground.hashlife_sim import (
    HashLifeSim,
    HashLifeSimParams,
    save_filter_for,
    validate,
    view_of,
)


def _sim(**changes: object) -> HashLifeSim:
    return HashLifeSim.build(HashLifeSimParams().replace(**changes))


def test_build_fits_the_view_and_adopts_the_patterns_rule() -> None:
    sim = _sim(pattern="Replicator (HighLife)", rule="B3/S23")
    p = sim.params
    assert p.rule == "B36/S23", "a pattern loads under its own rule"
    assert view_of(p) == fit(sim.universe.bounding_box(), (p.width, p.height))
    frame = sim.frame()
    assert frame.shape == (p.height, p.width) and frame.dtype == np.uint8
    assert frame.max() == 255


def test_a_step_advances_two_to_the_step_exponent_generations() -> None:
    sim = _sim(pattern="R-pentomino", step_exponent=3)
    sim.step(2)
    reference = HashLife()
    reference.set_rect(0, 0, np.array([[0, 1, 1], [1, 1, 0], [0, 1, 0]], np.uint8))
    reference.step(16)
    assert sim.generation == 16
    assert sim.universe.to_macrocell() == reference.to_macrocell()


def test_hot_fields_keep_the_cells_and_the_generation() -> None:
    sim = _sim(pattern="Acorn")
    sim.step(5)
    before = sim.universe.to_macrocell()
    changed = sim.params.replace(
        step_exponent=2, max_memory_mb=64, mode="density", width=300, height=200, x="-7", mag=-1
    )
    sim.apply(changed)
    assert sim.params == changed
    assert sim.generation == 5
    assert sim.universe.to_macrocell() == before
    assert sim.universe.max_memory_mb == 64
    assert sim.frame().shape == (200, 300)
    sim.apply(changed.replace(rule="B36/S23"))
    assert sim.universe.rule == "B36/S23" and sim.generation == 5


def test_reset_returns_to_the_start_after_hot_edits() -> None:
    """Audit finding 10-01: a hot edit must not turn Reset into a rebuild from other
    params. Reset restores the starting snapshot and keeps the edited fields."""
    sim = _sim(pattern="Acorn")
    start = sim.universe.to_macrocell()
    sim.step(3)
    edited = sim.params.replace(rule="B36/S23", step_exponent=4, mag=1)
    sim.apply(edited)
    sim.step(1)
    assert sim.generation == 19
    sim.reset()
    assert sim.generation == 0
    assert sim.params == edited
    assert sim.universe.to_macrocell().replace("#R B36/S23", "#R B3/S23") == start
    sim.step(1)
    assert sim.generation == 16


def test_edits_made_at_the_start_belong_to_it() -> None:
    sim = _sim(pattern="Block")
    view = view_of(sim.params)
    assert view.mag >= 0
    far = (10, 10)  # a pixel away from the block: an isolated cell that dies
    cell = cell_at(view, *far)
    sim.paint(*far, 1)
    sim.step(1)
    assert sim.universe.get_cell(*cell) == 0
    sim.reset()
    assert sim.generation == 0
    assert sim.universe.get_cell(*cell) == 1, "Reset keeps an edit made at generation 0"


def test_paint_sets_and_erases_the_cell_under_the_pixel() -> None:
    sim = _sim(pattern="Glider")
    view = view_of(sim.params)
    cell = cell_at(view, 3, 5)
    assert sim.paint(3, 5, 1) is False
    assert sim.universe.get_cell(*cell) == 1
    assert sim.frame()[5, 3] == 255
    sim.paint(3, 5, 2)
    assert sim.universe.get_cell(*cell) == 0


def test_an_edit_outside_the_editing_box_raises_the_engines_message() -> None:
    sim = _sim(pattern="Glider")
    sim.apply(sim.params.replace(x=str(EDIT_LIMIT + 1), y="0", mag=0))
    before = sim.universe.to_macrocell()
    with pytest.raises(ValueError, match="editing box"):
        sim.paint(0, 0, 1)
    assert sim.universe.to_macrocell() == before


def test_drawing_needs_one_cell_per_pixel_or_closer() -> None:
    sim = _sim(pattern="Glider")
    sim.apply(sim.params.replace(mag=-1))
    with pytest.raises(ValueError, match="zoom in"):
        sim.paint(0, 0, 1)


def test_the_wheel_zooms_about_the_cursor_exactly() -> None:
    sim = _sim(pattern="Gosper glider gun")
    view = view_of(sim.params)
    assert view.mag < 5
    assert sim.paint(100, 60, 4) is True
    assert view_of(sim.params) == zoom_at(view, 100, 60, 1)
    assert sim.paint(100, 60, 5) is True
    assert view_of(sim.params) == view, "in, then out about the same pixel, is the identity"
    assert sim.paint(100, 60, 5) is True
    assert view_of(sim.params) == zoom_at(view, 100, 60, -1)


def test_a_modifier_click_recenters_on_the_pixel() -> None:
    sim = _sim(pattern="Gosper glider gun")
    view = view_of(sim.params)
    size = (sim.params.width, sim.params.height)
    assert sim.paint(40, 30, 3) is True
    assert center_cell(view_of(sim.params), size) == cell_at(view, 40, 30)
    assert view_of(sim.params).mag == view.mag


def test_zooming_in_stops_at_the_deepest_zoom() -> None:
    sim = _sim(pattern="Glider")
    sim.apply(sim.params.replace(mag=5))
    assert sim.paint(0, 0, 4) is False


def test_validate_names_the_field_at_fault() -> None:
    good = HashLifeSimParams()
    assert validate(good) is None
    assert validate(good.replace(x="1.5")) is not None
    assert validate(good.replace(y="١٢")) is not None  # non-ASCII digits
    assert validate(good.replace(x="-123456789012345678901234567890")) is None
    assert validate(good.replace(rule="B03/S23"))[0] == "rule"  # type: ignore[index]
    assert validate(good.replace(rule="garbage"))[0] == "rule"  # type: ignore[index]
    assert validate(good.replace(pattern="no such pattern"))[0] == "pattern"  # type: ignore[index]


def test_load_failures_are_value_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mc.gz"
    broken.write_bytes(gzip.compress(b"[M2] (test)\n$$*$\n")[:-6])  # truncated gzip
    with pytest.raises(ValueError, match="broken"):
        _sim(pattern=str(broken))
    with pytest.raises(ValueError, match="no built-in pattern or file"):
        _sim(pattern=str(tmp_path / "missing.rle"))


def test_save_writes_rle_inside_the_editing_box_and_macrocell_beyond(tmp_path: Path) -> None:
    sim = _sim(pattern="Glider")
    assert sim.pattern_file_name() == "Glider-gen0.rle"
    written = sim.save_pattern(tmp_path / "glider")
    assert written.name == "glider.rle"
    assert HashLife.from_file(written).to_macrocell() == sim.universe.to_macrocell()

    sim.universe.step(4 * (EDIT_LIMIT + 8))  # the glider leaves the editing box
    assert sim.pattern_suffix() == ".mc"
    assert sim.pattern_file_name() == f"Glider-gen{4 * (EDIT_LIMIT + 8)}.mc"
    written = sim.save_pattern(tmp_path / "far")
    assert written.name == "far.mc"
    assert HashLife.from_file(written).to_macrocell() == sim.universe.to_macrocell()
    with pytest.raises(ValueError, match="Macrocell"):
        sim.save_pattern(tmp_path / "far.rle")  # RLE can't carry it


def test_hot_fields_work_after_the_pattern_file_is_gone(tmp_path: Path) -> None:
    source = tmp_path / "glider.mc"
    _sim(pattern="Glider").universe.save(source)
    sim = _sim(pattern=str(source))
    source.unlink()
    assert sim.paint(5, 5, 5) is True, "the wheel still zooms"
    sim.apply(sim.params.replace(rule="B36/S23"))
    assert sim.universe.rule == "B36/S23"
    assert validate(sim.params)[0] == "pattern"  # type: ignore[index]  # reloading would fail


def test_save_names_and_filters_follow_the_file(tmp_path: Path) -> None:
    source = tmp_path / "my ship.mc.gz"
    _sim(pattern="Glider").universe.save(source)
    sim = _sim(pattern=str(source))
    assert sim.pattern_file_name() == "my-ship-gen0.rle"
    assert save_filter_for("x.mc.gz") == "Gzipped Macrocell (*.mc.gz)"
    assert save_filter_for("x.MC") == "Macrocell (*.mc)"
    assert save_filter_for("x.rle") == "RLE (*.rle)"


def test_readout_reports_population_memory_and_the_center() -> None:
    sim = _sim(pattern="Gosper glider gun", step_exponent=70)
    sim.step(1)
    assert sim.generation == 1 << 70
    text = sim.readout()
    assert text.startswith(f"pop {sim.universe.population:,} · step 2^70 · center (")
    assert f"of {sim.params.max_memory_mb:,} MB" in text


def test_a_cancel_between_steps_is_forgotten() -> None:
    sim = _sim(pattern="Acorn", step_exponent=12)
    sim.cancel()  # no step is running: the next one clears it (spec/hashlife.md)
    sim.step(1)
    assert sim.generation == 1 << 12
