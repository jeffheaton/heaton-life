"""The OTCA metapixel tiles (Brice Due, 2006), OFF and ON, programmed for B3/S23.

The tiles are assembled exactly as Dave Greene's metafier.py assembles them: about a
hundred RLE fragments placed, rotated, unioned and pre-run. That script lives in Golly's
source repository; this tool downloads it once (pinned by commit and SHA-256) and reads
its construction section as a layout description, never as code: the source is parsed
with ``ast`` and only an allow-list is evaluated (see ``Layout``). heaton-life's HashLife
does every pre-run.

Usage: python tiles.py [--metafier PATH] [--out out/tiles.npz]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import textwrap
import time
import urllib.request
from pathlib import Path

import numpy as np

from heaton_life.ca.hashlife import HashLife

OUT = Path(__file__).resolve().parent / "out"
METAFIER_URL = (
    "https://sourceforge.net/p/golly/code/ci/0df88ec6a8ef3f800fbf41e255d8b1405a6ee549"
    "/tree/Scripts/Python/metafier.py?format=raw"
)
METAFIER_SIZE = 42866
METAFIER_SHA256 = "3f424bb67b5381a30a8c6695dc2aa168e490fda18f0242396260be75071440f0"
RULE_B, RULE_S = "3", "23"

Cell = tuple[int, int]
Transform = tuple[int, int, int, int]  # (axx, axy, ayx, ayy): x' = x0 + axx x + axy y, …

# The script's named transforms.
TRANSFORMS: dict[str, Transform] = {
    "identity": (1, 0, 0, 1),
    "flip": (-1, 0, 0, -1),
    "flip_x": (-1, 0, 0, 1),
    "flip_y": (1, 0, 0, -1),
    "swap_xy": (0, 1, 1, 0),
    "swap_xy_flip": (0, -1, -1, 0),
    "rcw": (0, -1, 1, 0),
    "rccw": (0, 1, -1, 0),
}
_TOKEN = re.compile(r"(\d*)([bo$!])")


def fetch(dest: Path) -> bytes:
    """The pinned metafier.py: from ``dest`` when it is already there, else downloaded."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            METAFIER_URL, headers={"User-Agent": "heaton-life life_in_life example"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
    data = dest.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != METAFIER_SIZE or digest != METAFIER_SHA256:
        raise SystemExit(
            f"{dest}: {len(data)} bytes, SHA-256 {digest}; expected {METAFIER_SIZE} bytes, "
            f"{METAFIER_SHA256}. Delete it to download again."
        )
    return data


def parse_rle(text: str) -> set[Cell]:
    """A two-state RLE body (no header) as live cells, top-left at (0, 0)."""
    body = "".join(text.split())
    cells: set[Cell] = set()
    x = y = pos = 0
    while pos < len(body):
        m = _TOKEN.match(body, pos)
        if m is None:
            raise ValueError(f"bad RLE at {pos}: {body[pos : pos + 20]!r}")
        pos = m.end()
        n = int(m.group(1)) if m.group(1) else 1
        tag = m.group(2)
        if tag == "o":
            cells.update((x + i, y) for i in range(n))
        if tag in "bo":
            x += n
        elif tag == "$":
            x, y = 0, y + n
        else:
            break
    return cells


def transform(cells: set[Cell], x0: int, y0: int, a: Transform) -> set[Cell]:
    axx, axy, ayx, ayy = a
    return {(x0 + axx * x + axy * y, y0 + ayx * x + ayy * y) for x, y in cells}


def evolve(cells: set[Cell], n: int) -> set[Cell]:
    """B3/S23 on the unbounded plane for n generations, by HashLife."""
    if not cells or n == 0:
        return set(cells)
    xy = np.array(sorted(cells), dtype=np.int64)
    x0, y0 = (int(v) for v in xy.min(axis=0))
    x1, y1 = (int(v) for v in xy.max(axis=0))
    grid = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.uint8)
    grid[xy[:, 1] - y0, xy[:, 0] - x0] = 1
    u = HashLife("B3/S23", max_memory_mb=4000)
    u.set_rect(x0, y0, grid)
    u.step(n)
    box = u.bounding_box()
    if box is None:
        return set()
    bx0, by0, bx1, by1 = box
    rows, cols = np.nonzero(u.get_rect(bx0, by0, bx1, by1))
    return set(zip((cols + bx0).tolist(), (rows + by0).tolist()))


class Cells:
    """A pattern as the script uses one: + is union, p(x, y, A) transforms, p[n] pre-runs."""

    def __init__(self, cells: set[Cell] | None = None) -> None:
        self.cells: set[Cell] = cells if cells is not None else set()

    def __add__(self, other: Cells) -> Cells:
        return Cells(self.cells | other.cells)


Value = str | int | Transform | Cells


class Layout:
    """Evaluates the script's construction section as data. Allowed: str and int literals;
    + − * % on them; names; ``pattern(rle[, x, y[, A]])``; ``p + q``; ``p(x, y[, A])``;
    ``p[n]``; assignment, ``+=``, and ``for i in range(...)``. ``g.show(...)`` status lines
    and the ``if os.access(...)`` blocks that save files are skipped. Anything else raises."""

    def __init__(self) -> None:
        self.env: dict[str, Value] = dict(TRANSFORMS)

    def run(self, stmts: list[ast.stmt]) -> None:
        for s in stmts:
            self.stmt(s)

    def stmt(self, s: ast.stmt) -> None:
        if isinstance(s, ast.Expr) and self._is_status_line(s.value):
            return
        if isinstance(s, ast.If) and "os.access" in ast.unparse(s.test):
            return
        if isinstance(s, ast.Assign):
            names = [t.id for t in s.targets if isinstance(t, ast.Name)]
            if len(names) == len(s.targets):
                v = self.expr(s.value)
                for name in names:
                    self.env[name] = v
                return
        if (
            isinstance(s, ast.AugAssign)
            and isinstance(s.target, ast.Name)
            and isinstance(s.op, ast.Add)
        ):
            self.env[s.target.id] = self._add(self.env[s.target.id], self.expr(s.value))
            return
        if (
            isinstance(s, ast.For)
            and isinstance(s.target, ast.Name)
            and not s.orelse
            and isinstance(s.iter, ast.Call)
            and isinstance(s.iter.func, ast.Name)
            and s.iter.func.id == "range"
            and not s.iter.keywords
        ):
            for i in range(*(self._int(a) for a in s.iter.args)):
                self.env[s.target.id] = i
                self.run(s.body)
            return
        raise ValueError(f"line {s.lineno}: outside the allow-list: {ast.unparse(s)[:80]}")

    @staticmethod
    def _is_status_line(e: ast.expr) -> bool:
        return (
            isinstance(e, ast.Call)
            and isinstance(e.func, ast.Attribute)
            and isinstance(e.func.value, ast.Name)
            and e.func.value.id == "g"
            and e.func.attr == "show"
        )

    def _int(self, e: ast.expr) -> int:
        v = self.expr(e)
        if not isinstance(v, int):
            raise TypeError(f"expected an integer: {ast.unparse(e)}")
        return v

    @staticmethod
    def _transform(v: Value) -> Transform:
        if isinstance(v, tuple) and len(v) == 4:
            return v
        raise ValueError(f"expected a transform, got {v!r}")

    @staticmethod
    def _add(a: Value, b: Value) -> Value:
        if isinstance(a, Cells) and isinstance(b, Cells):
            return a + b
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        if isinstance(a, int) and isinstance(b, int):
            return a + b
        raise ValueError(f"cannot add {type(a).__name__} and {type(b).__name__}")

    def expr(self, e: ast.expr) -> Value:
        if isinstance(e, ast.Constant):
            v = e.value
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                return v
        elif isinstance(e, ast.Name):
            if e.id in self.env:
                return self.env[e.id]
            raise ValueError(f"unknown name {e.id}")
        elif isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.USub):
            return -self._int(e.operand)
        elif isinstance(e, ast.BinOp):
            return self._binop(e)
        elif isinstance(e, ast.Subscript):
            p = self.expr(e.value)
            n = self._int(e.slice)
            if isinstance(p, Cells) and 0 <= n <= 10_000:
                return Cells(evolve(p.cells, n))
        elif isinstance(e, ast.Call) and not e.keywords:
            return self._call(e)
        raise ValueError(f"outside the allow-list: {ast.unparse(e)[:80]}")

    def _binop(self, e: ast.BinOp) -> Value:
        a, b = self.expr(e.left), self.expr(e.right)
        if isinstance(e.op, ast.Add):
            return self._add(a, b)
        if isinstance(e.op, ast.Mult) and isinstance(b, int):
            if isinstance(a, str) and 0 <= b <= 1000:
                return a * b
            if isinstance(a, int):
                return a * b
        if isinstance(a, int) and isinstance(b, int):
            if isinstance(e.op, ast.Mod):
                return a % b
            if isinstance(e.op, ast.Sub):
                return a - b
        raise ValueError(f"outside the allow-list: {ast.unparse(e)[:80]}")

    def _call(self, e: ast.Call) -> Value:
        args = [self.expr(a) for a in e.args]
        if isinstance(e.func, ast.Name) and e.func.id == "pattern":
            if not args:
                return Cells()
            rle, rest = args[0], args[1:]
            if isinstance(rle, str) and len(rest) in (0, 2, 3):
                x0, y0 = (rest[0], rest[1]) if rest else (0, 0)
                a = self._transform(rest[2]) if len(rest) == 3 else TRANSFORMS["identity"]
                if isinstance(x0, int) and isinstance(y0, int):
                    return Cells(transform(parse_rle(rle), x0, y0, a))
        else:
            p = self.expr(e.func)
            if isinstance(p, Cells) and len(args) in (2, 3):
                x0, y0 = args[0], args[1]
                a = self._transform(args[2]) if len(args) == 3 else TRANSFORMS["identity"]
                if isinstance(x0, int) and isinstance(y0, int):
                    return Cells(transform(p.cells, x0, y0, a))
        raise ValueError(f"outside the allow-list: {ast.unparse(e)[:80]}")


def rule_bits() -> Cells:
    """The metapixel's B/S table: one cell per birth or survival count, as the script
    derives it (the counts run from 8 at the top to 0 at the bottom)."""
    brle = srle = "b10$b10$b26$b10$b10$b26$b10$b10$b!"
    for ch in RULE_B:
        i = 32 - int(ch) * 4
        brle = brle[:i] + "o" + brle[i + 1 :]
    for ch in RULE_S:
        i = 32 - int(ch) * 4
        srle = srle[:i] + "o" + srle[i + 1 :]
    identity = TRANSFORMS["identity"]
    return Cells(
        transform(parse_rle(brle), 148, 1404, identity)
        | transform(parse_rle(srle), 162, 1406, identity)
    )


def build(source: str) -> tuple[set[Cell], set[Cell]]:
    """(OFF, ON) tiles; each spans cells −5..2052 and repeats on a 2048-cell pitch."""
    lines = source.splitlines()
    start = next(i for i, ln in enumerate(lines) if "Building OFF metacell" in ln)
    end = next(i for i, ln in enumerate(lines) if ln.startswith("OFFcell += RuleBits"))
    layout = Layout()
    layout.run(ast.parse(textwrap.dedent("\n".join(lines[start:end]))).body)
    off, on, bits = layout.env["OFFcell"], layout.env["ONcell"], rule_bits()
    if not (isinstance(off, Cells) and isinstance(on, Cells)):
        raise TypeError("the construction section built no OFFcell/ONcell")
    return (off + bits).cells, (on + bits).cells


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metafier", type=Path, default=OUT / "metafier.py")
    ap.add_argument("--out", type=Path, default=OUT / "tiles.npz")
    args = ap.parse_args()
    source = fetch(args.metafier).decode()
    t0 = time.perf_counter()
    off, on = build(source)
    print(f"built in {time.perf_counter() - t0:.1f} s")
    off_a, on_a = (np.array(sorted(c), dtype=np.int32) for c in (off, on))
    for name, a in (("OFF", off_a), ("ON", on_a)):
        print(
            f"{name}: {len(a):,} cells, x {a[:, 0].min()}..{a[:, 0].max()}, "
            f"y {a[:, 1].min()}..{a[:, 1].max()}"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, off=off_a, on=on_a)
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
