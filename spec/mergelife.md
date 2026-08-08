# MergeLife (Heaton 2017, arXiv:1712.03019)

Conformance tier: **bit-exact**, doubly enforced:
1. [`vectors/mergelife/`](../vectors/mergelife/) — this project's PNG vectors.
2. [`vectors/mergelife-upstream/`](../vectors/mergelife-upstream/) — the upstream
   cross-engine vectors from github.com/jeffheaton/mergelife, which the reference
   Python/JS/Java/C engines all satisfy. Passing these means byte-identity with the
   reference implementations. **When in doubt, upstream wins.**

## State

RGB lattice, unsigned bytes, shape `(height, width, 3)`, row-major.

## Genome

8 dash-separated groups of 4 hex digits, e.g. `e542-5f79-9341-f31e-6c6b-7f08-8773-7068`
("Red World", from the paper). Group *i* is two bytes: `range_byte` (unsigned) and
`percent_byte` (**signed**, two's complement). Canonical form is lowercase with dashes.

Compilation to sub-rules `(limit, percent, color_index)`:

- `limit = range_byte * 8`, except `2040` (i.e. `0xff*8`) is promoted to `2048` so the
  top sub-rule catches every neighbor count.
- `percent = pct/127.0` if `pct > 0` else `pct/128.0` (range `[-1.0, 1.0]`).
- `color_index = i`, indexing the key-color table: black, red, green, yellow, blue,
  purple, cyan, white (the RGB cube corners, in genome order).
- Sub-rules are **stably sorted by `limit` alone**; equal limits keep genome order.
  (Sorting by the full tuple is a known historical divergence — don't.)

## Update step (exact)

1. **Merge**: `avg = floor((r + g + b) / 3)` per cell, integer math.
2. **Mode**: `pad = mode(avg)`, ties broken toward the lowest value
   (`bincount().argmax()` semantics).
3. **Neighbor count**: 3×3 sum of `avg` excluding the center, with the boundary padded
   by `pad` (constant padding — *not* toroidal).
4. **Sub-rules**, in sorted order, each claiming cells no earlier sub-rule claimed:
   `mask = (count < limit) AND unclaimed`. A sub-rule with an empty mask claims nothing.
   For claimed cells:
   - if `percent < 0`: `percent = |percent|` and `color_index = (color_index + 1) mod 8`
   - `cell = cell + floor((key_color - cell) * percent)` per channel, float64 multiply,
     floor toward −∞. A zero percent still **claims** the cells (they stay unchanged).
5. Cells claimed by no sub-rule keep their value.

## Parameters

```json
{ "genome": "e542-5f79-9341-f31e-6c6b-7f08-8773-7068",
  "width": 128, "height": 128, "init": "soup", "seed": 0 }
```

## Initialization

- **soup** (this project's vectors): PCG32 seq 0, one draw per channel,
  `value = draw & 0xFF`, row-major, channels innermost (R, G, B).
- **upstream vectors**: the upstream 32-bit LCG
  (`state = state*1664525 + 1013904223`, byte = `state >> 24`), same ordering — see
  `vectors/mergelife-upstream/README.md`.

## Vector encoding

RGB PNG, raw bytes.

## Determinism note

The percent multiply is float64, but all operands are exact small integers times an
exact dyadic-adjacent rational; IEEE-754 double arithmetic makes the result identical
across languages, which is why four independent engines agree byte-for-byte upstream.
