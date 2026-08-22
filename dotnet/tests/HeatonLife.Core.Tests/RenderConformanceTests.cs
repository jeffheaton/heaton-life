using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Render conformance: rebuild every colormap LUT and replay frame indexing
    /// against vectors/render/ — the same files the Python suite replays.
    /// Bit-exact tier: RGB bytes must match exactly (spec/render.md).
    /// </summary>
    public class RenderConformanceTests
    {
        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "render")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), "render", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            switch (root.GetProperty("kind").GetString())
            {
                case "lut":
                    RunLut(caseName, caseDir, root);
                    break;
                case "apply":
                    RunApply(caseName, caseDir, root);
                    break;
                case "frame":
                    RunFrame(caseName, caseDir, root);
                    break;
                case "fractal-render":
                    RunFractalRender(caseName, caseDir, root);
                    break;
                default:
                    throw new InvalidDataException($"unknown render kind in {caseName}");
            }
        }

        private static void RunLut(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string outputFile = root.GetProperty("output").GetProperty("file").GetString()!;
            var (width, height, channels, expected) = Png.Read(Path.Combine(caseDir, outputFile));
            Assert.Equal(3, channels);
            Assert.Equal(256, width * height);
            byte[] got = Colormaps.Get(root.GetProperty("cmap").GetString()!);
            Assert.True(got.AsSpan().SequenceEqual(expected), $"render/{caseName}: RGB mismatch");
        }

        private static void RunApply(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string outputFile = root.GetProperty("output").GetProperty("file").GetString()!;
            var (width, height, channels, expected) = Png.Read(Path.Combine(caseDir, outputFile));
            Assert.Equal(3, channels);
            double[] frame = ReadF64(
                Path.Combine(caseDir, root.GetProperty("input").GetProperty("file").GetString()!));
            Assert.Equal(width * height, frame.Length);
            byte[] got = Colormaps.ApplyFloat(frame, Colormaps.Get(root.GetProperty("cmap").GetString()!));
            Assert.True(got.AsSpan().SequenceEqual(expected), $"render/{caseName}: RGB mismatch");
        }

        private static void RunFrame(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string simFamily = root.GetProperty("sim_family").GetString()!;
            var p = root.GetProperty("params");
            string inputFile = root.GetProperty("input").GetProperty("file").GetString()!;
            string outputFile = root.GetProperty("output").GetProperty("file").GetString()!;
            int width = p.GetProperty("width").GetInt32();
            int height = p.GetProperty("height").GetInt32();

            switch (simFamily)
            {
                case "lifelike":
                    {
                        var sim = new LifeLike(
                            p.GetProperty("rule").GetString()!, width, height,
                            p.GetProperty("boundary").GetString() == "dead" ? Boundary.Dead : Boundary.Torus);
                        sim.SetState(ReadGrayBinarized(Path.Combine(caseDir, inputFile)));
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "cyclic":
                    {
                        var sim = new Cyclic(
                            p.GetProperty("states").GetInt32(), width, height,
                            p.GetProperty("threshold").GetInt32(), p.GetProperty("reach").GetInt32(),
                            p.GetProperty("neighborhood").GetString() == "vonneumann"
                                ? Neighborhood.VonNeumann
                                : Neighborhood.Moore);
                        var (_, _, _, pixels) = Png.Read(Path.Combine(caseDir, inputFile));
                        sim.SetState(pixels); // cyclic encoding: raw state values
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "wireworld":
                    {
                        var (_, _, _, pixels) = Png.Read(Path.Combine(caseDir, inputFile));
                        var cells = new byte[pixels.Length];
                        for (int i = 0; i < pixels.Length; i++)
                            cells[i] = (byte)(pixels[i] / 85); // wireworld encoding: state * 85
                        var sim = new Wireworld(
                            width, height, cells,
                            p.GetProperty("boundary").GetString() == "torus" ? Boundary.Torus : Boundary.Dead);
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "grayscott":
                    {
                        var sim = new GrayScott(
                            width, height,
                            p.GetProperty("du").GetDouble(), p.GetProperty("dv").GetDouble(),
                            p.GetProperty("feed").GetDouble(), p.GetProperty("kill").GetDouble(),
                            p.GetProperty("dt").GetDouble());
                        sim.SetState(ReadF64(Path.Combine(caseDir, inputFile)));
                        AssertFloatFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "boids":
                    {
                        var sim = new Boids(
                            p.GetProperty("count").GetInt32(), width, height,
                            p.GetProperty("perception").GetDouble(),
                            p.GetProperty("separation_radius").GetDouble(),
                            p.GetProperty("w_separation").GetDouble(),
                            p.GetProperty("w_alignment").GetDouble(),
                            p.GetProperty("w_cohesion").GetDouble(),
                            p.GetProperty("max_speed").GetDouble(),
                            p.GetProperty("min_speed").GetDouble(),
                            p.GetProperty("max_force").GetDouble(),
                            p.GetProperty("boundary").GetString() == "bounce"
                                ? BoidsBoundary.Bounce
                                : BoidsBoundary.Wrap,
                            p.TryGetProperty("dimensions", out var dims) ? dims.GetInt32() : 2,
                            p.TryGetProperty("depth", out var boidsDepth) ? boidsDepth.GetInt32() : 256);
                        sim.SetState(ReadF64(Path.Combine(caseDir, inputFile)));
                        AssertFloatFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                default:
                    throw new InvalidDataException($"no frame builder for '{simFamily}'");
            }
        }

        private static void RunFractalRender(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("epsilon", root.GetProperty("tier").GetString());
            double epsilon = root.GetProperty("epsilon").GetDouble();
            var p = root.GetProperty("params");
            var vp = root.GetProperty("viewport");
            var viewport = new Viewport(
                vp.GetProperty("center_re").GetString()!,
                vp.GetProperty("center_im").GetString()!,
                vp.GetProperty("zoom_log10").GetDouble());
            int width = root.GetProperty("size")[0].GetInt32();
            int height = root.GetProperty("size")[1].GetInt32();
            double[] produced = root.GetProperty("sim_family").GetString() switch
            {
                "mandelbrot" => new Mandelbrot(
                        p.GetProperty("max_iter").GetInt32(),
                        p.GetProperty("escape_radius").GetDouble())
                    .Render(width, height, viewport),
                "newton" => new Newton(
                        p.GetProperty("degree").GetInt32(),
                        p.GetProperty("max_iter").GetInt32())
                    .Render(width, height, viewport),
                var other => throw new InvalidDataException($"no fractal-render builder for '{other}'"),
            };
            double[] expected = ReadF64(
                Path.Combine(caseDir, root.GetProperty("output").GetProperty("file").GetString()!));
            Assert.Equal(expected.Length, produced.Length);
            double maxDiff = 0;
            for (int i = 0; i < expected.Length; i++)
                maxDiff = Math.Max(maxDiff, Math.Abs(produced[i] - expected[i]));
            Assert.True(maxDiff <= epsilon, $"render/{caseName}: max |Δ| = {maxDiff:g3} (ε = {epsilon:g1})");
        }

        private static void AssertByteFrame(string caseName, string caseDir, string outputFile, byte[] frame)
        {
            var (_, _, channels, expected) = Png.Read(Path.Combine(caseDir, outputFile));
            Assert.Equal(1, channels);
            Assert.True(frame.AsSpan().SequenceEqual(expected), $"render/{caseName}: frame mismatch");
        }

        private static void AssertFloatFrame(string caseName, string caseDir, string outputFile, double[] frame)
        {
            double[] expected = ReadF64(Path.Combine(caseDir, outputFile));
            Assert.Equal(expected.Length, frame.Length);
            for (int i = 0; i < expected.Length; i++)
                Assert.True(
                    frame[i].Equals(expected[i]),
                    $"render/{caseName}: frame mismatch at {i}: {frame[i]:R} != {expected[i]:R}");
        }

        private static byte[] ReadGrayBinarized(string path)
        {
            var (_, _, channels, pixels) = Png.Read(path);
            Assert.Equal(1, channels);
            var state = new byte[pixels.Length];
            for (int i = 0; i < pixels.Length; i++)
                state[i] = (byte)(pixels[i] > 0 ? 1 : 0);
            return state;
        }

        private static double[] ReadF64(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            var values = new double[bytes.Length / 8];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
        }

        [Fact]
        public void WireworldAnchorsLandOnStateColors()
        {
            byte[] lut = Colormaps.Get("wireworld");
            // state * 85 -> exact anchor colors for the four Wireworld states
            Assert.Equal(new byte[] { 0, 0, 0 }, new[] { lut[0], lut[1], lut[2] });
            Assert.Equal(new byte[] { 70, 130, 255 }, new[] { lut[85 * 3], lut[85 * 3 + 1], lut[85 * 3 + 2] });
            Assert.Equal(new byte[] { 255, 80, 60 }, new[] { lut[170 * 3], lut[170 * 3 + 1], lut[170 * 3 + 2] });
            Assert.Equal(new byte[] { 255, 210, 70 }, new[] { lut[255 * 3], lut[255 * 3 + 1], lut[255 * 3 + 2] });
        }

        [Fact]
        public void IndexedApplyIsDirectLookup()
        {
            byte[] lut = Colormaps.Get("fire");
            var frame = new byte[] { 0, 85, 170, 255 };
            byte[] rgb = Colormaps.ApplyIndexed(frame, lut);
            for (int i = 0; i < frame.Length; i++)
                for (int c = 0; c < 3; c++)
                    Assert.Equal(lut[frame[i] * 3 + c], rgb[i * 3 + c]);
        }
    }
}
