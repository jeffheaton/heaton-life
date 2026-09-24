"""Discovery -- spec/nucleus.md: the box period test, Newton's method for a nucleus, and
the atom size estimate (Mandelbrot).

A view that holds a minibrot holds its nucleus c0 (z_p(c0) = 0 for its period p). The box
test finds p from the view -- the first n at which the images of a square's corners
surround 0 -- and Newton on z_p(c) = 0 homes in on c0. Every decision is an integer
comparison in the reference orbit's fixed point (core.bignum: values round(x * 2^F),
products rounded half away from zero), so both ports find the same nucleus, bit for bit,
and print the same center. Only the size estimate's final logarithm is libm (an epsilon
output).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from typing import Any

from heaton_life.core import decimal_text
from heaton_life.core.bignum import _integer_type, from_double, parse_fixed, working_bits
from heaton_life.core.pow10 import pow10
from heaton_life.fractal.locations import Location

MAX_STEPS = 64  # Newton steps per run
MAX_BACKTRACKS = 24  # halvings of a step the line search may try
MAX_EVALUATIONS = 200  # evaluations of z_p per run (checked after an accepted step)
MAX_ESCALATIONS = 4  # precision raises after a run that reached the floor
BOX_ESCAPE_BITS = 16  # a box corner past 2^16 has escaped for good
BOX_HALVINGS = 8  # times the box test halves its square after a corner escapes
RADIUS_BITS = 128  # F >= RADIUS_BITS - binade(radius): the square spans >= 2^119 ulps
FLOOR_BITS = 64  # a Newton step under 2^32 ulps: the run reached its fixed point's floor
NEAR_BITS = 8  # N < 2^(F + NEAR_BITS), |z_p| < 2^((8 - F) / 2): no backtracking any more
RESOLVE_BITS = 64  # converged needs F >= depth_bits + RESOLVE_BITS: F places the atom
STAGNATION_WINDOW = 12  # accepted steps that must shrink the step by a bit
FRAME_LOG10 = 0.4  # location(): the half-height is 10^0.4 (about 2.5) sizes
_LOG10_2 = 0.30102999566398120  # the double nearest log10(2)

__all__ = ["BoxResult", "Nucleus", "box_period", "find_nucleus"]


def _rdiv(numerator: Any, denominator: Any) -> Any:
    """round(numerator / denominator), ties away from zero; denominator > 0."""
    quotient, remainder = divmod(abs(numerator), denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return -quotient if numerator < 0 else quotient


def _rshift(value: Any, k: int) -> Any:
    """round(value / 2^k), ties away from zero (symmetric in sign); k >= 0."""
    if k == 0:
        return value
    half = 1 << (k - 1)
    return (value + half) >> k if value >= 0 else -((-value + half) >> k)


def _multiplier(bits: int) -> Callable[[Any, Any], Any]:
    """mul(a, b) = round(a * b / 2^bits), ties away from zero (the orbit's multiply)."""
    half = 1 << (bits - 1)

    def mul(a: Any, b: Any) -> Any:
        product = a * b
        return (product + half) >> bits if product >= 0 else -((-product + half) >> bits)

    return mul


def _radius(zoom_log10: float, radius: float | None) -> float:
    """The box half-side and Newton's reach: half the frame's width by default."""
    if not (math.isfinite(zoom_log10) and abs(zoom_log10) <= 300.0):
        raise ValueError(f"zoom_log10 must be finite and within [-300, 300], got {zoom_log10!r}")
    value = 2.0 * pow10(-zoom_log10) if radius is None else radius
    if not (math.isfinite(value) and value > 0.0):
        raise ValueError("radius must be finite and positive")
    return value


def _bits(center_re: str, center_im: str, zoom_log10: float, radius: float) -> int:
    """The orbit's precision at ``zoom_log10``, and enough for the radius to span 2^119
    ulps after the box's 8 halvings: RADIUS_BITS - binade(radius) at least."""
    binade = math.frexp(radius)[1] - 1  # radius in [2^binade, 2^(binade+1))
    return max(working_bits(center_re, center_im, zoom_log10), RADIUS_BITS - binade)


# --- the box period test ----------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BoxResult:
    """What box_period found (spec/nucleus.md "Box period")."""

    period: int | None  # the first n whose corners surround 0, or None
    reason: str  # "surrounded", "budget" (max_period ran out), "escaped" (every square)
    halvings: int  # of the last square tried, 0 ... BOX_HALVINGS
    radius: float  # that square's half-side, radius * 2^-halvings: Newton's reach for a snap


def box_period(
    center_re: str,
    center_im: str,
    zoom_log10: float,
    max_period: int,
    radius: float | None = None,
) -> BoxResult:
    """The first n <= max_period at which the images of the square's corners, c +- r +- ri,
    surround 0 -- the period of the lowest-period nucleus the square holds. ``radius`` is
    the square's half-side, half the frame's width (2 * 10^-zoom) by default; a host
    passes its frame's iteration budget as ``max_period``. A corner past 2^16 has escaped,
    and the corners no longer stand for the square's image: the square is halved and the
    test starts again, at most BOX_HALVINGS times."""
    if max_period < 1:
        raise ValueError("max_period must be positive")
    half_side = _radius(zoom_log10, radius)
    bits = _bits(center_re, center_im, zoom_log10, half_side)
    integer = _integer_type()
    cr = integer(parse_fixed(center_re, bits))
    ci = integer(parse_fixed(center_im, bits))
    r0 = integer(from_double(half_side, bits))
    for halving in range(BOX_HALVINGS + 1):
        period, escaped = _box(cr, ci, _rshift(r0, halving), max_period, bits)
        if not escaped:
            reason = "budget" if period is None else "surrounded"
            return BoxResult(period, reason, halving, math.ldexp(half_side, -halving))
    return BoxResult(None, "escaped", BOX_HALVINGS, math.ldexp(half_side, -BOX_HALVINGS))


def _box(cr: Any, ci: Any, r: Any, max_period: int, bits: int) -> tuple[int | None, bool]:
    """One square: (the first surround, False), (None, True) when a corner escapes first,
    or (None, False) when the budget runs out."""
    corners = [(cr - r, ci - r), (cr + r, ci - r), (cr + r, ci + r), (cr - r, ci + r)]
    mul = _multiplier(bits)
    limit = (cr * 0 + 1) << (bits + BOX_ESCAPE_BITS)
    z = [(cr * 0, cr * 0) for _ in corners]
    for n in range(1, max_period + 1):
        z = [
            (mul(x, x) - mul(y, y) + ccr, 2 * mul(x, y) + cci)
            for (x, y), (ccr, cci) in zip(z, corners, strict=True)
        ]
        if _surrounds_origin(z):
            return n, False
        if any(abs(x) >= limit or abs(y) >= limit for x, y in z):
            return None, True
    return None, False


def _surrounds_origin(points: list[tuple[Any, Any]]) -> bool:
    """Crossing parity of the closed polygon against the positive real axis, in integers:
    an edge a -> b straddles when (a.y >= 0) != (b.y >= 0) (a vertex on the axis counts as
    above) and crosses to the right of 0 when (a.x b.y - b.x a.y)(b.y - a.y) > 0."""
    inside = False
    for index, (ax, ay) in enumerate(points):
        bx, by = points[(index + 1) % len(points)]
        if (ay >= 0) != (by >= 0) and (ax * by - bx * ay) * (by - ay) > 0:
            inside = not inside
    return inside


# --- Newton ---------------------------------------------------------------------------------


def _evaluate(cr: Any, ci: Any, period: int, bits: int) -> tuple[Any, Any, Any, Any, bool]:
    """z_p and dz_p/dc at c: the derivative dz' = 2 z dz + 1 from the pre-step z, then the
    orbit step; escaped once a component passes 2."""
    mul = _multiplier(bits)
    one = cr * 0 + (1 << bits)
    bound = one << 1
    zr = zi = dr = di = cr * 0
    for _ in range(period):
        dr, di = 2 * (mul(zr, dr) - mul(zi, di)) + one, 2 * (mul(zr, di) + mul(zi, dr))
        zr, zi = mul(zr, zr) - mul(zi, zi) + cr, 2 * mul(zr, zi) + ci
        if abs(zr) > bound or abs(zi) > bound:
            return zr, zi, dr, di, True
    return zr, zi, dr, di, False


@dataclasses.dataclass
class _Run:
    cr: Any
    ci: Any
    zr: Any
    zi: Any
    dr: Any
    di: Any
    escaped: bool
    steps: int
    evaluations: int
    stop: str


def _newton(
    cr: Any,
    ci: Any,
    origin: tuple[Any, Any],
    period: int,
    bits: int,
    reach: Any,
    max_steps: int,
    max_evaluations: int,
) -> _Run:
    """One Newton run at ``bits`` from (cr, ci) (spec/nucleus.md "Newton"); ``reach`` is
    the step clamp, and a point more than twice it from ``origin`` (the view's center) has
    left the view."""
    origin_re, origin_im = origin
    zr, zi, dr, di, escaped = _evaluate(cr, ci, period, bits)
    evaluations = 1
    norm = zr * zr + zi * zi
    steps = 0  # accepted steps
    near = cr * 0 + (1 << (bits + NEAR_BITS))
    window_start: Any = 0
    reach2 = reach * reach
    while True:
        if escaped:
            stop = "start-escaped"
            break
        if steps == max_steps:
            stop = "max-steps"
            break
        den = dr * dr + di * di
        if den == 0:
            stop = "zero-derivative"
            break
        delta_re = _rdiv((zr * dr + zi * di) << bits, den)
        delta_im = _rdiv((zi * dr - zr * di) << bits, den)
        newton2 = delta_re * delta_re + delta_im * delta_im  # Newton's distance to the root
        clamp = 0
        while newton2 > reach2 << (2 * clamp):
            clamp += 1
        delta_re, delta_im = _rshift(delta_re, clamp), _rshift(delta_im, clamp)
        accepted = False
        step2: Any = 0
        for back in range(1 if norm < near else MAX_BACKTRACKS + 1):
            sr, si = _rshift(delta_re, back), _rshift(delta_im, back)
            if sr == 0 and si == 0:
                break
            evaluations += 1
            t = _evaluate(cr - sr, ci - si, period, bits)
            if t[4]:
                continue
            candidate = t[0] * t[0] + t[1] * t[1]
            if not candidate < norm:
                continue
            cr, ci = cr - sr, ci - si
            zr, zi, dr, di = t[0], t[1], t[2], t[3]
            norm = candidate
            step2 = sr * sr + si * si
            accepted = True
            break
        if not accepted:
            stop = "floor" if newton2 < 1 << FLOOR_BITS else "no-improvement"
            break
        steps += 1
        if abs(cr - origin_re) > 2 * reach or abs(ci - origin_im) > 2 * reach:
            stop = "left-view"
            break
        if steps % STAGNATION_WINDOW == 1:
            window_start = step2
        elif steps % STAGNATION_WINDOW == 0 and step2 * 4 > window_start:
            stop = "stagnated"  # less than a bit gained over the window
            break
        if evaluations >= max_evaluations:
            stop = "max-evaluations"
            break
    return _Run(cr, ci, zr, zi, dr, di, escaped, steps, evaluations, stop)


@dataclasses.dataclass(frozen=True)
class Nucleus:
    """What find_nucleus found (spec/nucleus.md "The result"). ``found`` is the verdict;
    ``center_re`` and ``center_im`` are the last Newton point, printed at the places its
    size needs."""

    found: bool  # converged, no divisor period got there first, and inside
    converged: bool  # |z_p| under the bar, F 64 bits past the depth: a nucleus of p or a divisor
    inside: bool  # the point is within the reach of the view's center, in each component
    stop: str  # why the last Newton run ended
    center_re: str
    center_im: str
    period: int
    lower_period: int | None  # the divisor period Newton reached instead, if any
    bits: int  # the fixed point's fraction bits at the end
    steps: int  # over every run
    evaluations: int  # over every run (the final pass not counted)
    depth_bits: int  # bitlen(|dz_p/dc|^2 * 2^2F) - 2F: about log2 of 1/size
    size_log10: float  # log10 of the atom size (epsilon); NaN unless converged on period p

    def location(self) -> Location:
        """The portable record of a found nucleus (spec/nucleus.md "The result"): a
        half-height 2.5 times the size, so the minibrot's spike (2 sizes from the nucleus,
        whichever way it faces) fits, and 100 periods of iterations. It can be deeper than
        a renderer's range: a host clamps."""
        if not self.found or math.isnan(self.size_log10):
            raise ValueError("no nucleus was found")
        return Location(
            center_re=self.center_re,
            center_im=self.center_im,
            half_height_log10=self.size_log10 + FRAME_LOG10,
            format="nucleus",
            max_iter=min(100 * self.period, 2**31 - 1),
        )


def find_nucleus(
    center_re: str,
    center_im: str,
    period: int,
    zoom_log10: float,
    radius: float | None = None,
    *,
    max_steps: int = MAX_STEPS,
    max_evaluations: int = MAX_EVALUATIONS,
    max_escalations: int = MAX_ESCALATIONS,
) -> Nucleus:
    """Newton's method for the nucleus of ``period`` nearest the view (spec/nucleus.md):
    steps no longer than ``radius`` (half the frame's width by default), each halved up to
    24 times until |z_p| strictly shrinks, stopping if the point leaves twice that reach;
    precision from twice the view's zoom (a minibrot found from zoom z lies near zoom 2z),
    raised when a run reaches its floor with the derivative saying the nucleus is finer.
    The verdict: |z_p| < 2^(0.4 (8 - F)), and no divisor period gets there first."""
    if period < 1:
        raise ValueError("period must be positive")
    if max_steps < 1 or max_evaluations < 1 or max_escalations < 0:
        raise ValueError("budgets must be positive (max_escalations non-negative)")
    reach = _radius(zoom_log10, radius)
    bits = _bits(center_re, center_im, 2.0 * zoom_log10, reach)
    integer = _integer_type()
    start_re = integer(parse_fixed(center_re, bits))
    start_im = integer(parse_fixed(center_im, bits))

    def run_at(cr: Any, ci: Any, f: int) -> _Run:
        m = integer(from_double(reach, f))
        return _newton(cr, ci, (start_re, start_im), period, f, m, max_steps, max_evaluations)

    run = run_at(start_re, start_im, bits)
    steps, evaluations = run.steps, run.evaluations
    for _ in range(max_escalations):
        if run.stop != "floor":  # only a run that went as far as F allows
            break
        need = int((run.dr * run.dr + run.di * run.di).bit_length()) - 2 * bits + 128
        if need <= bits:
            break
        shift = need - bits
        start_re, start_im = start_re << shift, start_im << shift
        run = run_at(run.cr << shift, run.ci << shift, need)
        bits = need
        steps += run.steps
        evaluations += run.evaluations
    cr, ci = run.cr, run.ci
    m = integer(from_double(reach, bits))
    inside = abs(cr - start_re) <= m and abs(ci - start_im) <= m
    depth_bits = (
        0
        if run.escaped  # the derivative of an orbit cut short measures nothing
        else max(int((run.dr * run.dr + run.di * run.di).bit_length()) - 2 * bits, 0)
    )
    verdict = integer(1) << _verdict_bits(bits)
    # Under the bar, and at a precision that places the atom: at a coarse F, a grid point
    # many sizes from the nucleus passes the bar too.
    converged = (
        not run.escaped
        and run.zr * run.zr + run.zi * run.zi < verdict
        and bits - depth_bits >= RESOLVE_BITS
    )
    lower = None
    size = math.nan
    if converged:
        lower, size = _final_pass(cr, ci, period, bits, verdict)
    # A converged point prints 8 places past the finer of its size and the view; any other
    # point, 8 past the view (its derivative says nothing about a size).
    places = max(math.ceil(zoom_log10), 0) + 8
    if converged:
        places = max((depth_bits * 30103 + 99999) // 100000 + 8, places)
    return Nucleus(
        found=converged and lower is None and bool(inside),
        converged=converged,
        inside=bool(inside),
        stop=run.stop,
        center_re=_printed(cr, bits, places),
        center_im=_printed(ci, bits, places),
        period=period,
        lower_period=lower,
        bits=bits,
        steps=steps,
        evaluations=evaluations,
        depth_bits=depth_bits,
        size_log10=size,
    )


def _verdict_bits(bits: int) -> int:
    """K = floor((6F + 32) / 5): N < 2^K is log2|z_p| < 0.4 (8 - F), Heaton Fractal's bar."""
    return (6 * bits + 32) // 5


def _printed(value: Any, bits: int, places: int) -> str:
    """value / 2^bits at ``places`` decimals, ties away from zero (navigation's print)."""
    return decimal_text.format_scaled(int(_rdiv(value * 10**places, 1 << bits)), places)


# --- the final pass: the lower-period screen and the atom size ------------------------------


def _final_pass(cr: Any, ci: Any, period: int, bits: int, verdict: Any) -> tuple[int | None, float]:
    """One more orbit of the found point: the least divisor n < p with |z_n|^2 under the
    verdict (Newton reached a nucleus of that period instead), and log10 of the atom size
    1 / |b l^2|, l = prod_{k=1}^{p-1} 2 z_k, b = 1 + sum_k 1/l_k (Hunt and Ott;
    Heiland-Allen's size estimate) -- NaN when a z_k or b l^2 is 0."""
    mul = _multiplier(bits)
    zr = zi = cr * 0
    l = _Ext(1.0, 0.0, 0)
    b = _Ext(1.0, 0.0, 0)
    degenerate = False
    for n in range(1, period):
        zr, zi = mul(zr, zr) - mul(zi, zi) + cr, 2 * mul(zr, zi) + ci
        if period % n == 0 and zr * zr + zi * zi < verdict:
            return n, math.nan
        if degenerate:
            continue
        z = _Ext.from_fixed(zr, zi, bits)
        if z.is_zero():
            degenerate = True
            continue
        l = l.times(z).doubled()
        b = b.plus(l.reciprocal())
    if degenerate:
        return None, math.nan
    v = b.times(l).times(l)
    if v.is_zero():
        return None, math.nan
    return None, -(0.5 * math.log10(v.re * v.re + v.im * v.im) + v.e * _LOG10_2) + 0.0


class _Ext:
    """A complex float with an exponent: (re + i im) * 2^e, max(|re|, |im|) in [1, 2) or
    both 0. IEEE + - * / only, in fixed shapes; every rescaling is by an exact power of two."""

    __slots__ = ("e", "im", "re")

    def __init__(self, re: float, im: float, e: int) -> None:
        big = max(abs(re), abs(im))
        if big == 0.0:
            self.re, self.im, self.e = 0.0, 0.0, 0
            return
        k = math.frexp(big)[1] - 1  # big in [2^k, 2^(k+1))
        self.re, self.im, self.e = math.ldexp(re, -k), math.ldexp(im, -k), e + k

    @classmethod
    def from_fixed(cls, x: Any, y: Any, bits: int) -> _Ext:
        """(x + iy) / 2^bits: each part rounded to 53 bits (half to even), then one shared
        exponent; a part more than 60 binades below the other is dropped."""
        (mx, ex), (my, ey) = _split(int(x), bits), _split(int(y), bits)
        if mx == 0.0:
            return cls(0.0, my, ey)
        if my == 0.0:
            return cls(mx, 0.0, ex)
        e = max(ex, ey)
        return cls(_align(mx, e - ex), _align(my, e - ey), e)

    def times(self, other: _Ext) -> _Ext:
        return _Ext(
            self.re * other.re - self.im * other.im,
            self.re * other.im + self.im * other.re,
            self.e + other.e,
        )

    def doubled(self) -> _Ext:
        return _Ext(self.re, self.im, self.e + 1)

    def reciprocal(self) -> _Ext:
        den = self.re * self.re + self.im * self.im
        return _Ext(self.re / den, -self.im / den, -self.e)

    def plus(self, other: _Ext) -> _Ext:
        if self.is_zero():
            return other
        if other.is_zero():
            return self
        e = max(self.e, other.e)
        return _Ext(
            _align(self.re, e - self.e) + _align(other.re, e - other.e),
            _align(self.im, e - self.e) + _align(other.im, e - other.e),
            e,
        )

    def is_zero(self) -> bool:
        return self.re == 0.0 and self.im == 0.0


def _align(mantissa: float, gap: int) -> float:
    """mantissa * 2^-gap, or 0 when gap > 60 (too small to matter)."""
    return 0.0 if gap > 60 else math.ldexp(mantissa, -gap)


def _split(value: int, bits: int) -> tuple[float, int]:
    """value / 2^bits as (m, e) with |m| in [1, 2), m rounded to 53 bits half to even."""
    if value == 0:
        return 0.0, 0
    magnitude = abs(value)
    length = magnitude.bit_length()
    shift = max(length - 53, 0)
    q = magnitude >> shift
    if shift:
        remainder = magnitude & ((1 << shift) - 1)
        half = 1 << (shift - 1)
        if remainder > half or (remainder == half and q & 1):
            q += 1
    top = q.bit_length() - 1
    m = math.ldexp(float(q), -top)  # exact: q has at most 54 bits
    return (-m if value < 0 else m), shift + top - bits
