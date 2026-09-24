using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Fractal color and the phase lookup (spec/fractal-color.md; spec/render.md "Cyclic
    /// palettes" and "Phase lookup"; spec/rng.md "Presentation noise"). The Python suite's
    /// test_coloring.py; the vectors pin the bytes, these the behavior around them.
    /// </summary>
    public class FractalColorTests
    {
        private static (int[] Counts, double[] Smooth, double[] Distance) Seahorse(double zoom = 4.0, int width = 96, int height = 64)
        {
            var counts = new int[width * height];
            var smooth = new double[width * height];
            var distance = new double[width * height];
            new Mandelbrot(1600).Fields(
                width, height,
                new Viewport("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", zoom),
                counts, smooth, null, distance);
            return (counts, smooth, distance);
        }

        [Fact]
        public void NormalizeRenderIsTheMeasuredStretchApplied()
        {
            var (_, mu, _) = Seahorse();
            Assert.True(FractalColor.TryMeasureStretch(mu, new double[mu.Length], out var stretch));
            Assert.True(stretch.Lo < stretch.Hi);
            var applied = new double[mu.Length];
            FractalColor.ApplyStretch(mu, stretch, applied);
            Assert.True(FractalEngine.NormalizeRender(mu).AsSpan().SequenceEqual(applied));
            Assert.False(FractalColor.TryMeasureStretch(new double[16], new double[16], out _));
            var flat = new double[2];
            FractalColor.ApplyStretch(new[] { 3.0, 0.0 }, new Stretch(5.0, 5.0), flat);
            Assert.Equal(new[] { Math.Sqrt(0.6), 0.0 }, flat);
        }

        [Fact]
        public void DepthPhase()
        {
            var (_, mu, _) = Seahorse();
            var t = new double[mu.Length];
            FractalColor.DepthPhase(mu, 4.0, new PhaseParams(0.02, 0.25, 0.3), t);
            double baseline = 0.3 + 0.25 * (4.0 * 3.321928094887362);
            for (int i = 0; i < mu.Length; i++)
            {
                if (mu[i] > 0.0)
                    Assert.Equal(baseline + 0.02 * (mu[i] - 0.0), t[i]);
                else
                    Assert.True(double.IsNaN(t[i]));
            }
            var a = new double[mu.Length];
            var b = new double[mu.Length];
            FractalColor.DepthPhase(mu, 0.0, new PhaseParams(), a);
            FractalColor.DepthPhase(mu, 9.5, new PhaseParams(), b);
            for (int i = 0; i < mu.Length; i++)
                Assert.True(a[i].Equals(b[i]));                   // cycles per octave 0: zoom-invariant
            Assert.Throws<ArgumentException>(() => new PhaseParams(double.NaN));
            Assert.Equal(0x400A934F0979A371L, BitConverter.DoubleToInt64Bits(FractalColor.Log2Of10));
        }

        [Fact]
        public void MeasureFrequencyAndRetune()
        {
            var (counts, mu, _) = Seahorse(7.0, 64, 48);
            var scratch = new double[2 * mu.Length];
            Assert.True(FractalColor.TryMeasureFrequency(counts, mu, 64, 0.03, 1.0, scratch, out var fit));
            Assert.True(FractalColor.TryMeasureFrequency(counts, mu, 64, 0.03, 0.01, scratch, out var capped));
            Assert.Equal(Math.Min(0.01, fit.CyclesPerIteration), capped.CyclesPerIteration);
            Assert.Equal(fit.Anchor, Math.Floor(fit.Anchor));
            Assert.Equal(1.0, FractalColor.ColorScale(1920, 1080));
            Assert.False(FractalColor.TryMeasureFrequency(new int[36], new double[36], 6, 0.03, 0.01, new double[72], out _));
            // Only finite escaped values step (an infinite pair would step by NaN, which the
            // ports would sort to opposite ends): the same fit as test_coloring.py's.
            var infMu = new double[100];
            var sevens = new int[100];
            double sum = 5.0;
            for (int i = 0; i < 100; i++)
            {
                if (i < 80)
                    sum += i + 1;
                infMu[i] = i < 80 ? sum : double.PositiveInfinity;
                sevens[i] = 7;
            }
            Assert.True(FractalColor.TryMeasureFrequency(sevens, infMu, 100, 0.03, 1.0, new double[200], out var withInf));
            Assert.Equal(0x3F90813E7C93CBF9L, BitConverter.DoubleToInt64Bits(withInf.CyclesPerIteration));
            Assert.Equal(7.0, withInf.Anchor);
            var allInf = new double[81];
            Array.Fill(allInf, double.PositiveInfinity);
            var allSevens = new int[81];
            Array.Fill(allSevens, 7);
            Assert.False(FractalColor.TryMeasureFrequency(allSevens, allInf, 9, 0.03, 0.01, new double[162], out _));

            // Retune, bit for bit (test_coloring.py pins the same), with k carried through.
            var old = new PhaseParams(0.01, 0.25, 0.2, 100.0);
            var retuned = FractalColor.Retune(old, new Frequency(0.004, 950.0), 900.0);
            Assert.Equal(0.004, retuned.CyclesPerIteration);
            Assert.Equal(0.25, retuned.CyclesPerOctave);
            Assert.Equal(950.0, retuned.Anchor);
            Assert.Equal(0x4020CCCCCCCCCCCCL, BitConverter.DoubleToInt64Bits(retuned.PhaseOffset));
            var before = new double[1];
            var after = new double[1];
            FractalColor.DepthPhase(new[] { 900.0 }, 5.0, old, before);
            FractalColor.DepthPhase(new[] { 900.0 }, 5.0, retuned, after);
            Assert.True(Math.Abs(after[0] - before[0]) < 1e-12);
        }

        [Fact]
        public void RegistriesStayApart()
        {
            Assert.Equal(new[] { "fire", "gray", "ice", "phosphor", "rainbow", "violet", "wireworld" }, Colormaps.Names);
            Assert.Equal(new[] { "deep", "classic", "embers", "glacier" }, Colormaps.CyclicNames);
            Assert.True(Colormaps.IsCyclic("deep"));
            Assert.False(Colormaps.IsCyclic("rainbow"));
            Assert.Throws<ArgumentException>(() => Colormaps.IsCyclic("nope"));
            foreach (string name in Colormaps.CyclicNames)
                Assert.Equal(768, Colormaps.Get(name).Length);
        }

        [Fact]
        public void PhaseLookupHitsEntriesAndWraps()
        {
            byte[] lut = Colormaps.Get("deep");
            var t = new double[256];
            for (int k = 0; k < 256; k++)
                t[k] = k / 256.0;
            var plain = new byte[768];
            Colormaps.ApplyPhase(t, 16, lut, plain, antialias: false, dither: 0.0);
            Assert.True(plain.AsSpan().SequenceEqual(lut));
            // Halfway between entries 255 and 0: the cycle closes, and ties round to even.
            var half = new byte[3];
            Colormaps.ApplyPhase(new[] { 255.5 / 256 }, 1, lut, half, antialias: false, dither: 0.0);
            for (int c = 0; c < 3; c++)
                Assert.Equal((byte)Math.Round((lut[765 + c] + lut[c]) / 2.0), half[c]);
            foreach (double shift in new[] { 3.0, -5.0 })
            {
                var moved = new double[256];
                for (int k = 0; k < 256; k++)
                    moved[k] = t[k] + shift;
                var rgb = new byte[768];
                Colormaps.ApplyPhase(moved, 16, lut, rgb, antialias: false, dither: 0.0);
                Assert.True(rgb.AsSpan().SequenceEqual(plain), $"shift {shift}");
            }
            byte[] fire = Colormaps.Get("fire");
            var mirror = new byte[12];
            Colormaps.ApplyPhase(new[] { 0.0, 255.0 / 510, 0.5, 1.0 - 1.0 / 510 }, 4, fire, mirror, PhaseWrap.Mirror, false, 0.0);
            Assert.Equal(new[] { fire[0], fire[1], fire[2], fire[765], fire[766], fire[767], fire[765], fire[766], fire[767], fire[3], fire[4], fire[5] }, mirror);
        }

        [Fact]
        public void InteriorAndNonFinitePhases()
        {
            var rgb = new byte[15];
            Colormaps.ApplyPhase(
                new[] { double.NaN, double.PositiveInfinity, double.NegativeInfinity, 1e308, 0.25 }, 5, Colormaps.Get("glacier"), rgb,
                dither: 0.0, interiorR: 7, interiorG: 8, interiorB: 9);
            for (int i = 0; i < 4; i++)
                Assert.Equal(new byte[] { 7, 8, 9 }, rgb.AsSpan(3 * i, 3).ToArray());
            Assert.Throws<ArgumentException>(() => Colormaps.ApplyPhase(new double[1], 1, Colormaps.Get("deep"), new byte[3], dither: -1.0));
            Assert.Throws<ArgumentException>(() => Colormaps.ApplyPhase(new double[1], 1, Colormaps.Get("deep"), new byte[3], (PhaseWrap)7));
        }

        [Fact]
        public void AntialiasFadesNoiseToTheMean()
        {
            var rng = new Pcg32(3);
            var noise = new double[32 * 32];
            for (int i = 0; i < noise.Length; i++)
                noise[i] = rng.NextU32() / 4294967296.0 * 50.0;       // tens of cycles per pixel
            byte[] lut = Colormaps.Get("classic");
            var rgb = new byte[noise.Length * 3];
            Colormaps.ApplyPhase(noise, 32, lut, rgb, dither: 0.0);
            for (int c = 0; c < 3; c++)
            {
                long sum = 0;
                for (int k = 0; k < 256; k++)
                    sum += lut[3 * k + c];
                byte mean = (byte)Math.Round(sum / 256.0);
                for (int i = 0; i < noise.Length; i++)
                    Assert.Equal(mean, rgb[3 * i + c]);
            }
        }

        [Fact]
        public void DitherKnownAnswers()
        {
            Assert.Equal(0x00000000u, Dither.Triple32(0));
            Assert.Equal(0x042741D6u, Dither.Triple32(1));
            Assert.Equal(0xF1DFE8E9u, Dither.Triple32(2));
            Assert.Equal(0xA5D6919Eu, Dither.Triple32(0x68BC21EB));
            Assert.Equal(0x0921725Eu, Dither.Triple32(0xDEADBEEF));
            Assert.Equal(-2782302622L, Dither.Tpdf(0, 0, 0, 0));
            Assert.Equal(-3302658959L, Dither.Tpdf(0, 0, 0, 1));
            Assert.Equal(239395147L, Dither.Tpdf(0, 0, 0, 2));
            Assert.Equal(964350720L, Dither.Tpdf(1, 0, 0, 0));
            Assert.Equal(179844703L, Dither.Tpdf(0, 1, 0, 0));
            Assert.Equal(-3366029565L, Dither.Tpdf(3, 5, 7, 1));
            // Amplitude 1 moves a code by at most one.
            var (_, mu, _) = Seahorse();
            var t = new double[mu.Length];
            FractalColor.DepthPhase(mu, 4.0, new PhaseParams(), t);
            byte[] lut = Colormaps.Get("deep");
            var clean = new byte[t.Length * 3];
            var dithered = new byte[t.Length * 3];
            Colormaps.ApplyPhase(t, 96, lut, clean, dither: 0.0);
            Colormaps.ApplyPhase(t, 96, lut, dithered);
            bool changed = false;
            for (int i = 0; i < clean.Length; i++)
            {
                Assert.True(Math.Abs(clean[i] - dithered[i]) <= 1);
                changed |= clean[i] != dithered[i];
            }
            Assert.True(changed);
        }

        [Fact]
        public void Shading()
        {
            const int w = 10, h = 8;
            double stroke = 1.6 / FractalColor.ColorScale(w, h);      // 1.6 pixels on this small frame
            var rgb = new byte[w * h * 3];
            Array.Fill(rgb, (byte)200);
            var de = new double[w * h];
            Array.Fill(de, 1000.0);
            de[0] = double.NaN;
            de[4 * w + 5] = 0.0;
            FractalColor.ShadeRgb(rgb, de, w, new ShadeParams(stroke), new double[2 * w * h]);
            byte core = (byte)Math.Round(200 * Math.Sqrt(0.15));
            for (int i = 0; i < w * h; i++)
                for (int c = 0; c < 3; c++)
                    Assert.Equal(i == 4 * w + 5 ? core : (byte)200, rgb[3 * i + c]);
            // A dense patch -- nothing in reach clears the stroke width -- is released.
            var dense = new double[w * h];
            Array.Fill(dense, 0.01);
            var released = new byte[w * h * 3];
            Array.Fill(released, (byte)200);
            FractalColor.ShadeRgb(released, dense, w, new ShadeParams(stroke), new double[2 * w * h]);
            Assert.All(released, v => Assert.Equal(200, v));
            FractalColor.ShadeRgb(released, dense, w, new ShadeParams(stroke, denseRelease: 0.0), new double[2 * w * h]);
            Assert.All(released, v => Assert.True(v < 200));
            Assert.Throws<ArgumentException>(() => new ShadeParams(0.0));
            Assert.Throws<ArgumentException>(() => new ShadeParams(strength: 1.5));
            Assert.Throws<ArgumentException>(() => new ShadeParams(denseRelease: -0.1));
            Assert.Throws<ArgumentException>(() => new ShadeParams(double.NaN));
            // A width that overflows once scaled to the frame is an error in both ports.
            var wide = new byte[4000 * 3];
            var five = new double[4000];
            Array.Fill(five, 5.0);
            Assert.Throws<ArgumentException>(() => FractalColor.ShadeRgb(wide, five, 4000, new ShadeParams(1e308), new double[8000]));
            // A tie: strength 0.75 at DE 0 halves a byte exactly, and 201 rounds to even (100).
            var tie = new byte[] { 201, 7, 3 };
            FractalColor.ShadeRgb(tie, new[] { 0.0 }, 1, new ShadeParams(1.0 / FractalColor.ColorScale(1, 1), 0.75, 0.0), new double[2]);
            Assert.Equal(new byte[] { 100, 4, 2 }, tie);
        }
    }
}
