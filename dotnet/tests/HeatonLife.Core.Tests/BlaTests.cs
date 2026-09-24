using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// BLA (spec/deep-zoom.md "BLA"): the magnitude, the table's invariants, that a cached
    /// orbit longer than max_iter gives the same pixels, and that where nothing engages BLA
    /// is BLA-off bit for bit. The Python suite's test_bla.py; the vectors pin the counts.
    /// </summary>
    public class BlaTests
    {
        // test_deep_oracle.py's p1959 nucleus, the frame shifted 0.7 widths right at zoom 30:
        // a reference that escapes near 3000 and pixels that rebase.
        private static Viewport P1959Zoom30() => new Viewport(
            "-0.741792701429200123284154862459", "0.123977941724695971711689620339", 30.0);

        [Fact]
        public void Mag()
        {
            Assert.Equal(0.0, BlaTable.Mag(0.0, 0.0));
            Assert.Equal(5.0, BlaTable.Mag(3.0, 4.0));
            Assert.Equal(0.0, BlaTable.Mag(-0.0, -0.0));
            Assert.True(Math.Abs(BlaTable.Mag(3e-300, 4e-300) / 5e-300 - 1.0) < 1e-15);
            Assert.True(Math.Abs(BlaTable.Mag(3e300, 4e300) / 5e300 - 1.0) < 1e-15);
            Assert.Equal(double.PositiveInfinity, BlaTable.Mag(double.PositiveInfinity, 1.0));
            Assert.True(double.IsNaN(BlaTable.Mag(double.NaN, 1.0)));
            Assert.Equal(1e-320, BlaTable.Mag(1e-320, 0.0));                // scaled into range and back, exactly
        }

        [Fact]
        public void TableInvariants()
        {
            var viewport = P1959Zoom30();
            var (orbitRe, orbitIm) = ReferenceOrbit.Mandelbrot(
                viewport.OrbitCenterRe, viewport.OrbitCenterIm, viewport.ZoomLog10, 20000);
            var table = BlaTable.Build(orbitRe, orbitIm, orbitRe.Length, 1000.0, BlaTable.DcBound(1e-30, 1e-30));
            Assert.True(table.Extent < orbitRe.Length - 1, "premise: the reference escapes");
            Assert.True(table.Levels >= 6);
            int live = 0;
            for (int level = 0; level < table.Levels; level++)
            {
                Assert.Equal(0.0, table.R[level][0]);                          // entries from Z_0 = 0 are dead
                for (int k = 0; k < table.R[level].Length; k++)
                {
                    double r = table.R[level][k];
                    Assert.True(r >= 0.0 && !double.IsInfinity(r) && !double.IsNaN(r));
                    if (level > 0)
                        Assert.True(r <= table.R[level - 1][2 * k], "radii never grow");
                    if (r > 0)
                        live++;
                }
            }
            Assert.True(live > 0);
        }

        [Fact]
        public void ACachedLongerOrbitGivesTheSamePixels()
        {
            // A deep render caches the whole orbit; a shallower max_iter then reuses it, so the
            // table reaches past max_iter. Entries a pixel could take end at m + span <= n + span
            // <= max_iter, so the pixels equal a replay of the exact max_iter + 1 prefix.
            var viewport = P1959Zoom30();
            const int w = 12, h = 12;
            new Mandelbrot(20000, 1000.0, 1, true).Fields(w, h, viewport, new int[w * h], new int[w * h]);
            var (longRe, longIm) = ReferenceOrbit.Mandelbrot(
                viewport.OrbitCenterRe, viewport.OrbitCenterIm, viewport.ZoomLog10, 20000);
            foreach (int maxIter in new[] { 1500, 2003, 2500 })
            {
                var cached = new int[w * h];
                var cachedApplied = new int[w * h];
                new Mandelbrot(maxIter, 1000.0, 3, true).Fields(w, h, viewport, cached, cachedApplied);
                var prefixRe = new double[maxIter + 1];
                var prefixIm = new double[maxIter + 1];
                Array.Copy(longRe, prefixRe, maxIter + 1);
                Array.Copy(longIm, prefixIm, maxIter + 1);
                var replay = new int[w * h];
                var replayApplied = new int[w * h];
                new Mandelbrot(maxIter, 1000.0, 1, true).Fields(w, h, viewport, prefixRe, prefixIm, replay, null, null, replayApplied);
                Assert.True(cached.AsSpan().SequenceEqual(replay), $"max_iter {maxIter}");
                Assert.True(cachedApplied.AsSpan().SequenceEqual(replayApplied), $"max_iter {maxIter}");
            }
        }

        [Fact]
        public void ALiveRenderFromAPrimedCacheMatchesTheVector()
        {
            // The public path reuses whatever orbit the cache holds: prime it at 8x max_iter,
            // then render a BLA vector's frame live — its counts and skips must be the file's.
            string caseDir = System.IO.Path.Combine(TestPaths.VectorRoot(), "mandelbrot", "bla-p1959-zoom30-16");
            using var doc = System.Text.Json.JsonDocument.Parse(System.IO.File.ReadAllText(System.IO.Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            var vp = root.GetProperty("viewport");
            var viewport = new Viewport(vp.GetProperty("center_re").GetString()!, vp.GetProperty("center_im").GetString()!, vp.GetProperty("zoom_log10").GetDouble());
            int maxIter = root.GetProperty("params").GetProperty("max_iter").GetInt32();
            int w = root.GetProperty("size")[0].GetInt32(), h = root.GetProperty("size")[1].GetInt32();
            new Mandelbrot(8 * maxIter, 1000.0, 1, false).Iterations(4, 4, viewport);
            var counts = new int[w * h];
            var applied = new int[w * h];
            new Mandelbrot(maxIter, 1000.0, 3, true).Fields(w, h, viewport, counts, applied);
            Assert.True(counts.AsSpan().SequenceEqual(ReadI32(System.IO.Path.Combine(caseDir, "iterations.i32"))));
            Assert.True(applied.AsSpan().SequenceEqual(ReadI32(System.IO.Path.Combine(caseDir, "bla_applications.i32"))));
        }

        private static int[] ReadI32(string path)
        {
            byte[] bytes = System.IO.File.ReadAllBytes(path);
            var values = new int[bytes.Length / 4];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
        }

        [Fact]
        public void CeilPowerOfTwo()
        {
            Assert.Equal(1.0, BlaTable.CeilPowerOfTwo(1.0));
            Assert.Equal(2.0, BlaTable.CeilPowerOfTwo(1.0000000000000002));
            Assert.Equal(0.5, BlaTable.CeilPowerOfTwo(0.3));
            Assert.Equal(0.0, BlaTable.CeilPowerOfTwo(0.0));
            Assert.Equal(double.Epsilon * 4, BlaTable.CeilPowerOfTwo(double.Epsilon * 3));
            Assert.Equal(BitConverter.Int64BitsToDouble(1L << 52), BlaTable.CeilPowerOfTwo(BitConverter.Int64BitsToDouble((1L << 52) - 1)));
            Assert.Equal(double.PositiveInfinity, BlaTable.CeilPowerOfTwo(double.MaxValue));
        }

        [Fact]
        public void WhereNothingEngagesBlaIsBlaOff()
        {
            // At zoom 14 no entry survives eps = 2^-53: the BLA loop is the plain loop, bit for bit.
            var viewport = new Viewport("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0);
            const int w = 32, h = 32;
            var onCounts = new int[w * h];
            var onApplied = new int[w * h];
            var onSmooth = new double[w * h];
            var onDistance = new double[w * h];
            new Mandelbrot(5000, 1000.0, 1, true).Fields(w, h, viewport, onCounts, onApplied, onSmooth, null, onDistance);
            var offCounts = new int[w * h];
            var offSmooth = new double[w * h];
            var offDistance = new double[w * h];
            new Mandelbrot(5000).Fields(w, h, viewport, offCounts, offSmooth, null, offDistance);
            Assert.All(onApplied, a => Assert.Equal(0, a));
            Assert.True(onCounts.AsSpan().SequenceEqual(offCounts));
            Assert.True(onSmooth.AsSpan().SequenceEqual(offSmooth));
            for (int i = 0; i < w * h; i++)
                Assert.True(onDistance[i].Equals(offDistance[i]), $"pixel {i}");
        }

        [Fact]
        public void BlaIsOptInAndT1Only()
        {
            var home = new Viewport("-0.5", "0.0", 0.0);
            var a = new int[256];
            var applied = new int[256];
            new Mandelbrot(300, 1000.0, 1, true).Fields(16, 16, home, a, applied);
            Assert.True(a.AsSpan().SequenceEqual(new Mandelbrot(300).Iterations(16, 16, home)));
            Assert.All(applied, x => Assert.Equal(0, x));
            Assert.False(new Mandelbrot().Bla);
            Assert.True(new Mandelbrot(10, 1000.0, 1, true).Bla);
        }
    }
}
