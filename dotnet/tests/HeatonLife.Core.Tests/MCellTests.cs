using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Numerics;
using System.Text;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// MCell files (spec/formats.md "MCell"): detection, the Life, Generations and Larger than Life
    /// families, the cell data and its two-letter states, boards, every refusal's reason, the
    /// writer, and both unbounded universes. The Python suite checks the same
    /// (python/tests/test_mcell.py).
    /// </summary>
    public class MCellTests
    {
        // MCell's own example of the format (its author's description of .mcl files).
        private const string Worms =
            "#MCell 3.00\n#GAME Generations\n#RULE 3467/25/6\n#SPEED 20\n#BOARD 300x300\n#WRAP 0\n"
            + "#D\n#D The universe of Worms.\n#D\n#D Discovered by Mirek Wojtowicz\n#D 1999.04.08\n"
            + "#L ..DE.DED$.CE.E.DD$BDBABBC$.CACCEC$.A.BD.B$..B3C$3.3A$..4A$3.AA31$8.AA$\n"
            + "#L 7.4A$7.3A$7.3CB$6.B.DB.A$6.CECCAC$6.CBBABDB$5.DD.E.EC$5.DED.ED\n";

        private const string Glider = "#MCell 4.20\n#GAME Life\n#RULE 23/3\n#D A glider\n#L .A$..A$3A\n";

        private static string Mcell(params string[] lines) => string.Join("\n", new[] { "#MCell 4.20" }.Concat(lines)) + "\n";

        private static byte[] Gzip(string text)
        {
            using var buffer = new MemoryStream();
            using (var gzip = new GZipStream(buffer, CompressionLevel.Optimal, leaveOpen: true))
            {
                byte[] bytes = Encoding.UTF8.GetBytes(text);
                gzip.Write(bytes, 0, bytes.Length);
            }
            return buffer.ToArray();
        }

        private static int[][] Rows(PatternFile f)
            => Enumerable.Range(0, f.Height).Select(y => f.Cells.Skip(y * f.Width).Take(f.Width).Select(c => (int)c).ToArray()).ToArray();

        // -- detection ---------------------------------------------------------------------------

        [Fact]
        public void AFileThatStartsWithMCellIsOne()
        {
            Assert.Equal(PatternFormat.MCell, PatternFiles.Detect(Glider));
            Assert.Equal(PatternFormat.MCell, PatternFiles.Detect("\n  \n" + Glider));
            Assert.Equal(PatternFormat.MCell, PatternFiles.Detect(Gzip(Glider)));
            Assert.Equal(PatternFormat.Rle, PatternFiles.Detect("#MCELL 4.20\n#L A\n")); // matched exactly as written
            Assert.Equal("mcell", PatternFiles.FormatName(PatternFormat.MCell));
        }

        // -- reading -----------------------------------------------------------------------------

        [Fact]
        public void MCellsOwnExampleReadsAsItsBoard()
        {
            PatternFile found = PatternFiles.Read(Worms);
            Assert.Equal(PatternFormat.MCell, found.Format);
            Assert.Equal("3467/25/6", found.Rule);
            Assert.Equal(BigInteger.Zero, found.Generation);
            Assert.Equal(new BoundedGrid(300, 300, new Topology(Boundary.Dead)), found.BoundedGrid);
            Assert.Equal((300, 300), (found.Width, found.Height));
            Assert.Equal((new BigInteger(-150), new BigInteger(-150)), (found.X, found.Y));
            Assert.Equal(
                new PatternMetadata(null, null, new[] { "", "The universe of Worms.", "", "Discovered by Mirek Wojtowicz", "1999.04.08" }),
                found.Metadata);
            PatternFile trimmed = PatternFiles.Read(Worms, trim: true);
            Assert.Equal((13, 48), (trimmed.Width, trimmed.Height));
            Assert.Equal((new BigInteger(-6), new BigInteger(-24)), (trimmed.X, trimmed.Y));
            for (int y = 0; y < 48; y++)
                for (int x = 0; x < 13; x++)
                    Assert.Equal(found.Cells[(126 + y) * 300 + 144 + x], trimmed.Cells[y * 13 + x]);
            Assert.Equal(5, trimmed.Cells.Max());
            Assert.Equal(4, trimmed.Cells[2]); // D, the first live cell
            PatternExtent extent = PatternFiles.Measure(Worms);
            Assert.Equal((new BigInteger(300), new BigInteger(300)), (extent.Width, extent.Height));
            Assert.Equal((new BigInteger(-150), new BigInteger(-150)), (extent.X, extent.Y));
            Assert.False(extent.TwoState);
            Assert.Equal(found.BoundedGrid, extent.BoundedGrid);
        }

        [Fact]
        public void ALifeFileIsTwoStateAndReadsSurvivalBirth()
        {
            PatternFile found = PatternFiles.Read(Glider);
            Assert.Equal("B3/S23", found.Rule);
            Assert.Null(found.BoundedGrid);
            Assert.Equal((BigInteger.Zero, BigInteger.Zero), (found.X, found.Y));
            Assert.Equal(new[] { new[] { 0, 1, 0 }, new[] { 0, 0, 1 }, new[] { 1, 1, 1 } }, Rows(found));
            Assert.Equal(new[] { "A glider" }, found.Metadata.Comments);
            Assert.True(PatternFiles.Measure(Glider).TwoState);
            // MCell's Life rules have one bit: every state from 1 to 255 is alive.
            Assert.Equal(new[] { new[] { 1, 0, 1 }, new[] { 1, 0, 1 } }, Rows(PatternFiles.Read(Mcell("#L A.C$jO.aB"))));
            // No #GAME is Life, no #RULE is 23/3, and the family's case doesn't matter.
            Assert.Equal("B3/S23", PatternFiles.Read(Mcell("#L A")).Rule);
            Assert.Equal("B36/S125", PatternFiles.Read(Mcell("#GAME LIFE", "#RULE 125/36", "#L A")).Rule);
            Assert.Equal("B0/S", PatternFiles.Read(Mcell("#RULE /0", "#L A")).Rule); // B0, as MCell writes it
        }

        [Fact]
        public void GenerationsAndLargerThanLifeKeepTheirStates()
        {
            PatternFile gen = PatternFiles.Read(Mcell("#GAME Generations", "#RULE /2/3", "#L A.B"));
            Assert.Equal("/2/3", gen.Rule);
            Assert.Equal(new[] { new[] { 1, 0, 2 } }, Rows(gen));
            Assert.False(PatternFiles.Measure(Mcell("#GAME Generations", "#RULE /2/3", "#L A")).TwoState);
            // A long rule split over several #RULE lines, MCell's spaced fields, and a board.
            PatternFile ltl = PatternFiles.Read(Mcell(
                "#GAME Larger than Life", "#RULE R5,C30,M1,", "#RULE  S34..58, B34..45,NM", "#BOARD 40 X 30", "#L 3aB$$A"));
            Assert.Equal("R5,C30,M1,S34..58,B34..45,NM", ltl.Rule);
            Assert.Equal(new BoundedGrid(40, 30, new Topology(Boundary.Torus)), ltl.BoundedGrid); // no #WRAP: a torus
            Assert.Equal((40, 30), (ltl.Width, ltl.Height));
            Assert.Equal(26, ltl.Cells.Max());
        }

        [Fact]
        public void TheCellData()
        {
            int[][] Cells(string data, string rule = "/2/256") => Rows(PatternFiles.Read(Mcell("#GAME Generations", $"#RULE {rule}", data)));

            Assert.Equal(new[] { new[] { 25, 48, 49, 255 } }, Cells("#L aA aXbA jO")); // whitespace is ignored
            Assert.Equal(new[] { new[] { 26, 26 }, new[] { 24, 0 } }, Cells("#L 2a\n#L B$X")); // #L lines join, a tag included
            Assert.Equal(new[] { new[] { 1, 0, 2 }, new[] { 0, 0, 0 } }, Cells("#L A0$.B$")); // 0$ makes nothing
            Assert.Equal(
                new[] { new[] { 0, 0, 0, 1 }, new[] { 0, 0, 0, 0 }, new[] { 0, 0, 0, 0 } }, Cells("#L 3.A2$"));
            FormatException empty = Assert.Throws<FormatException>(() => PatternFiles.Read(Mcell("#D only a comment")));
            Assert.Equal("the MCell pattern has no cells", empty.Message);
            Assert.Equal(BigInteger.Zero, PatternFiles.Measure(Mcell("#L $")).Width); // rows with nothing in them
        }

        [Fact]
        public void IgnoredLinesAndBoards()
        {
            PatternFile plane = PatternFiles.Read(Mcell(
                "#SPEED 0", "#CCOLORS 16", "#DIV #NOISE,act=1", "#FUTURE x", "#BOARD 9x7", "#WRAP 0", "#L 3A"));
            Assert.Equal(new BoundedGrid(9, 7, new Topology(Boundary.Dead)), plane.BoundedGrid);
            Assert.Equal((new BigInteger(-4), new BigInteger(-3)), (plane.X, plane.Y));
            Assert.Equal(new byte[] { 1, 1, 1 }, plane.Cells.Skip(3 * 9 + 3).Take(3).ToArray());
            // #WRAP is checked without a board too, though it plays no part.
            Assert.Null(PatternFiles.Read(Mcell("#WRAP 1", "#L A")).BoundedGrid);
        }

        public static IEnumerable<object[]> Refusals()
        {
            yield return new object[] { new[] { "#L A", "A" }, "line 3 does not start with '#'" };
            yield return new object[]
            {
                new[] { "#GAME Weighted Life" },
                "the family 'Weighted Life' is not read here (Life, Generations and Larger than Life are)",
            };
            yield return new object[] { new[] { "#RULE B3/S23" }, "a Life rule is survival/birth digits, such as 23/3, not 'B3/S23'" };
            yield return new object[] { new[] { "#RULE 23/39" }, "a Life rule is survival/birth digits, such as 23/3, not '23/39'" };
            // No MCell rule carries a History or Super suffix: MCell has neither.
            yield return new object[]
            {
                new[] { "#RULE 23/3Super" }, "a Life rule is survival/birth digits, such as 23/3, not '23/3Super'",
            };
            yield return new object[]
            {
                new[] { "#GAME Rules table", "#RULE Langtons-Loops" },
                "the family 'Rules table' is not read here (Life, Generations and Larger than Life are)",
            };
            // A rule file appended after the cells, as RLE may carry one, is no MCell line.
            yield return new object[]
            {
                new[] { "#GAME Generations", "#RULE 2/3/4", "#L A", "@RULE x" }, "line 5 does not start with '#'",
            };
            yield return new object[]
            {
                new[] { "#GAME Generations", "#RULE B2/S345/C4" },
                "a Generations rule is survival/birth/states digits, such as 345/2/4, not 'B2/S345/C4'",
            };
            yield return new object[]
            {
                new[] { "#GAME Generations", "#RULE 2/3/1" },
                "invalid Generations rule '2/3/1': a Generations rule has 2 to 256 states (spec/generations.md)",
            };
            yield return new object[]
            {
                new[] { "#GAME Larger than Life", "#RULE R5,C0,M1,S34..58" },
                "invalid Larger than Life rule 'R5,C0,M1,S34..58': expected the fields R, C, M, S, B and N, in that order (spec/ltl.md)",
            };
            yield return new object[] { new[] { "#BOARD 0x5" }, "#BOARD is <width>x<height>, not '0x5'" };
            yield return new object[] { new[] { "#BOARD 30x" }, "#BOARD is <width>x<height>, not '30x'" };
            yield return new object[] { new[] { "#WRAP yes" }, "#WRAP is 0 or 1, not 'yes'" };
            yield return new object[] { new[] { "#L 2A!" }, "'!' in the cell data is no run count, state or '$'" };
            yield return new object[] { new[] { "#L A12" }, "a run count in the cell data has no state or '$' after it" };
            yield return new object[] { new[] { "#L 3c." }, "'c' in the cell data has no state letter A to X after it" };
            yield return new object[] { new[] { "#L jX" }, "the cell data's state 264 is past 255" };
            yield return new object[]
            {
                new[] { "#GAME Generations", "#RULE 2/3/4", "#L ABCD" }, "the cell data's state 4 is past the rule's 4 states",
            };
            yield return new object[] { new[] { "#BOARD 2x2", "#L 3A" }, "the pattern reaches past its board (:T2,2)" };
        }

        [Theory]
        [MemberData(nameof(Refusals))]
        public void EveryRefusalSaysWhy(string[] lines, string reason)
        {
            FormatException e = Assert.Throws<FormatException>(() => PatternFiles.Read(Mcell(lines)));
            Assert.Equal("invalid MCell file: " + reason, e.Message);
            if (!reason.Contains("board")) // measuring refuses what reading refuses
                Assert.Throws<FormatException>(() => PatternFiles.Measure(Mcell(lines)));
        }

        // -- writing -----------------------------------------------------------------------------

        [Fact]
        public void TheWriter()
        {
            byte[] glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };
            var notes = new PatternMetadata("Glider", "J. Conway", new[] { "found 1969", "" });
            string text = Patterns.McellEncode(glider, 3, 3, "23/3", notes);
            Assert.Equal(
                "#MCell 4.00\n#GAME Life\n#RULE 23/3\n#D Glider\n#D J. Conway\n#D found 1969\n#D\n#L .A$2.A$3A\n", text);
            PatternFile back = PatternFiles.Read(text);
            Assert.Equal(glider, back.Cells);
            Assert.Equal("B3/S23", back.Rule);
            Assert.Equal(new PatternMetadata(null, null, new[] { "Glider", "J. Conway", "found 1969", "" }), back.Metadata);
            // The data decodes to exactly the grid: empty rows, and the first row padded to the width.
            var sparse = new byte[4 * 6];
            sparse[1 * 6 + 2] = 1;
            Assert.EndsWith("#L 6.$2.A2$\n", Patterns.McellEncode(sparse, 6, 4, "B3/S23"));
            Assert.Equal(sparse, PatternFiles.Read(Patterns.McellEncode(sparse, 6, 4, "B3/S23")).Cells);
            // Generations and Larger than Life, two-letter states, and a board.
            byte[] states = { 0, 25, 255, 3, 0, 0 };
            string gen = Patterns.McellEncode(states, 3, 2, "B2/S345/C256", null, new Topology(Boundary.Torus));
            Assert.Equal(
                new[] { "#GAME Generations", "#RULE 345/2/256", "#BOARD 3x2", "#WRAP 1" },
                gen.Split('\n').Skip(1).Take(4).ToArray());
            Assert.EndsWith("#L .aAjO$C\n", gen);
            string ltl = Patterns.McellEncode(states, 3, 2, "r5,c256,m0,s1..2,b3..4", null, new Topology(Boundary.Dead));
            Assert.Contains("#GAME Larger than Life\n#RULE R5,C256,M0,S1..2,B3..4,NM\n", ltl);
            Assert.Contains("#WRAP 0", ltl);
            foreach (var (written, rule) in new[] { (gen, "345/2/256"), (ltl, "R5,C256,M0,S1..2,B3..4,NM") })
            {
                PatternFile found = PatternFiles.Read(written);
                Assert.Equal(states, found.Cells);
                Assert.Equal(rule, found.Rule);
            }
        }

        public static IEnumerable<object?[]> WriterRefusals()
        {
            yield return new object?[] { "B2a/S23", null, "no MCell family holds the rule 'B2a/S23'" };
            yield return new object?[] { "B2/S34H", null, "no MCell family holds the rule 'B2/S34H'" };
            yield return new object?[] { "B3/S23History", null, "no MCell family holds the rule 'B3/S23History'" };
            yield return new object?[] { "B3/S23Super", null, "no MCell family holds the rule 'B3/S23Super'" };
            yield return new object?[] { "Langtons-Loops", null, "no MCell family holds the rule 'Langtons-Loops'" };
            yield return new object?[] { "B2a/S/C3", null, "no MCell family holds the rule 'B2a/S/C3'" };
            yield return new object?[] { "WireWorld", null, "no MCell family holds the rule 'WireWorld'" };
            yield return new object?[] { "B3/S23", "klein", "an MCell board is a torus or the plane, not ':K4*,3'" };
            yield return new object?[] { "B3/S23", "torus+1", "an MCell board is a torus or the plane, not ':T4+1,3'" };
            yield return new object?[] { "B2/S/C3", null, "the cells hold state 3, past the rule's 3 states" };
        }

        [Theory]
        [MemberData(nameof(WriterRefusals))]
        public void TheWriterRefusesWhatMCellCantHold(string rule, string? topology, string reason)
        {
            byte[] cells = { 0, 1, 0, 1, 1, 0, 3, 0, 0, 0, 0, 1 };
            if (!reason.Contains("state"))
                cells = cells.Select(c => (byte)Math.Min((int)c, 1)).ToArray();
            Topology? world = topology switch
            {
                "klein" => new Topology(Boundary.Klein),
                "torus+1" => new Topology(Boundary.Torus, 1),
                _ => null,
            };
            ArgumentException e = Assert.ThrowsAny<ArgumentException>(() => Patterns.McellEncode(cells, 4, 3, rule, null, world));
            Assert.Equal(reason, e.Message);
            Assert.ThrowsAny<ArgumentException>(() => Patterns.McellEncode(Array.Empty<byte>(), 0, 3, "B3/S23"));
        }

        [Fact]
        public void RandomGridsRoundTrip()
        {
            var rng = new Pcg32(17);
            for (int trial = 0; trial < 40; trial++)
            {
                int width = 1 + (int)(rng.NextU32() % 90), height = 1 + (int)(rng.NextU32() % 12);
                int states = new[] { 2, 5, 30, 256 }[trial % 4];
                var grid = new byte[width * height];
                for (int i = 0; i < grid.Length; i++)
                {
                    uint draw = rng.NextU32();
                    grid[i] = (byte)(draw % 3 == 0 ? draw % (uint)states : 0);
                }
                string rule = states == 2 ? "B3/S23" : $"B2/S34/C{states}";
                Topology? topology = (trial % 3) switch
                {
                    1 => new Topology(Boundary.Torus),
                    2 => new Topology(Boundary.Dead),
                    _ => null,
                };
                string text = Patterns.McellEncode(grid, width, height, rule, null, topology);
                Assert.All(text.Split('\n').Where(line => line.StartsWith("#L", StringComparison.Ordinal)), line => Assert.True(line.Length <= 73));
                PatternFile found = PatternFiles.Read(text);
                Assert.Equal(grid, found.Cells);
                PatternExtent extent = PatternFiles.Measure(text);
                Assert.Equal((new BigInteger(width), new BigInteger(height)), (extent.Width, extent.Height));
            }
        }

        // -- the unbounded universes -------------------------------------------------------------

        [Fact]
        public void TheTwoStateUniverseReadsALifeFile()
        {
            PatternUniverse found = PatternFiles.ReadUniverse(Glider);
            Assert.Equal(PatternFormat.MCell, found.Format);
            Assert.Equal("B3/S23", found.Universe.Rule);
            Assert.Equal(new BigInteger(5), found.Universe.Population);
            Assert.Equal(new CellBox(0, 0, 2, 2), found.Universe.BoundingBox);
            PatternSnapshot snapshot = new HashLife().ReadSnapshot(Encoding.UTF8.GetBytes(Glider));
            Assert.Equal("B3/S23", snapshot.Rule);
            Assert.Equal(new[] { "A glider" }, snapshot.Metadata.Comments);
            foreach (var (text, reason) in new[]
            {
                (Worms, "the unbounded universe has no bounded grid (the MCell board ':P300,300')"),
                (Mcell("#GAME Generations", "#RULE 2/3/4", "#L A"), "Generations rule of 4 states"),
                (Mcell("#GAME Larger than Life", "#RULE 5,34,45,34,58", "#L A"), "Larger than Life"),
            })
            {
                Exception e = Assert.ThrowsAny<Exception>(() => PatternFiles.ReadUniverse(text));
                Assert.True(e is FormatException || e is ArgumentException, e.GetType().Name);
                Assert.Contains(reason, e.Message);
            }
        }

        [Fact]
        public void TheMultiStateUniverseReadsAGenerationsFile()
        {
            string text = Mcell("#GAME Generations", "#RULE 345/2/4", "#D Star Wars", "#L A.BC$$3C");
            MultiStatePatternUniverse found = MultiStateFiles.ReadUniverse(text);
            Assert.Equal(PatternFormat.MCell, found.Format);
            Assert.Equal("B2/S345/C4", found.Universe.Rule);
            Assert.Equal(new BigInteger(6), found.Universe.Population);
            Assert.Equal(new CellBox(0, 0, 3, 2), found.Universe.BoundingBox);
            Assert.Equal(new[] { "Star Wars" }, found.Metadata.Comments);
            foreach (var (refused, reason) in new[]
            {
                (Worms, "the unbounded universe has no bounded grid"),
                (Glider, "not a state rule"),
                (Mcell("#GAME Larger than Life", "#RULE 5,34,45,34,58", "#L A"), "Larger than Life"),
            })
            {
                Exception e = Assert.ThrowsAny<Exception>(() => MultiStateFiles.ReadUniverse(refused));
                Assert.True(e is FormatException || e is ArgumentException, e.GetType().Name);
                Assert.Contains(reason, e.Message);
            }
        }
    }
}
