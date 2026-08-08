import numpy as np
import pytest

from heaton_life.rd import GRAY_SCOTT_PRESETS, GrayScott, GrayScottParams


def test_homogeneous_steady_state_is_exact_fixed_point() -> None:
    state = np.stack(
        [np.ones((16, 16), dtype=np.float64), np.zeros((16, 16), dtype=np.float64)]
    )
    sim = GrayScott(size=(16, 16), init=state)
    sim.step(10)
    assert np.array_equal(sim.state, state)  # bitwise: no reaction, no diffusion


def test_center_init_keeps_symmetry() -> None:
    sim = GrayScott(size=(65, 65), init="center", feed=0.0367, kill=0.0649)
    sim.step(50)
    v = sim.state[1]
    assert np.allclose(v, v[::-1, :], atol=1e-12)
    assert np.allclose(v, v[:, ::-1], atol=1e-12)
    assert np.allclose(v, v.T, atol=1e-12)


def test_mitosis_forms_pattern_and_stays_bounded() -> None:
    sim = GrayScott(size=(64, 64), feed=0.0367, kill=0.0649, init="spots", seed=3)
    sim.step(800)
    u, v = sim.state
    assert np.isfinite(sim.state).all()
    assert 0.0 <= u.min() and u.max() <= 1.05
    assert 0.0 <= v.min() and v.max() <= 1.0
    assert v.std() > 0.01, "mitosis should form spatial structure"


def test_determinism_and_reset() -> None:
    a = GrayScott(size=(48, 48), seed=5)
    b = GrayScott(size=(48, 48), seed=5)
    a.step(100)
    b.step(100)
    assert np.array_equal(a.state, b.state)
    a.reset()
    assert a.generation == 0
    assert np.array_equal(a.state, GrayScott(size=(48, 48), seed=5).state)


def test_params_roundtrip_and_array_rejection() -> None:
    sim = GrayScott(size=(32, 24), feed=0.03, kill=0.062, seed=2)
    clone = GrayScott.from_params(GrayScottParams.from_json(sim.params.to_json()))
    assert np.array_equal(clone.state, sim.state)
    boxed = GrayScott(size=(8, 8), init=np.zeros((2, 8, 8)))
    with pytest.raises(ValueError):
        GrayScott.from_params(boxed.params)


def test_presets_all_in_range() -> None:
    for name, fk in GRAY_SCOTT_PRESETS.items():
        assert 0.0 < fk["feed"] < 0.12, name
        assert 0.0 < fk["kill"] < 0.08, name


def test_frame_shape_and_range() -> None:
    sim = GrayScott(size=(32, 32), seed=1)
    frame = sim.frame()
    assert frame.shape == (32, 32)
    assert frame.min() >= 0.0 and frame.max() <= 1.0
