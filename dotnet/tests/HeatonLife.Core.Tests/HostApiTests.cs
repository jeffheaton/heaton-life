using System;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The interactive-host surface (Stage 1 of the deep-zoom plan): the allocation-free
    /// fixed-width orbit agrees with the BigInteger one bit for bit, caller-buffer frames
    /// match the allocating ones, and the tier queries say what a frame will cost.
    /// </summary>
    public class HostApiTests
    {
        /// <summary>
        /// FixedOrbit's limb arithmetic against the BigInteger orbit, for every family,
        /// centers from a few digits to hundreds, signs, tiny components and zooms across
        /// T1. Identical integer operations, so identical samples — not "close".
        /// </summary>
        [Fact]
        public void FixedWidthOrbitMatchesTheBigIntegerOrbit()
        {
            var rng = new Pcg32(1);
            string Digits(int n)
            {
                var chars = new char[n];
                for (int i = 0; i < n; i++)
                    chars[i] = (char)('0' + rng.NextU32() % 10);
                return new string(chars);
            }
            var cases = new System.Collections.Generic.List<(ReferenceOrbit.Kind, string, string, double, double, double)>
            {
                (ReferenceOrbit.Kind.Mandelbrot, "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0, 0, 0),
                (ReferenceOrbit.Kind.Mandelbrot, "-2", "1e-295", 280.0, 0, 0),
                (ReferenceOrbit.Kind.Mandelbrot, "-2", "9.2012923132971335189e-309", 280.0, 0, 0),
                (ReferenceOrbit.Kind.Julia, "1.27658194945592591790467276337476", "-0.47966605489732779175475867397901", 13.0, -0.123, 0.745),
                (ReferenceOrbit.Kind.Julia, "0", "0", 157.5, 0.0, 1.0),
                (ReferenceOrbit.Kind.BurningShip, "-1.7443", "-0.0328", 15.0, 0, 0),
                (ReferenceOrbit.Kind.Julia, "-1e160", "0", 13.0, -0.7269, 0.745),       // BigInteger fallback: too wide
                (ReferenceOrbit.Kind.Mandelbrot, "70000", "0", 13.0, 0, 0),              // likewise
            };
            var kinds = new[] { ReferenceOrbit.Kind.Mandelbrot, ReferenceOrbit.Kind.Julia, ReferenceOrbit.Kind.BurningShip };
            for (int i = 0; i < 60; i++)
            {
                var kind = kinds[i % 3];
                string sign() => rng.NextU32() % 2 == 0 ? "-" : "";
                string re = sign() + "0." + Digits(5 + (int)(rng.NextU32() % 250));
                string im = sign() + "0." + Digits(5 + (int)(rng.NextU32() % 250));
                double zoom = 13.0 + rng.NextU32() % 277;
                cases.Add((kind, re, im, zoom, kind == ReferenceOrbit.Kind.Julia ? -0.7269 : 0.0, kind == ReferenceOrbit.Kind.Julia ? 0.1889 : 0.0));
            }
            int fixedRuns = 0;
            foreach (var (kind, re, im, zoom, cRe, cIm) in cases)
            {
                // Premise: which path "bigInteger: false" really takes for this case.
                int bits = ReferenceOrbit.WorkingBits(re, im, zoom);
                var center = (ReferenceOrbit.ParseFixed(re, bits), ReferenceOrbit.ParseFixed(im, bits));
                bool julia = kind == ReferenceOrbit.Kind.Julia;
                if (julia
                    ? FixedOrbit.Fits(bits, center.Item1, center.Item2, ReferenceOrbit.FromDouble(cRe, bits), ReferenceOrbit.FromDouble(cIm, bits))
                    : FixedOrbit.Fits(bits, 0, 0, center.Item1, center.Item2))
                    fixedRuns++;

                var fixedWidth = ReferenceOrbit.ComputeUncached(kind, re, im, zoom, 2000, cRe, cIm, bigInteger: false);
                var big = ReferenceOrbit.ComputeUncached(kind, re, im, zoom, 2000, cRe, cIm, bigInteger: true);
                Assert.True(big.Re.Length == fixedWidth.Re.Length, $"{kind} {re} {im} @{zoom}: length");
                for (int k = 0; k < big.Re.Length; k++)
                {
                    Assert.True(
                        BitConverter.DoubleToInt64Bits(big.Re[k]) == BitConverter.DoubleToInt64Bits(fixedWidth.Re[k])
                        && BitConverter.DoubleToInt64Bits(big.Im[k]) == BitConverter.DoubleToInt64Bits(fixedWidth.Im[k]),
                        $"{kind} {re} {im} @{zoom}: sample {k}");
                }
            }
            Assert.Equal(cases.Count - 2, fixedRuns);                  // all but the two over-wide cases
        }

        /// <summary>
        /// The point of the fixed-width path: a deep orbit allocates its output and little
        /// else (the BigInteger step allocated 1.5–4.7 KB per iteration).
        /// </summary>
        [Fact]
        public void FixedWidthOrbitAllocatesLittleBeyondItsSamples()
        {
            const string re = "-0.743643887037158704752191506114774", im = "0.131825904205311970493132056385139";
            ReferenceOrbit.ComputeUncached(ReferenceOrbit.Kind.Mandelbrot, re, im, 50.0, 1000, 0, 0, false);  // JIT
            long before = GC.GetAllocatedBytesForCurrentThread();
            var (orbitRe, _) = ReferenceOrbit.ComputeUncached(ReferenceOrbit.Kind.Mandelbrot, re, im, 80.0, 20000, 0, 0, false);
            long perIteration = (GC.GetAllocatedBytesForCurrentThread() - before) / orbitRe.Length;
            Assert.True(perIteration < 128, $"{perIteration} bytes per iteration");
        }

        /// <summary>A T0 and a T1 frame per family, each with escaped and interior pixels.</summary>
        public static TheoryData<string, string, string, double, int> Frames() => new TheoryData<string, string, string, double, int>
        {
            { "mandelbrot", "-0.5", "0.0", 0.0, 800 },
            { "mandelbrot", "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0, 5000 },
            { "julia", "0.0", "0.0", 0.0, 800 },
            { "julia", "1.27658194945592591790467276337476", "-0.47966605489732779175475867397901", 13.0, 600 },
            { "burning ship", "-0.5", "-0.5", -0.2, 800 },
            { "burning ship", "-1.754922416920962297102312166890", "-0.021877487111524730772258958890", 13.0, 3000 },
        };

        [Theory]
        [MemberData(nameof(Frames))]
        public void CallerBuffersMatchTheAllocatingApi(string family, string re, string im, double zoom, int maxIter)
        {
            var viewport = new Viewport(re, im, zoom);
            Func<(double[], int[])> allocating;
            Action<int[], double[]?, CancellationToken> buffered;
            switch (family)
            {
                case "mandelbrot":
                    allocating = () => new Mandelbrot(maxIter).RenderAndCounts(48, 32, viewport);
                    buffered = (c, s, t) => new Mandelbrot(maxIter).Iterations(48, 32, viewport, c, s, null, t);
                    break;
                case "julia":
                    allocating = () => new Julia(-0.123, 0.745, maxIter).RenderAndCounts(48, 32, viewport);
                    buffered = (c, s, t) => new Julia(-0.123, 0.745, maxIter).Iterations(48, 32, viewport, c, s, null, t);
                    break;
                default:
                    allocating = () => new BurningShip(maxIter).RenderAndCounts(48, 32, viewport);
                    buffered = (c, s, t) => new BurningShip(maxIter).Iterations(48, 32, viewport, c, s, null, t);
                    break;
            }
            var (render, counts) = allocating();
            var myCounts = new int[48 * 32];
            var smooth = new double[48 * 32];
            buffered(myCounts, smooth, CancellationToken.None);
            Assert.Equal(counts, myCounts);

            // Premise: a real frame, not an all-interior or one-count one.
            Assert.Contains(myCounts, n => n > 0);
            Assert.Contains(myCounts, n => n < 0);
            var escaped = new System.Collections.Generic.HashSet<double>();
            for (int i = 0; i < smooth.Length; i++)
            {
                Assert.Equal(myCounts[i] > 0, smooth[i] > 0);
                if (smooth[i] > 0)
                    escaped.Add(smooth[i]);
            }
            Assert.True(escaped.Count > 10, $"{family}: only {escaped.Count} distinct smooth values");

            var myRender = new double[48 * 32];
            FractalEngine.NormalizeRender(smooth, myRender, new double[48 * 32]);
            Assert.True(render.AsSpan().SequenceEqual(myRender), family);

            // A token that is never canceled changes nothing.
            using var never = new CancellationTokenSource();
            var tokenCounts = new int[48 * 32];
            buffered(tokenCounts, null, never.Token);
            Assert.Equal(counts, tokenCounts);
        }

        [Fact]
        public void NormalizeRenderIntoBuffersMatchesTheAllocatingForm()
        {
            var rng = new Pcg32(9);
            foreach (int escapedEvery in new[] { 0, 1, 3, 1000 })
            {
                var mu = new double[500];
                for (int i = 0; i < mu.Length; i++)
                    mu[i] = escapedEvery > 0 && i % escapedEvery == 0 ? 1 + rng.NextU32() % 900 + rng.NextU32() / 4294967296.0 : 0.0;
                var render = new double[500];
                var scratch = new double[600];
                for (int i = 0; i < scratch.Length; i++)
                    scratch[i] = double.NaN;                              // stale scratch must not matter
                FractalEngine.NormalizeRender(mu, render, scratch);
                Assert.True(FractalEngine.NormalizeRender(mu).AsSpan().SequenceEqual(render));
            }
            Assert.Throws<ArgumentException>(() => FractalEngine.NormalizeRender(new double[4], new double[3], new double[4]));
            Assert.Throws<ArgumentException>(() => FractalEngine.NormalizeRender(new double[4], new double[4], new double[3]));
            var aliased = new double[] { 0.0, 3.0, 1.0, 2.0 };
            Assert.Throws<ArgumentException>(() => FractalEngine.NormalizeRender(aliased, new double[4], aliased));
            // render may be mu itself: each value is read before it is overwritten.
            var inPlace = (double[])aliased.Clone();
            FractalEngine.NormalizeRender(inPlace, inPlace, new double[4]);
            Assert.True(FractalEngine.NormalizeRender(aliased).AsSpan().SequenceEqual(inPlace));
        }

        [Fact]
        public void TiersAndCeilings()
        {
            Assert.Equal(FractalTier.T0, FractalEngine.TierOf(-3.0));
            Assert.Equal(FractalTier.T0, FractalEngine.TierOf(12.0));
            Assert.Equal(FractalTier.T1, FractalEngine.TierOf(12.0000001));
            Assert.Equal(FractalTier.T1, FractalEngine.TierOf(290.0));
            Assert.Equal(FractalTier.T2, FractalEngine.TierOf(290.5));
            Assert.Equal(9000.0, new Mandelbrot().MaxZoomLog10);
            Assert.Equal(9000.0, new Julia().MaxZoomLog10);
            Assert.Equal(290.0, new BurningShip().MaxZoomLog10);
            Assert.Equal(12.0, new Newton().MaxZoomLog10);
            foreach (double bad in new[] { double.NaN, double.PositiveInfinity, double.NegativeInfinity })
                Assert.Throws<ArgumentException>(() => FractalEngine.TierOf(bad));
        }
    }
}
