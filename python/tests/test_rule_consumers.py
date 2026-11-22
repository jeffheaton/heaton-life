"""Every consumer of a Life-like rule takes every notation of spec/rules.md: Advance
Selection and Advance Outside on grids and in HashLife, the pattern-file readers, and the
RLE and Macrocell writers, which write the rule's canonical spelling."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import LifeLike
from heaton_life.ca.hashlife import HashLife, read_timeline, read_universe, write_timeline
from heaton_life.ca.rulestring import compile_rule
from heaton_life.init import (
    measure_pattern,
    read_pattern,
    rle_decode,
    rle_encode,
    rle_measure,
    soup,
)

MOORE_MAP = (
    "MAPARYXfhZofugWaH7oaIDogBZofuhogOiA6IDogIAAgAAWaH7oaIDogGiA6ICAAIAAaIDogIAAgACAAIAAAAAAAA"
)
HEX_MAP = "MAPFgFoF2gXgH5oF4B+AH4A6A"
VN_MAP = "MAPHmkphg"

# One rule of each class as a person might type it, and its canonical form.
RULES = [
    ("b3/s2-i34q", "B3/S2-i34q"),
    ("B2cekin/S12", "B2-a/S12"),
    ("b2/s34h", "B2/S34H"),
    ("B2/S013v", "B2/S013V"),
    ("map" + MOORE_MAP[3:] + "==", MOORE_MAP),
    (HEX_MAP + "==", HEX_MAP),
    ("map" + VN_MAP[3:], VN_MAP),
]
IDS = [
    "isotropic-minus",
    "isotropic-letters",
    "hexagonal",
    "von-neumann",
    "map-moore",
    "map-hexagonal",
    "map-von-neumann",
]
B0_RULES = ["MAPg" + "A" * 85, "B0/S2H", "b03/s23"]

GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
GLIDER_RLE_UPPERCASE = "BOB$2BO$3O!"  # dead and alive in a two-state file
SELECTION = (85, 65, 114, 84)  # on the grid; HashLife's is 100 left and 75 up of it


def _advanced(rule: str, *, outside: bool) -> tuple[NDArray[np.uint8], NDArray[np.uint8]]:
    """A soup advanced 12 generations by a dead-edged 200 × 160 grid, and by HashLife on the
    plane, each told the rule as ``rule``; the pattern never reaches the grid's edge."""
    cells = soup((40, 30), density=0.4, seed=11)
    world = LifeLike(rule, size=(200, 160), init=np.zeros((160, 200), np.uint8), boundary="dead")
    world.state[60:90, 80:120] = cells
    u = HashLife(rule)
    u.set_rect(-20, -15, cells)
    x0, y0, x1, y1 = SELECTION
    if outside:
        world.advance_outside(x0, y0, x1, y1, 12)
        u.advance_outside(x0 - 100, y0 - 75, x1 - 100, y1 - 75, 12)
    else:
        world.advance_selection(x0, y0, x1, y1, 12)
        u.advance_selection(x0 - 100, y0 - 75, x1 - 100, y1 - 75, 12)
    assert (world.generation, u.generation) == (0, 0)
    assert world.params.rule == u.rule
    return world.state, u.get_rect(-100, -75, 99, 84)


@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize(("typed", "canonical"), RULES, ids=IDS)
def test_advance_runs_the_worlds_own_rule(typed: str, canonical: str, outside: bool) -> None:
    grid, plane = _advanced(typed, outside=outside)
    assert np.array_equal(grid, plane)
    assert HashLife(typed).rule == canonical
    # The rule shows in the result: Life advances the same soup to other cells.
    life_grid, _ = _advanced("B3/S23", outside=outside)
    assert not np.array_equal(grid, life_grid)


@pytest.mark.parametrize(("typed", "canonical"), RULES, ids=IDS)
def test_readers_take_every_notation(typed: str, canonical: str) -> None:
    # RLE: a header naming the rule in any spelling makes the file two-state.
    rle = f"x = 3, y = 3, rule = {typed}\n{GLIDER_RLE_UPPERCASE}\n"
    found = read_pattern(rle)
    assert (found.format, found.rule) == ("rle", typed)  # the header's, as written
    assert np.array_equal(found.cells, GLIDER)
    placed = read_universe(rle).universe
    assert placed.rule == canonical
    assert np.array_equal(placed.get_rect(0, 0, 2, 2), GLIDER)

    # Life 1.05: an #R line that isn't survival/birth digits is the rule as written.
    for written in (typed, f" {typed} "):
        life = f"#Life 1.05\n#R{written}\n#P 0 0\n.*.\n..*\n***\n"
        found = read_pattern(life)
        assert (found.format, found.rule) == ("life-1.05", typed)
        assert np.array_equal(found.cells, GLIDER)
        assert read_universe(life).universe.rule == canonical

    # Macrocell: #R in any spelling reads back canonical.
    u = HashLife(canonical)
    u.set_rect(0, 0, GLIDER)
    mc = u.to_macrocell().replace(f"#R {canonical}\n", f"#R {typed}\n")
    assert f"#R {typed}\n" in mc
    found = read_pattern(mc)
    assert (found.format, found.rule) == ("macrocell", canonical)
    assert np.array_equal(found.cells, GLIDER)
    assert read_universe(mc).universe.rule == canonical


def test_rules_with_spaces_read_from_life_and_macrocell_files() -> None:
    life = "#Life 1.05\n#R b3 / s2-i34q\n#P 0 0\n.*.\n..*\n***\n"
    assert read_pattern(life).rule == "b3 / s2-i34q"
    assert read_universe(life).universe.rule == "B3/S2-i34q"
    u = HashLife("B2/S34H")
    u.set_rect(0, 0, GLIDER)
    mc = u.to_macrocell().replace("#R B2/S34H\n", "#R b2 /s34h\n")
    assert read_universe(mc).universe.rule == "B2/S34H"


@pytest.mark.parametrize("rule", B0_RULES)
def test_a_b0_rule_reads_into_a_grid_and_a_universe(rule: str) -> None:
    """spec/hashlife.md "Rules with B0": every reader takes a rule with B0, its cells the
    universe's cells; a grid takes them as written."""
    canonical = compile_rule(rule).canonical
    rle = f"x = 3, y = 3, rule = {rule}\n{GLIDER_RLE_UPPERCASE}\n"
    found = read_pattern(rle)
    assert found.rule == rule  # still a Life-like rule, so the file is two-state
    assert np.array_equal(found.cells, GLIDER)
    universe = read_universe(rle).universe
    assert universe.rule == canonical
    assert np.array_equal(universe.get_rect(0, 0, 2, 2), GLIDER)
    life = f"#Life 1.05\n#R {rule}\n#P 0 0\n.*.\n..*\n***\n"
    assert read_universe(life).universe.to_macrocell() == universe.to_macrocell()
    u = HashLife("B3/S2-i34q")
    u.set_rect(0, 0, GLIDER)
    u.rule = rule
    assert u.rule == canonical
    assert np.array_equal(u.get_rect(0, 0, 2, 2), GLIDER)  # a new rule keeps the cells


@pytest.mark.parametrize("preset", ["life", "highlife", "Life"])
def test_a_file_names_its_rule_never_a_preset(preset: str) -> None:
    """spec/rules.md "Preset names": a preset is for rules people type. A grid read keeps a
    Life 1.0x rule as written, for the caller to compile; every reader that compiles a file's
    rule refuses a preset, while a typed HashLife still takes one."""
    life = f"#Life 1.05\n#R {preset}\n#P 0 0\n.*.\n..*\n***\n"
    assert read_pattern(life).rule == preset
    with pytest.raises(ValueError, match="invalid rule"):
        read_universe(life)
    mc = f"[M2] (example 1.0)\n#R {preset}\n.*$..*$***$\n"
    for reader in (read_pattern, read_universe, measure_pattern):
        with pytest.raises(ValueError, match="invalid rule"):
            reader(mc)
    rle = f"x = 3, y = 3, rule = {preset}\nbo$2bo$3o!\n"
    assert rle_measure(rle).extended  # no rule, so the file is extended
    with pytest.raises(ValueError, match="extended"):
        read_universe(rle)
    assert HashLife(preset).rule == compile_rule(preset).canonical


@pytest.mark.parametrize(("typed", "canonical"), RULES, ids=IDS)
def test_writers_write_the_canonical_spelling(typed: str, canonical: str) -> None:
    u = HashLife(typed)
    u.set_rect(0, 0, GLIDER)
    rle = u.to_rle()
    assert f", rule = {canonical}\n" in rle
    back = HashLife.from_rle(rle)
    assert back.rule == canonical
    assert np.array_equal(back.get_rect(0, 0, 2, 2), GLIDER)

    mc = u.to_macrocell()
    assert f"\n#R {canonical}\n" in mc
    assert HashLife.from_macrocell(mc).rule == canonical

    first = u.snapshot()
    u.step(4)
    timeline = write_timeline(u, [first, u.snapshot()])
    assert f"\n#R {canonical}\n" in timeline
    assert read_timeline(timeline).universe.rule == canonical

    grid = rle_encode(GLIDER, typed)
    assert grid.startswith(f"x = 3, y = 3, rule = {canonical}\n")
    cells, rule = rle_decode(grid)
    assert rule == canonical
    assert np.array_equal(cells, GLIDER)


def test_the_grid_writer_writes_a_header_that_reads_back() -> None:
    # An RLE header's rule ends at whitespace, so a rule spelled with spaces is written
    # canonically or it would read back as "B3" in the extended dialect.
    text = rle_encode(GLIDER, "b3 / s32")
    assert text.startswith("x = 3, y = 3, rule = B3/S23\n")
    cells, rule = rle_decode(text)
    assert rule == "B3/S23"
    assert np.array_equal(cells, GLIDER)
    # Any other rule is written as given; a preset name is not a rule in a file.
    assert rle_encode(GLIDER, "WireWorld").startswith("x = 3, y = 3, rule = WireWorld\n")
    assert rle_encode(GLIDER, "life").startswith("x = 3, y = 3, rule = life\n")
