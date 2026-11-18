using System;
using System.Collections.Generic;
using System.IO;
using System.Numerics;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Pattern conformance: replay vectors/patterns/ — RLE dialects with canonical
    /// re-encodes, the extent, the decode limit, trimmed decoding, transforms, extract
    /// and stamp semantics (spec/patterns.md).
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
                        var outputs = root.GetProperty("outputs");
                        Assert.Equal(
                            ReadGray(Path.Combine(caseDir, outputs.GetProperty("rotate90").GetString()!)),
                            Patterns.Rotate90(grid, width, height));
                        Assert.Equal(
                            ReadGray(Path.Combine(caseDir, outputs.GetProperty("flip_h").GetString()!)),
                            Patterns.FlipH(grid, width, height));
                        Assert.Equal(
                            ReadGray(Path.Combine(caseDir, outputs.GetProperty("flip_v").GetString()!)),
                            Patterns.FlipV(grid, width, height));
                        break;
                    }
                case "stamp":
                    {
                        var patternShape = root.GetProperty("pattern").GetProperty("shape");
                        int patternHeight = patternShape[0].GetInt32();
                        int patternWidth = patternShape[1].GetInt32();
                        byte[] pattern = ReadGray(
                            Path.Combine(caseDir, root.GetProperty("pattern").GetProperty("file").GetString()!));
                        int gridWidth = root.GetProperty("grid_width").GetInt32();
                        int gridHeight = root.GetProperty("grid_height").GetInt32();
                        var grid = new byte[gridWidth * gridHeight];
                        Array.Fill(grid, (byte)root.GetProperty("background").GetInt32());
                        Patterns.Stamp(
                            grid, gridWidth, gridHeight, 1, pattern, patternWidth, patternHeight,
                            root.GetProperty("x").GetInt32(), root.GetProperty("y").GetInt32(),
                            root.GetProperty("torus").GetBoolean(),
                            root.GetProperty("transparent").GetBoolean());
                        Assert.Equal(
                            ReadGray(Path.Combine(
                                caseDir, root.GetProperty("expected").GetProperty("file").GetString()!)),
                            grid);
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
                default:
                    throw new InvalidDataException($"unknown pattern kind in {caseName}");
            }
        }

        private static BigInteger Big(JsonElement text) => BigInteger.Parse(text.GetString()!);

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
