using System;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The acceptance tests for C#-side reference orbits: regenerate every orbit the
    /// Python reference pinned into a vector and require it byte for byte. Both
    /// ports run the same fixed-point integer arithmetic (spec/deep-zoom.md
    /// "Reference orbit"), and in a repo whose identity is that every port agrees,
    /// the vector is the oracle, not an argument about rounding.
    /// </summary>
    public class ReferenceOrbitTests
    {
        private const string CenterRe = "-0.743643887037158704752191506114774";

        /// <summary>Every fractal vector that stores a reference orbit.</summary>
        public static IEnumerable<object[]> OrbitCases()
        {
            foreach (string family in new[] { "mandelbrot", "julia", "burning-ship" })
                foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), family)))
                    if (File.ReadAllText(Path.Combine(dir, "params.json")).Contains("\"reference_orbit\""))
                        yield return new object[] { family + "/" + Path.GetFileName(dir) };
        }

        /// <summary>
        /// C# regenerates every stored orbit byte for byte — the reference orbit and,
        /// for Julia, the critical orbit. Both ports run the same fixed-point integer
        /// arithmetic (spec/deep-zoom.md "Reference orbit"), so this holds for any
        /// center and length, not only for the well-behaved ones.
        /// </summary>
        [Theory]
        [MemberData(nameof(OrbitCases))]
        public void RegeneratesEveryShippedOrbitByteForByte(string caseDir)
        {
            string dir = Path.Combine(TestPaths.VectorRoot(), caseDir);
            using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            var root = doc.RootElement;
            var viewport = root.GetProperty("viewport");
            var p = root.GetProperty("params");
            // The orbit is the reference point's: the center unless the viewport names another.
            bool offCenter = viewport.TryGetProperty("reference_re", out _);
            string centerRe = viewport.GetProperty(offCenter ? "reference_re" : "center_re").GetString()!;
            string centerIm = viewport.GetProperty(offCenter ? "reference_im" : "center_im").GetString()!;
            double zoom = viewport.GetProperty("zoom_log10").GetDouble();
            int maxIter = p.GetProperty("max_iter").GetInt32();
            string family = root.GetProperty("family").GetString()!;

            (double[] Re, double[] Im) orbit = family switch
            {
                "julia" => ReferenceOrbit.Julia(
                    centerRe, centerIm, zoom, maxIter,
                    p.GetProperty("c_re").GetDouble(), p.GetProperty("c_im").GetDouble()),
                "burning-ship" => ReferenceOrbit.BurningShip(centerRe, centerIm, zoom, maxIter),
                _ => ReferenceOrbit.Mandelbrot(centerRe, centerIm, zoom, maxIter),
            };
            var orbitMeta = root.GetProperty("reference_orbit");
            Assert.Equal(orbitMeta.GetProperty("length").GetInt32(), orbit.Re.Length);
            AssertMatchesFile(orbit.Re, orbit.Im, Path.Combine(dir, orbitMeta.GetProperty("file").GetString()!));

            if (root.TryGetProperty("critical_orbit", out var criticalMeta))
            {
                var critical = ReferenceOrbit.JuliaCritical(
                    p.GetProperty("c_re").GetDouble(), p.GetProperty("c_im").GetDouble(), zoom, maxIter);
                Assert.Equal(criticalMeta.GetProperty("length").GetInt32(), critical.Re.Length);
                AssertMatchesFile(critical.Re, critical.Im, Path.Combine(dir, criticalMeta.GetProperty("file").GetString()!));
            }
        }

        /// <summary>
        /// The full 139,166-sample orbit of Dinkydau's 256-place "11 Dimensions" center at
        /// zoom 160, pinned by SHA-256 — too long to ship (2.2 MB), so both suites assert
        /// the same digest (Python: test_fractal.py). While Python iterated in floating
        /// point this orbit parted from the C# one at sample 67,941.
        /// </summary>
        [Fact]
        public void LongCenterOrbitMatchesThePythonDigest()
        {
            string dir = Path.Combine(TestPaths.VectorRoot(), "mandelbrot", "deep-zoom20-11dim-32");
            using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            var viewport = doc.RootElement.GetProperty("viewport");
            var (re, im) = ReferenceOrbit.Mandelbrot(
                viewport.GetProperty("center_re").GetString()!,
                viewport.GetProperty("center_im").GetString()!,
                160.0, 200000);
            Assert.Equal(139166, re.Length);
            var bytes = new byte[re.Length * 16];
            for (int i = 0; i < re.Length; i++)
            {
                WriteLe(bytes, i * 16, re[i]);
                WriteLe(bytes, i * 16 + 8, im[i]);
            }
            using var sha = System.Security.Cryptography.SHA256.Create();
            string digest = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
            Assert.Equal("7664f6f70b16eb1b8ac09bb5eb78f2f1999edf72c68919b7e3cfd501c35f9b4c", digest);
        }

        [Fact]
        public void WorkingBitsCountTheCentersDigits()
        {
            Assert.Equal(new[] { 0, 1, 0, 0, 295, 1 }, new[]
            {
                ReferenceOrbit.DecimalPlaces("0"), ReferenceOrbit.DecimalPlaces("0.0"),
                ReferenceOrbit.DecimalPlaces("-2"), ReferenceOrbit.DecimalPlaces("2.5E1"),
                ReferenceOrbit.DecimalPlaces("1e-295"), ReferenceOrbit.DecimalPlaces(".5"),
            });
            // 10^33 has 110 bits, exactly zoom 14's 46 + 64: the shipped vector keeps F = 174.
            Assert.Equal(174, ReferenceOrbit.WorkingBits(
                "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0));
            Assert.Equal(1060, ReferenceOrbit.WorkingBits("-2", "1e-295", 280.0));   // zoom term wins
            Assert.Equal(1094, ReferenceOrbit.WorkingBits("-2", "1e-310", 280.0));   // digit term: 10^310 is 1030 bits

            // The digit term stops at MaxDigitPlaces: a string alone cannot set F.
            Assert.Equal(ReferenceOrbit.WorkingBits("-1.75", "1e-340", 13.0),
                ReferenceOrbit.WorkingBits("-1.75", "1e-100000", 13.0));
            Assert.Equal(1130 + 64, ReferenceOrbit.WorkingBits("-1.75", "1e-340", 13.0));   // 10^340 is 1130 bits

            // With the digit term a subnormal center component converts correctly.
            var (_, im) = ReferenceOrbit.Mandelbrot("-2", "9.2012923132971335189e-309", 280.0, 40);
            Assert.Equal(9.201292313297136e-309, im[1]);
        }

        /// <summary>
        /// Samples past the float64 range round to infinities, as IEEE rounding does, in
        /// both ports (Python: test_fractal.py); the pixels then escape at once.
        /// </summary>
        [Fact]
        public void OrbitSamplesPastTheFloat64RangeAreInfinities()
        {
            var (re, im) = ReferenceOrbit.Mandelbrot("1e309", "0", 13.0, 10);
            Assert.Equal(new[] { 0.0, double.PositiveInfinity }, re);
            Assert.Equal(new[] { 0.0, 0.0 }, im);
            var (jre, jim) = ReferenceOrbit.Julia("-1e160", "0", 13.0, 10, -0.7269, 0.745);
            Assert.Equal(new[] { -1e160, double.PositiveInfinity }, jre);
            Assert.Equal(new[] { 0.0, 0.745 }, jim);
            int[] counts = new Mandelbrot(100).Iterations(4, 4, new Viewport("1e400", "0", 13.0));
            Assert.All(counts, n => Assert.Equal(1, n));
        }

        private static void AssertMatchesFile(double[] re, double[] im, string path)
        {
            byte[] expected = File.ReadAllBytes(path);
            Assert.Equal(expected.Length / 16, re.Length);
            Assert.Equal(re.Length, im.Length);

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
        /// int(3.33 * zoom) + 64. spec/deep-zoom.md once said ceil (since corrected);
        /// the shipped vector was produced by the truncating form and the vector wins.
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
        /// Decimal centers are parsed WITHOUT passing through double — the reason
        /// the viewport carries strings at all. A 33-digit center round-trips to
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
        public void RejectsMalformedCenters(string bad)
        {
            Assert.Throws<ArgumentException>(() => ReferenceOrbit.ParseFixed(bad, 64));
        }

        [Fact]
        public void ShortOrbitsAreExpectedWhenTheCenterItselfEscapes()
        {
            // A center well outside the set escapes in a handful of steps, so the
            // orbit is far shorter than max_iter + 1. Both ports clamp the
            // reference index to the last sample, which is why this is legal.
            var (re, im) = ReferenceOrbit.Mandelbrot("2.0", "2.0", 13.0, 500);
            Assert.True(re.Length < 501, $"expected an early stop, got {re.Length}");
            Assert.Equal(re.Length, im.Length);
            double lastAbs2 = re[re.Length - 1] * re[re.Length - 1]
                              + im[im.Length - 1] * im[im.Length - 1];
            Assert.True(lastAbs2 > ReferenceOrbit.EscapeAbs2);
        }

        /// <summary>
        /// Fixed point to double is one IEEE-754 rounding, subnormals included. At
        /// 1100 fractional bits every double and every midpoint between neighbors is
        /// exact in fixed point, so the expected answers are known without a second
        /// implementation: doubles round-trip, midpoints go to the even neighbor, and
        /// one unit either side of a midpoint goes to the nearer one.
        /// </summary>
        [Fact]
        public void ToDoubleRoundsOnceAcrossTheSubnormalRange()
        {
            const int bits = 1100;
            var random = new Random(7);
            var patterns = new List<long>
            {
                1L, 2L, 3L, (1L << 52) - 1, 1L << 52, (1L << 52) + 1,     // subnormal edge
                BitConverter.DoubleToInt64Bits(1e-310), BitConverter.DoubleToInt64Bits(1e-300),
                BitConverter.DoubleToInt64Bits(1.0), BitConverter.DoubleToInt64Bits(2.0),
                BitConverter.DoubleToInt64Bits(1e50),
            };
            for (int i = 0; i < 4000; i++)
            {
                // Uniform over exponent fields 0..1100 (1e-308..1e23), random mantissa.
                long exponentField = random.Next(0, 1101);
                long mantissa = ((long)random.Next() << 21) ^ random.Next();
                patterns.Add((exponentField << 52) | (mantissa & ((1L << 52) - 1)));
            }

            foreach (long pattern in patterns)
            {
                double d = BitConverter.Int64BitsToDouble(pattern);
                double next = BitConverter.Int64BitsToDouble(pattern + 1);
                var fd = ReferenceOrbit.FromDouble(d, bits);
                var fn = ReferenceOrbit.FromDouble(next, bits);
                Assert.Equal(d, ReferenceOrbit.ToDouble(fd, bits));
                Assert.Equal(-d, ReferenceOrbit.ToDouble(-fd, bits));

                var mid = (fd + fn) / 2;
                Assert.Equal(fd + fn, mid * 2);                        // the midpoint is exact
                double even = (pattern & 1) == 0 ? d : next;
                Assert.Equal(even, ReferenceOrbit.ToDouble(mid, bits));
                Assert.Equal(-even, ReferenceOrbit.ToDouble(-mid, bits));
                Assert.Equal(d, ReferenceOrbit.ToDouble(mid - 1, bits));
                Assert.Equal(next, ReferenceOrbit.ToDouble(mid + 1, bits));
            }

            // Below the smallest subnormal: half of it is a tie with 0, which is even.
            var tiny = ReferenceOrbit.FromDouble(double.Epsilon, bits);
            Assert.Equal(0.0, ReferenceOrbit.ToDouble(tiny / 2, bits));
            Assert.Equal(double.Epsilon, ReferenceOrbit.ToDouble(tiny / 2 + 1, bits));
            Assert.Equal(0.0, ReferenceOrbit.ToDouble(tiny / 4, bits));
        }

        /// <summary>
        /// Past zoom ~268.8 the working precision exceeds 1022 fractional bits, and a
        /// center component below ~1e-292 used to throw instead of converting.
        /// (1e-295 still has ~80 significant bits at zoom 280's 1060 fractional bits;
        /// a subnormal component would have too few until the precision rule counts
        /// the center's digits, which is why this is not 1e-310.)
        /// </summary>
        [Fact]
        public void TinyCenterComponentsConvertAtExtremeZoom()
        {
            var (re, im) = ReferenceOrbit.Mandelbrot("-2", "1e-295", 280.0, 50);
            Assert.Equal(-2.0, re[1]);
            Assert.Equal(1e-295, im[1]);
            Assert.Equal(2.0, re[2]);
            Assert.Equal(-3e-295, im[2]);                                 // 2*(-2)*1e-295 + 1e-295
        }

        private const string JuliaCaseDir = "julia/deep-zoom13-32";
        private const string RabbitBetaRe = "1.27658194945592591790467276337476";
        private const string RabbitBetaIm = "-0.47966605489732779175475867397901";

        /// <summary>
        /// End to end with no stored data: a deep Julia render that makes both of its
        /// own orbits reproduces the vector's counts. The frame sits on the rabbit's
        /// repelling fixed point, where most pixels rebase — before the critical orbit,
        /// they restarted on the center's orbit and the frame was wrong.
        /// </summary>
        [Fact]
        public void DeepJuliaWithItsOwnOrbitsReproducesTheVector()
        {
            byte[] bytes = File.ReadAllBytes(
                Path.Combine(TestPaths.VectorRoot(), JuliaCaseDir, "iterations.i32"));
            var expected = new int[bytes.Length / 4];
            Buffer.BlockCopy(bytes, 0, expected, 0, bytes.Length);

            var julia = new Julia(-0.123, 0.745, 600);
            int[] counts = julia.Iterations(32, 32, new Viewport(RabbitBetaRe, RabbitBetaIm, 13.0));
            Assert.Equal(expected, counts);
        }

        [Fact]
        public void JuliaRejectsACriticalOrbitThatDoesNotStartAtZero()
        {
            var viewport = new Viewport(RabbitBetaRe, RabbitBetaIm, 13.0);
            var (re, im) = ReferenceOrbit.Julia(RabbitBetaRe, RabbitBetaIm, 13.0, 50, -0.123, 0.745);
            var julia = new Julia(-0.123, 0.745, 50);
            // The center's own orbit starts at the center, not at 0: exactly the
            // mistake the critical orbit exists to prevent.
            Assert.Throws<ArgumentException>(() => julia.Iterations(4, 4, viewport, re, im, re, im));
            // Malformed replay data fails up front, not as an index error in a worker row.
            var (wr, wi) = ReferenceOrbit.JuliaCritical(-0.123, 0.745, 13.0, 50);
            Assert.Throws<ArgumentException>(() => julia.Iterations(4, 4, viewport, re, im, wr, new double[] { 0.0 }));
            Assert.Throws<ArgumentException>(() => julia.Iterations(4, 4, viewport, re, im, new double[0], new double[0]));
            Assert.Throws<ArgumentException>(() => julia.Iterations(4, 4, viewport, re, new double[] { re[0] }, wr, wi));
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
