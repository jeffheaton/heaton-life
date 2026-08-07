import numpy as np

from heaton_life.core.rng import Pcg32

# First six outputs of the pcg_basic reference implementation for seed=42, seq=54
# (the values printed by the PCG demo program). These pin the spec across languages.
KNOWN_42_54 = [0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B, 0xCBED606E]


def test_known_answer_seed42_seq54() -> None:
    rng = Pcg32(42, 54)
    assert [rng.next_u32() for _ in range(6)] == KNOWN_42_54


def test_determinism() -> None:
    a = Pcg32(123, 7)
    b = Pcg32(123, 7)
    assert [a.next_u32() for _ in range(100)] == [b.next_u32() for _ in range(100)]


def test_seed_sensitivity() -> None:
    assert Pcg32(1).next_u32() != Pcg32(2).next_u32()
    assert Pcg32(1, 0).next_u32() != Pcg32(1, 1).next_u32()


def test_fill_matches_scalar_draws() -> None:
    scalar = Pcg32(9, 3)
    array = Pcg32(9, 3)
    expected = [scalar.next_u32() for _ in range(257)]
    got = array.fill_u32(257)
    assert got.dtype == np.uint32
    assert got.tolist() == expected


def test_range_is_u32() -> None:
    rng = Pcg32(0)
    for _ in range(1000):
        v = rng.next_u32()
        assert 0 <= v <= 0xFFFFFFFF
