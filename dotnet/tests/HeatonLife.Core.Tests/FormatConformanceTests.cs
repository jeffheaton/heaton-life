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
    /// Pattern file conformance: replay vectors/formats/ — every format read into a grid, into a
    /// new unbounded universe and into one that exists, measured without a grid, detection,
    /// metadata read and written, Macrocell timelines, MCell files written and every MCell
    /// refusal's reason (spec/formats.md, spec/macrocell.md).
    /// Bit-exact, and as strict as the Python runner (python/tests/test_format_vectors.py): an
    /// unknown key, kind, or spec_version fails the case.
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
                    "canonical", "bounded_grid", "mcell", "mcell_error",
                }),
                ["universe"] = Of(
                    common, new[] { "input", "error", "format", "metadata", "with_metadata", "rle", "rle_error", "frames", "step" },
                    state),
                ["detect"] = Of(common, new[] { "inputs" }),
                ["measure"] = Of(common, new[]
                {
                    "input", "error", "format", "width", "height", "x", "y", "rule", "generation", "metadata", "two_state",
                    "bounded_grid",
                }),
                ["timeline-read"] = Of(common, new[] { "input", "error", "count", "first", "step", "metadata", "universe", "frames" }),
                ["timeline-write"] = Of(common, new[] { "input", "generations", "metadata", "timeline", "frames" }),
                ["mcell-reasons"] = Of(common, new[] { "cases" }),
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

        /// <summary>A rule's canonical form in the family that reads it, so that two spellings
        /// of one rule (<c>345/2/4</c> and <c>B2/S345/C4</c>) compare equal.</summary>
        private static string CanonicalRule(string text)
        {
            string rule = PatternFiles.LifeRule(text);
            if (RuleString.TryCompile(rule, true, out LifeRule? life, out _))
                return life.Canonical;
            if (GenerationsRule.TryCompile(text, out GenerationsRule? generations, out _))
                return generations.Canonical;
            return LtlRule.TryParse(text, out LtlRule? ltl, out _) ? ltl!.Canonical : text;
        }

        internal static PatternMetadata Metadata(JsonElement e)
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

        /// <summary>A case's bounded grid (spec/topology.md): its canonical suffix, or null if absent.</summary>
        private static BoundedGrid? Bounded(JsonElement root)
            => root.TryGetProperty("bounded_grid", out JsonElement suffix) ? BoundedGrid.Parse(suffix.GetString()!) : null;

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
                        Assert.Equal(Bounded(root), found.BoundedGrid);
                        // A bounded world writes its suffix; its trimmed cells are no world.
                        Topology? topology = found.BoundedGrid == null || root.GetProperty("trim").GetBoolean()
                            ? (Topology?)null
                            : found.BoundedGrid.Topology;
                        string canonical = File.ReadAllText(Path.Combine(dir, root.GetProperty("canonical").GetString()!));
                        Assert.Equal(
                            canonical,
                            Patterns.RleEncode(
                                found.Cells, found.Width, found.Height, found.Rule ?? "B3/S23", found.Metadata, topology));
                        PatternFile again = PatternFiles.Read(canonical); // the round trip
                        Assert.Equal(found.Cells, again.Cells);
                        Assert.Equal(found.Metadata, again.Metadata);
                        string writerRule = found.Rule ?? "B3/S23";
                        if (root.TryGetProperty("mcell_error", out JsonElement refused) && refused.GetBoolean())
                        {
                            Assert.ThrowsAny<ArgumentException>(
                                () => Patterns.McellEncode(found.Cells, found.Width, found.Height, writerRule, found.Metadata, topology));
                        }
                        else if (root.TryGetProperty("mcell", out JsonElement mcell))
                        {
                            string text = Patterns.McellEncode(found.Cells, found.Width, found.Height, writerRule, found.Metadata, topology);
                            Assert.Equal(File.ReadAllText(Path.Combine(dir, mcell.GetString()!)), text);
                            PatternFile back = PatternFiles.Read(text); // the same grid, rule and world
                            Assert.Equal(found.Cells, back.Cells);
                            Assert.Equal(CanonicalRule(writerRule), CanonicalRule(back.Rule!));
                            Assert.Equal(topology == null ? null : found.BoundedGrid, back.BoundedGrid);
                            PatternMetadata notes = found.Metadata;
                            var flat = new List<string>();
                            if (notes.Name != null)
                                flat.Add(notes.Name);
                            if (notes.Author != null)
                                flat.Add(notes.Author);
                            flat.AddRange(notes.Comments);
                            Assert.Equal(new PatternMetadata(null, null, flat), back.Metadata); // all comments
                        }
                        break;
                    }
                case "mcell-reasons":
                    {
                        foreach (JsonElement entry in root.GetProperty("cases").EnumerateArray())
                        {
                            Assert.Equal(
                                new HashSet<string> { "input", "message" },
                                new HashSet<string>(entry.EnumerateObject().Select(p => p.Name)));
                            string input = entry.GetProperty("input").GetString()!;
                            FormatException e = Assert.Throws<FormatException>(() => PatternFiles.Read(input));
                            Assert.Equal(entry.GetProperty("message").GetString(), e.Message);
                        }
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
                        if (root.TryGetProperty("frames", out JsonElement frames))
                        {
                            // A timeline: the universe at the file's own root, and every frame.
                            Assert.Equal(BigInteger.Parse(root.GetProperty("step").GetString()!), found.Step);
                            ExpectFrames(dir, found.Universe, found.Frames, frames);
                        }
                        else
                        {
                            Assert.Empty(found.Frames);
                            Assert.Null(found.Step);
                        }
                        break;
                    }
                case "measure":
                    {
                        byte[] data = File.ReadAllBytes(Path.Combine(dir, root.GetProperty("input").GetString()!));
                        if (error)
                        {
                            Refused(() => PatternFiles.Measure(data));
                            return;
                        }
                        PatternExtent extent = PatternFiles.Measure(data);
                        Assert.Equal(root.GetProperty("format").GetString(), PatternFiles.FormatName(extent.Format));
                        Assert.Equal(BigInteger.Parse(root.GetProperty("width").GetString()!), extent.Width);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("height").GetString()!), extent.Height);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("x").GetString()!), extent.X);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("y").GetString()!), extent.Y);
                        JsonElement rule = root.GetProperty("rule");
                        Assert.Equal(rule.ValueKind == JsonValueKind.Null ? null : rule.GetString(), extent.Rule);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("generation").GetString()!), extent.Generation);
                        Assert.Equal(Metadata(root.GetProperty("metadata")), extent.Metadata);
                        Assert.Equal(root.GetProperty("two_state").GetBoolean(), extent.TwoState);
                        Assert.Equal(Bounded(root), extent.BoundedGrid);
                        if (data.All(b => b < 0x80))
                        {
                            // A text file measures the same handed over as text.
                            PatternExtent text = PatternFiles.Measure(Encoding.ASCII.GetString(data));
                            Assert.Equal((extent.Format, extent.Width, extent.Height), (text.Format, text.Width, text.Height));
                            Assert.Equal((extent.X, extent.Y, extent.Rule), (text.X, text.Y, text.Rule));
                            Assert.Equal((extent.Generation, extent.TwoState), (text.Generation, text.TwoState));
                            Assert.Equal(extent.Metadata, text.Metadata);
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
                        // A file with a #FRAMES line is a timeline to the reader by content too.
                        bool framed = text.Split('\n').Any(line => line.Trim().StartsWith("#FRAMES", StringComparison.Ordinal));
                        if (error)
                        {
                            Assert.Throws<FormatException>(() => Macrocell.ReadTimeline(text));
                            if (framed)
                                Assert.Throws<FormatException>(() => PatternFiles.ReadUniverse(text));
                            return;
                        }
                        MacrocellTimeline timeline = Macrocell.ReadTimeline(text);
                        Assert.Equal(root.GetProperty("count").GetInt32(), timeline.Frames.Count);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("first").GetString()!), timeline.Frames[0].Generation);
                        Assert.Equal(BigInteger.Parse(root.GetProperty("step").GetString()!), timeline.Step);
                        Assert.Equal(Metadata(root.GetProperty("metadata")), timeline.Metadata);
                        ExpectState(dir, timeline.Universe, root.GetProperty("universe"));
                        ExpectFrames(dir, timeline.Universe, timeline.Frames, root.GetProperty("frames"));
                        PatternUniverse byContent = PatternFiles.ReadUniverse(text);
                        Assert.Equal(timeline.Step, byContent.Step);
                        ExpectState(dir, byContent.Universe, root.GetProperty("universe"));
                        ExpectFrames(dir, byContent.Universe, byContent.Frames, root.GetProperty("frames"));
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

        /// <summary>Each frame restored in turn matches its pinned state.</summary>
        private static void ExpectFrames(string dir, HashLife universe, IReadOnlyList<HashLifeSnapshot> frames, JsonElement entries)
        {
            int i = 0;
            foreach (JsonElement entry in entries.EnumerateArray())
            {
                Assert.True(i < frames.Count, "fewer frames than the case pins");
                universe.Restore(frames[i++]);
                ExpectState(dir, universe, entry);
            }
            Assert.Equal(frames.Count, i);
        }

        public static IEnumerable<object[]> UniverseCases()
        {
            foreach (object[] c in Cases())
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, (string)c[0], "params.json")));
                if (doc.RootElement.GetProperty("kind").GetString() == "universe")
                    yield return c;
            }
        }

        /// <summary>
        /// spec/formats.md "Reading into a universe that exists": every universe case's file, read
        /// into a universe that already holds a state and a snapshot, is accepted or refused as the
        /// case says, restores to the case's states, and leaves that universe as it was.
        /// </summary>
        [Theory]
        [MemberData(nameof(UniverseCases))]
        public void ReadSnapshotReadsAsTheUniverseCase(string caseName)
        {
            string dir = Path.Combine(Root, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            JsonElement root = doc.RootElement;
            byte[] data = File.ReadAllBytes(Path.Combine(dir, root.GetProperty("input").GetString()!));
            var host = new HashLife("B36/S23");
            host.SetRect(3, -2, new byte[] { 0, 1, 0, 0, 0, 1, 1, 1, 1 }, 3, 3);
            host.Step(7);
            HashLifeSnapshot kept = host.Snapshot();
            host.Step(5);
            var before = (host.ToMacrocell(), host.Generation, host.Rule);
            if (root.TryGetProperty("error", out JsonElement flag) && flag.GetBoolean())
            {
                Refused(() => host.ReadSnapshot(data));
                Assert.Equal(before, (host.ToMacrocell(), host.Generation, host.Rule));
                return;
            }
            PatternSnapshot found = host.ReadSnapshot(data);
            Assert.Equal(before, (host.ToMacrocell(), host.Generation, host.Rule));
            Assert.Equal(root.GetProperty("format").GetString(), PatternFiles.FormatName(found.Format));
            Assert.Equal(Metadata(root.GetProperty("metadata")), found.Metadata);
            Assert.Equal(
                root.TryGetProperty("step", out JsonElement step) ? BigInteger.Parse(step.GetString()!) : (BigInteger?)null,
                found.Step);
            host.Rule = found.Rule; // the case's states carry the file's rule
            host.Restore(found.Snapshot);
            ExpectState(dir, host, root);
            if (root.TryGetProperty("frames", out JsonElement frames))
                ExpectFrames(dir, host, found.Frames, frames);
            else
                Assert.Empty(found.Frames);
            host.Restore(kept); // a snapshot taken before the read still restores
            Assert.Equal(7, (int)host.Generation);
        }
    }
}
