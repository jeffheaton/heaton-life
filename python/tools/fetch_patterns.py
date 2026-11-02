#!/usr/bin/env python3
"""Download the giant HashLife patterns into a local cache and verify their SHA-256.

The Caterpillar (Nivasch, Summers and Bell, 2004) and Annelid (Brithos, 2026) carry no
stated license, so they are never committed. conwaylife.com answers scripts with 403, so
this tool fetches pinned Wayback Machine copies (``id_`` URLs serve the original bytes)
into a git-ignored cache and checks each file against its pinned size and digest. A file
already in the cache is verified, not downloaded again.

Point ``HEATON_LIFE_PATTERNS`` at the cache to run the giant tests
(``tests/test_hashlife_giants.py``) and to benchmark the giants with
``tools/bench_hashlife.py``.

Usage:
    .venv/bin/python tools/fetch_patterns.py              # into python/.patterns
    .venv/bin/python tools/fetch_patterns.py --dest DIR
    export HEATON_LIFE_PATTERNS="$PWD/.patterns"
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_DEST = Path(__file__).resolve().parents[1] / ".patterns"
_USER_AGENT = "heaton-life fetch_patterns.py (https://github.com/jeffheaton/heaton-life)"
_STALLS = 6  # requests in a row that add no bytes before giving up


@dataclasses.dataclass(frozen=True)
class Giant:
    name: str
    """File name in the cache."""
    url: str
    size: int
    sha256: str
    about: str


GIANTS = (
    Giant(
        name="caterpillar.mc",
        url="https://web.archive.org/web/20241118174849id_/"
        "https://conwaylife.com/patterns/caterpillar.mc",
        size=8_192_751,
        sha256="02123320933ff9e550da90282202e6f3377c6456defd0edc9c53be2c171339a3",
        about="The Caterpillar, 17c/45 (Nivasch, Summers and Bell, 2004): 11,967,399 cells",
    ),
    Giant(
        name="annelid.mc.gz",
        url="https://web.archive.org/web/20260829065849id_/"
        "https://conwaylife.com/forums/download/file.php?id=8623",
        size=5_504_351,
        sha256="fc988d49edd8625ada6079f2c60dd078d028b928aed7ae585fe695d59dac5ae9",
        about="Annelid, (28,3)c/84 (Brithos, 2026): 168,807,151 cells, gzip Macrocell",
    ),
)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, target: Path, size: int) -> None:
    """Fetch ``size`` bytes into ``target``, resuming with Range requests: a connection
    that closes early ends ``read`` quietly (http.client returns b"" rather than raise),
    so only the byte count shows a short body."""
    target.write_bytes(b"")
    stalls = 0
    while (have := target.stat().st_size) < size:
        headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                mode = "ab" if response.status == 206 else "wb"  # 200: the server restarted
                with target.open(mode) as f:
                    while chunk := response.read(1 << 20):
                        f.write(chunk)
        except OSError as exc:  # URLError, HTTPError, timeouts: the Wayback Machine is flaky
            print(f"  {exc}", flush=True)
        got = target.stat().st_size
        if got > size:
            raise OSError(f"{url} sent {got:,} bytes, more than the pinned {size:,}")
        if got < size:
            stalls = stalls + 1 if got <= have else 0
            if stalls == _STALLS:
                raise OSError(f"{url} stopped at {got:,} of {size:,} bytes")
            print(f"  {got:,} of {size:,} bytes; resuming", flush=True)
            time.sleep(2 * stalls)


def fetch(giant: Giant, dest: Path) -> bool:
    """Make ``dest/giant.name`` hold the pinned bytes; True when it does."""
    path = dest / giant.name
    if path.is_file():
        digest = _digest(path)
        if digest == giant.sha256:
            print(f"{giant.name}: cached, SHA-256 verified")
            return True
        if giant.sha256:
            print(f"{giant.name}: cached copy has SHA-256 {digest}; downloading again")
    print(f"{giant.name}: {giant.about}\n  downloading {giant.url}", flush=True)
    part = path.with_name(path.name + ".part")
    try:
        _download(giant.url, part, giant.size)
        digest = _digest(part)
        if not giant.sha256:
            print(f"  no digest pinned yet: SHA-256 {digest}")
        elif digest != giant.sha256:
            print(f"  SHA-256 mismatch: got {digest}, want {giant.sha256}")
            return False
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
    print(f"  saved {path} ({giant.size:,} bytes)")
    return bool(giant.sha256)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="the cache directory")
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    verified = [fetch(giant, args.dest) for giant in GIANTS]
    print(f'\nexport HEATON_LIFE_PATTERNS="{args.dest.resolve()}"')
    if not all(verified):
        sys.exit(1)


if __name__ == "__main__":
    main()
