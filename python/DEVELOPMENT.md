# Developing heaton-life (Python)

This guide is for working on the library itself. If you only want to use it, the
[README](README.md) covers installation and the API.

The Python package is one part of a larger repository. The algorithm
specifications (`../spec/`), the golden conformance vectors (`../vectors/`), and
the .NET implementation (`../dotnet/`) sit beside it, and the tests here read the
vectors directly, so work from a full clone rather than from an installed wheel.

## Prerequisites

- Python 3.11 or newer.
- A clone of the repository:

  ```
  git clone https://github.com/jeffheaton/heaton-life.git
  cd heaton-life/python
  ```

- Optional, for MP4 export: `ffmpeg` is pulled in by the `video` extra
  (`imageio-ffmpeg`), nothing to install by hand.
- Optional, for fast deep zooms: the `precision` extra installs `gmpy2`; binary
  wheels exist for the common platforms. Without it the orbit runs on plain Python
  integers, about half as fast and bit-for-bit the same.

## Setting up

The project convention is a virtual environment at `python/.venv`:

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,playground,video]"
```

| Extra | What it adds |
|---|---|
| `dev` | pytest, pytest-cov, ruff, mypy, gmpy2 (the test suite exercises the fast deep-zoom path), mpmath (an independent oracle in `test_pow10.py`) |
| `playground` | PyQt6, for the interactive app and its offscreen tests |
| `precision` | gmpy2 for faster deep-zoom reference orbits (plain Python ints otherwise; identical results) |
| `video` | imageio-ffmpeg for `.mp4` output from `Animation.save`, `render_zoom_movie` / `MovieWriter` and `encode_frames` |

## Layout

```
python/
├── pyproject.toml      # packaging, ruff, pytest, and mypy configuration
├── src/heaton_life/    # the package (src layout; installed editable above)
│   ├── core/           # protocols, Viewport, params, PCG32, buffers, kernels, integrators
│   ├── ca/             # lifelike, elementary, cyclic, wireworld, mergelife (+ the rule gallery),
│   │                   #   hashlife/ (the unbounded universe, Macrocell, views, frames)
│   ├── lenia/          # kernels, classic, asymptotic, flow
│   ├── fractal/        # escape-time engine, perturbation engine, mandelbrot, julia, burning_ship, newton
│   ├── boids/          # reynolds (O(N²) neighbors, capped at 2k boids; a spatial hash is future work)
│   ├── rd/             # gray_scott + presets
│   ├── evolve/         # the MergeLife genetic algorithm and objective
│   ├── init/           # soup, blob, single, RLE import, built-in patterns, PNG I/O
│   ├── render/         # colormaps, image, animate (GIF/MP4 with inline notebook display)
│   ├── playground/     # PyQt6 app (optional extra)
│   └── version.py      # build stamp (see Releasing)
├── tests/              # pytest suite; replays ../vectors and drives the playground offscreen
├── tools/              # gen_vectors.py, gen_gallery.py, gen_palettes.py, score_rules.py,
│                       #   bench_hashlife.py, fetch_patterns.py
└── examples/           # the intro notebook (runs in Colab)
```

## The checks

These four commands are what the Build Library workflow runs. `ruff check`, `mypy`,
and `pytest` must be green before committing; `ruff format --check` is advisory (see
below).

```
ruff check src tests tools
ruff format --check src tests tools
mypy
QT_QPA_PLATFORM=offscreen pytest -q
```

- **ruff**: line length 100, configured in `pyproject.toml`. `ruff format --check` is
  advisory in CI and the tree is not currently format-clean (about 40 files would
  change), so format only the files you touch (`ruff format <file>`) rather than
  reformatting the tree in an unrelated commit.
- **mypy** runs in strict mode over `heaton_life` (`gmpy2` has no stubs and is
  ignored for missing imports).
- **pytest** takes a few seconds. `pytest -m "not slow"` skips the long evolver
  runs and the deep-zoom oracle (`tests/test_deep_oracle.py`, the only tests that
  check T1 against direct arbitrary-precision iteration), so run the full suite
  before touching the fractal code. Coverage: `pytest --cov=heaton_life --cov-report=term`.
- The playground tests run Qt offscreen, which is what `QT_QPA_PLATFORM=offscreen`
  is for. On a headless Linux machine install `libegl1 libgl1 libxkbcommon0` first.

## How the library is built: the spec decides

heaton-life is spec first and multi-language, and that shapes every change.

- **The specification wins.** Each family has a page under `../spec/` describing
  its math (gather, respond, integrate), its parameters, and its random draws.
  When an implementation and the spec disagree, the implementation is wrong, or
  the spec gets fixed deliberately and every implementation follows.
- **The vectors decide disputes.** `../vectors/` holds golden outputs
  (`params.json` plus expected states) shared by every implementation. Families
  in the bit-exact tier (the discrete automata, fractal iteration counts, colormaps
  and frame indexing, fractal color and the phase lookup, patterns and RLE, PNG grid
  I/O, the evolver) must match byte for byte; the epsilon tier (Lenia, boids,
  Gray-Scott, and the `fractal-render-*` cases under `render/`) must match within the
  tolerance recorded in each `params.json`, and the fractal `distance` output within
  its own `relative_epsilon`.
- **All randomness flows through PCG32** (`heaton_life.core.rng.Pcg32`). Never use
  NumPy's random module or Python's `random`; seeding and draw order are part of
  each family's spec, and the .NET port reproduces them exactly.
- **Never regenerate existing vectors casually.** They are the cross-language
  contract. Regenerate only when a deliberate spec change justifies it, and add
  new families or cases additively by appending their `write_case(...)` calls to
  `tools/gen_vectors.py`. The script has no section selector and regenerates every
  family when run except `png-io` (its `write_png_io_cases()` is not called from
  `main()` because PNG bytes are encoder-specific; invoke it by hand when adding a
  png-io case); afterward check `git status ../vectors/` and confirm only the
  new case directories changed (existing vectors must come back byte-identical)
  before committing. `../vectors/mergelife-upstream/` tracks the upstream MergeLife
  project and is never regenerated here.
- **Changes travel in order**: spec page, then the Python implementation (plus
  additive vectors if there is new surface), then the .NET port, with both test
  suites green. The C# port is expression for expression where a bit-exact tier
  applies, so keep Python expressions in the shape the spec gives them.

Some floating-point rules are not obvious and are easy to "clean up" by mistake:

- Powers of ten in the fractal pixel scale go through `heaton_life.core.pow10`
  (the integer algorithm in `../spec/pow10.md`), never `10 ** x`, `math.pow`, or
  `log10`. Platform math libraries differ in the last bit at fractional zooms, and
  that flips escape counts in a bit-exact vector.
- NumPy (2.0.2 and later, hence the floor) fuses complex multiplies into FMAs; the C# port mirrors that at the
  same sites. Do not restructure the complex arithmetic in the fractal engine.
- Rounding is half-even (`np.round`), and operation order is specified where it
  matters (for example the Gray-Scott Laplacian `((N + S) + W) + E - 4C`).

## Adding or changing a family

1. Write or update the spec page first, including parameters, seeding, and the
   conformance cases you intend to pin.
2. Implement it under the matching package, following the `Simulation` protocol
   in `core/protocols.py`: `step(n)`, `reset(seed)`, `state`, and `frame()`.
   Frames are always renderable: 2-D `uint8`, 2-D float in `[0, 1]`, or `HxWx3`
   `uint8` RGB. Fractals implement the `Field` protocol instead
   (`render(size, viewport)`).
3. Give it a frozen `Params` dataclass with UI metadata on each field (`label`,
   `min`, `max`, `step`, `choices`, `role`; see `ca/lifelike.py` for the pattern). The playground builds its forms from this,
   so a new family gets a UI for free.
4. Curated content (presets, galleries, built-in patterns) is part of the
   cross-implementation contract: it is listed in the spec and pinned by tests in
   both ports rather than by vectors.
5. Wire it into the conformance machinery: a codec and tier for the family in
   `src/heaton_life/conformance.py` (`CODECS`, `TIERS`; the codec defines the vector
   file encoding, which the spec page's vector section must match) and a section in
   `tools/gen_vectors.py` (read the regeneration policy above first). Then add tests:
   unit tests for the implementation and a conformance test that replays the
   family's vectors.
6. Port it to .NET (`../dotnet/`), then update the docs: the README sample if it
   belongs there, and the gallery image via `tools/gen_gallery.py`.

## Tools

- `tools/gen_gallery.py` renders one tile per system into `../docs/gallery.png`,
  the image at the top of both READMEs.
- `tools/gen_vectors.py` generates conformance vectors. Read the regeneration
  policy above before running any of it.
- `tools/gen_palettes.py` records how the cyclic palettes (`../spec/render.md`,
  "Cyclic palettes") were baked into `src/heaton_life/render/_palette_tables.py` and
  `../dotnet/src/HeatonLife.Core/PaletteTables.cs`. Those bytes are normative data,
  pinned by `../vectors/render/lut-<name>/`; the script is not re-run casually, and if
  it is, both table files and the LUT vectors must come back unchanged.
- `tools/bench_hashlife.py` measures HashLife throughput (`../spec/hashlife.md`): load
  time, then generations per second at fixed step sizes 2^e, with nodes, store memory
  (and its peak), collections, and the process's peak RSS, for the built-in set or any
  `.rle`/`.mc`/`.mc.gz` files given. See "HashLife giants" below.
- `tools/fetch_patterns.py` downloads the giant HashLife patterns (the Caterpillar and
  Annelid) into the git-ignored `.patterns/` and checks each against its pinned size and
  SHA-256. See "HashLife giants" below.
- `tools/score_rules.py` scores MergeLife rule strings with the paper objective
  (`../spec/evolve.md`).

## HashLife giants

Two engineered spaceships are the HashLife engine's stress tests: **the Caterpillar**
(Nivasch, Summers and Bell, 2004; 17c/45, 11,967,399 cells, an 8 MB Macrocell file) and
**Annelid** (Brithos, 2026; (28,3)c/84, 168,807,151 cells, 5.5 MB of gzip Macrocell).
Neither file states a license, so neither is committed. `tools/fetch_patterns.py` fetches
pinned Wayback Machine copies (conwaylife.com refuses scripts) into the git-ignored
`.patterns/`, checking each file's size and SHA-256:

```
.venv/bin/python tools/fetch_patterns.py
export HEATON_LIFE_PATTERNS="$PWD/.patterns"
.venv/bin/pytest -q tests/test_hashlife_giants.py
.venv/bin/python tools/bench_hashlife.py .patterns/caterpillar.mc \
    --budget 4000 --exponents 0,4,8 --seconds 30 --min-steps 2
```

`tests/test_hashlife_giants.py` skips unless `HEATON_LIFE_PATTERNS` names the cache
(and is marked `slow`). It checks the Macrocell placement (the Caterpillar's top-left cell
lands on (0, 0); Annelid's box) and one period of each ship:

- The Caterpillar after 270 generations equals generation 0 moved 102 cells up, compared
  row for row with `get_rect` in strips, once under an 8 GB budget and once under 1.5 GB,
  where the 2^8 sub-step overflows the store and takes the abandon, collect, and halve
  path ("Memory" in `../spec/hashlife.md`).
- Annelid after 252 generations has moved (−9, −84) with the same population, the same
  128 × 128 grid of `population_in` regions relative to its box, and identical 512 × 512
  windows around a live cell of each occupied region on the grid's diagonals. The whole
  state is too big to compare cell by cell.

It takes about five minutes and 4 to 6 GB of memory.

**Measurements** (2026-11-02, Apple silicon, CPython 3.12; one process per budget, five
at a time; `--exponents 0,4,8 --seconds 30 --min-steps 2`, so each size runs at least 30 s
and two steps, starting where the previous size stopped). Peak store is the budget's own
estimate, sampled between steps; RSS is the process's peak; collections are cumulative.

The Caterpillar loads in 0.7 s (336,720 nodes, 41 MiB of store):

| Budget (MiB) | 2^0 gen/s | 2^4 gen/s | 2^8 gen/s (512 gens) | Peak store (MiB) | Collections | Peak RSS (MiB) |
|---:|---:|---:|---:|---:|---:|---:|
| 500 | 0.20 | 1.5 | 0.95 (537 s) | 477 | 49 | 1,314 |
| 1,000 | 0.22 | 2.7 | 1.1 (471 s) | 880 | 19 | 2,262 |
| 2,000 | 0.27 | 3.0 | 5.7 (89 s) | 1,970 | 2 | 4,405 |
| 4,000 | 0.27 | 3.6 | 6.0 (85 s) | 3,096 | 1 | 5,397 |
| 8,000 | 0.26 | 3.6 | 8.2 (62 s) | 3,836 | 0 | 6,444 |

Annelid loads in 1.6 s (778,484 nodes, 101 MiB of store). One generation rebuilds about
2.8 million nodes, so single generations cost 19 s; at 2^8 a generation costs 0.13 s:

| Budget (MiB) | 2^0 gen/s | 2^4 gen/s | 2^8 gen/s (512 gens) | Peak store (MiB) | Collections | Peak RSS (MiB) |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.05 | 0.41 | 0.59 (862 s) | 994 | 21 | 2,328 |
| 2,000 | 0.05 | 0.64 | 4.6 (112 s) | 1,855 | 2 | 3,060 |
| 4,000 | 0.05 | 0.64 | 7.4 (69 s) | 3,645 | 0 | 5,915 |
| 8,000 | 0.05 | 0.64 | 7.5 (69 s) | 3,645 | 0 | 5,908 |

At 500 MiB the first generation raises `HashLifeMemoryError`: one generation's new nodes
don't fit beside the pattern.

**The speed gate.** Neither giant stalls at the budgets Python needs for it, 2 to 8 GB:
from 2 GB up a 2^8 step costs 31 to 45 s on the Caterpillar and 34 to 56 s on Annelid,
with at most a couple of collections. Below that the budget, not the algorithm, sets the
pace. A sub-step whose new nodes overflow the store is abandoned, collected, and split in
half ("Memory" in `../spec/hashlife.md`), so at 500 MiB to 1 GB the Caterpillar's 2^8
steps run about 8 times slower (Annelid's 13 times, at 1 GB), and at the default 500 MiB
Annelid can't take a single generation (`step` says so and asks for a bigger budget).
Results are identical at every budget: the tight-budget Caterpillar test above, and
`tests/test_hashlife.py` at 10 and 500 MiB.

So `store.py` is unchanged. In-flight collection (a saved-node stack, so a step
collects midway instead of starting over) would cut the waste below 2 GB, but every
recursion would pay for the stack, and a 2^8 Caterpillar step still makes about 8 million
new nodes, a gigabyte of store, so a 500 MiB budget would collect over and over. A denser
store has little room in pure Python: a node is a dict entry, a tuple, and an int, about
130 bytes. The C# port's arena has both. Run the giants in Python at 2 to 8 GB; the
playground's giant presets ask for 4 GB (the Caterpillar) and 8 GB (Annelid), and the
giant tests run at 8 GB (the Caterpillar's period once more at 1.5 GB).

The budget is the store's own estimate (about 130 bytes a node plus 45 to 100 per cached
result, fitted with `tracemalloc`). The process's peak RSS runs 1.6 to 2.8 times the store's
peak (the interpreter's own 100 MB or so, and memory freed by collections stays with the
allocator), so leave headroom.

## Playground

```
heaton-life                          # or: python -m heaton_life.playground
```

Space plays and pauses, N single-steps, R resets, Ctrl+S saves a PNG. The
playground consumes only the public API; if it seems to need a hack, the API is
what needs changing.

The **HashLife** family (Cellular Automata) is the unbounded universe:

- **Pattern** is a built-in name (the presets list them) or a `.rle`, `.mc`, or `.mc.gz`
  file (Browse…). Loading adopts the file's rule and fits the view to the pattern.
  With `HEATON_LIFE_PATTERNS` set, the presets include the two giants, with budgets
  they run well at.
- **Step (2^k gens)**: each step advances 2^k generations; the speed slider sets steps
  per second. **Max memory (MB)** is the hash budget: it changes speed,
  never results.
- The view is the spec's three integers: **View x/y** (the frame's top-left pixel in the
  pixel plane) and **Mag** (2^mag pixels per cell; negative zooms out, one quadtree node
  per pixel). The wheel (2× a notch; a trackpad swipe's coasting is ignored) and a
  trackpad pinch zoom about the pointer; a drag pans while zoomed out past one cell per
  pixel, with Option/Alt held at any zoom, or with the middle button; Ctrl/Cmd+click
  recenters. At one cell per pixel or closer, left-click draws and right-click erases,
  inside the ±10⁹ editing box (outside it the status bar says why nothing changed).
- Navigation answers at once, mid-step: the canvas keeps the view
  (`playground/navigator.py`), draws the last frame where it lands in the new one, and
  the engine renders the new view between steps, once per burst of gestures.
- The frame fills the canvas: **Frame width/height** (read-only) follow the window, at
  one frame pixel per canvas pixel or the **Cell** setting's square of them, and a resize
  keeps the view's center in place. Loading a pattern fits it to the canvas.
- Every field but the pattern changes the universe in place, and Reset returns to the
  starting snapshot (edits made at the start belong to it) without reloading the file.
  Pause and Reset cut a long step short at a completed sub-step.
- **Save pattern…** (Ctrl+Shift+S) writes RLE while the pattern lies inside the editing
  box and Macrocell otherwise; the dialog also offers the other formats. The status bar
  shows generation, population, step size, the center cell, nodes, and store memory.

## Versioning

The version lives in six places that move together, three of them here: `version` in
`pyproject.toml`, `__version__` in `src/heaton_life/__init__.py`, and the `VERSION`
baseline in `src/heaton_life/version.py`; and three in the .NET library: `<Version>` in
`../dotnet/src/HeatonLife.Core/HeatonLife.Core.csproj`, the `Version` constant in its
`Version.cs` baseline, and the `heaton-life-dotnet-<version>.zip` link in
`../dotnet/README.md`. `tests/test_release_version.py` fails unless all six agree, and
the Build Library workflow also refuses a `pyproject.toml` that disagrees with
`__version__`.

`src/heaton_life/version.py` is the build stamp that ships inside the wheel
(`VERSION`, `BUILD_DATE`, `BUILD`). The tracked file is a baseline with `BUILD = 0`,
meaning a local build (local and editable installs report its `VERSION`, and so does
the self-check's report header); the Build Library workflow regenerates it with the
run number and date before packaging.

## Releasing

[`../RELEASING.md`](../RELEASING.md) is the whole sequence, for both packages: the
release convention's two manual steps, **Build Library**
(`.github/workflows/build-lib.yml`), which tests, stamps `version.py`, builds the wheel
and sdist and stages them with a build record on `s3://data.heatonresearch.com/library/`,
then **Deploy Library to PyPI** (`.github/workflows/deploy-lib.yml`), which uploads
what was staged by Trusted Publishing and tags `v<version>` at the built commit.
**Test Library** (`test-lib.yml`) runs the suite on Linux, macOS and Windows with
Python 3.11 to 3.14 on every push that touches `python/`, `vectors/` or `spec/`.

The staged wheel is public at
`https://data.heatonresearch.com/library/heaton_life-<version>-py3-none-any.whl`, so a
build can be tried before it is deployed: point the intro notebook's install cell
there for a trial, and revert it before committing. The notebook
(`examples/heaton_life_intro.ipynb`) installs the latest release with an unpinned
`!pip install --upgrade heaton-life` and is committed with its outputs cleared; after a
release, run it end to end against the new version, and if the API changed, update the
cells and clear the outputs. `README.md` is frozen into the wheel as the PyPI project
page, so finish README edits first.

## Code style

- ruff clean at line length 100; mypy strict; no `Any` where a real type exists.
- Params are frozen dataclasses with UI metadata; every family follows the
  `Simulation` or `Field` protocol.
- Docstrings cite the spec page a module implements, so readers can find the
  contract a function is honoring.
- Nothing merges without its spec page and vectors.
