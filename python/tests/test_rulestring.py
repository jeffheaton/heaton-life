import pytest

from heaton_life.ca.rulestring import LifeRule, canonical_rule, compile_rule, parse_rule


def test_parse_life() -> None:
    assert parse_rule("B3/S23") == (frozenset({3}), frozenset({2, 3}))


def test_case_and_whitespace_insensitive() -> None:
    assert parse_rule("b36 / s23") == (frozenset({3, 6}), frozenset({2, 3}))


def test_presets() -> None:
    assert parse_rule("highlife") == (frozenset({3, 6}), frozenset({2, 3}))
    assert parse_rule("Life") == parse_rule("B3/S23")


def test_empty_survival() -> None:
    birth, survive = parse_rule("B2/S")
    assert birth == frozenset({2})
    assert survive == frozenset()


def test_canonical() -> None:
    assert canonical_rule("b3/s32") == "B3/S23"
    assert canonical_rule("seeds") == "B2/S"


@pytest.mark.parametrize("bad", ["", "garbage", "B9/S23", "23/3", "B3S23", "B3/S23/C4"])
def test_invalid_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_rule(bad)


# -- the rule model (spec/rules.md) -----------------------------------------------------------

_EDGES = {"N": 128, "W": 32, "E": 8, "S": 2}


def _classes() -> dict[str, frozenset[int]]:
    """Every letter class as the neighbor arrangements it holds, from one-class rules."""
    out: dict[str, frozenset[int]] = {}
    for n in range(9):
        for letter in "cekainyqjrtwz" if 0 < n < 8 else [""]:
            try:
                table = compile_rule(f"B{n}{letter}/S").table
            except ValueError:
                continue
            out[f"{n}{letter}"] = frozenset(i for i in range(512) if table[i])
    return out


def test_letter_classes_divide_the_arrangements() -> None:
    classes = _classes()
    assert len(classes) == 51
    seen: set[int] = set()
    for name, members in classes.items():
        assert not seen & members, name
        seen |= members
        assert all(m.bit_count() == int(name[0]) and not m & 16 for m in members), name
    assert len(seen) == 256


def test_letter_classes_are_closed_under_the_squares_symmetries() -> None:
    def turn(m: int) -> int:  # a quarter turn: NW->NE->SE->SW, N->E->S->W
        cycle = [256, 64, 1, 4]
        sides = [128, 8, 2, 32]
        out = 0
        for ring in (cycle, sides):
            for k, bit in enumerate(ring):
                if m & bit:
                    out |= ring[(k + 1) % 4]
        return out

    def mirror(m: int) -> int:  # left-right: NW<->NE, W<->E, SW<->SE
        pairs = [(256, 64), (32, 8), (4, 1)]
        out = m & (128 | 2)
        for a, b in pairs:
            out |= (b if m & a else 0) | (a if m & b else 0)
        return out

    for name, members in _classes().items():
        assert {turn(m) for m in members} == members, name
        assert {mirror(m) for m in members} == members, name


def test_high_counts_are_complements_and_four_pairs_up_as_published() -> None:
    classes = _classes()

    def flipped(name: str) -> frozenset[int]:
        return frozenset(m ^ 0x1EF for m in classes[name])

    for name in classes:
        n = int(name[0])
        if n != 4:
            assert flipped(name) == classes[f"{8 - n}{name[1:]}"], name
    # LifeWiki's black/white reversal table pairs the count-4 classes like this.
    for a, b in ("ce", "it", "nr", "yj", "qw", "kk", "aa", "zz"):
        assert flipped(f"4{a}") == classes[f"4{b}"], (a, b)


def test_von_neumann_classes_match_the_published_equivalences() -> None:
    # LifeWiki "von Neumann emulation": the classes that look alike to N, W, E, S alone.
    groups = {
        "0": "0 1c 2n 2c 3c 4c",
        "1": "1e 2a 2k 3i 3n 3y 3q 4n 4y 5e",
        "2e": "2e 3k 3a 3j 4k 4a 4q 4w 5a 5j 5k 6e",
        "2i": "2i 3r 4i 4t 4z 5r 6i",
        "3": "3e 4j 4r 5i 5n 5y 5q 6a 6k 7e",
        "4": "4e 5c 6c 6n 7c 8",
    }
    classes = _classes()

    def orthogonal(m: int) -> str:
        live = [k for k, bit in _EDGES.items() if m & bit]
        if len(live) == 2:
            return "2i" if set(live) in ({"N", "S"}, {"W", "E"}) else "2e"
        return str(len(live))

    for group, names in groups.items():
        for name in names.split():
            assert {orthogonal(m) for m in classes[name]} == {group}, name
    assert sorted(" ".join(groups.values()).split()) == sorted(classes)


def test_a_von_neumann_rule_is_its_published_isotropic_twin() -> None:
    assert compile_rule("B1/SV").table == compile_rule("B1e2ak3inqy4ny5e/S").table


def test_canonical_forms() -> None:
    cases = {
        "B3/S2-i34q": "B3/S2-i34q",
        "B2-a/S12": "B2-a/S12",
        "B2ci3ai4c8/S02ae3eijkq4iz5ar6i7e": "B2ci3ai4c8/S02ae3eijkq4iz5ar6i7e",
        "b2cekin/s12": "B2-a/S12",
        "B2CEKIN/S12": "B2-a/S12",
        "B4-eijryz/S": "B4acknqtw/S",  # eight characters either way: the letters win
        "B1-c/S": "B1e/S",
        "B2a2c/S": "B2ac/S",
        "B2-a2a/S": "B2/S",
        "B2-cekain/S": "B/S",
        "B3a2c/S": "B2c3a/S",
        "b2 / s34h": "B2/S34H",
        "B1/sv": "B1/SV",
        "B33/S233": "B3/S23",
    }
    for text, canonical in cases.items():
        assert canonical_rule(text) == canonical, text
        assert canonical_rule(canonical) == canonical


def test_whitespace_is_the_specs_list() -> None:
    assert canonical_rule(chr(0xA0) + "B3/S23" + chr(0x3000)) == "B3/S23"
    assert canonical_rule("B3" + chr(0x2028) + "/" + chr(0x85) + "S23") == "B3/S23"
    for space in (0x200B, 0x1C, 0x180E):
        with pytest.raises(ValueError):
            compile_rule(chr(space) + "B3/S23")


def test_only_ascii_spells_a_rule() -> None:
    for text in ("B" + chr(0x663) + "/S23", chr(0xFF22) + "3/S23", "B2" + chr(0x212A) + "/S"):
        with pytest.raises(ValueError):
            compile_rule(text)


def test_neighborhoods_ignore_the_cells_they_lack() -> None:
    hexagonal = compile_rule("B2/S34H").table
    vonneumann = compile_rule("B2/S013V").table
    for i in range(512):
        assert hexagonal[i] == hexagonal[i ^ 64] == hexagonal[i ^ 4]  # NE, SW
        assert all(vonneumann[i] == vonneumann[i ^ c] for c in (256, 64, 4, 1))
    # Neither is isotropic in the square's sense: a hexagonal rule sees NW but not NE.
    assert hexagonal[256 | 128] != hexagonal[64 | 128]


def test_map_strings_round_trip_every_table() -> None:
    from heaton_life.core.rng import Pcg32

    rng = Pcg32(7, 0)
    for _ in range(20):
        bits = "".join(str(rng.next_u32() >> 31) for _ in range(512))
        rule = compile_rule(_map(bits))
        assert "".join(map(str, rule.table)) == bits
        assert compile_rule(rule.canonical) == rule
        assert compile_rule(rule.canonical + "==") == rule
    # Totalistic tables written as MAP strings run the same, but keep their notation.
    life = compile_rule("B3/S23")
    as_map = compile_rule(_map("".join(map(str, life.table))))
    assert as_map.table == life.table and as_map.canonical.startswith("MAP")
    for rule, length in (("B2/S34H", 22), ("B2/S013V", 6)):
        own = _own_entries(compile_rule(rule))
        twin = compile_rule(_map(own, length))
        assert twin.table == compile_rule(rule).table
        assert twin.neighborhood == compile_rule(rule).neighborhood


def _map(bits: str, length: int = 86) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    bits = bits.ljust(length * 6, "0")
    return "MAP" + "".join(alphabet[int(bits[i : i + 6], 2)] for i in range(0, length * 6, 6))


def _own_entries(rule: LifeRule) -> str:
    """A hexagonal or von Neumann rule's own table, the Moore order of the cells it has."""
    cells = (256, 128, 32, 16, 8, 2, 1) if rule.neighborhood == "hexagonal" else (128, 32, 16, 8, 2)
    out = []
    for i in range(1 << len(cells)):
        index = sum(w for k, w in enumerate(cells) if i >> (len(cells) - 1 - k) & 1)
        out.append(str(rule.table[index]))
    return "".join(out)


def test_parse_rule_answers_only_outer_totalistic_moore_rules() -> None:
    life = compile_rule("B3/S23")
    assert parse_rule(_map("".join(map(str, life.table)))) == parse_rule("B3/S23")
    assert parse_rule("B3cekainyqjr/S2cekain3") == parse_rule("B3/S23")
    for rule in ("B2-a/S12", "B2/S34H", "B/SV"):
        with pytest.raises(ValueError, match="compile_rule"):
            parse_rule(rule)


def test_presets_are_for_typed_rules_only() -> None:
    assert compile_rule("Life").canonical == "B3/S23"
    with pytest.raises(ValueError):
        compile_rule("life", presets=False)


def test_b0() -> None:
    assert compile_rule("B03/S23").has_b0
    assert compile_rule("MAPg" + "A" * 85).has_b0
    assert not compile_rule("B3/S23").has_b0
    with pytest.raises(ValueError):
        LifeRule("B3/S23", "moore", bytes(511))
