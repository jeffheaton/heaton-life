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
        private static readonly HashSet<string> SpecVersions = new HashSet<string> { "0.2.0", "0.3.0", "0.4.0", "0.6.0", "0.7.0", "0.8.0" };
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
        private static readonly HashSet<string> OutputKinds = new HashSet<string> { "iterations", "roots", "status", "bla_applications" };

        /// <summary>spec_version as integers, compared component by component ("0.10.0" &gt; "0.4.0").</summary>
        private static bool AtLeast(string version, int major, int minor, int patch)
        {
            string[] parts = version.Split('.');
            var got = (int.Parse(parts[0]), int.Parse(parts[1]), int.Parse(parts[2]));
            return got.CompareTo((major, minor, patch)) >= 0;
        }

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
            bool bla = false;
            if (paramNames.Remove("bla"))
            {
                // spec/deep-zoom.md "BLA" (0.8.0): an algorithm parameter, Mandelbrot only.
                Assert.True(family == "mandelbrot", $"{family}/{caseName}: {family} has no BLA");
                Assert.True(AtLeast(root.GetProperty("spec_version").GetString()!, 0, 8, 0), $"{family}/{caseName}: bla before 0.8.0");
                bla = p.GetProperty("bla").GetBoolean();
            }
            Assert.True(ParamKeys[family].SetEquals(paramNames), $"{family}/{caseName}: unexpected params");
            Assert.True(family == "julia" || !root.TryGetProperty("critical_orbit", out _));
            var vp = root.GetProperty("viewport");
            bool offCenter = vp.TryGetProperty("reference_re", out _) || vp.TryGetProperty("reference_im", out _);
            if (offCenter)
            {
                // An off-center reference (spec/deep-zoom.md) arrived in 0.4.0; an older
                // runner would iterate the center instead and replay the case wrongly.
                Assert.True(AtLeast(root.GetProperty("spec_version").GetString()!, 0, 4, 0), $"{family}/{caseName}: reference before 0.4.0");
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
            bool withStatus = false, withDistance = false, withBla = false;
            string version = root.GetProperty("spec_version").GetString()!;
            foreach (var output in root.GetProperty("outputs").EnumerateArray())
            {
                if (output.GetProperty("kind").GetString() == "bla_table")
                {
                    // spec/deep-zoom.md "BLA": the table itself, value for value.
                    AssertKeys(output, $"{family}/{caseName} output", "kind", "file", "shape", "entries");
                    Assert.EndsWith(".f64", output.GetProperty("file").GetString()!);
                    Assert.True(p.TryGetProperty("bla", out _), $"{family}/{caseName}: a table without bla");
                    continue;
                }
                if (output.GetProperty("kind").GetString() == "distance")
                {
                    // spec/fractals.md "Distance estimate" (0.7.0): float64, relative epsilon.
                    withDistance = true;
                    AssertKeys(output, $"{family}/{caseName} output", "kind", "file", "shape", "relative_epsilon");
                    Assert.EndsWith(".f64", output.GetProperty("file").GetString()!);
                    Assert.True(AtLeast(version, 0, 7, 0), $"{family}/{caseName}: distance before 0.7.0");
                    Assert.True(family == "mandelbrot" || family == "julia", $"{family}/{caseName}: no distance estimate");
                }
                else
                {
                    AssertKeys(output, $"{family}/{caseName} output", "kind", "file", "shape");
                    withStatus |= output.GetProperty("kind").GetString() == "status";
                    withBla |= output.GetProperty("kind").GetString() == "bla_applications";
                    Assert.True(
                        OutputKinds.Contains(output.GetProperty("kind").GetString()!)
                        && output.GetProperty("file").GetString()!.EndsWith(".i32", StringComparison.Ordinal),
                        $"{family}/{caseName}: runner does not understand output {output}");
                }
                // size is [width, height]; shape is [rows, cols].
                Assert.Equal(root.GetProperty("size")[1].GetInt32(), output.GetProperty("shape")[0].GetInt32());
                Assert.Equal(root.GetProperty("size")[0].GetInt32(), output.GetProperty("shape")[1].GetInt32());
            }
            // spec/fractals.md "Status" (0.6.0): how each count was decided.
            Assert.True(!withStatus || AtLeast(version, 0, 6, 0), $"{family}/{caseName}: status before 0.6.0");
            // A BLA case records its applications, and only a BLA case has them.
            Assert.True(bla == withBla, $"{family}/{caseName}: bla and bla_applications go together");
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
                double[]? distance = null;
                var produced = withDistance || withBla
                    ? ComputeFields(
                        family, p, viewport, width, height, orbitRe, orbitIm, criticalRe, criticalIm, workers, withStatus,
                        withDistance, bla, out distance)
                    : ComputeOutputs(
                        family, p, viewport, width, height, orbitRe, orbitIm, criticalRe, criticalIm, workers, withStatus);
                foreach (var output in root.GetProperty("outputs").EnumerateArray())
                {
                    string kind = output.GetProperty("kind").GetString()!;
                    if (kind == "bla_table")
                    {
                        AssertTable(caseDir, output, viewport, width, height, orbitRe!, orbitIm!,
                            p.GetProperty("max_iter").GetInt32(), p.GetProperty("escape_radius").GetDouble());
                        continue;
                    }
                    if (kind == "distance")
                    {
                        double[] want = ReadF64(Path.Combine(caseDir, output.GetProperty("file").GetString()!));
                        AssertRelative(distance!, want, output.GetProperty("relative_epsilon").GetDouble(),
                            $"{family}/{caseName}: distance (workers={workers})");
                        continue;
                    }
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
            int workers,
            bool withStatus)
        {
            if (withStatus)
            {
                // Status cases are T0 frames: the families compute them, no orbit handed in.
                Assert.Null(orbitRe);
                var counts = new int[width * height];
                var status = new byte[width * height];
                switch (family)
                {
                    case "mandelbrot":
                        new Mandelbrot(p.GetProperty("max_iter").GetInt32(), p.GetProperty("escape_radius").GetDouble(), workers)
                            .CountsAndStatus(width, height, viewport, counts, status);
                        break;
                    case "julia":
                        new Julia(p.GetProperty("c_re").GetDouble(), p.GetProperty("c_im").GetDouble(),
                                p.GetProperty("max_iter").GetInt32(), p.GetProperty("escape_radius").GetDouble(), workers)
                            .CountsAndStatus(width, height, viewport, counts, status);
                        break;
                    case "burning-ship":
                        new BurningShip(p.GetProperty("max_iter").GetInt32(), p.GetProperty("escape_radius").GetDouble(), workers)
                            .CountsAndStatus(width, height, viewport, counts, status);
                        break;
                    default:
                        throw new InvalidDataException($"no status for family '{family}'");
                }
                var statusInts = new int[status.Length];
                for (int i = 0; i < status.Length; i++)
                    statusInts[i] = status[i];
                return new Dictionary<string, int[]> { ["iterations"] = counts, ["status"] = statusInts };
            }
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

        /// <summary>
        /// A distance case: counts, statuses and the distance estimate from one
        /// <c>Fields</c> call — the distance loop's own path, checked against the same
        /// count files — replaying the stored orbits at T1.
        /// </summary>
        private static Dictionary<string, int[]> ComputeFields(
            string family,
            JsonElement p,
            Viewport viewport,
            int width,
            int height,
            double[]? orbitRe,
            double[]? orbitIm,
            double[]? criticalRe,
            double[]? criticalIm,
            int workers,
            bool withStatus,
            bool withDistance,
            bool bla,
            out double[]? distance)
        {
            var counts = new int[width * height];
            byte[]? status = withStatus ? new byte[width * height] : null;
            distance = withDistance ? new double[width * height] : null;
            int[]? applications = bla ? new int[width * height] : null;
            if (family == "mandelbrot")
            {
                var field = new Mandelbrot(p.GetProperty("max_iter").GetInt32(), p.GetProperty("escape_radius").GetDouble(), workers, bla);
                if (orbitRe != null)
                    field.Fields(width, height, viewport, orbitRe, orbitIm!, counts, status, distance, applications);
                else if (applications != null)
                    field.Fields(width, height, viewport, counts, applications, status: status, distance: distance);
                else
                    field.Fields(width, height, viewport, counts, status: status, distance: distance);
            }
            else
            {
                var field = new Julia(p.GetProperty("c_re").GetDouble(), p.GetProperty("c_im").GetDouble(),
                    p.GetProperty("max_iter").GetInt32(), p.GetProperty("escape_radius").GetDouble(), workers);
                if (orbitRe != null)
                    field.Fields(width, height, viewport, orbitRe, orbitIm!, criticalRe!, criticalIm!, counts, status, distance);
                else
                    field.Fields(width, height, viewport, counts, status: status, distance: distance);
            }
            var produced = new Dictionary<string, int[]> { ["iterations"] = counts };
            if (applications != null)
            {
                long total = 0;
                foreach (int a in applications)
                    total += a;
                Assert.True(total > 0, "a BLA case must engage, or it pins nothing");
                produced["bla_applications"] = applications;
            }
            if (status != null)
            {
                var statusInts = new int[status.Length];
                for (int i = 0; i < status.Length; i++)
                    statusInts[i] = status[i];
                produced["status"] = statusInts;
            }
            return produced;
        }

        /// <summary>
        /// The BLA table built from the stored orbit and the frame's dc bound, level by level
        /// (ar, ai, br, bi, r), must equal the stored words value for value (NaN equal to NaN).
        /// </summary>
        private static void AssertTable(
            string caseDir, JsonElement output, Viewport viewport, int width, int height, double[] orbitRe, double[] orbitIm,
            int maxIter, double escapeRadius)
        {
            int samples = (int)Math.Min(orbitRe.Length, (long)maxIter + 1);
            var table = BlaTable.Build(orbitRe, orbitIm, samples, escapeRadius, BlaTable.FrameDcBound(width, height, viewport));
            var entries = output.GetProperty("entries");
            Assert.Equal(entries.GetArrayLength(), table.Levels);
            var words = new List<double>();
            for (int level = 0; level < table.Levels; level++)
            {
                Assert.Equal(entries[level].GetInt32(), table.R[level].Length);
                words.AddRange(table.Ar[level]);
                words.AddRange(table.Ai[level]);
                words.AddRange(table.Br[level]);
                words.AddRange(table.Bi[level]);
                words.AddRange(table.R[level]);
            }
            double[] want = ReadF64(Path.Combine(caseDir, output.GetProperty("file").GetString()!));
            Assert.Equal(want.Length, words.Count);
            for (int i = 0; i < want.Length; i++)
                Assert.True(want[i].Equals(words[i]), $"bla_table word {i}: {words[i]:R}, want {want[i]:R}");
        }

        /// <summary>
        /// spec/fractals.md "Distance estimate": NaN, 0 and ±∞ positions match exactly;
        /// elsewhere |got - want| &lt;= epsilon * |want|.
        /// </summary>
        private static void AssertRelative(double[] got, double[] want, double epsilon, string what)
        {
            Assert.Equal(want.Length, got.Length);
            for (int i = 0; i < want.Length; i++)
            {
                bool special = double.IsNaN(want[i]) || double.IsInfinity(want[i]) || want[i] == 0.0;
                if (special)
                    Assert.True(want[i].Equals(got[i]), $"{what}: pixel {i} is {got[i]:R}, want {want[i]:R}");
                else
                    Assert.True(Math.Abs(got[i] - want[i]) <= epsilon * Math.Abs(want[i]),
                        $"{what}: pixel {i} is {got[i]:R}, want {want[i]:R}");
            }
        }

        /// <summary>Raw little-endian float64.</summary>
        private static double[] ReadF64(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            var values = new double[bytes.Length / 8];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
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
