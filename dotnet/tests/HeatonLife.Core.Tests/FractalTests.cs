using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class FractalTests
    {
        [Fact]
        public void SoftwareFmaMatchesHardwareIntrinsic()
        {
            // The Core library targets netstandard2.1 (no Math.FusedMultiplyAdd), so it
            // carries a software fma; the test project targets net10.0 where the real
            // intrinsic exists. Pin them bitwise across the magnitudes fractal
            // iteration produces (escape radius 1e3 -> products up to ~1e6, deltas
            // down to ~1e-20 at deep zoom).
            var rng = new Pcg32(2024);
            double Draw()
            {
                double mantissa = rng.NextU32() / 4294967296.0 * 4.0 - 2.0;
                int exp = (int)(rng.NextU32() % 41) - 20; // 1e-20 .. 1e20
                return mantissa * Math.Pow(10.0, exp);
            }
            for (int i = 0; i < 2_000_000; i++)
            {
                double a = Draw(), b = Draw(), c = Draw();
                double expected = Math.FusedMultiplyAdd(a, b, c);
                double got = FractalEngine.Fma(a, b, c);
                Assert.True(
                    BitConverter.DoubleToInt64Bits(expected) == BitConverter.DoubleToInt64Bits(got),
                    $"fma mismatch for ({a:R}, {b:R}, {c:R}): {expected:R} vs {got:R}");
            }
        }

        [Fact]
        public void MandelbrotInteriorNeverEscapes()
        {
            var field = new Mandelbrot(200);
            int[] counts = field.Iterations(16, 16, new Viewport("-0.5", "0.0", 1.0));
            // The view is well inside the set at zoom 10: the center pixel is interior.
            Assert.Equal(-1, counts[8 * 16 + 8]);
        }

        [Fact]
        public void JuliaIsSymmetricUnderNegation()
        {
            // z^2 preserves z -> -z, so the classic Julia grid equals its 180° rotation.
            var field = new Julia();
            int[] counts = field.Iterations(32, 32, new Viewport("0.0", "0.0", 0.0));
            for (int i = 0; i < counts.Length; i++)
                Assert.Equal(counts[i], counts[counts.Length - 1 - i]);
        }

        [Fact]
        public void NewtonConvergesToAllRootsOfZCubed()
        {
            var field = new Newton(3, 60);
            var (roots, iters) = field.Basins(32, 32, new Viewport("0.0", "0.0", -0.1));
            var seen = new bool[3];
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i] >= 0)
                {
                    seen[roots[i]] = true;
                    Assert.True(iters[i] >= 1);
                }
            }
            Assert.True(seen[0] && seen[1] && seen[2], "all three basins should appear");
        }

        [Fact]
        public void DeepZoomRequiresOrbit()
        {
            var field = new Mandelbrot();
            var deep = new Viewport("-0.75", "0.1", 20.0);
            Assert.Throws<ArgumentException>(() => field.Iterations(64, 64, deep));
        }
    }
}
