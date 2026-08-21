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

        /// <summary>
        /// The end-to-end proof that C# deep-zooms on its own: replay the shipped
        /// deep-zoom vector WITHOUT handing the field an orbit, and require the exact
        /// iteration grid Python produced. The conformance suite replays this case
        /// with the vector's orbit supplied; this one makes the library build its own
        /// (spec/deep-zoom.md's sanctioned BigInteger fixed point) and still land on
        /// the same 2304 counts. Until 2026-08-21 this threw.
        /// </summary>
        [Fact]
        public void DeepZoomReplaysTheVectorWithNoCallerSuppliedOrbit()
        {
            string dir = System.IO.Path.Combine(
                TestPaths.VectorRoot(), "mandelbrot", "deep-zoom14-48");
            byte[] raw = System.IO.File.ReadAllBytes(System.IO.Path.Combine(dir, "iterations.i32"));
            var expected = new int[raw.Length / 4];
            Buffer.BlockCopy(raw, 0, expected, 0, raw.Length);

            var deep = new Viewport(
                "-0.743643887037158704752191506114774",
                "0.131825904205311970493132056385139",
                14.0);
            var field = new Mandelbrot(maxIter: 5000, escapeRadius: 1000.0);

            int[] counts = field.Iterations(48, 48, deep);

            Assert.Equal(expected.Length, counts.Length);
            for (int i = 0; i < expected.Length; i++)
                Assert.True(
                    expected[i] == counts[i],
                    $"pixel {i} ({i % 48},{i / 48}): expected {expected[i]}, got {counts[i]}");
        }

        /// <summary>
        /// A self-generated orbit is indistinguishable from a supplied one — the
        /// perturbation loop cannot tell them apart.
        /// </summary>
        [Fact]
        public void ASelfGeneratedOrbitMatchesASuppliedOne()
        {
            var deep = new Viewport(
                "-0.743643887037158704752191506114774",
                "0.131825904205311970493132056385139",
                14.0);
            var field = new Mandelbrot(maxIter: 5000, escapeRadius: 1000.0);

            int[] selfMade = field.Iterations(24, 24, deep);
            var (re, im) = ReferenceOrbit.Mandelbrot(
                deep.CenterRe, deep.CenterIm, deep.ZoomLog10, 5000);
            int[] supplied = field.Iterations(24, 24, deep, re, im);

            Assert.Equal(supplied, selfMade);
        }

        /// <summary>
        /// Newton now carries the same one-computation-two-consumers overload as the
        /// three escape-time fields, and as the Python reference's
        /// render_and_counts. Both halves must equal what the single-purpose calls
        /// return, or a caller has two sources of truth.
        /// </summary>
        [Fact]
        public void NewtonRenderAndCountsAgreesWithBothSinglePurposeCalls()
        {
            var field = new Newton(3, 60);
            var viewport = new Viewport("0.1", "-0.2", -0.1);

            var (render, counts) = field.RenderAndCounts(24, 24, viewport);

            Assert.Equal(field.Render(24, 24, viewport), render);
            Assert.Equal(field.Iterations(24, 24, viewport), counts);
            foreach (double v in render)
                Assert.InRange(v, 0.0, 1.0);
        }

        /// <summary>
        /// SmoothMu is public, matching the reference's smooth_iterations. Without
        /// it a consumer could only reach the percentile-stretched render, never the
        /// raw mu — this test would not compile if it went back to internal.
        /// </summary>
        [Fact]
        public void SmoothMuIsReachableByConsumers()
        {
            double logR = Math.Log(1000.0);
            Assert.Equal(0.0, FractalEngine.SmoothMu(-1, 0.0, 0.0, logR));   // interior
            double mu = FractalEngine.SmoothMu(7, 1200.0, 900.0, logR);
            Assert.InRange(mu, 6.0, 9.0);      // near its escape iteration
        }

        /// <summary>Above the T1 ceiling there is still no tier to fall back to.</summary>
        [Fact]
        public void BeyondThePerturbationTierStillThrows()
        {
            var field = new Mandelbrot();
            var tooDeep = new Viewport("-0.75", "0.1", 400.0);
            Assert.Throws<ArgumentException>(() => field.Iterations(16, 16, tooDeep));
        }

        /// <summary>Newton has no perturbation tier at all (spec/fractals.md).</summary>
        [Fact]
        public void NewtonStillRefusesToLeaveTheDirectTier()
        {
            var newton = new Newton();
            var deep = new Viewport("0.3", "0.5", 14.0);
            Assert.Throws<ArgumentException>(() => newton.Iterations(16, 16, deep));
        }

        /// <summary>
        /// spec/deep-zoom.md: "Tier selection is automatic and invisible to the
        /// caller." The ZOOM must decide, never whether the caller happened to pass
        /// a reference orbit — the port used to tier on `orbit != null`, so two
        /// callers with the same viewport could get different counts (T0 and T1
        /// legitimately disagree on a few percent of boundary pixels). At or below
        /// the T0 ceiling a supplied orbit is ignored, matching the Python
        /// reference, which tiers on zoom alone and takes no orbit at all.
        /// </summary>
        [Fact]
        public void TierFollowsZoomNotOrbitPresence()
        {
            var field = new Mandelbrot();
            var shallow = new Viewport("-0.743643887037151", "0.13182590420533", 3.0);

            int[] plain = field.Iterations(48, 48, shallow);

            // A perfectly usable orbit, offered at a zoom the direct tier owns.
            var orbitRe = new double[600];
            var orbitIm = new double[600];
            double zr = 0.0, zi = 0.0;
            double cr = shallow.CenterReDouble, ci = shallow.CenterImDouble;
            for (int i = 1; i < orbitRe.Length; i++)
            {
                double nr = zr * zr - zi * zi + cr;
                zi = 2.0 * zr * zi + ci;
                zr = nr;
                orbitRe[i] = zr;
                orbitIm[i] = zi;
            }
            var withOrbit = new int[48 * 48];
            field.Iterations(48, 48, shallow, orbitRe, orbitIm, withOrbit);

            Assert.Equal(plain, withOrbit);
        }

    }
}
