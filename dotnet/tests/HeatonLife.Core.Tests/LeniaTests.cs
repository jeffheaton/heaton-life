using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class LeniaTests
    {
        [Fact]
        public void RingKernelNormalizedAndCentered()
        {
            double[] kernel = RingKernel.Build(64, 64, 13);
            Assert.Equal(64 * 64, kernel.Length);
            Assert.Equal(0.0, kernel[0]); // r = 0 excluded
            double sum = 0.0;
            foreach (double v in kernel)
            {
                Assert.True(v >= 0.0);
                sum += v;
            }
            Assert.True(Math.Abs(sum - 1.0) < 1e-12);
            // wrapped symmetry: K(x) == K(-x) on the torus
            for (int y = 0; y < 64; y++)
                for (int x = 0; x < 64; x++)
                {
                    double mirrored = kernel[((64 - y) % 64) * 64 + (64 - x) % 64];
                    Assert.True(Math.Abs(kernel[y * 64 + x] - mirrored) < 1e-15);
                }
        }

        [Fact]
        public void RingKernelRejectsOversizedRadius()
        {
            Assert.Throws<ArgumentException>(() => RingKernel.Build(16, 16, 8));
        }

        [Fact]
        public void EmptyWorldStaysEssentiallyEmpty()
        {
            var zero = new double[32 * 32];
            var classic = new ClassicLenia(32, 32, radius: 8);
            classic.SetState(zero);
            classic.Step(10);
            foreach (double v in classic.State)
                Assert.True(v < 1e-12);

            var asymptotic = new AsymptoticLenia(32, 32, radius: 8);
            asymptotic.SetState(zero);
            asymptotic.Step(10);
            foreach (double v in asymptotic.State)
                Assert.True(v < 1e-12);

            var flow = new FlowLenia(32, 32, radius: 8);
            flow.SetState(zero);
            flow.Step(10);
            foreach (double v in flow.State)
                Assert.Equal(0.0, v);
        }

        [Fact]
        public void ClassicBoundedAndAliveWithDefaults()
        {
            var sim = new ClassicLenia(128, 128); // ctor seeds blobs(40, 0), the Python default
            sim.Step(300);
            var stats = Stats(sim.State);
            Assert.True(stats.Min >= 0.0 && stats.Max <= 1.0);
            Assert.True(stats.Mean > 0.01, "default params should sustain life");
            Assert.True(stats.Std > 0.05, "structure, not uniformity");
        }

        [Fact]
        public void AsymptoticBoundedWithoutClipping()
        {
            var sim = new AsymptoticLenia(96, 96); // 96 is not a power of two: Bluestein path
            sim.SeedBlobs(40, 1);
            sim.Step(200);
            var stats = Stats(sim.State);
            Assert.True(stats.Min >= 0.0 && stats.Max <= 1.0);
            Assert.True(stats.Std > 0.05);
        }

        [Fact]
        public void FlowConservesMassAndClumps()
        {
            var sim = new FlowLenia(128, 128); // ctor seeds soup(0.5, 0), the Python default
            var before = Stats(sim.State);
            sim.Step(100);
            var after = Stats(sim.State);
            Assert.True(
                Math.Abs(after.Sum - before.Sum) / before.Sum < 1e-9,
                "flow must conserve mass");
            Assert.True(after.Std > before.Std * 1.5, "soup should aggregate into clumps");
        }

        [Fact]
        public void Determinism()
        {
            var a = new ClassicLenia(64, 64);
            var b = new ClassicLenia(64, 64);
            a.SeedBlobs(40, 9);
            b.SeedBlobs(40, 9);
            a.Step(20);
            b.Step(20);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
        }

        private static (double Min, double Max, double Sum, double Mean, double Std) Stats(
            ReadOnlySpan<double> values)
        {
            double min = double.PositiveInfinity, max = double.NegativeInfinity, sum = 0, sumSq = 0;
            foreach (double v in values)
            {
                min = Math.Min(min, v);
                max = Math.Max(max, v);
                sum += v;
                sumSq += v * v;
            }
            double mean = sum / values.Length;
            return (min, max, sum, mean, Math.Sqrt(sumSq / values.Length - mean * mean));
        }
    }
}
