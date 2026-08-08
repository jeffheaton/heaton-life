# Boids (Reynolds 1987)

Conformance tier: **ε-tolerance** (ε = 1e-6; flocking is chaotic, keep cross-language
comparisons to ≤50 steps). Vectors: [`vectors/boids/`](../vectors/boids/).

## State

Point cloud, not a grid: float64 array `(count, 4)`, rows `[x, y, vx, vy]`, world
units in `[0, width) x [0, height)`. Unit timestep (speeds are per-step displacements).

## Update (one step, in this order)

Neighbors are O(N²) — every pair, minimum-image wrapped deltas when `boundary=wrap`:
`delta_ij = pos_j − pos_i` (wrapped); neighbor iff `0 < |delta|² ≤ perception²`.

1. `mean_offset_i` = mean of `delta_ij` over neighbors (relative — a torus has no
   absolute mean position); `mean_vel_i` = mean neighbor velocity.
2. `separation_i` = Σ over j with `|delta|² ≤ separation_radius²` of
   `−delta_ij / max(|delta|², 1e-12)`.
3. Reynolds steering, applied to each of the three vectors `d`:
   `steer(d) = clip_norm(normalize(d)·max_speed − vel, max_force)`; zero when `d = 0`.
4. `vel += w_separation·steer(separation) + w_alignment·steer(mean_vel) + w_cohesion·steer(mean_offset)`
5. Speed clamp: rescale to `max_speed` if above; up to `min_speed` if `0 < speed < min_speed`.
6. `pos += vel`; then `wrap` (mod size) or `bounce` (reflect position at each wall
   and negate that velocity component).

Reductions may associate freely (ε tier); do not promise bitwise sums.

## Parameters

```json
{ "count": 300, "width": 256, "height": 256,
  "perception": 12.0, "separation_radius": 6.0,
  "w_separation": 1.5, "w_alignment": 1.0, "w_cohesion": 1.0,
  "max_speed": 3.0, "min_speed": 1.0, "max_force": 0.08,
  "boundary": "wrap", "init": "random", "seed": 0 }
```

Count is capped at 2000 (O(N²) neighbors); a spatial hash is future work if larger
flocks are ever needed.

## Initialization

PCG32 seq 0, three draws per boid in order: `x = u·width`, `y = u·height`,
`heading = u·2π` where `u = draw / 2³²`; velocity = `(cos, sin)(heading)` times
`(min_speed + max_speed)/2`. (cos/sin are libm calls — another reason this family
is ε-tier.)

## Frame (presentation)

Rasterized `(height, width)` float field: a 3×3 soft dot per boid (center 1.0,
cross 0.55, diagonals 0.3, summed and clipped), wrapped. The playground instead
draws oriented triangles straight from the state — the same simulation, two
renderers, which is the point of the state/frame split.

## Vector encoding

Raw little-endian float64, shape `(count, 4)` in the checkpoint entry.

## Oracles

- All weights zero ⇒ velocities are untouched **bitwise** and total momentum is
  conserved exactly; positions advance linearly (mod wrap).
- Cohesion-only pulls a pair together; separation-only pushes a close pair apart;
  alignment-only halves heading variance within 60 steps.
- Speed clamps hold under full steering; wrap keeps positions in-world; bounce
  reflects and negates the wall-normal velocity.
