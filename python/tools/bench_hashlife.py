#!/usr/bin/env python3
"""Measure HashLife throughput (spec/hashlife.md): load time, then generations per second
at fixed step sizes 2^e, with population, nodes, store memory (and its peak), collections,
and the process's peak RSS.

Usage:
    .venv/bin/python tools/bench_hashlife.py
    .venv/bin/python tools/bench_hashlife.py .patterns/caterpillar.mc --exponents 0,4,8 \
        --budget 4000 --seconds 30 --min-steps 2

(tools/fetch_patterns.py puts the giants in .patterns/.)

With no files it runs a built-in set: a methuselah, a gun, and a 256×256 soup.
"""

from __future__ import annotations

import argparse
import resource
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


def _max_rss_mib() -> float:
    """The process's peak resident set (ru_maxrss is bytes on macOS, KiB elsewhere)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 2**20 if sys.platform == "darwin" else rss / 2**10


def bench(
    label: str,
    make: Callable[[], HashLife],
    exponents: list[int],
    seconds: float,
    min_steps: int = 1,
) -> None:
    start = time.perf_counter()
    u = make()
    load = time.perf_counter() - start
    print(
        f"{label}: loaded in {load:.2f}s — population {u.population:,}, nodes {u.node_count:,}, "
        f"budget {u.max_memory_mb:,} MiB",
        flush=True,
    )
    peak = u.memory_used
    for e in exponents:
        first = u.generation
        steps = 0
        start = time.perf_counter()
        while steps < min_steps or time.perf_counter() - start < seconds:
            u.step(1 << e)
            steps += 1
            peak = max(peak, u.memory_used)  # sampled between steps; GC runs at 3/4
        elapsed = time.perf_counter() - start
        gens = u.generation - first
        print(
            f"  2^{e:<3} {steps:>6} steps  {gens:>16,} gens  {elapsed:7.2f}s  "
            f"{gens / elapsed:>16,.0f} gen/s  pop {u.population:,}  nodes {u.node_count:,}  "
            f"store {u.memory_used / 2**20:,.0f} MiB (peak {peak / 2**20:,.0f})  "
            f"GCs {u.collections}  max RSS {_max_rss_mib():,.0f} MiB",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help=".rle, .mc, or .mc.gz patterns")
    parser.add_argument("--exponents", default="0,4,8", help="step sizes 2^e, comma-separated")
    parser.add_argument("--seconds", type=float, default=3.0, help="time per step size")
    parser.add_argument("--budget", type=int, default=500, help="max_memory_mb")
    parser.add_argument("--min-steps", type=int, default=1, help="steps per size, at least")
    args = parser.parse_args()
    exponents = [int(e) for e in args.exponents.split(",")]
    if args.files:
        for path in args.files:
            bench(
                path.name,
                lambda p=path: HashLife.from_file(p, max_memory_mb=args.budget),
                exponents,
                args.seconds,
                args.min_steps,
            )
        return
    bench("R-pentomino", lambda: _builtin("R-pentomino", args.budget), [0, 8, 16], args.seconds)
    bench(
        "Gosper gun", lambda: _builtin("Gosper glider gun", args.budget), [4, 16, 40], args.seconds
    )
    bench("soup 256×256", lambda: _soup(args.budget), exponents, args.seconds)


if __name__ == "__main__":
    main()
