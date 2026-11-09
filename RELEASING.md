# Releasing

One release is two packages with one version: `heaton-life` on PyPI and
`HeatonLife.Core` on NuGet.org. The conformance vectors make them one library,
so they ship together. The release automation follows the release convention
in `~/.claude/CLAUDE.md`, which dynaface and heaton-voxel follow too, in two
manual steps per language:
- A **build** tests the code and stamps the version file. It stages the
  packages on S3 with a build record (`<name>-<version>-build.json`: the
  commit, run and build number).
- A **deploy** publishes what was staged, by version. It then tags
  `v<version>` at the commit the build recorded.

Nothing reaches a registry until you run the deploy, and what it publishes is
exactly what the build checked. A tag records a release; it never triggers
one.

| step | Python | .NET |
| --- | --- | --- |
| test, on every push that can change the result | **Test Library** ([`test-lib.yml`](.github/workflows/test-lib.yml)) | **Test Library (.NET)** ([`test-lib-dotnet.yml`](.github/workflows/test-lib-dotnet.yml)) |
| build and stage | **Build Library** ([`build-lib.yml`](.github/workflows/build-lib.yml)) | **Build Library (.NET)** ([`build-lib-dotnet.yml`](.github/workflows/build-lib-dotnet.yml)) |
| publish | **Deploy Library to PyPI** ([`deploy-lib.yml`](.github/workflows/deploy-lib.yml)) | **Deploy Library to NuGet (.NET)** ([`deploy-lib-dotnet.yml`](.github/workflows/deploy-lib-dotnet.yml)) |

What each build stages on `s3://data.heatonresearch.com/library/`:
- Python: `heaton_life-<version>-py3-none-any.whl`, `heaton_life-<version>.tar.gz`
  and `heaton-life-<version>-build.json`.
- .NET: `heaton-life-dotnet-<version>.zip` (the DLL, its XML docs and PDB, and the
  license), `HeatonLife.Core.<version>.nupkg` and `.snupkg`, and
  `HeatonLife.Core-<version>-build.json`.

The bucket grants public read itself, so a staged file is unlisted but
downloadable by anyone with its URL; never treat one as secret.
`dotnet/README.md` links the zip, so for that one, public is the point.

The tests run Python 3.11 to 3.14 on Linux, macOS and Windows. The convention
says 3.10 to 3.14; the package's floor is 3.11 (`requires-python`: it uses
`typing.Self`, and the tests `tomllib`), and that is what is tested.

## One-time setup

Each item is done once, by the account owner. Nothing in the workflows can
do it for you.

1. **AWS secrets.** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
   `AWS_DEFAULT_REGION` (`us-east-1`) are set on the repository already
   (2026-08-22). They are the only secrets the release needs.
2. **PyPI.** The project exists, so add a trusted publisher to it: PyPI → Your
   projects → heaton-life → Publishing, with
   - Owner: `jeffheaton`
   - Repository name: `heaton-life`
   - Workflow name: `deploy-lib.yml`
   - Environment name: leave blank

   Then delete the old `PYPI_API_TOKEN` repository secret, and revoke the token
   on PyPI: no workflow reads it any more.
3. **NuGet.org.** The policy `heaton-life-dotnet` (Account → Trusted
   Publishing, created 2026-08-22) is bound to `jeffheaton/heaton-life` and the
   workflow file `build-lib-dotnet.yml`, which published 1.0.0 and 1.1.0. The
   build no longer publishes, so edit the policy's workflow file to
   `deploy-lib-dotnet.yml`. The deploy logs in as `jeffheaton`
   (`NuGet/login`'s `user`). Without a matching policy the login step fails
   with `No matching trust policy owned by user '…' was found`.
4. **Codecov.** Add `jeffheaton/heaton-life` at <https://app.codecov.io/gh>,
   or give the Codecov GitHub app access to it. The test workflows upload with
   OIDC, so no token is stored. Until it is added, the upload reports
   "Repository not found"; a failed upload never fails a run.

## Making a release

1. Set the new version in all six places:
   - `python/pyproject.toml` (`version`)
   - `python/src/heaton_life/__init__.py` (`__version__`)
   - `python/src/heaton_life/version.py` (`VERSION`, the baseline local builds report)
   - `dotnet/src/HeatonLife.Core/HeatonLife.Core.csproj` (`<Version>`)
   - `dotnet/src/HeatonLife.Core/Version.cs` (`Version`, the same baseline)
   - the `heaton-life-dotnet-<version>.zip` link under "Install" in
     `dotnet/README.md`, its text and its URL

   `python/tests/test_release_version.py` fails while they disagree, and
   Build Library (.NET), which runs no Python, refuses the last three before
   it builds anything. Add the release's entry to `CHANGELOG.md`, which the
   NuGet release notes link to. `python/README.md` and `dotnet/README.md` are
   frozen into each package as its registry page, so finish README edits first.
2. Commit and push to `main`, and let **Test Library** and
   **Test Library (.NET)** go green.
3. Run **Build Library** and **Build Library (.NET)** from the Actions tab
   (`gh workflow run build-lib.yml -R jeffheaton/heaton-life`, and the same
   for `build-lib-dotnet.yml`).
   - **Python:** static analysis reports (flake8, mypy, bandit, black and
     isort, plus ruff, this repo's own linter; reports, not gates); the suite
     under pytest, with JUnit results published as a check and coverage
     reports (the 60% threshold is reported, not enforced). Then it stamps
     `version.py` with the date and run number, builds the wheel and sdist,
     checks them with `twine check --strict`, and installs the wheel into an
     empty venv to read the stamp back.
   - **.NET:** the version check above, the `dotnet format` check, which does
     gate, and a vulnerable-packages report. Then it stamps `Version.cs`,
     builds Release, runs the xunit suite over that build (published as a
     check), and packs the DLL zip and the `.nupkg` and `.snupkg` (symbols,
     with Source Link at the built commit for every file but the stamped
     `Version.cs`).
   - **Both:** the results are uploaded as run artifacts and staged on S3.
4. Look at what the builds staged: the artifacts on each run's page, and the
   reports. To try the wheel before it is public on PyPI, install it from
   `https://data.heatonresearch.com/library/heaton_life-<version>-py3-none-any.whl`
   (the intro notebook's install cell can point there for a trial).
5. Run **Deploy Library to PyPI** and **Deploy Library to NuGet (.NET)**, one
   after the other, each with the version (e.g. `1.2.0`):

   ```
   gh workflow run deploy-lib.yml -R jeffheaton/heaton-life -f version=<version>
   ```
   ```
   gh workflow run deploy-lib-dotnet.yml -R jeffheaton/heaton-life -f version=<version>
   ```

   Each:
   1. downloads its files and build record for that version from S3;
   2. checks that `v<version>` is either untagged or already at the recorded
      commit, and refuses otherwise;
   3. publishes, then tags `v<version>` at that commit.

   The two builds of one release must come from one commit: the second deploy
   then finds the tag already where it belongs, and refuses otherwise. If they
   differ, rebuild the older one at the newer commit.
6. After both are out:
   - NuGet.org's package page lists the version, renders the README and offers
     "Download symbols", and its repository commit is the tagged one.
   - The intro notebook (`python/examples/heaton_life_intro.ipynb`) installs the
     latest release unpinned; if its install cell was pointed at S3 for a
     trial, revert that, then run it end to end against the new version.
   - Record the release in `ROADMAP.md`.

A version, once on PyPI or NuGet.org, can't be uploaded again. NuGet's push
skips a duplicate rather than failing; PyPI's refuses it. To fix a bad
release, publish the next version. Rerunning a build at the same version
replaces what is staged on S3, so a deploy always publishes the latest build
of that version.

## The Unity app

heaton-life-unity takes the C# library as a DLL built from a checkout of this
repo at the release commit (its `tools/build_core_dll.py`), not from NuGet.
Its own "Releasing" section in `CLAUDE.md` has the order the two follow.
