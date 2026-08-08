import numpy as np
import pytest

from heaton_life.lenia import (
    AsymptoticLenia,
    ClassicLenia,
    FlowLenia,
    FlowLeniaParams,
    LeniaParams,
    ring_kernel,
)


def test_ring_kernel_normalized_and_centered() -> None:
    kernel = ring_kernel((64, 64), 13)
    assert kernel.shape == (64, 64)
    assert kernel[0, 0] == 0.0  # r = 0 excluded
    assert kernel.min() >= 0.0
    assert np.isclose(kernel.sum(), 1.0, atol=1e-12)
    # wrapped symmetry: K(x) == K(-x) on the torus
    assert np.allclose(kernel, np.roll(kernel[::-1, ::-1], (1, 1), axis=(0, 1)), atol=1e-15)


def test_ring_kernel_rejects_oversized_radius() -> None:
    with pytest.raises(ValueError):
        ring_kernel((16, 16), 8)


def test_empty_world_stays_essentially_empty() -> None:
    zero = np.zeros((32, 32), dtype=np.float64)
    for cls in (ClassicLenia, AsymptoticLenia):
        sim = cls(size=(32, 32), radius=8, init=zero)
        sim.step(10)
        assert sim.state.max() < 1e-12, cls.__name__
    flow = FlowLenia(size=(32, 32), radius=8, init=zero)
    flow.step(10)
    assert flow.state.max() == 0.0


def test_classic_bounded_and_alive_with_defaults() -> None:
    sim = ClassicLenia(size=(128, 128), seed=0)
    sim.step(300)
    assert sim.state.min() >= 0.0 and sim.state.max() <= 1.0
    assert sim.state.mean() > 0.01, "default params should sustain life"
    assert sim.state.std() > 0.05, "structure, not uniformity"


def test_asymptotic_bounded_without_clipping() -> None:
    sim = AsymptoticLenia(size=(96, 96), seed=1)
    sim.step(200)
    assert sim.state.min() >= 0.0 and sim.state.max() <= 1.0
    assert sim.state.std() > 0.05


def test_flow_conserves_mass_and_clumps() -> None:
    sim = FlowLenia(size=(128, 128), seed=0)
    mass0 = sim.state.sum()
    std0 = sim.state.std()
    sim.step(100)
    assert abs(sim.state.sum() - mass0) / mass0 < 1e-9, "flow must conserve mass"
    assert sim.state.std() > std0 * 1.5, "soup should aggregate into clumps"


def test_determinism() -> None:
    a = ClassicLenia(size=(64, 64), seed=9)
    b = ClassicLenia(size=(64, 64), seed=9)
    a.step(20)
    b.step(20)
    assert np.array_equal(a.state, b.state)


def test_params_roundtrip_all_variants() -> None:
    classic = ClassicLenia(size=(64, 48), seed=3)
    clone = ClassicLenia.from_params(LeniaParams.from_json(classic.params.to_json()))
    assert np.array_equal(clone.state, classic.state)

    flow = FlowLenia(size=(64, 48), seed=3)
    fclone = FlowLenia.from_params(FlowLeniaParams.from_json(flow.params.to_json()))
    assert np.array_equal(fclone.state, flow.state)
    assert fclone.params.theta == flow.params.theta


def test_array_init_rejected_in_from_params() -> None:
    sim = ClassicLenia(size=(32, 32), radius=8, init=np.zeros((32, 32)))
    with pytest.raises(ValueError):
        ClassicLenia.from_params(sim.params)


def test_frame_is_state_in_unit_range() -> None:
    sim = AsymptoticLenia(size=(64, 64), seed=2)
    sim.step(50)
    frame = sim.frame()
    assert frame is sim.state
    assert frame.min() >= 0.0 and frame.max() <= 1.0
