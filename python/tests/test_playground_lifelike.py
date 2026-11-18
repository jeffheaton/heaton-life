"""The playground's Life-like adapter: starting from a pattern, and the advice that a
pattern file belongs in HashLife. Qt-free."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import numpy as np
import pytest

from heaton_life.ca import LifeLike, LifeLikeParams
from heaton_life.ca.hashlife import HashLife, HashLifeMemoryError
from heaton_life.playground import lifelike_sim
from heaton_life.playground.lifelike_sim import (
    GRID_LIMIT,
    ROOMY,
    LifeLikeSim,
    LifeLikeSimParams,
    advise,
    measure,
    validate,
)
from heaton_life.playground.model import field_specs
from heaton_life.playground.registry import FAMILIES, Redirect

GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbo$2bo$3o!\n"


def _file(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="ascii", newline="\n")  # the same bytes on Windows
    return str(path)


def _from(pattern: str, **changes: object) -> LifeLikeSimParams:
    return LifeLikeSimParams(init="pattern", pattern=pattern).replace(**changes)


def _macrocell(tmp_path: Path, name: str, cells: list[tuple[int, int]]) -> str:
    universe = HashLife()
    for x, y in cells:
        universe.set_cell(x, y, True)
    path = tmp_path / name
    universe.save(path)
    return str(path)


# -- the params -------------------------------------------------------------------------------


def test_the_params_are_the_librarys_plus_a_pattern() -> None:
    library = {f.name: f for f in dataclasses.fields(LifeLikeParams)}
    ours = {f.name: f for f in dataclasses.fields(LifeLikeSimParams)}
    assert set(ours) == set(library) | {"pattern"}
    for name, field in library.items():
        assert ours[name].default == field.default, name
        if name != "init":
            assert dict(ours[name].metadata) == dict(field.metadata), name
    assert ours["init"].metadata["choices"] == [*library["init"].metadata["choices"], "pattern"]
    assert (GRID_LIMIT, ROOMY) == (library["width"].metadata["max"], GRID_LIMIT // 2)


def test_choosing_a_pattern_is_choosing_to_start_from_it() -> None:
    specs = {s.name: s for s in field_specs(LifeLikeSimParams)}
    assert specs["pattern"].role == "file" and specs["pattern"].selects == (("init", "pattern"),)
    assert specs["rule"].selects == ()


# -- building ---------------------------------------------------------------------------------


def test_a_grid_that_doesnt_start_from_a_pattern_is_the_librarys() -> None:
    params = LifeLikeSimParams(seed=7, density=0.4, width=64, height=48)
    sim = LifeLikeSim.build(params)
    library = LifeLike("B3/S23", size=(64, 48), init="soup", density=0.4, seed=7)
    assert np.array_equal(sim.state, library.state) and sim.params == params
    sim.step(3)
    library.step(3)
    assert np.array_equal(sim.state, library.state) and sim.generation == 3


def test_a_builtin_is_centered_under_its_own_rule() -> None:
    sim = LifeLikeSim.build(_from("Replicator (HighLife)", rule="B3/S23"))
    assert sim.params.rule == "B36/S23"
    cells = measure("Replicator (HighLife)").cells
    assert cells is not None
    height, width = cells.shape
    top, left = (256 - height) // 2, (256 - width) // 2
    assert np.array_equal(sim.state[top : top + height, left : left + width], cells)
    assert int(sim.state.sum()) == int(cells.sum())


def test_an_rle_file_is_centered_and_its_rule_adopted(tmp_path: Path) -> None:
    text = "#C a glider\nx = 3, y = 3, rule = B36/S23\nbo$2bo$3o!\n"
    sim = LifeLikeSim.build(_from(_file(tmp_path, "glider.rle", text), width=32, height=16))
    assert (sim.params.rule, sim.params.width, sim.params.height) == ("B36/S23", 32, 16)
    assert np.array_equal(sim.state[6:9, 14:17], GLIDER) and int(sim.state.sum()) == 5


def test_a_file_that_names_no_rule_keeps_the_forms(tmp_path: Path) -> None:
    sim = LifeLikeSim.build(_from(_file(tmp_path, "bare.rle", "bo$2bo$3o!"), rule="B36/S23"))
    assert sim.params.rule == "B36/S23"


def test_the_grid_grows_to_twice_the_pattern(tmp_path: Path) -> None:
    sim = LifeLikeSim.build(_from(_file(tmp_path, "row.rle", "300o!")))
    assert (sim.params.width, sim.params.height) == (600, 256)
    assert sim.state.shape == (256, 600) and int(sim.state[127, 150:450].sum()) == 300
    wide = LifeLikeSim.build(_from(_file(tmp_path, "wide.rle", f"{ROOMY + 1}o!")))
    assert wide.params.width == GRID_LIMIT  # twice it is past the largest grid


def test_a_small_macrocell_file_loads_too(tmp_path: Path) -> None:
    glider = [(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)]
    for name in ("glider.mc", "glider.mc.gz"):
        far = [(x + 1_000_000, y - 7) for x, y in glider]  # its place on the plane is dropped
        sim = LifeLikeSim.build(_from(_macrocell(tmp_path, name, far), width=32, height=16))
        assert np.array_equal(sim.state[6:9, 14:17], GLIDER), name


def test_rule_and_boundary_change_in_place(tmp_path: Path) -> None:
    sim = LifeLikeSim.build(_from("Glider"))
    before = sim.state.copy()
    params = sim.params.replace(rule="B36/S23", boundary="dead")
    sim.apply(params)
    assert np.array_equal(sim.state, before) and sim.params == params


# -- measuring: a file never becomes a grid before its size is known ----------------------------


def test_a_giant_is_measured_without_a_grid(tmp_path: Path) -> None:
    measured = measure(_file(tmp_path, "row.rle", "1000000o$o!"))
    assert (measured.width, measured.height, measured.cells) == (1_000_000, 2, None)


def test_dead_cells_and_a_declared_size_are_not_the_pattern(tmp_path: Path) -> None:
    """rle_decode would make a list of the billion dead cells, or a grid of the header's."""
    for text in (
        "999999999bo!",
        "o999999999b$o!",
        "x = 1000000000, y = 1000000000, rule = B3/S23\n999999999$o$o!",
    ):
        measured = measure(_file(tmp_path, f"pad-{len(text)}.rle", text))
        assert measured.cells is not None and measured.cells.shape[1] == 1, text
        assert int(measured.cells.sum()) == measured.cells.shape[0]


def test_what_isnt_a_life_like_pattern_says_so(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no built-in pattern or file named"):
        measure(str(tmp_path / "missing.rle"))
    with pytest.raises(ValueError, match="history.rle: a multi-state RLE"):
        measure(_file(tmp_path, "history.rle", "x = 3, y = 1, rule = LifeHistory\nA.C!"))
    with pytest.raises(ValueError, match="no live cells"):
        measure(_file(tmp_path, "empty.rle", "x = 3, y = 3\n3b$3b!"))
    with pytest.raises(ValueError, match="broken.mc: line 3"):
        measure(_file(tmp_path, "broken.mc", "[M2] (broken)\n#R B3/S23\nnot a node\n"))
    with pytest.raises(ValueError, match="odd.rle: unsupported RLE tag"):
        measure(_file(tmp_path, "odd.rle", "x = 3, y = 1\n3o?!"))


def test_a_file_is_measured_once_until_it_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _file(tmp_path, "glider.rle", GLIDER_RLE)
    scans = []
    scan = lifelike_sim.rle_measure
    monkeypatch.setattr(lifelike_sim, "rle_measure", lambda text: scans.append(1) or scan(text))
    first = measure(path)
    assert measure(path) is first and len(scans) == 1
    Path(path).write_text("x = 2, y = 2\n2o$2o!\n", encoding="ascii", newline="\n")
    os.utime(path, ns=(10**18, 10**18))  # a modified time it can't have had
    assert measure(path).width == 2 and len(scans) == 2


# -- advice -------------------------------------------------------------------------------------


def test_no_advice_for_what_life_like_suits(tmp_path: Path) -> None:
    assert advise(_from("Gosper glider gun")) is None
    assert advise(_from(_file(tmp_path, "glider.rle", GLIDER_RLE))) is None
    assert advise(_from(_file(tmp_path, "edge.rle", f"{ROOMY}o!"))) is None
    giant = _file(tmp_path, "giant.rle", "1000000o!")
    assert advise(LifeLikeSimParams(init="soup", pattern=giant)) is None  # not what it starts from


def test_a_pattern_past_the_largest_grid_can_only_go_to_hashlife(tmp_path: Path) -> None:
    advice = advise(_from(_file(tmp_path, "over.rle", f"{GRID_LIMIT + 1}o$o!")))
    assert advice is not None and advice.required
    assert "over.rle is 2,049 × 2 cells" in advice.reason and "2,048 × 2,048" in advice.reason
    caterpillar = _file(tmp_path, "like-the-caterpillar.rle", "4195o330720$o!")
    advice = advise(_from(caterpillar))
    assert advice is not None and advice.required and "1.4 GB" in advice.reason
    assert "GB" not in advise(_from(_file(tmp_path, "over.rle", "2049o$o!"))).reason  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="2,048 × 2,048"):
        LifeLikeSim.build(_from(caterpillar))  # the backstop, should a build get that far


def test_a_pattern_with_little_room_is_better_in_hashlife(tmp_path: Path) -> None:
    advice = advise(_from(_file(tmp_path, "big.rle", f"{ROOMY + 1}o!")))
    assert advice is not None and not advice.required
    assert (
        "big.rle is 1,025 × 1 cells" in advice.reason
        and "more than half its width or height" in advice.reason
    )
    tall = advise(_from(_file(tmp_path, "tall.rle", f"o{GRID_LIMIT - 1}$o!")))
    assert tall is not None and not tall.required  # the last size that fits at all


def test_a_macrocell_file_is_hashlifes_whatever_its_size(tmp_path: Path) -> None:
    small = advise(_from(_macrocell(tmp_path, "small.mc", [(0, 0), (1, 0)])))
    assert small is not None and not small.required
    assert "small.mc is a Macrocell file" in small.reason and "2 × 1 cells" in small.reason
    apart = advise(_from(_macrocell(tmp_path, "apart.mc.gz", [(0, 0), (5000, 9)])))
    assert apart is not None and apart.required and "5,001 × 10 cells" in apart.reason


def test_a_file_too_large_to_read_can_only_go_to_hashlife(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifelike_sim, "RLE_SIZE_LIMIT", 64)
    advice = advise(_from(_file(tmp_path, "long.rle", "bo$" * 40 + "o!")))
    assert advice is not None and advice.required and "MB of RLE" in advice.reason

    def over_budget(path: object) -> HashLife:
        raise HashLifeMemoryError("over budget")

    monkeypatch.setattr(HashLife, "from_file", over_budget)
    advice = advise(_from(_macrocell(tmp_path, "vast.mc", [(0, 0)])))
    assert advice is not None and advice.required and "just to read" in advice.reason


@pytest.mark.parametrize(
    ("cells", "text"),
    [(5, "5 bytes"), (4096, "4.1 KB"), (1_387_374_595, "1.4 GB"), (86_000_000_000_000, "86 TB")],
)
def test_memory_in_round_figures(cells: int, text: str) -> None:
    assert lifelike_sim._memory(cells) == text


# -- the family ---------------------------------------------------------------------------------


def test_the_family_offers_hashlife_with_the_same_file(tmp_path: Path) -> None:
    family = FAMILIES["lifelike"]
    assert family.advise is not None and family.params_cls is LifeLikeSimParams
    path = _file(tmp_path, "over.rle", f"{GRID_LIMIT + 1}o!")
    redirect = family.advise(_from(path))
    assert isinstance(redirect, Redirect) and redirect.required
    assert (redirect.family, redirect.key, dict(redirect.changes)) == (
        "hashlife",
        path,
        {"pattern": path},
    )
    assert redirect.title == "over.rle is too large for Life-like"
    assert "2,049 × 1 cells" in redirect.text
    borderline = family.advise(_from(_file(tmp_path, "big.rle", f"{ROOMY + 1}o!")))
    assert borderline is not None and not borderline.required
    assert borderline.title == "big.rle may be better in HashLife"
    assert family.advise(_from("Glider")) is None


def test_validation_names_the_field(tmp_path: Path) -> None:
    assert validate(_from("Glider")) is None
    assert validate(_from(_file(tmp_path, "glider.rle", GLIDER_RLE))) is None
    assert validate(LifeLikeSimParams(pattern="nothing here")) is None  # not what it starts from
    problem = validate(_from("nothing here"))
    assert problem is not None and problem[0] == "pattern"
    problem = validate(LifeLikeSimParams(rule="B3/S9"))
    assert problem is not None and problem[0] == "rule"


def test_the_pattern_presets_build() -> None:
    family = FAMILIES["lifelike"]
    for name in ("R-pentomino", "Gosper glider gun"):
        params = family.params_cls.from_dict(family.params_cls().to_dict() | family.presets[name])
        assert family.validate(params) is None and family.advise is not None
        assert family.advise(params) is None
        sim = family.build(params)
        assert int(np.asarray(sim.state).sum()) in (5, 36), name


# -- saving -------------------------------------------------------------------------------------


def test_save_pattern_writes_the_live_cells_as_rle(tmp_path: Path) -> None:
    sim = LifeLikeSim.build(_from("Gosper glider gun"))
    assert sim.pattern_file_name() == "Gosper-glider-gun-gen0.rle"
    sim.step(30)
    written = sim.save_pattern(tmp_path / "gun-later")  # no extension: it gets .rle
    assert written.name == "gun-later.rle" and sim.pattern_file_name().endswith("-gen30.rle")
    again = LifeLikeSim.build(_from(str(written)))
    assert int(again.state.sum()) == int(sim.state.sum())
    rows, columns = np.flatnonzero(sim.state.any(axis=1)), np.flatnonzero(sim.state.any(axis=0))
    box = sim.state[rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
    assert np.array_equal(measure(str(written)).cells, box)


def test_save_pattern_names_a_soup_by_its_rule_and_refuses_an_empty_grid(tmp_path: Path) -> None:
    soup = LifeLikeSim.build(LifeLikeSimParams(rule="B36/S23"))
    assert soup.pattern_file_name() == "life-B36S23-gen0.rle"
    empty = LifeLikeSim.build(LifeLikeSimParams(density=0.0))
    with pytest.raises(ValueError, match="no live cells"):
        empty.save_pattern(tmp_path / "nothing.rle")
