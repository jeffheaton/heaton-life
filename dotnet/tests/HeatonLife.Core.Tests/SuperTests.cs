using System;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Super rules (spec/super.md): 26 states over any Life-like rule. The on cells must run the
    /// base rule exactly, on every neighborhood and topology; states 0–6 behave as History's; the
    /// trails, the no-trail cells, the labels and a newborn's state follow super.md's tables; and the
    /// rule reads, writes and runs on grids, in RLE and on the unbounded plane. The Python
    /// reference's tests/test_super.py.
    /// </summary>
    public class SuperTests
    {
        private const string LifeMoreMap =
            "MAPARYXfhZofugWaH7oaIDogBZofuhogOiA6IDogIAAgAAWaH7oaIDogGiA6ICAAIAAaIDogIAAgACAAIAAAAAAAA";

        public static TheoryData<string> Rules() => new TheoryData<string>
        {
            "B3/S23Super", "B36/S23Super", "B2/S34HSuper", "B2/S013VSuper", "B3/S2-i34qSuper", LifeMoreMap + "Super",
        };

        private static readonly Topology[] Topologies =
        {
            new Topology(Boundary.Dead), new Topology(Boundary.Torus), new Topology(Boundary.Torus, 3, TopologyAxis.Y),
            new Topology(Boundary.Klein), new Topology(Boundary.Cross), new Topology(Boundary.Sphere),
        };

        /// <summary>Random Super states from PCG32 (test input), half the cells off; without
        /// <paramref name="walls"/> no boundary cell.</summary>
        private static byte[] States(int width, int height, ulong seed, bool walls = true)
        {
            var random = new Pcg32(seed);
            var cells = new byte[width * height];
            for (int i = 0; i < cells.Length; i++)
            {
                byte state = (byte)(random.NextU32() % 26);
                bool off = random.NextU32() % 2 == 0;
                cells[i] = off || (!walls && state == 6) ? (byte)0 : state;
            }
            return cells;
        }

        private static LifeLike World(string rule, byte[] cells, int width, int height, Boundary boundary = Boundary.Dead)
        {
            var world = new LifeLike(rule, width, height, boundary);
            world.SetState(cells);
            return world;
        }

        /// <summary>A base-36 state digit: 0–9, then a–z for 10–35.</summary>
        private static byte Digit(char c) => (byte)(c <= '9' ? c - '0' : c - 'a' + 10);

        private static byte[] Drawn(int width, params string[] rows)
        {
            var cells = new byte[width * rows.Length];
            for (int y = 0; y < rows.Length; y++)
                for (int x = 0; x < rows[y].Length; x++)
                    cells[y * width + x] = rows[y][x] == '.' ? (byte)0 : Digit(rows[y][x]);
            return cells;
        }

        // -- the rule ------------------------------------------------------------------------------

        [Fact]
        public void TheStatesAreNamedAsTheSpecNamesThem()
        {
            // spec/super.md "States": the names are the table's, states 0-6 History's (Python's
            // super_rules.NAMES pins the same table).
            Assert.Equal(TestPaths.SpecStateNames("super.md"), Super.Names);
            Assert.Equal(Super.States, Super.Names.Count);
            Assert.Equal(History.Names, Super.Names.Take(History.States));
        }

        [Fact]
        public void SuperRulesCompileOnlyWhereVariantsAreAskedFor()
        {
            LifeRule rule = RuleString.Compile("b36 / s23super", variants: true);
            Assert.Equal(("B36/S23Super", RuleVariant.Super, 26), (rule.Canonical, rule.Variant, rule.States));
            Assert.Equal("B36/S23", rule.Base.Canonical);
            Assert.True(rule.Table.SequenceEqual(RuleString.Compile("B36/S23").Table));
            Assert.Equal("B3/S23Super", RuleString.Compile("LifeSuper", true).Canonical);
            Assert.Equal("B3/S23Super", RuleString.Compile(" lifesuper ", true).Canonical);
            Assert.Equal("B2/S34HSuper", RuleString.Compile("B2/S34hSUPER", true).Canonical);
            foreach (string text in new[] { "B3/S23Super", "LifeSuper", "MAP" + new string('A', 86) + "Super" })
            {
                Assert.False(RuleString.TryCompile(text, out _, out string? reason));
                Assert.Equal("a Super rule has 26 states, not 2", reason);
            }
            Assert.False(RuleString.TryCompile("B3/S23Supe", true, out _, out string? supe));
            Assert.Equal("unexpected 'Supe' after the survival counts", supe);
            LifeRule plain = RuleString.Compile("MAP" + new string('A', 81) + "Super", true);
            Assert.Equal((RuleVariant.None, RuleNeighborhood.Moore), (plain.Variant, plain.Neighborhood));
            foreach (string stem in new[] { new string('A', 86), new string('A', 22), new string('A', 6) })
                Assert.Equal(RuleVariant.Super, RuleString.Compile("MAP" + stem + "==super", true).Variant);
        }

        [Fact]
        public void TheSameBaseAndConvertingCells()
        {
            LifeRule life = RuleString.Compile("B3/S23");
            LifeRule history = RuleString.Compile("LifeHistory", true);
            LifeRule super = RuleString.Compile("LifeSuper", true);
            Assert.True(super.SameBase(life) && super.SameBase(history));
            Assert.False(super.SameBase(RuleString.Compile("B36/S23Super", true)));
            byte[] cells = { 0, 1, 2, 5, 6, 7, 8, 9, 10, 14, 24, 25 };
            byte[] two = (byte[])cells.Clone(), seven = (byte[])cells.Clone(), many = (byte[])cells.Clone();
            life.ConvertCells(two);
            history.ConvertCells(seven);
            super.ConvertCells(many);
            Assert.Equal(new byte[] { 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1 }, two);
            Assert.Equal(new byte[] { 0, 1, 2, 5, 6, 1, 0, 1, 0, 0, 0, 1 }, seven);
            Assert.Equal(cells, many);
        }

        // -- the evolution -------------------------------------------------------------------------

        /// <summary>The grid's step and the multi-state universe's cell function agree on random
        /// blocks of every state, under every topology.</summary>
        [Theory]
        [MemberData(nameof(Rules))]
        public void TheGridStepIsTheCellFunction(string text)
        {
            SuperRule cell = SuperRule.For(RuleString.Compile(text, true));
            ulong seed = 1;
            foreach (Topology topology in Topologies)
            {
                const int size = 10;
                byte[] cells = States(size, size, seed++);
                var world = new LifeLike(text, size, size, topology);
                world.SetState(cells);
                var halo = new Halo(topology, size, size);
                var padded = new byte[halo.Length];
                int stride = halo.Columns;
                for (int g = 0; g < 3; g++)
                {
                    halo.Fill(cells, padded, 0);
                    world.Step();
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
                    cells = world.State.ToArray();
                }
            }
        }

        public static TheoryData<string, int> RulesAndTopologies()
        {
            var data = new TheoryData<string, int>();
            foreach (string rule in Rules())
                for (int t = 0; t < Topologies.Length; t++)
                    data.Add(rule, t);
            return data;
        }

        /// <summary>Without boundary cells, which cells are on is the base rule's run, whatever the
        /// other states.</summary>
        [Theory]
        [MemberData(nameof(RulesAndTopologies))]
        public void OnCellsRunTheBaseRule(string text, int topologyIndex)
        {
            Topology topology = Topologies[topologyIndex];
            LifeRule rule = RuleString.Compile(text, true);
            byte[] start = States(24, 24, 9, walls: false);
            var two = new LifeLike(rule.Base.Canonical, 24, 24, topology);
            two.SetState(start.Select(c => (byte)(c & 1)).ToArray());
            var many = new LifeLike(rule.Canonical, 24, 24, topology);
            many.SetState(start);
            for (int g = 0; g < 20; g++)
            {
                two.Step();
                many.Step();
                Assert.True(two.State.SequenceEqual(many.State.ToArray().Select(c => (byte)(c & 1)).ToArray()), $"{text} at {g}");
            }
        }

        [Theory]
        [InlineData("B3/S23")]
        [InlineData("B36/S23")]
        [InlineData("B2/S34H")]
        [InlineData("B2/S013V")]
        public void AHistoryPatternRunsAsUnderTheHistoryRule(string baseRule)
        {
            byte[] cells = States(30, 30, 4).Select(c => (byte)(c % 7 == 6 ? 0 : c % 7)).ToArray();
            for (int y = 3; y < 27; y += 6)
                cells[y * 30 + 4] = 6;
            LifeLike history = World(baseRule + "History", cells, 30, 30), super = World(baseRule + "Super", cells, 30, 30);
            foreach (int n in new[] { 1, 2, 5, 20 })
            {
                history.Step(n);
                super.Step(n);
                Assert.True(history.State.SequenceEqual(super.State), $"{baseRule} at {super.Generation}");
            }
        }

        [Fact]
        public void EachStateChangesAsTheTableSays()
        {
            const int width = 24, height = 12;
            var cells = new byte[width * height];
            byte[] lone = { 1, 3, 5, 7, 9, 11, 13, 25 };
            for (int i = 0; i < lone.Length; i++)
                cells[1 * width + 1 + 3 * i] = lone[i];
            cells[4 * width + 1] = 7;
            cells[4 * width + 2] = 9;
            cells[5 * width + 1] = 13;
            cells[5 * width + 2] = 25;
            cells[5 * width + 6] = cells[5 * width + 7] = cells[5 * width + 8] = 13;
            cells[4 * width + 7] = 4;
            cells[6 * width + 7] = 8;
            cells[4 * width + 12] = 14;
            cells[4 * width + 15] = 16;
            cells[4 * width + 18] = 24;
            cells[7 * width + 12] = 16;
            cells[7 * width + 13] = 1;
            cells[7 * width + 16] = 24;
            cells[7 * width + 17] = 1;
            cells[7 * width + 20] = 16;
            cells[7 * width + 21] = 14;
            cells[9 * width + 12] = 18;
            cells[9 * width + 13] = 20;
            cells[9 * width + 14] = 22;
            LifeLike w = World("B3/S23Super", cells, width, height);
            w.Step();
            byte At(int x, int y) => w.State[y * width + x];
            Assert.Equal(new byte[] { 2, 4, 4, 8, 10, 12, 0, 0 }, Enumerable.Range(0, 8).Select(i => At(1 + 3 * i, 1)).ToArray());
            Assert.Equal((7, 9, 13, 25), ((int)At(1, 4), (int)At(2, 4), (int)At(1, 5), (int)At(2, 5)));
            Assert.Equal((3, 13, 7), ((int)At(7, 4), (int)At(7, 5), (int)At(7, 6))); // born into 4 and 8: 3 and 7
            Assert.Equal((0, 0), ((int)At(6, 5), (int)At(8, 5))); // the blinker's ends leave no trail
            Assert.Equal((0, 16, 24), ((int)At(12, 4), (int)At(15, 4), (int)At(18, 4)));
            Assert.Equal((14, 2), ((int)At(12, 7), (int)At(13, 7)));
            Assert.Equal((18, 2), ((int)At(16, 7), (int)At(17, 7)));
            Assert.Equal((14, 0), ((int)At(20, 7), (int)At(21, 7)));
            Assert.Equal((18, 18, 20), ((int)At(12, 9), (int)At(13, 9), (int)At(14, 9)));
            w.Step();
            // The blinker turns back: its ends are born of parents 3, 13 and 7, which mix, so 1.
            Assert.Equal((1, 13, 1), ((int)At(6, 5), (int)At(7, 5), (int)At(8, 5)));
            Assert.Equal((4, 8), ((int)At(7, 4), (int)At(7, 6)));
            Assert.Equal((18, 18, 18), ((int)At(12, 9), (int)At(13, 9), (int)At(14, 9)));
            Assert.Equal(0, At(12, 7)); // the vanishing label lasted one generation
        }

        [Fact]
        public void TheCyclingLabelsChaseEachOther()
        {
            LifeLike w = World("B3/S23Super", Drawn(7, ".......", ".imkim.", "......."), 7, 3);
            w.Step();
            // 18 beside 22 becomes 22; 22 beside 20 becomes 20; 20 beside 18 becomes 18; the last
            // 22 has no 20 beside it and stays.
            Assert.Equal(new byte[] { 22, 20, 18, 22, 22 }, w.State.Slice(8, 5).ToArray());
        }

        [Theory]
        [InlineData(13, 13, 13, 13)]
        [InlineData(15, 15, 3, 15)]
        [InlineData(17, 3, 3, 17)]
        [InlineData(9, 9, 9, 9)]
        [InlineData(9, 9, 7, 9)]
        [InlineData(11, 7, 7, 11)]
        [InlineData(13, 15, 7, 13)]
        [InlineData(15, 15, 7, 13)]
        [InlineData(7, 7, 7, 13)]
        [InlineData(11, 9, 7, 1)]
        [InlineData(9, 9, 3, 1)]
        [InlineData(13, 3, 7, 1)]
        [InlineData(9, 9, 13, 1)]
        [InlineData(3, 3, 3, 1)]
        [InlineData(1, 1, 1, 1)]
        [InlineData(5, 5, 5, 1)]
        [InlineData(25, 25, 1, 1)]
        public void ANewbornTakesItsParentsState(byte a, byte b, byte c, byte newborn)
        {
            SuperRule rule = SuperRule.For(RuleString.Compile("B3/S23Super", true));
            foreach (byte target in new byte[] { 0, 2, 10, 12, 14, 16, 18, 20, 22, 24 })
                Assert.Equal(newborn, rule.NextState(a, b, c, 0, target, 0, 0, 0, 0));
            Assert.Equal(newborn, Super.Newborn(new[] { a, b, c }));
        }

        [Fact]
        public void NewbornsOfOtherParentCounts()
        {
            SuperRule two = SuperRule.For(RuleString.Compile("B2/SSuper", true));
            Assert.Equal(13, two.NextState(13, 13, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(13, two.NextState(13, 3, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(9, two.NextState(9, 7, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(13, two.NextState(13, 15, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(1, two.NextState(13, 1, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(1, two.NextState(3, 3, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(1, two.NextState(9, 11, 0, 0, 0, 0, 0, 0, 0));
            Assert.Equal(13, two.NextState(7, 7, 0, 0, 0, 0, 0, 0, 0));
            SuperRule six = SuperRule.For(RuleString.Compile("B36/S23Super", true));
            Assert.Equal(15, six.NextState(15, 15, 15, 15, 0, 15, 3, 0, 0));
            Assert.Equal(9, six.NextState(9, 9, 7, 9, 0, 7, 9, 0, 0));
            Assert.Equal(1, Super.Newborn(ReadOnlySpan<byte>.Empty)); // no parents (B0): 1, as History's
            LifeLike b0 = World("B0/S8Super", new byte[25], 5, 5);
            b0.Step();
            Assert.True(b0.State.ToArray().All(v => v == 1));
            Assert.Throws<ArgumentOutOfRangeException>(() => Super.Newborn(new byte[] { 2 }));
        }

        [Fact]
        public void BoundaryCellsTakeTheirNeighborsAway()
        {
            const int width = 16, height = 9;
            var cells = new byte[width * height];
            cells[2 * width + 2] = 6;
            cells[1 * width + 1] = 7;
            cells[1 * width + 2] = 9;
            cells[1 * width + 3] = 16;
            cells[2 * width + 1] = 8;
            cells[2 * width + 3] = 25;
            cells[3 * width + 1] = 14;
            cells[3 * width + 2] = 11;
            cells[3 * width + 3] = 18;
            cells[1 * width + 10] = 6;
            cells[3 * width + 9] = cells[3 * width + 10] = cells[3 * width + 11] = 1;
            LifeLike w = World("B3/S23Super", cells, width, height);
            w.Step();
            byte At(int x, int y) => w.State[y * width + x];
            Assert.Equal(6, At(2, 2));
            Assert.Equal((0, 10, 0), ((int)At(1, 1), (int)At(2, 1), (int)At(3, 1)));
            Assert.Equal((0, 0), ((int)At(1, 2), (int)At(3, 2)));
            Assert.Equal((0, 12, 0), ((int)At(1, 3), (int)At(2, 3), (int)At(3, 3)));
            Assert.Equal((0, 1, 1), ((int)At(10, 2), (int)At(10, 3), (int)At(10, 4))); // never born beside the wall
            var hex = new byte[25];
            hex[2 * 5 + 2] = 16;
            hex[1 * 5 + 3] = 14; // NE of the label: no hexagonal neighbor of it
            LifeLike hexWorld = World("B3/S23HSuper", hex, 5, 5, Boundary.Torus);
            hexWorld.Step();
            Assert.Equal(16, hexWorld.State[2 * 5 + 2]);
        }

        [Fact]
        public void SuperCellsAreCheckedAndFramedAsThemselves()
        {
            byte[] cells = Enumerable.Range(0, 52).Select(i => (byte)(i % 26)).ToArray();
            LifeLike w = World("B3/S23Super", cells, 13, 4);
            Assert.Equal((26, RuleVariant.Super), (w.States, w.CompiledRule.Variant));
            Assert.Equal(cells, w.Frame());
            Assert.Contains("Super", Assert.Throws<ArgumentException>(() => w.SetState(Enumerable.Repeat((byte)26, 52).ToArray())).Message);
            Assert.Equal(cells, w.State.ToArray()); // a refused state changes nothing
            Assert.Throws<ArgumentOutOfRangeException>(() => w.SetCell(0, 0, 26));
            w.SetCell(0, 0, 25);
            Assert.Equal(25, w.State[0]);
            w.FillRandom(0, 0, 12, 3, 0.5, 4);
            Assert.True(w.State.ToArray().All(v => v <= 1)); // the two-state rule's soup
        }

        [Fact]
        public void StepsFramesAndAdvancesBehaveAsOnEveryGrid()
        {
            var w = new LifeLike("B3/S23Super", 64, 48, new Topology(Boundary.Klein, 1));
            w.SetState(States(64, 48, 3));
            var frame = new byte[64 * 48];
            w.Step(2); // warm up
            w.WriteFrame(frame);
            long before = GC.GetAllocatedBytesForCurrentThread();
            w.Step(20);
            w.WriteFrame(frame);
            Assert.Equal(0, GC.GetAllocatedBytesForCurrentThread() - before);
            byte[] cells = w.State.ToArray();
            using var source = new CancellationTokenSource();
            source.Cancel();
            Assert.Throws<OperationCanceledException>(() => w.AdvanceSelection(4, 4, 40, 30, 5, source.Token));
            Assert.Equal(cells, w.State.ToArray()); // a canceled advance leaves the world as it was
            Assert.Equal(22, w.Generation);
        }

        // -- files ---------------------------------------------------------------------------------

        [Fact]
        public void RleReadsAndWritesSuper()
        {
            const string text = "x = 5, y = 2, rule = LifeSuper\nMpAH2.$oDbX!\n";
            RlePattern decoded = Patterns.RleDecode(text);
            Assert.Equal("LifeSuper", decoded.Rule);
            Assert.Equal(new byte[] { 13, 25, 8, 0, 0, 1, 4, 0, 24, 0 }, decoded.Cells);
            string written = Patterns.RleEncode(decoded.Cells, decoded.Width, decoded.Height, decoded.Rule!);
            Assert.Equal("x = 5, y = 2, rule = B3/S23Super\nMpAH$AD.X!\n", written);
            Assert.Equal(decoded.Cells, Patterns.RleDecode(written).Cells);
            Assert.Equal(new byte[] { 2, 15, 2 }, Patterns.RleDecode("x = 3, y = 1, rule = B3/S23Super\nBOB!\n").Cells);
            const string bounded = "#CXRLE Pos=-1,0 Gen=4\nx = 3, y = 1, rule = B3/S23Super:T10,6\nFpAB!\n";
            PatternFile found = PatternFiles.Read(bounded);
            Assert.NotNull(found.BoundedGrid);
            Assert.Equal(("B3/S23Super", (byte)25, new BigInteger(4)), (found.Rule, found.Cells.Max(), found.Generation));
            Assert.False(PatternFiles.Measure(bounded).TwoState);
        }

        [Fact]
        public void SuperFilesGoToTheMultiStateUniverse()
        {
            const string text = "#CXRLE Pos=-2,3 Gen=7\nx = 4, y = 2, rule = LifeSuper\nFFFF$.MpAX!\n";
            Assert.ThrowsAny<FormatException>(() => PatternFiles.ReadUniverse(text));
            Assert.Contains("Super rule of 26 states", Assert.Throws<ArgumentException>(() => new HashLife("B3/S23Super")).Message);
            Assert.ThrowsAny<ArgumentException>(() => PatternFiles.ReadUniverse("#Life 1.05\n#R B3/S23Super\n*\n"));
            MultiStateHashLife u = MultiStateFiles.ReadUniverse(Encoding.ASCII.GetBytes(text)).Universe;
            Assert.Equal(("B3/S23Super", 26, new BigInteger(7)), (u.Rule, u.States, u.Generation));
            Assert.Equal(new byte[] { 6, 6, 6, 6, 0, 13, 25, 24 }, u.GetRect(-2, 3, 1, 4));
            MultiStateHashLife again = MultiStateHashLife.FromMacrocell(u.ToMacrocell());
            Assert.Equal(u.ToMacrocell(), again.ToMacrocell());
            Assert.Equal(u.ToMacrocell(), MultiStateHashLife.FromRle(u.ToRle()).ToMacrocell());
            Assert.Same(StateRules.Compile("lifesuper"), StateRules.Compile("B3/S23Super"));
            Assert.Contains("B0", Assert.Throws<ArgumentException>(() => new MultiStateHashLife("B0/S8Super")).Message);
        }

        [Fact]
        public void ThePlaneAgreesWithAGridInsideAWall()
        {
            foreach (string rule in new[] { "B3/S23Super", "B2/S34HSuper", "B2/S013VSuper" })
            {
                const int width = 22, height = 18;
                byte[] inner = States(width - 2, height - 2, 11, walls: false);
                var grid = new byte[width * height];
                for (int y = 0; y < height; y++)
                    for (int x = 0; x < width; x++)
                        grid[y * width + x] = x == 0 || y == 0 || x == width - 1 || y == height - 1
                            ? (byte)6
                            : inner[(y - 1) * (width - 2) + x - 1];
                var u = new MultiStateHashLife(rule);
                u.SetRect(-5, 7, grid, width, height);
                LifeLike g = World(rule, grid, width, height);
                foreach (int gen in new[] { 1, 2, 3, 10, 64, 200 })
                {
                    u.Step(gen - u.Generation);
                    g.Step(gen - g.Generation);
                    Assert.True(u.GetRect(-5, 7, 16, 24).AsSpan().SequenceEqual(g.State), $"{rule} at {gen}");
                    Assert.Equal(g.State.ToArray().Count(v => v != 0), (int)u.Population);
                }
            }
        }

        [Theory]
        [InlineData("B3/S23Super")]
        [InlineData("B2/S/C3")]
        [InlineData("B3/S23History")]
        public void RandomFillOnThePlaneIsTheTwoStateUniverses(string rule)
        {
            var u = new MultiStateHashLife(rule);
            u.FillRandom(-7, 2, 12, 9, 0.4, 5);
            var two = new HashLife();
            two.FillRandom(-7, 2, 12, 9, 0.4, 5);
            Assert.Equal(two.GetRect(-7, 2, 12, 9), u.GetRect(-7, 2, 12, 9));
            Assert.Contains(
                "Life-like tool",
                Assert.Throws<ArgumentException>(() => new MultiStateHashLife("WireWorld").FillRandom(0, 0, 1, 1, 0.5, 1)).Message);
        }
    }
}
