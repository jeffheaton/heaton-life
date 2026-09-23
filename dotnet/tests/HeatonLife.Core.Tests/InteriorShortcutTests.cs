using System;
using System.Globalization;
using System.Numerics;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Interior shortcuts and status (spec/fractals.md): the cardioid/bulb test and exact
    /// cycle detection are output-neutral — every count is what the plain loop gives — and
    /// the status says how each count was decided. The Python suite's test_interior_shortcuts.py.
    /// </summary>
    public class InteriorShortcutTests
    {
        /// <summary>The escape loop with no shortcut at all: the definition the shortcuts must match.</summary>
        private static int Plain(double zr, double zi, double cr, double ci, bool ship, int maxIter, double r2 = 1e6)
        {
            for (int it = 1; it <= maxIter; it++)
            {
                if (ship)
                {
                    zr = Math.Abs(zr);
                    zi = Math.Abs(zi);
                }
                var (sr, si) = FractalEngine.ComplexMul(zr, zi, zr, zi);
                zr = sr + cr;
                zi = si + ci;
                if (zr * zr + zi * zi > r2)
                    return it;
            }
            return -1;
        }

        /// <summary>A double's exact value times 2^1074, an integer for every finite double.</summary>
        private static BigInteger Scaled(double value)
        {
            long bits = BitConverter.DoubleToInt64Bits(value);
            int exponent = (int)((bits >> 52) & 0x7FF);
            long mantissa = bits & 0xFFFFFFFFFFFFFL;
            BigInteger scaled = exponent == 0 ? mantissa : (BigInteger)(mantissa | (1L << 52)) << (exponent - 1);
            return bits < 0 ? -scaled : scaled;
        }

        /// <summary>
        /// The exact inequalities the float test approximates, in integers: with S = 2^1074,
        /// X = x·S and Y = y·S, the cardioid's q(q + x − 1/4) &lt; y²/4 is 4Q(Q + X_q·S) &lt; Y²S²
        /// (Q = X_q² + Y², X_q = X − S/4), and the bulb's (x + 1)² + y² &lt; 1/16 is
        /// 16((X + S)² + Y²) &lt; S².
        /// </summary>
        private static bool ExactlyInside(double x, double y)
        {
            BigInteger s = BigInteger.One << 1074;
            BigInteger bx = Scaled(x), by = Scaled(y);
            BigInteger xq = bx - (s >> 2);
            BigInteger q = xq * xq + by * by;
            if (4 * q * (q + xq * s) < by * by * s * s)
                return true;
            BigInteger x1 = bx + s;
            return 16 * (x1 * x1 + by * by) < s * s;
        }

        [Fact]
        public void TheCardioidTestOnlyFlagsInteriorPoints()
        {
            var rng = new Pcg32(4);
            double Uniform(double lo, double hi) => lo + (hi - lo) * (rng.NextU32() / 4294967296.0);
            int flagged = 0, total = 0, flaggedBulb = 0;
            for (int i = 0; i < 3000; i++)
            {
                double t = Uniform(0, 2 * Math.PI);
                double scale = 1 + Math.Pow(10, Uniform(-16, -3)) * (rng.NextU32() % 2 == 0 ? 1 : -1);
                // The main cardioid's boundary, e^{it}/2 - e^{2it}/4, and the bulb's circle.
                bool bulb = rng.NextU32() % 2 == 0;
                double cr = bulb ? -1 + Math.Cos(t) / 4 * scale : (Math.Cos(t) / 2 - Math.Cos(2 * t) / 4) * scale;
                double ci = bulb ? Math.Sin(t) / 4 * scale : (Math.Sin(t) / 2 - Math.Sin(2 * t) / 4) * scale;
                total++;
                if (!FractalEngine.CardioidOrBulb(cr, ci))
                    continue;
                flagged++;
                if (bulb)
                    flaggedBulb++;
                Assert.True(ExactlyInside(cr, ci), $"({cr:R}, {ci:R}) is flagged but not inside");
                if (flagged <= 400)
                    Assert.Equal(-1, Plain(0, 0, cr, ci, false, 20000));
            }
            Assert.InRange(flagged, total * 2 / 10, total * 7 / 10);    // premise: the sweep straddles both boundaries
            Assert.InRange(flaggedBulb, flagged / 4, flagged * 3 / 4);  // premise: the bulb is checked too
        }

        [Fact]
        public void ASmallEscapeRadiusTurnsTheCardioidTestOff()
        {
            // Orbits in the period-2 bulb reach |z| near 1.27, so below radius 2 a point of
            // the cardioid or bulb can escape: the counts must stay the plain loop's.
            var vp = new Viewport("-0.5", "0.0", 0.0);
            const int w = 64, h = 64;
            double ps = FractalEngine.PixelScale(w, vp);
            foreach (double radius in new[] { 1.0, 1.2, 1.9, 2.0 })
            {
                var (counts, status) = new Mandelbrot(200, radius).CountsAndStatus(w, h, vp);
                bool anyShortcut = false;
                for (int y = 0; y < h; y++)
                {
                    for (int x = 0; x < w; x++)
                    {
                        double cr = FractalEngine.OffsetRe(x, w, ps) + vp.CenterReDouble;
                        double ci = FractalEngine.OffsetIm(y, h, ps) + vp.CenterImDouble;
                        int i = y * w + x;
                        Assert.True(Plain(0, 0, cr, ci, false, 200, radius * radius) == counts[i], $"radius {radius} pixel ({x},{y})");
                        anyShortcut |= status[i] == (byte)PixelStatus.CardioidOrBulb;
                    }
                }
                Assert.Equal(radius >= 2.0, anyShortcut);
            }
        }

        [Fact]
        public void TheShortcutsAreOutputNeutral()
        {
            var rng = new Pcg32(8);
            double Uniform(double lo, double hi) => lo + (hi - lo) * (rng.NextU32() / 4294967296.0);
            for (int trial = 0; trial < 12; trial++)
            {
                int family = (int)(rng.NextU32() % 3);
                var vp = new Viewport(Uniform(-1.8, 0.4).ToString("R", CultureInfo.InvariantCulture), Uniform(-0.8, 0.8).ToString("R", CultureInfo.InvariantCulture), Uniform(-0.3, 6.0));
                const int w = 48, h = 40;
                var counts = new int[w * h];
                var status = new byte[w * h];
                if (family == 0)
                    new Mandelbrot(1500).CountsAndStatus(w, h, vp, counts, status);
                else if (family == 1)
                    new Julia(-0.123, 0.745, 1500).CountsAndStatus(w, h, vp, counts, status);
                else
                    new BurningShip(1500).CountsAndStatus(w, h, vp, counts, status);
                double ps = FractalEngine.PixelScale(w, vp);
                for (int y = 0; y < h; y++)
                {
                    for (int x = 0; x < w; x++)
                    {
                        double cr = FractalEngine.OffsetRe(x, w, ps) + vp.CenterReDouble;
                        double ci = FractalEngine.OffsetIm(y, h, ps) + vp.CenterImDouble;
                        int want = family == 1 ? Plain(cr, ci, -0.123, 0.745, false, 1500) : Plain(0, 0, cr, ci, family == 2, 1500);
                        int i = y * w + x;
                        Assert.True(want == counts[i], $"family {family} pixel ({x},{y})");
                        Assert.Equal(counts[i] > 0, status[i] == (byte)PixelStatus.Escaped);
                        Assert.True(status[i] <= 3);
                        Assert.True(family == 0 || status[i] != (byte)PixelStatus.CardioidOrBulb);
                    }
                }
            }
        }

        [Fact]
        public void CyclesAreFoundAndDeepFramesReportOnlyEscapedOrExhausted()
        {
            var (_, status) = new Julia(-0.123, 0.745, 1000).CountsAndStatus(64, 64, new Viewport("0", "0", 0.0));
            int cycles = 0;
            foreach (byte s in status)
            {
                Assert.NotEqual((byte)PixelStatus.Exhausted, s);           // the rabbit's interior is an attracting 3-cycle
                if (s == (byte)PixelStatus.Cycle)
                    cycles++;
            }
            Assert.True(cycles > 300);
            // T1 proves nothing: its state includes the orbit index, which never repeats.
            // Each frame has exhausted pixels, which T0 would have proved.
            var frames = new (string Name, (int[] Counts, byte[] Status) Result)[]
            {
                ("mandelbrot", new Mandelbrot(5000).CountsAndStatus(32, 32,
                    new Viewport("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0))),
                ("julia", new Julia(-0.123, 0.745, 600).CountsAndStatus(32, 32,
                    new Viewport("1.27658194945592591790467276337476", "-0.47966605489732779175475867397901", 13.0))),
                ("burning-ship", new BurningShip(1000).CountsAndStatus(32, 32,
                    new Viewport("0.403269293475576420989278613990", "-0.595275727121703516488710194270", 13.0))),
            };
            foreach (var (name, (counts, deep)) in frames)
            {
                int exhausted = 0;
                for (int i = 0; i < deep.Length; i++)
                {
                    Assert.True((counts[i] > 0 ? (byte)PixelStatus.Escaped : (byte)PixelStatus.Exhausted) == deep[i], $"{name} pixel {i}");
                    if (deep[i] == (byte)PixelStatus.Exhausted)
                        exhausted++;
                }
                Assert.True(exhausted > 0, $"premise: {name} has interior pixels");
            }
        }
    }
}
