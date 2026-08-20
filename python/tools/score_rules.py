#!/usr/bin/env python3
"""Score MergeLife rules under the paper objective (spec/evolve.md).

Feed it hex codes and it prints each rule's objective score at the paper
config (100x100, 5 cycles, max over cycles), best first. Scoring is
deterministic per seed; pass --repeats to see the spread across seeds the
way the reference trainer's random lattices did.

Usage:
  .venv/bin/python tools/score_rules.py RULE [RULE ...]
  .venv/bin/python tools/score_rules.py --file rules.txt        # one rule per line
  .venv/bin/python tools/score_rules.py --size 50 50 RULE       # the app's evolve grid
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.ca.mergelife import parse_rule_error
from heaton_life.evolve import score_genome


def read_rules(args: argparse.Namespace) -> list[str]:
    rules: list[str] = list(args.rules)
    if args.file is not None:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
        rules.extend(line.strip() for line in text.splitlines() if line.strip())
    return rules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rules", nargs="*", help="MergeLife rule hex codes")
    parser.add_argument("--file", help="file of rules, one per line ('-' for stdin)")
    parser.add_argument(
        "--size", nargs=2, type=int, default=(100, 100), metavar=("W", "H"),
        help="lattice size (default 100 100, the paper config)")
    parser.add_argument(
        "--cycles", type=int, default=5,
        help="evaluation cycles; the score is the max over them (default 5)")
    parser.add_argument("--seed", type=int, default=0, help="base lattice seed (default 0)")
    parser.add_argument(
        "--repeats", type=int, default=1,
        help="score this many times at seed, seed+cycles, ... (default 1)")
    args = parser.parse_args()

    rules = read_rules(args)
    if not rules:
        parser.error("no rules given (positional args or --file)")
    for rule in rules:
        error = parse_rule_error(rule)
        if error is not None:
            print(f"invalid rule {rule!r}: {error}", file=sys.stderr)
            return 1

    width, height = args.size
    results: list[tuple[str, list[float]]] = []
    for rule in rules:
        scores = [
            score_genome(
                rule,
                cycles=args.cycles,
                size=(width, height),
                seed=args.seed + repeat * args.cycles,
            )["score"]
            for repeat in range(args.repeats)
        ]
        results.append((rule, scores))
        spread = "  ".join(f"{score:7.3f}" for score in scores)
        print(f"scored {rule}  {spread}", file=sys.stderr)

    results.sort(key=lambda item: max(item[1]), reverse=True)
    print(f"\n{width}x{height}, {args.cycles} cycles, seed {args.seed}, "
          f"{args.repeats} repeat(s) — best first:")
    for rank, (rule, scores) in enumerate(results, start=1):
        spread = "  ".join(f"{score:7.3f}" for score in scores)
        print(f"{rank:3d}. {rule}  best {max(scores):7.3f}   ({spread})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
