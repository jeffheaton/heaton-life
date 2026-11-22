"""MCell files (spec/formats.md "MCell"): detection, the Life, Generations and Larger than Life
families, the cell data and its two-letter states, boards, every refusal's reason, the
writer, and both unbounded universes. The .NET suite checks the same (MCellTests.cs)."""

from __future__ import annotations

import gzip

import numpy as np
import pytest

from heaton_life.ca.hashlife import HashLife, read_universe
from heaton_life.ca.hashlife.multistate import read_multistate_universe
from heaton_life.core import BoundedGrid, Topology
from heaton_life.core.rng import Pcg32
from heaton_life.init import (
    PatternMetadata,
    detect_format,
    mcell_encode,
    measure_pattern,
    read_pattern,
)

# MCell's own example of the format (its author's description of .mcl files).
WORMS = (
    "#MCell 3.00\n#GAME Generations\n#RULE 3467/25/6\n#SPEED 20\n#BOARD 300x300\n#WRAP 0\n"
    "#D\n#D The universe of Worms.\n#D\n#D Discovered by Mirek Wojtowicz\n#D 1999.04.08\n"
    "#L ..DE.DED$.CE.E.DD$BDBABBC$.CACCEC$.A.BD.B$..B3C$3.3A$..4A$3.AA31$8.AA$\n"
    "#L 7.4A$7.3A$7.3CB$6.B.DB.A$6.CECCAC$6.CBBABDB$5.DD.E.EC$5.DED.ED\n"
)
GLIDER = "#MCell 4.20\n#GAME Life\n#RULE 23/3\n#D A glider\n#L .A$..A$3A\n"


def _mcell(*lines: str) -> str:
    return "\n".join(["#MCell 4.20", *lines]) + "\n"


# -- detection -------------------------------------------------------------------------------


def test_a_file_that_starts_with_mcell_is_one() -> None:
    assert detect_format(GLIDER) == "mcell"
    assert detect_format("\n  \n" + GLIDER) == "mcell"
    assert detect_format(gzip.compress(GLIDER.encode(), mtime=0)) == "mcell"
    assert detect_format("#MCELL 4.20\n#L A\n") == "rle"  # matched exactly as written


# -- reading ---------------------------------------------------------------------------------


def test_mcells_own_example_reads_as_its_board() -> None:
    found = read_pattern(WORMS)
    assert found.format == "mcell" and found.rule == "3467/25/6" and found.generation == 0
    assert found.bounded_grid == BoundedGrid(300, 300, Topology("dead"))
    assert found.cells.shape == (300, 300) and (found.x, found.y) == (-150, -150)
    comments = ("", "The universe of Worms.", "", "Discovered by Mirek Wojtowicz", "1999.04.08")
    assert found.metadata == PatternMetadata(None, None, comments)
    trimmed = read_pattern(WORMS, trim=True)
    assert trimmed.cells.shape == (48, 13) and (trimmed.x, trimmed.y) == (-6, -24)
    # The pattern is 13 x 48, centered on the origin like the world.
    assert np.array_equal(found.cells[126:174, 144:157], trimmed.cells)
    assert int(trimmed.cells.max()) == 5 and trimmed.cells[0, 2] == 4  # D, the first live cell
    extent = measure_pattern(WORMS)
    assert (extent.width, extent.height, extent.x, extent.y) == (300, 300, -150, -150)
    assert not extent.two_state and extent.bounded_grid == found.bounded_grid


def test_a_life_file_is_two_state_and_reads_survival_birth() -> None:
    found = read_pattern(GLIDER)
    assert found.rule == "B3/S23" and found.bounded_grid is None and (found.x, found.y) == (0, 0)
    assert found.cells.tolist() == [[0, 1, 0], [0, 0, 1], [1, 1, 1]]
    assert found.metadata.comments == ("A glider",)
    assert measure_pattern(GLIDER).two_state
    # MCell's Life rules have one bit: every state from 1 to 255 is alive.
    assert read_pattern(_mcell("#L A.C$jO.aB")).cells.tolist() == [[1, 0, 1], [1, 0, 1]]
    # No #GAME is Life, no #RULE is 23/3, and the family's case doesn't matter.
    assert read_pattern(_mcell("#L A")).rule == "B3/S23"
    assert read_pattern(_mcell("#GAME LIFE", "#RULE 125/36", "#L A")).rule == "B36/S125"
    assert read_pattern(_mcell("#RULE /0", "#L A")).rule == "B0/S"  # B0, as MCell writes it


def test_generations_and_larger_than_life_keep_their_states() -> None:
    gen = read_pattern(_mcell("#GAME Generations", "#RULE /2/3", "#L A.B"))
    assert gen.rule == "/2/3" and gen.cells.tolist() == [[1, 0, 2]]
    assert not measure_pattern(_mcell("#GAME Generations", "#RULE /2/3", "#L A")).two_state
    # A long rule split over several #RULE lines, MCell's spaced fields, and a board.
    ltl = read_pattern(
        _mcell(
            "#GAME Larger than Life",
            "#RULE R5,C30,M1,",
            "#RULE  S34..58, B34..45,NM",
            "#BOARD 40 X 30",
            "#L 3aB$$A",
        )
    )
    assert ltl.rule == "R5,C30,M1,S34..58,B34..45,NM"
    assert ltl.bounded_grid == BoundedGrid(40, 30, Topology("torus"))  # no #WRAP: a torus
    assert ltl.cells.shape == (30, 40) and int(ltl.cells.max()) == 26


def test_the_cell_data() -> None:
    def cells(data: str, rule: str = "/2/256") -> list[list[int]]:
        return read_pattern(_mcell("#GAME Generations", f"#RULE {rule}", data)).cells.tolist()

    assert cells("#L aA aXbA jO") == [[25, 48, 49, 255]]  # whitespace is ignored
    assert cells("#L 2a\n#L B$X") == [[26, 26], [24, 0]]  # #L lines join, a tag included
    assert cells("#L A0$.B$") == [[1, 0, 2], [0, 0, 0]]  # 0$ makes nothing; a row end adds one
    assert cells("#L 3.A2$") == [[0, 0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 0]]
    with pytest.raises(ValueError, match="the MCell pattern has no cells"):
        read_pattern(_mcell("#D only a comment"))
    assert measure_pattern(_mcell("#L $")).width == 0  # rows with nothing in them


def test_ignored_lines_and_boards() -> None:
    plane = read_pattern(
        _mcell(
            "#SPEED 0",
            "#CCOLORS 16",
            "#DIV #NOISE,act=1",
            "#FUTURE x",
            "#BOARD 9x7",
            "#WRAP 0",
            "#L 3A",
        )
    )
    assert plane.bounded_grid == BoundedGrid(9, 7, Topology("dead"))
    assert (plane.x, plane.y) == (-4, -3) and plane.cells[3, 3:6].tolist() == [1, 1, 1]
    # #WRAP is checked without a board too, though it plays no part.
    assert read_pattern(_mcell("#WRAP 1", "#L A")).bounded_grid is None


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        (("#L A", "A"), "line 3 does not start with '#'"),
        (
            ("#GAME Weighted Life",),
            (
                "the family 'Weighted Life' is not read here "
                "(Life, Generations and Larger than Life are)"
            ),
        ),
        (("#RULE B3/S23",), "a Life rule is survival/birth digits, such as 23/3, not 'B3/S23'"),
        (("#RULE 23/39",), "a Life rule is survival/birth digits, such as 23/3, not '23/39'"),
        # No MCell rule carries a History or Super suffix: MCell has neither.
        (
            ("#RULE 23/3Super",),
            "a Life rule is survival/birth digits, such as 23/3, not '23/3Super'",
        ),
        (
            ("#GAME Rules table", "#RULE Langtons-Loops"),
            (
                "the family 'Rules table' is not read here "
                "(Life, Generations and Larger than Life are)"
            ),
        ),
        # A rule file appended after the cells, as RLE may carry one, is no MCell line.
        (("#GAME Generations", "#RULE 2/3/4", "#L A", "@RULE x"), "line 5 does not start with '#'"),
        (
            ("#GAME Generations", "#RULE B2/S345/C4"),
            "a Generations rule is survival/birth/states digits, such as 345/2/4, not 'B2/S345/C4'",
        ),
        (
            ("#GAME Generations", "#RULE 2/3/1"),
            (
                "invalid Generations rule '2/3/1': a Generations rule has 2 to 256 states "
                "(spec/generations.md)"
            ),
        ),
        (
            ("#GAME Larger than Life", "#RULE R5,C0,M1,S34..58"),
            (
                "invalid Larger than Life rule 'R5,C0,M1,S34..58': expected the fields R, C, "
                "M, S, B and N, in that order (spec/ltl.md)"
            ),
        ),
        (("#BOARD 0x5",), "#BOARD is <width>x<height>, not '0x5'"),
        (("#BOARD 30x",), "#BOARD is <width>x<height>, not '30x'"),
        (("#WRAP yes",), "#WRAP is 0 or 1, not 'yes'"),
        (("#L 2A!",), "'!' in the cell data is no run count, state or '$'"),
        (("#L A12",), "a run count in the cell data has no state or '$' after it"),
        (("#L 3c.",), "'c' in the cell data has no state letter A to X after it"),
        (("#L jX",), "the cell data's state 264 is past 255"),
        (
            ("#GAME Generations", "#RULE 2/3/4", "#L ABCD"),
            "the cell data's state 4 is past the rule's 4 states",
        ),
        (("#BOARD 2x2", "#L 3A"), "the pattern reaches past its board (:T2,2)"),
    ],
)
def test_every_refusal_says_why(lines: tuple[str, ...], reason: str) -> None:
    with pytest.raises(ValueError) as error:
        read_pattern(_mcell(*lines))
    assert str(error.value) == f"invalid MCell file: {reason}"
    if "board" not in reason:  # measuring refuses what reading refuses
        with pytest.raises(ValueError):
            measure_pattern(_mcell(*lines))


# -- writing ---------------------------------------------------------------------------------


def test_the_writer() -> None:
    glider = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
    notes = PatternMetadata("Glider", "J. Conway", ("found 1969", ""))
    text = mcell_encode(glider, "23/3", metadata=notes)
    assert text == (
        "#MCell 4.00\n#GAME Life\n#RULE 23/3\n#D Glider\n#D J. Conway\n#D found 1969\n#D\n"
        "#L .A$2.A$3A\n"
    )
    back = read_pattern(text)
    assert np.array_equal(back.cells, glider) and back.rule == "B3/S23"
    assert back.metadata == PatternMetadata(None, None, ("Glider", "J. Conway", "found 1969", ""))
    # The data decodes to exactly the grid: empty rows, and the first row padded to the width.
    sparse = np.zeros((4, 6), dtype=np.uint8)
    sparse[1, 2] = 1
    assert mcell_encode(sparse, "B3/S23").endswith("#L 6.$2.A2$\n")
    assert np.array_equal(read_pattern(mcell_encode(sparse, "B3/S23")).cells, sparse)
    # Generations and Larger than Life, two-letter states, and a board.
    states = np.array([[0, 25, 255], [3, 0, 0]], dtype=np.uint8)
    gen = mcell_encode(states, "B2/S345/C256", topology=Topology("torus"))
    assert gen.splitlines()[1:5] == [
        "#GAME Generations",
        "#RULE 345/2/256",
        "#BOARD 3x2",
        "#WRAP 1",
    ]
    assert gen.endswith("#L .aAjO$C\n")
    ltl = mcell_encode(states, "r5,c256,m0,s1..2,b3..4", topology=Topology("dead"))
    assert "#GAME Larger than Life\n#RULE R5,C256,M0,S1..2,B3..4,NM\n" in ltl and "#WRAP 0" in ltl
    for text, rule in ((gen, "345/2/256"), (ltl, "R5,C256,M0,S1..2,B3..4,NM")):
        found = read_pattern(text)
        assert np.array_equal(found.cells, states) and found.rule == rule


@pytest.mark.parametrize(
    ("rule", "topology", "reason"),
    [
        ("B2a/S23", None, "no MCell family holds the rule 'B2a/S23'"),
        ("B2/S34H", None, "no MCell family holds the rule 'B2/S34H'"),
        ("B3/S23History", None, "no MCell family holds the rule 'B3/S23History'"),
        ("B3/S23Super", None, "no MCell family holds the rule 'B3/S23Super'"),
        ("Langtons-Loops", None, "no MCell family holds the rule 'Langtons-Loops'"),
        ("B2a/S/C3", None, "no MCell family holds the rule 'B2a/S/C3'"),
        ("WireWorld", None, "no MCell family holds the rule 'WireWorld'"),
        ("B3/S23", Topology("klein"), "an MCell board is a torus or the plane, not ':K4*,3'"),
        ("B3/S23", Topology("torus", 1), "an MCell board is a torus or the plane, not ':T4+1,3'"),
        ("B2/S/C3", None, "the cells hold state 3, past the rule's 3 states"),
    ],
)
def test_the_writer_refuses_what_mcell_cant_hold(
    rule: str, topology: Topology | None, reason: str
) -> None:
    cells = np.array([[0, 1, 0, 1], [1, 0, 3, 0], [0, 0, 0, 1]], dtype=np.uint8)
    if "state" not in reason:
        cells = np.minimum(cells, 1)
    with pytest.raises(ValueError, match=reason.replace("+", r"\+").replace("*", r"\*")):
        mcell_encode(cells, rule, topology=topology)
    with pytest.raises(ValueError, match="at least one row and one column"):
        mcell_encode(np.zeros((0, 3), dtype=np.uint8), "B3/S23")


def test_random_grids_round_trip() -> None:
    rng = Pcg32(17)
    for trial in range(40):
        width, height = 1 + rng.next_u32() % 90, 1 + rng.next_u32() % 12
        states = (2, 5, 30, 256)[trial % 4]
        draws = np.array([rng.next_u32() for _ in range(width * height)], dtype=np.uint64)
        grid = np.where(draws % 3 == 0, draws % states, 0).astype(np.uint8).reshape(height, width)
        rule = "B3/S23" if states == 2 else f"B2/S34/C{states}"
        topology = (None, Topology("torus"), Topology("dead"))[trial % 3]
        text = mcell_encode(grid, rule, topology=topology)
        assert all(len(line) <= 73 for line in text.splitlines() if line.startswith("#L"))
        found = read_pattern(text)
        assert np.array_equal(found.cells, grid), trial
        extent = measure_pattern(text)
        assert (extent.width, extent.height) == (width, height)


# -- the unbounded universes -----------------------------------------------------------------


def test_the_two_state_universe_reads_a_life_file() -> None:
    found = read_universe(GLIDER)
    assert found.format == "mcell" and found.universe.rule == "B3/S23"
    assert found.universe.population == 5 and found.universe.bounding_box() == (0, 0, 2, 2)
    snapshot = HashLife().read_snapshot(GLIDER)
    assert snapshot.rule == "B3/S23" and snapshot.metadata.comments == ("A glider",)
    for text, reason in (
        (WORMS, "the unbounded universe has no bounded grid \\(the MCell board ':P300,300'\\)"),
        (_mcell("#GAME Generations", "#RULE 2/3/4", "#L A"), "Generations rule of 4 states"),
        (_mcell("#GAME Larger than Life", "#RULE 5,34,45,34,58", "#L A"), "Larger than Life"),
    ):
        with pytest.raises(ValueError, match=reason):
            read_universe(text)


def test_the_multi_state_universe_reads_a_generations_file() -> None:
    text = _mcell("#GAME Generations", "#RULE 345/2/4", "#D Star Wars", "#L A.BC$$3C")
    found = read_multistate_universe(text)
    assert found.format == "mcell" and found.universe.rule == "B2/S345/C4"
    assert found.universe.population == 6 and found.universe.bounding_box() == (0, 0, 3, 2)
    assert found.metadata.comments == ("Star Wars",)
    for text, reason in (
        (WORMS, "the unbounded universe has no bounded grid"),
        (GLIDER, "not a state rule"),
        (_mcell("#GAME Larger than Life", "#RULE 5,34,45,34,58", "#L A"), "Larger than Life"),
    ):
        with pytest.raises(ValueError, match=reason):
            read_multistate_universe(text)
