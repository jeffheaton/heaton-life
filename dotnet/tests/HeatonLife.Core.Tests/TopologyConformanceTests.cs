using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Grid topology conformance: replay vectors/topology/ — each topology's halo (where every
    /// point past an edge lands), the bounded-grid suffix read and canonicalized, and a rule's text
    /// split at its suffix, with the reason for every error (spec/topology.md "Vector encoding").
    /// As strict as the Python runner (python/tests/test_topology_vectors.py).
    /// </summary>
    public class TopologyConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.16.0" };
        private static readonly string[] CaseKeys = { "spec_version", "family", "tier", "kind", "cases" };
        private static readonly string[] HaloKeys = { "width", "height", "boundary", "shift", "axis", "radius" };
        private static readonly string[] SuffixKeys = { "input", "canonical", "width", "height", "boundary", "shift", "axis" };
        private static readonly string[] ErrorKeys = { "input", "error", "reason" };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "topology");

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Root).OrderBy(d => d, StringComparer.Ordinal))
            {
                if (File.Exists(Path.Combine(dir, "params.json")))
                    yield return new object[] { Path.GetFileName(dir) };
            }
        }

        [Fact]
        public void EveryKindHasVectors()
        {
            var kinds = new HashSet<string>();
            foreach (object[] c in Cases())
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, (string)c[0], "params.json")));
                kinds.Add(doc.RootElement.GetProperty("kind").GetString()!);
            }
            Assert.Equal(new HashSet<string> { "halo", "suffix", "split" }, kinds);
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, caseName, "params.json")));
            JsonElement root = doc.RootElement;
            AssertKeys(root, CaseKeys);
            Assert.Contains(root.GetProperty("spec_version").GetString(), SpecVersions);
            Assert.Equal("topology", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string kind = root.GetProperty("kind").GetString()!;
            foreach (JsonElement entry in root.GetProperty("cases").EnumerateArray())
            {
                switch (kind)
                {
                    case "halo":
                        HaloCase(entry);
                        break;
                    case "suffix":
                        SuffixCase(entry);
                        break;
                    case "split":
                        SplitCase(entry);
                        break;
                    default:
                        throw new InvalidDataException($"unknown topology kind {kind}");
                }
            }
        }

        private static void HaloCase(JsonElement entry)
        {
            int width = entry.GetProperty("width").GetInt32();
            int height = entry.GetProperty("height").GetInt32();
            int radius = entry.GetProperty("radius").GetInt32();
            string boundary = entry.GetProperty("boundary").GetString()!;
            int shift = entry.GetProperty("shift").GetInt32();
            string axis = entry.GetProperty("axis").GetString()!;
            if (entry.TryGetProperty("error", out _))
            {
                AssertKeys(entry, HaloKeys.Concat(new[] { "error", "reason" }).ToArray());
                TopologyException refused = Assert.Throws<TopologyException>(
                    () => new Halo(Topology.Parse(boundary, shift, axis), width, height, radius));
                Assert.Equal(entry.GetProperty("reason").GetString(), refused.Reason);
                return;
            }
            AssertKeys(entry, HaloKeys.Concat(new[] { "map" }).ToArray());
            Topology topology = Topology.Parse(boundary, shift, axis);
            Assert.Equal((shift, axis), (topology.Shift, topology.AxisName)); // canonical
            var halo = new Halo(topology, width, height, radius);
            JsonElement[] rows = entry.GetProperty("map").EnumerateArray().ToArray();
            Assert.Equal(halo.Rows, rows.Length);
            // A fill of distinct values holds the mapped ones, the blank where there is none.
            byte[]? filled = null;
            if (width * height < 255)
            {
                var cells = new byte[width * height];
                for (int i = 0; i < cells.Length; i++)
                    cells[i] = (byte)(i + 1);
                filled = new byte[halo.Length];
                halo.Fill(cells, filled, 0);
            }
            for (int row = 0; row < halo.Rows; row++)
            {
                int[] expected = rows[row].EnumerateArray().Select(v => v.GetInt32()).ToArray();
                Assert.Equal(halo.Columns, expected.Length);
                for (int column = 0; column < halo.Columns; column++)
                {
                    Assert.True(
                        expected[column] == halo.Source(column, row),
                        $"{boundary} {width}x{height} r{radius} at ({column}, {row})");
                    if (filled != null)
                        Assert.Equal(expected[column], filled[row * halo.Columns + column] - 1);
                }
            }
        }

        private static void SuffixCase(JsonElement entry)
        {
            string text = entry.GetProperty("input").GetString()!;
            if (entry.TryGetProperty("error", out _))
            {
                AssertKeys(entry, ErrorKeys);
                string reason = entry.GetProperty("reason").GetString()!;
                Assert.False(BoundedGrid.TryParse(text, out BoundedGrid? none, out string? found), text);
                Assert.Null(none);
                Assert.Equal(reason, found);
                TopologyException thrown = Assert.Throws<TopologyException>(() => BoundedGrid.Parse(text));
                Assert.Equal($"invalid bounded grid '{text}': {reason} (spec/topology.md)", thrown.Message);
                Assert.Equal(reason, thrown.Reason);
                return;
            }
            AssertKeys(entry, SuffixKeys);
            BoundedGrid grid = BoundedGrid.Parse(text);
            Assert.True(BoundedGrid.TryParse(text, out BoundedGrid? again, out string? noReason), text);
            Assert.Null(noReason);
            Assert.Equal(grid, again);
            Assert.Equal(entry.GetProperty("width").GetInt32(), grid.Width);
            Assert.Equal(entry.GetProperty("height").GetInt32(), grid.Height);
            Assert.Equal(entry.GetProperty("boundary").GetString(), grid.Topology.Name);
            Assert.Equal(entry.GetProperty("shift").GetInt32(), grid.Topology.Shift);
            Assert.Equal(entry.GetProperty("axis").GetString(), grid.Topology.AxisName);
            string canonical = entry.GetProperty("canonical").GetString()!;
            Assert.Equal(canonical, grid.Suffix);
            Assert.Equal(canonical, grid.ToString());
            Assert.Equal(grid, BoundedGrid.Parse(canonical));
        }

        private static void SplitCase(JsonElement entry)
        {
            string text = entry.GetProperty("input").GetString()!;
            if (entry.TryGetProperty("error", out _))
            {
                AssertKeys(entry, ErrorKeys);
                TopologyException refused = Assert.Throws<TopologyException>(() => BoundedGrid.SplitRule(text, out _));
                Assert.Equal(entry.GetProperty("reason").GetString(), refused.Reason);
                return;
            }
            AssertKeys(entry, new[] { "input", "rule", "suffix" });
            string rule = BoundedGrid.SplitRule(text, out BoundedGrid? grid);
            Assert.Equal(entry.GetProperty("rule").GetString(), rule);
            JsonElement suffix = entry.GetProperty("suffix");
            Assert.Equal(suffix.ValueKind == JsonValueKind.Null ? null : suffix.GetString(), grid?.Suffix);
        }

        private static void AssertKeys(JsonElement element, string[] keys)
        {
            var found = new HashSet<string>(element.EnumerateObject().Select(p => p.Name));
            Assert.Equal(new HashSet<string>(keys), found);
        }
    }
}
