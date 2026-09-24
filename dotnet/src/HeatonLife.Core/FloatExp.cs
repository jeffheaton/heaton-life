using System;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// A float64 mantissa with an unbounded exponent (spec/floatexp.md): m·2^e with |m| in
    /// [1, 2), or exactly zero as (0, 0). Every operation is one IEEE-754 float64 operation
    /// on mantissas plus exact integer exponent arithmetic, and every rescaling is a
    /// multiply by an exact normal power of two, so the Python reference
    /// (heaton_life.core.floatexp) and this port compute the same bits: add and mul are
    /// correctly rounded (ties to even) with no exponent range limit. No libm call and no
    /// fused multiply-add.
    /// </summary>
    internal readonly struct FloatExp
    {
        internal const int AlignLimit = 64;
        internal const int MinNormalExp = -1022;
        internal const int MaxExp = 1023;

        /// <summary>A result whose exponent falls below this is zero, so exponents never overflow.</summary>
        internal const long ExpFloor = -(1L << 31);

        internal static readonly FloatExp Zero = new FloatExp(0.0, 0L, true);

        internal readonly double M;
        internal readonly long E;

        private FloatExp(double m, long e, bool raw)
        {
            M = m;
            E = e;
        }

        internal bool IsZero => M == 0.0;

        /// <summary>value·2^exponent, normalized (exact).</summary>
        internal static FloatExp Normalize(double value, long exponent)
        {
            if (value == 0.0)
                return Zero;
            if (double.IsNaN(value) || double.IsInfinity(value))
                throw new ArgumentException("floatexp values are finite");
            int k = Binade(value);
            if (exponent + k < ExpFloor)
                return Zero;   // past 2^-(2^31): an iterated square, e.g. at an exact zero of the orbit
            return new FloatExp(ScaleExact(value, -k), exponent + k, true);
        }

        internal static FloatExp FromDouble(double value) => Normalize(value, 0);

        /// <summary>value/2^bits, the integer rounded to 53 significant bits (ties to even, sticky).</summary>
        internal static FloatExp FromFixed(BigInteger value, int bits)
        {
            if (value.IsZero)
                return Zero;
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
            int top = DecimalText.BitLength(q) - 1;   // 53, or 54 when rounding carried
            double m = (double)(long)q * Pow2(-top);   // exact: q has at most 54 bits
            return new FloatExp(value.Sign < 0 ? -m : m, (long)shift + top - bits, true);
        }

        internal FloatExp Neg() => IsZero ? Zero : new FloatExp(-M, E, true);

        internal FloatExp Twice() => IsZero ? Zero : new FloatExp(M, E + 1, true);

        internal static FloatExp Mul(FloatExp a, FloatExp b) =>
            a.IsZero || b.IsZero ? Zero : Normalize(a.M * b.M, a.E + b.E);

        /// <summary>
        /// Correctly rounded a + b: aligned at the larger exponent (exact while the gap is at
        /// most 64), one IEEE add; an operand more than 64 binades down cannot move the result.
        /// </summary>
        internal static FloatExp Add(FloatExp a, FloatExp b)
        {
            if (a.IsZero)
                return b;
            if (b.IsZero)
                return a;
            if (a.E < b.E)
            {
                FloatExp t = a;
                a = b;
                b = t;
            }
            long gap = a.E - b.E;
            if (gap > AlignLimit)
                return a;
            return Normalize(a.M + b.M * Pow2(-(int)gap), a.E);
        }

        internal static FloatExp Sub(FloatExp a, FloatExp b) => Add(a, b.Neg());

        /// <summary>-1, 0 or 1 as a &lt;, =, &gt; b (a total order on values; zero has no sign).</summary>
        internal static int Compare(FloatExp a, FloatExp b)
        {
            int sa = Math.Sign(a.M), sb = Math.Sign(b.M);
            if (sa != sb)
                return sa < sb ? -1 : 1;
            if (sa == 0)
                return 0;
            int c = a.E != b.E ? a.E.CompareTo(b.E) : Math.Abs(a.M).CompareTo(Math.Abs(b.M));
            return c * sa;
        }

        /// <summary>
        /// m·2^e rounded once to a double: exact in the normal range, one correctly rounded
        /// step into the subnormals, signed zero below them, ±∞ past the top.
        /// </summary>
        internal double ToDouble()
        {
            if (IsZero)
                return 0.0;
            if (E > MaxExp)
                return M > 0.0 ? double.PositiveInfinity : double.NegativeInfinity;
            if (E >= MinNormalExp)
                return M * Pow2((int)E);
            if (E >= 2 * MinNormalExp)
                return (M * Pow2((int)E - MinNormalExp)) * Pow2(MinNormalExp);   // exact, then one rounding
            return M < 0.0 ? -0.0 : 0.0;
        }

        /// <summary>This / 2^exponent as a double (ToDouble's rounding).</summary>
        internal double Scaled(long exponent) => IsZero ? 0.0 : new FloatExp(M, E - exponent, true).ToDouble();

        /// <summary>The k with |value| in [2^k, 2^(k+1)), for a finite nonzero double (subnormals too).</summary>
        internal static int Binade(double value)
        {
            long raw = BitConverter.DoubleToInt64Bits(value);
            int field = (int)((raw >> 52) & 0x7FF);
            if (field != 0)
                return field - 1023;
            long mantissa = raw & 0xFFFFFFFFFFFFFL;
            int top = 0;
            while ((mantissa >> (top + 1)) != 0)
                top++;
            return top - 1074;
        }

        /// <summary>2^k for k in [-1022, 1023], exact from the IEEE bits.</summary>
        internal static double Pow2(int k)
        {
            if (k < MinNormalExp || k > MaxExp)
                throw new ArgumentOutOfRangeException(nameof(k), $"2^{k} is not a normal double");
            return BitConverter.Int64BitsToDouble((long)(k + 1023) << 52);
        }

        /// <summary>value·2^k where the result is normal and the scaling therefore exact (two multiplies when 2^k is not normal).</summary>
        internal static double ScaleExact(double value, int k)
        {
            if (k >= MinNormalExp && k <= MaxExp)
                return value * Pow2(k);
            int first = Math.Max(MinNormalExp, Math.Min(MaxExp, k));
            return (value * Pow2(first)) * Pow2(k - first);
        }
    }
}
