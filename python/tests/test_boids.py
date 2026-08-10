import numpy as np
import pytest

from heaton_life.boids import Boids, BoidsParams


def make(count: int = 2, **kwargs: object) -> Boids:
    defaults: dict[str, object] = {
        "size": (128, 128),
        "w_separation": 0.0,
        "w_alignment": 0.0,
        "w_cohesion": 0.0,
    }
    return Boids(count, **{**defaults, **kwargs})  # type: ignore[arg-type]


def test_zero_steering_conserves_momentum_exactly() -> None:
    sim = Boids(50, size=(128, 128), w_separation=0.0, w_alignment=0.0, w_cohesion=0.0, seed=4)
    vel0 = sim.state[:, 2:4].copy()
    sim.step(50)
    assert np.array_equal(sim.state[:, 2:4], vel0), "no steering -> velocities untouched, bitwise"


def test_positions_advance_by_velocity_with_wrap() -> None:
    state = np.array([[127.0, 64.0, 2.0, 0.0]])
    sim = make(1, init=state)
    sim.step()
    assert sim.state[0, 0] == pytest.approx((127.0 + 2.0) % 128.0)
    assert sim.state[0, 1] == 64.0


def test_cohesion_pulls_together() -> None:
    state = np.array([[60.0, 64.0, 0.0, 1.0], [70.0, 64.0, 0.0, -1.0]])
    sim = make(2, init=state, w_cohesion=1.0, perception=20.0)
    d0 = abs(sim.state[0, 0] - sim.state[1, 0])
    sim.step(10)
    d1 = abs(sim.state[0, 0] - sim.state[1, 0])
    assert d1 < d0


def test_separation_pushes_apart() -> None:
    state = np.array([[63.0, 64.0, 0.0, 1.0], [65.0, 64.0, 0.0, -1.0]])
    sim = make(2, init=state, w_separation=1.0, perception=20.0, separation_radius=8.0)
    sim.step(10)
    d1 = abs(sim.state[0, 0] - sim.state[1, 0])
    assert d1 > 2.0


def test_alignment_reduces_heading_spread() -> None:
    sim = Boids(
        60, size=(64, 64), w_separation=0.0, w_cohesion=0.0, w_alignment=1.0,
        perception=64.0, seed=8,
    )
    def spread(s: Boids) -> float:
        v = s.state[:, 2:4]
        return float(np.var(np.arctan2(v[:, 1], v[:, 0])))
    before = spread(sim)
    sim.step(60)
    assert spread(sim) < before * 0.5


def test_wrap_keeps_positions_in_world() -> None:
    sim = Boids(100, size=(96, 64), seed=1)
    sim.step(100)
    assert (sim.state[:, 0] >= 0).all() and (sim.state[:, 0] < 96).all()
    assert (sim.state[:, 1] >= 0).all() and (sim.state[:, 1] < 64).all()


def test_bounce_reflects_at_wall() -> None:
    state = np.array([[126.5, 64.0, 3.0, 0.0]])  # heading out the right wall
    sim = make(1, init=state, boundary="bounce")
    sim.step()
    assert sim.state[0, 0] <= 128.0
    assert sim.state[0, 2] < 0.0, "x-velocity must flip on bounce"


def test_speed_clamps_hold_under_steering() -> None:
    sim = Boids(80, size=(128, 128), seed=6)  # default weights on
    sim.step(30)
    speed = np.sqrt((sim.state[:, 2:4] ** 2).sum(axis=1))
    p = sim.params
    assert (speed <= p.max_speed + 1e-9).all()
    assert (speed >= p.min_speed - 1e-9).all()


def test_determinism_and_roundtrip() -> None:
    a = Boids(40, size=(64, 64), seed=9)
    b = Boids.from_params(BoidsParams.from_json(a.params.to_json()))
    a.step(20)
    b.step(20)
    assert np.array_equal(a.state, b.state)


def test_frame_rasterizes_dots() -> None:
    sim = Boids(30, size=(64, 64), seed=2)
    frame = sim.frame()
    assert frame.shape == (64, 64)
    assert frame.min() >= 0.0 and frame.max() <= 1.0
    assert (frame > 0).sum() >= 30, "each boid leaves at least its own dot"
    assert sim.state.shape == (30, 4)  # state != frame, concretely


def test_overlay_payload() -> None:
    sim = Boids(10, size=(64, 32), seed=3)
    payload = sim.overlay()
    assert np.asarray(payload["points"]).shape == (10, 4)
    assert payload["world"] == (64, 32)


def test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        Boids(5, boundary="portal")
    with pytest.raises(ValueError):
        Boids(5, init=np.zeros((4, 4)))
    sim = make(1, init=np.array([[1.0, 1.0, 1.0, 0.0]]))
    with pytest.raises(ValueError):
        Boids.from_params(sim.params)
    with pytest.raises(ValueError):
        Boids(5, dimensions=4)  # the math wouldn't care, the UI does
    with pytest.raises(ValueError):
        Boids(5, dimensions=3, init=np.zeros((5, 4)))  # 3D wants (5, 6)


# -- d = 3 (same algorithm, one more component) --------------------------------------


def test_3d_seeding_launches_at_exact_speed() -> None:
    sim = Boids(64, dimensions=3, size=(64, 64), depth=48, seed=5)
    assert sim.state.shape == (64, 6)
    launch = (sim.params.min_speed + sim.params.max_speed) / 2.0
    speed = np.sqrt((sim.state[:, 3:6] ** 2).sum(axis=1))
    assert speed == pytest.approx(launch, abs=1e-12), "sphere direction is unit-norm"
    assert (sim.state[:, 2] >= 0).all() and (sim.state[:, 2] < 48).all()


def test_3d_zero_steering_conserves_momentum_exactly() -> None:
    sim = Boids(
        50, dimensions=3, size=(96, 96), depth=96,
        w_separation=0.0, w_alignment=0.0, w_cohesion=0.0, seed=4,
    )
    vel0 = sim.state[:, 3:6].copy()
    sim.step(50)
    assert np.array_equal(sim.state[:, 3:6], vel0)


def test_3d_wrap_keeps_positions_in_world() -> None:
    sim = Boids(80, dimensions=3, size=(96, 64), depth=48, seed=1)
    sim.step(60)
    assert (sim.state[:, 0] >= 0).all() and (sim.state[:, 0] < 96).all()
    assert (sim.state[:, 1] >= 0).all() and (sim.state[:, 1] < 64).all()
    assert (sim.state[:, 2] >= 0).all() and (sim.state[:, 2] < 48).all()


def test_3d_bounce_reflects_z() -> None:
    state = np.array([[64.0, 64.0, 126.5, 0.0, 0.0, 3.0]])  # heading out the far wall
    sim = Boids(
        1, dimensions=3, size=(128, 128), depth=128, boundary="bounce",
        w_separation=0.0, w_alignment=0.0, w_cohesion=0.0, init=state,
    )
    sim.step()
    assert sim.state[0, 2] <= 128.0
    assert sim.state[0, 5] < 0.0, "z-velocity must flip on bounce"


def test_3d_cohesion_pulls_together_in_z() -> None:
    state = np.array([
        [64.0, 64.0, 40.0, 1.0, 0.0, 0.0],
        [64.0, 64.0, 60.0, -1.0, 0.0, 0.0],
    ])
    sim = Boids(
        2, dimensions=3, size=(128, 128), depth=128, w_cohesion=1.0,
        w_separation=0.0, w_alignment=0.0, perception=30.0, init=state,
    )
    d0 = abs(sim.state[0, 2] - sim.state[1, 2])
    sim.step(10)
    assert abs(sim.state[0, 2] - sim.state[1, 2]) < d0


def test_3d_speed_clamps_hold_under_steering() -> None:
    sim = Boids(80, dimensions=3, size=(96, 96), depth=96, seed=6)
    sim.step(30)
    speed = np.sqrt((sim.state[:, 3:6] ** 2).sum(axis=1))
    p = sim.params
    assert (speed <= p.max_speed + 1e-9).all()
    assert (speed >= p.min_speed - 1e-9).all()


def test_3d_frame_is_depth_cued() -> None:
    # Two lone boids at the same x/y offset pattern, one near, one far: the
    # near dot must be brighter (b = 0.3 + 0.7*(1 - z/depth)).
    state = np.array([
        [16.0, 16.0, 4.0, 1.0, 0.0, 0.0],
        [48.0, 48.0, 60.0, 1.0, 0.0, 0.0],
    ])
    sim = Boids(
        2, dimensions=3, size=(64, 64), depth=64,
        w_separation=0.0, w_alignment=0.0, w_cohesion=0.0, init=state,
    )
    frame = sim.frame()
    assert frame.shape == (64, 64)
    near, far = frame[16, 16], frame[48, 48]
    assert near > far > 0.0
    assert near == pytest.approx(0.3 + 0.7 * (1.0 - 4.0 / 64.0))


def test_3d_determinism_and_roundtrip() -> None:
    a = Boids(40, dimensions=3, size=(64, 64), depth=64, seed=9)
    b = Boids.from_params(BoidsParams.from_json(a.params.to_json()))
    a.step(20)
    b.step(20)
    assert np.array_equal(a.state, b.state)
