"""Generate the ants of the rule-table starter set (spec/ruletable.md, "The starter set").

An ant (a turmite of one internal state) on K colors is a rule table of 5K states: a cell
is its color c, or K + 4c + d where the ant stands on it with heading d (0 north, 1 east,
2 south, 3 west). The table is generated from the ant's definition, the turn it makes on
each color, so it is exactly that definition: on color c the ant turns, the cell takes
color c + 1 (mod K), and the ant steps forward. The rule files land beside the hand-written
loops in ``src/heaton_life/ca/rules/``; rerunning this script must reproduce them byte for
byte.

    .venv/bin/python tools/gen_rule_tables.py
"""

from __future__ import annotations

import pathlib

RULES = pathlib.Path(__file__).resolve().parent.parent / "src" / "heaton_life" / "ca" / "rules"

# The cell's neighbors in a vonNeumann transition's order (after C), each with the heading
# an ant there takes to step onto the cell.
_FROM = (("north", 2), ("east", 3), ("south", 0), ("west", 1))
_TURN = {"R": 1, "L": 3}


def ant_table(turns: str) -> list[str]:
    """The @TABLE section's lines for the ant whose turn on color k is ``turns[k]``."""
    k = len(turns)
    states = 5 * k

    def ant(color: int, heading: int) -> int:
        return k + 4 * color + heading

    lines = [
        f"n_states:{states}",
        "neighborhood:vonNeumann",
        "symmetries:none",
        "",
        "var a={" + ",".join(str(s) for s in range(states)) + "}",
        "var b={a}",
        "var c={a}",
        "var e={a}",
    ]
    # A center whose next color is n: the color n itself, or an ant on the color before it.
    for n in range(k):
        before = (n - 1) % k
        members = [n, *(ant(before, d) for d in range(4))]
        lines.append(f"var next{n}={{" + ",".join(str(m) for m in members) + "}")
    lines += ["", "# C N E S W C'"]
    for position, (side, heading) in enumerate(_FROM):
        lines.append(f"# An ant steps on from the {side}, now heading {'NESW'[heading]}.")
        for color in range(k):
            # The heading it had: the one its turn on this color makes into `heading`.
            before = (heading - _TURN[turns[color]]) % 4
            source = ant(color, before)
            for n in range(k):
                fields = ["a", "b", "c"]
                fields.insert(position, str(source))
                lines.append(",".join([f"next{n}", *fields, str(ant(n, heading))]))
    lines.append("# The ant leaves: its cell takes its next color.")
    for color in range(k):
        for d in range(4):
            lines.append(f"{ant(color, d)},a,b,c,e,{(color + 1) % k}")
    return lines


def ant_file(name: str, turns: str, description: str) -> str:
    k = len(turns)
    names = [f"{c} color {c}" for c in range(k)]
    names += [
        f"{k + 4 * c + d} ant on color {c} heading {['north', 'east', 'south', 'west'][d]}"
        for c in range(k)
        for d in range(4)
    ]
    return "\n".join(
        [
            f"@RULE {name}",
            "",
            description.strip(),
            "",
            f"States: a cell is its color c (0 to {k - 1}), or {k} + 4c + d where the ant",
            "stands on it with heading d (0 north, 1 east, 2 south, 3 west). Each",
            "generation the ant's cell takes its next color and the ant appears on the",
            "neighbor its new heading points to, facing that way. Two ants that would",
            "land on one cell: the one from the north wins, then east, south, west.",
            "",
            "Generated from the definition by python/tools/gen_rule_tables.py for",
            "heaton-life (spec/ruletable.md).",
            "",
            "@TABLE",
            *ant_table(turns),
            "",
            "@NAMES",
            *names,
            "",
        ]
    )


ANTS = (
    (
        "Langtons-Ant",
        "RL",
        """
Langton's ant.

Source: C. G. Langton, "Studying artificial life with cellular automata",
Physica D 22 (1986) 120-149. On a white cell (0) the ant turns right, on a
black one (1) left; it flips the cell's color and steps forward. From one ant
on an all-white plane its path looks random until step 9,977, and then it
builds a highway that repeats every 104 steps.

The starter pattern (Langtons-Ant.rle) is one ant facing north on color 0.
""",
    ),
    (
        "Ant-LLRR",
        "LLRR",
        """
The ant LLRR, of the many-color ants of Greg Turk and Jim Propp (D. Gale,
J. Propp, S. Sutherland and S. Troubetzkoy, "Further travels with my ant",
Mathematical Intelligencer 17:3 (1995) 48-56). On color k it turns as the
name's k-th letter says (L left, R right), sets the cell to color k + 1
(mod 4) and steps forward. Its pattern grows symmetrically.

The starter pattern (Ant-LLRR.rle) is one ant facing north on color 0.
""",
    ),
    (
        "Ant-RLR",
        "RLR",
        """
The ant RLR, of the many-color ants of Greg Turk and Jim Propp (D. Gale,
J. Propp, S. Sutherland and S. Troubetzkoy, "Further travels with my ant",
Mathematical Intelligencer 17:3 (1995) 48-56). On color k it turns as the
name's k-th letter says (L left, R right), sets the cell to color k + 1
(mod 3) and steps forward. Its pattern grows chaotically.

The starter pattern (Ant-RLR.rle) is one ant facing north on color 0.
""",
    ),
)


def main() -> None:
    for name, turns, description in ANTS:
        path = RULES / f"{name}.rule"
        path.write_text(ant_file(name, turns, description), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(RULES.parent.parent.parent.parent)}")


if __name__ == "__main__":
    main()
