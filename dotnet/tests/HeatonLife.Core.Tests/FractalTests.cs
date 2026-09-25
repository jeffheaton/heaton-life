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

        /// <summary>
        /// The software fma is a real fma — one rounding, subnormals included — not just on
        /// well-scaled operands. T1 calls it as ComplexMul does, Fma(t, dz, -(u * dz')):
        /// with t of order 1 and dz down to the ~1e-292 offsets of zoom 290 and below;
        /// and, for Julia (no dc floor), with t as small as dz itself — right after a
        /// rebase onto the critical orbit W0 = 0, or while dz contracts toward an
        /// attracting cycle. Before the exact slow path the Dekker form differed from the
        /// hardware in a third of the tiny-product cases (spec/deep-zoom.md
        /// "Float-determinism gotchas"). Random bit patterns cover every exponent.
        /// </summary>
        [Fact]
        public void SoftwareFmaMatchesHardwareEverywhere()
        {
            var rng = new Pcg32(290);
            double Unit() => rng.NextU32() / 4294967296.0 * 4.0 - 2.0;
            void Check(double a, double b, double c, string where)
            {
                double expected = Math.FusedMultiplyAdd(a, b, c);
                double got = FractalEngine.Fma(a, b, c);
                Assert.True(
                    BitConverter.DoubleToInt64Bits(expected) == BitConverter.DoubleToInt64Bits(got),
                    $"fma mismatch ({where}) for ({a:R}, {b:R}, {c:R}): {expected:R} vs {got:R}");
            }

            // ComplexMul shape, t ~ 1: every T1 depth and on into the subnormals.
            for (int exp = -20; exp >= -323; exp -= 3)
            {
                double scale = Math.Pow(10.0, exp);
                for (int i = 0; i < 4000; i++)
                {
                    double t = Unit(), u = Unit(), dz = Unit() * scale, dz2 = Unit() * scale;
                    Check(t, dz, -(u * dz2), $"t~1, dz~1e{exp}");
                }
            }

            // The near-zero diagonal: t ~ dz, products down through the subnormals.
            for (int exp = -20; exp >= -170; exp -= 2)
            {
                double scale = Math.Pow(10.0, exp);
                for (int i = 0; i < 4000; i++)
                {
                    double t = Unit() * scale, u = Unit() * scale, dz = Unit() * scale, dz2 = Unit() * scale;
                    Check(t, dz, -(u * dz2), $"t~dz~1e{exp}");
                }
            }

            // Arbitrary finite bit patterns, c on its own scale: every exponent pairing.
            double Any()
            {
                long bits = ((long)rng.NextU32() << 32) | rng.NextU32();
                double x = BitConverter.Int64BitsToDouble(bits & ~(0x7FFL << 52) | ((long)(rng.NextU32() % 2047) << 52));
                return x;
            }
            for (int i = 0; i < 400_000; i++)
            {
                double a = Any(), b = Any(), c = Any();
                Check(a, b, c, "random bits");                    // products that overflow included
                if (!double.IsInfinity(a * b))
                    Check(a, b, -(a * b), "near cancellation");
            }

            // Infinities and NaN in every position, against finite, zero and overflowing
            // products. NaN payloads are not compared, only NaN-ness.
            double[] specials =
            {
                0.0, -0.0, 1.5, -2.5e-300, 2e154, -2e154, 1.7976931348623157e308, 4.9e-324,
                double.PositiveInfinity, double.NegativeInfinity, double.NaN,
            };
            foreach (double a in specials)
            {
                foreach (double b in specials)
                {
                    foreach (double c in specials)
                    {
                        double expected = Math.FusedMultiplyAdd(a, b, c);
                        double got = FractalEngine.Fma(a, b, c);
                        Assert.True(
                            double.IsNaN(expected)
                                ? double.IsNaN(got)
                                : BitConverter.DoubleToInt64Bits(expected) == BitConverter.DoubleToInt64Bits(got),
                            $"fma mismatch (specials) for ({a:R}, {b:R}, {c:R}): {expected:R} vs {got:R}");
                    }
                }
            }
        }

        /// <summary>
        /// Ties that only the product's error term breaks. With c a 53-bit x and a*b =
        /// ±h(1 − k²2^−2m), h = ulp(x)/2, the product rounds to ±h whenever k² ≤ 2^(2m−54)
        /// (about half the draws; the rest are ordinary Dekker-path checks), so p + c is an
        /// exact tie and the tiny error e alone decides the rounding. Rounding t + e and then
        /// s + t + e to nearest rounds twice and lands on the even neighbor instead: a quarter
        /// of these checks went wrong before the error terms were rounded to odd, and random
        /// operands almost never produce one (22 in 2,000,000 of the reviewer's family).
        /// </summary>
        [Fact]
        public void SoftwareFmaBreaksTiesWithTheProductsErrorTerm()
        {
            void Check(double a, double b, double c)
            {
                double expected = Math.FusedMultiplyAdd(a, b, c);
                double got = FractalEngine.Fma(a, b, c);
                Assert.True(
                    BitConverter.DoubleToInt64Bits(expected) == BitConverter.DoubleToInt64Bits(got),
                    $"fma mismatch for ({a:R}, {b:R}, {c:R}): {expected:R} vs {got:R}");
            }

            // The case the second release review found: the hardware gives 1 + 2^-52.
            Check(1.0 + Math.Pow(2, -30), Math.Pow(2, -53) * (1.0 - Math.Pow(2, -30)), 1.0 + Math.Pow(2, -52));

            var rng = new Pcg32(1101);
            for (int i = 0; i < 200_000; i++)
            {
                int exponent = (int)(rng.NextU32() % 1800) - 900;
                long mantissa = (1L << 52) | (((long)rng.NextU32() << 20 | (rng.NextU32() >> 12)) & ((1L << 52) - 1));
                double x = mantissa * Math.Pow(2, exponent - 52);
                double h = (BitConverter.Int64BitsToDouble(BitConverter.DoubleToInt64Bits(x) + 1) - x) / 2.0;
                int m = 27 + (int)(rng.NextU32() % 19);
                int shift = (int)(rng.NextU32() % 40) - 20;
                double k = 1 + rng.NextU32() % 1023;
                double a = (1.0 + k * Math.Pow(2, -m)) * Math.Pow(2, shift);
                double b = (rng.NextU32() % 2 == 0 ? 1 : -1) * h * (1.0 - k * Math.Pow(2, -m)) * Math.Pow(2, -shift);
                Check(a, b, x);
                Check(a, -b, -x);
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

        /// <summary>spec/fractals.md "Counts convention": |z|² &gt; R² could never fire.</summary>
        [Theory]
        [InlineData(1e200)]
        [InlineData(double.PositiveInfinity)]
        [InlineData(double.NaN)]
        public void EscapeRadiusSquaredMustBeFinite(double radius)
        {
            Assert.Throws<ArgumentException>(() => new Mandelbrot(100, radius));
            Assert.Throws<ArgumentException>(() => new Julia(0.0, 1.0, 100, radius));
            Assert.Throws<ArgumentException>(() => new BurningShip(100, radius));
            _ = new Mandelbrot(100, 1.3e154);   // its square is still finite
        }

        /// <summary>Past a family's own ceiling there is no tier to fall back to.</summary>
        [Fact]
        public void EachFamilyRefusesZoomsPastItsCeiling()
        {
            // Mandelbrot and Julia render T2 to 1e9000; the Burning Ship stops at T1; a zoom
            // that is not finite is refused before any orbit work.
            Assert.Throws<ArgumentException>(() => new Mandelbrot().Iterations(16, 16, new Viewport("-0.75", "0.1", 9000.5)));
            Assert.Throws<ArgumentException>(() => new BurningShip().Iterations(16, 16, new Viewport("-0.75", "0.1", 300.0)));
            ReferenceOrbit.ClearCache();
            Assert.Throws<ArgumentException>(() => new Julia().Iterations(16, 16, new Viewport("-0.75", "0.1", double.NaN)));
            Assert.Equal(0, ReferenceOrbit.CacheUsage.Count);
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
