"""Bake the cyclic palettes (spec/render.md "Cyclic palettes") into byte tables.

The tables are normative as data -- both ports embed the bytes this script writes, and
vectors/render/lut-<name>/lut.png pins them -- and this script records how they were
made. It bakes Heaton Fractal's gradient stops (~/projects/mandelbrot,
Core/Settings.swift) the way its PaletteBaker evaluates them: positions wrapped into
[0, 1) and stable-sorted, stops linearized with the sRGB curve and converted to Oklab
(Ottosson's matrices; the reverse matrices by cofactor inversion), linear
interpolation in Oklab between neighboring stops around the cycle. Entry i is the
gradient at position i/256, clamped to [0, 1] in linear light, encoded with the sRGB
curve and rounded half to even from x255. An entry exactly on a stop takes the stop's
own bytes: the Oklab round trip leaves one such value (embers at 0.50, blue 0.10 * 255 =
25.5) a few ulps either side of a rounding tie depending on the platform's cbrt, and
every other entry is asserted to clear a tie by more than 1e-9.

Writes python/src/heaton_life/render/_palette_tables.py and
dotnet/src/HeatonLife.Core/PaletteTables.cs. Run from python/:

    .venv/bin/python tools/gen_palettes.py
"""

from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (name, Heaton Fractal's name, stops as (position, (r, g, b)) in sRGB 0..1)
PALETTES: list[tuple[str, str, list[tuple[float, tuple[float, float, float]]]]] = [
    (
        "deep",
        "Ultra Fractal Deep",
        [
            (0.0, (0.04, 0.12, 0.55)),
            (0.16, (0.125, 0.420, 0.796)),
            (0.42, (0.929, 1.000, 1.000)),
            (0.6425, (1.000, 0.667, 0.0)),
            (0.80, (0.85, 0.25, 0.05)),
            (0.875, (0.14, 0.11, 0.33)),
            (0.93, (0.08, 0.20, 0.62)),
        ],
    ),
    (
        "classic",
        "Ultra Fractal",
        [
            (0.0, (0.0, 0.027, 0.392)),
            (0.16, (0.125, 0.420, 0.796)),
            (0.42, (0.929, 1.000, 1.000)),
            (0.6425, (1.000, 0.667, 0.0)),
            (0.8575, (0.0, 0.008, 0.0)),
        ],
    ),
    (
        "embers",
        "Embers",
        [
            (0.00, (0.02, 0.01, 0.03)),
            (0.25, (0.55, 0.06, 0.05)),
            (0.50, (0.98, 0.55, 0.10)),
            (0.72, (1.00, 0.94, 0.72)),
            (0.88, (0.16, 0.10, 0.22)),
        ],
    ),
    (
        "glacier",
        "Glacier",
        [
            (0.00, (0.01, 0.03, 0.09)),
            (0.30, (0.06, 0.32, 0.52)),
            (0.55, (0.55, 0.85, 0.93)),
            (0.75, (0.95, 0.98, 1.00)),
            (0.90, (0.10, 0.16, 0.35)),
        ],
    ),
]

M1 = (  # linear sRGB -> LMS
    (0.4122214708, 0.5363325363, 0.0514459929),
    (0.2119034982, 0.6806995451, 0.1073969566),
    (0.0883024619, 0.2817188376, 0.6299787005),
)
M2 = (  # cube-rooted LMS -> Oklab
    (0.2104542553, 0.7936177850, -0.0040720468),
    (1.9779984951, -2.4285922050, 0.4505937099),
    (0.0259040371, 0.7827717662, -0.8086757660),
)

Matrix = tuple[tuple[float, float, float], ...]
Vec = tuple[float, float, float]


def _inverse(m: Matrix) -> Matrix:
    """Cofactor inverse, HF's ColorMatrix3.inverted() expression for expression."""
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    d = (
        m00 * (m11 * m22 - m12 * m21)
        - m01 * (m10 * m22 - m12 * m20)
        + m02 * (m10 * m21 - m11 * m20)
    )
    inv = 1 / d
    return (
        (
            (m11 * m22 - m12 * m21) * inv,
            (m02 * m21 - m01 * m22) * inv,
            (m01 * m12 - m02 * m11) * inv,
        ),
        (
            (m12 * m20 - m10 * m22) * inv,
            (m00 * m22 - m02 * m20) * inv,
            (m02 * m10 - m00 * m12) * inv,
        ),
        (
            (m10 * m21 - m11 * m20) * inv,
            (m01 * m20 - m00 * m21) * inv,
            (m00 * m11 - m01 * m10) * inv,
        ),
    )


M2_INV = _inverse(M2)
M1_INV = _inverse(M1)


def _apply(m: Matrix, v: Vec) -> Vec:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


SRGB_THRESHOLD = 0.0031308
SRGB_ENCODED_THRESHOLD = 12.92 * SRGB_THRESHOLD


def _eotf(v: float) -> float:
    """sRGB code value (0..1) to linear light, HF's sRGBInverseOETF."""
    v = min(max(v, 0.0), 1.0)
    return v / 12.92 if v <= SRGB_ENCODED_THRESHOLD else ((v + 0.055) / 1.055) ** 2.4


def _oetf(v: float) -> float:
    """Linear light to an sRGB code value (0..1), HF's sRGBOETF."""
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= SRGB_THRESHOLD else 1.055 * v ** (1.0 / 2.4) - 0.055


def _to_oklab(rgb: Vec) -> Vec:
    lms = _apply(M1, tuple(_eotf(c) for c in rgb))  # type: ignore[arg-type]
    return _apply(M2, tuple(math.cbrt(c) for c in lms))  # type: ignore[arg-type]


def _to_linear(lab: Vec) -> Vec:
    n = _apply(M2_INV, lab)
    return _apply(M1_INV, (n[0] * n[0] * n[0], n[1] * n[1] * n[1], n[2] * n[2] * n[2]))


def bake(stops: list[tuple[float, tuple[float, float, float]]]) -> bytes:
    wrapped = sorted(
        (
            (p - math.floor(p) if p - math.floor(p) < 1 else 0.0, i, c)
            for i, (p, c) in enumerate(stops)
        ),
        key=lambda s: (s[0], s[1]),
    )
    positions = [p for p, _, _ in wrapped]
    colors = [c for _, _, c in wrapped]
    labs = [_to_oklab(c) for c in colors]
    first = positions[0]
    out = bytearray()
    for i in range(256):
        t = i / 256
        if t in positions:  # exactly on a stop: the stop's own color, no round trip
            channels = [c * 255.0 for c in colors[positions.index(t)]]
        else:
            q = t + 1 if t < first else t
            k = len(positions) - 1
            while k > 0 and positions[k] > q:
                k -= 1
            start = positions[k]
            end = positions[k + 1] if k + 1 < len(positions) else first + 1
            f = (q - start) / (end - start)
            a, b = labs[k], labs[(k + 1) % len(labs)]
            s = 1 - f
            lab = (a[0] * s + b[0] * f, a[1] * s + b[1] * f, a[2] * s + b[2] * f)
            channels = [_oetf(c) * 255.0 for c in _to_linear(lab)]
            for v in channels:
                assert abs(v - math.floor(v) - 0.5) > 1e-9, f"entry {i} is on a rounding tie"
        out.extend(round(v) for v in channels)  # half to even
    return bytes(out)


def main() -> None:
    tables = [(name, hf, bake(stops)) for name, hf, stops in PALETTES]
    header = "generated by python/tools/gen_palettes.py -- normative data, do not edit"
    py = [f'"""Cyclic palette tables (spec/render.md "Cyclic palettes"):\n{header}.\n"""', ""]
    py.append("TABLES: dict[str, str] = {")
    for name, hf, data in tables:
        py.append(f"    # Heaton Fractal's {hf!r}")
        hexed = data.hex()
        py.append(f'    "{name}": (')
        for k in range(0, len(hexed), 64):
            py.append(f'        "{hexed[k : k + 64]}"')
        py.append("    ),")
    py.append("}")
    (ROOT / "python/src/heaton_life/render/_palette_tables.py").write_text("\n".join(py) + "\n")

    cs = [
        "namespace HeatonLife",
        "{",
        "    /// <summary>",
        '    /// Cyclic palette tables (spec/render.md "Cyclic palettes"): 256 RGB entries each, as',
        f"    /// hex. {header[0].upper()}{header[1:]}.",
        "    /// </summary>",
        "    internal static class PaletteTables",
        "    {",
        "        internal static readonly string[] Names = { "
        + ", ".join(f'"{name}"' for name, _, _ in tables)
        + " };",
        "",
        "        internal static readonly string[] Hex =",
        "        {",
    ]
    for name, hf, data in tables:
        hexed = data.hex()
        cs.append(f'            // {name}: Heaton Fractal\'s "{hf}"')
        chunks = [hexed[k : k + 64] for k in range(0, len(hexed), 64)]
        for j, chunk in enumerate(chunks):
            end = "," if j == len(chunks) - 1 else " +"
            cs.append(f'            "{chunk}"{end}')
    cs += ["        };", "    }", "}"]
    (ROOT / "dotnet/src/HeatonLife.Core/PaletteTables.cs").write_text("\n".join(cs) + "\n")
    for name, _, data in tables:
        print(name, data[:6].hex(), "...")


if __name__ == "__main__":
    main()
