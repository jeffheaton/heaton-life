"""Bivariate linear approximation inside T1 -- spec/deep-zoom.md "BLA".

A pixel near the reference follows it almost linearly: over l steps from reference
index m, dz_{m+l} ~ A dz_m + B dc while |dz| stays below a radius where the dropped
dz^2 terms are under float64 rounding. A table of (A, B, r) over power-of-two spans of
the reference orbit lets a pixel skip whole spans instead of stepping. Mandelbrot only,
opt-in (it changes counts on float64-chaotic pixels).

Everything here is plain float64 on real arrays -- never complex arrays or Python/NumPy
complex scalars, whose multiply may be fma-contracted -- so the C# port (BlaTable,
Perturbation.PerturbZ2Bla) matches it with plain doubles, expression for expression.
The BLA-off plain step inside the loop keeps the perturbation step's fma shape.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
from numpy.typing import NDArray

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int32]

STRIDE = 8  # steps folded into one level-0 entry
EPSILON = math.ldexp(1.0, -53)  # float64's unit roundoff: dz^2 dropped below rounding
LEVEL_CAP = 32
_CAP = math.ldexp(1.0, 960)  # coefficients this large are dead (never applied)
_TWO_400, _TWO_M400 = math.ldexp(1.0, 400), math.ldexp(1.0, -400)
_TWO_600, _TWO_M600 = math.ldexp(1.0, 600), math.ldexp(1.0, -600)


def mag(x: FloatArray, y: FloatArray) -> FloatArray:
    """|x + iy| with an exact power-of-two scale, so neither square leaves the normal
    range: a = max(|x|, |y|); s = 2^600 below 2^-400, 2^-600 above 2^400, else 1;
    sqrt((xs)^2 + (ys)^2) / s. 0, +inf and NaN come out as themselves."""
    a = np.maximum(np.abs(x), np.abs(y))
    small = a < _TWO_M400
    large = a > _TWO_400
    s = np.where(small, _TWO_600, np.where(large, _TWO_M600, 1.0))
    t = np.where(small, _TWO_M600, np.where(large, _TWO_600, 1.0))
    with np.errstate(over="ignore", invalid="ignore"):
        xs = x * s
        ys = y * s
        result: FloatArray = np.sqrt(xs * xs + ys * ys) * t
    return result


@dataclasses.dataclass(frozen=True)
class BlaLevel:
    """One level of the table: entry k skips S * 2^level steps from index k * S * 2^level."""

    ar: FloatArray
    ai: FloatArray
    br: FloatArray
    bi: FloatArray
    r: FloatArray  # validity radius; 0 = dead


@dataclasses.dataclass(frozen=True)
class BlaTable:
    """The BLA table of one reference orbit, escape radius and frame (dc bound)."""

    levels: tuple[BlaLevel, ...]
    extent: int  # k*: the steps tabulated are 0 .. extent - 1

    @property
    def live(self) -> bool:
        """Whether any entry can ever be taken (a parent is never live when its left
        child is dead, so level 0 decides)."""
        return bool(self.levels) and bool((self.levels[0].r > 0.0).any())


def ceil_power_of_two(x: float) -> float:
    """The least power of two >= x (x itself when it is one); 0, inf and NaN unchanged."""
    if not (x > 0.0) or math.isinf(x):
        return x
    mantissa, exponent = math.frexp(x)  # x = mantissa * 2^exponent, 0.5 <= mantissa < 1
    if mantissa == 0.5:
        return x
    return math.inf if exponent > 1023 else math.ldexp(1.0, exponent)


def frame_dc_bound(deltas: ComplexArray) -> float:
    """The frame's bound on |dc|: mag(max |dc.re|, max |dc.im|) over its pixel deltas,
    rounded up to a power of two -- conservative (a larger bound only shrinks radii), and
    one table then serves every frame within an octave of zoom."""
    if deltas.size == 0:
        return 0.0
    mr = np.max(np.abs(deltas.real))
    mi = np.max(np.abs(deltas.imag))
    return ceil_power_of_two(float(mag(np.array([mr]), np.array([mi]))[0]))


def _merge(
    r1: FloatArray,
    r2: FloatArray,
    ar: FloatArray,
    ai: FloatArray,
    br: FloatArray,
    bi: FloatArray,
    dc_bound: float,
) -> FloatArray:
    """The radius of x followed by y: num > 0 ? min(r1, num / |A_x|) : 0, with
    num = r2 - |B_x| dc_bound -- NaN-free as spelled (a NaN num is dead, a NaN
    quotient keeps r1, |A_x| = 0 gives +inf and keeps r1)."""
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        num = r2 - mag(br, bi) * dc_bound
        cand = num / mag(ar, ai)
    result: FloatArray = np.where(num > 0.0, np.where(cand < r1, cand, r1), 0.0)
    return result


def _level(
    ar: FloatArray, ai: FloatArray, br: FloatArray, bi: FloatArray, r: FloatArray
) -> BlaLevel:
    """Apply the dead rule: live only if r > 0 and |A|, |B| < 2^960."""
    alive = (r > 0.0) & (mag(ar, ai) < _CAP) & (mag(br, bi) < _CAP)
    return BlaLevel(ar, ai, br, bi, np.where(alive, r, 0.0))


def build_table(orbit: ComplexArray, escape_radius: float, dc_bound: float) -> BlaTable:
    """The table over the orbit's steps before it first escapes (spec/deep-zoom.md "BLA"):
    level 0 folds S single steps (A = 2Z, B = 1, r = eps |Z|) left to right, each level
    above merges pairs; a pure function of the float64 samples, R and the dc bound."""
    zr_all = np.ascontiguousarray(orbit.real)
    zi_all = np.ascontiguousarray(orbit.imag)
    r2 = escape_radius * escape_radius
    escaped = np.flatnonzero((zr_all[1:] * zr_all[1:] + zi_all[1:] * zi_all[1:]) > r2)
    extent = int(escaped[0]) + 1 if escaped.size else len(orbit) - 1
    n0 = max(extent, 0) // STRIDE
    if n0 == 0:
        return BlaTable((), extent)
    base = np.arange(n0) * STRIDE
    ar = np.ones(n0)
    ai = np.zeros(n0)
    br = np.zeros(n0)
    bi = np.zeros(n0)
    r = np.full(n0, np.inf)
    with np.errstate(over="ignore", invalid="ignore"):
        for j in range(STRIDE):
            zr = zr_all[base + j]
            zi = zi_all[base + j]
            sr = 2.0 * zr
            si = 2.0 * zi
            r = _merge(r, EPSILON * mag(zr, zi), ar, ai, br, bi, dc_bound)
            br, bi = (sr * br - si * bi) + 1.0, sr * bi + si * br
            ar, ai = sr * ar - si * ai, sr * ai + si * ar
    levels = [_level(ar, ai, br, bi, r)]
    while len(levels) < LEVEL_CAP and levels[-1].r.size >= 2:
        below = levels[-1]
        count = below.r.size // 2
        x = slice(0, 2 * count, 2)
        y = slice(1, 2 * count, 2)
        xar, xai, xbr, xbi = below.ar[x], below.ai[x], below.br[x], below.bi[x]
        yar, yai, ybr, ybi = below.ar[y], below.ai[y], below.br[y], below.bi[y]
        with np.errstate(over="ignore", invalid="ignore"):
            ar = yar * xar - yai * xai
            ai = yar * xai + yai * xar
            br = (yar * xbr - yai * xbi) + ybr
            bi = (yar * xbi + yai * xbr) + ybi
        r = _merge(below.r[x], below.r[y], xar, xai, xbr, xbi, dc_bound)
        levels.append(_level(ar, ai, br, bi, r))
    return BlaTable(tuple(levels), extent)


def table_words(table: BlaTable) -> FloatArray:
    """The table as one float64 array, level by level, each level's ar, ai, br, bi, r in
    turn -- the layout of a vector's bla_table output (spec/fractals.md)."""
    parts = [
        part for level in table.levels for part in (level.ar, level.ai, level.br, level.bi, level.r)
    ]
    words: FloatArray = np.concatenate(parts) if parts else np.zeros(0)
    return words


def perturb_z2_bla(
    orbit: ComplexArray,
    delta_c: ComplexArray,
    max_iter: int,
    escape_radius: float,
    table: BlaTable,
    scale: float | None = None,
) -> tuple[IntArray, ComplexArray, tuple[FloatArray, FloatArray] | None, IntArray]:
    """Mandelbrot perturbation with BLA skips (spec/deep-zoom.md "BLA"): each pass, a
    pixel at a stride-aligned index takes the longest live span whose radius exceeds
    |dz| (and that fits in max_iter), else one plain step. Returns (counts, final z,
    derivative at escape or None, BLA applications per pixel). With ``scale`` (the pixel
    scale) the distance estimate's derivative rides along: d' = A d + B ps on a skip."""
    n_pix = delta_c.size
    counts = np.full(n_pix, -1, dtype=np.int32)
    final = np.zeros(n_pix, dtype=np.complex128)
    applications = np.zeros(n_pix, dtype=np.int32)
    last = len(orbit) - 1
    dz = np.zeros(n_pix, dtype=np.complex128)
    dc = delta_c.copy()
    m = np.zeros(n_pix, dtype=np.int64)
    n = np.zeros(n_pix, dtype=np.int64)
    apps = np.zeros(n_pix, dtype=np.int32)
    idx = np.arange(n_pix)
    r2 = escape_radius * escape_radius
    levels = table.levels
    sizes = [level.r.size for level in levels]
    distance = scale is not None
    ps = scale if scale is not None else 0.0
    dr = np.zeros(n_pix) if distance else np.zeros(0)
    di = np.zeros(n_pix) if distance else np.zeros(0)
    final_dr = np.zeros(n_pix) if distance else np.zeros(0)
    final_di = np.zeros(n_pix) if distance else np.zeros(0)
    z = orbit[m] + dz  # the pre-square z of the first pass: fl(Z_0 + dz_0)
    while idx.size:
        chosen = np.full(idx.size, -1, dtype=np.int64)
        if levels:
            cand = np.flatnonzero((m % STRIDE == 0) & (m // STRIDE < sizes[0]))
            if cand.size:
                dm = mag(dz.real[cand], dz.imag[cand])
                mm = m[cand]
                nn = n[cand]
                alive = np.ones(cand.size, dtype=bool)
                for level_index, level in enumerate(levels):
                    span = STRIDE << level_index
                    alive &= (mm % span == 0) & (mm // span < sizes[level_index])
                    alive &= nn + span <= max_iter
                    slot = np.where(alive, mm // span, 0)
                    alive &= dm < level.r[slot]
                    if not alive.any():
                        break
                    chosen[cand[alive]] = level_index
        skip = chosen >= 0
        plain = np.flatnonzero(~skip)
        if distance:  # the derivative first: plain steps read the pre-square z
            zr, zi = z.real[plain], z.imag[plain]
            pdr, pdi = dr[plain], di[plain]
            dr[plain] = 2.0 * (zr * pdr - zi * pdi) + ps
            di[plain] = 2.0 * (zr * pdi + zi * pdr)
        if plain.size:
            mp = m[plain]
            dzp = dz[plain]
            dz[plain] = (2.0 * orbit[mp] + dzp) * dzp + dc[plain]
            m[plain] = np.minimum(mp + 1, last)
            n[plain] += 1
        for level_index in np.unique(chosen[skip]):
            span = STRIDE << int(level_index)
            level = levels[int(level_index)]
            sel = np.flatnonzero(chosen == level_index)
            e = m[sel] // span
            ar, ai, br, bi = level.ar[e], level.ai[e], level.br[e], level.bi[e]
            if distance:
                pdr, pdi = dr[sel], di[sel]
                dr[sel] = (ar * pdr - ai * pdi) + br * ps
                di[sel] = (ar * pdi + ai * pdr) + bi * ps
            zr, zi = dz.real[sel], dz.imag[sel]
            cr, ci = dc.real[sel], dc.imag[sel]
            new_re = (ar * zr - ai * zi) + (br * cr - bi * ci)
            new_im = (ar * zi + ai * zr) + (br * ci + bi * cr)
            dz.real[sel] = new_re
            dz.imag[sel] = new_im
            m[sel] += span
            n[sel] += span
            apps[sel] += 1
        z = orbit[m] + dz
        zabs2 = z.real * z.real + z.imag * z.imag
        escaped = zabs2 > r2
        done = escaped | (n >= max_iter)
        if done.any():
            hits = idx[escaped]
            counts[hits] = n[escaped]
            final[hits] = z[escaped]
            if distance:
                final_dr[hits] = dr[escaped]
                final_di[hits] = di[escaped]
            applications[idx[done]] = apps[done]
            keep = ~done
            dz, dc, m, n, apps, idx, z, zabs2 = (
                dz[keep],
                dc[keep],
                m[keep],
                n[keep],
                apps[keep],
                idx[keep],
                z[keep],
                zabs2[keep],
            )
            if distance:
                dr, di = dr[keep], di[keep]
            if not idx.size:
                break
        rebase = zabs2 < (dz.real * dz.real + dz.imag * dz.imag)
        if rebase.any():
            dz[rebase] = z[rebase]
            m[rebase] = 0
    return counts, final, ((final_dr, final_di) if distance else None), applications
