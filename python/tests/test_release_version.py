"""The version moves in six places at once (CLAUDE.md, "CI / releases"); a release that
bumps five ships a wrong stamp or link for the life of an immutable package."""

import re
import tomllib
from pathlib import Path

import heaton_life
from heaton_life import version

REPO = Path(__file__).resolve().parents[2]


def _one(pattern: str, path: str) -> str:
    matches = re.findall(pattern, (REPO / path).read_text(encoding="utf-8"))
    assert len(matches) == 1, f"{path}: expected one match for {pattern!r}, found {matches}"
    return str(matches[0])


def test_every_version_place_agrees() -> None:
    pyproject = tomllib.loads((REPO / "python/pyproject.toml").read_text(encoding="utf-8"))
    places = {
        "python/pyproject.toml": pyproject["project"]["version"],
        "heaton_life.__version__": heaton_life.__version__,
        "heaton_life.version.VERSION": version.VERSION,
        "HeatonLife.Core.csproj <Version>": _one(
            r"<Version>([^<]+)</Version>", "dotnet/src/HeatonLife.Core/HeatonLife.Core.csproj"
        ),
        "Version.cs Version": _one(
            r'public const string Version = "([^"]+)";', "dotnet/src/HeatonLife.Core/Version.cs"
        ),
    }
    # The README's zip link: its text and its URL both name the version.
    links = re.findall(
        r"heaton-life-dotnet-([0-9][^/`)\s]*)\.zip",
        (REPO / "dotnet/README.md").read_text(encoding="utf-8"),
    )
    assert len(links) == 2, links
    places["dotnet/README.md zip link"] = links[0]
    places["dotnet/README.md zip URL"] = links[1]
    assert len(set(places.values())) == 1, places
