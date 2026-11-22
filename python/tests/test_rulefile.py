"""Rule files (spec/rule-files.md): the compiler against a direct reading of each table,
the symmetries' variants, trees read and written, and tables that restate other families."""

from __future__ import annotations

import functools
import itertools
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from heaton_life.ca import LifeLike, Wireworld
from heaton_life.ca.rulefile import (
    _RING,
    RuleFileError,
    _parse_table,
    _split_sections,
    parse_rule_file,
    try_parse_rule_file,
    variant_orders,
)
from heaton_life.ca.ruletable import STARTER_RULES, RuleTableCA, starter_rule

FILES = Path(__file__).resolve().parents[2] / "vectors" / "ruletable-files"
BLOCK = ("nw", "n", "ne", "w", "c", "e", "sw", "s", "se")


def _vector_text(case: str) -> str:
    return (FILES / case / "input.rule").read_bytes().decode("utf-8")


@functools.cache
def _table(text: str) -> Any:
    sections = _split_sections(text)
    return _parse_table(next(s for s in sections if s.name == "TABLE"))


def _bind(fields: list[Any], values: list[int], variables: dict[str, Any]) -> dict[str, int] | None:
    """The binding under which ``fields`` match ``values`` in order, or None."""
    binding: dict[str, int] = {}
    for field, value in zip(fields, values, strict=True):
        if isinstance(field, int):
            if field != value:
                return None
        elif value not in variables[field] or binding.get(field, value) != value:
            return None
        else:
            binding[field] = value
    return binding


def _permuted(
    fields: list[Any], values: list[int], variables: dict[str, Any], bound: dict[str, int]
) -> bool:
    """Whether the neighbor fields match the neighbor values in some order (a multiset
    match by backtracking, independent of the compiler's variants)."""
    if not fields:
        return True
    field, rest = fields[0], fields[1:]
    for i, value in enumerate(values):
        if isinstance(field, int):
            ok = field == value
        else:
            ok = value in variables[field] and bound.get(field, value) == value
        if ok:
            new = dict(bound)
            if not isinstance(field, int):
                new[field] = value
            if _permuted(rest, values[:i] + values[i + 1 :], variables, new):
                return True
    return False


def _direct(text: str, block: dict[str, int]) -> int:
    """A cell's next state read straight from a table, as spec/rule-files.md "Meaning" says:
    the transitions in order, each as its variants in order, every variable bound. A
    permute table (whose outputs here are all states) is matched as a multiset."""
    table = _table(text)
    ring = _RING[table.neighborhood]
    values = [block[name] for name in ring]
    for transition in table.transitions:
        center, neighbors = transition.inputs[0], list(transition.inputs[1:])
        start = _bind([center], [block["c"]], table.variables)
        if start is None:
            continue
        out = transition.output
        if table.symmetries == "permute":
            assert isinstance(out, int) or out == center or len(table.variables[out]) == 1
            if _permuted(neighbors, values, table.variables, start):
                if isinstance(out, int):
                    return out
                return start[out] if out in start else table.variables[out][0]
            continue
        for order in variant_orders(table.neighborhood, table.symmetries):
            fields = [center] + [neighbors[order[i]] for i in range(len(ring))]
            binding = _bind(fields, [block["c"], *values], table.variables)
            if binding is not None:
                if isinstance(out, int):
                    return out
                return binding[out] if out in binding else table.variables[out][0]
    return block["c"]


TABLE_CASES = [
    "compile-bound-order",
    "compile-moore-rotate8reflect",
    "compile-moore-rotate4-reflect",
    "compile-moore-reflect",
    "compile-vonneumann-permute",
    "compile-vonneumann-reflect",
    "compile-hexagonal-rotations",
    "compile-hexagonal-rotate2",
    "compile-hexagonal-rotate3",
    "compile-one-dimensional-reflect",
    "compile-one-dimensional-permute",
    "compile-life-table",
    "compile-wireworld-table",
    "compile-hex-b2-s34",
    "compile-rule30-rows",
    "compile-data-sections",
]


@pytest.mark.parametrize("case", TABLE_CASES)
def test_compiled_tree_matches_a_direct_reading(case: str) -> None:
    text = _vector_text(case)
    rule = parse_rule_file(text)
    states = rule.states
    rng = np.random.default_rng(7)  # test inputs only; nothing here is simulation state
    blocks = (
        itertools.product(range(states), repeat=9)
        if states**9 <= 20000
        else (tuple(int(v) for v in rng.integers(0, states, 9)) for _ in range(5000))
    )
    for values in blocks:
        block = dict(zip(BLOCK, values, strict=True))
        assert rule.next_state(*values) == _direct(text, block), (case, values)


@pytest.mark.parametrize("name", STARTER_RULES)
def test_starter_rules_match_a_direct_reading(name: str) -> None:
    rule = starter_rule(name)
    rng = np.random.default_rng(3)
    for _ in range(3000):
        values = tuple(int(v) for v in rng.integers(0, rule.states, 9))
        block = dict(zip(BLOCK, values, strict=True))
        assert rule.next_state(*values) == _direct(rule.text, block), (name, values)


def test_vectorized_walk_equals_the_cell_function() -> None:
    for name in (*STARTER_RULES, "compile-bound-order", "compile-hex-b2-s34"):
        rule = starter_rule(name) if name in STARTER_RULES else parse_rule_file(_vector_text(name))
        rng = np.random.default_rng(11)
        arrays = {cell: rng.integers(0, rule.states, (17, 13)).astype(np.uint8) for cell in BLOCK}
        got = rule.evaluate(arrays)
        for y, x in itertools.product(range(17), range(13)):
            assert got[y, x] == rule.next_state(*(int(arrays[c][y, x]) for c in BLOCK))


@pytest.mark.parametrize(
    ("neighborhood", "symmetries", "count"),
    [
        ("vonNeumann", "none", 1),
        ("vonNeumann", "rotate4", 4),
        ("vonNeumann", "rotate4reflect", 8),
        ("vonNeumann", "reflect_horizontal", 2),
        ("vonNeumann", "permute", 24),
        ("Moore", "rotate4", 4),
        ("Moore", "rotate8", 8),
        ("Moore", "rotate4reflect", 8),
        ("Moore", "rotate8reflect", 16),
        ("Moore", "reflect_horizontal", 2),
        ("Moore", "permute", 40320),
        ("hexagonal", "rotate2", 2),
        ("hexagonal", "rotate3", 3),
        ("hexagonal", "rotate6", 6),
        ("hexagonal", "rotate6reflect", 12),
        ("hexagonal", "permute", 720),
        ("oneDimensional", "reflect", 2),
        ("oneDimensional", "permute", 2),
    ],
)
def test_variants_are_distinct_permutations(neighborhood: str, symmetries: str, count: int) -> None:
    orders = variant_orders(neighborhood, symmetries)
    assert len(orders) == count == len(set(orders))
    k = len(_RING[neighborhood])
    assert orders[0] == tuple(range(k))  # the transition itself comes first
    assert all(sorted(order) == list(range(k)) for order in orders)


def test_reflection_swaps_east_and_west() -> None:
    ring = _RING["Moore"]
    mirrored = variant_orders("Moore", "reflect_horizontal")[1]
    assert {ring[i]: ring[mirrored[i]] for i in range(8)} == {
        "n": "n", "ne": "nw", "e": "w", "se": "sw", "s": "s", "sw": "se", "w": "e", "nw": "ne",
    }  # fmt: skip
    assert variant_orders("oneDimensional", "reflect")[1] == (1, 0)
    assert variant_orders("vonNeumann", "reflect")[1] == (0, 3, 2, 1)


@pytest.mark.parametrize("name", STARTER_RULES)
def test_a_tree_written_and_read_back_is_the_same_tree(name: str) -> None:
    rule = starter_rule(name)
    again = parse_rule_file(f"@RULE Again\n@TREE\n{rule.tree_text()}")
    assert again.tree_text() == rule.tree_text()
    assert (again.source, again.neighborhood, again.symmetries) == ("tree", None, None)


def test_tables_that_restate_other_families_run_as_they_do() -> None:
    life = parse_rule_file(_vector_text("compile-life-table"))
    for boundary, shift in (("torus", 0), ("klein", 3), ("cross", 0), ("dead", 0)):
        a = RuleTableCA(life, size=(30, 30), init="soup", density=0.4, seed=4,
                        boundary=boundary, shift=shift)  # fmt: skip
        b = LifeLike("B3/S23", size=(30, 30), init="soup", density=0.4, seed=4,
                     boundary=boundary, shift=shift)  # fmt: skip
        for _ in range(12):
            assert np.array_equal(a.state, b.state)
            a.step()
            b.step()
    hexagonal = parse_rule_file(_vector_text("compile-hex-b2-s34"))
    a = RuleTableCA(hexagonal, size=(32, 32), init="soup", density=0.3, seed=9, boundary="torus")
    b = LifeLike("B2/S34H", size=(32, 32), init="soup", density=0.3, seed=9)
    for _ in range(10):
        assert np.array_equal(a.state, b.state)
        a.step()
        b.step()
    from heaton_life.ca.wireworld import clock_loop

    wire = parse_rule_file(_vector_text("compile-wireworld-table"))
    a = RuleTableCA(wire, size=(20, 20), init=clock_loop((20, 20)))
    w = Wireworld(size=(20, 20), init=clock_loop((20, 20)))
    for _ in range(50):
        assert np.array_equal(a.state, w.state)
        a.step()
        w.step()


def test_a_one_dimensional_table_runs_every_row_by_itself() -> None:
    rows = parse_rule_file(_vector_text("compile-rule30-rows"))
    world = RuleTableCA(rows, size=(40, 6), init="soup", density=0.2, seed=1, boundary="torus")
    cells = world.state.copy()
    for _ in range(15):
        world.step()
        left, right = np.roll(cells, 1, axis=1), np.roll(cells, -1, axis=1)
        cells = ((30 >> (4 * left + 2 * cells + right)) & 1).astype(np.uint8)
        assert np.array_equal(world.state, cells)


def test_errors_carry_the_reason_and_the_line() -> None:
    rule, error = try_parse_rule_file("@RULE X\n@TABLE\nn_states:9\n")
    assert rule is None and error is not None
    assert (error.reason, error.line) == ("'neighborhood' is missing", None)
    with pytest.raises(RuleFileError, match=r"^invalid rule file: line 1: '@RULE' has no name"):
        parse_rule_file("@RULE\n")
    with pytest.raises(TypeError):
        parse_rule_file(b"@RULE X")  # type: ignore[arg-type]


def test_the_rule_keeps_its_file() -> None:
    text = _vector_text("compile-data-sections")
    rule = parse_rule_file(text)
    assert rule.text == text and rule.name == rule.canonical == "Data-Sections"
    assert rule.icons is not None and rule.icons.sets[0].count == 2
    assert [n.name for n in rule.names] == ["nothing", "first one"]
