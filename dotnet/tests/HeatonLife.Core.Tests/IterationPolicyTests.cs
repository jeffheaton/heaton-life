using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Iteration-policy conformance (spec/fractals.md "Iteration policy", policy version 1).
    /// Strict: a key this runner does not know fails the case.
    /// </summary>
    public class IterationPolicyTests
    {
        [Fact]
        public void IterationPolicyTable()
        {
            string path = Path.Combine(TestPaths.VectorRoot(), "iteration-policy", "table", "params.json");
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            AssertKeys(root, "table", "spec_version", "family", "tier", "policy_version", "ramp", "frames");
            Assert.Equal("iteration-policy", root.GetProperty("family").GetString());
            Assert.Equal("0.6.0", root.GetProperty("spec_version").GetString());
            Assert.Equal(1, root.GetProperty("policy_version").GetInt32());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            foreach (var row in root.GetProperty("ramp").EnumerateArray())
            {
                AssertKeys(row, "ramp row", "zoom_log10", "max_iter");
                Assert.Equal(row.GetProperty("max_iter").GetInt32(), IterationPolicy.AutoMaxIter(row.GetProperty("zoom_log10").GetDouble()));
            }
            foreach (var frame in root.GetProperty("frames").EnumerateArray())
            {
                AssertKeys(frame, "frame", "zoom_log10", "counts", "need", "suggest");
                var countsJson = frame.GetProperty("counts");
                var counts = new int[countsJson.GetArrayLength()];
                for (int i = 0; i < counts.Length; i++)
                    counts[i] = countsJson[i].GetInt32();
                Assert.Equal(frame.GetProperty("need").GetInt32(), IterationPolicy.NeedFromCounts(counts));
                Assert.Equal(frame.GetProperty("suggest").GetInt32(),
                    IterationPolicy.SuggestMaxIter(frame.GetProperty("zoom_log10").GetDouble(), counts));
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
    }
}
