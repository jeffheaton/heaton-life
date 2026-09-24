using System;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The off-center reference (spec/deep-zoom.md "Off-center reference"): a T1 frame may
    /// iterate a reference R other than its center C, offsetting every pixel by
    /// round64(C − R). The vectors pin the ports to each other; these pin the rest — the
    /// offset's one rounding (the Python suite's table), that R = C is the centered
    /// frame, that T0 ignores R, and that C# computes R's orbit itself.
    /// </summary>
    public class OffCenterReferenceTests
    {
        private const string SeahorseRe = "-0.743643887037158704752191506114774";
        private const string SeahorseIm = "0.131825904205311970493132056385139";
        private const string BetaRe = "1.27658194945592591790467276337476";
        private const string BetaIm = "-0.47966605489732779175475867397901";
        private const string ShipRe = "0.403269293475576420989278613990";
        private const string ShipIm = "-0.595275727121703516488710194270";

        /// <summary>round64(minuend − subtrahend) as bit patterns: test_off_center_reference.py's DIFFERENCES.</summary>
        public static TheoryData<string, string, ulong> Differences() => new TheoryData<string, string, ulong>
        {
            { "0.10", "0.1", 0x0000000000000000 },                   // an exact zero is +0.0 ...
            { "-0", "0", 0x0000000000000000 },
            { "  -2.5e+3 ", "-2500.000", 0x0000000000000000 },
            { SeahorseRe, "-0.743643887037146704752191506114774", 0xBD0B05876E5B0120 },
            { "0.1000000000000000055511151231257827", "0.1", 0x3C5999999999999A }, // both round to 0.1
            { "1." + new string('0', 300) + "1", "1", 0x017124E63593F5E1 },
            { "1.5e-14", "5E-15", 0x3D06849B86A12B9B },
            { "9007199254740993", "0", 0x4340000000000000 },         // ties to even: down ...
            { "9007199254740995", "0", 0x4340000000000002 },         // ... and up
            { "3e-324", "0", 0x0000000000000001 },                   // the least subnormal
            { "0", "2e-324", 0x8000000000000000 },                   // a nonzero underflow keeps its sign
            { "1e309", "0", 0x7FF0000000000000 },
            { "-1e400", "1e400", 0xFFF0000000000000 },
            { "1e-100000", "-1e-100000", 0x0000000000000000 },
        };

        [Theory]
        [MemberData(nameof(Differences))]
        public void DifferenceIsTheExactDifferenceRoundedOnce(string minuend, string subtrahend, ulong expected)
            => Assert.Equal(expected, (ulong)BitConverter.DoubleToInt64Bits(DecimalText.Difference(minuend, subtrahend)));

        [Fact]
        public void AViewportCarriesAReferenceBothOrNeither()
        {
            var centered = new Viewport(SeahorseRe, SeahorseIm, 14.0);
            Assert.False(centered.HasReference);
            Assert.Equal(SeahorseRe, centered.OrbitCenterRe);
            Assert.Equal(SeahorseIm, centered.OrbitCenterIm);
            Assert.Equal(0.0, centered.ReferenceOffsetRe);

            var vp = centered.WithReference("-0.7436438870371467", "0");
            Assert.True(vp.HasReference);
            Assert.Equal("-0.7436438870371467", vp.OrbitCenterRe);
            Assert.Equal("0", vp.OrbitCenterIm);
            Assert.Equal(SeahorseRe, vp.CenterRe);
            Assert.False(vp.WithReference(null, null).HasReference);
            Assert.False(new Viewport(SeahorseRe, SeahorseIm, 14.0, null, null).HasReference);

            Assert.Throws<ArgumentException>(() => new Viewport(SeahorseRe, SeahorseIm, 14.0, "0.1", null));
            Assert.Throws<ArgumentException>(() => centered.WithReference(null, "0.1"));
            Assert.Throws<ArgumentException>(() => centered.WithReference("NaN", "0"));
        }

        [Fact]
        public void TheOffsetIsExactNotADifferenceOfDoubles()
        {
            // References that agree with the center to 20 places: the same float64 projections.
            const string refRe = "-0.743643887037158704753", refIm = "0.131825904205311970491";
            var vp = new Viewport(SeahorseRe, SeahorseIm, 20.0, refRe, refIm);
            Assert.Equal(0x3B8E8B45E7719C9EUL, (ulong)BitConverter.DoubleToInt64Bits(vp.ReferenceOffsetRe));
            Assert.Equal(0x3BA422FEFB8AF0B3UL, (ulong)BitConverter.DoubleToInt64Bits(vp.ReferenceOffsetIm));
            var reference = new Viewport(refRe, refIm);
            Assert.Equal(0.0, vp.CenterReDouble - reference.CenterReDouble);   // premise: doubles lose it all
            Assert.Equal(0.0, vp.CenterImDouble - reference.CenterImDouble);
        }

        /// <summary>
        /// The deltas of a 16x9 frame of the Seahorse at 1e14 with its reference (0.3, -0.2)
        /// frames away — test_off_center_reference.py's DELTAS_RE / DELTAS_IM. The offref
        /// vectors cannot see a last-bit change in a delta (their Julia and Burning Ship
        /// frames are well conditioned); this table can, and every family forms its deltas
        /// through DeltaRe/DeltaIm.
        /// </summary>
        [Fact]
        public void DeltasMatchTheSharedTable()
        {
            ulong[] deltasRe =
            {
                0xBD214F8AC2B24CB8, 0xBD1FCE82149073FE, 0xBD1CFDEEA3BC4E8A, 0xBD1A2D5B32E82917,
                0xBD175CC7C21403A4, 0xBD148C34513FDE30, 0xBD11BBA0E06BB8BD, 0xBD0DD61ADF2F2693,
                0xBD0834F3FD86DBAD, 0xBD0293CD1BDE90C6, 0xBCF9E54C746C8BBE, 0xBCED45FD6237EBE0,
                0xBCCB05876E5B0120, 0x3CDF86735614D6A8, 0x3CF323EA98D5CB78, 0x3CFE66385C266144,
            };
            ulong[] deltasIm =
            {
                0x3D14442592C440D8, 0x3D11739221F01B65, 0x3D0D45FD6237EBE4, 0x3D07A4D6808FA0FD,
                0x3D0203AF9EE75616, 0x3CF8C5117A7E165E, 0x3CEB05876E5B0122, 0x3CC203AF9EE75620,
                0xBCE203AF9EE75614,
            };
            var vp = new Viewport(SeahorseRe, SeahorseIm, 14.0,
                "-0.743643887037146704752191506114774", "0.131825904205303970493132056385139");
            double ps = FractalEngine.PixelScale(16, vp);
            for (int x = 0; x < 16; x++)
                Assert.Equal(deltasRe[x], (ulong)BitConverter.DoubleToInt64Bits(FractalEngine.DeltaRe(x, 16, ps, vp.ReferenceOffsetRe)));
            for (int y = 0; y < 9; y++)
                Assert.Equal(deltasIm[y], (ulong)BitConverter.DoubleToInt64Bits(FractalEngine.DeltaIm(y, 9, ps, vp.ReferenceOffsetIm)));
        }

        /// <summary>
        /// An overflowing offset is absurd but defined: d = ±∞ enters each component apart
        /// and IEEE takes it from there — including the software fma's infinite addend, which
        /// the last frame reaches (2·dz·dz overflows). test_off_center_reference.py's NON_FINITE.
        /// </summary>
        public static TheoryData<string, string, string, string, int[], int[], int[]> NonFinite() =>
            new TheoryData<string, string, string, string, int[], int[], int[]>
            {
                { "0", "1e400", "0", "0", new[] { 1, 1, 1, 1, 1, 1 }, new[] { 1, -1, 1, 1, -1, 1 }, new[] { 1, 1, 1, 1, 1, 1 } },
                { "1e400", "0", "0", "0", new[] { 1, 1, 1, 1, 1, 1 }, new[] { 1, 1, 1, 1, 1, 1 }, new[] { 1, 1, 1, 1, 1, 1 } },
                { "0", "1e308", "0", "-1e308", new[] { 1, 1, 1, 1, 1, 1 }, new[] { -1, -1, -1, -1, -1, -1 }, new[] { 1, 1, 1, 1, 1, 1 } },
                { "2e154", "2e154", "0", "0", new[] { 1, 1, 1, 1, 1, 1 }, new[] { 1, 1, 1, 1, 1, 1 }, new[] { 1, 1, 1, 1, 1, 1 } },
            };

        [Theory]
        [MemberData(nameof(NonFinite))]
        public void NonFiniteOffsetsFollowIeee(
            string centerRe, string centerIm, string refRe, string refIm, int[] mandelbrot, int[] julia, int[] burningShip)
        {
            var vp = new Viewport(centerRe, centerIm, 13.0, refRe, refIm);
            Assert.Equal(mandelbrot, new Mandelbrot(50).Iterations(3, 2, vp));
            Assert.Equal(julia, new Julia(-0.123, 0.745, 50).Iterations(3, 2, vp));
            Assert.Equal(burningShip, new BurningShip(50).Iterations(3, 2, vp));
        }

        public static TheoryData<string> Families() => new TheoryData<string> { "mandelbrot", "julia", "burning-ship" };

        private static (string Re, string Im, double Zoom) Deep(string family) => family switch
        {
            "mandelbrot" => (SeahorseRe, SeahorseIm, 14.0),
            "julia" => (BetaRe, BetaIm, 13.0),
            _ => (ShipRe, ShipIm, 13.0),
        };

        /// <summary>Counts and raw smooth values of the offref vectors' fields.</summary>
        private static (int[] Counts, double[] Smooth) Frame(
            string family, Viewport viewport, int width, int height, int workers = 1)
        {
            var counts = new int[width * height];
            var smooth = new double[width * height];
            switch (family)
            {
                case "mandelbrot":
                    new Mandelbrot(5000, workers: workers).Iterations(width, height, viewport, counts, smooth);
                    break;
                case "julia":
                    new Julia(-0.123, 0.745, 600, workers: workers).Iterations(width, height, viewport, counts, smooth);
                    break;
                default:
                    new BurningShip(1000, workers: workers).Iterations(width, height, viewport, counts, smooth);
                    break;
            }
            return (counts, smooth);
        }

        /// <summary>R = C, even spelled differently, is the centered frame: counts and smooth values.</summary>
        [Theory]
        [MemberData(nameof(Families))]
        public void AReferenceAtTheCenterChangesNothing(string family)
        {
            var (re, im, zoom) = Deep(family);
            var centered = new Viewport(re, im, zoom);
            var (wantCounts, wantSmooth) = Frame(family, centered, 24, 16);
            Assert.Contains(wantCounts, n => n > 0);                  // premise: a real frame
            Assert.Contains(wantCounts, n => n < 0);
            foreach (var (refRe, refIm) in new[] { (re, im), (re + "000", im + "0e0") })
            {
                var vp = centered.WithReference(refRe, refIm);
                Assert.Equal(0L, BitConverter.DoubleToInt64Bits(vp.ReferenceOffsetRe));
                Assert.Equal(0L, BitConverter.DoubleToInt64Bits(vp.ReferenceOffsetIm));
                var (counts, smooth) = Frame(family, vp, 24, 16);
                Assert.Equal(wantCounts, counts);
                Assert.True(wantSmooth.AsSpan().SequenceEqual(smooth), family);
            }
        }

        [Theory]
        [MemberData(nameof(Families))]
        public void T0IgnoresTheReference(string family)
        {
            var (re, im, _) = Deep(family);
            var shallow = new Viewport(re, im, 6.0);
            var (want, _) = Frame(family, shallow, 24, 16);
            var (got, _) = Frame(family, shallow.WithReference("0.25", "-0.5"), 24, 16);
            Assert.Equal(want, got);
        }

        /// <summary>
        /// The offref vectors again, but rendered from the viewport alone — C# computing the
        /// reference's orbit, where the conformance runner replays the stored one.
        /// </summary>
        [Theory]
        [InlineData("mandelbrot", "deep-zoom14-offref-48")]
        [InlineData("julia", "deep-zoom13-offref-32")]
        [InlineData("burning-ship", "deep-zoom13-offref-32")]
        public void ComputesTheReferencesOrbitItself(string family, string caseName)
        {
            string dir = Path.Combine(TestPaths.VectorRoot(), family, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            var vp = doc.RootElement.GetProperty("viewport");
            var viewport = new Viewport(
                vp.GetProperty("center_re").GetString()!,
                vp.GetProperty("center_im").GetString()!,
                vp.GetProperty("zoom_log10").GetDouble(),
                vp.GetProperty("reference_re").GetString()!,
                vp.GetProperty("reference_im").GetString()!);
            int width = doc.RootElement.GetProperty("size")[0].GetInt32();
            int height = doc.RootElement.GetProperty("size")[1].GetInt32();
            byte[] bytes = File.ReadAllBytes(Path.Combine(dir, "iterations.i32"));
            var expected = new int[bytes.Length / 4];
            Buffer.BlockCopy(bytes, 0, expected, 0, bytes.Length);
            foreach (int workers in new[] { 1, 3 })
                Assert.Equal(expected, Frame(family, viewport, width, height, workers).Counts);
        }

        [Fact]
        public void ReferenceOnScreenMeasuresWidthAndHeight()
        {
            var vp = new Viewport(SeahorseRe, SeahorseIm, 14.0);
            Assert.True(FractalEngine.ReferenceOnScreen(48, 32, vp));     // no reference: the center
            // References (fx, fy) frame widths from the center, exactly (Python's _moved).
            var at0302 = vp.WithReference("-0.743643887037146704752191506114774", "0.131825904205303970493132056385139");
            var at4933 = vp.WithReference("-0.743643887037178304752191506114774", "0.131825904205325170493132056385139");
            var at5100 = vp.WithReference("-0.743643887037138304752191506114774", SeahorseIm);
            var at0034 = vp.WithReference(SeahorseRe, "0.131825904205325570493132056385139");
            Assert.True(FractalEngine.ReferenceOnScreen(48, 32, at0302));   // (0.3, -0.2)
            Assert.True(FractalEngine.ReferenceOnScreen(48, 32, at4933));   // (-0.49, 0.33)
            Assert.False(FractalEngine.ReferenceOnScreen(48, 32, at5100));  // (0.51, 0)
            Assert.False(FractalEngine.ReferenceOnScreen(48, 32, at0034));  // (0, 0.34): the height is 2/3 of the width
            Assert.True(FractalEngine.ReferenceOnScreen(32, 48, at0034));
            Assert.False(FractalEngine.ReferenceOnScreen(48, 32, vp.WithReference("1e400", "0")));  // d = inf
        }

        /// <summary>Past zoom 290 the comparison runs in floatexp: the same fractions give the same answers at zoom 1000.</summary>
        [Fact]
        public void ReferenceOnScreenAtT2()
        {
            var vp = new Viewport("0", "0", 1000.0);   // 4e-1000 is one frame width
            Assert.True(FractalEngine.ReferenceOnScreen(48, 32, vp.WithReference("1.2e-1000", "-8e-1001")));     // (0.3, -0.2)
            Assert.True(FractalEngine.ReferenceOnScreen(48, 32, vp.WithReference("-1.96e-1000", "1.32e-1000")));  // (-0.49, 0.33)
            Assert.False(FractalEngine.ReferenceOnScreen(48, 32, vp.WithReference("2.04e-1000", "0")));          // (0.51, 0)
            Assert.False(FractalEngine.ReferenceOnScreen(48, 32, vp.WithReference("0", "1.36e-1000")));          // (0, 0.34)
            Assert.True(FractalEngine.ReferenceOnScreen(32, 48, vp.WithReference("0", "1.36e-1000")));
        }
    }

    /// <summary>The cache half: it runs alone, like every test that asserts what the cache holds.</summary>
    [Collection("orbit cache")]
    public class OffCenterReferenceCacheTests
    {
        private const string SeahorseRe = "-0.743643887037158704752191506114774";
        private const string SeahorseIm = "0.131825904205311970493132056385139";

        /// <summary>
        /// The cache key is the reference's, so a pan that keeps it runs no orbit — the point
        /// of the feature. RenderProgress tells a hit (no orbit phase) from a computation.
        /// </summary>
        [Fact]
        public void PanningWithAKeptReferenceRunsNoOrbit()
        {
            ReferenceOrbit.ClearCache();
            var field = new Mandelbrot(maxIter: 3000);
            var counts = new int[32 * 32];
            // A tenth of a frame per step at 1e20 (Python's _moved), the reference kept throughout.
            string[] pans =
            {
                SeahorseRe,
                "-0.743643887037158704748191506114774",
                "-0.743643887037158704744191506114774",
                "-0.743643887037158704740191506114774",
            };
            for (int i = 0; i < pans.Length; i++)
            {
                var vp = new Viewport(pans[i], SeahorseIm, 20.0, SeahorseRe, SeahorseIm);
                Assert.True(FractalEngine.ReferenceOnScreen(32, 32, vp));
                var progress = new RenderProgress();
                field.Iterations(32, 32, vp, counts, null, progress);
                Assert.Equal(i == 0 ? 3000 : 0, progress.OrbitTotal);
            }

            // Premise: centered, the same pan is a new orbit.
            var centered = new RenderProgress();
            field.Iterations(32, 32, new Viewport(pans[1], SeahorseIm, 20.0), counts, null, centered);
            Assert.Equal(3000, centered.OrbitTotal);
            ReferenceOrbit.ClearCache();
        }

        /// <summary>
        /// A family's T1 frame computes R's orbit, not C's (and Julia's critical orbit): after
        /// the render, R's orbit is a cache hit and C's is not. The Julia and Burning Ship
        /// offref vectors equal their centered frames, so this is what catches a family
        /// that ignores the reference when it computes its own orbit.
        /// </summary>
        [Theory]
        [InlineData("mandelbrot", "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0,
            "-0.743643887037146704752191506114774", "0.131825904205303970493132056385139")]
        [InlineData("julia", "1.27658194945592591790467276337476", "-0.47966605489732779175475867397901", 13.0,
            "1.27658194945578591790467276337476", "-0.47966605489722779175475867397901")]
        [InlineData("burning-ship", "0.403269293475576420989278613990", "-0.595275727121703516488710194270", 13.0,
            "0.403269293475696420989278613990", "-0.595275727121583516488710194270")]
        public void EachFamilyIteratesTheReferencesOrbit(
            string family, string centerRe, string centerIm, double zoom, string refRe, string refIm)
        {
            const int maxIter = 600;
            ReferenceOrbit.ClearCache();
            var vp = new Viewport(centerRe, centerIm, zoom, refRe, refIm);
            var kind = family == "julia" ? ReferenceOrbit.Kind.Julia
                : family == "burning-ship" ? ReferenceOrbit.Kind.BurningShip : ReferenceOrbit.Kind.Mandelbrot;
            double cRe = family == "julia" ? -0.123 : 0.0, cIm = family == "julia" ? 0.745 : 0.0;
            switch (family)
            {
                case "mandelbrot": new Mandelbrot(maxIter).Iterations(16, 16, vp); break;
                case "julia": new Julia(cRe, cIm, maxIter).Iterations(16, 16, vp); break;
                default: new BurningShip(maxIter).Iterations(16, 16, vp); break;
            }

            int OrbitWork(string re, string im)
            {
                var progress = new RenderProgress();
                // A Julia frame's orbits run at twice its zoom (FractalEngine.OrbitZoom).
                ReferenceOrbit.Compute(kind, re, im, FractalEngine.OrbitZoom(family == "julia", zoom), maxIter, cRe, cIm, progress);
                return progress.OrbitTotal;
            }
            Assert.Equal(0, OrbitWork(refRe, refIm));                   // cached by the render
            if (family == "julia")
                Assert.Equal(0, OrbitWork("0", "0"));                   // the critical orbit
            Assert.NotEqual(0, OrbitWork(centerRe, centerIm));          // never computed
            ReferenceOrbit.ClearCache();
        }
    }
}
