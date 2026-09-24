using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Discovery vectors (spec/nucleus.md): the box period, Newton's nucleus and a snap must
    /// reproduce the Python reference bit for bit — every field but the size and the
    /// framing's half-height, which match within the case's relative epsilon. Strict: a key
    /// this runner does not know fails the case.
    /// </summary>
    public class NucleusConformanceTests
    {
        private static readonly string[] BaseKeys =
        {
            "spec_version", "family", "tier", "relative_epsilon", "operation", "input", "expected",
        };

        private static readonly string[] CommonInput = { "center_re", "center_im", "zoom_log10", "radius" };

        private static readonly Dictionary<string, string[]> InputKeys = new Dictionary<string, string[]>
        {
            ["box"] = new[] { "max_period" },
            ["snap"] = new[] { "max_period" },
            ["find"] = new[] { "period", "max_steps", "max_evaluations", "max_escalations" },
        };

        private static readonly Dictionary<string, string[]> ExpectedKeys = new Dictionary<string, string[]>
        {
            ["box"] = new[] { "box" },
            ["snap"] = new[] { "box", "nucleus", "location" },
            ["find"] = new[] { "nucleus", "location" },
        };

        private static readonly string[] NucleusKeys =
        {
            "found", "converged", "inside", "stop", "center_re", "center_im", "period", "lower_period",
            "bits", "steps", "evaluations", "depth_bits", "size_log10",
        };

        private static readonly string[] Stops =
        {
            "floor", "no-improvement", "left-view", "stagnated", "max-evaluations", "max-steps", "zero-derivative", "start-escaped",
        };

        private static string Dir => Path.Combine(TestPaths.VectorRoot(), "nucleus");

        [Fact]
        public void TheVectorsCoverEveryOutcome()
        {
            var operations = new HashSet<string>();
            var stops = new HashSet<string>();
            var reasons = new HashSet<string>();
            foreach (string dir in Directory.GetDirectories(Dir))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
                var root = doc.RootElement;
                operations.Add(root.GetProperty("operation").GetString()!);
                var expected = root.GetProperty("expected");
                if (expected.TryGetProperty("nucleus", out var nucleus) && nucleus.ValueKind != JsonValueKind.Null)
                    stops.Add(nucleus.GetProperty("stop").GetString()!);
                if (expected.TryGetProperty("box", out var box))
                    reasons.Add(box.GetProperty("reason").GetString()!);
            }
            Assert.True(operations.SetEquals(InputKeys.Keys), string.Join(", ", operations));
            Assert.True(stops.SetEquals(Stops), string.Join(", ", stops));
            Assert.True(reasons.SetEquals(new[] { "surrounded", "budget", "escaped" }), string.Join(", ", reasons));
        }

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Dir))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Dir, caseName, "params.json")));
            var root = doc.RootElement;
            AssertKeys(root, caseName, BaseKeys);
            Assert.Equal("nucleus", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            Assert.Equal("0.9.0", root.GetProperty("spec_version").GetString());
            string operation = root.GetProperty("operation").GetString()!;
            Assert.True(InputKeys.ContainsKey(operation), $"{caseName}: unknown operation {operation}");
            var input = root.GetProperty("input");
            var inputKeys = new List<string>(CommonInput);
            inputKeys.AddRange(InputKeys[operation]);
            AssertKeys(input, caseName + " input", inputKeys.ToArray());
            var expected = root.GetProperty("expected");
            AssertKeys(expected, caseName + " expected", ExpectedKeys[operation]);
            double epsilon = root.GetProperty("relative_epsilon").GetDouble();

            string centerRe = input.GetProperty("center_re").GetString()!;
            string centerIm = input.GetProperty("center_im").GetString()!;
            double zoom = input.GetProperty("zoom_log10").GetDouble();
            var radiusElement = input.GetProperty("radius");
            double? radius = radiusElement.ValueKind == JsonValueKind.Null ? (double?)null : Double(radiusElement.GetString()!);

            if (operation == "find")
            {
                Nucleus got = NucleusFinder.FindNucleus(
                    centerRe, centerIm, input.GetProperty("period").GetInt32(), zoom, radius,
                    input.GetProperty("max_steps").GetInt32(), input.GetProperty("max_evaluations").GetInt32(),
                    input.GetProperty("max_escalations").GetInt32());
                CheckNucleus(caseName, got, expected.GetProperty("nucleus"), expected.GetProperty("location"), epsilon);
                return;
            }
            BoxResult box = NucleusFinder.BoxPeriod(centerRe, centerIm, zoom, input.GetProperty("max_period").GetInt32(), radius);
            var wantBox = expected.GetProperty("box");
            AssertKeys(wantBox, caseName + " box", "period", "reason", "halvings", "radius");
            Assert.Equal(NullableInt(wantBox.GetProperty("period")), box.Period);
            Assert.Equal(wantBox.GetProperty("reason").GetString(), box.Reason);
            Assert.Equal(wantBox.GetProperty("halvings").GetInt32(), box.Halvings);
            Assert.Equal(Double(wantBox.GetProperty("radius").GetString()!), box.Radius);
            if (operation == "box")
                return;
            if (box.Period == null)
            {
                Assert.Equal(JsonValueKind.Null, expected.GetProperty("nucleus").ValueKind);
                Assert.Equal(JsonValueKind.Null, expected.GetProperty("location").ValueKind);
                return;
            }
            Nucleus snapped = NucleusFinder.FindNucleus(centerRe, centerIm, box.Period.Value, zoom, box.Radius);
            CheckNucleus(caseName, snapped, expected.GetProperty("nucleus"), expected.GetProperty("location"), epsilon);
        }

        private static void CheckNucleus(string caseName, Nucleus got, JsonElement want, JsonElement location, double epsilon)
        {
            AssertKeys(want, caseName + " nucleus", NucleusKeys);
            Assert.Equal(want.GetProperty("found").GetBoolean(), got.Found);
            Assert.Equal(want.GetProperty("converged").GetBoolean(), got.Converged);
            Assert.Equal(want.GetProperty("inside").GetBoolean(), got.Inside);
            Assert.Equal(want.GetProperty("stop").GetString(), got.Stop);
            Assert.Equal(want.GetProperty("center_re").GetString(), got.CenterRe);
            Assert.Equal(want.GetProperty("center_im").GetString(), got.CenterIm);
            Assert.Equal(want.GetProperty("period").GetInt32(), got.Period);
            Assert.Equal(NullableInt(want.GetProperty("lower_period")), got.LowerPeriod);
            Assert.Equal(want.GetProperty("bits").GetInt32(), got.Bits);
            Assert.Equal(want.GetProperty("steps").GetInt32(), got.Steps);
            Assert.Equal(want.GetProperty("evaluations").GetInt32(), got.Evaluations);
            Assert.Equal(want.GetProperty("depth_bits").GetInt32(), got.DepthBits);
            AssertClose(Double(want.GetProperty("size_log10").GetString()!), got.SizeLog10, epsilon, caseName);
            if (location.ValueKind == JsonValueKind.Null)
            {
                Assert.False(got.Found);
                return;
            }
            AssertKeys(location, caseName + " location", "half_height_log10", "max_iter");
            Location loc = got.ToLocation();
            Assert.Equal("nucleus", loc.Format);
            Assert.Equal(location.GetProperty("max_iter").GetInt64(), loc.MaxIter);
            AssertClose(Double(location.GetProperty("half_height_log10").GetString()!), loc.HalfHeightLog10!.Value, epsilon, caseName);
        }

        private static void AssertClose(double want, double got, double epsilon, string caseName)
        {
            if (double.IsNaN(want))
            {
                Assert.True(double.IsNaN(got), $"{caseName}: expected NaN, got {got:R}");
                return;
            }
            Assert.True(Math.Abs(got - want) <= epsilon * Math.Abs(want), $"{caseName}: {got:R} vs {want:R}");
        }

        private static int? NullableInt(JsonElement element) =>
            element.ValueKind == JsonValueKind.Null ? (int?)null : element.GetInt32();

        private static double Double(string bits) =>
            BitConverter.Int64BitsToDouble(unchecked((long)Convert.ToUInt64(bits.Substring(2), 16)));

        private static void AssertKeys(JsonElement element, string where, params string[] keys)
        {
            var want = new HashSet<string>(keys);
            var present = new HashSet<string>();
            foreach (var property in element.EnumerateObject())
            {
                Assert.True(want.Contains(property.Name), $"{where}: runner does not understand '{property.Name}'");
                present.Add(property.Name);
            }
            foreach (string key in keys)
                Assert.True(present.Contains(key), $"{where}: missing '{key}'");
        }
    }
}
