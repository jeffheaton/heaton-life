using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Fractal conformance runner: rebuilds each field and compares int32 outputs
    /// exactly, mirroring the Python test_fractal_vectors.py. Fractal vectors are
    /// one-shot renders (no time axis): params + viewport + declared outputs.
    /// Deep-zoom cases ship their pinned reference orbit; the C# side consumes the
    /// stored orbit (orbit *generation* needs bignum and stays on the Python side).
    /// </summary>
    public class FractalConformanceTests
    {
        private static readonly string[] Families = { "mandelbrot", "julia", "burning-ship", "newton" };

        public static IEnumerable<object[]> Cases()
        {
            foreach (string family in Families)
                foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), family)))
                    yield return new object[] { family, Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string family, string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), family, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            var p = root.GetProperty("params");
            var vp = root.GetProperty("viewport");
            var viewport = new Viewport(
                vp.GetProperty("center_re").GetString()!,
                vp.GetProperty("center_im").GetString()!,
                vp.GetProperty("zoom_log10").GetDouble());
            int width = root.GetProperty("size")[0].GetInt32();
            int height = root.GetProperty("size")[1].GetInt32();

            double[]? orbitRe = null, orbitIm = null;
            if (root.TryGetProperty("reference_orbit", out var orbitMeta))
            {
                (orbitRe, orbitIm) = ReadC128(
                    Path.Combine(caseDir, orbitMeta.GetProperty("file").GetString()!));
                Assert.Equal(orbitMeta.GetProperty("length").GetInt32(), orbitRe.Length);
            }

            // Serial and parallel must both match the vectors byte-for-byte
            // (spec/fractals.md "Parallel rendering"): 5 workers deliberately does
            // not divide the vector heights evenly.
            foreach (int workers in new[] { 1, 5 })
            {
                var produced = ComputeOutputs(
                    family, p, viewport, width, height, orbitRe, orbitIm, workers);
                foreach (var output in root.GetProperty("outputs").EnumerateArray())
                {
                    string kind = output.GetProperty("kind").GetString()!;
                    int[] expected = ReadI32(
                        Path.Combine(caseDir, output.GetProperty("file").GetString()!));
                    long shapeLen = 1;
                    foreach (var dim in output.GetProperty("shape").EnumerateArray())
                        shapeLen *= dim.GetInt64();
                    Assert.Equal(shapeLen, expected.Length);
                    Assert.True(
                        produced[kind].AsSpan().SequenceEqual(expected),
                        $"{family}/{caseName}: {kind} mismatch (workers={workers})");
                }
            }
        }

        private static Dictionary<string, int[]> ComputeOutputs(
            string family,
            JsonElement p,
            Viewport viewport,
            int width,
            int height,
            double[]? orbitRe,
            double[]? orbitIm,
            int workers)
        {
            switch (family)
            {
                case "mandelbrot":
                {
                    var field = new Mandelbrot(
                        p.GetProperty("max_iter").GetInt32(),
                        p.GetProperty("escape_radius").GetDouble(),
                        workers);
                    int[] iterations = orbitRe != null
                        ? field.Iterations(width, height, viewport, orbitRe, orbitIm!)
                        : field.Iterations(width, height, viewport);
                    return new Dictionary<string, int[]> { ["iterations"] = iterations };
                }
                case "julia":
                {
                    var field = new Julia(
                        p.GetProperty("c_re").GetDouble(),
                        p.GetProperty("c_im").GetDouble(),
                        p.GetProperty("max_iter").GetInt32(),
                        p.GetProperty("escape_radius").GetDouble(),
                        workers);
                    int[] iterations = orbitRe != null
                        ? field.Iterations(width, height, viewport, orbitRe, orbitIm!)
                        : field.Iterations(width, height, viewport);
                    return new Dictionary<string, int[]> { ["iterations"] = iterations };
                }
                case "burning-ship":
                {
                    var field = new BurningShip(
                        p.GetProperty("max_iter").GetInt32(),
                        p.GetProperty("escape_radius").GetDouble(),
                        workers);
                    int[] iterations = orbitRe != null
                        ? field.Iterations(width, height, viewport, orbitRe, orbitIm!)
                        : field.Iterations(width, height, viewport);
                    return new Dictionary<string, int[]> { ["iterations"] = iterations };
                }
                case "newton":
                {
                    var field = new Newton(
                        p.GetProperty("degree").GetInt32(),
                        p.GetProperty("max_iter").GetInt32(),
                        workers);
                    var (roots, iterations) = field.Basins(width, height, viewport);
                    return new Dictionary<string, int[]>
                    {
                        ["roots"] = roots,
                        ["iterations"] = iterations,
                    };
                }
                default:
                    throw new InvalidDataException($"no fractal builder for family '{family}'");
            }
        }

        /// <summary>Raw little-endian int32, the fractal output encoding.</summary>
        private static int[] ReadI32(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            var values = new int[bytes.Length / 4];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
        }

        /// <summary>Raw little-endian complex128 (interleaved re, im) -> parallel arrays.</summary>
        private static (double[] Re, double[] Im) ReadC128(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            var interleaved = new double[bytes.Length / 8];
            Buffer.BlockCopy(bytes, 0, interleaved, 0, bytes.Length);
            var re = new double[interleaved.Length / 2];
            var im = new double[interleaved.Length / 2];
            for (int i = 0; i < re.Length; i++)
            {
                re[i] = interleaved[2 * i];
                im[i] = interleaved[2 * i + 1];
            }
            return (re, im);
        }
    }
}
