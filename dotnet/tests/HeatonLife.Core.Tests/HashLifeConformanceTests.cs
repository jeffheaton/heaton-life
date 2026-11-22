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
    /// HashLife conformance: replay vectors/hashlife/ — evolution checkpoints, Macrocell and RLE
    /// reading and canonical writing, edit sequences, view arithmetic, rendered frames, and
    /// snapshot scripts: what snapshots hold, releasing them, files read into a universe that
    /// exists (spec/hashlife.md "Vector encoding"). Every state is compared through its canonical
    /// Macrocell text, byte for byte or by SHA-256 and line count. As strict as the Python
    /// runner (python/tests/test_hashlife_vectors.py): an unknown key, kind, or spec_version
    /// fails the case.
    /// </summary>
    public class HashLifeConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.14.0", "0.15.0", "0.16.0" };

        private static readonly Dictionary<string, HashSet<string>> Keys = BuildKeys();

        private static Dictionary<string, HashSet<string>> BuildKeys()
        {
            string[] common = { "spec_version", "family", "tier", "kind" };
            string[] state = { "generation", "population", "bounding_box", "background" }; // background: B0 rules
            string[] stored = { "state", "state_sha256", "state_lines" };
            HashSet<string> Of(params string[][] groups) => new HashSet<string>(groups.SelectMany(g => g));
            return new Dictionary<string, HashSet<string>>
            {
                ["evolve"] = Of(common, new[] { "input", "checkpoints" }),
                ["macrocell"] = Of(common, new[] { "input", "error", "rle", "rle_error" }, stored, state),
                ["rle"] = Of(common, new[] { "input", "error", "rle" }, stored, state),
                ["edit"] = Of(common, new[] { "rule", "ops" }, stored, state),
                ["view"] = Of(common, new[] { "operations" }),
                ["render"] = Of(common, new[] { "input", "generation", "frames" }),
                ["snapshots"] = Of(common, new[] { "rule", "ops" }, stored, state),
            };
        }

        /// <summary>A snapshot script's own ops (spec 0.16.0); its other ops are the edit ops.</summary>
        private static readonly Dictionary<string, HashSet<string>> SnapshotOps = new Dictionary<string, HashSet<string>>
        {
            ["snapshot"] = new HashSet<string> { "op", "name" },
            ["release"] = new HashSet<string> { "op", "name" },
            ["restore"] = new HashSet<string> { "op", "name", "expect", "error" },
            ["read"] = new HashSet<string> { "op", "input", "name", "frames", "expect", "error" },
            ["measure"] = new HashSet<string> { "op", "names", "expect" },
        };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "hashlife");

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
            Assert.Equal("hashlife", meta.GetProperty("family").GetString());
            Assert.Equal("bit-exact", meta.GetProperty("tier").GetString());
            Assert.Contains(meta.GetProperty("spec_version").GetString(), SpecVersions);
            Assert.True(Keys.ContainsKey(kind), $"unknown kind {kind}");
            foreach (JsonProperty property in meta.EnumerateObject())
                Assert.True(Keys[kind].Contains(property.Name), $"unknown key {property.Name}");

            switch (kind)
            {
                case "evolve":
                    {
                        HashLife u = HashLife.Load(File.ReadAllBytes(Path.Combine(dir, meta.GetProperty("input").GetString()!)));
                        foreach (JsonElement entry in meta.GetProperty("checkpoints").EnumerateArray())
                        {
                            u.Step(BigInteger.Parse(entry.GetProperty("generation").GetString()!) - u.Generation);
                            ExpectState(dir, u, entry);
                        }
                        break;
                    }
                case "macrocell":
                case "rle":
                    {
                        string text = File.ReadAllText(Path.Combine(dir, meta.GetProperty("input").GetString()!));
                        Func<string, HashLife> read = kind == "macrocell"
                            ? t => HashLife.FromMacrocell(t)
                            : t => HashLife.FromRle(t);
                        if (meta.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                        {
                            Exception e = Assert.ThrowsAny<Exception>(() => read(text));
                            Assert.True(e is FormatException || e is ArgumentException, e.ToString());
                            return;
                        }
                        HashLife u = read(text);
                        ExpectState(dir, u, meta);
                        if (meta.TryGetProperty("rle_error", out JsonElement rleError) && rleError.GetBoolean())
                        {
                            var refused = Assert.Throws<InvalidOperationException>(() => u.ToRle());
                            Assert.Contains("Macrocell", refused.Message);
                        }
                        else
                        {
                            Assert.Equal(File.ReadAllText(Path.Combine(dir, meta.GetProperty("rle").GetString()!)), u.ToRle());
                        }
                        break;
                    }
                case "view":
                    foreach (JsonElement op in meta.GetProperty("operations").EnumerateArray())
                        CheckViewOp(op);
                    break;
                case "render":
                    {
                        HashLife u = HashLife.Load(File.ReadAllBytes(Path.Combine(dir, meta.GetProperty("input").GetString()!)));
                        u.Step(BigInteger.Parse(meta.GetProperty("generation").GetString()!) - u.Generation);
                        foreach (JsonElement frame in meta.GetProperty("frames").EnumerateArray())
                        {
                            JsonElement size = frame.GetProperty("size");
                            int width = size[0].GetInt32(), height = size[1].GetInt32();
                            var mode = frame.GetProperty("mode").GetString() switch
                            {
                                "any" => HashLifeRenderMode.Any,
                                "density" => HashLifeRenderMode.Density,
                                var other => throw new InvalidDataException($"unknown render mode {other}"),
                            };
                            byte[] got = u.Frame(width, height, View(frame.GetProperty("view")), mode);
                            var (w, h, channels, pixels) = Png.Read(Path.Combine(dir, frame.GetProperty("file").GetString()!));
                            Assert.Equal((width, height, 1), (w, h, channels));
                            Assert.True(pixels.AsSpan().SequenceEqual(got), $"{caseName}: {frame}");
                        }
                        break;
                    }
                case "edit":
                    {
                        var u = new HashLife(meta.GetProperty("rule").GetString()!);
                        foreach (JsonElement op in meta.GetProperty("ops").EnumerateArray())
                        {
                            if (op.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                            {
                                (string, BigInteger) before = (u.ToMacrocell(), u.Generation);
                                Exception e = Assert.ThrowsAny<Exception>(() => Apply(u, op));
                                Assert.True(e is ArgumentException || e is InvalidOperationException, e.ToString());
                                Assert.Equal(before, (u.ToMacrocell(), u.Generation));
                            }
                            else
                            {
                                Apply(u, op);
                            }
                        }
                        ExpectState(dir, u, meta);
                        break;
                    }
                case "snapshots":
                    {
                        var u = new HashLife(meta.GetProperty("rule").GetString()!);
                        var named = new Dictionary<string, HashLifeSnapshot>();
                        foreach (JsonElement op in meta.GetProperty("ops").EnumerateArray())
                        {
                            if (op.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                            {
                                var before = (u.ToMacrocell(), u.Generation, u.Rule);
                                Exception e = Assert.ThrowsAny<Exception>(() => SnapshotOp(dir, u, named, op));
                                Assert.True(
                                    e is ArgumentException || e is FormatException || e is InvalidOperationException, e.ToString());
                                Assert.Equal(before, (u.ToMacrocell(), u.Generation, u.Rule));
                            }
                            else
                            {
                                SnapshotOp(dir, u, named, op);
                            }
                        }
                        ExpectState(dir, u, meta);
                        break;
                    }
                default:
                    throw new InvalidDataException($"unknown kind {kind}");
            }
        }

        /// <summary>A state pinned by generation, population, bounding box, and canonical text; a
        /// state of a rule with B0 by its background too (spec 0.16.0).</summary>
        internal static void ExpectState(string dir, HashLife u, JsonElement entry)
        {
            Assert.Equal(entry.GetProperty("generation").GetString(), u.Generation.ToString());
            Assert.Equal(entry.GetProperty("population").GetString(), u.Population.ToString());
            if (entry.TryGetProperty("background", out JsonElement background))
                Assert.Equal(background.GetInt32() == 1, u.BackgroundAlive);
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
                Assert.Equal(entry.GetProperty("state_sha256").GetString(), digest);
            }
        }

        private static void Apply(HashLife u, JsonElement op)
        {
            switch (op.GetProperty("op").GetString())
            {
                case "set_cell":
                    u.SetCell(op.GetProperty("x").GetInt64(), op.GetProperty("y").GetInt64(), op.GetProperty("alive").GetBoolean());
                    break;
                case "set_rect":
                    {
                        string[] rows = op.GetProperty("cells").EnumerateArray().Select(r => r.GetString()!).ToArray();
                        int width = rows[0].Length;
                        var cells = new byte[rows.Length * width];
                        for (int y = 0; y < rows.Length; y++)
                            for (int x = 0; x < width; x++)
                                cells[y * width + x] = (byte)(rows[y][x] == '*' ? 1 : 0);
                        var mode = op.GetProperty("mode").GetString() switch
                        {
                            "copy" => HashLifePasteMode.Copy,
                            "or" => HashLifePasteMode.Or,
                            "xor" => HashLifePasteMode.Xor,
                            "and" => HashLifePasteMode.And, // spec 0.16.0 on
                            var other => throw new InvalidDataException($"unknown paste mode {other}"),
                        };
                        u.SetRect(op.GetProperty("x").GetInt64(), op.GetProperty("y").GetInt64(), cells, width, rows.Length, mode);
                        break;
                    }
                case "clear_rect":
                    u.ClearRect(
                        op.GetProperty("x0").GetInt64(), op.GetProperty("y0").GetInt64(),
                        op.GetProperty("x1").GetInt64(), op.GetProperty("y1").GetInt64());
                    break;
                case "fill_random":
                    u.FillRandom(
                        op.GetProperty("x0").GetInt64(), op.GetProperty("y0").GetInt64(),
                        op.GetProperty("x1").GetInt64(), op.GetProperty("y1").GetInt64(),
                        op.GetProperty("density").GetDouble(), op.GetProperty("seed").GetUInt64());
                    break;
                case "step":
                    u.Step(BigInteger.Parse(op.GetProperty("n").GetString()!));
                    break;
                case "clear":
                    u.Clear();
                    break;
                case "clear_outside": // spec 0.16.0 on
                    u.ClearOutside(Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"));
                    break;
                case "rotate_rect":
                    {
                        CellBox got = u.RotateRect(
                            Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"),
                            op.GetProperty("clockwise").GetBoolean());
                        Assert.Equal(
                            op.GetProperty("expect").EnumerateArray().Select(v => v.GetInt64().ToString()).ToArray(),
                            new[] { got.X0, got.Y0, got.X1, got.Y1 }.Select(v => v.ToString()).ToArray());
                        break;
                    }
                case "flip_rect":
                    u.FlipRect(
                        Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"),
                        op.GetProperty("horizontal").GetBoolean());
                    break;
                case "advance_selection":
                    u.AdvanceSelection(
                        Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"),
                        BigInteger.Parse(op.GetProperty("n").GetString()!));
                    break;
                case "advance_outside":
                    u.AdvanceOutside(
                        Long(op, "x0"), Long(op, "y0"), Long(op, "x1"), Long(op, "y1"),
                        BigInteger.Parse(op.GetProperty("n").GetString()!));
                    break;
                case "set_generation":
                    u.SetGeneration(BigInteger.Parse(op.GetProperty("n").GetString()!));
                    break;
                case "set_rule": // spec 0.16.0: the universe's new rule keeps its cells
                    u.Rule = op.GetProperty("rule").GetString()!;
                    break;
                case "bounding_box_in":
                    {
                        CellBox? box = u.BoundingBoxIn(
                            Big(op.GetProperty("x0")), Big(op.GetProperty("y0")),
                            Big(op.GetProperty("x1")), Big(op.GetProperty("y1")));
                        JsonElement expect = op.GetProperty("expect");
                        if (expect.ValueKind == JsonValueKind.Null)
                        {
                            Assert.Null(box);
                        }
                        else
                        {
                            Assert.NotNull(box);
                            CellBox b = box!.Value;
                            Assert.Equal(
                                expect.EnumerateArray().Select(v => v.GetString()).ToArray(),
                                new[] { b.X0, b.Y0, b.X1, b.Y1 }.Select(v => v.ToString()).ToArray());
                        }
                        break;
                    }
                default:
                    throw new InvalidDataException($"unknown op {op.GetProperty("op").GetString()}");
            }
        }

        /// <summary>One op of a snapshot script (spec/hashlife.md "Vector encoding", snapshots).</summary>
        private static void SnapshotOp(string dir, HashLife u, Dictionary<string, HashLifeSnapshot> named, JsonElement op)
        {
            string kind = op.GetProperty("op").GetString()!;
            if (!SnapshotOps.TryGetValue(kind, out HashSet<string>? keys))
            {
                Apply(u, op);
                return;
            }
            foreach (JsonProperty property in op.EnumerateObject())
                Assert.True(keys.Contains(property.Name), $"unknown key {property.Name} in {kind}");
            switch (kind)
            {
                case "snapshot":
                    named[op.GetProperty("name").GetString()!] = u.Snapshot();
                    break;
                case "release":
                    named[op.GetProperty("name").GetString()!].Release();
                    break;
                case "restore":
                    u.Restore(named[op.GetProperty("name").GetString()!]);
                    ExpectState(dir, u, op.GetProperty("expect"));
                    break;
                case "read":
                    {
                        var before = (u.ToMacrocell(), u.Generation, u.Rule);
                        PatternSnapshot found = u.ReadSnapshot(File.ReadAllBytes(Path.Combine(dir, op.GetProperty("input").GetString()!)));
                        Assert.Equal(before, (u.ToMacrocell(), u.Generation, u.Rule)); // a read never moves it
                        JsonElement expect = op.GetProperty("expect");
                        Assert.Equal(expect.GetProperty("format").GetString(), PatternFiles.FormatName(found.Format));
                        Assert.Equal(expect.GetProperty("rule").GetString(), found.Rule);
                        Assert.Equal(FormatConformanceTests.Metadata(expect.GetProperty("metadata")), found.Metadata);
                        JsonElement step = expect.GetProperty("step");
                        Assert.Equal(step.ValueKind == JsonValueKind.Null ? null : step.GetString(), found.Step?.ToString());
                        named[op.GetProperty("name").GetString()!] = found.Snapshot;
                        string[] frames = op.GetProperty("frames").EnumerateArray().Select(f => f.GetString()!).ToArray();
                        Assert.Equal(frames.Length, found.Frames.Count);
                        for (int i = 0; i < frames.Length; i++)
                            named[frames[i]] = found.Frames[i];
                        break;
                    }
                default: // measure
                    {
                        var listed = op.GetProperty("names").EnumerateArray().Select(n => named[n.GetString()!]).ToList();
                        SnapshotFootprint footprint = u.MeasureSnapshots(listed);
                        JsonElement expect = op.GetProperty("expect");
                        Assert.Equal(expect.GetProperty("universe_nodes").GetInt64(), footprint.UniverseNodes);
                        Assert.Equal(
                            expect.GetProperty("added").EnumerateArray().Select(a => a.GetInt64()).ToArray(),
                            footprint.Added.ToArray());
                        Assert.Equal(expect.GetProperty("nodes").GetInt64(), footprint.Nodes);
                        Assert.Equal(footprint.Nodes * 40, footprint.EstimatedBytes);
                        break;
                    }
            }
        }

        private static long Long(JsonElement op, string key) => op.GetProperty(key).GetInt64();

        private static BigInteger Big(JsonElement value)
            => value.ValueKind == JsonValueKind.String ? BigInteger.Parse(value.GetString()!) : value.GetInt64();

        private static LifeView View(JsonElement fields) => new LifeView(Big(fields[0]), Big(fields[1]), fields[2].GetInt32());

        private static void CheckViewOp(JsonElement op)
        {
            if (op.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
            {
                Assert.ThrowsAny<ArgumentException>(() => ViewResult(op));
                return;
            }
            BigInteger[] want = op.GetProperty("expect").EnumerateArray().Select(Big).ToArray();
            BigInteger[] got = ViewResult(op);
            Assert.True(want.SequenceEqual(got), $"{op}: got [{string.Join(", ", got)}]");
        }

        private static BigInteger[] ViewResult(JsonElement op)
        {
            BigInteger[] got;
            switch (op.GetProperty("op").GetString())
            {
                case "pan":
                    got = Parts(LifeView.Pan(View(op.GetProperty("view")), op.GetProperty("dx").GetInt64(), op.GetProperty("dy").GetInt64()));
                    break;
                case "zoom_at":
                    got = Parts(LifeView.ZoomAt(
                        View(op.GetProperty("view")), op.GetProperty("i").GetInt64(), op.GetProperty("j").GetInt64(),
                        op.GetProperty("steps").GetInt32()));
                    break;
                case "cell_at":
                    {
                        var (x, y) = LifeView.CellAt(View(op.GetProperty("view")), op.GetProperty("i").GetInt64(), op.GetProperty("j").GetInt64());
                        got = new[] { x, y };
                        break;
                    }
                case "center_cell":
                    {
                        JsonElement size = op.GetProperty("size");
                        var (x, y) = LifeView.CenterCell(View(op.GetProperty("view")), size[0].GetInt64(), size[1].GetInt64());
                        got = new[] { x, y };
                        break;
                    }
                case "centered":
                    {
                        JsonElement cell = op.GetProperty("cell"), size = op.GetProperty("size");
                        got = Parts(LifeView.Centered(
                            Big(cell[0]), Big(cell[1]), op.GetProperty("mag").GetInt32(), size[0].GetInt64(), size[1].GetInt64()));
                        break;
                    }
                case "fit":
                    {
                        JsonElement box = op.GetProperty("box"), size = op.GetProperty("size");
                        CellBox? b = box.ValueKind == JsonValueKind.Null
                            ? (CellBox?)null
                            : new CellBox(Big(box[0]), Big(box[1]), Big(box[2]), Big(box[3]));
                        got = Parts(LifeView.Fit(b, size[0].GetInt64(), size[1].GetInt64()));
                        break;
                    }
                case "resized":
                    {
                        JsonElement old = op.GetProperty("old"), size = op.GetProperty("new");
                        got = Parts(LifeView.Resized(
                            View(op.GetProperty("view")), old[0].GetInt64(), old[1].GetInt64(),
                            size[0].GetInt64(), size[1].GetInt64()));
                        break;
                    }
                case "frame_map":
                    {
                        var (steps, dx, dy) = LifeView.FrameMap(View(op.GetProperty("frame")), View(op.GetProperty("view")));
                        got = new[] { new BigInteger(steps), dx, dy };
                        break;
                    }
                default:
                    throw new InvalidDataException($"unknown view op {op.GetProperty("op").GetString()}");
            }
            return got;
        }

        private static BigInteger[] Parts(LifeView view) => new[] { view.X, view.Y, new BigInteger(view.Mag) };
    }
}
