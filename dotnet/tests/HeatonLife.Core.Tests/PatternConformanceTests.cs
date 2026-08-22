using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Pattern conformance: replay vectors/patterns/ — RLE dialects with canonical
    /// re-encodes, transforms, extract and stamp semantics (spec/patterns.md).
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
                default:
                    throw new InvalidDataException($"unknown pattern kind in {caseName}");
            }
        }

        private static byte[] ReadGray(string path)
        {
            var (_, _, channels, pixels) = Png.Read(path);
            Assert.Equal(1, channels);
            return pixels;
        }
    }
}
