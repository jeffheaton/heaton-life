# MergeLife (Heaton 2017, arXiv:1712.03019)

Conformance tier: **bit-exact**, doubly enforced:
1. [`vectors/mergelife/`](../vectors/mergelife/) — this project's PNG vectors.
2. [`vectors/mergelife-upstream/`](../vectors/mergelife-upstream/) — the upstream
   cross-engine vectors from github.com/jeffheaton/mergelife, which the reference
   Python/JS/Java/C engines all satisfy. Passing these means byte-identity with the
   reference implementations. **When in doubt, upstream wins.**

## State

RGB lattice, unsigned bytes, shape `(height, width, 3)`, row-major.

## Rule

8 dash-separated groups of 4 hex digits, e.g. `e542-5f79-9341-f31e-6c6b-7f08-8773-7068`
("Red World", from the paper). Group *i* is two bytes: `range_byte` (unsigned) and
`percent_byte` (**signed**, two's complement). Canonical form is lowercase with dashes.

Compilation to sub-rules `(limit, percent, color_index)`:

- `limit = range_byte * 8`, except `2040` (i.e. `0xff*8`) is promoted to `2048` so the
  top sub-rule catches every neighbor count.
- `percent = pct/127.0` if `pct > 0` else `pct/128.0` (range `[-1.0, 1.0]`).
- `color_index = i`, indexing the key-color table: black, red, green, yellow, blue,
  purple, cyan, white (the RGB cube corners, in rule order).
- Sub-rules are **stably sorted by `limit` alone**; equal limits keep rule order.
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

The JSON key `"genome"` is frozen — it is the vectors' cross-language wire format
(and the upstream repo's name for the rule). APIs and UI say **rule**; "genome"
survives only inside the GA trainer (spec/evolve.md), where rules really are
genomes of an evolutionary search.

## Initialization

- **soup** (this project's vectors): PCG32 seq 0, one draw per channel,
  `value = draw & 0xFF`, row-major, channels innermost (R, G, B).
- **upstream vectors**: the upstream 32-bit LCG
  (`state = state*1664525 + 1013904223`, byte = `state >> 24`), same ordering — see
  `vectors/mergelife-upstream/README.md`.

## Decoded rule table (the rule lab)

`decode_rule(rule)` (C#: `MergeLife.DecodeRule`) expands a rule into the 8-row
table the HeatonCA "Rule" tab displays — the data lives in the library so every
UI renders the identical table. Rows are the compiled sub-rules in their sorted
order (stable by `limit`); each row carries:

| field | meaning |
|---|---|
| `limit` | α, the exclusive high bound (`2048` when promoted from `2040`) |
| `range_low` / `range_high` | inclusive claim interval: previous row's limit (0 for the first) .. `limit − 1` |
| `percent` | the signed compiled percent in `[-1, 1]` |
| `color_index` | γ, the 0-based position in the rule (original order) |
| `color_name` | γ's key-color name |
| `target_index` | the effective merge target: γ, or `(γ+1) mod 8` when `percent < 0` |
| `target_name` / `target_rgb` | the target's name and true key color |
| `range_byte` | raw octet 1 (`0..255`) — raw, so a promoted row still reads `0xff` |
| `percent_byte` | raw octet 2 as a signed byte (`-128..127`) |

Color names, in rule order: Black, Red, Green, Yellow, Blue, Purple, Cyan, White.

Display conventions (so the three UIs render identically): the Key Color column
shows `target_name` swatched with the **true** key color (not the display
toolkit's named color); Percent (β) is `trunc(percent × 100)` with its sign;
Index (γ) is `color_index` 0-based; octets display as `0x%02x` of the **raw**
octet with the decimal (octet 2: signed) in parentheses. The raw-octet rule is
a deliberate fix over HeatonCA, which re-derives octet 1 from the promoted
limit (`2048/8 = 0x100`) and hex-formats octet 2's magnitude instead of its
raw byte.

Conformance: [`vectors/mergelife-decode/`](../vectors/mergelife-decode/), one
case per rule with the expected rows embedded in `params.json`; bit-exact
(`percent` compares as exact float64).

## Vector encoding

RGB PNG, raw bytes.

## Determinism note

The percent multiply is float64, but all operands are exact small integers times an
exact dyadic-adjacent rational; IEEE-754 double arithmetic makes the result identical
across languages, which is why four independent engines agree byte-for-byte upstream.
