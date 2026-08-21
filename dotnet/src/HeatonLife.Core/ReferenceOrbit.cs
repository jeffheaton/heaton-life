using System;
using System.Collections.Generic;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// High-precision reference orbits for the perturbation tier
    /// (spec/deep-zoom.md). The only bignum computation in the fractal pipeline:
    /// one orbit of the viewport centre, so a T1 render needs no externally
    /// supplied data.
    ///
    /// spec/deep-zoom.md "Cross-language notes" sanctions exactly two options for
    /// C#: "fixed-point over System.Numerics.BigInteger for the reference orbit
    /// (only ~max_iter multiplies — cheap), or consume reference orbits exported in
    /// conformance vectors." This is the first; the port shipped only the second
    /// until 2026-08-21, which meant C# could not deep-zoom on its own at all.
    ///
    /// Why fixed point is sound here even though the Python reference uses binary
    /// FLOATING point (gmpy2/mpmath): every orbit sample is rounded to **float64**
    /// before the perturbation loop ever sees it (orbits travel as complex128, and
    /// `Perturbation` takes double[]). The two representations therefore only have
    /// to agree to better than half a double ulp per sample, not bit-for-bit in
    /// their own mantissas. Fixed point holds a CONSTANT absolute precision of
    /// 2^-F, so it is strictly finer than a prec-F float wherever |Z| >= 1 and
    /// stays finer than float64's own resolution until |Z| falls below about
    /// 2^-(F-53) — far under the guard band the precision formula reserves.
    ///
    /// The proof is empirical, not argued: <c>ReferenceOrbitTests</c> regenerates
    /// vectors/mandelbrot/deep-zoom14-48/orbit.c128 and requires all 80,016 bytes
    /// to match the orbit gmpy2 produced.
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
        /// Working precision for a centre at 10^zoom magnification, plus guard.
        /// NOTE the truncation: <c>(int)(3.33 * zoom)</c>, matching the Python
        /// reference's <c>int(3.33 * ...)</c>. spec/deep-zoom.md's "Precision" line
        /// says ceil, but the shipped orbit vector was produced by the truncating
        /// form (46 bits at zoom 14, not 47) and the vector is the contract, so the
        /// spec text is the thing that was wrong. Do not "fix" this to Ceiling
        /// without regenerating every deep-zoom vector.
        /// </summary>
        public static int PrecisionBits(double zoomLog10) =>
            (int)(3.33 * Math.Max(zoomLog10, 0.0)) + GuardBits;

        /// <summary>
        /// Extra FRACTIONAL bits the fixed-point carries beyond
        /// <see cref="PrecisionBits"/>. Fixed point measures precision from the
        /// binary point, a float from the leading digit, so a value below 1 gets
        /// fewer significant bits here than gmpy2 gives it at the same nominal
        /// precision. That bites immediately: a centre of ~0.13 held at 110
        /// fractional bits has ~107 significant bits, and rounding 107 -&gt; 53 in
        /// two steps is only safe above 2*53+2 = 108 — the orbit came out one ulp
        /// off in the imaginary part of Z[1], which for a Mandelbrot orbit IS the
        /// parsed centre. The headroom makes every sample a correctly rounded
        /// double of the true value, which is what gmpy2 at its precision also
        /// produces, so the two agree.
        /// </summary>
        internal const int WorkingGuardBits = 64;

        /// <summary>Z0..ZK for Z -&gt; Z^2 + C with Z0 = 0 and C = the centre.</summary>
        public static (double[] Re, double[] Im) Mandelbrot(
            string centerRe, string centerIm, double zoomLog10, int maxIter) =>
            Compute(Kind.Mandelbrot, centerRe, centerIm, zoomLog10, maxIter, 0.0, 0.0);

        /// <summary>
        /// Z0..ZK for Z -&gt; Z^2 + c with Z0 = the centre and c fixed
        /// (spec/fractals.md: Julia's reference uses the centre's orbit under the
        /// same c, and its delta carries no dc term).
        /// </summary>
        public static (double[] Re, double[] Im) Julia(
            string centerRe, string centerIm, double zoomLog10, int maxIter, double cRe, double cIm) =>
            Compute(Kind.Julia, centerRe, centerIm, zoomLog10, maxIter, cRe, cIm);

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

        // The orbit depends only on (kind, centre, precision, max_iter, c) — cache
        // it, as spec/deep-zoom.md "Caching & interactivity" asks, so zooming toward
        // a fixed centre does not recompute thousands of bignum multiplies per
        // frame. Same capacity as the Python reference's lru_cache(maxsize=8).
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

            int bits = PrecisionBits(zoomLog10) + WorkingGuardBits;
            string key = kind + "|" + centerRe + "|" + centerIm + "|" + bits + "|" + maxIter
                         + "|" + cRe.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                         + "|" + cIm.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
            lock (CacheLock)
            {
                if (Cache.TryGetValue(key, out var hit))
                    return hit;
            }

            var computed = Iterate(kind, centerRe, centerIm, bits, maxIter, cRe, cIm);

            lock (CacheLock)
            {
                if (!Cache.ContainsKey(key))
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
                throw new ArgumentException("centre components must be finite", nameof(value));
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
        /// is simply the parsed centre — and extra working precision did not fix it,
        /// because the error was in the final conversion, not the arithmetic.
        /// </summary>
        internal static double ToDouble(BigInteger value, int bits)
        {
            if (value.IsZero)
                return 0.0;
            bool negative = value.Sign < 0;
            BigInteger magnitude = negative ? -value : value;
            int length = BitLength(magnitude);
            double result;
            if (length <= 53)
            {
                // Fits a double exactly; no rounding decision to make.
                result = (double)magnitude * Pow2(-bits);
            }
            else
            {
                int shift = length - 54;                       // keep 53 bits + a guard bit
                BigInteger top = magnitude >> shift;
                bool sticky = !(magnitude - (top << shift)).IsZero;
                bool guard = !(top & BigInteger.One).IsZero;
                BigInteger rounded = top >> 1;
                if (guard && (sticky || !(rounded & BigInteger.One).IsZero))
                    rounded += BigInteger.One;                 // ties to even
                result = (double)rounded * Pow2(shift + 1 - bits);
            }
            return negative ? -result : result;
        }

        /// <summary>Position of the highest set bit of a positive BigInteger.</summary>
        private static int BitLength(BigInteger value)
        {
            byte[] bytes = value.ToByteArray();               // little-endian, two's complement
            int i = bytes.Length - 1;
            while (i > 0 && bytes[i] == 0)
                i--;
            int top = bytes[i];
            int inTop = 0;
            while (top > 0)
            {
                inTop++;
                top >>= 1;
            }
            return i * 8 + inTop;
        }

        /// <summary>
        /// 2^n as an exact double, built from its IEEE-754 bit pattern.
        /// netstandard2.1 has no Math.ScaleB, and Math.Pow would put a libm call on
        /// a determinism-critical path — this is exact by construction on every
        /// runtime.
        /// </summary>
        internal static double Pow2(int n)
        {
            if (n < -1022 || n > 1023)
                throw new ArgumentOutOfRangeException(nameof(n), $"2^{n} is outside the normal range");
            return BitConverter.Int64BitsToDouble((long)(n + 1023) << 52);
        }

        /// <summary>
        /// Parse a decimal string (the viewport centre format — arbitrary length,
        /// language-neutral, spec/deep-zoom.md) into fixed point WITHOUT going
        /// through double, which is the entire point: the centre carries more
        /// digits than float64 can hold. Hand-rolled because Core takes no Regex.
        /// </summary>
        internal static BigInteger ParseFixed(string text, int bits)
        {
            if (string.IsNullOrWhiteSpace(text))
                throw new ArgumentException("empty decimal string", nameof(text));
            string s = text.Trim();
            int i = 0;
            bool negative = false;
            if (s[i] == '+' || s[i] == '-')
            {
                negative = s[i] == '-';
                i++;
            }

            BigInteger digits = BigInteger.Zero;
            int fractionDigits = 0;
            bool sawDigit = false;
            bool sawPoint = false;
            bool sawExponent = false;
            for (; i < s.Length; i++)
            {
                char c = s[i];
                if (c >= '0' && c <= '9')
                {
                    digits = digits * 10 + (c - '0');
                    if (sawPoint)
                        fractionDigits++;
                    sawDigit = true;
                }
                else if (c == '.' && !sawPoint)
                {
                    sawPoint = true;
                }
                else if ((c == 'e' || c == 'E') && sawDigit)
                {
                    i++;
                    sawExponent = true;
                    break;
                }
                else
                {
                    throw new ArgumentException($"not a decimal number: '{text}'", nameof(text));
                }
            }
            if (!sawDigit)
                throw new ArgumentException($"not a decimal number: '{text}'", nameof(text));

            int exponent = 0;
            if (sawExponent && i >= s.Length)
                throw new ArgumentException($"truncated exponent: '{text}'", nameof(text));
            if (i < s.Length)
            {
                bool expNegative = false;
                if (s[i] == '+' || s[i] == '-')
                {
                    expNegative = s[i] == '-';
                    i++;
                }
                if (i >= s.Length)
                    throw new ArgumentException($"truncated exponent: '{text}'", nameof(text));
                for (; i < s.Length; i++)
                {
                    char c = s[i];
                    if (c < '0' || c > '9')
                        throw new ArgumentException($"not a decimal number: '{text}'", nameof(text));
                    exponent = exponent * 10 + (c - '0');
                    if (exponent > 100000)
                        throw new ArgumentException($"exponent out of range: '{text}'", nameof(text));
                }
                if (expNegative)
                    exponent = -exponent;
            }

            // value = digits * 10^(exponent - fractionDigits), scaled by 2^bits.
            int netExponent = exponent - fractionDigits;
            BigInteger scaled = digits << bits;
            BigInteger result = netExponent >= 0
                ? scaled * BigInteger.Pow(10, netExponent)
                : RoundDiv(scaled, BigInteger.Pow(10, -netExponent));
            return negative ? -result : result;
        }
    }
}
