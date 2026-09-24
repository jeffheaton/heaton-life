using System;
using System.Globalization;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// Pinned cosine and sine of a rational number of turns (spec/turns.md): (cos 2πk/n,
    /// sin 2πk/n) as float64 from integer arithmetic alone — the turn reduced exactly to a
    /// quarter-turn quadrant, the angle in fixed point with 192 fraction bits against a
    /// pinned π/2, a Taylor series with floor divisions, and one correct rounding (ties to
    /// even) of each result. No libm, so every platform gives the Python reference's
    /// (heaton_life.core.turns) bits. Quarter turns are exact.
    /// </summary>
    internal static class Turns
    {
        internal const int FractionBits = 192;

        /// <summary>floor(π/2 · 2^192), pinned.</summary>
        private static readonly BigInteger HalfPi = BigInteger.Parse(
            "01921FB54442D18469898CC51701B839A252049C1114CF98E8", NumberStyles.HexNumber, CultureInfo.InvariantCulture);

        private static readonly BigInteger One = BigInteger.One << FractionBits;

        /// <summary>(cos, sin) of 2πk/n for 1 ≤ n ≤ 2^61; zero components are +0.0.</summary>
        internal static (double Re, double Im) Cis(long k, long n)
        {
            if (n < 1 || n > (1L << 61))
                throw new ArgumentOutOfRangeException(nameof(n), $"n must lie in [1, 2^61], got {n}");
            k %= n;
            if (k < 0)
                k += n;
            long q = 4 * k / n, r = 4 * k % n;
            CosSin(HalfPi * r / n, out BigInteger c, out BigInteger s);
            BigInteger re, im;
            switch (q)
            {
                case 0: re = c; im = s; break;
                case 1: re = -s; im = c; break;
                case 2: re = -c; im = -s; break;
                default: re = s; im = -c; break;
            }
            return (ReferenceOrbit.ToDouble(re, FractionBits), ReferenceOrbit.ToDouble(im, FractionBits));
        }

        /// <summary>
        /// cos and sin of x/2^F for 0 ≤ x &lt; (π/2)·2^F in the same fixed point: each Taylor term
        /// floor((prev·x²/2^F)/(m(m + 1))), summed with alternating signs until a term is 0.
        /// </summary>
        private static void CosSin(BigInteger x, out BigInteger c, out BigInteger s)
        {
            BigInteger x2 = (x * x) >> FractionBits;
            s = x;
            BigInteger term = x;
            int sign = -1;
            for (long m = 2; ; m += 2)
            {
                term = ((term * x2) >> FractionBits) / (m * (m + 1));
                if (term.IsZero)
                    break;
                s += sign * term;
                sign = -sign;
            }
            c = One;
            term = One;
            sign = -1;
            for (long m = 1; ; m += 2)
            {
                term = ((term * x2) >> FractionBits) / (m * (m + 1));
                if (term.IsZero)
                    break;
                c += sign * term;
                sign = -sign;
            }
        }
    }
}
