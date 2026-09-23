using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Location vectors (spec/locations.md): the importers and the framing conversion must
    /// reproduce the Python reference — centers, budgets, references, formats and warnings
    /// exactly, the half-height and viewport zooms within the case's relative epsilon (they
    /// go through log10). Core reads no JSON, so the Heaton Fractal preset and journal cases
    /// parse here, as a host would, and hand Core the fields.
    /// </summary>
    public class LocationConformanceTests
    {
        private static readonly HashSet<string> Keys = new HashSet<string>
        {
            "spec_version", "family", "tier", "epsilon", "format", "input",
        };

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "locations")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string dir = Path.Combine(TestPaths.VectorRoot(), "locations", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("locations", root.GetProperty("family").GetString());
            Assert.Equal("epsilon", root.GetProperty("tier").GetString());
            Assert.Equal("0.5.0", root.GetProperty("spec_version").GetString());
            bool error = root.TryGetProperty("error", out var errorFlag) && errorFlag.GetBoolean();
            var allowed = new HashSet<string>(Keys);
            allowed.UnionWith(error ? new[] { "error" } : new[] { "expected", "viewports" });
            foreach (var property in root.EnumerateObject())
                Assert.True(allowed.Contains(property.Name), $"{caseName}: runner does not understand '{property.Name}'");

            string format = root.GetProperty("format").GetString()!;
            string text = new UTF8Encoding(false).GetString(File.ReadAllBytes(Path.Combine(dir, root.GetProperty("input").GetString()!)));
            if (error)
            {
                Assert.ThrowsAny<ArgumentException>(() => Parse(format, text));
                return;
            }
            Location loc = Parse(format, text);
            var want = root.GetProperty("expected");
            Assert.Equal(want.GetProperty("center_re").GetString(), loc.CenterRe);
            Assert.Equal(want.GetProperty("center_im").GetString(), loc.CenterIm);
            Assert.Equal(want.GetProperty("format").GetString(), loc.Format);
            var maxIter = want.GetProperty("max_iter");
            Assert.Equal(maxIter.ValueKind == JsonValueKind.Null ? (long?)null : maxIter.GetInt64(), loc.MaxIter);
            var reference = want.GetProperty("reference");
            if (reference.ValueKind == JsonValueKind.Null)
            {
                Assert.Null(loc.ReferenceRe);
                Assert.Null(loc.ReferenceIm);
            }
            else
            {
                Assert.Equal(reference[0].GetString(), loc.ReferenceRe);
                Assert.Equal(reference[1].GetString(), loc.ReferenceIm);
            }
            var warnings = new List<string>();
            foreach (var code in want.GetProperty("warnings").EnumerateArray())
                warnings.Add(code.GetString()!);
            Assert.Equal(warnings, loc.Warnings);

            double epsilon = root.GetProperty("epsilon").GetDouble();
            var halfHeight = want.GetProperty("half_height_log10");
            if (halfHeight.ValueKind == JsonValueKind.Null)
            {
                Assert.Null(loc.HalfHeightLog10);
                Assert.Equal(0, root.GetProperty("viewports").GetArrayLength());
                Assert.Throws<InvalidOperationException>(() => loc.ToViewport(64, 64));
                return;
            }
            Assert.NotNull(loc.HalfHeightLog10);
            AssertClose(halfHeight.GetDouble(), loc.HalfHeightLog10!.Value, epsilon, $"{caseName} half-height");
            Assert.True(root.GetProperty("viewports").GetArrayLength() > 0);
            foreach (var entry in root.GetProperty("viewports").EnumerateArray())
            {
                var vp = loc.ToViewport(entry.GetProperty("size")[0].GetInt32(), entry.GetProperty("size")[1].GetInt32());
                Assert.Equal(loc.CenterRe, vp.CenterRe);
                Assert.Equal(loc.CenterIm, vp.CenterIm);
                AssertClose(entry.GetProperty("zoom_log10").GetDouble(), vp.ZoomLog10, epsilon, $"{caseName} zoom");
            }
        }

        private static void AssertClose(double want, double got, double epsilon, string what) =>
            Assert.True(Math.Abs(got - want) <= epsilon * Math.Max(1.0, Math.Abs(want)), $"{what}: {got:R} vs {want:R}");

        private static Location Parse(string format, string text) => format switch
        {
            "kfr" => Locations.ParseKfr(text),
            "f3" => Locations.ParseFraktaler3(text),
            "hf-result" => Locations.ParseHeatonFractalResult(text),
            "hf-preset" => Preset(text),
            "hf-journal" => Journal(text),
            _ => throw new InvalidDataException($"no importer for '{format}'"),
        };

        /// <summary>A host's reading of a Heaton Fractal preset: the envelope's settings, or a bare settings object.</summary>
        private static Location Preset(string text)
        {
            using var doc = JsonDocument.Parse(text);
            var settings = doc.RootElement.TryGetProperty("settings", out var inner) && inner.ValueKind == JsonValueKind.Object
                ? inner
                : doc.RootElement;
            var location = settings.GetProperty("location");
            // baseHalfHeight is required (Core refuses null); a missing depth is no scale.
            string? baseHalfHeight = location.TryGetProperty("baseHalfHeight", out var h0) ? h0.GetString() : null;
            double? depth = settings.TryGetProperty("zoom", out var zoom) && zoom.ValueKind == JsonValueKind.Object
                && zoom.TryGetProperty("targetDepthLog10", out var d) ? d.GetDouble() : (double?)null;
            long? budget = settings.TryGetProperty("quality", out var quality) && quality.ValueKind == JsonValueKind.Object
                && quality.TryGetProperty("maxIterationsOverride", out var m) && m.ValueKind != JsonValueKind.Null
                ? m.GetInt64() : (long?)null;
            return Locations.HeatonFractalPreset(
                location.GetProperty("centerReal").GetString()!, location.GetProperty("centerImag").GetString()!,
                baseHalfHeight!, depth, budget);
        }

        /// <summary>A host's reading of a hunt journal: one JSON seed per line, torn lines skipped.</summary>
        private static Location Journal(string text)
        {
            var seeds = new List<(string, string, double)>();
            foreach (string line in text.Replace("\r\n", "\n").Split('\n'))
            {
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    var seed = doc.RootElement;
                    seeds.Add((seed.GetProperty("real").GetString()!, seed.GetProperty("imaginary").GetString()!,
                        seed.GetProperty("depthLog10").GetDouble()));
                }
                catch (Exception ex) when (ex is JsonException || ex is KeyNotFoundException || ex is InvalidOperationException)
                {
                    continue;
                }
            }
            return Locations.HeatonFractalJournal(seeds);
        }
    }
}
