# Changelog

Both packages, `heaton-life` on PyPI and `HeatonLife.Core` on NuGet, share one version
number, and from 1.1.0 on each release ships both from one commit. Every entry applies to
both unless it names a port. The spec version (the `spec_version` field of the conformance
vectors) moves on its own; each release lists the one it implements.

## 1.1.0 (2026-09-25)

Implements spec version 0.13.0 (1.0.0 implemented 0.2.0). Every conformance vector that
existed at 1.0.0 is byte-identical; the new behavior comes with new vector cases. The
public APIs of both packages are backward compatible: nothing was removed or renamed,
and new parameters are optional.

### Added

- **Deep zoom to 10⁹⁰⁰⁰.** A floatexp perturbation tier (T2) takes Mandelbrot and Julia
  from 10²⁹⁰, where 1.0.0 stopped, to 10⁹⁰⁰⁰. The Burning Ship still stops at 10²⁹⁰ and
  Newton at 10¹². Each family reports its ceiling (`max_zoom_log10` / `MaxZoomLog10`),
  and `tier_of` / `FractalEngine.TierOf` names a zoom's tier.
- **Bilinear approximation (BLA)** for Mandelbrot at T1 and T2, opt-in
  (`Mandelbrot(bla=True)`; in .NET `new Mandelbrot(maxIter, escapeRadius, workers,
  bla: true)`), which skips many iterations at once on deep frames.
- **Navigation:** off-center reference points; exact decimal pan and zoom
  (`heaton_life.fractal.navigation` / `Navigation`); location import from Kalles
  Fraktaler, Fraktaler-3, and Heaton Fractal (`fractal.locations` / `Locations`); and a
  nucleus finder (`find_nucleus` / `NucleusFinder`).
- **Escape fields:** pixel status, interior shortcuts, a distance estimate, and an
  iteration policy that picks a frame's `max_iter`.
- **Fractal color:** the measured stretch, a depth phase that holds a point's color
  still through a dive, distance shading, and four cyclic palettes (`deep`, `classic`,
  `embers`, `glacier`).
- **Zoom movies:** schedules, plans, and measured iteration budgets in both ports. The
  Python package also renders them (`render_zoom_movie`, to an MP4 or a resumable
  folder of PNG frames).
- **Platform self-check** (`heaton_life.self_check.run()` / `SelfCheck.Run`): 21 checks
  against answers embedded in the package, which a host runs on its own runtime to
  confirm it reproduces the bit-exact results, each scoped to what its failure would
  invalidate ([spec/self-check.md](spec/self-check.md)).
- A resumable reference-orbit cache: a longer orbit for a cached point and precision (a
  higher `max_iter` at the same zoom, or panning on a fixed reference) extends the cached
  one instead of starting over.
- .NET: `CancellationToken` overloads for the fractal renders, reference-orbit progress
  in `RenderProgress`, and a low-allocation orbit step.
- Python playground: the fractal zoom reaches each family's ceiling (10⁹⁰⁰⁰ for
  Mandelbrot and Julia), `max_iter` goes to 1,000,000 for Mandelbrot, Julia, and the
  Burning Ship, and click and wheel navigation is exact decimal arithmetic.

### Changed

- **Julia deep frames (past 10¹²) render correctly now, so they differ from 1.0.0.**
  1.0.0 restarted rebased pixels on the center's own orbit instead of Julia's critical
  orbit, and got 439 of the 1,024 pixels of `julia/deep-zoom13-32` wrong. Its orbits,
  computed at the frame's own zoom, were also too coarse near preimages of 0: on their own
  they cost 51 of 144 pixels at c = i and 10¹⁰⁰, where 1.0.0 got 98 wrong. Rebased pixels
  now restart on the critical orbit, and both orbits are computed at twice the frame's
  zoom. .NET: a caller that supplies its own orbits must compute them at twice the frame's
  zoom (`ReferenceOrbit.Julia` / `JuliaCritical` with `2 × ZoomLog10`).
- **Python: NumPy 2.0.2 or newer is required** (1.0.0 allowed `numpy>=1.24`). The
  reference relies on NumPy's complex multiply being fused. Before 2.0.2, NumPy counted
  an output that merely touched an input's memory as overlapping (numpy#27077) and took a
  plain C loop that is unfused in most builds, so results depended on where the
  allocator placed arrays; NumPy 1.24 had no fused complex kernel at all. The
  self-check's `numpy-fma` check now catches both.
- Newton's roots come from exact integer turns instead of the platform's `cos`/`sin`.
  Python's `Newton.roots` values can differ from 1.0.0 by up to about 4 × 10⁻¹⁶
  (-0.49999999999999983 is now -0.5, and 6.1e-17 is now 0); basins and renders were
  unchanged in every case tested.
- Viewport centers follow one strict decimal grammar in both ports: NaN, infinities, `_`
  separators, non-ASCII digits, exponents beyond ±100,000, and centers longer than
  10,000 digits are rejected.
- Fail-fast validation: an escape radius whose square is not finite (NaN and infinities
  included) is rejected, and in Python a Newton degree that is not an `int` (3.0
  included) raises `TypeError`.
- Reference orbits take enough precision for the center's own digits, not only for the
  zoom.
- Python: reference orbits run the spec's fixed-point arithmetic, as the .NET port
  already did, instead of floating point (gmpy2 or mpmath). The two had parted after
  enough iterations (at sample 38 of one deep Julia orbit, and 67,941 at a 10¹⁶⁰
  Mandelbrot location), so Python deep frames with long orbits can differ from 1.0.0;
  both ports now agree bit for bit at any length.
- Python: MP4 export no longer rescales frames to a multiple of 16 (1.0.0 stretched 1080
  rows to 1088; an odd width or height still loses one column or row), and it fails with
  a clear error when ffmpeg or the target file is unusable.
- Python: `mpmath` is no longer installed with the package. 1.1.0 no longer uses it,
  because reference orbits are integer arithmetic now; it moved to the dev extra, for the
  tests. The `[fast]` extra, which did nothing, is gone.
- Python: saved Mandelbrot parameters now include `bla`, which 1.0.0 rejects when
  loading them.
- Python internals outside every `__all__`: `fractal.engine.escape_time` returns
  `(counts, final, status)`, and `core.bignum.reference_orbit` returns read-only arrays
  and is no longer an `lru_cache` wrapper.
- .NET: `StateCodec` saves an Elementary world's space-time diagram after its tape, and
  `Elementary.SetState(tape, diagram, generation)` restores it. 1.1.0 loads 1.0.0 saves,
  but 1.0.0 cannot load an Elementary world saved by 1.1.0. `SetState(tape, generation)`
  now places the tape in its generation's row of the diagram.
- .NET: `RenderProgress.Started` is true from the reference-orbit phase on, and each
  render resets the progress object it is given.
- .NET: the `InternalsVisibleTo` grants to `HeatonLife.Core.EditorTests` and
  `HeatonLife.Unity` are gone; hosts use the public API, `SelfCheck` included.

### Fixed

- .NET: the software fma, which stands in for the hardware one on netstandard2.1, was
  not a correctly rounded fused multiply-add. For products below 2⁻⁹⁶⁸ and for huge
  operands its error-free transforms were not exact, so deep Julia smooth renders could
  disagree with Python (by about 3 × 10⁻⁷ on `render/fractal-render-julia-deep157`). And
  everywhere else it rounded twice, so a tie in the sum that only the product's rounding
  error breaks went the wrong way (fma(1 + 2⁻³⁰, 2⁻⁵³(1 − 2⁻³⁰), 1 + 2⁻⁵²) gave
  1 + 2⁻⁵¹, not 1 + 2⁻⁵²): C#'s complex multiply could then disagree with NumPy's in the
  last place. Both are fixed (exact integer arithmetic in the far ranges, the error terms
  rounded to odd in the common one), pinned bitwise against the hardware instruction,
  cases built to be such ties included.
- .NET: the software fma returned NaN for finite factors whose product overflows, where
  IEEE gives an infinity (or the addend, when it is the infinity); a Julia center near
  2 × 10¹⁵⁴ reached it.
- .NET: a render with `maxIter = int.MaxValue` could run forever (a 32-bit loop counter
  wrapped); the loop counters are 64-bit now.
- .NET: a deep frame whose center lies within about 10⁻²⁹² of an axis threw
  `ArgumentOutOfRangeException` past a zoom of about 10²⁶⁹ (converting an orbit sample
  that small needed a power of two below the normal range); it renders now.
- .NET: a deep Julia frame whose center lies beyond about 10¹⁶² threw
  `ArgumentOutOfRangeException` (an orbit sample overflowed a power of two); an orbit
  that overflows is infinite now, as in Python.

## 1.0.0 (2026-08-22)

The first release: MergeLife, Life-like, Elementary, Cyclic, and Wireworld automata;
Classic, Asymptotic, and Flow Lenia; Mandelbrot, Julia, and Burning Ship with
perturbation deep zoom to 10²⁹⁰, and Newton's basins; Reynolds boids in 2D and 3D; Gray-Scott
reaction-diffusion; the rendering pipeline; and the MergeLife evolver. Spec version
0.2.0. The NuGet package was built from commit `234075b` and the PyPI wheel from
`59da437`; the Python sources are identical at both.
