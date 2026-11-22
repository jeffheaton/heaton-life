using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Pattern conformance: replay vectors/patterns/ — RLE dialects with canonical
    /// re-encodes, the extent, the decode limit, trimmed decoding, transforms, extract
    /// and stamp semantics, region editing, and turned rectangles (spec/patterns.md).
    /// Bit-exact; the same files the Python suite replays.
    /// </summary>
    public class PatternConformanceTests
    {
        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "patterns")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), "patterns", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            switch (root.GetProperty("kind").GetString())
            {
                case "rle":
                    {
                        string input = File.ReadAllText(Path.Combine(caseDir, root.GetProperty("input").GetString()!));
                        RlePattern decoded = Patterns.RleDecode(input);
                        string? expectedRule = root.GetProperty("rule").ValueKind == JsonValueKind.Null
                            ? null
                            : root.GetProperty("rule").GetString();
                        Assert.Equal(expectedRule, decoded.Rule);
                        byte[] expectedGrid = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()!));
                        Assert.Equal(expectedGrid, decoded.Cells);
                        string canonical = Patterns.RleEncode(
                            decoded.Cells, decoded.Width, decoded.Height, decoded.Rule ?? "B3/S23");
                        Assert.Equal(
                            File.ReadAllText(Path.Combine(caseDir, root.GetProperty("canonical").GetString()!)),
                            canonical);
                        break;
                    }
                case "transform":
                    {
                        var shape = root.GetProperty("grid").GetProperty("shape");
                        int height = shape[0].GetInt32();
                        int width = shape[1].GetInt32();
                        byte[] grid = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()!));
                        var names = new HashSet<string>();
                        foreach (JsonProperty output in root.GetProperty("outputs").EnumerateObject())
                        {
                            names.Add(output.Name);
                            byte[] got = output.Name switch
                            {
                                "rotate90" => Patterns.Rotate90(grid, width, height),
                                "rotate90_ccw" => Patterns.Rotate90Ccw(grid, width, height),
                                "flip_h" => Patterns.FlipH(grid, width, height),
                                "flip_v" => Patterns.FlipV(grid, width, height),
                                _ => throw new InvalidDataException($"unknown transform {output.Name}"),
                            };
                            Assert.Equal(ReadGray(Path.Combine(caseDir, output.Value.GetString()!)), got);
                        }
                        Assert.Superset(new HashSet<string> { "rotate90", "flip_h", "flip_v" }, names);
                        break;
                    }
                case "stamp":
                    {
                        var patternShape = root.GetProperty("pattern").GetProperty("shape");
                        int patternHeight = patternShape[0].GetInt32();
                        int patternWidth = patternShape[1].GetInt32();
                        byte[] pattern = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("pattern").GetProperty("file").GetString()!));
                        int gridWidth, gridHeight;
                        byte[] grid;
                        if (root.TryGetProperty("grid", out JsonElement background))
                        {
                            // spec 0.16.0: a background grid instead of one value.
                            gridHeight = background.GetProperty("shape")[0].GetInt32();
                            gridWidth = background.GetProperty("shape")[1].GetInt32();
                            grid = ReadGray(Path.Combine(caseDir, background.GetProperty("file").GetString()!));
                        }
                        else
                        {
                            gridWidth = root.GetProperty("grid_width").GetInt32();
                            gridHeight = root.GetProperty("grid_height").GetInt32();
                            grid = new byte[gridWidth * gridHeight];
                            Array.Fill(grid, (byte)root.GetProperty("background").GetInt32());
                        }
                        int x = root.GetProperty("x").GetInt32(), y = root.GetProperty("y").GetInt32();
                        bool torus = root.GetProperty("torus").GetBoolean();
                        Action stamp;
                        if (root.TryGetProperty("mode", out JsonElement mode))
                        {
                            StampMode stampMode = mode.GetString() switch
                            {
                                "copy" => StampMode.Copy,
                                "or" => StampMode.Or,
                                "xor" => StampMode.Xor,
                                "and" => StampMode.And,
                                var other => throw new InvalidDataException($"unknown stamp mode {other}"),
                            };
                            stamp = () => Patterns.Stamp(
                                grid, gridWidth, gridHeight, 1, pattern, patternWidth, patternHeight, x, y, torus,
                                stampMode);
                        }
                        else
                        {
                            bool transparent = root.GetProperty("transparent").GetBoolean();
                            stamp = () => Patterns.Stamp(
                                grid, gridWidth, gridHeight, 1, pattern, patternWidth, patternHeight, x, y, torus,
                                transparent);
                        }
                        if (IsError(root))
                        {
                            byte[] before = (byte[])grid.Clone();
                            Assert.ThrowsAny<ArgumentException>(stamp);
                            Assert.Equal(before, grid);
                            break;
                        }
                        stamp();
                        Assert.Equal(
                            ReadGray(Path.Combine(
                                caseDir, root.GetProperty("expected").GetProperty("file").GetString()!)),
                            grid);
                        break;
                    }
                case "fill-random":
                    {
                        var shape = root.GetProperty("grid").GetProperty("shape");
                        int height = shape[0].GetInt32(), width = shape[1].GetInt32();
                        byte[] grid = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()!));
                        int[] region = root.GetProperty("region").EnumerateArray().Select(v => v.GetInt32()).ToArray();
                        void Fill() => Patterns.FillRandom(
                            grid, width, height, region[0], region[1], region[2], region[3],
                            root.GetProperty("density").GetDouble(), root.GetProperty("seed").GetUInt64());
                        if (IsError(root))
                        {
                            byte[] before = (byte[])grid.Clone();
                            Assert.ThrowsAny<ArgumentException>(Fill);
                            Assert.Equal(before, grid);
                            break;
                        }
                        Fill();
                        Assert.Equal(
                            ReadGray(Path.Combine(
                                caseDir, root.GetProperty("expected").GetProperty("file").GetString()!)),
                            grid);
                        break;
                    }
                case "advance":
                    {
                        var shape = root.GetProperty("grid").GetProperty("shape");
                        int height = shape[0].GetInt32(), width = shape[1].GetInt32();
                        byte[] grid = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()!));
                        int[] region = root.GetProperty("region").EnumerateArray().Select(v => v.GetInt32()).ToArray();
                        int n = root.GetProperty("n").GetInt32();
                        bool outside = root.GetProperty("outside").GetBoolean();
                        (Func<byte[]> state, Func<int> generation, Action advance) = World(
                            root.GetProperty("world"), grid, width, height, region, n, outside);
                        if (IsError(root))
                        {
                            Assert.ThrowsAny<ArgumentException>(advance);
                            Assert.Equal(grid, state());
                            Assert.Equal(0, generation());
                            break;
                        }
                        advance();
                        Assert.Equal(
                            ReadGray(Path.Combine(
                                caseDir, root.GetProperty("expected").GetProperty("file").GetString()!)),
                            state());
                        Assert.Equal(0, generation());
                        break;
                    }
                case "extract":
                    {
                        var gridShape = root.GetProperty("grid").GetProperty("shape");
                        int gridHeight = gridShape[0].GetInt32();
                        int gridWidth = gridShape[1].GetInt32();
                        byte[] grid = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()!));
                        byte[] region = Patterns.Extract(
                            grid, gridWidth, gridHeight, 1,
                            root.GetProperty("x").GetInt32(), root.GetProperty("y").GetInt32(),
                            root.GetProperty("width").GetInt32(), root.GetProperty("height").GetInt32(),
                            root.GetProperty("torus").GetBoolean());
                        Assert.Equal(
                            ReadGray(Path.Combine(
                                caseDir, root.GetProperty("expected").GetProperty("file").GetString()!)),
                            region);
                        break;
                    }
                case "rle-extent":
                    {
                        string input = File.ReadAllText(Path.Combine(caseDir, root.GetProperty("input").GetString()!));
                        RleExtent extent = Patterns.RleMeasure(input);
                        var want = root.GetProperty("extent");
                        Assert.Equal(Big(want.GetProperty("width")), extent.Width);
                        Assert.Equal(Big(want.GetProperty("height")), extent.Height);
                        Assert.Equal(Big(want.GetProperty("population")), extent.Population);
                        var live = want.GetProperty("live");
                        CellBox? expectedLive = live.ValueKind == JsonValueKind.Null
                            ? (CellBox?)null
                            : new CellBox(Big(live[0]), Big(live[1]), Big(live[2]), Big(live[3]));
                        Assert.Equal(expectedLive, extent.Live);
                        Assert.Equal(
                            want.GetProperty("rule").ValueKind == JsonValueKind.Null
                                ? null
                                : want.GetProperty("rule").GetString(),
                            extent.Rule);
                        Assert.Equal(want.GetProperty("extended").GetBoolean(), extent.Extended);
                        break;
                    }
                case "rle-limit":
                    {
                        string input = File.ReadAllText(Path.Combine(caseDir, root.GetProperty("input").GetString()!));
                        var limit = root.GetProperty("limit");
                        if (IsError(root))
                        {
                            Assert.ThrowsAny<ArgumentException>(() => Decode(input, limit, trim: false));
                            break;
                        }
                        RlePattern decoded = Decode(input, limit, trim: false);
                        var shape = root.GetProperty("shape");
                        Assert.Equal(shape[0].GetInt32(), decoded.Height);
                        Assert.Equal(shape[1].GetInt32(), decoded.Width);
                        int population = 0;
                        foreach (byte cell in decoded.Cells)
                        {
                            if (cell != 0)
                                population++;
                        }
                        Assert.Equal(root.GetProperty("population").GetInt32(), population);
                        break;
                    }
                case "rle-trim":
                    {
                        string input = File.ReadAllText(Path.Combine(caseDir, root.GetProperty("input").GetString()!));
                        var limit = root.GetProperty("limit");
                        if (IsError(root))
                        {
                            Assert.ThrowsAny<ArgumentException>(() => Decode(input, limit, trim: true));
                            break;
                        }
                        RlePattern decoded = Decode(input, limit, trim: true);
                        Assert.Equal(
                            root.GetProperty("rule").ValueKind == JsonValueKind.Null
                                ? null
                                : root.GetProperty("rule").GetString(),
                            decoded.Rule);
                        var shape = root.GetProperty("grid").GetProperty("shape");
                        Assert.Equal(shape[0].GetInt32(), decoded.Height);
                        Assert.Equal(shape[1].GetInt32(), decoded.Width);
                        Assert.Equal(
                            ReadGray(Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()!)),
                            decoded.Cells);
                        break;
                    }
                case "turned-rect":
                    {
                        foreach (JsonElement entry in root.GetProperty("cases").EnumerateArray())
                        {
                            BigInteger[] rect = entry.GetProperty("rect").EnumerateArray().Select(Big).ToArray();
                            bool clockwise = entry.GetProperty("clockwise").GetBoolean();
                            var keys = new HashSet<string>(entry.EnumerateObject().Select(p => p.Name));
                            if (IsError(entry))
                            {
                                Assert.True(keys.SetEquals(new[] { "rect", "clockwise", "error" }), caseName);
                                Assert.Throws<ArgumentException>(
                                    () => Patterns.TurnedRect(rect[0], rect[1], rect[2], rect[3], clockwise));
                                continue;
                            }
                            Assert.True(keys.SetEquals(new[] { "rect", "clockwise", "expect" }), caseName);
                            BigInteger[] expect = entry.GetProperty("expect").EnumerateArray().Select(Big).ToArray();
                            var want = new CellBox(expect[0], expect[1], expect[2], expect[3]);
                            Assert.Equal(want, Patterns.TurnedRect(rect[0], rect[1], rect[2], rect[3], clockwise));
                            Assert.Equal(want, Patterns.TurnedRect(new CellBox(rect[0], rect[1], rect[2], rect[3]), clockwise));
                            if (rect.Concat(expect).All(v => BigInteger.Abs(v) <= HashLife.EditLimit))
                            {
                                // The same rectangle as the universe's turn.
                                CellBox turned = new HashLife().RotateRect(
                                    (long)rect[0], (long)rect[1], (long)rect[2], (long)rect[3], clockwise);
                                Assert.Equal(want, turned);
                            }
                        }
                        break;
                    }
                default:
                    throw new InvalidDataException($"unknown pattern kind in {caseName}");
            }
        }

        private static BigInteger Big(JsonElement text) => BigInteger.Parse(text.GetString()!);

        /// <summary>The world an "advance" case names — a family and its parameters, cells from the
        /// grid — as its state, its generation, and the advance the case runs.</summary>
        private static (Func<byte[]>, Func<int>, Action) World(
            JsonElement world, byte[] grid, int width, int height, int[] r, int n, bool outside)
        {
            var keys = world.EnumerateObject().Select(p => p.Name).ToHashSet();
            // A topology's shift and axis appear only when they aren't 0 and x (spec/topology.md).
            Topology Edge(string name) => Topology.Parse(
                name,
                world.TryGetProperty("shift", out JsonElement shift) ? shift.GetInt32() : 0,
                world.TryGetProperty("axis", out JsonElement axis) ? axis.GetString()! : "x");
            var topologyKeys = new HashSet<string> { "boundary", "shift", "axis" };
            switch (world.GetProperty("family").GetString())
            {
                case "lifelike":
                    {
                        Assert.Subset(keys, new HashSet<string> { "family", "rule", "boundary" });
                        Assert.Superset(keys, new HashSet<string>(topologyKeys) { "family", "rule" });
                        var life = new LifeLike(
                            world.GetProperty("rule").GetString()!, width, height,
                            Edge(world.GetProperty("boundary").GetString()!));
                        life.SetState(grid);
                        return (() => life.State.ToArray(), () => life.Generation, outside
                            ? () => life.AdvanceOutside(r[0], r[1], r[2], r[3], n)
                            : () => life.AdvanceSelection(r[0], r[1], r[2], r[3], n));
                    }
                case "wireworld":
                    {
                        Assert.Subset(keys, new HashSet<string> { "family", "boundary" });
                        Assert.Superset(keys, new HashSet<string>(topologyKeys) { "family" });
                        var wire = new Wireworld(width, height, grid, Edge(world.GetProperty("boundary").GetString()!));
                        return (() => wire.State.ToArray(), () => wire.Generation, outside
                            ? () => wire.AdvanceOutside(r[0], r[1], r[2], r[3], n)
                            : () => wire.AdvanceSelection(r[0], r[1], r[2], r[3], n));
                    }
                case "cyclic":
                    {
                        Assert.Equal(
                            new HashSet<string> { "family", "states", "threshold", "reach", "neighborhood" }, keys);
                        var cyclic = new Cyclic(
                            world.GetProperty("states").GetInt32(), width, height,
                            world.GetProperty("threshold").GetInt32(), world.GetProperty("reach").GetInt32(),
                            world.GetProperty("neighborhood").GetString() switch
                            {
                                "moore" => Neighborhood.Moore,
                                "vonneumann" => Neighborhood.VonNeumann,
                                var other => throw new InvalidDataException($"unknown neighborhood {other}"),
                            });
                        cyclic.SetState(grid);
                        return (() => cyclic.State.ToArray(), () => cyclic.Generation, outside
                            ? () => cyclic.AdvanceOutside(r[0], r[1], r[2], r[3], n)
                            : () => cyclic.AdvanceSelection(r[0], r[1], r[2], r[3], n));
                    }
                case "ltl":
                    {
                        Assert.Equal(new HashSet<string>(topologyKeys) { "family", "rule" }, keys);
                        var ltl = new LargerThanLife(
                            world.GetProperty("rule").GetString()!, width, height,
                            Edge(world.GetProperty("boundary").GetString()!));
                        ltl.SetState(grid);
                        return (() => ltl.State.ToArray(), () => ltl.Generation, outside
                            ? () => ltl.AdvanceOutside(r[0], r[1], r[2], r[3], n)
                            : () => ltl.AdvanceSelection(r[0], r[1], r[2], r[3], n));
                    }
                default:
                    throw new InvalidDataException($"unknown world {world}");
            }
        }

        private static bool IsError(JsonElement root) =>
            root.TryGetProperty("error", out JsonElement error) && error.GetBoolean();

        /// <summary>Decode under the case's limit: "default" (the spec's), a number, or null (lifted).</summary>
        private static RlePattern Decode(string input, JsonElement limit, bool trim)
        {
            if (limit.ValueKind == JsonValueKind.Null)
                return Patterns.RleDecode(input, null, trim);
            if (limit.ValueKind == JsonValueKind.Number)
                return Patterns.RleDecode(input, limit.GetInt64(), trim);
            Assert.Equal("default", limit.GetString());
            // The one-argument decode is the default limit's; trimming names it.
            return trim ? Patterns.RleDecode(input, Patterns.DefaultMaxCells, true) : Patterns.RleDecode(input);
        }

        private static byte[] ReadGray(string path)
        {
            var (_, _, channels, pixels) = Png.Read(path);
            Assert.Equal(1, channels);
            return pixels;
        }
    }
}
