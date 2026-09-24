using System;
using System.Numerics;
using System.Threading;

namespace HeatonLife
{
    /// <summary>What <see cref="NucleusFinder.BoxPeriod"/> found (spec/nucleus.md "Box period").</summary>
    public sealed class BoxResult
    {
        internal BoxResult(int? period, string reason, int halvings, double radius)
        {
            Period = period;
            Reason = reason;
            Halvings = halvings;
            Radius = radius;
        }

        /// <summary>The first n whose corners surround 0, or null.</summary>
        public int? Period { get; }

        /// <summary>surrounded, budget (max_period ran out) or escaped (on every square).</summary>
        public string Reason { get; }

        /// <summary>Halvings of the last square tried, 0 … 8.</summary>
        public int Halvings { get; }

        /// <summary>That square's half-side, radius·2^−halvings: Newton's reach for a snap.</summary>
        public double Radius { get; }
    }

    /// <summary>
    /// What <see cref="NucleusFinder.FindNucleus"/> found (spec/nucleus.md "The result").
    /// <see cref="Found"/> is the verdict; the center is the last Newton point, printed at
    /// the places its size needs.
    /// </summary>
    public sealed class Nucleus
    {
        internal Nucleus(
            bool found, bool converged, bool inside, string stop, string centerRe, string centerIm, int period,
            int? lowerPeriod, int bits, int steps, int evaluations, int depthBits, double sizeLog10)
        {
            Found = found;
            Converged = converged;
            Inside = inside;
            Stop = stop;
            CenterRe = centerRe;
            CenterIm = centerIm;
            Period = period;
            LowerPeriod = lowerPeriod;
            Bits = bits;
            Steps = steps;
            Evaluations = evaluations;
            DepthBits = depthBits;
            SizeLog10 = sizeLog10;
        }

        /// <summary><see cref="Converged"/>, no divisor period got there first, and <see cref="Inside"/>.</summary>
        public bool Found { get; }

        /// <summary>
        /// |z_p| &lt; 2^(0.4 (8 − F)) with F at least 64 bits past the depth: Newton reached a
        /// nucleus (of the period or a divisor), at a precision that places it.
        /// </summary>
        public bool Converged { get; }

        /// <summary>The point is within the reach of the view's center, in each component.</summary>
        public bool Inside { get; }

        /// <summary>
        /// Why the last Newton run ended: floor (the usual end of a run that converged),
        /// no-improvement, left-view, stagnated, max-evaluations, max-steps,
        /// zero-derivative, start-escaped.
        /// </summary>
        public string Stop { get; }

        /// <summary>The last Newton point's real part, printed at the places its size needs.</summary>
        public string CenterRe { get; }

        /// <summary>The last Newton point's imaginary part.</summary>
        public string CenterIm { get; }

        /// <summary>The period asked for.</summary>
        public int Period { get; }

        /// <summary>The divisor period Newton reached instead, or null.</summary>
        public int? LowerPeriod { get; }

        /// <summary>The fixed point's fraction bits at the end.</summary>
        public int Bits { get; }

        /// <summary>Accepted Newton steps, over every run.</summary>
        public int Steps { get; }

        /// <summary>Evaluations of z_p, over every run (the final pass not counted).</summary>
        public int Evaluations { get; }

        /// <summary>bitlen(|dz_p/dc|² · 2^2F) − 2F, at least 0 (0 when the orbit escaped): about log2 of 1/size.</summary>
        public int DepthBits { get; }

        /// <summary>log10 of the atom size estimate (ε tier); NaN unless converged on the period itself.</summary>
        public double SizeLog10 { get; }

        /// <summary>
        /// The portable record of a found nucleus (spec/nucleus.md "The result"): a
        /// half-height 2.5 times the size, so the minibrot's spike (2 sizes from the nucleus,
        /// whichever way it faces) fits, and 100 periods of iterations. It can be deeper than
        /// a renderer's range: a host clamps.
        /// </summary>
        public Location ToLocation()
        {
            if (!Found || double.IsNaN(SizeLog10))
                throw new InvalidOperationException("no nucleus was found");
            return new Location(
                CenterRe, CenterIm, SizeLog10 + NucleusFinder.FrameLog10, "nucleus", Math.Min(100L * Period, int.MaxValue),
                null, null, Array.Empty<string>());
        }
    }

    /// <summary>
    /// Discovery (spec/nucleus.md): the box period test, Newton's method for a nucleus, and
    /// the atom size estimate (Mandelbrot). Every decision is an integer comparison in the
    /// reference orbit's fixed point (<see cref="ReferenceOrbit"/>: values round(x·2^F),
    /// products rounded half away from zero), so this finds the same nucleus as the Python
    /// reference, bit for bit, and prints the same center. Only the size estimate's final
    /// logarithm is libm (ε). The Python reference's heaton_life.fractal.nucleus.
    /// </summary>
    public static class NucleusFinder
    {
        /// <summary>Accepted Newton steps per run, by default.</summary>
        public const int MaxSteps = 64;

        /// <summary>Evaluations of z_p per run, by default (checked after an accepted step).</summary>
        public const int MaxEvaluations = 200;

        /// <summary>Precision raises after a run that reached its floor, by default.</summary>
        public const int MaxEscalations = 4;

        internal const int MaxBacktracks = 24;
        internal const int BoxEscapeBits = 16;
        internal const int BoxHalvings = 8;
        internal const int RadiusBits = 128;
        internal const int FloorBits = 64;
        internal const int NearBits = 8;
        internal const int ResolveBits = 64;
        internal const int StagnationWindow = 12;
        internal const double FrameLog10 = 0.4;
        private const int PollInterval = 4096;
        private const double Log10Of2 = 0.30102999566398120;

        /// <summary>
        /// The first n ≤ <paramref name="maxPeriod"/> at which the images of the square's
        /// corners, c ± r ± ri, surround 0 — the period of the lowest-period nucleus the
        /// square holds (spec/nucleus.md "Box period"). <paramref name="radius"/> is the
        /// square's half-side, half the frame's width (2·10^−zoom) by default; a host passes
        /// its frame's iteration budget as <paramref name="maxPeriod"/>. A corner past 2^16
        /// has escaped and the corners no longer stand for the square's image: the square is
        /// halved and the test starts again, at most 8 times.
        /// </summary>
        public static BoxResult BoxPeriod(
            string centerRe, string centerIm, double zoomLog10, int maxPeriod, double? radius = null,
            CancellationToken cancellationToken = default)
        {
            if (maxPeriod < 1)
                throw new ArgumentOutOfRangeException(nameof(maxPeriod), "max_period must be positive");
            double halfSide = Radius(zoomLog10, radius);
            cancellationToken.ThrowIfCancellationRequested();
            int bits = Bits(centerRe, centerIm, zoomLog10, halfSide);
            BigInteger cr = ReferenceOrbit.ParseFixed(centerRe, bits);
            BigInteger ci = ReferenceOrbit.ParseFixed(centerIm, bits);
            BigInteger r0 = ReferenceOrbit.FromDouble(halfSide, bits);
            for (int halving = 0; halving <= BoxHalvings; halving++)
            {
                int? period = Box(cr, ci, RoundShift(r0, halving), maxPeriod, bits, cancellationToken, out bool escaped);
                if (!escaped)
                    return new BoxResult(period, period == null ? "budget" : "surrounded", halving, halfSide * PowerOfTwo(-halving));
            }
            return new BoxResult(null, "escaped", BoxHalvings, halfSide * PowerOfTwo(-BoxHalvings));
        }

        /// <summary>One square: the first surround; null with escaped set when a corner escapes first.</summary>
        private static int? Box(
            BigInteger cr, BigInteger ci, BigInteger r, int maxPeriod, int bits,
            CancellationToken cancellationToken, out bool escaped)
        {
            var cornerRe = new[] { cr - r, cr + r, cr + r, cr - r };
            var cornerIm = new[] { ci - r, ci - r, ci + r, ci + r };
            var x = new BigInteger[4];
            var y = new BigInteger[4];
            BigInteger limit = BigInteger.One << (bits + BoxEscapeBits);
            escaped = false;
            cancellationToken.ThrowIfCancellationRequested();
            for (long n = 1; n <= maxPeriod; n++)   // long: a bound of int.MaxValue must end
            {
                if ((n & (PollInterval - 1)) == 0)
                    cancellationToken.ThrowIfCancellationRequested();
                for (int k = 0; k < 4; k++)
                {
                    BigInteger xk = x[k], yk = y[k];
                    x[k] = ReferenceOrbit.Mul(xk, xk, bits) - ReferenceOrbit.Mul(yk, yk, bits) + cornerRe[k];
                    y[k] = 2 * ReferenceOrbit.Mul(xk, yk, bits) + cornerIm[k];
                }
                if (SurroundsOrigin(x, y))
                    return (int)n;
                for (int k = 0; k < 4; k++)
                {
                    if (BigInteger.Abs(x[k]) >= limit || BigInteger.Abs(y[k]) >= limit)
                    {
                        escaped = true;
                        return null;
                    }
                }
            }
            return null;
        }

        /// <summary>
        /// Crossing parity of the closed polygon against the positive real axis, in
        /// integers: an edge a → b straddles when (a.y ≥ 0) ≠ (b.y ≥ 0) (a vertex on the
        /// axis counts as above) and crosses to the right of 0 when
        /// (a.x·b.y − b.x·a.y)·(b.y − a.y) &gt; 0.
        /// </summary>
        internal static bool SurroundsOrigin(BigInteger[] x, BigInteger[] y)
        {
            bool inside = false;
            for (int i = 0; i < x.Length; i++)
            {
                int j = (i + 1) % x.Length;
                if ((y[i].Sign >= 0) != (y[j].Sign >= 0)
                    && ((x[i] * y[j] - x[j] * y[i]) * (y[j] - y[i])).Sign > 0)
                    inside = !inside;
            }
            return inside;
        }

        /// <summary>
        /// Newton's method for the nucleus of <paramref name="period"/> nearest the view
        /// (spec/nucleus.md "Newton"): steps no longer than <paramref name="radius"/> (half
        /// the frame's width by default), each halved up to 24 times until |z_p| strictly
        /// shrinks, stopping if the point leaves twice that reach; precision from twice the
        /// view's zoom (a minibrot found from zoom z lies near zoom 2z), raised when a run
        /// reaches its floor with the derivative saying the nucleus is finer. The verdict:
        /// |z_p| &lt; 2^(0.4 (8 − F)), and no divisor period gets there first. Cancellation
        /// throws; it never returns a partial result.
        /// </summary>
        public static Nucleus FindNucleus(
            string centerRe, string centerIm, int period, double zoomLog10, double? radius = null,
            int maxSteps = MaxSteps, int maxEvaluations = MaxEvaluations, int maxEscalations = MaxEscalations,
            CancellationToken cancellationToken = default)
        {
            if (period < 1)
                throw new ArgumentOutOfRangeException(nameof(period), "period must be positive");
            if (maxSteps < 1 || maxEvaluations < 1 || maxEscalations < 0)
                throw new ArgumentOutOfRangeException(nameof(maxSteps), "budgets must be positive (max_escalations non-negative)");
            double reach = Radius(zoomLog10, radius);
            cancellationToken.ThrowIfCancellationRequested();
            int bits = Bits(centerRe, centerIm, 2.0 * zoomLog10, reach);
            BigInteger startRe = ReferenceOrbit.ParseFixed(centerRe, bits);
            BigInteger startIm = ReferenceOrbit.ParseFixed(centerIm, bits);
            Run run = Newton(
                startRe, startIm, startRe, startIm, period, bits, ReferenceOrbit.FromDouble(reach, bits),
                maxSteps, maxEvaluations, cancellationToken);
            int steps = run.Steps, evaluations = run.Evaluations;
            // Only a run that went as far as F allows raises the precision.
            for (int escalation = 0; escalation < maxEscalations && run.Stop == "floor"; escalation++)
            {
                int need = DecimalText.BitLength(run.Dr * run.Dr + run.Di * run.Di) - 2 * bits + 128;
                if (need <= bits)
                    break;
                int shift = need - bits;
                startRe <<= shift;
                startIm <<= shift;
                run = Newton(
                    run.Cr << shift, run.Ci << shift, startRe, startIm, period, need,
                    ReferenceOrbit.FromDouble(reach, need), maxSteps, maxEvaluations, cancellationToken);
                bits = need;
                steps += run.Steps;
                evaluations += run.Evaluations;
            }
            BigInteger cr = run.Cr, ci = run.Ci;
            BigInteger m = ReferenceOrbit.FromDouble(reach, bits);
            bool inside = BigInteger.Abs(cr - startRe) <= m && BigInteger.Abs(ci - startIm) <= m;
            // The derivative of an orbit cut short measures nothing.
            int depthBits = run.Escaped
                ? 0
                : Math.Max(DecimalText.BitLength(run.Dr * run.Dr + run.Di * run.Di) - 2 * bits, 0);
            BigInteger verdict = BigInteger.One << VerdictBits(bits);
            // Under the bar, and at a precision that places the atom: at a coarse F, a grid
            // point many sizes from the nucleus passes the bar too.
            bool converged = !run.Escaped
                && run.Zr * run.Zr + run.Zi * run.Zi < verdict
                && bits - depthBits >= ResolveBits;
            int? lower = null;
            double size = double.NaN;
            if (converged)
                lower = FinalPass(cr, ci, period, bits, verdict, cancellationToken, out size);
            // A converged point prints 8 places past the finer of its size and the view; any
            // other point, 8 past the view (its derivative says nothing about a size).
            int places = (int)Math.Max(Math.Ceiling(zoomLog10), 0.0) + 8;
            if (converged)
                places = Math.Max((int)(((long)depthBits * 30103 + 99999) / 100000) + 8, places);
            return new Nucleus(
                converged && lower == null && inside, converged, inside, run.Stop, Printed(cr, bits, places), Printed(ci, bits, places), period, lower,
                bits, steps, evaluations, depthBits, size);
        }

        private static double Radius(double zoomLog10, double? radius)
        {
            if (!(Math.Abs(zoomLog10) <= 300.0))
                throw new ArgumentOutOfRangeException(nameof(zoomLog10), $"zoom_log10 must be finite and within [-300, 300], got {zoomLog10:R}");
            double value = radius ?? 2.0 * Pow10.Compute(-zoomLog10);
            if (!(value > 0.0) || double.IsInfinity(value))
                throw new ArgumentOutOfRangeException(nameof(radius), "radius must be finite and positive");
            return value;
        }

        /// <summary>
        /// The orbit's precision at <paramref name="zoomLog10"/>, and enough for the radius to
        /// span 2^119 ulps after the box's 8 halvings: RadiusBits − binade(radius) at least.
        /// </summary>
        private static int Bits(string centerRe, string centerIm, double zoomLog10, double radius) =>
            Math.Max(ReferenceOrbit.WorkingBits(centerRe, centerIm, zoomLog10), RadiusBits - Binade(radius));

        /// <summary>K = ⌊(6F + 32)/5⌋: N &lt; 2^K is log2|z_p| &lt; 0.4 (8 − F), Heaton Fractal's bar.</summary>
        internal static int VerdictBits(int bits) => (6 * bits + 32) / 5;

        /// <summary>value / 2^bits at <paramref name="places"/> decimals, ties away from zero (navigation's print).</summary>
        private static string Printed(BigInteger value, int bits, int places) =>
            DecimalText.FormatScaled(RoundDiv(value * BigInteger.Pow(10, places), BigInteger.One << bits), places);

        // ---- Newton ------------------------------------------------------------------

        internal struct Run
        {
            internal BigInteger Cr, Ci, Zr, Zi, Dr, Di;
            internal bool Escaped;
            internal int Steps, Evaluations;
            internal string Stop;
        }

        /// <summary>
        /// z_p and dz_p/dc at c: the derivative dz' = 2 z dz + 1 from the pre-step z, then
        /// the orbit step; escaped once a component passes 2.
        /// </summary>
        private static bool Evaluate(
            BigInteger cr, BigInteger ci, int period, int bits, CancellationToken cancellationToken,
            out BigInteger zr, out BigInteger zi, out BigInteger dr, out BigInteger di)
        {
            BigInteger one = BigInteger.One << bits;
            BigInteger bound = one << 1;
            zr = zi = dr = di = BigInteger.Zero;
            cancellationToken.ThrowIfCancellationRequested();
            for (long n = 1; n <= period; n++)   // long: a period of int.MaxValue must end
            {
                if ((n & (PollInterval - 1)) == 0)
                    cancellationToken.ThrowIfCancellationRequested();
                BigInteger nextDr = 2 * (ReferenceOrbit.Mul(zr, dr, bits) - ReferenceOrbit.Mul(zi, di, bits)) + one;
                BigInteger nextDi = 2 * (ReferenceOrbit.Mul(zr, di, bits) + ReferenceOrbit.Mul(zi, dr, bits));
                dr = nextDr;
                di = nextDi;
                BigInteger nextZr = ReferenceOrbit.Mul(zr, zr, bits) - ReferenceOrbit.Mul(zi, zi, bits) + cr;
                zi = 2 * ReferenceOrbit.Mul(zr, zi, bits) + ci;
                zr = nextZr;
                if (BigInteger.Abs(zr) > bound || BigInteger.Abs(zi) > bound)
                    return true;
            }
            return false;
        }

        /// <summary>
        /// One Newton run at <paramref name="bits"/> from (cr, ci) (spec/nucleus.md
        /// "Newton"): <paramref name="reach"/> is the step clamp, and a point more than twice
        /// it from the origin (the view's center) has left the view.
        /// </summary>
        internal static Run Newton(
            BigInteger cr, BigInteger ci, BigInteger originRe, BigInteger originIm, int period, int bits,
            BigInteger reach, int maxSteps, int maxEvaluations, CancellationToken cancellationToken)
        {
            bool escaped = Evaluate(cr, ci, period, bits, cancellationToken,
                out BigInteger zr, out BigInteger zi, out BigInteger dr, out BigInteger di);
            int evaluations = 1;
            BigInteger norm = zr * zr + zi * zi;
            int steps = 0;   // accepted steps
            BigInteger near = BigInteger.One << (bits + NearBits);   // |z_p| < 2^((8 − F)/2): no backtracking any more
            BigInteger windowStart = BigInteger.Zero;
            BigInteger reach2 = reach * reach;
            BigInteger twiceReach = reach * 2;
            string stop;
            while (true)
            {
                if (escaped)
                {
                    stop = "start-escaped";
                    break;
                }
                if (steps == maxSteps)
                {
                    stop = "max-steps";
                    break;
                }
                BigInteger den = dr * dr + di * di;
                if (den.IsZero)
                {
                    stop = "zero-derivative";
                    break;
                }
                BigInteger deltaRe = RoundDiv((zr * dr + zi * di) << bits, den);
                BigInteger deltaIm = RoundDiv((zi * dr - zr * di) << bits, den);
                BigInteger newton2 = deltaRe * deltaRe + deltaIm * deltaIm;   // Newton's distance to the root
                int clamp = 0;
                while (newton2 > reach2 << (2 * clamp))
                    clamp++;
                deltaRe = RoundShift(deltaRe, clamp);
                deltaIm = RoundShift(deltaIm, clamp);
                bool accepted = false;
                BigInteger step2 = BigInteger.Zero;
                int tries = norm < near ? 1 : MaxBacktracks + 1;
                for (int back = 0; back < tries; back++)
                {
                    BigInteger sr = RoundShift(deltaRe, back), si = RoundShift(deltaIm, back);
                    if (sr.IsZero && si.IsZero)
                        break;
                    evaluations++;
                    if (Evaluate(cr - sr, ci - si, period, bits, cancellationToken,
                        out BigInteger tzr, out BigInteger tzi, out BigInteger tdr, out BigInteger tdi))
                        continue;
                    BigInteger candidate = tzr * tzr + tzi * tzi;
                    if (!(candidate < norm))
                        continue;
                    cr -= sr;
                    ci -= si;
                    zr = tzr;
                    zi = tzi;
                    dr = tdr;
                    di = tdi;
                    norm = candidate;
                    step2 = sr * sr + si * si;
                    accepted = true;
                    break;
                }
                if (!accepted)
                {
                    stop = newton2 < BigInteger.One << FloorBits ? "floor" : "no-improvement";
                    break;
                }
                steps++;
                if (BigInteger.Abs(cr - originRe) > twiceReach || BigInteger.Abs(ci - originIm) > twiceReach)
                {
                    stop = "left-view";
                    break;
                }
                if (steps % StagnationWindow == 1)
                {
                    windowStart = step2;
                }
                else if (steps % StagnationWindow == 0 && step2 * 4 > windowStart)
                {
                    stop = "stagnated";   // less than a bit gained over the window
                    break;
                }
                if (evaluations >= maxEvaluations)
                {
                    stop = "max-evaluations";
                    break;
                }
            }
            return new Run
            {
                Cr = cr,
                Ci = ci,
                Zr = zr,
                Zi = zi,
                Dr = dr,
                Di = di,
                Escaped = escaped,
                Steps = steps,
                Evaluations = evaluations,
                Stop = stop,
            };
        }

        /// <summary>round(n / d), ties away from zero; d &gt; 0.</summary>
        internal static BigInteger RoundDiv(BigInteger numerator, BigInteger denominator)
        {
            bool negative = numerator.Sign < 0;
            BigInteger quotient = BigInteger.DivRem(BigInteger.Abs(numerator), denominator, out BigInteger remainder);
            if (remainder * 2 >= denominator)
                quotient += BigInteger.One;
            return negative ? -quotient : quotient;
        }

        /// <summary>round(value / 2^k), ties away from zero (symmetric in sign); k ≥ 0.</summary>
        internal static BigInteger RoundShift(BigInteger value, int k)
        {
            if (k == 0)
                return value;
            BigInteger half = BigInteger.One << (k - 1);
            return value.Sign >= 0 ? (value + half) >> k : -((-value + half) >> k);
        }

        // ---- the final pass: the lower-period screen and the atom size -----------------

        /// <summary>
        /// One more orbit of the found point: the least divisor n &lt; p with |z_n|² under the
        /// verdict (Newton reached a nucleus of that period instead), or null, and in
        /// <paramref name="sizeLog10"/> log10 of the atom size 1/|b l²|, l = ∏_{k=1}^{p−1} 2 z_k,
        /// b = 1 + Σ 1/l_k (Hunt and Ott; Heiland-Allen's size estimate) — NaN when a z_k or
        /// b l² is 0.
        /// </summary>
        private static int? FinalPass(
            BigInteger cr, BigInteger ci, int period, int bits, BigInteger verdict,
            CancellationToken cancellationToken, out double sizeLog10)
        {
            sizeLog10 = double.NaN;
            BigInteger zr = BigInteger.Zero, zi = BigInteger.Zero;
            var l = new Ext(1.0, 0.0, 0);
            var b = new Ext(1.0, 0.0, 0);
            bool degenerate = false;
            cancellationToken.ThrowIfCancellationRequested();
            for (int n = 1; n < period; n++)
            {
                if ((n & (PollInterval - 1)) == 0)
                    cancellationToken.ThrowIfCancellationRequested();
                BigInteger nextZr = ReferenceOrbit.Mul(zr, zr, bits) - ReferenceOrbit.Mul(zi, zi, bits) + cr;
                zi = 2 * ReferenceOrbit.Mul(zr, zi, bits) + ci;
                zr = nextZr;
                if (period % n == 0 && zr * zr + zi * zi < verdict)
                    return n;
                if (degenerate)
                    continue;
                Ext z = Ext.FromFixed(zr, zi, bits);
                if (z.IsZero)
                {
                    degenerate = true;
                    continue;
                }
                l = l.Times(z).Doubled();
                b = b.Plus(l.Reciprocal());
            }
            if (degenerate)
                return null;
            Ext v = b.Times(l).Times(l);
            if (!v.IsZero)
                sizeLog10 = -(0.5 * Math.Log10(v.Re * v.Re + v.Im * v.Im) + v.E * Log10Of2) + 0.0;
            return null;
        }

        /// <summary>
        /// A complex float with an exponent: (re + i im)·2^e, max(|re|, |im|) in [1, 2) or both
        /// 0. IEEE + − × ÷ only, in fixed shapes; every rescaling is by an exact power of two.
        /// </summary>
        internal readonly struct Ext
        {
            internal readonly double Re, Im;
            internal readonly int E;

            internal Ext(double re, double im, int e)
            {
                double big = Math.Max(Math.Abs(re), Math.Abs(im));
                if (big == 0.0)
                {
                    Re = 0.0;
                    Im = 0.0;
                    E = 0;
                    return;
                }
                int k = Binade(big);   // big in [2^k, 2^(k+1))
                Re = ScaleB(re, -k);
                Im = ScaleB(im, -k);
                E = e + k;
            }

            internal bool IsZero => Re == 0.0 && Im == 0.0;

            /// <summary>
            /// (x + iy)/2^bits: each part rounded to 53 bits (half to even), then one shared
            /// exponent; a part more than 60 binades below the other is dropped.
            /// </summary>
            internal static Ext FromFixed(BigInteger x, BigInteger y, int bits)
            {
                double mx = Split(x, bits, out int ex);
                double my = Split(y, bits, out int ey);
                if (mx == 0.0)
                    return new Ext(0.0, my, ey);
                if (my == 0.0)
                    return new Ext(mx, 0.0, ex);
                int e = Math.Max(ex, ey);
                return new Ext(Align(mx, e - ex), Align(my, e - ey), e);
            }

            internal Ext Times(Ext other) =>
                new Ext(Re * other.Re - Im * other.Im, Re * other.Im + Im * other.Re, E + other.E);

            internal Ext Doubled() => new Ext(Re, Im, E + 1);

            internal Ext Reciprocal()
            {
                double den = Re * Re + Im * Im;
                return new Ext(Re / den, -Im / den, -E);
            }

            internal Ext Plus(Ext other)
            {
                if (IsZero)
                    return other;
                if (other.IsZero)
                    return this;
                int e = Math.Max(E, other.E);
                return new Ext(
                    Align(Re, e - E) + Align(other.Re, e - other.E),
                    Align(Im, e - E) + Align(other.Im, e - other.E),
                    e);
            }
        }

        /// <summary>mantissa·2^−gap, or 0 when gap &gt; 60 (too small to matter).</summary>
        private static double Align(double mantissa, int gap) => gap > 60 ? 0.0 : ScaleB(mantissa, -gap);

        /// <summary>value/2^bits as m·2^e with |m| in [1, 2), m rounded to 53 bits half to even.</summary>
        internal static double Split(BigInteger value, int bits, out int exponent)
        {
            exponent = 0;
            if (value.IsZero)
                return 0.0;
            BigInteger magnitude = BigInteger.Abs(value);
            int length = DecimalText.BitLength(magnitude);
            int shift = Math.Max(length - 53, 0);
            BigInteger q = magnitude >> shift;
            if (shift > 0)
            {
                BigInteger remainder = magnitude - (q << shift);
                BigInteger half = BigInteger.One << (shift - 1);
                if (remainder > half || (remainder == half && !q.IsEven))
                    q += BigInteger.One;
            }
            int top = DecimalText.BitLength(q) - 1;
            double m = (double)(long)q * PowerOfTwo(-top);   // exact: q has at most 54 bits
            exponent = shift + top - bits;
            return value.Sign < 0 ? -m : m;
        }

        /// <summary>The binade of a positive finite x: the k with x in [2^k, 2^(k+1)).</summary>
        private static int Binade(double x)
        {
            long raw = BitConverter.DoubleToInt64Bits(x);
            int field = (int)((raw >> 52) & 0x7FF);
            if (field != 0)
                return field - 1023;
            long mantissa = raw & 0xFFFFFFFFFFFFFL;   // subnormal: mantissa·2^−1074
            int top = 0;
            while ((mantissa >> (top + 1)) != 0)
                top++;
            return top - 1074;
        }

        /// <summary>x·2^n by exact powers of two (one rounding while the result stays normal).</summary>
        private static double ScaleB(double x, int n)
        {
            while (n > 1023)
            {
                x *= PowerOfTwo(1023);
                n -= 1023;
            }
            while (n < -1022)
            {
                x *= PowerOfTwo(-1022);
                n += 1022;
            }
            return x * PowerOfTwo(n);
        }

        private static double PowerOfTwo(int exponent) => BitConverter.Int64BitsToDouble((long)(1023 + exponent) << 52);
    }
}
