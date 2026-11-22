"""Life-like rules (spec/rules.md): rule text compiled to one 512-entry transition table.

A two-state rule whose next state depends only on a cell and its eight neighbors is a table
indexed by the 3×3 block: NW 256, N 128, NE 64, W 32, the cell 16, E 8, SW 4, S 2, SE 1.
This module compiles every notation the spec defines to that table: ``B…/S…`` with digits
(outer-totalistic) or letter classes (isotropic non-totalistic), with an ``H``
(hexagonal) or ``V`` (von Neumann) suffix, and ``MAP`` strings. The parser is written by
hand to the spec's grammar, step for step like the C# port's.
"""

from __future__ import annotations

import dataclasses
import functools
import operator
from typing import Literal, TypeAlias

RULE_PRESETS = {
    "life": "B3/S23",
    "highlife": "B36/S23",
    "seeds": "B2/S",
    "daynight": "B3678/S34678",
    "replicator": "B1357/S1357",
    "maze": "B3/S12345",
    "diamoeba": "B35678/S5678",
}

Neighborhood = Literal["moore", "hexagonal", "vonneumann"]
NEIGHBORHOODS: tuple[Neighborhood, ...] = ("moore", "hexagonal", "vonneumann")
TABLE_SIZE = 512
"""Entries in every rule's table: one per filling of the 3×3 block."""

_CENTER = 16  # the cell's own bit in the neighborhood index
_NEIGHBORS = 0x1EF  # every bit but the cell's own
_WEIGHT = {"NW": 256, "N": 128, "NE": 64, "W": 32, "E": 8, "SW": 4, "S": 2, "SE": 1}
# The neighbors each neighborhood counts, and the most it can count (spec/rules.md
# "Neighborhoods"): hexagonal drops NE and SW, von Neumann keeps N, W, E, S.
_COUNTED: dict[Neighborhood, int] = {"moore": 0x1EF, "hexagonal": 0x1AB, "vonneumann": 0xAA}
_MAX_COUNT: dict[Neighborhood, int] = {"moore": 8, "hexagonal": 6, "vonneumann": 4}
_SUFFIX: dict[Neighborhood, str] = {"moore": "", "hexagonal": "H", "vonneumann": "V"}
_NAME: dict[Neighborhood, str] = {
    "moore": "Moore",
    "hexagonal": "hexagonal",
    "vonneumann": "von Neumann",
}

# One arrangement of each letter class of counts 1-4, as its live neighbors
# (spec/rules.md "Letter classes"). Counts 5-7 are the complements of 3-1, and counts 0
# and 8 have a single class, written here with the letter "".
_REPRESENTATIVES: dict[int, dict[str, str]] = {
    1: {"c": "NW", "e": "N"},
    2: {"c": "NW NE", "e": "N W", "k": "N SE", "a": "NW N", "i": "N S", "n": "NW SE"},
    3: {
        "c": "NW NE SE",
        "e": "N W E",
        "k": "N W SE",
        "a": "NW N W",
        "i": "NW W SW",
        "n": "NW NE W",
        "y": "NW NE S",
        "q": "NW W SE",
        "j": "NE E S",
        "r": "N NE S",
    },
    4: {
        "c": "NW NE SW SE",
        "e": "N W E S",
        "k": "N NE W SE",
        "a": "NW W SW S",
        "i": "NW NE W E",
        "n": "NW W SW SE",
        "y": "NW NE SW S",
        "q": "NW N W SE",
        "j": "N W E SE",
        "r": "N NE E S",
        "t": "NW N NE S",
        "w": "NW W S SE",
        "z": "NW N S SE",
    },
}
_LETTERS = frozenset("cekainyqjrtwz")
# The letters each count takes, alphabetical (the canonical spelling's order).
_LETTERS_OF: dict[int, str] = {
    n: "".join(sorted(_REPRESENTATIVES[min(n, 8 - n)])) if 0 < n < 8 else "" for n in range(9)
}

# spec/rules.md "Grammar": the whitespace allowed at the ends and around the slash.
_SPACE = frozenset(
    chr(c)
    for c in (
        *range(0x09, 0x0E),
        0x20,
        0x85,
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
    )
)
_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_BASE64_VALUE = {ch: i for i, ch in enumerate(_BASE64)}
# A MAP payload's length names its neighborhood; each holds 2^cells entries.
_MAP_LENGTH: dict[int, Neighborhood] = {86: "moore", 22: "hexagonal", 6: "vonneumann"}
_MAP_CELLS: dict[Neighborhood, int] = {"moore": 9, "hexagonal": 7, "vonneumann": 5}
_MAP_PAYLOAD: dict[Neighborhood, int] = {nb: length for length, nb in _MAP_LENGTH.items()}

Group: TypeAlias = tuple[int, bool, str]  # (count, minus, letters) as written
Key: TypeAlias = tuple[int, str]  # (count, letter class); counts 0 and 8, and H and V, use ""


@dataclasses.dataclass(frozen=True)
class LifeRule:
    """A Life-like rule compiled to its transition table (spec/rules.md).

    ``table[i]`` is the next state, 0 or 1, of a cell whose 3×3 block has neighborhood
    index ``i``: NW 256, N 128, NE 64, W 32, the cell 16, E 8, SW 4, S 2, SE 1. Two rules
    behave identically exactly when their tables are equal, whatever their notations.
    """

    canonical: str
    neighborhood: Neighborhood
    table: bytes

    def __post_init__(self) -> None:
        if len(self.table) != TABLE_SIZE or any(v > 1 for v in self.table):
            raise ValueError(f"a rule table holds {TABLE_SIZE} entries of 0 or 1")

    @property
    def has_b0(self) -> bool:
        """True when a dead cell with no live neighbors is born (``table[0] == 1``)."""
        return self.table[0] == 1

    @property
    def has_smax(self) -> bool:
        """True when a live cell whose neighbors are all alive survives (``table[511] ==
        1``): S8 in a Moore rule, S6 in a hexagonal one, S4 in a von Neumann one."""
        return self.table[TABLE_SIZE - 1] == 1

    def background(self, generation: int) -> int:
        """The unbounded universe's background at ``generation`` ≥ 0 (spec/rules.md "B0 and
        the background"): 0 for a rule without B0, 1 for B0 with Smax, and the generation's
        parity for B0 without Smax. The universe holds the cells that differ from it."""
        generation = operator.index(generation)
        if generation < 0:
            raise ValueError(f"a generation is never negative, got {generation}")
        if not self.has_b0:
            return 0
        return 1 if self.has_smax else generation & 1


def compile_rule(rule: str, *, presets: bool = True) -> LifeRule:
    """Compile rule text (spec/rules.md "Grammar") to its table and canonical string.

    With ``presets`` a RULE_PRESETS name (``life``, ``highlife``…) stands for its rule, a
    convenience where people type rules; file formats pass ``presets=False``. Raises
    ValueError for text outside the grammar.
    """
    if presets:
        named = RULE_PRESETS.get(rule.strip().lower())
        if named is not None:
            rule = named
    return _compile(rule)


def try_compile_rule(
    rule: str, *, presets: bool = True
) -> tuple[LifeRule, None] | tuple[None, str]:
    """``compile_rule`` without raising: ``(rule, None)`` when the text compiles, else
    ``(None, reason)``, the phrase spec/rules.md "Reasons" gives for the first problem a
    reading of the text finds (``compile_rule``'s error message carries the same one)."""
    try:
        return compile_rule(rule, presets=presets), None
    except _RuleError as error:
        return None, error.reason


def canonical_rule(rule: str) -> str:
    """The canonical form of a rule or preset name, e.g. 'b3 / s32' -> 'B3/S23'."""
    return compile_rule(rule).canonical


def parse_rule(rule: str) -> tuple[frozenset[int], frozenset[int]]:
    """An outer-totalistic Moore rule or preset name as (birth, survive) neighbor counts.

    Only a rule whose table depends on nothing but the cell and its count of live
    neighbors has counts: isotropic letters that split a count, MAP strings that aren't
    outer-totalistic, and hexagonal or von Neumann rules raise ValueError. compile_rule
    gives every rule's table.
    """
    compiled = compile_rule(rule)
    counts = _outer_totalistic(compiled)
    if counts is None:
        raise ValueError(
            f"{compiled.canonical} is not an outer-totalistic Moore rule, so it has no "
            "birth and survival counts; compile_rule gives its table (spec/rules.md)"
        )
    return counts


def _outer_totalistic(rule: LifeRule) -> tuple[frozenset[int], frozenset[int]] | None:
    if rule.neighborhood != "moore":
        return None
    sides: tuple[dict[int, int], dict[int, int]] = ({}, {})
    for index, value in enumerate(rule.table):
        side = sides[1 if index & _CENTER else 0]
        if side.setdefault((index & _NEIGHBORS).bit_count(), value) != value:
            return None
    birth, survive = (frozenset(n for n, v in side.items() if v) for side in sides)
    return birth, survive


class _RuleError(ValueError):
    """Text that is not a rule, with the reason spec/rules.md "Reasons" gives for it."""

    def __init__(self, text: str, reason: str) -> None:
        super().__init__(f"invalid rule '{text}': {reason} (spec/rules.md)")
        self.reason = reason


def _invalid(text: str, reason: str) -> _RuleError:
    return _RuleError(text, reason)


@functools.lru_cache(maxsize=64)
def _compile(text: str) -> LifeRule:
    start, end = 0, len(text)
    while start < end and text[start] in _SPACE:
        start += 1
    while end > start and text[end - 1] in _SPACE:
        end -= 1
    body = text[start:end]
    if len(body) >= 3 and body[0] in "Mm" and body[1] in "Aa" and body[2] in "Pp":
        return _compile_map(text, body[3:])
    if body[:1] in ("B", "b"):
        return _compile_bs(text, body)
    raise _invalid(text, "expected B…/S… or MAP…")


def _compile_bs(text: str, body: str) -> LifeRule:
    birth, pos = _groups(text, body, 1)
    pos = _skip_space(body, pos)
    if pos >= len(body) or body[pos] != "/":
        raise _invalid(text, "expected '/' after the birth counts")
    pos = _skip_space(body, pos + 1)
    if pos >= len(body) or body[pos] not in "Ss":
        raise _invalid(text, "expected S after '/'")
    survive, pos = _groups(text, body, pos + 1)
    # What follows the survival counts names the neighborhood. A variant with more states
    # will add a suffix word here; until one is specified (spec/rules.md "Grammar"),
    # nothing else may follow.
    rest = body[pos:]
    neighborhood: Neighborhood
    if rest == "":
        neighborhood = "moore"
    elif rest in ("H", "h"):
        neighborhood = "hexagonal"
    elif rest in ("V", "v"):
        neighborhood = "vonneumann"
    else:
        raise _invalid(text, f"unexpected '{rest}' after the survival counts")
    born = _side(text, birth, neighborhood)
    stays = _side(text, survive, neighborhood)
    canonical = f"B{_spell(born, neighborhood)}/S{_spell(stays, neighborhood)}"
    return LifeRule(
        canonical + _SUFFIX[neighborhood],
        neighborhood,
        _bs_table(born, stays, neighborhood),
    )


def _skip_space(body: str, pos: int) -> int:
    while pos < len(body) and body[pos] in _SPACE:
        pos += 1
    return pos


def _letter(ch: str) -> str | None:
    """The letter class ``ch`` names, in either case, or None. ASCII only."""
    lower = ch.lower() if "A" <= ch <= "Z" else ch
    return lower if lower in _LETTERS else None


def _groups(text: str, body: str, pos: int) -> tuple[list[Group], int]:
    """One side's digit groups as written, and the position after them."""
    groups: list[Group] = []
    while pos < len(body) and "0" <= body[pos] <= "8":
        count = ord(body[pos]) - ord("0")
        pos += 1
        minus = pos < len(body) and body[pos] == "-"
        if minus:
            pos += 1
        letters = ""
        while pos < len(body) and (letter := _letter(body[pos])) is not None:
            letters += letter
            pos += 1
        if minus and not letters:
            raise _invalid(text, f"'-' after {count} must be followed by letters")
        groups.append((count, minus, letters))
    return groups, pos


def _side(text: str, groups: list[Group], neighborhood: Neighborhood) -> frozenset[Key]:
    """The letter classes one side names (spec/rules.md "Birth and survival")."""
    keys: set[Key] = set()
    for count, minus, letters in groups:
        if count > _MAX_COUNT[neighborhood]:
            raise _invalid(
                text,
                f"the {_NAME[neighborhood]} neighborhood has {_MAX_COUNT[neighborhood]} neighbors",
            )
        if neighborhood != "moore":
            if letters:
                raise _invalid(
                    text, f"letters are only defined for Moore rules, not {_NAME[neighborhood]}"
                )
            keys.add((count, ""))
            continue
        defined = _LETTERS_OF[count]
        if not letters:
            keys.update((count, letter) for letter in defined or [""])
            continue
        if not defined:
            raise _invalid(text, f"{count} takes no letters")
        unknown = next((letter for letter in letters if letter not in defined), None)
        if unknown is not None:
            raise _invalid(text, f"{unknown} is not a letter class of {count}")
        chosen = set(defined) - set(letters) if minus else set(letters)
        keys.update((count, letter) for letter in chosen)
    return frozenset(keys)


def _spell(keys: frozenset[Key], neighborhood: Neighborhood) -> str:
    """One side in canonical form (spec/rules.md "Canonical form")."""
    out = []
    for count in range(9):
        if not any(n == count for n, _ in keys):
            continue
        letters = "".join(sorted(letter for n, letter in keys if n == count))
        defined = _LETTERS_OF[count]
        if neighborhood != "moore" or letters in ("", defined):
            out.append(str(count))
            continue
        plus = f"{count}{letters}"
        minus = f"{count}-{''.join(sorted(set(defined) - set(letters)))}"
        out.append(minus if len(minus) < len(plus) else plus)
    return "".join(out)


def _bs_table(born: frozenset[Key], stays: frozenset[Key], neighborhood: Neighborhood) -> bytes:
    if neighborhood == "moore":
        birth = frozenset[int]().union(*(_CLASSES[key] for key in born))
        survive = frozenset[int]().union(*(_CLASSES[key] for key in stays))
        return bytes(
            int((index & _NEIGHBORS) in (survive if index & _CENTER else birth))
            for index in range(TABLE_SIZE)
        )
    counted = _COUNTED[neighborhood]
    birth_counts = {n for n, _ in born}
    survive_counts = {n for n, _ in stays}
    return bytes(
        int((index & counted).bit_count() in (survive_counts if index & _CENTER else birth_counts))
        for index in range(TABLE_SIZE)
    )


def _symmetric(mask: int) -> frozenset[int]:
    """An arrangement under the eight symmetries of the square (quarter turns, mirrored or
    not); cells are compass offsets (dx, dy) with y down."""
    offsets = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)]
    cells = [(dx, dy) for dx, dy in offsets if mask & _bit(dx, dy)]
    images = set()
    for _ in range(4):
        cells = [(-dy, dx) for dx, dy in cells]  # a quarter turn clockwise
        images.add(sum(_bit(dx, dy) for dx, dy in cells))
        images.add(sum(_bit(-dx, dy) for dx, dy in cells))  # and its mirror image
    return frozenset(images)


def _bit(dx: int, dy: int) -> int:
    """The neighborhood-index weight of the cell at offset (dx, dy): NW 256 … SE 1."""
    return 1 << (4 - 3 * dy - dx)


def _letter_classes() -> dict[Key, frozenset[int]]:
    """Every Moore letter class as the arrangements it holds (index bits of live
    neighbors, the cell's own bit clear)."""
    classes: dict[Key, frozenset[int]] = {(0, ""): frozenset({0}), (8, ""): frozenset({_NEIGHBORS})}
    for count, representatives in _REPRESENTATIVES.items():
        for letter, cells in representatives.items():
            members = _symmetric(sum(_WEIGHT[cell] for cell in cells.split()))
            classes[(count, letter)] = members
            if count < 4:
                classes[(8 - count, letter)] = frozenset(m ^ _NEIGHBORS for m in members)
    return classes


_CLASSES = _letter_classes()


def _compile_map(text: str, payload: str) -> LifeRule:
    payload = payload.removesuffix("==")
    neighborhood = _MAP_LENGTH.get(len(payload))
    if neighborhood is None or any(ch not in _BASE64_VALUE for ch in payload):
        raise _invalid(
            text, "a MAP payload is 86, 22 or 6 base64 characters, optionally followed by =="
        )
    entries = [
        (_BASE64_VALUE[payload[i // 6]] >> (5 - i % 6)) & 1
        for i in range(1 << _MAP_CELLS[neighborhood])
    ]
    table = bytes(entries[_project(index, neighborhood)] for index in range(TABLE_SIZE))
    return LifeRule("MAP" + _base64(entries, neighborhood), neighborhood, table)


def _project(index: int, neighborhood: Neighborhood) -> int:
    """A Moore neighborhood index as the index of a MAP string's own neighborhood: the
    cells it has, in Moore order (spec/rules.md "MAP strings")."""
    if neighborhood == "moore":
        return index
    if neighborhood == "hexagonal":  # NW N W C E S SE
        return (index >> 2) & 0x60 | (index >> 1) & 0x1C | index & 0x3
    return (index >> 3) & 0x10 | (index >> 2) & 0xE | (index >> 1) & 0x1  # N W C E S


def _base64(entries: list[int], neighborhood: Neighborhood) -> str:
    """Entries as a canonical MAP payload: six bits a character, unused bits zero."""
    chars = []
    for start in range(0, _MAP_PAYLOAD[neighborhood] * 6, 6):
        value = 0
        for i in range(start, start + 6):
            value = value << 1 | (entries[i] if i < len(entries) else 0)
        chars.append(_BASE64[value])
    return "".join(chars)
