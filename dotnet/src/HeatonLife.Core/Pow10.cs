using System;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// Deterministic power of ten (spec/pow10.md). The fractal pixel scale is a
    /// bit-exact conformance output computed from 10^-zoom, and Math.Pow is a
    /// libm call — platform libms legitimately disagree in the last ulp
    /// (Windows UCRT rounds pow(10, 0.2) one ulp below macOS libm, measured
    /// 2026-08-21 as flipped escape counts in vectors/burning-ship/home-64;
    /// numpy's vendored routines differ from both). Like Pcg32, this replaces
    /// the platform primitive with a fixed integer algorithm: BigInteger all
    /// the way to the final ties-to-even rounding, so every implementation
    /// computes the same bits. Ported expression-for-expression from the
    /// Python reference (heaton_life.core.pow10).
    /// </summary>
    public static class Pow10
    {
        private const int F = 128; // fixed-point fraction bits (Q128)

        // round(log2(10) * 2^128) and round(ln(2) * 2^128) — spec/pow10.md appendix.
        private static readonly BigInteger Log2Of10Q128 =
            BigInteger.Parse("1130393554869435518674010122299176348979");
        private static readonly BigInteger Ln2Q128 =
            BigInteger.Parse("235865763225513294137944142764154484399");

        /// <summary>
        /// 10^x as float64 via the spec/pow10.md integer algorithm (bit-portable).
        /// Domain: finite |x| &lt;= 300 (deep-zoom.md's tier ceiling is 290;
        /// results stay normal). Throws <see cref="ArgumentException"/> outside it.
        /// </summary>
        public static double Compute(double x)
        {
            if (double.IsNaN(x) || double.IsInfinity(x) || Math.Abs(x) > 300.0)
                throw new ArgumentException($"pow10 domain is finite |x| <= 300, got {x}");
            if (x == 0.0)
                return 1.0;

            // 1. Exact decompose: x = m * 2^e, sign carried by m.
            long bits = BitConverter.DoubleToInt64Bits(x);
            int expField = (int)((bits >> 52) & 0x7FF);
            long frac = bits & 0xFFFFFFFFFFFFFL;
            long m;
            int e;
            if (expField == 0)
            {
                m = frac; // subnormal (|x| <= 300 never is, but exactness is free)
                e = -1074;
            }
            else
            {
                m = frac | (1L << 52);
                e = expField - 1075;
            }
            if (bits < 0)
                m = -m;

            // 2. Y ~= x * log2(10) in Q128. BigInteger right shift floors
            //    (toward -inf) for negatives, matching Python — required by spec.
            BigInteger y = e >= 0
                ? (m * Log2Of10Q128) << e
                : (m * Log2Of10Q128) >> -e;

            // 3. Split into binary exponent and fraction in [0, 2^F).
            BigInteger nBig = y >> F;
            BigInteger f = y - (nBig << F);
            int n = (int)nBig;

            // 4. t ~= frac * ln(2), in [0, ln 2).
            BigInteger t = (f * Ln2Q128) >> F;

            // 5. exp(t) * 2^F by Taylor; every operand non-negative, so C#'s
            //    truncating division matches Python's floor division.
            BigInteger acc = BigInteger.One << F;
            BigInteger term = BigInteger.One << F;
            for (int k = 1; ; k++)
            {
                term = ((term * t) >> F) / k;
                if (term.IsZero)
                    break;
                acc += term;
            }

            // 6. Round to a 53-bit mantissa, ties-to-even. acc is in [2^F, 2^(F+1)).
            const int shift = F + 1 - 53;
            BigInteger mant = acc >> shift;
            BigInteger rem = acc - (mant << shift);
            BigInteger half = BigInteger.One << (shift - 1);
            if (rem > half || (rem == half && !mant.IsEven))
                mant += 1;
            if (mant == BigInteger.One << 53)
            {
                mant = BigInteger.One << 52;
                n += 1;
            }

            // 7. Assemble the IEEE-754 double directly — no ldexp, no libm.
            long assembled = ((long)(n + 1023) << 52) | (long)(mant - (BigInteger.One << 52));
            return BitConverter.Int64BitsToDouble(assembled);
        }
    }
}
