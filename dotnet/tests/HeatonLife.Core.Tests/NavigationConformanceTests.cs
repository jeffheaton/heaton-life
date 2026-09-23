using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Navigation vectors (spec/navigation.md): exact viewport arithmetic must reproduce
    /// the Python reference's strings, and pixel_delta's doubles, bit for bit. Strict: a key
    /// or operation this runner does not know fails the case.
    /// </summary>
    public class NavigationConformanceTests
    {
        private static readonly HashSet<string> BaseKeys = new HashSet<string>
        {
            "spec_version", "family", "tier", "operation", "expected",
        };

        private static readonly Dictionary<string, string[]> OperationKeys = new Dictionary<string, string[]>
        {
            ["pan"] = new[] { "viewport", "size", "dx", "dy" },
            ["zoom_at"] = new[] { "viewport", "size", "dx", "dy", "zoom_log10" },
            ["pixel_delta"] = new[] { "from", "to", "size" },
            ["positional"] = new[] { "inputs" },
            ["sequence"] = new[] { "viewport", "size", "steps" },
        };

        [Fact]
        public void EveryOperationHasVectors()
        {
            var seen = new HashSet<string>();
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "navigation")))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
                seen.Add(doc.RootElement.GetProperty("operation").GetString()!);
            }
            Assert.True(seen.SetEquals(OperationKeys.Keys), string.Join(", ", seen));
        }

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "navigation")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string dir = Path.Combine(TestPaths.VectorRoot(), "navigation", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("navigation", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            Assert.Equal("0.5.0", root.GetProperty("spec_version").GetString());
            string operation = root.GetProperty("operation").GetString()!;
            Assert.True(OperationKeys.ContainsKey(operation), $"{caseName}: unknown operation {operation}");
            var allowed = new HashSet<string>(BaseKeys);
            allowed.UnionWith(OperationKeys[operation]);
            if (operation == "pan")
                allowed.Add("zoom_log10");                   // optional: pan and zoom in one step
            var present = new HashSet<string>();
            foreach (var property in root.EnumerateObject())
            {
                Assert.True(allowed.Contains(property.Name), $"{caseName}: runner does not understand '{property.Name}'");
                present.Add(property.Name);
            }
            foreach (string key in OperationKeys[operation])
                Assert.True(present.Contains(key), $"{caseName}: missing '{key}'");

            var expected = root.GetProperty("expected");
            if (operation == "positional")
            {
                var inputs = root.GetProperty("inputs");
                Assert.Equal(expected.GetArrayLength(), inputs.GetArrayLength());
                for (int i = 0; i < inputs.GetArrayLength(); i++)
                    Assert.Equal(expected[i].GetString(), Navigation.Positional(inputs[i].GetString()!));
                return;
            }
            int width = root.GetProperty("size")[0].GetInt32();
            int height = root.GetProperty("size")[1].GetInt32();
            if (operation == "pixel_delta")
            {
                var (dx, dy) = Navigation.PixelDelta(
                    ReadViewport(root.GetProperty("from")), ReadViewport(root.GetProperty("to")), width, height);
                Assert.Equal(expected.GetProperty("dx_bits").GetString(), Bits(dx));
                Assert.Equal(expected.GetProperty("dy_bits").GetString(), Bits(dy));
                return;
            }
            var viewport = ReadViewport(root.GetProperty("viewport"));
            if (operation == "sequence")
            {
                var steps = root.GetProperty("steps");
                Assert.Equal(expected.GetArrayLength(), steps.GetArrayLength());
                for (int i = 0; i < steps.GetArrayLength(); i++)
                {
                    var step = steps[i];
                    AssertKeys(step, $"{caseName} step {i}", "operation", "dx", "dy");
                    Assert.Equal("pan", step.GetProperty("operation").GetString());
                    viewport = Navigation.Pan(viewport, step.GetProperty("dx").GetDouble(), step.GetProperty("dy").GetDouble(), width, height);
                    AssertViewport(expected[i], viewport, $"{caseName} step {i}", "working_bits");
                    Assert.Equal(
                        expected[i].GetProperty("working_bits").GetInt32(),
                        ReferenceOrbit.WorkingBits(viewport.CenterRe, viewport.CenterIm, viewport.ZoomLog10));
                }
                return;
            }
            double dxIn = root.GetProperty("dx").GetDouble();
            double dyIn = root.GetProperty("dy").GetDouble();
            Viewport got = operation == "pan"
                ? (root.TryGetProperty("zoom_log10", out var zoom)
                    ? Navigation.Pan(viewport, dxIn, dyIn, width, height, zoom.GetDouble())
                    : Navigation.Pan(viewport, dxIn, dyIn, width, height))
                : Navigation.ZoomAt(viewport, dxIn, dyIn, width, height, root.GetProperty("zoom_log10").GetDouble());
            AssertViewport(expected, got, caseName);
        }

        private static Viewport ReadViewport(JsonElement vp)
        {
            bool offCenter = vp.TryGetProperty("reference_re", out _);
            return new Viewport(
                vp.GetProperty("center_re").GetString()!,
                vp.GetProperty("center_im").GetString()!,
                vp.GetProperty("zoom_log10").GetDouble(),
                offCenter ? vp.GetProperty("reference_re").GetString() : null,
                offCenter ? vp.GetProperty("reference_im").GetString() : null);
        }

        private static void AssertViewport(JsonElement expected, Viewport got, string where, params string[] extra)
        {
            var keys = new List<string> { "center_re", "center_im", "zoom_log10" };
            if (expected.TryGetProperty("reference_re", out _))
                keys.AddRange(new[] { "reference_re", "reference_im" });
            keys.AddRange(extra);
            AssertKeys(expected, where, keys.ToArray());
            Assert.True(expected.GetProperty("center_re").GetString() == got.CenterRe, $"{where}: center_re {got.CenterRe}");
            Assert.True(expected.GetProperty("center_im").GetString() == got.CenterIm, $"{where}: center_im {got.CenterIm}");
            Assert.Equal(expected.GetProperty("zoom_log10").GetDouble(), got.ZoomLog10);
            bool offCenter = expected.TryGetProperty("reference_re", out var referenceRe);
            Assert.Equal(offCenter ? referenceRe.GetString() : null, got.ReferenceRe);
            Assert.Equal(offCenter ? expected.GetProperty("reference_im").GetString() : null, got.ReferenceIm);
        }

        /// <summary>The object must carry exactly these keys (strict: unknown keys fail the case).</summary>
        private static void AssertKeys(JsonElement element, string where, params string[] expected)
        {
            var names = new HashSet<string>();
            foreach (var property in element.EnumerateObject())
                names.Add(property.Name);
            Assert.True(names.SetEquals(expected), $"{where}: unexpected keys {string.Join(", ", names)}");
        }

        private static string Bits(double value) => "0x" + BitConverter.DoubleToInt64Bits(value).ToString("X16");
    }
}
