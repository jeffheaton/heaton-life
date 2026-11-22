"""Grid topology conformance: replay vectors/topology/ — each topology's halo (where every
point past an edge lands), the bounded-grid suffix read and canonicalized, and a rule's
text split at its suffix, with the reasons for every error (spec/topology.md). The .NET
suite replays the same files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from heaton_life.core import (
    Halo,
    Topology,
    TopologyError,
    parse_bounded_grid,
    split_rule_suffix,
    try_parse_bounded_grid,
)

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "topology"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.16.0"}
_KEYS = {"spec_version", "family", "tier", "kind", "cases"}
_HALO = {"width", "height", "boundary", "shift", "axis", "radius"}
_SUFFIX = {"input", "canonical", "width", "height", "boundary", "shift", "axis"}
_ERROR = {"input", "error", "reason"}


def test_topology_vectors_exist() -> None:
    kinds = {json.loads(c.read_text(encoding="utf-8"))["kind"] for c in CASES}
    assert kinds == {"halo", "suffix", "split"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_topology_vector(case: Path) -> None:
    meta: dict[str, Any] = json.loads(case.read_text(encoding="utf-8"))
    assert set(meta) == _KEYS
    assert meta["spec_version"] in SPEC_VERSIONS
    assert (meta["family"], meta["tier"]) == ("topology", "bit-exact")
    kind = meta["kind"]
    for entry in meta["cases"]:
        if kind == "halo":
            _halo(entry)
        elif kind == "suffix":
            _suffix(entry)
        else:
            assert kind == "split"
            _split(entry)


def _halo(entry: dict[str, Any]) -> None:
    sizes = (entry["width"], entry["height"], entry["radius"])
    if entry.get("error"):
        assert set(entry) == _HALO | {"error", "reason"}
        with pytest.raises(TopologyError) as refused:
            Halo(Topology(entry["boundary"], entry["shift"], entry["axis"]), *sizes)
        assert refused.value.reason == entry["reason"], entry
        return
    assert set(entry) == _HALO | {"map"}
    topology = Topology(entry["boundary"], entry["shift"], entry["axis"])
    assert (topology.shift, topology.axis) == (entry["shift"], entry["axis"])  # canonical
    halo = Halo(topology, *sizes)
    expected = np.array(entry["map"], dtype=np.intp)
    assert np.array_equal(halo.sources(), expected), entry
    # And cell by cell, from locate itself.
    width, height, radius = sizes
    for (row, column), source in np.ndenumerate(expected):
        cell = topology.locate(column - radius, row - radius, width, height)
        assert source == (-1 if cell is None else cell[1] * width + cell[0])
    # A fill of distinct values holds the mapped ones, the blank where there is none.
    if width * height < 255:
        cells = np.arange(1, width * height + 1, dtype=np.uint8).reshape(height, width)
        assert np.array_equal(halo.fill(cells).astype(np.intp) - 1, expected)


def _suffix(entry: dict[str, Any]) -> None:
    text = entry["input"]
    if entry.get("error"):
        assert set(entry) == _ERROR
        assert try_parse_bounded_grid(text) == (None, entry["reason"])
        with pytest.raises(ValueError) as refused:
            parse_bounded_grid(text)
        reason = entry["reason"]
        assert str(refused.value) == f"invalid bounded grid '{text}': {reason} (spec/topology.md)"
        return
    assert set(entry) == _SUFFIX
    grid = parse_bounded_grid(text)
    topology = grid.topology
    found = (grid.width, grid.height, topology.boundary, topology.shift, topology.axis)
    wanted = tuple(entry[k] for k in ("width", "height", "boundary", "shift", "axis"))
    assert found == wanted, entry
    assert grid.suffix == entry["canonical"]
    assert parse_bounded_grid(entry["canonical"]) == grid


def _split(entry: dict[str, Any]) -> None:
    text = entry["input"]
    if entry.get("error"):
        assert set(entry) == _ERROR
        with pytest.raises(TopologyError) as refused:
            split_rule_suffix(text)
        assert refused.value.reason == entry["reason"], entry
        return
    assert set(entry) == {"input", "rule", "suffix"}
    rule, grid = split_rule_suffix(text)
    assert rule == entry["rule"]
    assert (None if grid is None else grid.suffix) == entry["suffix"]
