"""Reynolds boids — spec/boids.md.

State is a point cloud, not a grid: (N, 4) float64 rows of [x, y, vx, vy] in world
units (the world is width x height, matching the rasterized frame). Neighbors are
O(N^2) with minimum-image wrapped distances; count is capped where that stops
being reasonable (a spatial hash arrives if flocks ever need >2k).

The frame() rasterization is the proof of the state != frame split: the same
simulation feeds the shared colormap/GIF pipeline as soft dots, while the
playground draws oriented triangles from the raw state.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.params import Params
from heaton_life.core.rng import Pcg32

FloatArray = NDArray[np.float64]

# Rasterization kernel: center bright, cross and diagonals dimmer.
_DOT = [(0, 0, 1.0), (-1, 0, 0.55), (1, 0, 0.55), (0, -1, 0.55), (0, 1, 0.55),
        (-1, -1, 0.3), (-1, 1, 0.3), (1, -1, 0.3), (1, 1, 0.3)]


@dataclasses.dataclass(frozen=True)
class BoidsParams(Params):
    count: int = dataclasses.field(default=300, metadata={"min": 2, "max": 2000})
    width: int = dataclasses.field(default=256, metadata={"min": 64, "max": 1024})
    height: int = dataclasses.field(default=256, metadata={"min": 64, "max": 1024})
    perception: float = dataclasses.field(
        default=12.0, metadata={"min": 2.0, "max": 64.0, "step": 1.0}
    )
    separation_radius: float = dataclasses.field(
        default=6.0, metadata={"min": 1.0, "max": 32.0, "step": 0.5}
    )
    w_separation: float = dataclasses.field(
        default=1.5, metadata={"min": 0.0, "max": 5.0, "step": 0.1}
    )
    w_alignment: float = dataclasses.field(
        default=1.0, metadata={"min": 0.0, "max": 5.0, "step": 0.1}
    )
    w_cohesion: float = dataclasses.field(
        default=1.0, metadata={"min": 0.0, "max": 5.0, "step": 0.1}
    )
    max_speed: float = dataclasses.field(
        default=3.0, metadata={"min": 0.5, "max": 10.0, "step": 0.25}
    )
    min_speed: float = dataclasses.field(
        default=1.0, metadata={"min": 0.0, "max": 5.0, "step": 0.25}
    )
    max_force: float = dataclasses.field(
        default=0.08, metadata={"min": 0.005, "max": 1.0, "step": 0.01, "decimals": 3}
    )
    boundary: str = dataclasses.field(default="wrap", metadata={"choices": ["wrap", "bounce"]})
    init: str = dataclasses.field(default="random", metadata={"choices": ["random"]})
    seed: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"}
    )


class Boids:
    """A Reynolds flock. State is float64 (count, 4): [x, y, vx, vy] per boid."""

    def __init__(
        self,
        count: int = 300,
        *,
        size: tuple[int, int] = (256, 256),
        perception: float = 12.0,
        separation_radius: float = 6.0,
        w_separation: float = 1.5,
        w_alignment: float = 1.0,
        w_cohesion: float = 1.0,
        max_speed: float = 3.0,
        min_speed: float = 1.0,
        max_force: float = 0.08,
        boundary: str = "wrap",
        init: str | FloatArray = "random",
        seed: int = 0,
    ) -> None:
        if boundary not in ("wrap", "bounce"):
            raise ValueError(f"unknown boundary: {boundary!r}")
        width, height = size
        self._initial: FloatArray | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (count, 4):
                raise ValueError(f"init array shape {init.shape} does not match ({count}, 4)")
            self._initial = init.astype(np.float64)
            init_name = "array"
        else:
            init_name = init
        self.params = BoidsParams(
            count=count,
            width=width,
            height=height,
            perception=perception,
            separation_radius=separation_radius,
            w_separation=w_separation,
            w_alignment=w_alignment,
            w_cohesion=w_cohesion,
            max_speed=max_speed,
            min_speed=min_speed,
            max_force=max_force,
            boundary=boundary,
            init=init_name,
            seed=seed,
        )
        self._generation = 0
        self._state: FloatArray
        self.reset()

    @classmethod
    def from_params(cls, params: BoidsParams) -> Boids:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: Boids(init=...)")
        return cls(
            params.count,
            size=(params.width, params.height),
            perception=params.perception,
            separation_radius=params.separation_radius,
            w_separation=params.w_separation,
            w_alignment=params.w_alignment,
            w_cohesion=params.w_cohesion,
            max_speed=params.max_speed,
            min_speed=params.min_speed,
            max_force=params.max_force,
            boundary=params.boundary,
            init=params.init,
            seed=params.seed,
        )

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
        elif p.init == "random":
            # 3 draws per boid: x, y, heading; launch speed = (min+max)/2.
            rng = Pcg32(p.seed)
            state = np.empty((p.count, 4), dtype=np.float64)
            launch = (p.min_speed + p.max_speed) / 2.0
            for i in range(p.count):
                state[i, 0] = rng.next_u32() / 4294967296.0 * p.width
                state[i, 1] = rng.next_u32() / 4294967296.0 * p.height
                angle = rng.next_u32() / 4294967296.0 * 2.0 * np.pi
                state[i, 2] = np.cos(angle) * launch
                state[i, 3] = np.sin(angle) * launch
            self._state = state
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._generation = 0

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._state = _step_once(self._state, self.params)
        self._generation += n

    @property
    def state(self) -> FloatArray:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def frame(self) -> FloatArray:
        """Rasterize to (height, width) soft dots for the shared render pipeline."""
        p = self.params
        img = np.zeros((p.height, p.width), dtype=np.float64)
        px = self._state[:, 0].astype(np.int64) % p.width
        py = self._state[:, 1].astype(np.int64) % p.height
        for dy, dx, weight in _DOT:
            np.add.at(img, ((py + dy) % p.height, (px + dx) % p.width), weight)
        result: FloatArray = np.clip(img, 0.0, 1.0)
        return result

    def overlay(self) -> dict[str, object]:
        """Raw point cloud for vector rendering (playground triangles)."""
        return {"points": self._state.copy(), "world": (self.params.width, self.params.height)}


def _steer(direction: FloatArray, vel: FloatArray, max_speed: float, max_force: float) -> FloatArray:
    """Reynolds steering: desired = normalize(direction)*max_speed; clip force."""
    norm = np.sqrt((direction**2).sum(axis=1, keepdims=True))
    has = norm > 0.0
    desired = np.where(has, direction / np.where(has, norm, 1.0) * max_speed, 0.0)
    steer = desired - vel
    force = np.sqrt((steer**2).sum(axis=1, keepdims=True))
    over = force > max_force
    steer = np.where(over, steer / np.where(over, force, 1.0) * max_force, steer)
    return np.where(has, steer, 0.0)


def _step_once(state: FloatArray, p: BoidsParams) -> FloatArray:
    pos = state[:, 0:2]
    vel = state[:, 2:4]
    size = np.array([p.width, p.height], dtype=np.float64)

    delta = pos[None, :, :] - pos[:, None, :]  # delta[i, j] = pos_j - pos_i
    if p.boundary == "wrap":
        delta -= size * np.round(delta / size)  # minimum image on the torus
    d2 = (delta**2).sum(axis=2)
    neighbor = (d2 > 0.0) & (d2 <= p.perception * p.perception)
    n_count = neighbor.sum(axis=1)
    denom = np.maximum(n_count, 1)[:, None]

    mean_offset = (delta * neighbor[:, :, None]).sum(axis=1) / denom
    mean_vel = (vel[None, :, :] * neighbor[:, :, None]).sum(axis=1) / denom

    close = (d2 > 0.0) & (d2 <= p.separation_radius * p.separation_radius)
    push = -delta / np.maximum(d2, 1e-12)[:, :, None]
    separation = (push * close[:, :, None]).sum(axis=1)

    acc = (
        p.w_separation * _steer(separation, vel, p.max_speed, p.max_force)
        + p.w_alignment * _steer(mean_vel, vel, p.max_speed, p.max_force)
        + p.w_cohesion * _steer(mean_offset, vel, p.max_speed, p.max_force)
    )

    new_vel = vel + acc
    speed = np.sqrt((new_vel**2).sum(axis=1, keepdims=True))
    fast = speed > p.max_speed
    new_vel = np.where(fast, new_vel / np.where(fast, speed, 1.0) * p.max_speed, new_vel)
    slow = (speed > 0.0) & (speed < p.min_speed)
    new_vel = np.where(slow, new_vel / np.where(slow, speed, 1.0) * p.min_speed, new_vel)

    new_pos = pos + new_vel
    if p.boundary == "wrap":
        new_pos = new_pos % size
    else:  # bounce: reflect position and flip velocity at the walls
        for axis in (0, 1):
            low = new_pos[:, axis] < 0.0
            new_pos[low, axis] = -new_pos[low, axis]
            new_vel[low, axis] = -new_vel[low, axis]
            high = new_pos[:, axis] > size[axis]
            new_pos[high, axis] = 2.0 * size[axis] - new_pos[high, axis]
            new_vel[high, axis] = -new_vel[high, axis]
        np.clip(new_pos, 0.0, size - 1e-9, out=new_pos)

    return np.concatenate([new_pos, new_vel], axis=1)
