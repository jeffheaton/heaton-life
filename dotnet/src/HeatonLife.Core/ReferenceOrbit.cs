using System;
using System.Collections.Generic;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// High-precision reference orbits for the perturbation tier
    /// (spec/deep-zoom.md). The only bignum computation in the fractal pipeline:
    /// one orbit of the viewport center, so a T1 render needs no externally
    /// supplied data.
    ///
    /// The arithmetic is spec'd, not just the result: binary fixed point over
    /// System.Numerics.BigInteger with <see cref="WorkingBits"/> fractional bits,
    /// decimal parsing and products rounded to nearest with ties away from zero, and
    /// each sample converted to float64 by one correct rounding. The Python reference
    /// (core/bignum.py) runs the same integer operations, so the two orbits agree
    /// bit for bit at any length. Until 2026-09-23 Python iterated in binary
    /// FLOATING point instead; the two agreed only while rounding differences stayed
    /// below a double ulp, which a chaotic orbit outgrows within ~40 iterations
    /// (the deep Julia vector parted at sample 38, a 256-digit center at 67,941).
    ///
    /// <c>ReferenceOrbitTests</c> regenerates the shipped orbit vectors and requires
    /// them byte for byte.
    /// </summary>
    public static class ReferenceOrbit
    {
        /// <summary>Extra bits below the working precision (spec/deep-zoom.md).</summary>
        public const int GuardBits = 64;

        /// <summary>
        /// Stop the reference once it is unambiguously escaping. Mirrors the Python
        /// reference's <c>_ESCAPE_ABS2</c>: |Z|^2 &gt; 1e100 means every pixel that
        /// reaches this sample has already escaped at any sane radius, and it keeps
        /// the value inside float64's range. A short orbit is expected, not an
        /// error — both ports clamp the reference index to the last sample.
        /// </summary>
        public const double EscapeAbs2 = 1e100;

        /// <summary>
        /// Bits needed to resolve a frame at 10^zoom magnification, plus guard — the
        /// zoom term of <see cref="WorkingBits"/>. NOTE the truncation:
        /// <c>(int)(3.33 * zoom)</c>, matching the Python reference's <c>int(3.33 * ...)</c>
        /// (46 bits at zoom 14, not 47). The spec once said ceil; the shipped vectors
        /// were produced by the truncating form and the vectors are the contract. Do
        /// not "fix" this to Ceiling without regenerating every deep-zoom vector.
        /// </summary>
        public static int PrecisionBits(double zoomLog10) =>
            (int)(3.33 * Math.Max(zoomLog10, 0.0)) + GuardBits;

        /// <summary>
        /// Fractional bits the fixed point carries beyond the precision rule. Fixed
        /// point measures precision from the binary point, a float from the leading
        /// digit, so a value below 1 gets fewer significant bits than its nominal
        /// precision; the headroom keeps every sample a correctly rounded double
        /// (a center of ~0.13 at 110 fractional bits came out one ulp off in Z[1]).
        /// </summary>
        internal const int WorkingGuardBits = 64;

        /// <summary>
        /// Center digits past 10^-340 sit below half the smallest float64 subnormal: they
        /// cannot reach a sample, so the digit term of <see cref="WorkingBits"/> stops
        /// there and a long string cannot set the precision on its own.
        /// </summary>
        public const int MaxDigitPlaces = 340;

        /// <summary>
        /// Fractional bits F of the fixed-point orbit (spec/deep-zoom.md "Precision"):
        /// the frame's need (<see cref="PrecisionBits"/>) or the center's own digits (at
        /// most <see cref="MaxDigitPlaces"/> of them), whichever is finer, plus
        /// <see cref="WorkingGuardBits"/>. The digits term
        /// keeps a long or tiny center intact — without it a component of 1e-310 at
        /// zoom 280 would keep ~30 significant bits.
        /// </summary>
        public static int WorkingBits(string centerRe, string centerIm, double zoomLog10)
        {
            int places = Math.Min(Math.Max(DecimalPlaces(centerRe), DecimalPlaces(centerIm)), MaxDigitPlaces);
            int digitBits = DecimalText.BitLength(BigInteger.Pow(10, places));
            return Math.Max(PrecisionBits(zoomLog10), digitBits) + WorkingGuardBits;
        }

        /// <summary>Z0..ZK for Z -&gt; Z^2 + C with Z0 = 0 and C = the center.</summary>
        public static (double[] Re, double[] Im) Mandelbrot(
            string centerRe, string centerIm, double zoomLog10, int maxIter) =>
            Compute(Kind.Mandelbrot, centerRe, centerIm, zoomLog10, maxIter, 0.0, 0.0);

        /// <summary>
        /// Z0..ZK for Z -&gt; Z^2 + c with Z0 = the center and c fixed
        /// (spec/fractals.md: Julia's reference uses the center's orbit under the
        /// same c, and its delta carries no dc term).
        /// </summary>
        public static (double[] Re, double[] Im) Julia(
            string centerRe, string centerIm, double zoomLog10, int maxIter, double cRe, double cIm) =>
            Compute(Kind.Julia, centerRe, centerIm, zoomLog10, maxIter, cRe, cIm);

        /// <summary>
        /// W0..WK for W -&gt; W^2 + c with W0 = 0: the Julia critical orbit, which a
        /// rebased Julia pixel restarts on (spec/deep-zoom.md "Rebasing"). Exactly
        /// <see cref="Julia(string,string,double,int,double,double)"/> at center "0",
        /// so it shares that method's precision (set by the zoom) and cache.
        /// </summary>
        public static (double[] Re, double[] Im) JuliaCritical(
            double cRe, double cIm, double zoomLog10, int maxIter) =>
            Compute(Kind.Julia, "0", "0", zoomLog10, maxIter, cRe, cIm);

        /// <summary>Z0..ZK for the Burning Ship map, |x| and |y| taken each step.</summary>
        public static (double[] Re, double[] Im) BurningShip(
            string centerRe, string centerIm, double zoomLog10, int maxIter) =>
            Compute(Kind.BurningShip, centerRe, centerIm, zoomLog10, maxIter, 0.0, 0.0);

        internal enum Kind
        {
            Mandelbrot,
            Julia,
            BurningShip,
        }

        // The orbit depends only on (kind, center, precision, max_iter, c) — cache
        // it, as spec/deep-zoom.md "Caching & interactivity" asks, so zooming toward
        // a fixed center does not recompute thousands of bignum multiplies per
        // frame. Least-recently-used eviction at the Python reference's
        // lru_cache(maxsize=8): a Julia render hits its critical orbit every frame,
        // and first-in-first-out would evict it every eighth.
        private const int CacheCapacity = 8;
        private static readonly object CacheLock = new object();
        private static readonly List<string> CacheOrder = new List<string>();
        private static readonly Dictionary<string, (double[] Re, double[] Im)> Cache =
            new Dictionary<string, (double[], double[])>();

        internal static (double[] Re, double[] Im) Compute(
            Kind kind, string centerRe, string centerIm, double zoomLog10, int maxIter,
            double cRe, double cIm)
        {
            if (centerRe == null)
                throw new ArgumentNullException(nameof(centerRe));
            if (centerIm == null)
                throw new ArgumentNullException(nameof(centerIm));
            if (maxIter < 1)
                throw new ArgumentOutOfRangeException(nameof(maxIter), "max_iter must be positive");

            int bits = WorkingBits(centerRe, centerIm, zoomLog10);
            string key = kind + "|" + centerRe + "|" + centerIm + "|" + bits + "|" + maxIter
                         + "|" + cRe.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                         + "|" + cIm.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
            lock (CacheLock)
            {
                if (Cache.TryGetValue(key, out var hit))
                {
                    Touch(key);
                    return hit;
                }
            }

            var computed = Iterate(kind, centerRe, centerIm, bits, maxIter, cRe, cIm);

            lock (CacheLock)
            {
                if (Cache.ContainsKey(key))
                {
                    Touch(key);                                // another thread got here first
                }
                else
                {
                    if (CacheOrder.Count >= CacheCapacity)
                    {
                        Cache.Remove(CacheOrder[0]);
                        CacheOrder.RemoveAt(0);
                    }
                    Cache[key] = computed;
                    CacheOrder.Add(key);
                }
            }
            return computed;
        }

        /// <summary>Mark a cached key most recently used. Caller holds CacheLock.</summary>
        private static void Touch(string key)
        {
            CacheOrder.Remove(key);
            CacheOrder.Add(key);
        }

        /// <summary>Drop every cached orbit (tests; a host reclaiming memory).</summary>
        public static void ClearCache()
        {
            lock (CacheLock)
            {
                Cache.Clear();
                CacheOrder.Clear();
            }
        }

        private static (double[] Re, double[] Im) Iterate(
            Kind kind, string centerRe, string centerIm, int bits, int maxIter,
            double cRe, double cIm)
        {
            BigInteger centerR = ParseFixed(centerRe, bits);
            BigInteger centerI = ParseFixed(centerIm, bits);
            BigInteger zr, zi, cr, ci;
            if (kind == Kind.Julia)
            {
                zr = centerR;
                zi = centerI;
                cr = FromDouble(cRe, bits);
                ci = FromDouble(cIm, bits);
            }
            else
            {
                zr = BigInteger.Zero;
                zi = BigInteger.Zero;
                cr = centerR;
                ci = centerI;
            }

            // The reference loop appends AFTER each step, exactly as the Python
            // reference does, so orbit[0] is Z0 and the length is max_iter + 1
            // unless the escape cutoff cuts it short.
            var re = new List<double>(maxIter + 1) { ToDouble(zr, bits) };
            var im = new List<double>(maxIter + 1) { ToDouble(zi, bits) };
            for (int i = 0; i < maxIter; i++)
            {
                BigInteger nextR = Mul(zr, zr, bits) - Mul(zi, zi, bits) + cr;
                BigInteger nextI = kind == Kind.BurningShip
                    ? 2 * Mul(BigInteger.Abs(zr), BigInteger.Abs(zi), bits) + ci
                    : 2 * Mul(zr, zi, bits) + ci;
                zr = nextR;
                zi = nextI;

                double sr = ToDouble(zr, bits);
                double si = ToDouble(zi, bits);
                re.Add(sr);
                im.Add(si);
                // The escape test runs on the ROUNDED sample, like the reference.
                if (sr * sr + si * si > EscapeAbs2)
                    break;
            }
            return (re.ToArray(), im.ToArray());
        }

        // ---- fixed-point helpers ---------------------------------------------------
        // A real x is held as the BigInteger round(x * 2^bits). Products carry twice
        // the fractional bits, so they are shifted back with round-to-nearest
        // (ties away from zero) rather than truncated — truncation would bias every
        // multiply toward zero and drift the orbit over thousands of iterations.

        internal static BigInteger Mul(BigInteger a, BigInteger b, int bits)
        {
            BigInteger product = a * b;
            BigInteger half = BigInteger.One << (bits - 1);
            if (product.Sign >= 0)
                return (product + half) >> bits;
            return -((-product + half) >> bits);
        }

        /// <summary>Round-to-nearest quotient, ties away from zero. Denominator &gt; 0.</summary>
        private static BigInteger RoundDiv(BigInteger numerator, BigInteger denominator)
        {
            bool negative = numerator.Sign < 0;
            BigInteger n = negative ? -numerator : numerator;
            BigInteger quotient = BigInteger.DivRem(n, denominator, out BigInteger remainder);
            if (remainder * 2 >= denominator)
                quotient += BigInteger.One;
            return negative ? -quotient : quotient;
        }

        /// <summary>
        /// A double is an integer times a power of two, so this is EXACT — decomposed
        /// from the IEEE-754 bit pattern rather than multiplied through floating
        /// point, which would overflow at large working precisions.
        /// </summary>
        internal static BigInteger FromDouble(double value, int bits)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
                throw new ArgumentException("center components must be finite", nameof(value));
            if (value == 0.0)
                return BigInteger.Zero;
            long raw = BitConverter.DoubleToInt64Bits(value);
            bool negative = raw < 0;
            int exponent = (int)((raw >> 52) & 0x7FF);
            long mantissa = raw & 0xFFFFFFFFFFFFFL;
            if (exponent == 0)
                exponent = 1;                 // subnormal
            else
                mantissa |= 1L << 52;         // restore the implicit bit
            exponent -= 1075;                 // value = mantissa * 2^exponent
            int shift = exponent + bits;
            BigInteger scaled = shift >= 0
                ? (BigInteger)mantissa << shift
                : RoundShiftRight(mantissa, -shift);
            return negative ? -scaled : scaled;
        }

        /// <summary>value &gt;&gt; shift, rounded to nearest, ties away from zero.</summary>
        private static BigInteger RoundShiftRight(BigInteger value, int shift)
        {
            if (shift <= 0)
                return value << -shift;
            BigInteger half = BigInteger.One << (shift - 1);
            return (value + half) >> shift;
        }

        /// <summary>
        /// Fixed-point to the nearest double, ties to even — IEEE-754's own rule.
        ///
        /// This must NOT lean on the built-in <c>(double)BigInteger</c> conversion,
        /// which TRUNCATES the mantissa. That was the whole bug: the orbit came out
        /// one ulp low in the imaginary part of Z[1] — which for a Mandelbrot orbit
        /// is simply the parsed center — and extra working precision did not fix it,
        /// because the error was in the final conversion, not the arithmetic.
        ///
        /// Subnormals round the same single time: once a value falls below 2^-1022
        /// its ulp stops shrinking at 2^-1074, so the rounding point moves up, and the
        /// result is assembled from its IEEE-754 bit pattern rather than scaled by a
        /// power of two — a multiply into the subnormal range would round a second
        /// time. Orbit components that small are ordinary at deep zoom (a center with
        /// a tiny imaginary part is one), and the old form threw on them once the
        /// working precision passed 1022 fractional bits, near zoom 268.8.
        /// </summary>
        internal static double ToDouble(BigInteger value, int bits)
        {
            if (value.IsZero)
                return 0.0;
            bool negative = value.Sign < 0;
            BigInteger magnitude = negative ? -value : value;

            // value = magnitude * 2^-bits, leading bit at 2^(length - 1 - bits). The
            // result's ulp is 2^ulp: 53 significant bits while normal, 2^-1074 below.
            int length = DecimalText.BitLength(magnitude);
            int ulp = Math.Max(length - 1 - bits - 52, -1074);
            int shift = ulp + bits;                            // magnitude / 2^shift = value / 2^ulp
            BigInteger q;
            if (shift <= 0)
            {
                q = magnitude << -shift;                       // exact: under 53 bits
            }
            else
            {
                q = magnitude >> shift;
                BigInteger rest = magnitude - (q << shift);
                int versusHalf = rest.CompareTo(BigInteger.One << (shift - 1));
                if (versusHalf > 0 || (versusHalf == 0 && !q.IsEven))
                    q += BigInteger.One;                       // ties to even
            }

            return DecimalText.Compose(negative, q, ulp);
        }

        /// <summary>
        /// Parse a decimal string (the viewport center format — arbitrary length,
        /// language-neutral, spec/deep-zoom.md; grammar in <see cref="DecimalText"/>)
        /// into fixed point WITHOUT going through double, which is the entire point:
        /// the center carries more digits than float64 can hold.
        /// </summary>
        internal static BigInteger ParseFixed(string text, int bits)
        {
            DecimalText.Scan(text, out bool negative, out BigInteger digits, out int netExponent);
            // value = digits * 10^netExponent, scaled by 2^bits.
            BigInteger scaled = digits << bits;
            BigInteger result = netExponent >= 0
                ? scaled * BigInteger.Pow(10, netExponent)
                : RoundDiv(scaled, BigInteger.Pow(10, -netExponent));
            return negative ? -result : result;
        }

        /// <summary>
        /// Fraction digits needed to write a decimal string exactly: digits after the
        /// point minus the exponent, never below 0 ("1e-295" needs 295, "2.5E1" none).
        /// </summary>
        public static int DecimalPlaces(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            DecimalText.Scan(text, out _, out _, out int netExponent);
            return Math.Max(-netExponent, 0);
        }
    }
}
