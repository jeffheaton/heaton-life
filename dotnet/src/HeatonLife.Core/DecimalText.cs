using System;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// The decimal-string grammar of viewport centers (spec/deep-zoom.md "Viewport
    /// contract"), and exact conversions out of it. One grammar for every consumer —
    /// <see cref="Viewport"/> validation, the fixed-point orbit parse
    /// (<see cref="ReferenceOrbit"/>), and the float64 projection T0 renders from — and
    /// the same one the Python reference scans (core/decimal_text.py):
    ///
    ///     [ws] [+|-] digits-with-at-most-one-point [ (e|E) [+|-] digits ] [ws]
    ///
    /// At least one digit before the exponent (".5" and "5." are fine, "." is not); at
    /// most 10,000 digits before it; exponent magnitude at most 100,000; ASCII digits
    /// only; surrounding ASCII spaces, tabs, CRs and LFs are ignored. No NaN, no
    /// infinities. The two bounds keep parsing and the orbit precision finite for any
    /// string a caller can hand in. Hand-rolled because Core takes no Regex.
    /// </summary>
    internal static class DecimalText
    {
        internal const int MaxDigits = 10000;
        internal const int MaxExponent = 100000;

        private static readonly char[] Whitespace = { ' ', '\t', '\r', '\n' };

        /// <summary>
        /// Split a decimal string into sign, digits and net exponent (value = digits *
        /// 10^netExponent); ArgumentException for anything outside the grammar.
        /// </summary>
        internal static void Scan(string text, out bool negative, out BigInteger digits, out int netExponent)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            string s = text.Trim(Whitespace);
            if (s.Length == 0)
                throw new ArgumentException("empty decimal string", nameof(text));
            int i = 0;
            negative = false;
            if (s[i] == '+' || s[i] == '-')
            {
                negative = s[i] == '-';
                i++;
            }

            digits = BigInteger.Zero;
            int digitCount = 0;
            int fractionDigits = 0;
            bool sawDigit = false;
            bool sawPoint = false;
            bool sawExponent = false;
            for (; i < s.Length; i++)
            {
                char c = s[i];
                if (c >= '0' && c <= '9')
                {
                    if (++digitCount > MaxDigits)
                        throw new ArgumentException($"more than {MaxDigits} digits", nameof(text));
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
                    if (exponent > MaxExponent)
                        throw new ArgumentException($"exponent out of range: '{text}'", nameof(text));
                }
                if (expNegative)
                    exponent = -exponent;
            }
            netExponent = exponent - fractionDigits;
        }

        /// <summary>
        /// The double nearest a decimal string's exact value: one rounding, ties to
        /// even, subnormals like everything else, infinities past the float64 range,
        /// and "-0" as -0.0 — what CPython's correctly rounded float() gives. Computed
        /// from the digits because <c>double.Parse</c> is only guaranteed correctly
        /// rounded on .NET Core 3.0+, and Unity runs Core on Mono and IL2CPP.
        /// </summary>
        internal static double ToDouble(string text)
        {
            Scan(text, out bool negative, out BigInteger digits, out int netExponent);
            if (digits.IsZero)
                return negative ? -0.0 : 0.0;
            return netExponent >= 0
                ? RatioToDouble(negative, digits * BigInteger.Pow(10, netExponent), BigInteger.One)
                : RatioToDouble(negative, digits, BigInteger.Pow(10, -netExponent));
        }

        /// <summary>
        /// ±numerator/denominator (both positive) to the nearest double, ties to even,
        /// with IEEE-754's subnormal and overflow behavior.
        /// </summary>
        internal static double RatioToDouble(bool negative, BigInteger numerator, BigInteger denominator)
        {
            // The value lies in (2^(e-1), 2^(e+1)); its floor(log2) is e or e - 1.
            int e = BitLength(numerator) - BitLength(denominator);
            bool atLeast = e >= 0
                ? numerator >= denominator << e
                : numerator << -e >= denominator;
            int floorLog2 = atLeast ? e : e - 1;
            if (floorLog2 >= 1024)
                return negative ? double.NegativeInfinity : double.PositiveInfinity;
            if (floorLog2 < -1075)
                return negative ? -0.0 : 0.0;                  // below half the smallest subnormal

            // Round once, at the result's ulp: 53 significant bits while normal,
            // 2^-1074 below.
            int ulp = Math.Max(floorLog2 - 52, -1074);
            BigInteger n = ulp >= 0 ? numerator : numerator << -ulp;
            BigInteger d = ulp >= 0 ? denominator << ulp : denominator;
            BigInteger q = BigInteger.DivRem(n, d, out BigInteger remainder);
            int versusHalf = (remainder << 1).CompareTo(d);
            if (versusHalf > 0 || (versusHalf == 0 && !q.IsEven))
                q += BigInteger.One;
            return Compose(negative, q, ulp);
        }

        /// <summary>
        /// ±q * 2^ulp assembled from its IEEE-754 bit pattern, where q &lt;= 2^53 is
        /// already rounded at that ulp (normal when q &gt;= 2^52, else subnormal with
        /// ulp = -1074). No floating-point operation runs, so nothing rounds twice.
        /// </summary>
        internal static double Compose(bool negative, BigInteger q, int ulp)
        {
            long mantissa = (long)q;
            if (mantissa == 1L << 53)
            {
                mantissa >>= 1;                                // rounding carried into the next binade
                ulp++;
            }
            long pattern;
            if (mantissa >= 1L << 52)
            {
                int biased = ulp + 52 + 1023;
                if (biased >= 2047)
                    return negative ? double.NegativeInfinity : double.PositiveInfinity;
                pattern = ((long)biased << 52) | (mantissa & ((1L << 52) - 1));
            }
            else
            {
                pattern = mantissa;                            // subnormal (or zero): exponent field 0
            }
            double result = BitConverter.Int64BitsToDouble(pattern);
            return negative ? -result : result;
        }

        /// <summary>Position of the highest set bit of a positive BigInteger.</summary>
        internal static int BitLength(BigInteger value)
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
    }
}
