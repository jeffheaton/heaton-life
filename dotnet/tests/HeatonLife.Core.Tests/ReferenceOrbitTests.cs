using System;
using System.IO;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The acceptance test for C#-side reference orbits: regenerate the orbit that
    /// gmpy2 produced for the shipped deep-zoom vector and require it to match
    /// byte for byte. spec/deep-zoom.md sanctions BigInteger fixed point as an
    /// alternative to gmpy2/mpmath, and this is what "sanctioned" has to mean in a
    /// repo whose identity is that every port agrees — the vector is the oracle,
    /// not an argument about rounding.
    /// </summary>
    public class ReferenceOrbitTests
    {
        private const string CaseDir = "mandelbrot/deep-zoom14-48";
        private const string CenterRe = "-0.743643887037158704752191506114774";
        private const string CenterIm = "0.131825904205311970493132056385139";
        private const double Zoom = 14.0;
        private const int MaxIter = 5000;

        [Fact]
        public void MatchesTheShippedGmpy2OrbitByteForByte()
        {
            string path = Path.Combine(TestPaths.VectorRoot(), CaseDir, "orbit.c128");
            byte[] expected = File.ReadAllBytes(path);
            Assert.Equal(5001 * 16, expected.Length); // complex128 pairs

            var (re, im) = ReferenceOrbit.Mandelbrot(CenterRe, CenterIm, Zoom, MaxIter);
            Assert.Equal(5001, re.Length);
            Assert.Equal(5001, im.Length);

            // Re-encode exactly as the vector stores it: interleaved little-endian
            // f64 pairs, real first.
            var actual = new byte[re.Length * 16];
            for (int i = 0; i < re.Length; i++)
            {
                WriteLe(actual, i * 16, re[i]);
                WriteLe(actual, i * 16 + 8, im[i]);
            }

            // Report the FIRST divergence rather than a bare "arrays differ": the
            // iteration index is the whole diagnostic if this ever regresses.
            for (int i = 0; i < re.Length; i++)
            {
                double expRe = BitConverter.ToDouble(expected, i * 16);
                double expIm = BitConverter.ToDouble(expected, i * 16 + 8);
                Assert.True(
                    BitConverter.DoubleToInt64Bits(expRe) == BitConverter.DoubleToInt64Bits(re[i]) &&
                    BitConverter.DoubleToInt64Bits(expIm) == BitConverter.DoubleToInt64Bits(im[i]),
                    $"orbit diverges at Z[{i}]: expected ({expRe:R}, {expIm:R}), got ({re[i]:R}, {im[i]:R})");
            }
            Assert.Equal(expected, actual);
        }

        /// <summary>
        /// The precision formula truncates, matching the Python reference's
        /// int(3.33 * zoom) + 64. spec/deep-zoom.md says ceil, but the shipped
        /// vector was produced by the truncating form and the vector wins.
        /// </summary>
        [Fact]
        public void PrecisionFormulaTruncatesLikeTheReference()
        {
            Assert.Equal(64, ReferenceOrbit.PrecisionBits(0.0));
            Assert.Equal(64, ReferenceOrbit.PrecisionBits(-5.0));   // clamped at 0
            Assert.Equal(110, ReferenceOrbit.PrecisionBits(14.0));  // int(46.62) + 64
            Assert.Equal(102, ReferenceOrbit.PrecisionBits(11.5));  // int(38.295) = 38, + 64
        }

        /// <summary>
        /// Decimal centres are parsed WITHOUT passing through double — the reason
        /// the viewport carries strings at all. A 33-digit centre round-trips to
        /// far more precision than float64 could hold.
        /// </summary>
        [Fact]
        public void ParsesMorePrecisionThanADoubleCanHold()
        {
            const int bits = 200;
            var exact = ReferenceOrbit.ParseFixed(CenterRe, bits);
            var viaDouble = ReferenceOrbit.FromDouble(double.Parse(
                CenterRe, System.Globalization.CultureInfo.InvariantCulture), bits);
            Assert.NotEqual(exact, viaDouble);

            // Simple values are exact either way.
            Assert.Equal(BigIntegerOne(bits), ReferenceOrbit.ParseFixed("1", bits));
            Assert.Equal(BigIntegerOne(bits), ReferenceOrbit.ParseFixed("1.0", bits));
            Assert.Equal(-BigIntegerOne(bits), ReferenceOrbit.ParseFixed("-1", bits));
            Assert.Equal(System.Numerics.BigInteger.Zero, ReferenceOrbit.ParseFixed("0.0", bits));
            Assert.Equal(BigIntegerOne(bits) / 2, ReferenceOrbit.ParseFixed("0.5", bits));
            Assert.Equal(BigIntegerOne(bits) / 4, ReferenceOrbit.ParseFixed("2.5e-1", bits));
            Assert.Equal(BigIntegerOne(bits) * 25, ReferenceOrbit.ParseFixed("2.5E1", bits));
        }

        [Theory]
        [InlineData("")]
        [InlineData("   ")]
        [InlineData("abc")]
        [InlineData("1.2.3")]
        [InlineData("1e")]
        [InlineData("1e+")]
        [InlineData("--1")]
        public void RejectsMalformedCentres(string bad)
        {
            Assert.Throws<ArgumentException>(() => ReferenceOrbit.ParseFixed(bad, 64));
        }

        [Fact]
        public void ShortOrbitsAreExpectedWhenTheCentreItselfEscapes()
        {
            // A centre well outside the set escapes in a handful of steps, so the
            // orbit is far shorter than max_iter + 1. Both ports clamp the
            // reference index to the last sample, which is why this is legal.
            var (re, im) = ReferenceOrbit.Mandelbrot("2.0", "2.0", 13.0, 500);
            Assert.True(re.Length < 501, $"expected an early stop, got {re.Length}");
            Assert.Equal(re.Length, im.Length);
            double lastAbs2 = re[re.Length - 1] * re[re.Length - 1]
                              + im[im.Length - 1] * im[im.Length - 1];
            Assert.True(lastAbs2 > ReferenceOrbit.EscapeAbs2);
        }

        private static System.Numerics.BigInteger BigIntegerOne(int bits) =>
            System.Numerics.BigInteger.One << bits;

        private static void WriteLe(byte[] destination, int offset, double value)
        {
            long bits = BitConverter.DoubleToInt64Bits(value);
            for (int b = 0; b < 8; b++)
                destination[offset + b] = (byte)(bits >> (8 * b));
        }
    }
}
