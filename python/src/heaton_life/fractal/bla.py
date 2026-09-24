"""Bivariate linear approximation inside T1 -- spec/deep-zoom.md "BLA".

A pixel near the reference follows it almost linearly: over l steps from reference
index m, dz_{m+l} ~ A dz_m + B dc while |dz| stays below a radius where the dropped
dz^2 terms are under float64 rounding. A table of (A, B, r) over power-of-two spans of
the reference orbit lets a pixel skip whole spans instead of stepping. Mandelbrot only,
opt-in (it changes counts on float64-chaotic pixels).

Everything here is plain float64 on real arrays -- never complex arrays or Python/NumPy
complex scalars, whose multiply may be fma-contracted -- so the C# port (BlaTable,
Perturbation.PerturbZ2Bla) matches it with plain doubles, expression for expression. The
coefficients are carried in double-double (two doubles, Dekker's fma-free products), each
entry storing the hi: chained float64 products drift about 100 ulps over the top levels.
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


# Double-double (spec/deep-zoom.md "BLA", "Arithmetic"): a value is hi + lo, two doubles;
# every operation below is plain IEEE float64 (no fma), so both ports agree.
_SPLIT = 134217729.0  # 2^27 + 1, Dekker's splitter
DD = tuple[FloatArray, FloatArray]  # (hi, lo)
CDD = tuple[DD, DD]  # (re, im)


def _two_sum(a: FloatArray, b: FloatArray) -> DD:
    s = a + b
    bb = s - a
    return s, (a - (s - bb)) + (b - bb)


def _quick_two_sum(a: FloatArray, b: FloatArray) -> DD:
    s = a + b
    return s, b - (s - a)


def _split(a: FloatArray) -> DD:
    t = _SPLIT * a
    hi = t - (t - a)
    return hi, a - hi


def _two_prod(a: FloatArray, b: FloatArray) -> DD:
    p = a * b
    ah, al = _split(a)
    bh, bl = _split(b)
    return p, (((ah * bh - p) + ah * bl) + al * bh) + al * bl


def _dd_mul(x: DD, y: DD) -> DD:
    p, e = _two_prod(x[0], y[0])
    return _quick_two_sum(p, e + (x[0] * y[1] + x[1] * y[0]))


def _dd_add(x: DD, y: DD) -> DD:
    s, e = _two_sum(x[0], y[0])
    return _quick_two_sum(s, e + (x[1] + y[1]))


def _dd_neg(x: DD) -> DD:
    return -x[0], -x[1]


def _cdd_mul(x: CDD, y: CDD) -> CDD:
    """(x.re y.re - x.im y.im, x.re y.im + x.im y.re) in double-double."""
    return (
        _dd_add(_dd_mul(x[0], y[0]), _dd_neg(_dd_mul(x[1], y[1]))),
        _dd_add(_dd_mul(x[0], y[1]), _dd_mul(x[1], y[0])),
    )


def _cdd_take(x: CDD, sel: slice) -> CDD:
    return (x[0][0][sel], x[0][1][sel]), (x[1][0][sel], x[1][1][sel])


def _fold_start(n: int) -> tuple[CDD, CDD]:
    """A level-0 fold's start: A = 1, B = 0."""
    zero = np.zeros(n)
    return ((np.ones(n), zero.copy()), (zero.copy(), zero.copy())), (
        (zero.copy(), zero.copy()),
        (zero.copy(), zero.copy()),
    )


def _fold_step(coeff_a: CDD, coeff_b: CDD, zr: FloatArray, zi: FloatArray) -> tuple[CDD, CDD]:
    """One step of a level-0 fold, a = 2Z exact: B <- (a B).re + 1, (a B).im; A <- a A."""
    zero = np.zeros(zr.size)
    step: CDD = ((2.0 * zr, zero), (2.0 * zi, zero.copy()))
    ab = _cdd_mul(step, coeff_b)
    return _cdd_mul(step, coeff_a), (_dd_add(ab[0], (np.ones(zr.size), zero.copy())), ab[1])


def _merge_coefficients(xa: CDD, xb: CDD, ya: CDD, yb: CDD) -> tuple[CDD, CDD]:
    """x followed by y: A = A_y A_x, B = A_y B_x + B_y, on the children's pairs."""
    yxb = _cdd_mul(ya, xb)
    return _cdd_mul(ya, xa), (_dd_add(yxb[0], yb[0]), _dd_add(yxb[1], yb[1]))


def _hi(c: CDD) -> tuple[FloatArray, FloatArray]:
    return c[0][0], c[1][0]


def build_table(orbit: ComplexArray, escape_radius: float, dc_bound: float) -> BlaTable:
    """The table over the orbit's steps before it first escapes (spec/deep-zoom.md "BLA"):
    level 0 folds S single steps (A = 2Z, B = 1, r = eps |Z|) left to right, each level
    above merges pairs; the coefficients carried in double-double and stored as each
    component's hi, the radii in float64 from those stored values. A pure function of the
    float64 samples, R and the dc bound."""
    zr_all = np.ascontiguousarray(orbit.real)
    zi_all = np.ascontiguousarray(orbit.imag)
    r2 = escape_radius * escape_radius
    escaped = np.flatnonzero((zr_all[1:] * zr_all[1:] + zi_all[1:] * zi_all[1:]) > r2)
    extent = int(escaped[0]) + 1 if escaped.size else len(orbit) - 1
    n0 = max(extent, 0) // STRIDE
    if n0 == 0:
        return BlaTable((), extent)
    base = np.arange(n0) * STRIDE
    coeff_a, coeff_b = _fold_start(n0)
    r = np.full(n0, np.inf)
    with np.errstate(over="ignore", invalid="ignore"):
        for j in range(STRIDE):
            zr = zr_all[base + j]
            zi = zi_all[base + j]
            r = _merge(r, EPSILON * mag(zr, zi), *_hi(coeff_a), *_hi(coeff_b), dc_bound)
            coeff_a, coeff_b = _fold_step(coeff_a, coeff_b, zr, zi)
    pairs = [(coeff_a, coeff_b)]
    levels = [_level(*_hi(coeff_a), *_hi(coeff_b), r)]
    while len(levels) < LEVEL_CAP and levels[-1].r.size >= 2:
        below = levels[-1]
        below_a, below_b = pairs[-1]
        count = below.r.size // 2
        x = slice(0, 2 * count, 2)
        y = slice(1, 2 * count, 2)
        with np.errstate(over="ignore", invalid="ignore"):
            coeff_a, coeff_b = _merge_coefficients(
                _cdd_take(below_a, x),
                _cdd_take(below_b, x),
                _cdd_take(below_a, y),
                _cdd_take(below_b, y),
            )
        r = _merge(
            below.r[x], below.r[y], below.ar[x], below.ai[x], below.br[x], below.bi[x], dc_bound
        )
        pairs.append((coeff_a, coeff_b))
        levels.append(_level(*_hi(coeff_a), *_hi(coeff_b), r))
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


# --- T2 (spec/deep-zoom.md "BLA at T2") ------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BlaLevelX:
    """One level of a T2 table: T1's coefficients, the radius in floatexp (rm = 0: dead)."""

    ar: FloatArray
    ai: FloatArray
    br: FloatArray
    bi: FloatArray
    rm: FloatArray
    re: NDArray[np.int64]


@dataclasses.dataclass(frozen=True)
class BlaTableX:
    """The T2 BLA table of one reference orbit, escape radius and frame (dc bound 2^k)."""

    levels: tuple[BlaLevelX, ...]
    extent: int

    @property
    def live(self) -> bool:
        return bool(self.levels) and bool((self.levels[0].rm > 0.0).any())


def frame_dc_bound_exponent(
    dc_rm: FloatArray, dc_re: NDArray[np.int64], dc_im: FloatArray, dc_ie: NDArray[np.int64]
) -> int | None:
    """The T2 frame's bound on |dc| as 2^k: mag(max |dc.re|, max |dc.im|) over the frame's
    floatexp pixel deltas, rounded up to a power of two; None when every delta is zero.
    The magnitude is T1's mag of the pair scaled by 2^-E (E the larger exponent of the
    nonzero maxima), times 2^E."""
    from heaton_life.core import floatexp as fx

    def largest(m: FloatArray, e: NDArray[np.int64]) -> fx.X:
        nonzero = m != 0.0
        if not nonzero.any():
            return fx.ZERO
        top = int(e[nonzero].max())
        at = nonzero & (e == top)
        return float(np.abs(m[at]).max()), top

    mr = largest(dc_rm, dc_re)
    mi = largest(dc_im, dc_ie)
    if mr[0] == 0.0 and mi[0] == 0.0:
        return None
    exponent = mr[1] if mi[0] == 0.0 else mi[1] if mr[0] == 0.0 else max(mr[1], mi[1])
    s = fx.scaled(mr, exponent)
    t = fx.scaled(mi, exponent)
    value = float(mag(np.array([s]), np.array([t]))[0])  # in [1, 2 sqrt 2]
    mantissa, k = math.frexp(value)
    return exponent + (k - 1 if mantissa == 0.5 else k)


def _merge_x(
    r1m: FloatArray,
    r1e: NDArray[np.int64],
    r1_inf: NDArray[np.bool_],
    r2m: FloatArray,
    r2e: NDArray[np.int64],
    ar: FloatArray,
    ai: FloatArray,
    br: FloatArray,
    bi: FloatArray,
    dc_exponent: int | None,
) -> tuple[FloatArray, NDArray[np.int64], NDArray[np.bool_]]:
    """T1's merge in floatexp: num = r2 - |B_x| 2^k; num > 0 ? min(r1, num / |A_x|) : 0,
    |A_x| = 0 keeping r1; a magnitude that is not finite gives 0 (such an entry is dead
    anyway: its own coefficients cannot be finite)."""
    from heaton_life.core import floatexp as fx

    mag_a = mag(ar, ai)
    mag_b = mag(br, bi)
    finite = np.isfinite(mag_a) & np.isfinite(mag_b)
    n = r2m.size
    if dc_exponent is None:
        tm, te = np.zeros(n), np.zeros(n, dtype=np.int64)
    else:
        tm, te = fx.vnormalize(np.where(finite, mag_b, 0.0), np.full(n, dc_exponent, np.int64))
    nm, ne = fx.vadd(r2m, r2e, -tm, te)
    positive = finite & (nm > 0.0)
    a_zero = mag_a == 0.0
    usable = positive & ~a_zero
    am, ae = fx.vnormalize(np.where(usable, mag_a, 1.0), np.zeros(n, dtype=np.int64))
    with np.errstate(invalid="ignore", divide="ignore"):
        qm, qe = fx.vdiv(np.where(usable, nm, 0.0), np.where(usable, ne, 0), am, ae)
    less = r1_inf | (fx.vcompare_magnitude2(qm, qe, r1m, r1e) < 0)
    take = usable & less
    out_m = np.where(positive, np.where(take, qm, r1m), 0.0)
    out_e = np.where(positive, np.where(take, qe, r1e), 0).astype(np.int64)
    out_inf = positive & ~take & r1_inf
    return out_m, out_e, out_inf


def _level_x(
    ar: FloatArray,
    ai: FloatArray,
    br: FloatArray,
    bi: FloatArray,
    rm: FloatArray,
    re: NDArray[np.int64],
    r_inf: NDArray[np.bool_],
) -> BlaLevelX:
    alive = (rm > 0.0) & ~r_inf & (mag(ar, ai) < _CAP) & (mag(br, bi) < _CAP)
    return BlaLevelX(
        ar, ai, br, bi, np.where(alive, rm, 0.0), np.where(alive, re, 0).astype(np.int64)
    )


def build_table_t2(
    samples: ComplexArray, small: NDArray[np.bool_], escape_radius: float, dc_exponent: int | None
) -> BlaTableX:
    """The T2 table (spec/deep-zoom.md "BLA at T2"): T1's coefficients (double-double, each
    entry storing the hi of each component) and T1's radii in floatexp with the dc bound
    2^dc_exponent (None: zero), from those stored values. A step at a
    small index (``small``: the orbit's small table) has radius 0, so no span containing
    one is ever taken: its float64 sample may have lost bits."""
    from heaton_life.core import floatexp as fx

    zr_all = np.ascontiguousarray(samples.real)
    zi_all = np.ascontiguousarray(samples.imag)
    r2 = escape_radius * escape_radius
    with np.errstate(over="ignore", invalid="ignore"):
        escaped = np.flatnonzero((zr_all[1:] * zr_all[1:] + zi_all[1:] * zi_all[1:]) > r2)
    extent = int(escaped[0]) + 1 if escaped.size else len(samples) - 1
    n0 = max(extent, 0) // STRIDE
    if n0 == 0:
        return BlaTableX((), extent)
    base = np.arange(n0) * STRIDE
    coeff_a, coeff_b = _fold_start(n0)
    rm = np.zeros(n0)
    re = np.zeros(n0, dtype=np.int64)
    r_inf = np.ones(n0, dtype=bool)
    with np.errstate(over="ignore", invalid="ignore"):
        for j in range(STRIDE):
            zr = zr_all[base + j]
            zi = zi_all[base + j]
            sm, se = fx.vnormalize(
                np.where(small[base + j], 0.0, mag(zr, zi)), np.full(n0, -53, dtype=np.int64)
            )  # eps |Z|, exact
            rm, re, r_inf = _merge_x(
                rm, re, r_inf, sm, se, *_hi(coeff_a), *_hi(coeff_b), dc_exponent
            )
            coeff_a, coeff_b = _fold_step(coeff_a, coeff_b, zr, zi)
    pairs = [(coeff_a, coeff_b)]
    levels = [_level_x(*_hi(coeff_a), *_hi(coeff_b), rm, re, r_inf)]
    while len(levels) < LEVEL_CAP and levels[-1].rm.size >= 2:
        below = levels[-1]
        below_a, below_b = pairs[-1]
        count = below.rm.size // 2
        x = slice(0, 2 * count, 2)
        y = slice(1, 2 * count, 2)
        with np.errstate(over="ignore", invalid="ignore"):
            coeff_a, coeff_b = _merge_coefficients(
                _cdd_take(below_a, x),
                _cdd_take(below_b, x),
                _cdd_take(below_a, y),
                _cdd_take(below_b, y),
            )
        rm, re, r_inf = _merge_x(
            below.rm[x],
            below.re[x],
            np.zeros(count, dtype=bool),
            below.rm[y],
            below.re[y],
            below.ar[x],
            below.ai[x],
            below.br[x],
            below.bi[x],
            dc_exponent,
        )
        pairs.append((coeff_a, coeff_b))
        levels.append(_level_x(*_hi(coeff_a), *_hi(coeff_b), rm, re, r_inf))
    return BlaTableX(tuple(levels), extent)


def table_words_x(table: BlaTableX) -> FloatArray:
    """The T2 table as one float64 array, level by level, each level's ar, ai, br, bi, the
    radii's mantissas and their exponents (exact as float64) in turn -- the layout of a
    vector's bla_table_x output (spec/fractals.md)."""
    parts = [
        part
        for level in table.levels
        for part in (level.ar, level.ai, level.br, level.bi, level.rm, level.re.astype(np.float64))
    ]
    words: FloatArray = np.concatenate(parts) if parts else np.zeros(0)
    return words
