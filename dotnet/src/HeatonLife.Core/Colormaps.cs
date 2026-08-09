using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>
    /// Built-in colormaps (256x3 byte LUTs) — spec/render.md. LUTs are rebuilt from
    /// the spec'd anchors with piecewise-linear interpolation and half-even rounding,
    /// byte-identical with the Python reference (gated by vectors/render/). The flat
    /// RGB output drops straight into a Unity Color32/Texture2D upload.
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

        /// <summary>Names of the built-in colormaps, sorted.</summary>
        public static IReadOnlyList<string> Names
        {
            get
            {
                var names = new List<string>(Anchors.Keys);
                names.Sort(StringComparer.Ordinal);
                return names;
            }
        }

        /// <summary>Build the 256x3 LUT for a named colormap (flat 768 bytes, RGB rows).</summary>
        public static byte[] Get(string name)
        {
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

        private static void RequireLut(byte[] lut)
        {
            if (lut.Length != 256 * 3)
                throw new ArgumentException($"LUT must be 256*3 bytes, got {lut.Length}");
        }
    }
}
