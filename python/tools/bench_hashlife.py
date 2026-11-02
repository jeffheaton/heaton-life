#!/usr/bin/env python3
"""Measure HashLife throughput (spec/hashlife.md): load time, then generations per second
at fixed step sizes 2^e, with population, nodes, store memory, and collections.

Usage:
    .venv/bin/python tools/bench_hashlife.py
    .venv/bin/python tools/bench_hashlife.py caterpillar.mc --exponents 0,4,8 --budget 4000

With no files it runs a built-in set: a methuselah, a gun, and a 256×256 soup.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.ca.hashlife import HashLife
from heaton_life.init import BUILTIN_PATTERNS


def _builtin(name: str, budget: int) -> HashLife:
    u = HashLife(max_memory_mb=budget)
    u.set_rect(0, 0, next(p for p in BUILTIN_PATTERNS if p.name == name).cells())
    return u


def _soup(budget: int) -> HashLife:
    u = HashLife(max_memory_mb=budget)
    u.fill_random(-128, -128, 127, 127, density=0.35, seed=1)
    return u


def bench(label: str, make: Callable[[], HashLife], exponents: list[int], seconds: float) -> None:
    start = time.perf_counter()
    u = make()
    load = time.perf_counter() - start
    print(f"{label}: loaded in {load:.2f}s — population {u.population:,}, nodes {u.node_count:,}")
    for e in exponents:
        first = u.generation
        steps = 0
        start = time.perf_counter()
        while not steps or time.perf_counter() - start < seconds:
            u.step(1 << e)
            steps += 1
        elapsed = time.perf_counter() - start
        gens = u.generation - first
        print(
            f"  2^{e:<3} {steps:>6} steps  {gens:>16,} gens  {elapsed:7.2f}s  "
            f"{gens / elapsed:>16,.0f} gen/s  pop {u.population:,}  nodes {u.node_count:,}  "
            f"store {u.memory_used / 2**20:,.0f} MiB  GCs {u.collections}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help=".rle, .mc, or .mc.gz patterns")
    parser.add_argument("--exponents", default="0,4,8", help="step sizes 2^e, comma-separated")
    parser.add_argument("--seconds", type=float, default=3.0, help="time per step size")
    parser.add_argument("--budget", type=int, default=500, help="max_memory_mb")
    args = parser.parse_args()
    exponents = [int(e) for e in args.exponents.split(",")]
    if args.files:
        for path in args.files:
            bench(
                path.name,
                lambda p=path: HashLife.from_file(p, max_memory_mb=args.budget),
                exponents,
                args.seconds,
            )
        return
    bench("R-pentomino", lambda: _builtin("R-pentomino", args.budget), [0, 8, 16], args.seconds)
    bench(
        "Gosper gun", lambda: _builtin("Gosper glider gun", args.budget), [4, 16, 40], args.seconds
    )
    bench("soup 256×256", lambda: _soup(args.budget), exponents, args.seconds)


if __name__ == "__main__":
    main()
