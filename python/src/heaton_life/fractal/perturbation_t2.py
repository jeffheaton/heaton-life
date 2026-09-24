"""T2 perturbation past zoom 1e290 (spec/deep-zoom.md "T2").

Every pixel carries its delta as a float64 pair w and an integer exponent E, delta =
w * 2^E, renormalized by exact powers of two when max(|w|) leaves [2^-64, 2^64]. A step at
a *normal* reference index (|Z| >= 2^-400) is T1's shape on w in plain real float64
operations: t = 2Z + delta_d, w' = t * w + delta_c / 2^E, where delta_d is delta as a
double (zero once E < -1022, far below any ulp of 2Z). At a *small* index (Z = 0 or
|Z| < 2^-400, taken from the orbit's floatexp small table) the step, and the escape and
rebase tests that land there, run in floatexp (core.floatexp) per component. Every
scaling is by an exact normal power of two and no operation is fused, so the C# port
reproduces every count and every bit.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
from numpy.typing import NDArray

from heaton_life.core import floatexp as fx
from heaton_life.core.bignum import OrbitX
from heaton_life.fractal.bla import STRIDE, BlaTableX, mag

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

BAND = 64  # renormalize when max(|w|) leaves [2^-BAND, 2^BAND]
DC_GAP = 960  # a fast step needs delta_c's exponent at most this far above E
LOW = fx.pow2(-BAND)
HIGH = fx.pow2(BAND)


@dataclasses.dataclass
class XPair:
    """A complex floatexp array: each component's mantissa and exponent."""

    rm: FloatArray
    re: IntArray
    im: FloatArray
    ie: IntArray

    def take(self, sel: Any) -> XPair:
        return XPair(self.rm[sel], self.re[sel], self.im[sel], self.ie[sel])

    def put(self, sel: Any, other: XPair) -> None:
        self.rm[sel] = other.rm
        self.re[sel] = other.re
        self.im[sel] = other.im
        self.ie[sel] = other.ie

    @staticmethod
    def zeros(n: int) -> XPair:
        z = np.zeros(n, dtype=np.float64)
        e = np.zeros(n, dtype=np.int64)
        return XPair(z, e, z.copy(), e.copy())


def _x_of_scaled(w: FloatArray, exponent: IntArray) -> tuple[FloatArray, IntArray]:
    """w * 2^exponent as floatexp (exact)."""
    return fx.vnormalize(w, exponent)


def _scaled_of_x(m: FloatArray, e: IntArray, exponent: IntArray) -> FloatArray:
    """(m, e) / 2^exponent as a double (to_double's rounding)."""
    return fx.vto_double(m, e - exponent)


def _pow2_clipped(exponent: IntArray) -> FloatArray:
    return fx.vpow2(np.clip(exponent, fx.MIN_NORMAL_EXP, fx.MAX_EXP))


def _delta_double(
    wr: FloatArray, wi: FloatArray, exponent: IntArray
) -> tuple[FloatArray, FloatArray]:
    """delta as a double pair: w * 2^E for E >= -1022 (one multiply by an exact normal power
    of two), else 0."""
    live = exponent >= fx.MIN_NORMAL_EXP
    p = _pow2_clipped(exponent)
    with np.errstate(over="ignore", under="ignore"):
        return np.where(live, wr * p, 0.0), np.where(live, wi * p, 0.0)


def _split_pair(x: XPair, keep: IntArray) -> tuple[FloatArray, FloatArray, IntArray]:
    """(w, E) from a complex floatexp: E = the larger exponent of the nonzero parts (``keep``
    where both are zero), w = each part / 2^E."""
    r_zero = x.rm == 0.0
    i_zero = x.im == 0.0
    exponent = np.where(
        r_zero & i_zero,
        keep,
        np.where(r_zero, x.ie, np.where(i_zero, x.re, np.maximum(x.re, x.ie))),
    ).astype(np.int64)
    wr = np.where(r_zero, 0.0, _scaled_of_x(x.rm, x.re, exponent))
    wi = np.where(i_zero, 0.0, _scaled_of_x(x.im, x.ie, exponent))
    return wr, wi, exponent


def _renormalize(wr: FloatArray, wi: FloatArray, exponent: IntArray) -> BoolArray:
    """In place: when max(|w|) (nonzero) leaves [2^-64, 2^64], scale it into [1, 2) by an
    exact power of two and move the exponent. Returns which lanes moved."""
    big = np.maximum(np.abs(wr), np.abs(wi))
    out: BoolArray = (big != 0.0) & ((big < LOW) | (big > HIGH))
    if not out.any():
        return out
    k = (np.frexp(big[out])[1].astype(np.int64)) - 1  # binade of max(|w|)
    # 2^-k in one multiply while it is normal; below the normal range (k > 1022 never
    # happens: |w| <= 4 * 2^64 * |w| + ...), above it (k < -1022: a subnormal max) in two
    # exact multiplies, since the result lands in [1, 2).
    first = np.clip(-k, fx.MIN_NORMAL_EXP, fx.MAX_EXP)
    rest = -k - first
    p1 = fx.vpow2(first)
    p2 = fx.vpow2(rest)
    with np.errstate(over="ignore", under="ignore"):
        wr[out] = (wr[out] * p1) * p2
        wi[out] = (wi[out] * p1) * p2
    exponent[out] = exponent[out] + k
    # Past 2^-(2^31) the value is zero (floatexp.EXP_FLOOR), so exponents never overflow.
    gone = out & (exponent < fx.EXP_FLOOR)
    wr[gone] = 0.0
    wi[gone] = 0.0
    return out


def _gap_bad(c: XPair, exponent: IntArray) -> BoolArray:
    """A nonzero delta_c component more than DC_GAP binades above 2^E."""
    bad_r = (c.rm != 0.0) & (c.re - exponent > DC_GAP)
    bad_i = (c.im != 0.0) & (c.ie - exponent > DC_GAP)
    bad: BoolArray = bad_r | bad_i
    return bad


def _cmul(a: XPair, b: XPair) -> XPair:
    """(a.r b.r - a.i b.i, a.r b.i + a.i b.r) in floatexp, per component."""
    rr = fx.vmul(a.rm, a.re, b.rm, b.re)
    ii = fx.vmul(a.im, a.ie, b.im, b.ie)
    ri = fx.vmul(a.rm, a.re, b.im, b.ie)
    ir = fx.vmul(a.im, a.ie, b.rm, b.re)
    real = fx.vadd(rr[0], rr[1], -ii[0], ii[1])
    imag = fx.vadd(ri[0], ri[1], ir[0], ir[1])
    return XPair(real[0], real[1], imag[0], imag[1])


def _cadd(a: XPair, b: XPair) -> XPair:
    real = fx.vadd(a.rm, a.re, b.rm, b.re)
    imag = fx.vadd(a.im, a.ie, b.im, b.ie)
    return XPair(real[0], real[1], imag[0], imag[1])


def _twice(a: XPair) -> XPair:
    return XPair(a.rm, np.where(a.rm == 0.0, 0, a.re + 1), a.im, np.where(a.im == 0.0, 0, a.ie + 1))


def _abs2(a: XPair) -> tuple[FloatArray, IntArray]:
    rr = fx.vmul(a.rm, a.re, a.rm, a.re)
    ii = fx.vmul(a.im, a.ie, a.im, a.ie)
    return fx.vadd(rr[0], rr[1], ii[0], ii[1])


def _x_of_pair(wr: FloatArray, wi: FloatArray, exponent: IntArray) -> XPair:
    r = _x_of_scaled(wr, exponent)
    i = _x_of_scaled(wi, exponent)
    return XPair(r[0], r[1], i[0], i[1])


@dataclasses.dataclass
class _Refs:
    """Both orbits in one table: double samples, the small flag, and each small index's
    floatexp components (by position)."""

    zr: FloatArray
    zi: FloatArray
    small: BoolArray
    x: XPair  # indexed by absolute position; meaningful where small

    @staticmethod
    def build(orbits: list[OrbitX]) -> _Refs:
        samples = np.concatenate([o.samples for o in orbits])
        n = len(samples)
        small = np.zeros(n, dtype=bool)
        x = XPair.zeros(n)
        start = 0
        for o in orbits:
            positions = o.small.index + start
            small[positions] = True
            x.rm[positions] = o.small.re_m
            x.re[positions] = o.small.re_e
            x.im[positions] = o.small.im_m
            x.ie[positions] = o.small.im_e
            start += len(o.samples)
        return _Refs(samples.real.copy(), samples.imag.copy(), small, x)

    def z_x(self, m: IntArray) -> XPair:
        """Z[m] in floatexp: the small table where small, else the double sample exactly."""
        small = self.small[m]
        rr = fx.vnormalize(self.zr[m], np.zeros(m.size, dtype=np.int64))
        ii = fx.vnormalize(self.zi[m], np.zeros(m.size, dtype=np.int64))
        return XPair(
            np.where(small, self.x.rm[m], rr[0]),
            np.where(small, self.x.re[m], rr[1]),
            np.where(small, self.x.im[m], ii[0]),
            np.where(small, self.x.ie[m], ii[1]),
        )


@dataclasses.dataclass
class T2Result:
    counts: NDArray[np.int32]
    final: NDArray[np.complex128]
    # The distance derivative at escape, d = (dr, di) * 2^exponent (zeros when not asked).
    dr: FloatArray
    di: FloatArray
    d_exponent: IntArray
    applications: NDArray[np.int32]  # BLA skips per pixel (zeros without a table)


def perturb_t2(
    orbit: OrbitX,
    delta0: XPair | None,
    delta_c: XPair | None,
    max_iter: int,
    escape_radius: float,
    rebase_orbit: OrbitX | None = None,
    derivative: tuple[XPair, fx.X | None] | None = None,
    stats: dict[str, int] | None = None,
    table: BlaTableX | None = None,
) -> T2Result:
    """T2 escape counts for z^2 + c maps (Mandelbrot: delta0 None, i.e. 0; Julia:
    delta_c None, i.e. 0, and ``rebase_orbit`` the critical orbit). ``derivative`` =
    (d0, add): the distance derivative's start and its per-step addition (Mandelbrot: 0
    and ps; Julia: ps and None), each in floatexp. ``stats``, when given, counts each rare
    path taken (tests: every path must be exercised by some vector). ``table``: BLA at T2
    (spec/deep-zoom.md "BLA at T2"; Mandelbrot only, so no ``rebase_orbit``): at a
    stride-aligned index a pixel takes the longest live span whose floatexp radius
    exceeds |delta|, the skip itself in floatexp."""

    def count(name: str, mask: Any) -> None:
        if stats is not None:
            stats[name] = stats.get(name, 0) + int(np.count_nonzero(mask))

    counting = stats is not None

    refs = _Refs.build([orbit] if rebase_orbit is None else [orbit, rebase_orbit])
    rebase_start = 0 if rebase_orbit is None else len(orbit.samples)
    rebase_last = len(refs.zr) - 1
    n = (delta0 if delta0 is not None else delta_c).rm.size  # type: ignore[union-attr]
    counts = np.full(n, -1, dtype=np.int32)
    final = np.zeros(n, dtype=np.complex128)
    out_dr = np.zeros(n, dtype=np.float64)
    out_di = np.zeros(n, dtype=np.float64)
    out_de = np.zeros(n, dtype=np.int64)
    out_apps = np.zeros(n, dtype=np.int32)
    r2 = escape_radius * escape_radius
    r2x = fx.from_double(r2)

    dc = delta_c if delta_c is not None else XPair.zeros(n)
    has_dc = delta_c is not None
    # A zero delta0 (always, for Mandelbrot) starts at E = the larger exponent of delta_c's
    # nonzero parts (0 if both are zero), lane by lane; no render output depends on it,
    # since Mandelbrot's index 0 is small and its first step slow.
    dc_exponent = _split_pair(dc, np.zeros(n, dtype=np.int64))[2]
    if delta0 is None:
        wr = np.zeros(n)
        wi = np.zeros(n)
        exponent = dc_exponent
    else:
        wr, wi, exponent = _split_pair(delta0, dc_exponent)
    wr = np.array(wr, dtype=np.float64)
    wi = np.array(wi, dtype=np.float64)
    exponent = np.array(exponent, dtype=np.int64)

    def dc_scaled(sel_dc: XPair, e: IntArray) -> tuple[FloatArray, FloatArray, BoolArray]:
        if not has_dc:
            z = np.zeros(e.size)
            return z, z.copy(), np.zeros(e.size, dtype=bool)
        with np.errstate(over="ignore"):
            sr = np.where(sel_dc.rm == 0.0, 0.0, _scaled_of_x(sel_dc.rm, sel_dc.re, e))
            si = np.where(sel_dc.im == 0.0, 0.0, _scaled_of_x(sel_dc.im, sel_dc.ie, e))
        return sr, si, _gap_bad(sel_dc, e)

    dcs_r, dcs_i, dc_bad = dc_scaled(dc, exponent)
    m = np.zeros(n, dtype=np.int64)
    last = np.full(n, len(orbit.samples) - 1, dtype=np.int64)
    idx = np.arange(n)
    steps = np.zeros(n, dtype=np.int64)  # iterations done: the count at escape
    apps = np.zeros(n, dtype=np.int32)
    levels = () if table is None or not table.live else table.levels
    assert not levels or rebase_orbit is None, "BLA at T2 is Mandelbrot's (one orbit)"
    sizes = [level.rm.size for level in levels]

    # The distance derivative: its own scaled pair (dw, dE) and add/2^dE.
    track = derivative is not None
    if track:
        assert derivative is not None
        d0, add = derivative
        dwr, dwi, d_exp = _split_pair(d0, np.full(n, 0 if add is None else add[1], np.int64))
        dwr = np.array(dwr, dtype=np.float64)
        dwi = np.array(dwi, dtype=np.float64)
        d_exp = np.array(d_exp, dtype=np.int64)
        add_x = add
        # The pre-step z: fl(Z_0 + delta_0), by the landing rule at index 0.
        z_small, zdr, zdi, zx = _landing_z(refs, m, wr, wi, exponent)

    def add_scaled(e: IntArray) -> tuple[FloatArray, BoolArray]:
        if add_x is None:
            return np.zeros(e.size), np.zeros(e.size, dtype=bool)
        am, ae = add_x
        s = np.where(am == 0.0, 0.0, _scaled_of_x(np.full(e.size, am), np.full(e.size, ae), e))
        bad = (am != 0.0) & (ae - e > DC_GAP)
        return s, bad

    if track:
        adds, add_bad = add_scaled(d_exp)

    skip: Any
    plain: Any  # a mask, or a plain bool when no lane skips this pass
    while idx.size and max_iter > 0:  # max_iter 0: no step, every count -1
        # --- BLA: the longest live span from here whose radius exceeds |delta| -----------
        any_skip = False
        if levels:
            chosen = np.full(idx.size, -1, dtype=np.int64)
            cand = np.flatnonzero((m % STRIDE == 0) & (m // STRIDE < sizes[0]))
            if cand.size:
                dm, de = fx.vnormalize(mag(wr[cand], wi[cand]), exponent[cand])  # |delta|
                mm = m[cand]
                nn = steps[cand]
                alive = np.ones(cand.size, dtype=bool)
                for level_index, level in enumerate(levels):
                    span = STRIDE << level_index
                    alive &= (mm % span == 0) & (mm // span < sizes[level_index])
                    alive &= nn + span <= max_iter
                    slot = np.where(alive, mm // span, 0)
                    alive &= (level.rm[slot] > 0.0) & (
                        fx.vcompare_magnitude2(dm, de, level.rm[slot], level.re[slot]) < 0
                    )
                    if not alive.any():
                        break
                    chosen[cand[alive]] = level_index
            skip = chosen >= 0
            any_skip = bool(skip.any())
        if any_skip:
            # A skip, from the pre-step state, in floatexp per component:
            # delta' = A delta + B delta_c, d' = A d + B ps (fractals.md "Distance estimate").
            ssel = np.flatnonzero(skip)
            sar = np.empty(ssel.size)
            sai = np.empty(ssel.size)
            sbr = np.empty(ssel.size)
            sbi = np.empty(ssel.size)
            for level_index in np.unique(chosen[ssel]):
                at = chosen[ssel] == level_index
                level = levels[int(level_index)]
                e = m[ssel][at] // (STRIDE << int(level_index))
                sar[at], sai[at], sbr[at], sbi[at] = (
                    level.ar[e],
                    level.ai[e],
                    level.br[e],
                    level.bi[e],
                )
            coeff_a = _x_of_pair(sar, sai, np.zeros(ssel.size, dtype=np.int64))
            coeff_b = _x_of_pair(sbr, sbi, np.zeros(ssel.size, dtype=np.int64))
            delta = _x_of_pair(wr[ssel], wi[ssel], exponent[ssel])
            nxt = _cadd(_cmul(coeff_a, delta), _cmul(coeff_b, dc.take(ssel)))
            skip_wr, skip_wi, skip_e = _split_pair(nxt, exponent[ssel])
            if track:
                d = _x_of_pair(dwr[ssel], dwi[ssel], d_exp[ssel])
                prod = _cmul(coeff_a, d)
                if add_x is not None:
                    am, ae = add_x
                    full_m = np.full(ssel.size, am)
                    full_e = np.full(ssel.size, ae, dtype=np.int64)
                    br_x = fx.vmul(coeff_b.rm, coeff_b.re, full_m, full_e)
                    bi_x = fx.vmul(coeff_b.im, coeff_b.ie, full_m, full_e)
                    real = fx.vadd(prod.rm, prod.re, *br_x)
                    imag = fx.vadd(prod.im, prod.ie, *bi_x)
                    prod = XPair(real[0], real[1], imag[0], imag[1])
                skip_dwr, skip_dwi, skip_de = _split_pair(prod, d_exp[ssel])
            count("bla_skip", skip)
            plain = ~skip
        else:
            skip = False
            plain = True

        if track:
            # d' = 2 z d + add, from the pre-step z (fractals.md "Distance estimate").
            slow_d = z_small | add_bad
            if counting:
                count("d_slow_small", z_small & plain)
                count("d_slow_gap", add_bad & ~z_small & plain)
            with np.errstate(over="ignore", invalid="ignore"):
                tr = 2.0 * (zdr * dwr - zdi * dwi) + adds
                ti = 2.0 * (zdr * dwi + zdi * dwr)
            if slow_d.any():
                sel = np.flatnonzero(slow_d)
                d = _x_of_pair(dwr[sel], dwi[sel], d_exp[sel])
                zsel = zx.take(sel)
                zsel_fast = _x_of_pair(zdr[sel], zdi[sel], np.zeros(sel.size, dtype=np.int64))
                zsel = XPair(
                    np.where(z_small[sel], zsel.rm, zsel_fast.rm),
                    np.where(z_small[sel], zsel.re, zsel_fast.re),
                    np.where(z_small[sel], zsel.im, zsel_fast.im),
                    np.where(z_small[sel], zsel.ie, zsel_fast.ie),
                )
                prod = _twice(_cmul(zsel, d))
                if add_x is not None:
                    am, ae = add_x
                    prod = _cadd(
                        prod,
                        XPair(
                            np.full(sel.size, am),
                            np.full(sel.size, ae, dtype=np.int64),
                            np.zeros(sel.size),
                            np.zeros(sel.size, dtype=np.int64),
                        ),
                    )
                nr, ni, ne = _split_pair(prod, d_exp[sel])
                tr[sel], ti[sel] = nr, ni
                d_exp[sel] = ne
            dwr, dwi = tr, ti
            if any_skip:
                dwr[ssel], dwi[ssel], d_exp[ssel] = skip_dwr, skip_dwi, skip_de
            moved = _renormalize(dwr, dwi, d_exp)
            if slow_d.any() or moved.any() or any_skip:
                adds, add_bad = add_scaled(d_exp)

        # --- the step ------------------------------------------------------------------
        zr_m = refs.zr[m]
        zi_m = refs.zi[m]
        slow = refs.small[m] | dc_bad
        if counting:
            count("slow_small", refs.small[m] & plain)
            count("slow_gap", dc_bad & ~refs.small[m] & plain)
        ddr, ddi = _delta_double(wr, wi, exponent)
        with np.errstate(over="ignore", invalid="ignore"):
            tr = 2.0 * zr_m + ddr
            ti = 2.0 * zi_m + ddi
            nwr = (tr * wr - ti * wi) + dcs_r
            nwi = (tr * wi + ti * wr) + dcs_i
        changed = np.zeros(idx.size, dtype=bool)
        if slow.any():
            sel = np.flatnonzero(slow)
            z = refs.z_x(m[sel])
            delta = _x_of_pair(wr[sel], wi[sel], exponent[sel])
            t = _cadd(_twice(z), delta)
            nxt = _cadd(_cmul(t, delta), dc.take(sel))
            if counting:
                count(
                    "floor",
                    (nxt.rm == 0.0)
                    & (nxt.im == 0.0)
                    & ((delta.rm != 0.0) | (delta.im != 0.0))
                    & (plain[sel] if any_skip else True),
                )
            sr, si, se = _split_pair(nxt, exponent[sel])
            nwr[sel], nwi[sel] = sr, si
            exponent[sel] = se
            changed[sel] = True
        wr, wi = nwr, nwi
        if any_skip:
            wr[ssel], wi[ssel], exponent[ssel] = skip_wr, skip_wi, skip_e
            changed[ssel] = True
            m = np.where(skip, m + (STRIDE << np.maximum(chosen, 0)), np.minimum(m + 1, last))
            steps = steps + np.where(skip, STRIDE << np.maximum(chosen, 0), 1)
            apps = apps + skip.astype(np.int32)
        else:
            m = np.minimum(m + 1, last)
            steps = steps + 1
        moved = _renormalize(wr, wi, exponent)
        if counting:
            count("renormalize", moved)
            count("floor", moved & (wr == 0.0) & (wi == 0.0))
        changed |= moved
        if changed.any():
            sel = np.flatnonzero(changed)
            a, b, c = dc_scaled(dc.take(sel), exponent[sel])
            dcs_r[sel], dcs_i[sel], dc_bad[sel] = a, b, c

        # --- landing: escape, then rebase ------------------------------------------------
        small_now, zdr, zdi, zx = _landing_z(refs, m, wr, wi, exponent)
        ddr, ddi = _delta_double(wr, wi, exponent)
        with np.errstate(over="ignore", invalid="ignore"):
            zabs2 = zdr * zdr + zdi * zdi
            escaped = zabs2 > r2
            rebase = zabs2 < ddr * ddr + ddi * ddi
        if small_now.any():
            sel = np.flatnonzero(small_now)
            zsel = zx.take(sel)
            za = _abs2(zsel)
            da = _abs2(_x_of_pair(wr[sel], wi[sel], exponent[sel]))
            esc = (
                fx.vcompare_magnitude2(
                    za[0],
                    za[1],
                    np.full(sel.size, r2x[0]),
                    np.full(sel.size, r2x[1], dtype=np.int64),
                )
                > 0
            )
            reb = fx.vcompare_magnitude2(za[0], za[1], da[0], da[1]) < 0
            escaped[sel] = esc
            rebase[sel] = reb
        rebase &= ~escaped
        count("escape_small", escaped & small_now)
        if counting and any_skip:
            count("bla_skip_escape", escaped & skip)
            count("bla_skip_small", small_now & skip)
        done = escaped | (steps >= max_iter)
        rebase &= ~done
        count("rebase_small", rebase & small_now)
        count("rebase_normal", rebase & ~small_now)
        if done.any():
            hits = idx[escaped]
            counts[hits] = steps[escaped]
            # Per component (to_double of each): zdr + 1j * zdi would be a complex multiply,
            # turning an infinite imaginary part into a NaN real part and -0.0 into +0.0.
            final.real[hits] = zdr[escaped]
            final.imag[hits] = zdi[escaped]
            if track:
                out_dr[hits] = dwr[escaped]
                out_di[hits] = dwi[escaped]
                out_de[hits] = d_exp[escaped]
            out_apps[idx[done]] = apps[done]
            keep = ~done
            wr, wi, exponent, m, last, idx, steps, apps = (
                wr[keep],
                wi[keep],
                exponent[keep],
                m[keep],
                last[keep],
                idx[keep],
                steps[keep],
                apps[keep],
            )
            dcs_r, dcs_i, dc_bad = dcs_r[keep], dcs_i[keep], dc_bad[keep]
            dc = dc.take(keep)
            rebase = rebase[keep]
            small_now, zdr, zdi = small_now[keep], zdr[keep], zdi[keep]
            zx = zx.take(keep)
            if track:
                dwr, dwi, d_exp = dwr[keep], dwi[keep], d_exp[keep]
                adds, add_bad = adds[keep], add_bad[keep]
            if idx.size == 0:
                break
        if rebase.any():
            sel = np.flatnonzero(rebase)
            # delta <- z (exact: the double z, or the floatexp z at a small landing)
            zsel = zx.take(sel)
            zfast = _x_of_pair(zdr[sel], zdi[sel], np.zeros(sel.size, dtype=np.int64))
            znew = XPair(
                np.where(small_now[sel], zsel.rm, zfast.rm),
                np.where(small_now[sel], zsel.re, zfast.re),
                np.where(small_now[sel], zsel.im, zfast.im),
                np.where(small_now[sel], zsel.ie, zfast.ie),
            )
            nr, ni, ne = _split_pair(znew, exponent[sel])
            wr[sel], wi[sel], exponent[sel] = nr, ni, ne
            m[sel] = rebase_start
            last[sel] = rebase_last
            a, b, c = dc_scaled(dc.take(sel), exponent[sel])
            dcs_r[sel], dcs_i[sel], dc_bad[sel] = a, b, c
        if track:
            z_small = small_now
    return T2Result(counts, final, out_dr, out_di, out_de, out_apps)


def _landing_z(
    refs: _Refs, m: IntArray, wr: FloatArray, wi: FloatArray, exponent: IntArray
) -> tuple[BoolArray, FloatArray, FloatArray, XPair]:
    """z = Z[m] + delta: at a normal index as doubles (Z + delta_d); at a small index in
    floatexp (and its double, to_double's rounding, for the final z)."""
    small = refs.small[m]
    ddr, ddi = _delta_double(wr, wi, exponent)
    with np.errstate(over="ignore", invalid="ignore"):
        zdr = refs.zr[m] + ddr
        zdi = refs.zi[m] + ddi
    zx = XPair.zeros(m.size)
    if small.any():
        sel = np.flatnonzero(small)
        z = _cadd(refs.z_x(m[sel]), _x_of_pair(wr[sel], wi[sel], exponent[sel]))
        zx.put(sel, z)
        zdr[sel] = fx.vto_double(z.rm, z.re)
        zdi[sel] = fx.vto_double(z.im, z.ie)
    return small, zdr, zdi, zx
