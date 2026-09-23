using System;
using System.Globalization;
using System.Numerics;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The viewport-center grammar and its exact float64 projection (DecimalText;
    /// Python: core/decimal_text.py, whose test mirrors the grammar lists below).
    /// </summary>
    public class DecimalTextTests
    {
        public static readonly string[] Accepted =
        {
            "0", "-0", "+1", "5.", ".5", "-.5e-3", "1e5", "1E+5", "1e-005", "2.5E1",
            " 1 ", "\t-2.5e-3\n", "00012.3400", "1e100000",
        };

        public static readonly string[] Rejected =
        {
            "", " ", ".", "e5", "1e", "1e+", "--1", "+-1", "1.2.3", "1e5.5", "1e100001",
            "NaN", "nan", "Infinity", "-Inf", "1_000", "1,000", "0x10", "\u0661\u0662", "1 2",
        };

        [Fact]
        public void GrammarAcceptsAndRejectsExactlyTheSharedLists()
        {
            foreach (string s in Accepted)
                DecimalText.Scan(s, out _, out _, out _);
            foreach (string s in Rejected)
                Assert.Throws<ArgumentException>(() => DecimalText.Scan(s, out _, out _, out _));
        }

        [Fact]
        public void DigitCountIsBounded()
        {
            DecimalText.Scan(new string('1', DecimalText.MaxDigits), out _, out _, out _);
            DecimalText.Scan("0." + new string('1', DecimalText.MaxDigits - 1), out _, out _, out _);
            Assert.Throws<ArgumentException>(() =>
                DecimalText.Scan(new string('1', DecimalText.MaxDigits + 1), out _, out _, out _));
            Assert.Throws<ArgumentException>(() =>
                DecimalText.Scan("0." + new string('1', DecimalText.MaxDigits), out _, out _, out _));
        }

        [Fact]
        public void ViewportRefusesWhatTheOrbitParserCannotRead()
        {
            foreach (string s in new[] { "NaN", "Infinity", "1_000", "\u0661\u0662" })
            {
                Assert.Throws<ArgumentException>(() => new Viewport(s, "0", 0.0));
                Assert.Throws<ArgumentException>(() => new Viewport("0", s, 0.0));
            }
            Assert.Throws<ArgumentNullException>(() => new Viewport(null!, "0", 0.0));
        }

        /// <summary>.NET Core 3.0+ parses correctly rounded; the exact projection must agree bit for bit.</summary>
        [Fact]
        public void ProjectionMatchesCorrectlyRoundedParsing()
        {
            var random = new Random(11);
            for (int i = 0; i < 20000; i++)
            {
                int length = random.Next(1, 41);
                var chars = new char[length];
                for (int k = 0; k < length; k++)
                    chars[k] = (char)('0' + random.Next(10));
                string digits = new string(chars);
                int point = random.Next(0, length + 1);
                string text = (random.Next(2) == 0 ? "-" : "") + digits.Substring(0, point) + "." + digits.Substring(point)
                              + "e" + random.Next(-400, 400).ToString(CultureInfo.InvariantCulture);
                if (text.StartsWith(".e") || text.StartsWith("-.e"))
                    continue;
                double expected = double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);
                Assert.True(
                    BitConverter.DoubleToInt64Bits(expected) == BitConverter.DoubleToInt64Bits(DecimalText.ToDouble(text)),
                    $"{text}: expected {expected:R}");
            }
        }

        /// <summary>
        /// Exact decimal midpoints between neighboring doubles — normal, subnormal, and
        /// at the top of the range — go to the even neighbor; one unit in the last
        /// digit either side goes to the nearer one. Known answers, no second parser.
        /// </summary>
        [Fact]
        public void MidpointsRoundToEvenEverywhere()
        {
            var random = new Random(5);
            var patterns = new System.Collections.Generic.List<long>
            {
                0L, 1L, 2L, (1L << 52) - 1, 1L << 52,                     // subnormal edge
                BitConverter.DoubleToInt64Bits(1.0), BitConverter.DoubleToInt64Bits(9007199254740992.0),
                BitConverter.DoubleToInt64Bits(double.MaxValue) - 1,
            };
            for (int i = 0; i < 3000; i++)
            {
                long exponentField = random.Next(0, 2047);
                long mantissa = ((long)random.Next() << 21) ^ random.Next();
                patterns.Add((exponentField << 52) | (mantissa & ((1L << 52) - 1)));
            }

            foreach (long pattern in patterns)
            {
                double low = BitConverter.Int64BitsToDouble(pattern);
                double high = BitConverter.Int64BitsToDouble(pattern + 1);
                if (double.IsInfinity(high))
                    continue;
                // low = m * 2^x exactly; the midpoint is (2m + 1) * 2^(x - 1).
                long field = (pattern >> 52) & 0x7FF;
                long m = pattern & ((1L << 52) - 1);
                int x;
                if (field == 0)
                {
                    x = -1074;
                }
                else
                {
                    m |= 1L << 52;
                    x = (int)field - 1075;
                }
                BigInteger odd = 2 * (BigInteger)m + 1;
                int power = x - 1;                                 // midpoint = odd * 2^power
                BigInteger scaled = power >= 0 ? odd << power : odd * BigInteger.Pow(5, -power);
                int exponent = power >= 0 ? 0 : power;             // decimal: scaled * 10^exponent
                string Text(BigInteger v) => v.ToString(CultureInfo.InvariantCulture) + "e"
                    + exponent.ToString(CultureInfo.InvariantCulture);

                double even = (pattern & 1) == 0 ? low : high;
                Assert.Equal(even, DecimalText.ToDouble(Text(scaled)));
                Assert.Equal(-even, DecimalText.ToDouble("-" + Text(scaled)));
                Assert.Equal(low, DecimalText.ToDouble(Text(scaled - 1)));
                Assert.Equal(high, DecimalText.ToDouble(Text(scaled + 1)));
            }
        }

        [Fact]
        public void OverflowUnderflowAndSignedZero()
        {
            Assert.Equal(double.MaxValue, DecimalText.ToDouble("1.7976931348623157e308"));
            Assert.Equal(double.PositiveInfinity, DecimalText.ToDouble("1e400"));
            Assert.Equal(double.NegativeInfinity, DecimalText.ToDouble("-1e100000"));
            // Halfway between MaxValue (odd mantissa) and 2^1024 rounds to even: infinity.
            BigInteger half = (2 * ((BigInteger.One << 53) - 1) + 1) << 970;
            Assert.Equal(double.PositiveInfinity, DecimalText.ToDouble(half.ToString(CultureInfo.InvariantCulture)));
            Assert.Equal(double.MaxValue, DecimalText.ToDouble((half - 1).ToString(CultureInfo.InvariantCulture)));

            Assert.Equal(0.0, DecimalText.ToDouble("1e-400"));
            Assert.Equal(double.Epsilon, DecimalText.ToDouble("4.9406564584124654e-324"));
            Assert.Equal(BitConverter.DoubleToInt64Bits(-0.0), BitConverter.DoubleToInt64Bits(DecimalText.ToDouble("-0.000")));
            Assert.Equal(BitConverter.DoubleToInt64Bits(-0.0), BitConverter.DoubleToInt64Bits(DecimalText.ToDouble("-1e-400")));
        }
    }
}
