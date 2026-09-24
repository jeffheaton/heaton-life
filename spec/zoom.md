# Zoom movies

A zoom movie descends (or climbs) from one depth to another at a fixed center, one frame
per step of a schedule. This page pins the schedule and every frame's zoom, the
iteration budget each frame gets, and the survey that measures that budget, so every
port that renders the probes with the same field puts every frame at the same depth
with the same `max_iter`. Python `heaton_life.fractal.movie` (with `movie_max_iter`,
`need_at` and `measured_max_iter` in `heaton_life.fractal.policy`); C# `ZoomSchedule`,
`ZoomPlan`, `ZoomSurvey` (its `Survey` takes the host's probe renderer) and
`IterationPolicy.MovieMaxIter` / `NeedAt` / `MeasuredMaxIter`. Rendering and color
([below](#rendering-python-presentation)) are Python presentation.

The schedule is Heaton Fractal's, and the survey follows its measured mode
(`Render/ZoomSchedule.swift`, `Render/PalettePrePass.swift`,
`Numerics/IterationNeedCurve.swift`, `Render/IterationSurvey.swift`); [Departures from
Heaton Fractal](#departures-from-heaton-fractal) lists what differs and why.

All arithmetic below is float64 (one rounding per operation, left to right as
parenthesized, no fused multiply-add) or exact integers.

## Schedule

A schedule is four segment lengths in seconds: `hold_start`, `ease_in`, `ease_out`,
`hold_end` (defaults 3, 5, 5, 5, Heaton Fractal's). `UNIFORM` is all four 0: one constant
speed from the first frame to the last. The descent's speed is 0 through the first hold,
rises by smoothstep over the ease in, runs at full speed through the cruise, falls by
smoothstep over the ease out, and is 0 through the last hold; the cruise fills whatever
the other four leave.

### Fitting to a duration

`resolved(D)` fits a schedule to a run of `D` seconds:

1. `span = D` if `D` is finite and `> 0`, else `0`.
2. Each segment `v` becomes `v` if finite and `> 0`, else `0`: `h0, e0, e1, h1`.
3. `budget = span · 0.9`; `shaped = ((h0 + e0) + e1) + h1`. If `shaped > budget` and
   `shaped > 0`: `scale = budget / shaped` and each segment is multiplied by `scale` (one
   multiply each). A tenth of every run keeps cruising, up to rounding: among the
   smallest subnormals the segments can fill the span, leaving no cruise, and then
   `eff = 0.5 · (e0 + e1)` is 0 when the eases are (or halve to 0). The rules below
   cover `eff ≤ 0`.
4. `cruise = max(0, (((span − h0) − e0) − e1) − h1)`;
   `eff = cruise + 0.5 · (e0 + e1)` (each smoothstep ramp integrates to one half).
5. `peak_over_average = span / eff` when both are `> 0`, else `1`.

### Progress

`progress(t)`, the fraction of the descent done by `t` seconds, is the closed-form integral
of the speed normalized by `eff`, with the end pinned to exactly 1:

```
if not span > 0: return 0
if not eff > 0:  return 1 if t >= span else 0
if t >= span:    return 1
time = max(t, 0)                       # t, unless 0 is greater
if time <= h0: return 0
covered = 0;  r = time − h0
if e0 > 0:
    if r < e0: x = r / e0;  return min(1, (e0 · (((x·x)·x) − ((((0.5·x)·x)·x)·x))) / eff)
    covered += 0.5·e0;  r −= e0
if cruise > 0:
    if r < cruise: return min(1, (covered + r) / eff)
    covered += cruise;  r −= cruise
if e1 > 0 and r < e1:
    x = r / e1;  return min(1, (covered + e1 · ((x − ((x·x)·x)) + ((((0.5·x)·x)·x)·x))) / eff)
return 1
```

Over the ease in that is `e0·(x³ − x⁴/2)`, over the ease out `x − x³ + x⁴/2` of `e1`.

### Speed

`speed_fraction(t)`, the speed as a fraction of the peak:

```
if not (span > 0 and eff > 0): return 0
if t >= span: return 1 if (e1 == 0 and h1 == 0 and cruise > 0) else 0
time = max(t, 0)
if time < h0: return 0
r = time − h0
if e0 > 0:
    if r < e0: x = r / e0;  return (x·x)·(3 − 2·x)
    r −= e0
if r < cruise: return 1
r −= cruise
if e1 > 0 and r < e1: x = r / e1;  return 1 − (x·x)·(3 − 2·x)
return 0
```

At and past the end it is the value arriving there: 1 when the run ends in its cruise,
else 0.

## Plan

`ZoomPlan(start_zoom, end_zoom, frames, fps, schedule = UNIFORM)`: `frames ≥ 2` and
`fps ≥ 1` integers; `schedule` a schedule; each zoom finite with `|zoom| ≤ 10000`
([`pow10x`](pow10.md#floatexp)'s domain) and taken as `zoom + 0.0`, so a negative zero is
`+0`. Either direction:
`end < start` zooms out. `shallowest = end if end < start else start`, `deepest = end if
end > start else start`.

- `D = float64(frames − 1) / float64(fps)`, the last frame's time (a float64 division of
  exact integers, never an integer division), and `resolved = schedule.resolved(D)`.
- Frame `f` (`0 ≤ f < frames`): `time(f) = float64(f) / float64(fps)`,
  `p = resolved.progress(time(f))`, and
  ```
  zoom(f) = start                           if p == 0
          = end                             if p == 1
          = shallowest if lerp < shallowest, else deepest if lerp > deepest, else lerp
            where lerp = start + (end − start) · p
  ```
  The first frame is `start` and the last is `end`, exactly; holds are exactly still.
- `speed(f)`, decades per frame (negative zooming out), for motion blur and a UI:
  `(((end − start) / eff) / float64(fps)) · resolved.speed_fraction(time(f))`, 0 when
  `eff ≤ 0`.

No rotation: a frame's pixel offsets are the [pixel mapping](fractals.md)'s.

## Iteration budget

Policy, versioned apart from the counts like the [iteration
policy](fractals.md#iteration-policy) (still version 1: these are additions). Two rules,
chosen by whether the movie has a user limit.

**With a user limit** `U` (`1 ≤ U ≤ 2³¹ − 1`): Heaton Fractal's rule, on heaton-life's
depth ramp. With `a = auto_max_iter(zoom)` and `a_T = auto_max_iter(deepest)`:

```
movie_max_iter(zoom, deepest, U) = min(U, max(a, floor(U · a / a_T)))
```

in exact integers (`U · a` reaches `2⁶²`: 64-bit in C#). It is exactly `U` at the deepest
frame, the ramp scaled up proportionally above it, and `U` caps a ramp that would exceed
it. Without a limit, `movie_max_iter(zoom, deepest) = a`: the ramp alone, which is what a
[survey](#survey) improves on.

**Without one** (Heaton Fractal's measured mode): the budget comes from the survey's
knots `(zoom_k, need_k)`, ascending in zoom:

```
need_at(z)  = 0                                   with no knots
            = max(need_{k−1}, need_k, need_{k+1})  at a knot, z == zoom_k (neighbors that exist)
            = need_first                          for z < every knot
            = need_last                           for z > every knot
            = max(need_{k−1}, need_k)             between, zoom_{k−1} < z < zoom_k
measured_max_iter(z) = min(max(auto_max_iter(z), 2 · need_at(z)), 2³¹ − 1)
```

The larger of the two knots around a depth, and nothing assumed between them: Heaton
Fractal measured that the depth ramp is wrong near a nucleus by orders of magnitude in
both directions, and that twice the p99.9 keeps every escaping pixel clear of the budget,
so its steps between stations change no escaping pixel's count.

## Survey

The survey probes the descent at stations before any frame renders.

**Stations**, ascending (`LOG10_2 = 0.3010299956639812`, the double nearest `log10 2`;
`low = shallowest`, `high = deepest`); the regular and approach stations keep an octave
apart, and both ends are always probed:

1. `low`;
2. `low + float64(i) · (float64(s) · LOG10_2)` for `i = 1, 2, …` while below
   `high − 33.0 · LOG10_2` (every `s` octaves, default `s = 64`);
3. `high − float64(k) · LOG10_2` for `k` in 32, 24, 16, 12, 8, 7, 6, 5, 4, 3, 2, 1 where
   greater than `low + LOG10_2` (the approach, where a nucleus's escapes spread fastest);
4. `high`, when `high > low`.

**A probe** is a 192 × 108 frame (Heaton Fractal's) of the movie's own field — the family
and options its frames use, at the probe's budget — at the station's zoom and the
movie's center, rendered with counts and [status](fractals.md#status). **The patience
rule**, from a budget `b` (default `auto_max_iter(zoom)`) up to a cap `C ≤ 2³¹ − 1`
(default `min(64 · auto_max_iter(deepest), 2³¹ − 1)`):

```
b = min(b, C)
loop:
    probe at b;  E = escaped points, X = points with status 1 (exhausted), L = latest escape (0 if none)
    stop if X == 0, or (E > 0 and b ≥ 2·L), or b ≥ C
    b = min(2·b, C)
```

Points proven interior (status 2, 3) are resolved. A station's knot is
`need_from_counts(counts)` of its last probe, none when nothing escaped. Near a nucleus
escapes arrive in bands about a period apart, so doubling never stops inside a gap
between bands; a gap wider than a doubling ends the probe early (the vectors' case
`gap-past-double`). A station where nothing escapes and nothing is exhausted (all proven
interior) stops after one probe; one where nothing escapes runs to the cap.

With a user limit each station is probed once, at `movie_max_iter(zoom, deepest, U)`,
for [color](#rendering-python-presentation) only, and frame `f` gets
`movie_max_iter(zoom(f), deepest, U)`; without one it gets
`measured_max_iter(zoom(f))` from the stations' knots (Python `MovieSurvey.max_iter`, C#
`ZoomSurvey.MaxIter`).

## Rendering (Python, presentation)

`render_zoom_movie(field_for, size, center, plan, output, …)` renders every frame (or a
`frames` range) with `field_for(max_iter)` at `Viewport(center, zoom(f))`, the budget
from the survey, and writes it to an `.mp4` (consecutive frames, in order) or a
directory of `frame_N.png` files (`N` zero-padded to five digits; any order; existing
frames are skipped, so a crashed render resumes and several processes can share one
movie over disjoint ranges). `encode_frames` turns the directory into an `.mp4` in
numeric order and refuses one with a gap. The checks that need no frame run before the
survey: the arguments and `frames` range, the plan's deepest zoom and the shading
against the field, a passed survey's plan and limit, and the output (the video extra
and ffmpeg; an existing target a regular file it can read and write, or a new one's
directory present and writable; an `.mp4` frame of at least 2 × 2; a passed writer's
state). A path is resolved once, as imageio resolves it (`~` expanded, made absolute).
ffmpeg itself starts at the first frame, and the target is emptied only once that frame
is ready: a failure while frames go in
raises there, and closing an `.mp4` that took frames raises unless the file is a whole
MP4 (its top-level boxes cover it and include `moov`, which ffmpeg writes last), since
imageio never reads ffmpeg's exit status. Not bit-exact across platforms (it uses libm
`log2` and `hypot`), and not vectored:

- **Color** is the [depth phase](fractal-color.md) with two movie rules. The octave term
  is per sample, `k · (L − log2 max(ρ, 0.5))` with `L = zoom · LOG2_10` and `ρ` the
  sample's distance from the frame center in pixels of a 1920-wide frame of the same
  view (`ρ_samples · 1920 / (W · ss)`): a function of the point's plane radius alone, so
  a point keeps its color as it flies outward, as in Heaton Fractal's movies, at any
  output size, aspect or supersample. And with `track_color` (default) the frequency
  and anchor come from the stations' `measure_frequency` fits, linear in zoom between the
  two fitted stations around the frame and held past either end, so the palette follows
  the counts' rise with depth instead of strobing.
- **Supersampling** renders `ss × ss` samples per pixel, colors them undithered, averages
  them in light (encoded values squared, the gamma-2 model of [distance
  shading](fractal-color.md)), and dithers once at the output size with
  `tpdf_frame(W, H, f)`.
- **MP4**: libx264, yuv420p, frames cropped to even sizes and never rescaled (imageio's
  default macro block of 16 would stretch 1080 rows to 1088).

## Departures from Heaton Fractal

- **The last frame is the target.** Heaton Fractal's run lasts `frames / fps` with frame
  `f` at `f / fps`, so its last frame falls short of the target unless the fitted
  `hold_end ≥ 1/fps`; here `D = (frames − 1) / fps`. Its uniform path uses a different
  duration from its shaped one; here uniform is the same code with all segments 0.
- **The end is pinned.** Heaton Fractal's closed form can sit up to three ulps below 1
  through a closing hold (its two sums round differently) and return `1 + 2⁻⁵²` late in
  an ease out, so its movies can end a few ulps short of the target or pass it (past a
  family's deepest zoom) and step back. `progress` returns exactly 1 from the end of the
  ease out and at `t ≥ D`, and clamps the ease-out branch to 1 (the ease-in and cruise
  clamps are defensive: those branches cannot exceed 1). Heaton Fractal never evaluates
  `t = D`.
- **The ramp** is heaton-life's `auto_max_iter`, not Heaton Fractal's
  `1500 + 900·max(d, 1)^1.18` (libm `pow`).
- **The user-limit rule** floors the exact integer `U · a / a_T` of the rounded ramps.
  Heaton Fractal rounds `U · (here / atTarget)` of its unrounded ramps and floors the
  result at 1000, so its budget exceeds `U` when `U < 1000`.
- **Stations** start at the plan's shallow end (Heaton Fractal's regular stations start
  at magnification 1 whatever the start), stop 33 octaves short of the deep end (Heaton
  Fractal's run to the target, so they can land within `1e-11` of an approach station:
  two probes of one depth), take the approach only more than an octave past the shallow
  end (Heaton Fractal's: past magnification 1), and space the regular ones a whole
  number of octaves (Heaton Fractal's spacing is real).
- **Patience** re-probes at doubled budgets. Heaton Fractal runs one probe and stops it,
  checking every four dispatches, once every running point has passed
  `max(2 · latest escape, automatic)`.
- **The probe cap** has a default here. Heaton Fractal waits for its orbit's limit and
  grows the orbit when a station is cut off by it.
- **Frame depth** is float64 throughout (Heaton Fractal carries a frame's depth in
  float32 on the GPU).

## Not yet

- **Log-polar strips** (Heaton Fractal's exponential map): each plane point iterated once
  per movie, resampled into frames. heaton-life renders every frame directly.
- **Rotation** and **motion blur**.

## Conformance

`vectors/zoom/` (spec 0.13.0), bit-exact in both ports, floats as IEEE-754 bit patterns:

| case | what |
|---|---|
| `schedules` | `resolved` segments, cruise, eff and peak over average for 15 schedules (clamped, holds only, bad segments and durations, one where the ease-out clamp fires), then `progress` and `speed_fraction` at 23 times each |
| `plans` | every frame's progress, zoom and speed for 11 plans, among them three that a literal port of Heaton Fractal's closed form ended an ulp short of or past the target at this page's frame times, one where it passes 1 before the end, a zoom-out, a 2-frame plan and a negative zero |
| `budgets` | `movie_max_iter` with and without limits (Heaton Fractal's 11 Dimensions preset, `U = 2³¹ − 1`, `U = 1`), and `need_at` / `measured_max_iter` over four knot sets |
| `stations` | the stations of 9 plans and spacings, one with an approach station within an octave of the shallow end (dropped) |
| `probes` | the patience rule on synthetic probes: each point escapes at its listed count once the budget reaches it (−1 never, −2 proven interior); expected, every budget asked and the station. `at-twice-latest` stops on `b = 2·L` exactly, `gap-past-double` shows a gap wider than a doubling |
| `surveys` | whole surveys with real Mandelbrot probes (192 × 108, default escape radius): Seahorse Valley measured and with `U = 5000`, and a center inside the main cardioid; every budget each station asked for, the stations, and every frame's `max_iter` |
