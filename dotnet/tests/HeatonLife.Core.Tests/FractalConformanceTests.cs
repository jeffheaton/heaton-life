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
    /// Deep-zoom cases ship their pinned reference orbit (and, for Julia, the critical
    /// orbit rebased pixels restart on); this runner replays the stored orbits so the
    /// counts check needs no bignum. Regenerating those orbits in C# is
    /// ReferenceOrbitTests' job.
    /// </summary>
    public class FractalConformanceTests
    {
        private static readonly string[] Families = { "mandelbrot", "julia", "burning-ship", "newton" };

        // Everything this runner understands. A key outside these sets fails the case
        // rather than being skipped: a runner that ignored, say, "critical_orbit" would
        // replay a deep Julia case the old way and fail confusingly or pass wrongly.
        private static readonly HashSet<string> SpecVersions = new HashSet<string> { "0.2.0", "0.3.0", "0.4.0" };
        private static readonly HashSet<string> TopKeys = new HashSet<string>
        {
            "spec_version", "family", "tier", "params", "viewport", "size", "outputs",
            "reference_orbit", "critical_orbit", "source",
        };
        private static readonly Dictionary<string, HashSet<string>> ParamKeys = new Dictionary<string, HashSet<string>>
        {
            ["mandelbrot"] = new HashSet<string> { "max_iter", "escape_radius" },
            ["julia"] = new HashSet<string> { "c_re", "c_im", "max_iter", "escape_radius" },
            ["burning-ship"] = new HashSet<string> { "max_iter", "escape_radius" },
            ["newton"] = new HashSet<string> { "degree", "max_iter" },
        };
        private static readonly HashSet<string> OutputKinds = new HashSet<string> { "iterations", "roots" };

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
            foreach (var property in root.EnumerateObject())
                Assert.True(TopKeys.Contains(property.Name),
                    $"{family}/{caseName}: runner does not understand '{property.Name}'; teach it first");
            Assert.Contains(root.GetProperty("spec_version").GetString()!, SpecVersions);
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            var p = root.GetProperty("params");
            var paramNames = new HashSet<string>();
            foreach (var property in p.EnumerateObject())
                paramNames.Add(property.Name);
            Assert.True(ParamKeys[family].SetEquals(paramNames), $"{family}/{caseName}: unexpected params");
            Assert.True(family == "julia" || !root.TryGetProperty("critical_orbit", out _));
            var vp = root.GetProperty("viewport");
            bool offCenter = vp.TryGetProperty("reference_re", out _) || vp.TryGetProperty("reference_im", out _);
            if (offCenter)
            {
                // An off-center reference (spec/deep-zoom.md) arrived in 0.4.0; an older
                // runner would iterate the center instead and replay the case wrongly.
                Assert.Equal("0.4.0", root.GetProperty("spec_version").GetString());
                AssertKeys(vp, $"{family}/{caseName} viewport", "center_re", "center_im", "zoom_log10", "reference_re", "reference_im");
            }
            else
            {
                AssertKeys(vp, $"{family}/{caseName} viewport", "center_re", "center_im", "zoom_log10");
            }
            foreach (string key in new[] { "reference_orbit", "critical_orbit" })
            {
                if (!root.TryGetProperty(key, out var orbit))
                    continue;
                AssertKeys(orbit, $"{family}/{caseName} {key}", "file", "length");
                Assert.EndsWith(".c128", orbit.GetProperty("file").GetString()!);
            }
            foreach (var output in root.GetProperty("outputs").EnumerateArray())
            {
                AssertKeys(output, $"{family}/{caseName} output", "kind", "file", "shape");
                Assert.True(
                    OutputKinds.Contains(output.GetProperty("kind").GetString()!)
                    && output.GetProperty("file").GetString()!.EndsWith(".i32", StringComparison.Ordinal),
                    $"{family}/{caseName}: runner does not understand output {output}");
                // size is [width, height]; shape is [rows, cols].
                Assert.Equal(root.GetProperty("size")[1].GetInt32(), output.GetProperty("shape")[0].GetInt32());
                Assert.Equal(root.GetProperty("size")[0].GetInt32(), output.GetProperty("shape")[1].GetInt32());
            }
            var viewport = new Viewport(
                vp.GetProperty("center_re").GetString()!,
                vp.GetProperty("center_im").GetString()!,
                vp.GetProperty("zoom_log10").GetDouble(),
                offCenter ? vp.GetProperty("reference_re").GetString() : null,
                offCenter ? vp.GetProperty("reference_im").GetString() : null);
            int width = root.GetProperty("size")[0].GetInt32();
            int height = root.GetProperty("size")[1].GetInt32();

            double[]? orbitRe = null, orbitIm = null;
            if (root.TryGetProperty("reference_orbit", out var orbitMeta))
            {
                (orbitRe, orbitIm) = ReadC128(
                    Path.Combine(caseDir, orbitMeta.GetProperty("file").GetString()!));
                Assert.Equal(orbitMeta.GetProperty("length").GetInt32(), orbitRe.Length);
            }
            double[]? criticalRe = null, criticalIm = null;
            if (root.TryGetProperty("critical_orbit", out var criticalMeta))
            {
                (criticalRe, criticalIm) = ReadC128(
                    Path.Combine(caseDir, criticalMeta.GetProperty("file").GetString()!));
                Assert.Equal(criticalMeta.GetProperty("length").GetInt32(), criticalRe.Length);
            }

            // Serial and parallel must both match the vectors byte-for-byte
            // (spec/fractals.md "Parallel rendering"): 5 workers deliberately does
            // not divide the vector heights evenly.
            foreach (int workers in new[] { 1, 5 })
            {
                var produced = ComputeOutputs(
                    family, p, viewport, width, height, orbitRe, orbitIm, criticalRe, criticalIm, workers);
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
            double[]? criticalRe,
            double[]? criticalIm,
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
                            ? (criticalRe != null
                                ? field.Iterations(width, height, viewport, orbitRe, orbitIm!, criticalRe, criticalIm!)
                                : field.Iterations(width, height, viewport, orbitRe, orbitIm!))
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

        /// <summary>The object must carry exactly these keys (strict: unknown keys fail the case).</summary>
        private static void AssertKeys(JsonElement element, string where, params string[] expected)
        {
            var names = new HashSet<string>();
            foreach (var property in element.EnumerateObject())
                names.Add(property.Name);
            Assert.True(names.SetEquals(expected), $"{where}: unexpected keys {string.Join(", ", names)}");
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
