using System;
using System.Globalization;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Exact viewport arithmetic (spec/navigation.md): the properties the vectors cannot
    /// enumerate — precision never ratchets, a zero move changes nothing, the output is
    /// culture-proof, and bad inputs are refused. The Python suite's test_navigation.py.
    /// </summary>
    public class NavigationTests
    {
        private const string SeahorseRe = "-0.743643887037158704752191506114774";
        private const string SeahorseIm = "0.131825904205311970493132056385139";

        [Fact]
        public void CenterPlacesComeFromTheFrame()
        {
            Assert.Equal(14 + 3 + 2, Navigation.CenterPlaces(14.0, 512, 384));
            Assert.Equal(15 + 4 + 2, Navigation.CenterPlaces(14.2, 1920, 1080));
            Assert.Equal(0 + 2 + 2, Navigation.CenterPlaces(-1.5, 64, 48));
            Assert.Equal(3, Navigation.CenterPlaces(0.0, 1, 1));
            Assert.Equal(14 + 4 + 2, Navigation.CenterPlaces(14.0, 720, 1280));   // the height's digits
            foreach (double bad in new[] { 9000.5, -301.0, double.NaN, 1e10 })
                Assert.ThrowsAny<ArgumentException>(() => Navigation.CenterPlaces(bad, 64, 64));
        }

        [Fact]
        public void AZeroMoveChangesNothing()
        {
            var vp = new Viewport("-2", "1e-295", 280.0, "-2", "0");
            var same = Navigation.Pan(vp, 0.0, -0.0, 32, 32);
            Assert.Equal(("-2", "1e-295"), (same.CenterRe, same.CenterIm));
            Assert.Equal(("-2", "0"), (same.ReferenceRe, same.ReferenceIm));
            var still = Navigation.ZoomAt(vp, 5.0, 2.0, 32, 32, 280.0);
            Assert.Equal(("-2", "1e-295"), (still.CenterRe, still.CenterIm));
            Assert.Equal(("-2", "0"), (still.ReferenceRe, still.ReferenceIm));
            var aboutCenter = Navigation.ZoomAt(vp, 0.0, 0.0, 32, 32, 281.0);   // only the zoom moves
            Assert.Equal(("-2", "1e-295", 281.0), (aboutCenter.CenterRe, aboutCenter.CenterIm, aboutCenter.ZoomLog10));
            Assert.Equal(("-2", "0"), (aboutCenter.ReferenceRe, aboutCenter.ReferenceIm));
            // Any real move prints BOTH components at the frame's places.
            var moved = Navigation.Pan(vp, 7.5, 0.0, 32, 32);
            Assert.Equal("0." + new string('0', Navigation.CenterPlaces(280.0, 32, 32)), moved.CenterIm);
            Assert.NotEqual("-2", moved.CenterRe);
            var zoomed = Navigation.ZoomAt(vp, 5.0, 2.0, 32, 32, 281.5);
            Assert.Equal(("-2", "0"), (zoomed.ReferenceRe, zoomed.ReferenceIm));
        }

        /// <summary>
        /// After its first move a center's orbit costs what its zoom alone asks, at every
        /// depth, however many pans and anchored zooms follow.
        /// </summary>
        [Fact]
        public void RepeatedMovesNeverChangeTheWorkingBits()
        {
            var rng = new Pcg32(11);
            double Uniform(double lo, double hi) => lo + (hi - lo) * (rng.NextU32() / 4294967296.0);
            for (int trial = 0; trial < 60; trial++)
            {
                double zoom = Uniform(-2.0, 289.0);
                int width = 1 + (int)(rng.NextU32() % 4000), height = 1 + (int)(rng.NextU32() % 4000);
                var vp = Navigation.Pan(new Viewport(SeahorseRe, SeahorseIm, zoom), 1.25, -0.5, width, height);
                int bits = ReferenceOrbit.WorkingBits(vp.CenterRe, vp.CenterIm, zoom);
                Assert.Equal(ReferenceOrbit.WorkingBits("0", "0", zoom), bits);
                for (int step = 0; step < 8; step++)
                {
                    vp = rng.NextU32() % 2 == 0
                        ? Navigation.Pan(vp, Uniform(-3000, 3000), Uniform(-3000, 3000), width, height)
                        : Navigation.ZoomAt(vp, Uniform(-900, 900), Uniform(-900, 900), width, height, zoom);
                    Assert.Equal(bits, ReferenceOrbit.WorkingBits(vp.CenterRe, vp.CenterIm, zoom));
                    Assert.True(ReferenceOrbit.DecimalPlaces(vp.CenterRe) <= Navigation.CenterPlaces(zoom, width, height));
                }
            }
        }

        [Fact]
        public void PixelDeltaInvertsPan()
        {
            var rng = new Pcg32(9);
            double Uniform(double lo, double hi) => lo + (hi - lo) * (rng.NextU32() / 4294967296.0);
            for (int trial = 0; trial < 80; trial++)
            {
                double zoom = Uniform(-2.0, 289.0);
                int width = 16 + (int)(rng.NextU32() % 2033), height = 16 + (int)(rng.NextU32() % 2033);
                double dx = Uniform(-width, width), dy = Uniform(-height, height);
                var vp = new Viewport(SeahorseRe, SeahorseIm, zoom);
                var (gotX, gotY) = Navigation.PixelDelta(vp, Navigation.Pan(vp, dx, dy, width, height), width, height);
                Assert.True(Math.Abs(gotX - dx) <= 1.0 / 800 + 1e-9 * Math.Abs(dx), $"{gotX} vs {dx}");
                Assert.True(Math.Abs(gotY - dy) <= 1.0 / 800 + 1e-9 * Math.Abs(dy), $"{gotY} vs {dy}");
            }
            var (x0, y0) = Navigation.PixelDelta(new Viewport("0.1", "0", 3.0), new Viewport("0.10", "0.0", 20.0), 64, 64);
            Assert.Equal(0L, BitConverter.DoubleToInt64Bits(x0));     // +0.0, not -0.0
            Assert.Equal(0L, BitConverter.DoubleToInt64Bits(y0));
        }

        /// <summary>
        /// Centers are ASCII whatever the thread's culture: BigInteger formatting follows the
        /// culture's negative sign (U+2212 in Swedish), so Core formats magnitudes.
        /// </summary>
        [Fact]
        public void OutputIsCultureProof()
        {
            var saved = CultureInfo.CurrentCulture;
            try
            {
                CultureInfo.CurrentCulture = new CultureInfo("sv-SE");
                // Premise: this culture really writes a non-ASCII minus.
                Assert.Equal("\u22125", new System.Numerics.BigInteger(-5).ToString());
                var moved = Navigation.Pan(new Viewport(SeahorseRe, SeahorseIm, 14.0), -30.25, 12.5, 512, 384);
                Assert.StartsWith("-0.", moved.CenterRe);
                Assert.Equal("-0.00000012", Navigation.Positional("-1.2E-7"));
                Assert.DoesNotContain('−', moved.CenterRe + moved.CenterIm);
            }
            finally
            {
                CultureInfo.CurrentCulture = saved;
            }
        }

        [Fact]
        public void BadInputsAreRefused()
        {
            var vp = new Viewport(SeahorseRe, SeahorseIm, 14.0);
            foreach (double bad in new[] { double.NaN, double.PositiveInfinity, double.NegativeInfinity })
            {
                Assert.ThrowsAny<ArgumentException>(() => Navigation.Pan(vp, bad, 0.0, 64, 64));
                Assert.ThrowsAny<ArgumentException>(() => Navigation.ZoomAt(vp, 0.0, 1.0, 64, 64, bad));
            }
            Assert.ThrowsAny<ArgumentException>(() => Navigation.Pan(vp, 1.0, 1.0, 0, 64));
            foreach (double badZoom in new[] { 9001.0, -300.5 })
            {
                Assert.ThrowsAny<ArgumentException>(() => Navigation.Pan(vp, 1.0, 0.0, 64, 64, badZoom));
                Assert.ThrowsAny<ArgumentException>(() => Navigation.ZoomAt(vp, 1.0, 0.0, 64, 64, badZoom));
            }
            Assert.ThrowsAny<ArgumentException>(() => Navigation.Pan(new Viewport("0", "0", -300.0), 1e300, 0.0, 1, 1));
            // The 10,000-digit limit, at its edge: the grammar reads back what Positional writes.
            Assert.Equal(new string('9', 10000), Navigation.Positional(new string('9', 10000)));
            Assert.Equal("0." + new string('9', 9999), Navigation.Positional("0." + new string('9', 9999)));
            Assert.ThrowsAny<ArgumentException>(() => Navigation.Positional("1" + new string('0', 10000)));
            Assert.Equal(10001, DecimalText.FormatScaled(System.Numerics.BigInteger.One, 9999).Length);
            Assert.ThrowsAny<ArgumentException>(() => DecimalText.FormatScaled(System.Numerics.BigInteger.One, 10000));
            Assert.ThrowsAny<ArgumentException>(() => Navigation.Positional("1e-20000"));
            Assert.ThrowsAny<ArgumentException>(() => Navigation.Positional("1e20000"));
        }
    }
}
