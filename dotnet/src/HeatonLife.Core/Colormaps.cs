using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>How a phase lookup maps one cycle onto a LUT (spec/render.md "Phase lookup").</summary>
    public enum PhaseWrap
    {
        /// <summary>256 positions, entry k at t = k/256 — for the cyclic palettes.</summary>
        Cyclic = 0,

        /// <summary>510 positions, up the LUT and back down — any colormap, without a seam.</summary>
        Mirror = 1,
    }

    /// <summary>
    /// Built-in colormaps (256x3 byte LUTs) — spec/render.md. LUTs are rebuilt from
    /// the spec'd anchors with piecewise-linear interpolation and half-even rounding,
    /// byte-identical with the Python reference (gated by vectors/render/); the cyclic
    /// palettes are data (<see cref="PaletteTables"/>). The flat RGB output drops straight
    /// into a Unity Color32/Texture2D upload.
    /// </summary>
    public static class Colormaps
    {
        private static readonly Dictionary<string, int[][]> Anchors = new Dictionary<string, int[][]>
        {
            ["gray"] = new[] { new[] { 0, 0, 0 }, new[] { 255, 255, 255 } },
            ["phosphor"] = new[]
            {
                new[] { 6, 10, 6 }, new[] { 10, 60, 25 },
                new[] { 40, 200, 90 }, new[] { 170, 255, 190 },
            },
            ["fire"] = new[]
            {
                new[] { 0, 0, 0 }, new[] { 120, 16, 0 },
                new[] { 255, 140, 0 }, new[] { 255, 255, 220 },
            },
            ["ice"] = new[]
            {
                new[] { 0, 0, 0 }, new[] { 0, 40, 110 },
                new[] { 70, 160, 255 }, new[] { 230, 250, 255 },
            },
            ["violet"] = new[]
            {
                new[] { 8, 4, 16 }, new[] { 90, 30, 140 },
                new[] { 200, 100, 255 }, new[] { 255, 240, 255 },
            },
            // Anchors land exactly on indices 0/85/170/255 -> Wireworld's 4 states get
            // the classic empty/head/tail/conductor colors under frame = state * 85.
            ["wireworld"] = new[]
            {
                new[] { 0, 0, 0 }, new[] { 70, 130, 255 },
                new[] { 255, 80, 60 }, new[] { 255, 210, 70 },
            },
            // Closed hue wheel: index 255 matches index 0, which suits cyclic CA states.
            ["rainbow"] = new[]
            {
                new[] { 220, 40, 40 }, new[] { 230, 200, 40 }, new[] { 60, 200, 70 },
                new[] { 50, 200, 220 }, new[] { 70, 70, 230 }, new[] { 200, 60, 220 },
                new[] { 220, 40, 40 },
            },
        };

        /// <summary>Names of the anchor colormaps (the clipping lookup's), sorted.</summary>
        public static IReadOnlyList<string> Names
        {
            get
            {
                var names = new List<string>(Anchors.Keys);
                names.Sort(StringComparer.Ordinal);
                return names;
            }
        }

        /// <summary>
        /// Names of the cyclic palettes (spec/render.md "Cyclic palettes"), for
        /// <see cref="ApplyPhase"/>: deep, classic, embers, glacier.
        /// </summary>
        public static IReadOnlyList<string> CyclicNames => new List<string>(PaletteTables.Names);

        /// <summary>True for a cyclic palette, false for an anchor colormap; unknown names throw.</summary>
        public static bool IsCyclic(string name)
        {
            if (Array.IndexOf(PaletteTables.Names, name) >= 0)
                return true;
            if (Anchors.ContainsKey(name))
                return false;
            throw new ArgumentException($"unknown colormap '{name}'");
        }

        /// <summary>
        /// The 256x3 LUT for a named colormap or cyclic palette (flat 768 bytes, RGB rows).
        /// </summary>
        public static byte[] Get(string name)
        {
            int table = Array.IndexOf(PaletteTables.Names, name);
            if (table >= 0)
                return FromHex(PaletteTables.Hex[table]);
            if (!Anchors.TryGetValue(name, out var anchors))
                throw new ArgumentException($"unknown colormap '{name}'");
            int k = anchors.Length;
            double positionStep = 1.0 / (k - 1);
            double xStep = 1.0 / 255.0;
            var lut = new byte[256 * 3];
            for (int i = 0; i < 256; i++)
            {
                // linspace semantics: sample = i * step, endpoint exactly 1.
                double x = i == 255 ? 1.0 : i * xStep;
                int j = k - 2;
                while (j > 0 && x < j * positionStep)
                    j--;
                double pj = j * positionStep;
                double pj1 = j + 1 == k - 1 ? 1.0 : (j + 1) * positionStep;
                for (int c = 0; c < 3; c++)
                {
                    double value;
                    if (x == pj)
                        value = anchors[j][c];
                    else if (x == pj1)
                        value = anchors[j + 1][c];
                    else
                        value = (x - pj) * (anchors[j + 1][c] - anchors[j][c]) / (pj1 - pj)
                            + anchors[j][c];
                    lut[i * 3 + c] = (byte)Math.Round(value); // half-even, matching np.round
                }
            }
            return lut;
        }

        /// <summary>
        /// Colormap a float frame in [0, 1]: index = round_half_even(clip(v) * 255),
        /// RGB written to <paramref name="rgbOut"/> (frame length * 3 bytes).
        /// </summary>
        public static void ApplyFloat(ReadOnlySpan<double> frame, byte[] lut, byte[] rgbOut)
        {
            RequireLut(lut);
            if (rgbOut.Length != frame.Length * 3)
                throw new ArgumentException($"expected {frame.Length * 3} output bytes, got {rgbOut.Length}");
            for (int i = 0; i < frame.Length; i++)
            {
                double clipped = Math.Clamp(frame[i], 0.0, 1.0);
                int index = (int)Math.Round(clipped * 255.0); // half-even, matching np.round
                rgbOut[i * 3] = lut[index * 3];
                rgbOut[i * 3 + 1] = lut[index * 3 + 1];
                rgbOut[i * 3 + 2] = lut[index * 3 + 2];
            }
        }

        /// <summary>Colormap a float frame, allocating the RGB result.</summary>
        public static byte[] ApplyFloat(ReadOnlySpan<double> frame, byte[] lut)
        {
            var rgb = new byte[frame.Length * 3];
            ApplyFloat(frame, lut, rgb);
            return rgb;
        }

        /// <summary>Colormap a byte-indexed frame: direct LUT lookup per cell.</summary>
        public static void ApplyIndexed(ReadOnlySpan<byte> frame, byte[] lut, byte[] rgbOut)
        {
            RequireLut(lut);
            if (rgbOut.Length != frame.Length * 3)
                throw new ArgumentException($"expected {frame.Length * 3} output bytes, got {rgbOut.Length}");
            for (int i = 0; i < frame.Length; i++)
            {
                int index = frame[i];
                rgbOut[i * 3] = lut[index * 3];
                rgbOut[i * 3 + 1] = lut[index * 3 + 1];
                rgbOut[i * 3 + 2] = lut[index * 3 + 2];
            }
        }

        /// <summary>Colormap a byte-indexed frame, allocating the RGB result.</summary>
        public static byte[] ApplyIndexed(ReadOnlySpan<byte> frame, byte[] lut)
        {
            var rgb = new byte[frame.Length * 3];
            ApplyIndexed(frame, lut, rgb);
            return rgb;
        }

        /// <summary>
        /// Colormap a float frame straight to RGBA32 (alpha 255) — the zero-copy layout
        /// for Unity Texture2D.SetPixelData. Same indexing contract as ApplyFloat.
        /// </summary>
        public static void ApplyFloatRgba(ReadOnlySpan<double> frame, byte[] lut, byte[] rgbaOut)
        {
            RequireLut(lut);
            if (rgbaOut.Length != frame.Length * 4)
                throw new ArgumentException($"expected {frame.Length * 4} output bytes, got {rgbaOut.Length}");
            for (int i = 0; i < frame.Length; i++)
            {
                double clipped = Math.Clamp(frame[i], 0.0, 1.0);
                int index = (int)Math.Round(clipped * 255.0);
                rgbaOut[i * 4] = lut[index * 3];
                rgbaOut[i * 4 + 1] = lut[index * 3 + 1];
                rgbaOut[i * 4 + 2] = lut[index * 3 + 2];
                rgbaOut[i * 4 + 3] = 255;
            }
        }

        /// <summary>Colormap a byte-indexed frame straight to RGBA32 (alpha 255).</summary>
        public static void ApplyIndexedRgba(ReadOnlySpan<byte> frame, byte[] lut, byte[] rgbaOut)
        {
            RequireLut(lut);
            if (rgbaOut.Length != frame.Length * 4)
                throw new ArgumentException($"expected {frame.Length * 4} output bytes, got {rgbaOut.Length}");
            for (int i = 0; i < frame.Length; i++)
            {
                int index = frame[i];
                rgbaOut[i * 4] = lut[index * 3];
                rgbaOut[i * 4 + 1] = lut[index * 3 + 1];
                rgbaOut[i * 4 + 2] = lut[index * 3 + 2];
                rgbaOut[i * 4 + 3] = 255;
            }
        }

        /// <summary>Expand an RGB frame (e.g. MergeLife's) to RGBA32 with alpha 255.</summary>
        public static void RgbToRgba(ReadOnlySpan<byte> rgb, byte[] rgbaOut)
        {
            if (rgb.Length % 3 != 0)
                throw new ArgumentException($"RGB length must be a multiple of 3, got {rgb.Length}");
            int pixels = rgb.Length / 3;
            if (rgbaOut.Length != pixels * 4)
                throw new ArgumentException($"expected {pixels * 4} output bytes, got {rgbaOut.Length}");
            for (int i = 0; i < pixels; i++)
            {
                rgbaOut[i * 4] = rgb[i * 3];
                rgbaOut[i * 4 + 1] = rgb[i * 3 + 1];
                rgbaOut[i * 4 + 2] = rgb[i * 3 + 2];
                rgbaOut[i * 4 + 3] = 255;
            }
        }

        /// <summary>
        /// Color an unwrapped phase <paramref name="t"/> (cycles; NaN where a pixel did not
        /// escape) through a LUT that repeats (spec/render.md "Phase lookup"): linear
        /// interpolation between entries, an antialias blend toward the LUT's mean where t
        /// moves more than about a third of a cycle per pixel, and a +-1-code triangular
        /// dither per channel (<see cref="Dither"/>; amplitude 0 turns it off). Pixels whose
        /// phase is not finite take the interior color exactly. RGB into
        /// <paramref name="rgbOut"/> (3 bytes per pixel); <paramref name="width"/> fixes the
        /// pixels' columns and rows, which the antialias and the dither read.
        /// </summary>
        public static void ApplyPhase(
            ReadOnlySpan<double> t, int width, byte[] lut, byte[] rgbOut, PhaseWrap wrap = PhaseWrap.Cyclic,
            bool antialias = true, double dither = 1.0, uint frameIndex = 0,
            byte interiorR = 0, byte interiorG = 0, byte interiorB = 0)
            => Phase(t, width, lut, rgbOut, 3, wrap, antialias, dither, frameIndex, interiorR, interiorG, interiorB);

        /// <summary><see cref="ApplyPhase"/> straight to RGBA32 (alpha 255).</summary>
        public static void ApplyPhaseRgba(
            ReadOnlySpan<double> t, int width, byte[] lut, byte[] rgbaOut, PhaseWrap wrap = PhaseWrap.Cyclic,
            bool antialias = true, double dither = 1.0, uint frameIndex = 0,
            byte interiorR = 0, byte interiorG = 0, byte interiorB = 0)
            => Phase(t, width, lut, rgbaOut, 4, wrap, antialias, dither, frameIndex, interiorR, interiorG, interiorB);

        private const double TwoToMinus32 = 1.0 / 4294967296.0;

        private static void Phase(
            ReadOnlySpan<double> t, int width, byte[] lut, byte[] output, int stride, PhaseWrap wrap,
            bool antialias, double dither, uint frameIndex, byte interiorR, byte interiorG, byte interiorB)
        {
            RequireLut(lut);
            if (width < 1 || t.Length % width != 0)
                throw new ArgumentException("t must be one (height, width) frame");
            if (output.Length != t.Length * stride)
                throw new ArgumentException($"expected {t.Length * stride} output bytes, got {output.Length}");
            if (!(dither >= 0.0) || double.IsInfinity(dither))
                throw new ArgumentException("dither must be finite and non-negative", nameof(dither));
            if (wrap != PhaseWrap.Cyclic && wrap != PhaseWrap.Mirror)
                throw new ArgumentException($"unknown wrap {wrap}", nameof(wrap));
            int period = wrap == PhaseWrap.Cyclic ? 256 : 510;
            int height = t.Length / width;
            // The LUT's mean over one cycle's positions: an integer sum, one division.
            Span<double> mean = stackalloc double[3];
            for (int c = 0; c < 3; c++)
            {
                long sum = 0;
                for (int k = 0; k < period; k++)
                    sum += lut[Entry(k, period) * 3 + c];
                mean[c] = sum / (double)period;
            }
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    int i = y * width + x;
                    int o = i * stride;
                    if (stride == 4)
                        output[o + 3] = 255;
                    double ti = t[i];
                    double position = ti * period;
                    if (!double.IsFinite(ti) || !double.IsFinite(position))
                    {
                        output[o] = interiorR;
                        output[o + 1] = interiorG;
                        output[o + 2] = interiorB;
                        continue;
                    }
                    double floor = Math.Floor(position);
                    double f = position - floor;
                    double k0 = floor - period * Math.Floor(floor / period);
                    if (k0 < 0.0)
                        k0 += period;
                    if (k0 >= period)
                        k0 -= period;
                    int i0 = (int)k0;
                    int i1 = i0 + 1 == period ? 0 : i0 + 1;
                    int e0 = Entry(i0, period) * 3, e1 = Entry(i1, period) * 3;
                    double alias = 0.0;
                    if (antialias)
                    {
                        double need = 0.0;
                        if (x > 0)
                            need = Need(need, ti, t[i - 1]);
                        if (x < width - 1)
                            need = Need(need, ti, t[i + 1]);
                        if (y > 0)
                            need = Need(need, ti, t[i - width]);
                        if (y < height - 1)
                            need = Need(need, ti, t[i + width]);
                        alias = FractalColor.Smoothstep(0.35, 1.0, need);
                    }
                    for (int c = 0; c < 3; c++)
                    {
                        double a = lut[e0 + c], b = lut[e1 + c];
                        double v = a + (b - a) * f;
                        if (antialias)
                            v = v + (mean[c] - v) * alias;
                        if (dither != 0.0)
                            v = v + dither * (Dither.Tpdf(x, y, frameIndex, c) * TwoToMinus32);
                        v = Math.Round(v);                         // half-even
                        output[o + c] = (byte)(v < 0.0 ? 0.0 : (v > 255.0 ? 255.0 : v));
                    }
                }
            }
        }

        /// <summary>The LUT entry a cycle position reads: itself, or mirrored past 255.</summary>
        private static int Entry(int k, int period) => period == 256 || k <= 255 ? k : 510 - k;

        /// <summary>The larger of <paramref name="need"/> and |t - neighbor| when the neighbor is finite.</summary>
        private static double Need(double need, double t, double neighbor)
            => double.IsFinite(neighbor) ? Math.Max(need, Math.Abs(t - neighbor)) : need;

        private static byte[] FromHex(string hex)
        {
            var bytes = new byte[hex.Length / 2];
            for (int i = 0; i < bytes.Length; i++)
                bytes[i] = (byte)((Nibble(hex[2 * i]) << 4) | Nibble(hex[2 * i + 1]));
            return bytes;
        }

        private static int Nibble(char c) => c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10;

        private static void RequireLut(byte[] lut)
        {
            if (lut.Length != 256 * 3)
                throw new ArgumentException($"LUT must be 256*3 bytes, got {lut.Length}");
        }
    }
}
