using System;
using System.Linq;
using System.Numerics;
using System.Text;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// History rules (spec/history.md): seven states over any Life-like rule. The on cells must run
    /// the base rule exactly, on every neighborhood and topology; the other states follow
    /// history.md's table; boundary cells keep their neighbors off; and the rule reads, writes and
    /// runs on grids, in RLE and on the unbounded plane (the multi-state universe). The Python
    /// reference's tests/test_history.py.
    /// </summary>
    public class HistoryTests
    {
        private const string LifeMoreMap =
            "MAPARYXfhZofugWaH7oaIDogBZofuhogOiA6IDogIAAgAAWaH7oaIDogGiA6ICAAIAAaIDogIAAgACAAIAAAAAAAA";

        public static TheoryData<string> Rules() => new TheoryData<string>
        {
            "B3/S23History", "B36/S23History", "B2/S34HHistory", "B2/S013VHistory", "B3/S2-i34qHistory",
            LifeMoreMap + "History",
        };

        private static readonly Topology[] Topologies =
        {
            new Topology(Boundary.Dead), new Topology(Boundary.Torus), new Topology(Boundary.Torus, 3, TopologyAxis.Y),
            new Topology(Boundary.Klein), new Topology(Boundary.Cross), new Topology(Boundary.Sphere),
        };

        /// <summary>A Moore MAP string writing a 512-entry table.</summary>
        private static string MapOf(ReadOnlySpan<byte> table)
        {
            const string base64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
            var sb = new StringBuilder("MAP");
            for (int c = 0; c < 86; c++)
            {
                int value = 0;
                for (int b = 0; b < 6; b++)
                {
                    int i = c * 6 + b;
                    value = (value << 1) | (i < 512 ? table[i] : 0);
                }
                sb.Append(base64[value]);
            }
            return sb.ToString();
        }

        private static byte[] Soup(int width, int height, uint seed, double density = 0.4)
        {
            var cells = new byte[width * height];
            Seeding.Soup(cells, density, seed);
            return cells;
        }

        // -- the rule ------------------------------------------------------------------------------

        [Fact]
        public void TheStatesAreNamedAsTheSpecNamesThem()
        {
            // spec/history.md "States": the names are the table's (Python's history.NAMES pins the
            // same table).
            Assert.Equal(TestPaths.SpecStateNames("history.md"), History.Names);
            Assert.Equal(History.States, History.Names.Count);
            Assert.Throws<NotSupportedException>(() => ((System.Collections.Generic.IList<string>)History.Names)[0] = "x");
        }

        [Fact]
        public void HistoryRulesCompileOnlyWhereVariantsAreAskedFor()
        {
            LifeRule rule = RuleString.Compile("b36 / s23history", variants: true);
            Assert.Equal(("B36/S23History", RuleVariant.History, 7), (rule.Canonical, rule.Variant, rule.States));
            Assert.Equal("B36/S23", rule.Base.Canonical);
            Assert.True(rule.Table.SequenceEqual(RuleString.Compile("B36/S23").Table));
            Assert.Equal("B3/S23History", RuleString.Compile("LifeHistory", true).Canonical);
            Assert.Equal("B3/S23History", RuleString.Compile(" LIFEHISTORY ", true).Canonical);
            Assert.Equal("B2/S34HHistory", RuleString.Compile("B2/S34hhistory", true).Canonical);
            Assert.Equal(RuleVariant.None, RuleString.Compile("B3/S23", true).Variant);
            foreach (string text in new[] { "B3/S23History", "LifeHistory", "MAP" + new string('A', 86) + "History" })
            {
                Assert.False(RuleString.TryCompile(text, out _, out string? reason));
                Assert.Equal("a History rule has 7 states, not 2", reason);
            }
            Assert.False(RuleString.TryCompile("B3/S23Histor", true, out _, out string? histor));
            Assert.Equal("unexpected 'Histor' after the survival counts", histor);
            // ASCII case only: a dotless i is no letter of the word, in either port.
            Assert.False(RuleString.TryCompile("B3/S23Hıstory", true, out _, out _));
            LifeRule plain = RuleString.Compile("MAP" + new string('A', 79) + "History", true);
            Assert.Equal((RuleVariant.None, RuleNeighborhood.Moore), (plain.Variant, plain.Neighborhood));
            foreach (string stem in new[] { new string('A', 86), new string('A', 22), new string('A', 6) })
                Assert.Equal(RuleVariant.History, RuleString.Compile("MAP" + stem + "==History", true).Variant);
        }

        [Fact]
        public void TheSameBaseAndConvertingCells()
        {
            LifeRule history = RuleString.Compile("B3/S23History", true);
            LifeRule life = RuleString.Compile("B3/S23");
            Assert.True(history.SameBase(life) && life.SameBase(history));
            Assert.True(history.SameBase(RuleString.Compile(MapOf(life.Table))));
            Assert.True(history.SameBase(RuleString.Compile("b3 / s32")));
            Assert.False(history.SameBase(RuleString.Compile("B36/S23")));
            byte[] cells = { 0, 1, 2, 3, 4, 5, 6, 9, 12 };
            byte[] kept = (byte[])cells.Clone();
            history.ConvertCells(kept);
            Assert.Equal(new byte[] { 0, 1, 2, 3, 4, 5, 6, 1, 0 }, kept);
            life.ConvertCells(cells);
            Assert.Equal(new byte[] { 0, 1, 0, 1, 0, 1, 0, 1, 0 }, cells);
        }

        // -- the evolution -------------------------------------------------------------------------

        /// <summary>The grid's step and the multi-state universe's cell function agree on random
        /// blocks of every state, under every topology.</summary>
        [Theory]
        [MemberData(nameof(Rules))]
        public void TheGridStepIsTheCellFunction(string text)
        {
            HistoryRule cell = HistoryRule.For(RuleString.Compile(text, true));
            var random = new Pcg32(7);
            foreach (Topology topology in Topologies)
            {
                const int size = 10;
                var cells = new byte[size * size];
                for (int i = 0; i < cells.Length; i++)
                    cells[i] = (byte)(random.NextU32() % 7);
                var world = new LifeLike(text, size, size, topology);
                world.SetState(cells);
                world.Step();
                var halo = new Halo(topology, size, size);
                var padded = new byte[halo.Length];
                halo.Fill(cells, padded, 0);
                int stride = halo.Columns;
                for (int y = 0; y < size; y++)
                {
                    for (int x = 0; x < size; x++)
                    {
                        int up = y * stride + x, mid = up + stride, down = mid + stride;
                        byte want = cell.NextState(
                            padded[up], padded[up + 1], padded[up + 2], padded[mid], padded[mid + 1],
                            padded[mid + 2], padded[down], padded[down + 1], padded[down + 2]);
                        Assert.True(want == world.State[y * size + x], $"{text} {topology.Name} ({x}, {y})");
                    }
                }
            }
        }

        [Theory]
        [MemberData(nameof(Rules))]
        public void OnCellsRunTheBaseRule(string text)
        {
            LifeRule rule = RuleString.Compile(text, true);
            foreach (Topology topology in Topologies)
            {
                var two = new LifeLike(rule.Base.Canonical, 24, 24, topology);
                var seven = new LifeLike(rule.Canonical, 24, 24, topology);
                two.SeedSoup(0.35, 5);
                seven.SeedSoup(0.35, 5);
                Assert.True(two.State.SequenceEqual(seven.State)); // the base rule's soup: 0 and 1
                for (int step = 0; step < 30; step++)
                {
                    two.Step();
                    seven.Step();
                    for (int i = 0; i < two.State.Length; i++)
                        Assert.Equal(two.State[i], (byte)(seven.State[i] & 1));
                    Assert.True(seven.State.ToArray().Max() <= 2); // no marks appear by themselves
                }
            }
        }

        [Fact]
        public void EachStateChangesAsTheTableSays()
        {
            var w = new LifeLike("B3/S23History", 16, 8, Boundary.Dead);
            var cells = new byte[16 * 8];
            void At(int x, int y, byte v) => cells[y * 16 + x] = v;
            At(1, 1, 3); At(2, 1, 5); At(1, 2, 1); At(2, 2, 3); // a block: every cell survives
            At(1, 5, 1); At(4, 5, 3); At(7, 5, 5); // lone on cells die: 2, 4, 4
            At(10, 1, 1); At(11, 1, 1); At(12, 1, 1); // a blinker over envelope and marks
            At(11, 0, 2); At(11, 2, 4);
            w.SetState(cells);
            w.Step();
            byte S(int x, int y) => w.State[y * 16 + x];
            Assert.Equal(new byte[] { 3, 5, 1, 3 }, new[] { S(1, 1), S(2, 1), S(1, 2), S(2, 2) });
            Assert.Equal(new byte[] { 2, 4, 4 }, new[] { S(1, 5), S(4, 5), S(7, 5) });
            Assert.Equal(new byte[] { 1, 1, 3 }, new[] { S(11, 0), S(11, 1), S(11, 2) }); // born into 2 and 4
            Assert.Equal(new byte[] { 2, 2 }, new[] { S(10, 1), S(12, 1) });
            w.Step();
            Assert.Equal(new byte[] { 2, 4 }, new[] { S(11, 0), S(11, 2) }); // dying again
            Assert.Equal(new byte[] { 1, 1 }, new[] { S(10, 1), S(12, 1) }); // born from the envelope
            Assert.Equal(1, History.NextState(History.Envelope, true));
            Assert.Equal(4, History.NextState(History.StartOn, false));
            Assert.Throws<ArgumentOutOfRangeException>(() => History.NextState(7, true));
        }

        [Fact]
        public void AStartOnCellNeverComesBack()
        {
            var w = new LifeLike("B3/S23History", 8, 8, Boundary.Dead);
            var cells = new byte[64];
            cells[3 * 8 + 2] = cells[3 * 8 + 3] = cells[3 * 8 + 4] = 5; // a blinker of start-on cells
            w.SetState(cells);
            w.Step();
            Assert.Equal(new byte[] { 1, 5, 1 }, new[] { w.State[2 * 8 + 3], w.State[3 * 8 + 3], w.State[4 * 8 + 3] });
            Assert.Equal(((byte)4, (byte)4), (w.State[3 * 8 + 2], w.State[3 * 8 + 4]));
            w.Step();
            // The ends were marked off and are born marked on, never start-on; the middle stays 5.
            Assert.Equal(new byte[] { 3, 5, 3 }, w.State.Slice(3 * 8 + 2, 3).ToArray());
            Assert.Equal(2, w.State[2 * 8 + 3]);
        }

        [Fact]
        public void BoundaryCellsKeepTheirNeighborsOff()
        {
            var w = new LifeLike("B3/S23History", 9, 9, Boundary.Dead);
            var cells = new byte[81];
            cells[4 * 9 + 4] = 6;
            cells[2 * 9 + 2] = cells[2 * 9 + 3] = cells[3 * 9 + 2] = cells[3 * 9 + 3] = 1;
            cells[6 * 9 + 6] = cells[6 * 9 + 7] = cells[6 * 9 + 8] = 1;
            w.SetState(cells);
            w.Step();
            Assert.Equal(6, w.State[4 * 9 + 4]);
            Assert.Equal(2, w.State[3 * 9 + 3]); // beside the boundary: dies though it has 3 neighbors
            Assert.Equal(1, w.State[2 * 9 + 2]);
            var hex = new LifeLike("B3/S23HHistory", 5, 5, Boundary.Torus);
            var block = new byte[25];
            block[2 * 5 + 2] = 6;
            block[1 * 5 + 3] = block[0 * 5 + 3] = block[1 * 5 + 4] = block[0 * 5 + 4] = 1;
            hex.SetState(block);
            hex.Step();
            Assert.Equal(1, hex.State[1 * 5 + 3]); // NE of the boundary: no hexagonal neighbor of it
        }

        [Fact]
        public void B0HistoryRunsAsWrittenOnAGrid()
        {
            var w = new LifeLike("B0/S8History", 6, 6, Boundary.Torus);
            var cells = new byte[36];
            cells[0] = 6;
            w.SetState(cells);
            w.Step();
            Assert.Equal(6, w.State[0]);
            Assert.Equal(36 - 1 - 8, w.State.ToArray().Count(c => c == 1)); // all born but the ring
            Assert.Contains("B0", Assert.Throws<ArgumentException>(() => new MultiStateHashLife("B0/S8History")).Message);
        }

        [Fact]
        public void HistoryCellsAreCheckedAndFramedAsThemselves()
        {
            var w = new LifeLike("B3/S23History", 4, 3, Boundary.Torus);
            byte[] cells = Enumerable.Range(0, 12).Select(i => (byte)(i % 7)).ToArray();
            w.SetState(cells);
            Assert.Equal((7, RuleVariant.History), (w.States, w.CompiledRule.Variant));
            Assert.Equal(cells, w.Frame());
            Assert.Throws<ArgumentException>(() => w.SetState(Enumerable.Repeat((byte)7, 12).ToArray()));
            Assert.Equal(cells, w.State.ToArray()); // refused whole: nothing written
            Assert.Throws<ArgumentOutOfRangeException>(() => w.SetCell(0, 0, 7));
            w.SetCell(0, 0, 6);
            Assert.Equal(6, w.State[0]);
            var plain = new LifeLike("B3/S23", 4, 3, Boundary.Torus);
            plain.SetState(Enumerable.Repeat((byte)6, 12).ToArray());
            Assert.Equal((2, (byte)1), (plain.States, plain.State.ToArray().Max())); // nonzero is alive
            w.FillRandom(0, 0, 3, 2, 0.5, 4);
            Assert.True(w.State.ToArray().All(c => c <= 1)); // the two-state rule's soup
        }

        [Fact]
        public void StepAndWriteFrameAllocateNothing()
        {
            var w = new LifeLike("B3/S23History", 64, 48, new Topology(Boundary.Klein));
            w.SeedSoup(0.4, 3);
            var frame = new byte[64 * 48];
            w.Step(4);
            w.WriteFrame(frame);
            long before = GC.GetAllocatedBytesForCurrentThread();
            w.Step(10);
            w.WriteFrame(frame);
            Assert.Equal(0, GC.GetAllocatedBytesForCurrentThread() - before);
        }

        [Fact]
        public void AdvanceSelectionKeepsStates()
        {
            var w = new LifeLike("B3/S23History", 20, 12, new Topology(Boundary.Klein));
            w.SeedSoup(0.35, 2);
            w.Step(3);
            byte[] outside = w.State.ToArray();
            w.AdvanceSelection(4, 3, 12, 8, 5);
            Assert.True(w.State.Slice(0, 3 * 20).SequenceEqual(outside.AsSpan(0, 3 * 20)));
            Assert.True(w.State.ToArray().Max() <= 2);
            Assert.Equal(3, w.Generation);
        }

        // -- files ----------------------------------------------------------------------------------

        [Fact]
        public void RleReadsAndWritesHistory()
        {
            string text = "x = 5, y = 3, rule = LifeHistory\n.ABA$CDEF.$2B!\n";
            RlePattern decoded = Patterns.RleDecode(text);
            Assert.Equal("LifeHistory", decoded.Rule);
            Assert.Equal(new byte[] { 0, 1, 2, 1, 0, 3, 4, 5, 6, 0, 2, 2, 0, 0, 0 }, decoded.Cells);
            string written = Patterns.RleEncode(decoded.Cells, decoded.Width, decoded.Height, decoded.Rule!);
            Assert.Equal("x = 5, y = 3, rule = B3/S23History\n.ABA$CDEF$2B!\n", written);
            // Two-state letters under a History header: the file is extended, b and o still 0 and 1.
            Assert.Equal(new byte[] { 0, 1, 0 }, Patterns.RleDecode("x = 3, y = 1, rule = B3/S23History\nbob!\n").Cells);
            Assert.Equal(new byte[] { 2, 15, 2 }, Patterns.RleDecode("x = 3, y = 1, rule = B3/S23History\nBOB!\n").Cells);
            Assert.Equal(
                "x = 3, y = 1, rule = B36/S23History\nb2o!\n",
                Patterns.RleEncode(new byte[] { 0, 1, 1 }, 3, 1, "B36/S23History"));
            string bounded = "#CXRLE Pos=-1,0 Gen=4\nx = 3, y = 1, rule = B3/S23History:T10,6\nFAB!\n";
            PatternFile found = PatternFiles.Read(bounded);
            Assert.NotNull(found.BoundedGrid);
            Assert.Equal(("B3/S23History", (byte)6, new BigInteger(4)), (found.Rule, found.Cells.Max(), found.Generation));
            Assert.False(PatternFiles.Measure(bounded).TwoState);
        }

        [Fact]
        public void HistoryFilesGoToTheMultiStateUniverse()
        {
            string text = "#CXRLE Pos=-2,3 Gen=7\nx = 4, y = 2, rule = LifeHistory\nFFFF$.AB!\n";
            Assert.ThrowsAny<FormatException>(() => PatternFiles.ReadUniverse(text));
            Assert.Contains(
                "History rule of 7 states", Assert.Throws<ArgumentException>(() => new HashLife("B3/S23History")).Message);
            Assert.ThrowsAny<ArgumentException>(() => PatternFiles.ReadUniverse("#Life 1.05\n#R B3/S23History\n*\n"));
            MultiStateHashLife u = MultiStateFiles.ReadUniverse(Encoding.ASCII.GetBytes(text)).Universe;
            Assert.Equal(("B3/S23History", 7, new BigInteger(7)), (u.Rule, u.States, u.Generation));
            Assert.Equal(new byte[] { 6, 6, 6, 6, 0, 1, 2, 0 }, u.GetRect(-2, 3, 1, 4));
            MultiStateHashLife again = MultiStateHashLife.FromMacrocell(u.ToMacrocell());
            Assert.Equal(u.ToMacrocell(), again.ToMacrocell());
            Assert.Equal(u.ToMacrocell(), MultiStateHashLife.FromRle(u.ToRle()).ToMacrocell());
            Assert.Same(StateRules.Compile("lifehistory"), StateRules.Compile("B3/S23History"));
            Assert.Equal("B3/S23History", StateRules.Compile(" b3/s23HISTORY ").Canonical);
        }

        [Fact]
        public void ThePlaneAgreesWithAGridInsideAWall()
        {
            foreach (string rule in new[] { "B3/S23History", "B2/S34HHistory", "B2/S013VHistory" })
            {
                const int width = 22, height = 18;
                byte[] inner = Soup(width - 2, height - 2, 11);
                var grid = new byte[width * height];
                for (int y = 0; y < height; y++)
                    for (int x = 0; x < width; x++)
                        grid[y * width + x] = x == 0 || y == 0 || x == width - 1 || y == height - 1
                            ? (byte)6
                            : inner[(y - 1) * (width - 2) + x - 1];
                grid[4 * width + 5] = 3;
                grid[9 * width + 9] = 4;
                grid[12 * width + 15] = 5;
                var u = new MultiStateHashLife(rule);
                u.SetRect(-5, 7, grid, width, height);
                var g = new LifeLike(rule, width, height, Boundary.Dead);
                g.SetState(grid);
                foreach (int gen in new[] { 1, 2, 3, 10, 64, 200 })
                {
                    u.Step(gen - u.Generation);
                    g.Step(gen - g.Generation);
                    Assert.True(u.GetRect(-5, 7, 16, 24).AsSpan().SequenceEqual(g.State), $"{rule} at {gen}");
                    Assert.Equal(g.State.ToArray().Count(c => c != 0), (int)u.Population);
                }
            }
        }

        [Fact]
        public void RandomFillOnThePlaneIsTheTwoStateUniverses()
        {
            var u = new MultiStateHashLife("B3/S23History");
            u.FillRandom(-7, 2, 12, 9, 0.4, 5);
            var two = new HashLife();
            two.FillRandom(-7, 2, 12, 9, 0.4, 5);
            Assert.Equal(two.GetRect(-7, 2, 12, 9), u.GetRect(-7, 2, 12, 9));
            Assert.Contains(
                "Life-like tool",
                Assert.Throws<ArgumentException>(() => new MultiStateHashLife("WireWorld").FillRandom(0, 0, 1, 1, 0.5, 1)).Message);
        }

        [Fact]
        public void ALifePatternPastesIntoHistoryAndBack()
        {
            LifeRule life = RuleString.Compile("B3/S23");
            LifeRule history = RuleString.Compile("LifeHistory", true);
            byte[] glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };
            byte[] copy = (byte[])glider.Clone();
            history.ConvertCells(copy);
            Assert.Equal(glider, copy); // unchanged
            byte[] marked = { 2, 3, 4, 5, 6, 1 };
            life.ConvertCells(marked);
            Assert.Equal(new byte[] { 0, 1, 0, 1, 0, 1 }, marked);
        }
    }
}
