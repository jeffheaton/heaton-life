"""MergeLife cellular automaton (Heaton 2017, arXiv:1712.03019) — spec/mergelife.md.

Faithful port of the reference engine (github.com/jeffheaton/mergelife,
python/mergelife-lib), byte-identical per the upstream cross-engine conformance
vectors replayed in tests/test_mergelife.py. Do not "clean up" the numerics:
the stable sort by range limit alone, the mode-padded neighbor convolution, the
127/128 percent scaling, and the floor semantics are all part of the contract.
"""

from __future__ import annotations

import dataclasses
import re

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.params import Params
from heaton_life.core.rng import Pcg32
from heaton_life.init.patterns import clear

# The eight key colors: corners of the RGB cube, in rule order.
COLOR_TABLE = np.array(
    [
        [0, 0, 0],  # black
        [255, 0, 0],  # red
        [0, 255, 0],  # green
        [255, 255, 0],  # yellow
        [0, 0, 255],  # blue
        [255, 0, 255],  # purple
        [0, 255, 255],  # cyan
        [255, 255, 255],  # white
    ],
    dtype=np.int64,
)

_RULE = re.compile(r"^[0-9a-f]{32}$")


def parse_rule(rule: str) -> list[tuple[int, int]]:
    """Hex rule -> eight (range_byte, percent_byte) pairs; percent is a signed byte."""
    text = rule.strip().lower().replace("-", "")
    if not _RULE.match(text):
        raise ValueError(
            f"invalid MergeLife rule {rule!r} (expected 8 dash-separated groups of 4 hex digits)"
        )
    pairs: list[tuple[int, int]] = []
    for i in range(8):
        rng = int(text[i * 4 : i * 4 + 2], 16)
        pct = int(text[i * 4 + 2 : i * 4 + 4], 16)
        if pct >= 128:  # two's complement
            pct -= 256
        pairs.append((rng, pct))
    return pairs


def parse_rule_error(rule: str) -> str | None:
    """Validation helper: the parse error message, or None if the rule is valid."""
    try:
        parse_rule(rule)
    except ValueError as exc:
        return str(exc)
    return None


def canonical_rule(rule: str) -> str:
    """Normalize to the canonical lowercase dashed form."""
    parse_rule(rule)
    text = rule.strip().lower().replace("-", "")
    return "-".join(text[i * 4 : i * 4 + 4] for i in range(8))


def compile_rule(rule: str) -> list[tuple[int, float, int]]:
    """Rule -> sub-rules (limit, percent, color_index), stably sorted by limit alone.

    limit = range_byte * 8, with the full-range value 2040 promoted to 2048 so the
    top sub-rule catches every neighbor count. percent = pct/127 if positive else
    pct/128, giving [-1.0, 1.0].
    """
    entries: list[tuple[int, float, int]] = []
    for index, (rng, pct) in enumerate(parse_rule(rule)):
        limit = rng * 8
        if limit == 2040:
            limit = 2048
        percent = pct / 127.0 if pct > 0 else pct / 128.0
        entries.append((limit, percent, index))
    return sorted(entries, key=lambda e: e[0])  # stable: ties keep rule order


COLOR_NAMES = ("Black", "Red", "Green", "Yellow", "Blue", "Purple", "Cyan", "White")


@dataclasses.dataclass(frozen=True)
class DecodedSubRule:
    """One row of the rule-lab table — spec/mergelife.md "Decoded rule table"."""

    limit: int
    range_low: int
    range_high: int
    percent: float
    color_index: int
    color_name: str
    target_index: int
    target_name: str
    target_rgb: tuple[int, int, int]
    range_byte: int
    percent_byte: int


def decode_rule(rule: str) -> list[DecodedSubRule]:
    """The 8 sub-rules as display-ready rows, in compiled (sorted) order.

    Carries the raw octets alongside the compiled values: HeatonCA re-derives
    octet 1 from the promoted limit (2048/8 = 0x100) — the raw byte is 0xff.
    """
    raw = parse_rule(rule)
    rows: list[DecodedSubRule] = []
    low = 0
    for limit, percent, index in compile_rule(rule):
        range_byte, percent_byte = raw[index]
        target = (index + 1) % len(COLOR_NAMES) if percent < 0 else index
        r, g, b = (int(c) for c in COLOR_TABLE[target])
        rows.append(
            DecodedSubRule(
                limit=limit,
                range_low=low,
                range_high=limit - 1,
                percent=percent,
                color_index=index,
                color_name=COLOR_NAMES[index],
                target_index=target,
                target_name=COLOR_NAMES[target],
                target_rgb=(r, g, b),
                range_byte=range_byte,
                percent_byte=percent_byte,
            )
        )
        low = limit
    return rows


def random_rule(seed: int) -> str:
    """A random rule from PCG32 (UI convenience; not part of the upstream contract)."""
    rng = Pcg32(seed)
    groups = []
    for _ in range(8):
        range_byte = rng.next_u32() & 0xFF
        pct_byte = rng.next_u32() & 0xFF
        groups.append(f"{range_byte:02x}{pct_byte:02x}")
    return "-".join(groups)


@dataclasses.dataclass(frozen=True)
class MergeLifeParams(Params):
    rule: str = dataclasses.field(
        default="e542-5f79-9341-f31e-6c6b-7f08-8773-7068",  # "Red World" (paper)
        metadata={"label": "Rule"},
    )
    width: int = dataclasses.field(default=128, metadata={"min": 8, "max": 1024})
    height: int = dataclasses.field(default=128, metadata={"min": 8, "max": 1024})
    init: str = dataclasses.field(default="soup", metadata={"choices": ["soup"]})
    seed: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"}
    )


class MergeLife:
    """MergeLife CA. State is uint8 RGB, shape (height, width, 3), row-major."""

    def __init__(
        self,
        rule: str = "e542-5f79-9341-f31e-6c6b-7f08-8773-7068",
        *,
        size: tuple[int, int] = (128, 128),
        init: str | NDArray[np.uint8] = "soup",
        seed: int = 0,
    ) -> None:
        width, height = size
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width, 3):
                raise ValueError(
                    f"init array shape {init.shape} does not match (h={height}, w={width}, 3)"
                )
            self._initial = init.astype(np.uint8)
            init_name = "array"
        else:
            init_name = init
        self.params = MergeLifeParams(
            rule=canonical_rule(rule),
            width=width,
            height=height,
            init=init_name,
            seed=seed,
        )
        self._rule = compile_rule(self.params.rule)
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: MergeLifeParams) -> MergeLife:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: MergeLife(init=...)")
        return cls(
            params.rule,
            size=(params.width, params.height),
            init=params.init,
            seed=params.seed,
        )

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
        elif p.init == "soup":
            rng = Pcg32(p.seed)
            flat = np.fromiter(
                (rng.next_u32() & 0xFF for _ in range(p.width * p.height * 3)),
                dtype=np.uint8,
                count=p.width * p.height * 3,
            )
            self._state = flat.reshape(p.height, p.width, 3)
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._generation = 0

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._state = _update(self._state, self._rule)
        self._generation += n

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """spec/patterns.md "Clear": inclusive rectangle to this family's blank.

        MergeLife's blank is black (0, 0, 0); the trailing RGB axis broadcasts. The generation is untouched, exactly like stamping. The C# port has
        carried this per family as ``ClearRect`` all along; the Python library had
        no equivalent at all, even though the spec lists Clear alongside Extract
        and Stamp as normative.
        """
        clear(self._state, x0, y0, x1, y1, 0)

    def frame(self) -> NDArray[np.uint8]:
        return self._state.copy()


def _update(
    prev: NDArray[np.uint8], rule: list[tuple[int, float, int]]
) -> NDArray[np.uint8]:
    """One MergeLife step, exactly per the reference engine."""
    height, width = prev.shape[:2]

    # Merged grid: integer floor((r+g+b)/3).
    avg = prev.astype(np.int64).sum(axis=2) // 3
    # Grid mode of the merged values; bincount().argmax() breaks ties toward the
    # lowest value, same as the reference.
    pad_val = int(np.bincount(avg.ravel()).argmax())
    # 3x3 neighbor sum (center excluded), boundary padded with the mode.
    padded = np.full((height + 2, width + 2), pad_val, dtype=np.int64)
    padded[1:-1, 1:-1] = avg
    cnt = (
        padded[:-2, :-2]
        + padded[:-2, 1:-1]
        + padded[:-2, 2:]
        + padded[1:-1, :-2]
        + padded[1:-1, 2:]
        + padded[2:, :-2]
        + padded[2:, 1:-1]
        + padded[2:, 2:]
    )

    # Unmatched cells keep their value.
    new = prev.copy()
    remaining = np.ones((height, width), dtype=bool)
    for limit, percent, color_index in rule:
        mask = (cnt < limit) & remaining
        if not mask.any():
            continue
        remaining &= ~mask
        if percent < 0:
            percent = -percent
            color_index = (color_index + 1) % len(COLOR_TABLE)
        sel = prev[mask].astype(np.int64)
        moved = sel + np.floor((COLOR_TABLE[color_index] - sel) * percent)
        new[mask] = moved.astype(np.uint8)
    return new
