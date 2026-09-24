using System;
using System.Globalization;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Distance estimate (spec/fractals.md "Distance estimate"): the known limits, the
    /// guards, the domain, and that the distance loop is the other loops plus a derivative.
    /// The Python suite's test_distance.py (whose high-precision oracle checks the values;
    /// the vectors carry them here).
    /// </summary>
    public class DistanceTests
    {
        [Fact]
        public void TheTipReadsTwiceTheDistance()
        {
            // c = -2 - delta on the real axis, true distance delta: DE -> 2 delta (no factor 2).
            foreach (double delta in new[] { 1e-3, 1e-5, 1e-7 })
            {
                var viewport = new Viewport((-2.0 - delta).ToString("R", CultureInfo.InvariantCulture), "0.0", 3.0);
                var counts = new int[1];
                var distance = new double[1];
                new Mandelbrot(200000).Fields(1, 1, viewport, counts, distance: distance);
                double ratio = distance[0] * FractalEngine.PixelScale(1, viewport) / delta;
                Assert.True(Math.Abs(ratio - 2.0) < 2e-3, $"delta {delta}: ratio {ratio}");
            }
        }

        [Fact]
        public void ThePixelScaleEntersLinearly()
        {
            // d carries ps: halving it halves every d exactly, so DE in pixels doubles exactly.
            var rng = new Pcg32(11);
            for (int i = 0; i < 200; i++)
            {
                double cr = -0.7435 + (rng.NextU32() / 4294967296.0 - 0.5) * 1e-3;
                double ci = 0.1314 + (rng.NextU32() / 4294967296.0 - 0.5) * 1e-3;
                int a = FractalEngine.EscapeZ2De(0, 0, cr, ci, 2000, 1e6, 0, 0, true, 1e-5, out double fr, out double fi, out double dr, out double di, out _);
                int b = FractalEngine.EscapeZ2De(0, 0, cr, ci, 2000, 1e6, 0, 0, true, 5e-6, out double fr2, out double fi2, out double dr2, out double di2, out _);
                Assert.Equal(a, b);
                Assert.Equal(dr, 2.0 * dr2);
                Assert.Equal(di, 2.0 * di2);
                if (a > 0)
                    Assert.Equal(2.0 * FractalEngine.DistanceEstimate(a, fr, fi, dr, di), FractalEngine.DistanceEstimate(b, fr2, fi2, dr2, di2));
            }
        }

        [Fact]
        public void Guards()
        {
            double m2 = 1000.0 * 1000.0 + 20.0 * 20.0;
            double baseline = Math.Sqrt(m2) * (0.5 * Math.Log(m2));
            Assert.Equal(double.PositiveInfinity, FractalEngine.DistanceEstimate(5, 1000, 20, 0.0, 0.0));     // a critical point
            Assert.Equal(0.0, FractalEngine.DistanceEstimate(5, 1000, 20, double.PositiveInfinity, 1.0));     // overflowed
            Assert.Equal(0.0, FractalEngine.DistanceEstimate(5, 1000, 20, double.NaN, 1.0));
            Assert.Equal(0.0, FractalEngine.DistanceEstimate(5, 1000, 20, 0.0, double.NaN));
            double tiny = FractalEngine.DistanceEstimate(5, 1000, 20, 1e-170, -2e-170);                        // scaled, not 0
            Assert.True(Math.Abs(tiny / (baseline / (Math.Sqrt(5.0) * 1e-170)) - 1.0) < 1e-14);
            Assert.Equal(baseline / 5.0, FractalEngine.DistanceEstimate(5, 1000, 20, 3.0, 4.0));
            Assert.True(double.IsNaN(FractalEngine.DistanceEstimate(-1, 0, 0, 1, 1)));                       // did not escape
            Assert.Equal(baseline / 1e200, FractalEngine.DistanceEstimate(5, 1000, 20, 1e200, 0.0));         // scaled down, not 0
            double huge = FractalEngine.DistanceEstimate(5, 1000, 20, 1e300, -1e300);
            Assert.True(Math.Abs(huge / (baseline / (Math.Sqrt(2.0) * 1e300)) - 1.0) < 1e-14);
            // An odd frame centered on 0 puts a pixel exactly on Julia's critical point.
            var counts = new int[65 * 65];
            var distance = new double[65 * 65];
            new Julia(0.3, 0.0, 200).Fields(65, 65, new Viewport("0", "0", 0.0), counts, distance: distance);
            for (int i = 0; i < distance.Length; i++)
                Assert.True(i == 32 * 65 + 32 ? double.IsPositiveInfinity(distance[i]) : double.IsFinite(distance[i]), $"pixel {i}");
        }

        [Fact]
        public void FarFromTheSetAtDepthIsNotABoundary()
        {
            // |d| ends near 1.4e-163 at zoom 170: plain squares would flush to 0 and read a
            // false DE = +inf; the exponent-scaled magnitude reads 2.25e167.
            var counts = new int[16 * 16];
            var distance = new double[16 * 16];
            new Mandelbrot(2000).Fields(16, 16, new Viewport("-0.75", "0.1", 170.0), counts, distance: distance);
            foreach (double de in distance)
                Assert.True(de > 1e166 && double.IsFinite(de), $"{de:R}");
        }

        [Fact]
        public void TheDistanceLoopIsTheOtherLoopsPlusADerivative()
        {
            var cases = new (Func<int, int[], double[], byte[], double[], bool> Run, string Name)[]
            {
                ((workers, c, s, st, d) => { new Mandelbrot(500, 1000.0, workers).Fields(48, 40, new Viewport("-0.5", "0.0", 0.0), c, s, st, d); return true; }, "mandelbrot"),
                ((workers, c, s, st, d) => { new Julia(-0.123, 0.745, 800, 1000.0, workers).Fields(48, 40, new Viewport("0", "0", 0.0), c, s, st, d); return true; }, "julia"),
                ((workers, c, s, st, d) => { new Mandelbrot(3000, 1000.0, workers).Fields(48, 40, new Viewport("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 13.5), c, s, st, d); return true; }, "mandelbrot T1"),
            };
            foreach (var (run, name) in cases)
            {
                int n = 48 * 40;
                var counts = new int[n];
                var smooth = new double[n];
                var status = new byte[n];
                run(1, counts, smooth, status, null!);
                var countsDe = new int[n];
                var smoothDe = new double[n];
                var statusDe = new byte[n];
                var distance = new double[n];
                run(3, countsDe, smoothDe, statusDe, distance);
                Assert.True(counts.AsSpan().SequenceEqual(countsDe), name);
                Assert.True(status.AsSpan().SequenceEqual(statusDe), name);
                Assert.True(smooth.AsSpan().SequenceEqual(smoothDe), name);
                for (int i = 0; i < n; i++)
                    Assert.Equal(countsDe[i] <= 0, double.IsNaN(distance[i]));
            }
        }

        [Fact]
        public void Domain()
        {
            var viewport = new Viewport("-0.5", "0.0", 0.0);
            foreach (double radius in new[] { 1.5, 1e65 })
                Assert.Throws<ArgumentException>(() => new Mandelbrot(100, radius).Fields(4, 4, viewport, new int[16], distance: new double[16]));
            Assert.Throws<NotSupportedException>(() => new BurningShip().Fields(4, 4, viewport, new int[16], distance: new double[16]));
            Assert.Throws<ArgumentException>(() => new Mandelbrot().Fields(4, 4, viewport, new int[16], distance: new double[15]));
            Assert.False(new BurningShip().SupportsDistance);
            Assert.True(new Mandelbrot().SupportsDistance && new Julia().SupportsDistance);
            // Without a distance buffer a small radius is fine, as before.
            new Mandelbrot(100, 1.5).Fields(4, 4, viewport, new int[16]);
        }
    }
}
