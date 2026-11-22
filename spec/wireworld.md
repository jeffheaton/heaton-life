# Wireworld (Silverman)

Conformance tier: **bit-exact**. Vectors: [`vectors/wireworld/`](../vectors/wireworld/).

## State

2-D grid, unsigned bytes: `0` empty, `1` electron head, `2` electron tail, `3` conductor.
Shape `(height, width)`, row-major. Default boundary is `dead` (circuits rarely want a
torus); every [topology](topology.md#the-topologies) is allowed: `torus`, `klein`, `cross`
and `sphere`, with `shift` and `axis` as [lifelike.md](lifelike.md#parameters) gives
them.

## Gather / Respond / Integrate

Count electron heads among the 8 Moore neighbors, read from the grid's
[halo](topology.md#the-halo) of radius 1 (past a `dead` edge, empty). Then,
synchronously:

- head → tail
- tail → conductor
- conductor → head **iff** the head count is exactly 1 or 2, else stays conductor
- empty → empty

Note the classic Moore-neighborhood consequence: electrons "cut" right-angle corners
(the far corner cell sees the head diagonally), briefly doubling the head. This is
correct Wireworld behavior, not a bug.

## Parameters

```json
{ "width": 64, "height": 64, "init": "clock", "boundary": "dead" }
```

`shift` and `axis` join them for a torus or a Klein bottle; absent, they are 0 and `x`.

No seed — Wireworld has no randomness.

## Initialization

- **clock**: a rectangular conductor ring inset 2 cells from the edge, with one
  electron: tail at `(top, left+1)`, head at `(top, left+2)`. Deterministic.
- Patterns come from ASCII art: `.` empty, `H` head, `T` tail, `#` conductor.

## Vector encoding

Grayscale PNG, pixel = `state * 85` (0/85/170/255 — exact and human-viewable).

## Oracles

- A conductor flanked by 3 heads does not fire.
- The clock loop is periodic with a conserved electron (1–2 heads at every step).
