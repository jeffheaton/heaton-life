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
    /// Multi-state HashLife conformance: replay vectors/hashlife-multistate/ — Wireworld grids run
    /// on the plane beside the grid family, evolution from files, Macrocell and RLE reading and
    /// canonical writing, edits with states, frames under a zoom order, snapshot scripts and
    /// timelines (spec/hashlife-multistate.md "Vector encoding"). Every state is compared through
    /// its canonical Macrocell text. As strict as the Python runner
    /// (python/tests/test_hashlife_multistate_vectors.py): an unknown key, kind, op, or
    /// spec_version fails the case.
    /// </summary>
    public class MultiStateHashLifeConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.16.0" };
        private const string Digits = "0123456789abcdefghijklmnopqrstuvwxyz";

        private static readonly Dictionary<string, HashSet<string>> Keys = BuildKeys();

        private static Dictionary<string, HashSet<string>> BuildKeys()
        {
            string[] common = { "spec_version", "family", "tier", "kind" };
            string[] state = { "generation", "population", "bounding_box", "state", "state_sha256", "state_lines" };
            HashSet<string> Of(params string[][] groups) => new HashSet<string>(groups.SelectMany(g => g));
            return new Dictionary<string, HashSet<string>>
            {
                ["evolve"] = Of(common, new[] { "input", "checkpoints" }),
                ["grid"] = Of(common, new[] { "rule", "grid", "origin", "checkpoints" }),
                ["macrocell"] = Of(common, new[] { "input", "rule", "error", "rle", "rle_error" }, state),
                ["rle"] = Of(common, new[] { "input", "rule", "error", "rle", "rle_error" }, state),
                ["edit"] = Of(common, new[] { "rule", "ops" }, state),
                ["render"] = Of(common, new[] { "input", "generation", "frames" }),
                ["snapshots"] = Of(common, new[] { "rule", "ops" }, state),
                ["timeline"] = Of(common, new[] { "input", "generations", "metadata", "timeline", "frames" }),
            };
        }

        private static readonly HashSet<string> StateKeys = new HashSet<string>
        {
            "generation", "population", "bounding_box", "state", "state_sha256", "state_lines",
        };

        private static readonly Dictionary<string, HashSet<string>> EditOps = new Dictionary<string, HashSet<string>>
        {
            ["set_cell"] = new HashSet<string> { "x", "y", "state" },
            ["set_rect"] = new HashSet<string> { "x", "y", "mode", "cells" },
            ["clear_rect"] = new HashSet<string> { "x0", "y0", "x1", "y1" },
            ["clear_outside"] = new HashSet<string> { "x0", "y0", "x1", "y1" },
            ["rotate_rect"] = new HashSet<string> { "x0", "y0", "x1", "y1", "clockwise", "expect" },
            ["flip_rect"] = new HashSet<string> { "x0", "y0", "x1", "y1", "horizontal" },
            ["advance_selection"] = new HashSet<string> { "x0", "y0", "x1", "y1", "n" },
            ["advance_outside"] = new HashSet<string> { "x0", "y0", "x1", "y1", "n" },
            ["set_generation"] = new HashSet<string> { "n" },
            ["step"] = new HashSet<string> { "n" },
            ["clear"] = new HashSet<string>(),
            ["set_rule"] = new HashSet<string> { "rule" },
            ["fill_random"] = new HashSet<string> { "x0", "y0", "x1", "y1", "density", "seed" },
            ["get_rect"] = new HashSet<string> { "x0", "y0", "x1", "y1", "expect" },
            ["bounding_box_in"] = new HashSet<string> { "x0", "y0", "x1", "y1", "expect" },
        };

        private static readonly Dictionary<string, HashSet<string>> SnapshotOps = new Dictionary<string, HashSet<string>>
        {
            ["snapshot"] = new HashSet<string> { "name" },
            ["release"] = new HashSet<string> { "name" },
            ["restore"] = new HashSet<string> { "name", "expect" },
            ["read"] = new HashSet<string> { "input", "name", "frames", "expect" },
            ["measure"] = new HashSet<string> { "names", "expect" },
        };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "hashlife-multistate");

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

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string dir = Path.Combine(Root, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json")));
            JsonElement meta = doc.RootElement;
            string kind = meta.GetProperty("kind").GetString()!;
            Assert.Equal("hashlife-multistate", meta.GetProperty("family").GetString());
            Assert.Equal("bit-exact", meta.GetProperty("tier").GetString());
            Assert.Contains(meta.GetProperty("spec_version").GetString(), SpecVersions);
            Assert.True(Keys.ContainsKey(kind), $"unknown kind {kind}");
            foreach (JsonProperty property in meta.EnumerateObject())
                Assert.True(Keys[kind].Contains(property.Name), $"unknown key {property.Name}");

            switch (kind)
            {
                case "evolve":
                    {
                        MultiStateHashLife u = MultiStateHashLife.Load(File.ReadAllBytes(Path.Combine(dir, Text(meta, "input"))));
                        foreach (JsonElement entry in meta.GetProperty("checkpoints").EnumerateArray())
                        {
                            foreach (JsonProperty property in entry.EnumerateObject())
                                Assert.Contains(property.Name, StateKeys);
                            u.Step(BigInteger.Parse(Text(entry, "generation")) - u.Generation);
                            ExpectState(dir, u, entry);
                        }
                        break;
                    }
                case "grid":
                    {
                        // A History rule's grid is Life-like, its PNGs the states themselves
                        // (spec/history.md); Wireworld's are states × 85.
                        string ruleName = Text(meta, "rule");
                        bool history = RuleString.TryCompile(ruleName, true, out LifeRule? life, out _)
                            && life.Variant == RuleVariant.History;
                        int scale = history ? 1 : 85;
                        var (width, height, grid) = StatesPng(Path.Combine(dir, Text(meta, "grid")), scale);
                        long x = long.Parse(meta.GetProperty("origin")[0].GetString()!);
                        long y = long.Parse(meta.GetProperty("origin")[1].GetString()!);
                        var u = new MultiStateHashLife(ruleName);
                        u.SetRect(x, y, grid, width, height);
                        Wireworld? wire = history ? null : new Wireworld(width, height, grid);
                        LifeLike? lifeLike = null;
                        if (history)
                        {
                            lifeLike = new LifeLike(ruleName, width, height, Boundary.Dead);
                            lifeLike.SetState(grid);
                        }
                        foreach (JsonElement entry in meta.GetProperty("checkpoints").EnumerateArray())
                        {
                            foreach (JsonProperty property in entry.EnumerateObject())
                                Assert.True(StateKeys.Contains(property.Name) || property.Name == "cells", property.Name);
                            BigInteger gen = BigInteger.Parse(Text(entry, "generation"));
                            u.Step(gen - u.Generation);
                            if (wire != null)
                                wire.Step((int)gen - wire.Generation);
                            else
                                lifeLike!.Step((int)gen - lifeLike.Generation);
                            ExpectState(dir, u, entry);
                            byte[] cells = StatesPng(Path.Combine(dir, Text(entry, "cells")), scale).Cells;
                            ReadOnlySpan<byte> gridState = wire != null ? wire.State : lifeLike!.State;
                            Assert.True(gridState.SequenceEqual(cells), $"{caseName}: the grid family at {gen}");
                            Assert.True(
                                u.GetRect(x, y, x + width - 1, y + height - 1).AsSpan().SequenceEqual(cells),
                                $"{caseName}: the plane under the grid at {gen}");
                            Assert.Equal(cells.Count(c => c != 0), (int)u.Population); // nothing outside it
                        }
                        break;
                    }
                case "macrocell":
                case "rle":
                    {
                        string text = File.ReadAllText(Path.Combine(dir, Text(meta, "input")));
                        StateRule? rule = meta.TryGetProperty("rule", out JsonElement named) ? StateRules.Compile(named.GetString()!) : null;
                        Func<string, MultiStateHashLife> read = kind == "macrocell"
                            ? t => MultiStateHashLife.FromMacrocell(t, rule)
                            : t => MultiStateHashLife.FromRle(t, rule);
                        if (meta.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                        {
                            Exception e = Assert.ThrowsAny<Exception>(() => read(text));
                            Assert.True(e is FormatException || e is ArgumentException, e.ToString());
                            return;
                        }
                        MultiStateHashLife u = read(text);
                        ExpectState(dir, u, meta);
                        if (meta.TryGetProperty("rle_error", out JsonElement rleError) && rleError.GetBoolean())
                        {
                            var refused = Assert.Throws<InvalidOperationException>(() => u.ToRle());
                            Assert.Contains("Macrocell", refused.Message);
                        }
                        else
                        {
                            Assert.Equal(File.ReadAllText(Path.Combine(dir, Text(meta, "rle"))), u.ToRle());
                        }
                        break;
                    }
                case "render":
                    {
                        MultiStateHashLife u = MultiStateHashLife.Load(File.ReadAllBytes(Path.Combine(dir, Text(meta, "input"))));
                        u.Step(BigInteger.Parse(Text(meta, "generation")) - u.Generation);
                        foreach (JsonElement frame in meta.GetProperty("frames").EnumerateArray())
                        {
                            Assert.Equal(
                                new[] { "file", "mode", "order", "size", "view" },
                                frame.EnumerateObject().Select(p => p.Name).OrderBy(n => n, StringComparer.Ordinal).ToArray());
                            u.ZoomOrder = frame.GetProperty("order").EnumerateArray().Select(v => (byte)v.GetInt32()).ToArray();
                            JsonElement size = frame.GetProperty("size");
                            int width = size[0].GetInt32(), height = size[1].GetInt32();
                            var mode = Text(frame, "mode") switch
                            {
                                "state" => MultiStateRenderMode.State,
                                "density" => MultiStateRenderMode.Density,
                                var other => throw new InvalidDataException($"unknown render mode {other}"),
                            };
                            JsonElement view = frame.GetProperty("view");
                            var at = new LifeView(BigInteger.Parse(view[0].GetString()!), BigInteger.Parse(view[1].GetString()!), view[2].GetInt32());
                            byte[] got = u.Frame(width, height, at, mode);
                            var (w, h, channels, pixels) = Png.Read(Path.Combine(dir, Text(frame, "file")));
                            Assert.Equal((width, height, 1), (w, h, channels));
                            Assert.True(pixels.AsSpan().SequenceEqual(got), $"{caseName}: {frame}");
                        }
                        break;
                    }
                case "edit":
                case "snapshots":
                    {
                        var u = new MultiStateHashLife(Text(meta, "rule"));
                        var named = new Dictionary<string, HashLifeSnapshot>();
                        foreach (JsonElement op in meta.GetProperty("ops").EnumerateArray())
                        {
                            if (op.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                            {
                                var before = (u.ToMacrocell(), u.Generation, u.Rule);
                                Exception e = Assert.ThrowsAny<Exception>(() => Op(dir, u, named, op, kind == "snapshots"));
                                Assert.True(
                                    e is ArgumentException || e is FormatException || e is InvalidOperationException, e.ToString());
                                Assert.Equal(before, (u.ToMacrocell(), u.Generation, u.Rule));
                            }
                            else
                            {
                                Op(dir, u, named, op, kind == "snapshots");
                            }
                        }
                        ExpectState(dir, u, meta);
                        break;
                    }
                case "timeline":
                    {
                        MultiStateHashLife u = MultiStateHashLife.Load(File.ReadAllBytes(Path.Combine(dir, Text(meta, "input"))));
                        var frames = new List<HashLifeSnapshot>();
                        foreach (JsonElement generation in meta.GetProperty("generations").EnumerateArray())
                        {
                            u.Step(BigInteger.Parse(generation.GetString()!) - u.Generation);
                            frames.Add(u.Snapshot());
                        }
                        PatternMetadata metadata = Metadata(meta.GetProperty("metadata"));
                        string text = MultiStateMacrocell.WriteTimeline(u, frames, metadata);
                        Assert.Equal(File.ReadAllText(Path.Combine(dir, Text(meta, "timeline"))), text);
                        MultiStateTimeline back = MultiStateMacrocell.ReadTimeline(text);
                        Assert.Equal(metadata, back.Metadata);
                        JsonElement[] expected = meta.GetProperty("frames").EnumerateArray().ToArray();
                        Assert.Equal(expected.Length, back.Frames.Count);
                        for (int i = 0; i < expected.Length; i++)
                        {
                            back.Universe.Restore(back.Frames[i]);
                            ExpectState(dir, back.Universe, expected[i]);
                        }
                        break;
                    }
                default:
                    throw new InvalidDataException($"unknown kind {kind}");
            }
        }

        private static string Text(JsonElement element, string key) => element.GetProperty(key).GetString()!;

        private static long Long(JsonElement op, string key) => op.GetProperty(key).GetInt64();

        private static PatternMetadata Metadata(JsonElement notes)
        {
            string? Field(string key) => notes.GetProperty(key).ValueKind == JsonValueKind.Null ? null : notes.GetProperty(key).GetString();
            return new PatternMetadata(
                Field("name"), Field("author"), notes.GetProperty("comments").EnumerateArray().Select(c => c.GetString()!).ToArray());
        }

        /// <summary>A grid stored as the wireworld vectors store one, states × 85, or, with a
        /// <paramref name="scale"/> of 1, as the lifelike-history vectors store one.</summary>
        private static (int Width, int Height, byte[] Cells) StatesPng(string path, int scale = 85)
        {
            var (width, height, channels, pixels) = Png.Read(path);
            Assert.Equal(1, channels);
            return (width, height, pixels.Select(p => (byte)(p / scale)).ToArray());
        }

        private static (byte[] Cells, int Width, int Height) Cells(JsonElement rows)
        {
            string[] lines = rows.EnumerateArray().Select(r => r.GetString()!).ToArray();
            int width = lines[0].Length;
            var cells = new byte[lines.Length * width];
            for (int y = 0; y < lines.Length; y++)
                for (int x = 0; x < width; x++)
                    cells[y * width + x] = (byte)Digits.IndexOf(lines[y][x]);
            return (cells, width, lines.Length);
        }

        /// <summary>A state pinned by generation, population, bounding box, and canonical text.</summary>
        private static void ExpectState(string dir, MultiStateHashLife u, JsonElement entry)
        {
            Assert.Equal(Text(entry, "generation"), u.Generation.ToString());
            Assert.Equal(Text(entry, "population"), u.Population.ToString());
            JsonElement box = entry.GetProperty("bounding_box");
            CellBox? got = u.BoundingBox;
            if (box.ValueKind == JsonValueKind.Null)
            {
                Assert.Null(got);
            }
            else
            {
                Assert.NotNull(got);
                CellBox b = got!.Value;
                Assert.Equal(
                    box.EnumerateArray().Select(v => v.GetString()).ToArray(),
                    new[] { b.X0, b.Y0, b.X1, b.Y1 }.Select(v => v.ToString()).ToArray());
            }
            string text = u.ToMacrocell();
            if (entry.TryGetProperty("state", out JsonElement state))
            {
                Assert.Equal(File.ReadAllText(Path.Combine(dir, state.GetString()!)), text);
            }
            else
            {
                Assert.Equal(entry.GetProperty("state_lines").GetInt32(), text.Count(c => c == '\n'));
                string digest = Convert.ToHexString(SHA256.HashData(Encoding.ASCII.GetBytes(text))).ToLowerInvariant();
                Assert.Equal(Text(entry, "state_sha256"), digest);
            }
        }

        private static void Op(
            string dir, MultiStateHashLife u, Dictionary<string, HashLifeSnapshot> named, JsonElement op, bool snapshots)
        {
            string kind = Text(op, "op");
            if (snapshots && SnapshotOps.TryGetValue(kind, out HashSet<string>? allowed))
            {
                foreach (JsonProperty property in op.EnumerateObject())
                    Assert.True(property.Name == "op" || property.Name == "error" || allowed.Contains(property.Name), property.Name);
                SnapshotOp(dir, u, named, op, kind);
                return;
            }
            Assert.True(EditOps.ContainsKey(kind), $"unknown op {kind}");
            foreach (JsonProperty property in op.EnumerateObject())
                Assert.True(property.Name == "op" || property.Name == "error" || EditOps[kind].Contains(property.Name), property.Name);
            switch (kind)
            {
                case "set_cell":
                    u.SetCell(Long(op, "x"), Long(op, "y"), checked((byte)op.GetProperty("state").GetInt32()));
                    break;
                case "set_rect":
                    {
                        var (cells, width, height) = Cells(op.GetProperty("cells"));
                        var mode = Text(op, "mode") switch
                        {
                            "copy" => HashLifePasteMode.Copy,
                            "or" => HashLifePasteMode.Or,
                            "xor" => HashLifePasteMode.Xor,
                            "and" => HashLifePasteMode.And,
                            var other => throw new ArgumentException($"unknown paste mode {other}"),
                        };
                        u.SetRect(Long(op, "x"), Long(op, "y"), cells, width, height, mode);
                        break;
                    }
                case "clear_rect":
                    u.ClearRect(Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"));
                    break;
                case "clear_outside":
                    u.ClearOutside(Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"));
                    break;
                case "rotate_rect":
                    {
                        CellBox got = u.RotateRect(
                            Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"), op.GetProperty("clockwise").GetBoolean());
                        Assert.Equal(
                            op.GetProperty("expect").EnumerateArray().Select(v => v.GetInt64().ToString()).ToArray(),
                            new[] { got.X0, got.Y0, got.X1, got.Y1 }.Select(v => v.ToString()).ToArray());
                        break;
                    }
                case "flip_rect":
                    u.FlipRect(Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"), op.GetProperty("horizontal").GetBoolean());
                    break;
                case "advance_selection":
                    u.AdvanceSelection(Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"), BigInteger.Parse(Text(op, "n")));
                    break;
                case "advance_outside":
                    u.AdvanceOutside(Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"), BigInteger.Parse(Text(op, "n")));
                    break;
                case "set_generation":
                    u.SetGeneration(BigInteger.Parse(Text(op, "n")));
                    break;
                case "step":
                    u.Step(BigInteger.Parse(Text(op, "n")));
                    break;
                case "clear":
                    u.Clear();
                    break;
                case "set_rule":
                    u.Rule = Text(op, "rule");
                    break;
                case "fill_random": // History rules only (spec/hashlife-multistate.md "Editing")
                    u.FillRandom(
                        Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"),
                        op.GetProperty("density").GetDouble(), op.GetProperty("seed").GetUInt64());
                    break;
                case "get_rect":
                    {
                        long x0 = Long(op, "x0"), y0 = Long(op, "y0"), x1 = Long(op, "x1"), y1 = Long(op, "y1");
                        byte[] cells = u.GetRect(x0, y0, x1, y1);
                        int width = (int)(x1 - x0 + 1);
                        var rows = new List<string>();
                        for (int row = 0; row * width < cells.Length; row++)
                            rows.Add(new string(cells.Skip(row * width).Take(width).Select(c => Digits[c]).ToArray()));
                        Assert.Equal(op.GetProperty("expect").EnumerateArray().Select(r => r.GetString()).ToArray(), rows.ToArray());
                        break;
                    }
                default: // bounding_box_in
                    {
                        CellBox? found = u.BoundingBoxIn(
                            BigInteger.Parse(Text(op, "x0")), BigInteger.Parse(Text(op, "y0")),
                            BigInteger.Parse(Text(op, "x1")), BigInteger.Parse(Text(op, "y1")));
                        JsonElement expect = op.GetProperty("expect");
                        if (expect.ValueKind == JsonValueKind.Null)
                        {
                            Assert.Null(found);
                        }
                        else
                        {
                            Assert.NotNull(found);
                            CellBox b = found!.Value;
                            Assert.Equal(
                                expect.EnumerateArray().Select(v => v.GetString()).ToArray(),
                                new[] { b.X0, b.Y0, b.X1, b.Y1 }.Select(v => v.ToString()).ToArray());
                        }
                        break;
                    }
            }
        }

        private static void SnapshotOp(
            string dir, MultiStateHashLife u, Dictionary<string, HashLifeSnapshot> named, JsonElement op, string kind)
        {
            switch (kind)
            {
                case "snapshot":
                    named[Text(op, "name")] = u.Snapshot();
                    break;
                case "release":
                    named[Text(op, "name")].Release();
                    break;
                case "restore":
                    u.Restore(named[Text(op, "name")]);
                    ExpectState(dir, u, op.GetProperty("expect"));
                    break;
                case "read":
                    {
                        var before = (u.ToMacrocell(), u.Generation, u.Rule);
                        PatternSnapshot found = u.ReadSnapshot(File.ReadAllBytes(Path.Combine(dir, Text(op, "input"))));
                        Assert.Equal(before, (u.ToMacrocell(), u.Generation, u.Rule)); // a read never moves it
                        JsonElement expect = op.GetProperty("expect");
                        Assert.Equal(Text(expect, "format"), PatternFiles.FormatName(found.Format));
                        Assert.Equal(Text(expect, "rule"), found.Rule);
                        Assert.Equal(Metadata(expect.GetProperty("metadata")), found.Metadata);
                        JsonElement step = expect.GetProperty("step");
                        Assert.Equal(step.ValueKind == JsonValueKind.Null ? null : step.GetString(), found.Step?.ToString());
                        named[Text(op, "name")] = found.Snapshot;
                        string[] frames = op.GetProperty("frames").EnumerateArray().Select(f => f.GetString()!).ToArray();
                        Assert.Equal(frames.Length, found.Frames.Count);
                        for (int i = 0; i < frames.Length; i++)
                            named[frames[i]] = found.Frames[i];
                        break;
                    }
                default: // measure
                    {
                        SnapshotFootprint footprint = u.MeasureSnapshots(
                            op.GetProperty("names").EnumerateArray().Select(n => named[n.GetString()!]));
                        JsonElement expect = op.GetProperty("expect");
                        Assert.Equal(expect.GetProperty("universe_nodes").GetInt64(), footprint.UniverseNodes);
                        Assert.Equal(expect.GetProperty("added").EnumerateArray().Select(v => v.GetInt64()).ToArray(), footprint.Added.ToArray());
                        Assert.Equal(expect.GetProperty("nodes").GetInt64(), footprint.Nodes);
                        break;
                    }
            }
        }
    }
}
