using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Pattern file conformance: replay vectors/formats/ — every format read into a grid and into
    /// the unbounded universe, detection, metadata read and written, and Macrocell timelines
    /// (spec/formats.md, spec/macrocell.md). Bit-exact, and as strict as the Python runner
    /// (python/tests/test_format_vectors.py): an unknown key, kind, or spec_version fails the case.
    /// </summary>
    public class FormatConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.16.0" };

        private static readonly Dictionary<string, HashSet<string>> Keys = BuildKeys();

        private static Dictionary<string, HashSet<string>> BuildKeys()
        {
            string[] common = { "spec_version", "family", "tier", "kind" };
            string[] state = { "generation", "population", "bounding_box", "state", "state_sha256", "state_lines" };
            HashSet<string> Of(params string[][] groups) => new HashSet<string>(groups.SelectMany(g => g));
            return new Dictionary<string, HashSet<string>>
            {
                ["read"] = Of(common, new[]
                {
                    "input", "trim", "limit", "error", "format", "x", "y", "rule", "generation", "metadata", "grid",
                    "canonical",
                }),
                ["universe"] = Of(common, new[] { "input", "error", "format", "metadata", "with_metadata", "rle", "rle_error" }, state),
                ["detect"] = Of(common, new[] { "inputs" }),
                ["timeline-read"] = Of(common, new[] { "input", "error", "count", "first", "step", "metadata", "universe", "frames" }),
                ["timeline-write"] = Of(common, new[] { "input", "generations", "metadata", "timeline", "frames" }),
            };
        }

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "formats");

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
            Assert.Equal(new HashSet<string>(Keys.Keys), kinds);
        }

        private static PatternMetadata Metadata(JsonElement e)
        {
            string? name = e.GetProperty("name").ValueKind == JsonValueKind.Null ? null : e.GetProperty("name").GetString();
            string? author = e.GetProperty("author").ValueKind == JsonValueKind.Null ? null : e.GetProperty("author").GetString();
            var comments = e.GetProperty("comments").EnumerateArray().Select(c => c.GetString()!).ToList();
            return new PatternMetadata(name, author, comments);
        }

        private static void ExpectState(string caseDir, HashLife u, JsonElement entry)
        {
            Assert.Equal(BigInteger.Parse(entry.GetProperty("generation").GetString()!), u.Generation);
            Assert.Equal(BigInteger.Parse(entry.GetProperty("population").GetString()!), u.Population);
            JsonElement box = entry.GetProperty("bounding_box");
            CellBox? found = u.BoundingBox;
            if (box.ValueKind == JsonValueKind.Null)
            {
                Assert.Null(found);
            }
            else
            {
                Assert.NotNull(found);
                BigInteger[] want = box.EnumerateArray().Select(v => BigInteger.Parse(v.GetString()!)).ToArray();
                Assert.Equal(want, new[] { found!.Value.X0, found.Value.Y0, found.Value.X1, found.Value.Y1 });
            }
            string text = u.ToMacrocell();
            if (entry.TryGetProperty("state", out JsonElement file))
            {
                Assert.Equal(File.ReadAllText(Path.Combine(caseDir, file.GetString()!)), text);
            }
            else
            {
                Assert.Equal(entry.GetProperty("state_lines").GetInt32(), text.Count(ch => ch == '\n'));
                byte[] digest = SHA256.HashData(Encoding.ASCII.GetBytes(text));
                Assert.Equal(entry.GetProperty("state_sha256").GetString(), Convert.ToHexString(digest).ToLowerInvariant());
            }
        }

        private static void Refused(Action read)
        {
            Exception e = Assert.ThrowsAny<Exception>(read);
            Assert.True(e is FormatException || e is ArgumentException, $"refused with {e.GetType().Name}: {e.Message}");
        }

        private static PatternFile Read(JsonElement root, byte[] data)
        {
            JsonElement limit = root.GetProperty("limit");
            long? maxCells = limit.ValueKind == JsonValueKind.String
                ? Patterns.DefaultMaxCells
                : limit.ValueKind == JsonValueKind.Null ? (long?)null : limit.GetInt64();
            return PatternFiles.Read(data, maxCells, root.GetProperty("trim").GetBoolean());
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string dir = Path.Combine(Root, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            JsonElement root = doc.RootElement;
            string kind = root.GetProperty("kind").GetString()!;
            Assert.Equal("formats", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            Assert.Contains(root.GetProperty("spec_version").GetString(), SpecVersions);
            Assert.True(Keys.ContainsKey(kind), $"unknown kind {kind}");
            foreach (JsonProperty property in root.EnumerateObject())
                Assert.True(Keys[kind].Contains(property.Name), $"{caseName}: unknown key {property.Name}");
            bool error = root.TryGetProperty("error", out JsonElement flag) && flag.GetBoolean();

            switch (kind)
            {
                case "read":
                    {
                        byte[] data = File.ReadAllBytes(Path.Combine(dir, root.GetProperty("input").GetString()!));
                        if (error)
                        {
                            Refused(() => Read(root, data));
                            return;
                        }
                        PatternFile found = Read(root, data);
                        Assert.Equal(root.GetProperty("format").GetString(), PatternFiles.FormatName(found.Format));
                        Assert.Equal(BigInteger.Parse(root.GetProperty("x").GetString()!), found.X);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("y").GetString()!), found.Y);
                        JsonElement rule = root.GetProperty("rule");
                        Assert.Equal(rule.ValueKind == JsonValueKind.Null ? null : rule.GetString(), found.Rule);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("generation").GetString()!), found.Generation);
                        Assert.Equal(Metadata(root.GetProperty("metadata")), found.Metadata);
                        JsonElement grid = root.GetProperty("grid");
                        Assert.Equal(grid.GetProperty("shape")[0].GetInt32(), found.Height);
                        Assert.Equal(grid.GetProperty("shape")[1].GetInt32(), found.Width);
                        var (_, _, _, pixels) = Png.Read(Path.Combine(dir, grid.GetProperty("file").GetString()!));
                        Assert.Equal(pixels, found.Cells);
                        string canonical = File.ReadAllText(Path.Combine(dir, root.GetProperty("canonical").GetString()!));
                        Assert.Equal(
                            canonical,
                            Patterns.RleEncode(found.Cells, found.Width, found.Height, found.Rule ?? "B3/S23", found.Metadata));
                        PatternFile again = PatternFiles.Read(canonical); // the round trip
                        Assert.Equal(found.Cells, again.Cells);
                        Assert.Equal(found.Metadata, again.Metadata);
                        break;
                    }
                case "universe":
                    {
                        byte[] data = File.ReadAllBytes(Path.Combine(dir, root.GetProperty("input").GetString()!));
                        if (error)
                        {
                            Refused(() => PatternFiles.ReadUniverse(data));
                            return;
                        }
                        PatternUniverse found = PatternFiles.ReadUniverse(data);
                        Assert.Equal(root.GetProperty("format").GetString(), PatternFiles.FormatName(found.Format));
                        Assert.Equal(Metadata(root.GetProperty("metadata")), found.Metadata);
                        ExpectState(dir, found.Universe, root);
                        Assert.Equal(
                            File.ReadAllText(Path.Combine(dir, root.GetProperty("with_metadata").GetString()!)),
                            found.Universe.ToMacrocell(found.Metadata));
                        if (root.TryGetProperty("rle_error", out _))
                        {
                            Assert.Throws<InvalidOperationException>(() => found.Universe.ToRle(found.Metadata));
                        }
                        else
                        {
                            Assert.Equal(
                                File.ReadAllText(Path.Combine(dir, root.GetProperty("rle").GetString()!)),
                                found.Universe.ToRle(found.Metadata));
                        }
                        break;
                    }
                case "detect":
                    {
                        foreach (JsonElement entry in root.GetProperty("inputs").EnumerateArray())
                        {
                            byte[] data = Convert.FromHexString(entry.GetProperty("input").GetString()!);
                            if (entry.TryGetProperty("error", out _))
                                Refused(() => PatternFiles.Detect(data));
                            else
                                Assert.Equal(entry.GetProperty("format").GetString(), PatternFiles.FormatName(PatternFiles.Detect(data)));
                        }
                        break;
                    }
                case "timeline-read":
                    {
                        string text = File.ReadAllText(Path.Combine(dir, root.GetProperty("input").GetString()!));
                        if (error)
                        {
                            Assert.Throws<FormatException>(() => Macrocell.ReadTimeline(text));
                            return;
                        }
                        MacrocellTimeline timeline = Macrocell.ReadTimeline(text);
                        Assert.Equal(root.GetProperty("count").GetInt32(), timeline.Frames.Count);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("first").GetString()!), timeline.Frames[0].Generation);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("step").GetString()!), timeline.Step);
                        Assert.Equal(Metadata(root.GetProperty("metadata")), timeline.Metadata);
                        ExpectState(dir, timeline.Universe, root.GetProperty("universe"));
                        int i = 0;
                        foreach (JsonElement entry in root.GetProperty("frames").EnumerateArray())
                        {
                            timeline.Universe.Restore(timeline.Frames[i++]);
                            ExpectState(dir, timeline.Universe, entry);
                        }
                        Assert.Equal(timeline.Frames.Count, i);
                        break;
                    }
                case "timeline-write":
                    {
                        byte[] input = File.ReadAllBytes(Path.Combine(dir, root.GetProperty("input").GetString()!));
                        HashLife universe = PatternFiles.ReadUniverse(input).Universe;
                        var frames = new List<HashLifeSnapshot>();
                        foreach (JsonElement generation in root.GetProperty("generations").EnumerateArray())
                        {
                            universe.Step(BigInteger.Parse(generation.GetString()!) - universe.Generation);
                            frames.Add(universe.Snapshot());
                        }
                        PatternMetadata metadata = Metadata(root.GetProperty("metadata"));
                        string text = Macrocell.WriteTimeline(universe, frames, metadata);
                        Assert.Equal(File.ReadAllText(Path.Combine(dir, root.GetProperty("timeline").GetString()!)), text);
                        MacrocellTimeline timeline = Macrocell.ReadTimeline(text);
                        Assert.Equal(metadata, timeline.Metadata);
                        int i = 0;
                        foreach (JsonElement entry in root.GetProperty("frames").EnumerateArray())
                        {
                            timeline.Universe.Restore(timeline.Frames[i++]);
                            ExpectState(dir, timeline.Universe, entry);
                        }
                        Assert.Equal(timeline.Frames.Count, i);
                        break;
                    }
                default:
                    throw new InvalidDataException($"unknown kind {kind}");
            }
        }
    }
}
