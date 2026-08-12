# Boids (Reynolds 1987), d-dimensional

Conformance tier: **ε-tolerance** (ε = 1e-6; flocking is chaotic, keep cross-language
comparisons to ≤50 steps). Vectors: [`vectors/boids/`](../vectors/boids/).

One algorithm, any dimension: the update rules below are written over the d
components of position and velocity and never mention an axis by name, so the
same definition flocks in 2D and 3D (and would in 4D — implementations expose
`dimensions` ∈ {2, 3}). Only **initialization** and the **frame projection**
are per-dimension recipes.

## State

Point cloud, not a grid: float64 array `(count, 2·d)`, rows
`[pos₀ … pos_{d−1}, vel₀ … vel_{d−1}]`, world units in `[0, sizeₐ)` per axis
where the box is `(width, height)` for d = 2 and `(width, height, depth)` for
d = 3. Unit timestep (speeds are per-step displacements). The d = 2 layout is
the historical `(count, 4)` rows `[x, y, vx, vy]`, unchanged.

## Update (one step, in this order)

All norms are Euclidean over the d components. Neighbors are O(N²) — every
pair, minimum-image wrapped deltas **per axis** when `boundary=wrap`:
`delta_ij = pos_j − pos_i` (wrapped); neighbor iff `0 < |delta|² ≤ perception²`.

1. `mean_offset_i` = mean of `delta_ij` over neighbors (relative — a torus has no
   absolute mean position); `mean_vel_i` = mean neighbor velocity.
2. `separation_i` = Σ over j with `|delta|² ≤ separation_radius²` of
   `−delta_ij / max(|delta|², 1e-12)`.
3. Reynolds steering, applied to each of the three vectors `d`:
   `steer(d) = clip_norm(normalize(d)·max_speed − vel, max_force)`; zero when `d = 0`.
4. `vel += w_separation·steer(separation) + w_alignment·steer(mean_vel) + w_cohesion·steer(mean_offset)`
5. Speed clamp: rescale to `max_speed` if above; up to `min_speed` if `0 < speed < min_speed`.
6. `pos += vel`; then `wrap` (mod size per axis) or `bounce` (reflect position at
   each wall and negate that velocity component, per axis).

Reductions may associate freely (ε tier); do not promise bitwise sums.

## Parameters

```json
{ "count": 300, "dimensions": 2, "width": 256, "height": 256, "depth": 256,
  "perception": 12.0, "separation_radius": 6.0,
  "w_separation": 1.5, "w_alignment": 1.0, "w_cohesion": 1.0,
  "max_speed": 3.0, "min_speed": 1.0, "max_force": 0.08,
  "boundary": "wrap", "init": "random", "seed": 0 }
```

`depth` participates only when `dimensions = 3`. Count is capped at 2000
(O(N²) neighbors); a spatial hash is future work if larger flocks are ever
needed.

## Initialization

PCG32 seq 0, per-dimension recipes (an angle does not generalize by component,
so each d gets an explicit draw order; `u = draw / 2³²` throughout, launch
speed = `(min_speed + max_speed)/2`):

- **d = 2** — three draws per boid in order: `x = u·width`, `y = u·height`,
  `heading = u·2π`; velocity = `(cos, sin)(heading)` times launch. (The
  historical recipe, byte-for-byte: existing 2D vectors and saved worlds
  replay unchanged.)
- **d = 3** — five draws per boid in order: `x = u·width`, `y = u·height`,
  `z = u·depth`, `φ = u·2π`, `w = u·2 − 1`; direction =
  `(√(1−w²)·cos φ, √(1−w²)·sin φ, w)` — uniform on the sphere, no rejection
  sampling — velocity = direction times launch.

(cos/sin/sqrt are libm calls — another reason this family is ε-tier.)

## Frame (presentation)

Rasterized `(height, width)` float field: a 3×3 soft dot per boid (center 1.0,
cross 0.55, diagonals 0.3, summed and clipped), wrapped; pixel =
truncate(position) with floored wrap on x and y.

- **d = 2** — kernel weights as-is (the historical frame, unchanged).
- **d = 3** — orthographic projection along z onto the same `(height, width)`
  field; each boid's kernel weights are scaled by the depth cue
  `b = 0.3 + 0.7·(1 − z/depth)` (z = 0 is the near plane, brightest), then
  summed and clipped exactly as in 2D.

The playground/app may instead draw oriented shapes (or a perspective 3D view)
straight from the state — the same simulation, multiple renderers, which is
the point of the state/frame split. The orthographic frame is the canonical
cross-language presentation.

## Nudge (editing)

The standard pointer interaction, defined here so every front-end pushes the
same flock the same way. `nudge(x, y, radius, strength)` applies a radial
velocity impulse at world point `(x, y)`: for each boid,
`offset = (pos₀ − x, pos₁ − y)`, minimum-image wrapped per axis when
`boundary = wrap`; `dist = |offset|`; boids with `0 < dist < radius` receive
`vel₀,₁ += offset/dist · strength`. Positive strength repels (scare), negative
attracts (lure). The pointer is 2-D: the impulse acts in the x/y plane and
never touches z position or velocity, any d; a boid exactly at the point is
untouched. Editing, not physics — the generation does not change, and the next
step's speed clamp bounds the result. (Apps conventionally use radius 48 and
strength `±0.8 · max_speed`.)

## Vector encoding

Raw little-endian float64, shape `(count, 2·d)` in the checkpoint entry.

## Oracles

- All weights zero ⇒ velocities are untouched **bitwise** and total momentum is
  conserved exactly (per component, any d); positions advance linearly (mod wrap).
- Cohesion-only pulls a pair together; separation-only pushes a close pair apart;
  alignment-only halves heading variance within 60 steps.
- Speed clamps hold under full steering; wrap keeps positions in-world; bounce
  reflects and negates the wall-normal velocity — per axis, including z.
- d = 3 seeding: |velocity| = launch speed for every boid (the sphere direction
  is unit-norm by construction).
