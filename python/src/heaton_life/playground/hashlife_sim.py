"""Playground adapter: an unbounded HashLife universe through the Simulation protocol.

The universe lives in the sim; the view lives in the params — the frame's top-left pixel
(x, y) in the pixel plane, as decimal strings, and the magnification exponent ``mag``
(spec/hashlife.md "View and render") — so the auto-generated form edits it, as with
FractalSim. Only ``pattern`` is cold: loading a pattern adopts its rule and fits the view
to it. Every other field changes the sim in place, keeping the cells and the generation
(audit finding 10-01), and Reset restores the starting snapshot instead of reloading the
file. Each step advances 2^step_exponent generations.
"""

from __future__ import annotations

import dataclasses
import zlib
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife import (
    DEFAULT_MEMORY_MB,
    EDIT_LIMIT,
    MAX_LEVEL,
    MAX_MAG,
    MIN_MEMORY_MB,
    RENDER_MODES,
    HashLife,
    LifeView,
    RenderMode,
    StepCanceled,
    cell_at,
    center_cell,
    fit,
    pan,
    zoom_at,
)
from heaton_life.core.params import Params
from heaton_life.init import BUILTIN_PATTERNS

BUILTIN_NAMES = tuple(p.name for p in BUILTIN_PATTERNS if p.family == "lifelike")
PATTERN_SUFFIXES = (".rle", ".mc", ".mc.gz")
PATTERN_FILTER = "Patterns (*.rle *.mc *.gz);;All files (*)"
_SAVE_FILTERS = {
    ".rle": "RLE (*.rle)",
    ".mc": "Macrocell (*.mc)",
    ".mc.gz": "Gzipped Macrocell (*.mc.gz)",
}
SAVE_FILTER = ";;".join(_SAVE_FILTERS.values())
MAX_STEP_EXPONENT = MAX_LEVEL - 3  # 2^509, the largest sub-step (spec/hashlife.md "Depth")
_STEP_LIMIT = 1 << (MAX_LEVEL - 2)  # one engine step takes fewer generations than this


@dataclasses.dataclass(frozen=True)
class HashLifeSimParams(Params):
    pattern: str = dataclasses.field(
        default="Gosper glider gun",
        metadata={"role": "file", "filter": PATTERN_FILTER, "label": "Pattern"},
    )
    rule: str = dataclasses.field(default="B3/S23", metadata={"label": "Rule (B/S)"})
    step_exponent: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": MAX_STEP_EXPONENT, "label": "Step (2^k gens)"}
    )
    max_memory_mb: int = dataclasses.field(
        default=DEFAULT_MEMORY_MB,
        metadata={"min": MIN_MEMORY_MB, "max": 100_000_000, "label": "Max memory (MB)"},
    )
    mode: str = dataclasses.field(
        default="any", metadata={"choices": RENDER_MODES, "label": "Zoomed-out pixels"}
    )
    width: int = dataclasses.field(default=768, metadata={"min": 64, "max": 2048})
    height: int = dataclasses.field(default=512, metadata={"min": 64, "max": 2048})
    x: str = dataclasses.field(default="0", metadata={"label": "View x (px)"})
    y: str = dataclasses.field(default="0", metadata={"label": "View y (px)"})
    mag: int = dataclasses.field(
        default=0, metadata={"min": -4096, "max": MAX_MAG, "label": "Mag (2^mag px/cell)"}
    )


def _integer(text: str, name: str) -> int:
    """A decimal integer of any size: an optional '-' and ASCII digits, nothing else."""
    digits = text.removeprefix("-")
    if not (digits.isascii() and digits.isdigit()):
        raise ValueError(f"{name} must be a decimal integer, got {text!r}")
    return int(text)


def view_of(params: HashLifeSimParams) -> LifeView:
    return LifeView(_integer(params.x, "view x"), _integer(params.y, "view y"), params.mag)


def _render_mode(params: HashLifeSimParams) -> RenderMode:
    return "density" if params.mode == "density" else "any"


def load_pattern(pattern: str, max_memory_mb: int) -> HashLife:
    """A built-in pattern by name (top-left cell at (0, 0), under its own rule), or a
    ``.rle``/``.mc``/``.mc.gz`` file under the rule it names."""
    builtin = next((p for p in BUILTIN_PATTERNS if p.name == pattern), None)
    if builtin is not None and builtin.family == "lifelike":
        universe = HashLife(builtin.rule, max_memory_mb=max_memory_mb)
        universe.set_rect(0, 0, builtin.cells())
        return universe
    path = Path(pattern).expanduser()
    if not path.is_file():
        raise ValueError(f"no built-in pattern or file named {pattern!r}")
    try:
        return HashLife.from_file(path, max_memory_mb=max_memory_mb)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc


def _hot_problem(params: HashLifeSimParams) -> tuple[str, str] | None:
    for name in ("x", "y"):
        try:
            _integer(getattr(params, name), f"view {name}")
        except ValueError as exc:
            return (name, str(exc))
    if not 0 <= params.step_exponent <= MAX_STEP_EXPONENT:
        message = (
            f"a step is 2^0 to 2^{MAX_STEP_EXPONENT} generations, the deepest tree's "
            f'largest sub-step (spec/hashlife.md "Depth"); got 2^{params.step_exponent}'
        )
        return ("step_exponent", message)
    try:
        HashLife(params.rule, max_memory_mb=params.max_memory_mb)
    except ValueError as exc:
        return ("rule", str(exc))
    return None


def validate(params: Params) -> tuple[str, str] | None:
    """The first field the engine would reject, as (field, message), or None."""
    assert isinstance(params, HashLifeSimParams)
    problem = _hot_problem(params)
    if problem is not None:
        return problem
    pattern = params.pattern
    if pattern not in BUILTIN_NAMES and not Path(pattern).expanduser().is_file():
        return ("pattern", f"no built-in pattern or file named {pattern!r}")
    return None


class HashLifeSim:
    """A HashLife universe, the view of it, and the snapshot Reset returns to."""

    def __init__(self, universe: HashLife, params: HashLifeSimParams) -> None:
        self.universe = universe
        self.params = params
        self._view = view_of(params)
        self._start = universe.snapshot()
        self._frame: NDArray[np.uint8] | None = None
        self._canceled = False

    @classmethod
    def build(cls, params: Params) -> HashLifeSim:
        """Load the pattern, adopt its rule, and fit the view to it."""
        assert isinstance(params, HashLifeSimParams)
        universe = load_pattern(params.pattern, params.max_memory_mb)
        view = fit(universe.bounding_box(), (params.width, params.height))
        loaded = params.replace(rule=universe.rule, x=str(view.x), y=str(view.y), mag=view.mag)
        return cls(universe, loaded)

    def apply(self, params: HashLifeSimParams) -> None:
        """Hot fields in place: everything but the pattern; the cells and generation stay.
        (The pattern file may be gone by now: only reloading needs it.)"""
        problem = _hot_problem(params)
        if problem is not None:
            raise ValueError(problem[1])
        self._view = view_of(params)
        self.universe.max_memory_mb = params.max_memory_mb
        self.universe.rule = params.rule
        self.params = params
        self._frame = None

    # -- Simulation protocol ------------------------------------------------------------

    def step(self, n: int = 1) -> None:
        """Advance n steps of 2^step_exponent generations; ``cancel()`` cuts it short at a
        completed sub-step. A batch that would reach 2^510 generations, past what one
        engine step takes, goes in parts. A step that can't fit one generation into the
        budget raises HashLifeMemoryError, and a pattern spread past the deepest tree
        raises ValueError (the engine stops playing and shows either)."""
        universe = self.universe
        if universe.generation == self._start.generation:
            self._start = universe.snapshot()  # edits made at the start belong to it
        k = self.params.step_exponent
        per_part = (_STEP_LIMIT - 1) >> k  # whole steps one engine call can take
        self._canceled = False
        try:
            while n > 0 and not self._canceled:
                part = min(n, per_part)
                universe.step(part << k)
                n -= part
        except StepCanceled:
            pass  # the universe holds the last completed sub-step
        finally:
            self._frame = None

    def reset(self, seed: int | None = None) -> None:
        """Back to the starting cells and generation; rule, budget, and view stay."""
        self.universe.restore(self._start)
        self._frame = None

    def cancel(self) -> None:
        """Stop a running step early; safe to call from another thread."""
        self._canceled = True  # between parts of a batch
        self.universe.cancel()  # inside one

    @property
    def generation(self) -> int:
        return self.universe.generation

    @property
    def state(self) -> NDArray[np.uint8]:
        return self.frame()

    def frame(self) -> NDArray[np.uint8]:
        if self._frame is None:
            p = self.params
            self._frame = self.universe.render(self._view, (p.width, p.height), _render_mode(p))
        return self._frame

    # -- interaction --------------------------------------------------------------------

    def paint(self, x: int, y: int, button: int) -> bool:
        """Pixel (x, y) of the frame. 1: set the cell under it; 2: erase it; 3: recenter
        on it; 4/5: zoom in/out about it. True when the view moved. Raises ValueError for an
        edit outside the editing box, or zoomed out past one cell per pixel."""
        view = self._view
        if button in (1, 2):
            if view.mag < 0:
                raise ValueError("zoom in to one cell per pixel or closer to draw cells")
            cx, cy = cell_at(view, x, y)
            self.universe.set_cell(cx, cy, button == 1)
            self._frame = None
            return False
        p = self.params
        if button == 3:
            moved = pan(view, p.width // 2 - x, p.height // 2 - y)
        elif button in (4, 5):
            moved = zoom_at(view, x, y, 1 if button == 4 else -1)
        else:
            return False
        if moved == view:
            return False
        self.apply(p.replace(x=str(moved.x), y=str(moved.y), mag=moved.mag))
        return True

    def readout(self) -> str:
        """The status-bar line: population, step size, center cell, nodes, and memory."""
        u, p = self.universe, self.params
        cx, cy = center_cell(self._view, (p.width, p.height))
        return (
            f"pop {u.population:,} · step 2^{p.step_exponent} · center ({cx:,}, {cy:,}) · "
            f"{u.node_count:,} nodes · {u.memory_used / 2**20:,.0f} of "
            f"{u.max_memory_mb:,} MB"
        )

    # -- pattern files ------------------------------------------------------------------

    def pattern_suffix(self) -> str:
        """``.rle`` when RLE can carry the pattern (it lies inside the editing box), else
        ``.mc``: Macrocell carries anything."""
        box = self.universe.bounding_box()
        if box is None or max(abs(v) for v in box) <= EDIT_LIMIT:
            return ".rle"
        return ".mc"

    def pattern_file_name(self) -> str:
        """A suggested name for Save pattern: the pattern's name, generation, and suffix."""
        stem = Path(self.params.pattern).name
        for suffix in PATTERN_SUFFIXES[::-1]:  # .mc.gz before .mc
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        stem = "-".join(stem.split()) or "pattern"
        return f"{stem}-gen{self.universe.generation}{self.pattern_suffix()}"

    def save_pattern(self, path: str | Path) -> Path:
        """Write the cells by extension; a name without one gets ``pattern_suffix()``."""
        target = Path(path)
        if not target.name.lower().endswith(PATTERN_SUFFIXES):
            target = target.with_name(target.name + self.pattern_suffix())
        self.universe.save(target)
        return target


def save_filter_for(name: str) -> str:
    """The Save dialog's filter that matches a suggested file name."""
    lower = name.lower()
    for suffix in PATTERN_SUFFIXES[::-1]:
        if lower.endswith(suffix):
            return _SAVE_FILTERS[suffix]
    return _SAVE_FILTERS[".rle"]
