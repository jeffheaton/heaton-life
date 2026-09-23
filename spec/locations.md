# Locations: conventions, conversions and importers

A deep-zoom *location* is a center and a scale. Every program that renders one frames
it its own way, so the same numbers show different pictures in different programs.
This page pins the conventions heaton-life, Heaton Fractal (HF), Kalles Fraktaler 2+
(KF) and Fraktaler-3 (F3) use, how a location converts between them, and how the
library reads their files. Python `heaton_life.fractal.locations`, C#
`HeatonLife.Locations`.

## Conventions

| | heaton-life | Heaton Fractal | Kalles Fraktaler 2.15 | Fraktaler-3 |
|---|---|---|---|---|
| Framing axis | **width**: `ps = (4/W)·10^−z` | height: `p = 2·h0/(10^d·H)` | height: half-height `2/Zoom`, `p = 4/(Zoom·H)` | height: `p = 4/(zoom·H)` |
| Scale field | `zoom_log10` (float) | `targetDepthLog10` `d`, with `baseHalfHeight` `h0` (a decimal string) | `Zoom` (decimal) | `location.zoom` (decimal string) |
| Pixel sample | `j + 0.5 − W/2` | `x + 0.5 − W/2` | `i − W/2` (half a pixel off) | `i + 0.5 − W/2` |
| Imaginary axis | up | up | down, unless `ImagPointsUp` (2.15.4+) | up, unless `transform.reflect` |
| Escape | `|z| > 1000` | `|z|² ≥ 256²` | per file | per file |
| Center precision | the frame's places ([navigation.md](navigation.md)) | printed at `⌊d⌋ + 64` places by its hunter | `≈ log10 Zoom + 23` places | `24 + log2(zoom·H)` bits |

Sources: KF `fraktal_sft.cpp` (`SetPosition`: `di = 2/z`; `GetZoom`: `2/m_ZoomRadius`)
and `render.cpp` (`m_pixel_scale = 2·m_ZoomRadius/m_nY`); F3's documentation ("Zoom 1
(without Transform) corresponds to vertical axis from −2 to +2") and `hybrid.cc`
(`4/zoom/height`); HF's ARCHITECTURE.md and `IterationUniforms.swift`.

Every other program frames by the **height**, so a location's portable scale is its
**half-height** `h`, the distance from the center to the top edge in plane units:

| Source | `log10 h` |
|---|---|
| KF, F3 | `log10 2 − log10 Zoom` |
| HF preset | `log10 h0 − d` |
| HF hunt result / journal | `−d` (hunts frame with `h0 = 1`: the nucleus's size fills the half-height) |

Viewing that location in a heaton-life frame `W × H` so the **vertical extent
matches** gives

```
zoom_log10 = log10(fl(2·H / W)) − log10 h
```

— for KF and F3, `log10 Zoom + log10(H/W)`; for HF, `d + log10(2H/(h0·W))`. A square
frame of a KF location is `log10 Zoom`; a 16:9 frame is `log10 Zoom − 0.2499`.

> Heaton Fractal imports a KF or F3 zoom as `d = log10 Zoom` with `h0 = 1`, which is
> half the KF half-height: its imports land `log10 2 = 0.30103` decades too deep (its
> own `metallic-e1324.kfr` comment says so). The table above is the exact framing.

These conversions use `log10`, and so are **not bit-exact**: a platform's `log10` may
differ in the last place. They run once, when a location enters, never on a render
path; the zoom they produce is stored with the viewport and is the contract from then on
(the vectors compare it within a relative `1e-12`). Centers convert exactly: they are decimal
strings everywhere.

## The location record

An importer returns:

- `center_re`, `center_im` — decimal strings in the [grammar](deep-zoom.md#viewport-contract-lands-in-core-on-day-one),
  rewritten positionally ([navigation.md](navigation.md) `positional`: same value, same
  places, no exponent);
- `half_height_log10` — `log10 h`, or none when the file gives no scale;
- `max_iter` — the file's iteration budget, or none;
- `reference` — F3's `[reference] real, imag` (its perturbation reference), or none;
- `format` — `kfr`, `f3`, `hf-preset`, `hf-result`, `hf-journal`;
- `warnings` — codes for what the file asks that heaton-life does not do, in this
  order: `rotation-ignored`, `stretch-ignored`, `reflect-ignored` (the source shows the
  view mirrored top to bottom: F3's `reflect`, or KF's default downward imaginary
  axis), `exponential-map-ignored` (F3's log-polar strip), `old-style-skew` (KF's
  legacy `Rotate ≠ 0` or `Ratio ≠ 360`, which KF 2.15 itself no longer loads),
  `no-scale`.

`viewport(W, H)` builds the heaton-life viewport by the formula above (an error without
a scale). The reference is reported, not attached: a host that wants it passes it to
`with_reference`.

## File formats

**KF `.kfr`** — `Key: value` lines. Lines split at `\r\n`, `\r` or `\n`; a leading
byte-order mark is dropped; blank lines and lines starting with `;` or `#` are skipped.
The key is the text before the first `:` (or `=`), both sides trimmed, matched without
regard to case; a later duplicate wins; unknown keys are ignored (KF writes dozens).
`Re` and `Im` are required. `Zoom` must be positive; without it there is no scale.
`Iterations` is a whole number (`1e6` allowed). `RotateAngle ≠ 0` warns
`rotation-ignored`, `StretchAmount ≠ 0` warns `stretch-ignored`, and `ImagPointsUp`
absent or 0 warns `reflect-ignored` (KF draws the imaginary axis down unless it is set,
which covers every file from before 2.15.4); legacy `Rotate ≠ 0` or `Ratio ≠ 360` warns
`old-style-skew`.

**F3 `.f3.toml`** — the TOML subset F3 writes: `[section]` headers, `key = value` with
dotted keys (`location.real = "…"`), `#` comments, basic `"…"` and literal `'…'`
strings, numbers (`_` separators dropped), booleans — and multi-line strings. F3 1.x
through 3.0 (toml11 v3 at `setw(70)`) write any string of 68 or more characters, so
every deep coordinate, as `"""`, a newline, chunks of 69 characters each ending in a
line-ending backslash (which removes itself, the newline and the whitespace after it),
the last chunk, a line-ending backslash, and the closing `"""`; F3 3.1 writes every
string on one line. The importer reads both, and triple-apostrophe literal strings
(no escapes). A multi-line string closes at the first unescaped triple delimiter, and
up to two more delimiter characters just before it belong to the value. Other lines (arrays,
inline tables, dates, the keys of `[[array tables]]`) are skipped. F3 **leaves out every
key that holds its default**, so a missing one means the default: `location.real` and
`location.imag` `"0"`, `location.zoom` `"1"` (an F3 file always has a scale),
`bailout.iterations` 1024, and a missing reference part the location's. A file with
neither a `location.*` key nor `program = "fraktaler-3"` is not a location. Strings are
the values; numbers are taken by their source text. `reference.real` or
`reference.imag` gives the reference; `transform.rotate ≠ 0`,
`transform.stretch_amount ≠ 0`, `transform.reflect = true` and
`transform.exponential_map = true` warn.

**HF preset JSON** — `settings.location.centerReal`, `centerImag` and `baseHalfHeight`,
all strings and all **required** (HF's own decoder requires `baseHalfHeight`; the
`"1.25"` in its source is only a constructor default); `settings.zoom.targetDepthLog10`,
a finite number — when the zoom group or the key is missing there is **no scale** (HF
itself would render at its app default, depth 433 at the time of writing);
`settings.quality.maxIterationsOverride`, a positive integer or absent.
The file is either a preset envelope (`{"formatVersion", …, "settings": {…}}`) or a bare
settings object (HF's `settings.json`). The C# port takes the parsed fields — Core reads
no JSON — as does every host that parses its own.

**HF hunt result `.txt`** — `re = …` and `im = …` lines (spaces or tabs around `=`),
`#` comments. A comment of the form `… depth 1e<d>` gives the scale; otherwise none.

**HF hunt `journal.jsonl`** — one JSON object per line with string `real` and
`imaginary` and a finite number `depthLog10`; the deepest entry wins (not the last
line), the latest among equals; a line that is not such a seed — a torn write, `NaN`
(not JSON), a numeric center — is skipped. Like the preset, C# takes the parsed fields.

Iteration budgets are whole numbers from 1 to 2⁶³ − 1; a larger one is an error in
every format.

## Conformance

Centers, budgets, references, formats and warnings are **exact**; `half_height_log10`
and the zooms of `viewport` within a **relative** `1e-12`:
`|got − want| ≤ epsilon · max(1, |want|)` (the `epsilon` in each case). At a zoom near
2836 that allows about `2.8e-9`; an absolute `1e-12` would allow only about two ulps
there, less than two platforms' `log10` can differ by after the addition. Vectors in
[`../vectors/locations/`](../vectors/locations/): an input file beside `params.json`,
which holds the expected record and the viewports of one or more frame sizes.
