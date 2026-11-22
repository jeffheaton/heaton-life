using System;
using System.Linq;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Every consumer of a Life-like rule takes every notation of spec/rules.md: Advance Selection
    /// and Advance Outside on grids and in HashLife, the pattern-file readers, and the RLE and
    /// Macrocell writers, which write the rule's canonical spelling. Mirrors
    /// python/tests/test_rule_consumers.py.
    /// </summary>
    public class RuleConsumerTests
    {
        private const string MooreMap =
            "MAPARYXfhZofugWaH7oaIDogBZofuhogOiA6IDogIAAgAAWaH7oaIDogGiA6ICAAIAAaIDogIAAgACAAIAAAAAAAA";
        private const string HexMap = "MAPFgFoF2gXgH5oF4B+AH4A6A";
        private const string VnMap = "MAPHmkphg";
        private const string GliderRleUppercase = "BOB$2BO$3O!"; // dead and alive in a two-state file
        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        /// <summary>One rule of each class as a person might type it, and its canonical form.</summary>
        public static TheoryData<string, string> Rules() => new TheoryData<string, string>
        {
            { "b3/s2-i34q", "B3/S2-i34q" },
            { "B2cekin/S12", "B2-a/S12" },
            { "b2/s34h", "B2/S34H" },
            { "B2/S013v", "B2/S013V" },
            { "map" + MooreMap.Substring(3) + "==", MooreMap },
            { HexMap + "==", HexMap },
            { "map" + VnMap.Substring(3), VnMap },
        };

        public static TheoryData<string> B0Rules() => new TheoryData<string>
        {
            "MAPg" + new string('A', 85),
            "B0/S2H",
            "b03/s23",
        };

        [Theory]
        [MemberData(nameof(Rules))]
        public void AdvanceRunsTheWorldsOwnRule(string typed, string canonical)
        {
            foreach (bool outside in new[] { false, true })
            {
                var (grid, plane) = Advanced(typed, outside);
                Assert.Equal(plane, grid);
                // The rule shows in the result: Life advances the same soup to other cells.
                var (lifeGrid, _) = Advanced("B3/S23", outside);
                Assert.NotEqual(lifeGrid, grid);
            }
            Assert.Equal(canonical, new HashLife(typed).Rule);
        }

        /// <summary>A soup advanced 12 generations by a dead-edged 200 × 160 grid, and by HashLife on
        /// the plane, each told the rule as <paramref name="rule"/>; the pattern never reaches the
        /// grid's edge. The selection is (85, 65)..(114, 84) on the grid, 100 left and 75 up of it in
        /// HashLife.</summary>
        private static (byte[] Grid, byte[] Plane) Advanced(string rule, bool outside)
        {
            const int width = 200, height = 160;
            var soup = new byte[40 * 30];
            Seeding.Soup(soup, 0.4, 11);
            var cells = new byte[width * height];
            for (int y = 0; y < 30; y++)
                Array.Copy(soup, y * 40, cells, (60 + y) * width + 80, 40);
            var world = new LifeLike(rule, width, height, Boundary.Dead);
            world.SetState(cells);
            var u = new HashLife(rule);
            u.SetRect(-20, -15, soup, 40, 30);
            if (outside)
            {
                world.AdvanceOutside(85, 65, 114, 84, 12);
                u.AdvanceOutside(-15, -10, 14, 9, 12);
            }
            else
            {
                world.AdvanceSelection(85, 65, 114, 84, 12);
                u.AdvanceSelection(-15, -10, 14, 9, 12);
            }
            Assert.Equal(0, world.Generation);
            Assert.True(u.Generation.IsZero);
            Assert.Equal(world.Rule, u.Rule);
            return (world.State.ToArray(), u.GetRect(-100, -75, 99, 84));
        }

        [Theory]
        [MemberData(nameof(Rules))]
        public void ReadersTakeEveryNotation(string typed, string canonical)
        {
            // RLE: a header naming the rule in any spelling makes the file two-state.
            string rle = $"x = 3, y = 3, rule = {typed}\n{GliderRleUppercase}\n";
            PatternFile found = PatternFiles.Read(rle);
            Assert.Equal(PatternFormat.Rle, found.Format);
            Assert.Equal(typed, found.Rule); // the header's, as written
            Assert.Equal(Glider, found.Cells);
            HashLife placed = PatternFiles.ReadUniverse(rle).Universe;
            Assert.Equal(canonical, placed.Rule);
            Assert.Equal(Glider, placed.GetRect(0, 0, 2, 2));

            // Life 1.05: an #R line that isn't survival/birth digits is the rule as written.
            foreach (string written in new[] { typed, $" {typed} " })
            {
                string life = $"#Life 1.05\n#R{written}\n#P 0 0\n.*.\n..*\n***\n";
                found = PatternFiles.Read(life);
                Assert.Equal(PatternFormat.Life105, found.Format);
                Assert.Equal(typed, found.Rule);
                Assert.Equal(Glider, found.Cells);
                Assert.Equal(canonical, PatternFiles.ReadUniverse(life).Universe.Rule);
            }

            // Macrocell: #R in any spelling reads back canonical.
            var u = new HashLife(canonical);
            u.SetRect(0, 0, Glider, 3, 3);
            string mc = u.ToMacrocell().Replace($"#R {canonical}\n", $"#R {typed}\n");
            Assert.Contains($"#R {typed}\n", mc);
            found = PatternFiles.Read(mc);
            Assert.Equal(PatternFormat.Macrocell, found.Format);
            Assert.Equal(canonical, found.Rule);
            Assert.Equal(Glider, found.Cells);
            Assert.Equal(canonical, PatternFiles.ReadUniverse(mc).Universe.Rule);
        }

        [Fact]
        public void RulesWithSpacesReadFromLifeAndMacrocellFiles()
        {
            string life = "#Life 1.05\n#R b3 / s2-i34q\n#P 0 0\n.*.\n..*\n***\n";
            Assert.Equal("b3 / s2-i34q", PatternFiles.Read(life).Rule);
            Assert.Equal("B3/S2-i34q", PatternFiles.ReadUniverse(life).Universe.Rule);
            var u = new HashLife("B2/S34H");
            u.SetRect(0, 0, Glider, 3, 3);
            string mc = u.ToMacrocell().Replace("#R B2/S34H\n", "#R b2 /s34h\n");
            Assert.Equal("B2/S34H", PatternFiles.ReadUniverse(mc).Universe.Rule);
        }

        [Theory]
        [InlineData("life")]
        [InlineData("highlife")]
        [InlineData("Life")]
        public void AFileNamesItsRuleNeverAPreset(string preset)
        {
            // spec/rules.md "Preset names": a grid read keeps a Life 1.0x rule as written, for the
            // caller to compile; every reader that compiles a file's rule refuses a preset.
            string life = $"#Life 1.05\n#R {preset}\n#P 0 0\n.*.\n..*\n***\n";
            Assert.Equal(preset, PatternFiles.Read(life).Rule);
            Assert.StartsWith("invalid rule", Assert.ThrowsAny<ArgumentException>(() => PatternFiles.ReadUniverse(life)).Message);
            string mc = $"[M2] (example 1.0)\n#R {preset}\n.*$..*$***$\n";
            Assert.Contains("invalid rule", Assert.Throws<FormatException>(() => PatternFiles.Read(mc)).Message);
            Assert.Contains("invalid rule", Assert.Throws<FormatException>(() => PatternFiles.ReadUniverse(mc)).Message);
            Assert.Contains("invalid rule", Assert.Throws<FormatException>(() => PatternFiles.Measure(mc)).Message);
            string rle = $"x = 3, y = 3, rule = {preset}\nbo$2bo$3o!\n";
            Assert.True(Patterns.RleMeasure(rle).Extended); // no rule, so the file is extended
            Assert.Contains("extended", Assert.Throws<FormatException>(() => PatternFiles.ReadUniverse(rle)).Message);
        }

        /// <summary>spec/hashlife.md "Rules with B0": every reader takes a rule with B0, its cells
        /// the universe's cells; a grid takes them as written.</summary>
        [Theory]
        [MemberData(nameof(B0Rules))]
        public void AB0RuleReadsIntoAGridAndAUniverse(string rule)
        {
            string canonical = RuleString.Compile(rule).Canonical;
            string rle = $"x = 3, y = 3, rule = {rule}\n{GliderRleUppercase}\n";
            PatternFile found = PatternFiles.Read(rle);
            Assert.Equal(rule, found.Rule); // still a Life-like rule, so the file is two-state
            Assert.Equal(Glider, found.Cells);
            HashLife universe = PatternFiles.ReadUniverse(rle).Universe;
            Assert.Equal(canonical, universe.Rule);
            Assert.Equal(Glider, universe.GetRect(0, 0, 2, 2));
            string life = $"#Life 1.05\n#R {rule}\n#P 0 0\n.*.\n..*\n***\n";
            Assert.Equal(universe.ToMacrocell(), PatternFiles.ReadUniverse(life).Universe.ToMacrocell());
            var u = new HashLife("B3/S2-i34q");
            u.SetRect(0, 0, Glider, 3, 3);
            u.Rule = rule;
            Assert.Equal(canonical, u.Rule);
            Assert.Equal(Glider, u.GetRect(0, 0, 2, 2)); // a new rule keeps the cells
        }

        [Theory]
        [MemberData(nameof(Rules))]
        public void WritersWriteTheCanonicalSpelling(string typed, string canonical)
        {
            var u = new HashLife(typed);
            u.SetRect(0, 0, Glider, 3, 3);
            string rle = u.ToRle();
            Assert.Contains($", rule = {canonical}\n", rle);
            HashLife back = HashLife.FromRle(rle);
            Assert.Equal(canonical, back.Rule);
            Assert.Equal(Glider, back.GetRect(0, 0, 2, 2));

            string mc = u.ToMacrocell();
            Assert.Contains($"\n#R {canonical}\n", mc);
            Assert.Equal(canonical, HashLife.FromMacrocell(mc).Rule);

            HashLifeSnapshot first = u.Snapshot();
            u.Step(4);
            string timeline = Macrocell.WriteTimeline(u, new[] { first, u.Snapshot() });
            Assert.Contains($"\n#R {canonical}\n", timeline);
            Assert.Equal(canonical, Macrocell.ReadTimeline(timeline).Universe.Rule);

            string grid = Patterns.RleEncode(Glider, 3, 3, typed);
            Assert.StartsWith($"x = 3, y = 3, rule = {canonical}\n", grid);
            RlePattern decoded = Patterns.RleDecode(grid);
            Assert.Equal(canonical, decoded.Rule);
            Assert.Equal(Glider, decoded.Cells);
        }

        [Fact]
        public void TheGridWriterWritesAHeaderThatReadsBack()
        {
            // An RLE header's rule ends at whitespace, so a rule spelled with spaces is written
            // canonically or it would read back as "B3" in the extended dialect.
            string text = Patterns.RleEncode(Glider, 3, 3, "b3 / s32");
            Assert.StartsWith("x = 3, y = 3, rule = B3/S23\n", text);
            RlePattern decoded = Patterns.RleDecode(text);
            Assert.Equal("B3/S23", decoded.Rule);
            Assert.Equal(Glider, decoded.Cells);
            // Any other rule is written as given.
            Assert.StartsWith("x = 3, y = 3, rule = WireWorld\n", Patterns.RleEncode(Glider, 3, 3, "WireWorld"));
            Assert.StartsWith("x = 3, y = 3, rule = life\n", Patterns.RleEncode(Glider, 3, 3, "life"));
        }
    }
}
