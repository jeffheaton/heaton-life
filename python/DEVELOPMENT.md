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
  wheels exist for the common platforms. Without it the library falls back to
  `mpmath`, which is slower but gives the same results.

## Setting up

The project convention is a virtual environment at `python/.venv`:

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,playground]"
```

| Extra | What it adds |
|---|---|
| `dev` | pytest, pytest-cov, ruff, mypy, gmpy2 (the test suite exercises the fast deep-zoom path) |
| `playground` | PyQt6, for the interactive app and its offscreen tests |
| `precision` | gmpy2 for fast deep-zoom reference orbits (mpmath fallback is built in) |
| `video` | imageio-ffmpeg for `.mp4` output from `Animation.save` |

## Layout

```
python/
├── pyproject.toml      # packaging, ruff, pytest, and mypy configuration
├── src/heaton_life/    # the package (src layout; installed editable above)
│   ├── core/           # protocols, Viewport, params, PCG32, buffers, kernels, integrators
│   ├── ca/             # lifelike, elementary, cyclic, wireworld, mergelife (+ the rule gallery)
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
├── tools/              # gen_vectors.py, gen_gallery.py, score_rules.py
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
- **mypy** runs in strict mode over `heaton_life` (`gmpy2` and `mpmath` have no
  stubs and are ignored for missing imports).
- **pytest** takes a few seconds. `pytest -m "not slow"` skips the long evolver
  runs. Coverage: `pytest --cov=heaton_life --cov-report=term`.
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
  and frame indexing, patterns and RLE, PNG grid I/O, the evolver) must match byte
  for byte; the epsilon tier (Lenia, boids, Gray-Scott, and the smooth-colored fractal render
  cases under `render/`) must match within the tolerance recorded in each
  `params.json`.
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
- NumPy 2.x fuses complex multiplies into FMAs; the C# port mirrors that at the
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
- `tools/score_rules.py` scores MergeLife rule strings with the paper objective
  (`../spec/evolve.md`).

## Playground

```
heaton-life                          # or: python -m heaton_life.playground
```

Space plays and pauses, N single-steps, R resets, Ctrl+S saves a PNG. The
playground consumes only the public API; if it seems to need a hack, the API is
what needs changing.

## Versioning

The version is declared in two places that must agree: `version` in
`pyproject.toml` and `__version__` in `src/heaton_life/__init__.py`. The build
fails if they differ. The .NET library's `<Version>` in
`../dotnet/src/HeatonLife.Core/HeatonLife.Core.csproj` is bumped in step with
them.

`src/heaton_life/version.py` is the build stamp that ships inside the wheel
(`VERSION`, `BUILD_DATE`, `BUILD`). The tracked file is a baseline with `BUILD = 0`,
meaning a local build; the Build Library workflow regenerates it with the run
number and date before packaging.

## Releasing

Two manually dispatched GitHub workflows (the same build-then-deploy shape as the
maintainer's [dynaface](https://github.com/jeffheaton/dynaface) project). Nothing
runs on push.

1. **Build Library** (`.github/workflows/build-lib.yml`): ruff and mypy reports
   (advisory), the test suite (fatal), the regenerated `version.py`, then the
   wheel, `twine check`, a workflow artifact named `heaton-life-wheel`, and a copy
   at `s3://data.heatonresearch.com/library/`. The S3 copy is public, for example
   `https://data.heatonresearch.com/library/heaton_life-1.0.0-py3-none-any.whl`,
   which lets a build be tried before it is deployed to PyPI (the intro notebook
   installed from that URL until 1.0.0; it now installs from PyPI).
2. **Deploy Library to PyPI** (`.github/workflows/deploy-lib.yml`): takes a wheel
   file name, downloads it from that S3 prefix, and uploads it to PyPI with twine.
   Splitting build from deploy means a build can be inspected before the
   irreversible step.

Repository secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_DEFAULT_REGION` (`us-east-1`), and `PYPI_API_TOKEN`, which should be a token
scoped to the `heaton-life` project (PyPI → Your projects → heaton-life → Settings →
API tokens). The first upload, 1.0.0, needed an account-scoped token because the
project did not exist yet; if that token is still the one stored, replace it with a
project-scoped one and update the repository secret.

Release checklist:

1. Bump the version in `pyproject.toml`, `__version__` in `src/heaton_life/__init__.py`,
   and the `VERSION` baseline in `src/heaton_life/version.py` (CI checks only the first
   two against each other; the baseline is what local and editable builds report), in
   step with the .NET csproj, its `Version.cs` baseline, and the zip link in
   `dotnet/README.md` (see `../dotnet/DEVELOPMENT.md`, "Releasing"). `README.md` is
   frozen into the wheel as the PyPI project page, so finish README edits first.
2. Run the four checks locally, commit, and push.
3. Dispatch Build Library:

   ```
   gh workflow run build-lib.yml -R jeffheaton/heaton-life
   ```

   Check the run, then download the `heaton-life-wheel` artifact and try it in a
   fresh environment (or point the intro notebook's install cell at the S3 wheel URL).
4. Dispatch the deploy with the wheel's file name:

   ```
   gh workflow run deploy-lib.yml -R jeffheaton/heaton-life -f whl_file=heaton_life-1.0.0-py3-none-any.whl
   ```

   PyPI versions are immutable: anything that needs changing after the upload
   becomes the next version.
5. The intro notebook (`examples/heaton_life_intro.ipynb`) installs the latest
   release with an unpinned `!pip install --upgrade heaton-life` and is committed
   with its outputs cleared, so nothing in it changes per release. If you pointed
   its install cell at the S3 wheel URL in step 3, revert that. After the upload,
   run the notebook end to end (Colab, or a fresh venv) against the new version to
   confirm every sample still runs; if the API changed, update the cells and
   clear the outputs before committing.
6. Once both packages are out, tag the released commit (one tag serves both,
   since the versions move together) and push it:
   `git tag -a v<version> -m "heaton-life <version>" && git push origin v<version>`.

## Code style

- ruff clean at line length 100; mypy strict; no `Any` where a real type exists.
- Params are frozen dataclasses with UI metadata; every family follows the
  `Simulation` or `Field` protocol.
- Docstrings cite the spec page a module implements, so readers can find the
  contract a function is honoring.
- Nothing merges without its spec page and vectors.
