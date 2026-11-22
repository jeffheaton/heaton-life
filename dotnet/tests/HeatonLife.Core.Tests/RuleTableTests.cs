using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The rule-table family (spec/ruletable.md, spec/rule-files.md): the starter set against its
    /// publications' figures and definitions, the grid family's inits, edits, cancellation and
    /// allocation, and rule tables on the unbounded plane and in files. The Python suite's
    /// test_ruletable.py and test_rulefile.py, port for port.
    /// </summary>
    public class RuleTableTests
    {
        private static readonly string[] LangtonFig6 =
        {
            " 22222222",
            "2170140142",
            "2022222202",
            "272    212",
            "212    212",
            "202    212",
            "272    212",
            "21222222122222",
            "207107107111112",
            " 2222222222222",
        };

        private static readonly string[] LangtonFig9 =
        {
            "        2",
            "       212",
            "       272",
            "       202",
            "       212",
            " 222222272  22222222",
            "2111701702 2170140142",
            "2122222212 2022222202",
            "212    272 272    212",
            "202    202 212    212",
            "242    212 202    212",
            "212    272 272    212",
            "2022222202 21222222122222",
            "2410710712 207107107111112",
            " 22222222   2222222222222",
        };

        // Fig. 3 of Byl (1989), every time step as printed.
        private static readonly string[][] BylFig3 =
        {
            new[] { " 22", "2312", "2342", " 25" },
            new[] { " 22", "2142", "2332", " 225" },
            new[] { " 22", "2432", "2133", " 225" },
            new[] { " 22", "2332", "24131", " 225" },
            new[] { " 22", "2312", "23413", " 2252" },
            new[] { " 22", "2142", "233311", " 2242" },
            new[] { " 22", "2432", "21333", " 22422" },
            new[] { " 22", "2332", "241333", " 22422" },
            new[] { " 22", "2312 1", "2341331", " 22422" },
            new[] { " 22", "2142 3", "2334133", " 224222" },
            new[] { " 22  1", "2432", "21334131", " 224222" },
            new[] { " 22", "2332  1", "24133413", " 2242222" },
            new[] { " 22", "2312   1", "234133411", " 2242222" },
            new[] { " 22", "2142 1", "23341334", " 22422222" },
            new[] { " 22", "2432 31", "213341332", " 22422222" },
            new[] { " 22  1", "2332   1", "241334132", " 2242222" },
            new[] { " 22", "2312   32", "234133412", " 2242222" },
            new[] { " 22    1", "2142 1 12", "233413342", " 2242222" },
            new[] { " 22     2", "2432 3 42", "213341332", " 2242222" },
            new[] { " 22  1 22", "2332   32", "241334132", " 2242222" },
            new[] { " 22    2", "2312  132", "234133412", " 2242222" },
            new[] { " 22   22", "2142 5112", "233413342", " 2242222" },
            new[] { " 22   22", "2432 2142", "213345332", " 2242222" },
            new[] { " 22   22", "2332 2432", "241352132", " 2242522" },
            new[] { " 22   22", "2312 2332", "2345 2412", " 2242 52" },
            new[] { " 22   22", "2145 2312", "2332 2342", " 22 2 25" },
            new[] { " 225  22", "2432 2142", "2132 2332", " 22   225" },
            new[] { " 235  22", "2332 2432", "2412 2133", " 22   225" },
        };

        private static (int Width, int Height, byte[] Cells) Grid(string[] rows)
        {
            int width = rows.Max(r => r.Length);
            var cells = new byte[rows.Length * width];
            for (int y = 0; y < rows.Length; y++)
                for (int x = 0; x < rows[y].Length; x++)
                    cells[y * width + x] = rows[y][x] == ' ' ? (byte)0 : (byte)(rows[y][x] - '0');
            return (width, rows.Length, cells);
        }

        private static byte[] Placed((int Width, int Height, byte[] Cells) pattern, int width, int height, int x0, int y0)
        {
            var grid = new byte[width * height];
            for (int y = 0; y < pattern.Height; y++)
                Array.Copy(pattern.Cells, y * pattern.Width, grid, (y0 + y) * width + x0, pattern.Width);
            return grid;
        }

        /// <summary>The rows of a grid's non-zero box as text, each mirrored when asked, 0 as a
        /// space and trailing spaces dropped.</summary>
        private static string[] Text(ReadOnlySpan<byte> cells, int width, int height, bool mirrored = false)
        {
            int x0 = width, x1 = -1, y0 = height, y1 = -1;
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    if (cells[y * width + x] == 0)
                        continue;
                    int mx = mirrored ? width - 1 - x : x;
                    x0 = Math.Min(x0, mx);
                    x1 = Math.Max(x1, mx);
                    y0 = Math.Min(y0, y);
                    y1 = Math.Max(y1, y);
                }
            var rows = new List<string>();
            for (int y = y0; y <= y1; y++)
            {
                var row = new char[x1 - x0 + 1];
                for (int mx = x0; mx <= x1; mx++)
                {
                    int x = mirrored ? width - 1 - mx : mx;
                    byte v = cells[y * width + x];
                    row[mx - x0] = v == 0 ? ' ' : (char)('0' + v);
                }
                rows.Add(new string(row).TrimEnd());
            }
            return rows.ToArray();
        }

        private static int Components(ReadOnlySpan<byte> cells, int width, int height)
        {
            var seen = new bool[cells.Length];
            int count = 0;
            var stack = new Stack<int>();
            for (int start = 0; start < cells.Length; start++)
            {
                if (cells[start] == 0 || seen[start])
                    continue;
                count++;
                seen[start] = true;
                stack.Push(start);
                while (stack.Count > 0)
                {
                    int at = stack.Pop();
                    int x = at % width, y = at / width;
                    foreach ((int nx, int ny) in new[] { (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1) })
                    {
                        int next = ny * width + nx;
                        if (nx >= 0 && nx < width && ny >= 0 && ny < height && cells[next] != 0 && !seen[next])
                        {
                            seen[next] = true;
                            stack.Push(next);
                        }
                    }
                }
            }
            return count;
        }

        // -- the starter set ---------------------------------------------------------------

        [Fact]
        public void TheStarterSet()
        {
            Assert.Equal(
                new[] { "Langtons-Loops", "Byl-Loop", "Evoloop", "Langtons-Ant", "Ant-LLRR", "Ant-RLR" },
                RuleTables.StarterNames.ToArray());
            var expected = new Dictionary<string, (int, string, string)>
            {
                ["Langtons-Loops"] = (8, "vonNeumann", "rotate4"),
                ["Byl-Loop"] = (6, "vonNeumann", "rotate4"),
                ["Evoloop"] = (9, "vonNeumann", "rotate4"),
                ["Langtons-Ant"] = (10, "vonNeumann", "none"),
                ["Ant-LLRR"] = (20, "vonNeumann", "none"),
                ["Ant-RLR"] = (15, "vonNeumann", "none"),
            };
            foreach (var (name, (states, neighborhood, symmetries)) in expected)
            {
                RuleTable rule = RuleTables.Starter(name);
                Assert.Equal(name, rule.Name);
                Assert.Equal((states, neighborhood, symmetries, 4, RuleSource.Table),
                    (rule.States, rule.Neighborhood, rule.Symmetries, rule.Neighbors, rule.Source));
                Assert.Equal(0, rule.NextState(0, 0, 0, 0, 0, 0, 0, 0, 0));
                Assert.Same(rule, RuleTables.Starter(name.ToUpperInvariant()));
                Assert.Same(rule, StateRules.Compile($" {name.ToLowerInvariant()} "));
                Assert.Same(rule, StateRules.Check(rule));
                Assert.Equal(states, rule.Names.Count);
            }
            Assert.Equal(Grid(LangtonFig6).Cells, RuleTables.StarterPattern("Langtons-Loops").Cells);
            Assert.Equal(Grid(LangtonFig6).Cells, RuleTables.StarterPattern("Evoloop").Cells);
            Assert.Equal(new byte[] { 2 }, RuleTables.StarterPattern("Langtons-Ant").Cells);
            Assert.Equal(new byte[] { 4 }, RuleTables.StarterPattern("Ant-LLRR").Cells);
            Assert.Equal(new byte[] { 3 }, RuleTables.StarterPattern("Ant-RLR").Cells);
            Assert.Throws<ArgumentException>(() => RuleTables.Starter("Codd"));
            Assert.Null(RuleTables.StarterOrNull(" Langtons-Loops"));
        }

        [Fact]
        public void LangtonsLoopReproducesAsFigure9Shows()
        {
            var w = new RuleTableCA(RuleTables.Starter("Langtons-Loops"), 48, 40,
                Placed(Grid(LangtonFig6), 48, 40, 8, 14), Boundary.Dead);
            w.Step(151);
            // The figure prints a blank cell as 0 inside the loops and as a space around them.
            Assert.Equal(LangtonFig9.Select(r => r.Replace('0', ' ').TrimEnd()).ToArray(), Text(w.State, 48, 40));
        }

        [Fact]
        public void BylsLoopRunsAsFigure3ShowsMirrored()
        {
            (int pw, int ph, byte[] pattern) = RuleTables.StarterPattern("Byl-Loop");
            var w = new RuleTableCA(RuleTables.Starter("Byl-Loop"), 30, 30, Placed((pw, ph, pattern), 30, 30, 13, 13));
            for (int t = 0; t < BylFig3.Length; t++)
            {
                Assert.Equal(BylFig3[t], Text(w.State, 30, 30, mirrored: true));
                w.Step();
            }
        }

        [Fact]
        public void TheEvoloopsFirstOffspringSeparatesAtGeneration128()
        {
            var w = new RuleTableCA(RuleTables.Starter("Evoloop"), 72, 72, Placed(Grid(LangtonFig6), 72, 72, 20, 30));
            w.Step(127);
            Assert.Equal(1, Components(w.State, 72, 72));
            w.Step();
            Assert.Equal(2, Components(w.State, 72, 72));
        }

        /// <summary>A direct simulation of the ant (spec/ruletable.md "The ants") from where the
        /// starter init puts it, facing north: its cells, and where it was after each step.</summary>
        private static (byte[] Cells, List<(int X, int Y)> Path) Ant(string turns, int steps, int width, int height)
        {
            int k = turns.Length;
            var colors = new int[width * height];
            int x = (width - 1) / 2, y = (height - 1) / 2, d = 0;
            var path = new List<(int, int)> { (x, y) };
            for (int i = 0; i < steps; i++)
            {
                int color = colors[y * width + x];
                d = (d + (turns[color] == 'R' ? 1 : 3)) % 4;
                colors[y * width + x] = (color + 1) % k;
                x += new[] { 0, 1, 0, -1 }[d];
                y += new[] { -1, 0, 1, 0 }[d];
                path.Add((x, y));
            }
            var cells = new byte[colors.Length];
            for (int i = 0; i < cells.Length; i++)
                cells[i] = (byte)colors[i];
            cells[y * width + x] = (byte)(k + 4 * colors[y * width + x] + d);
            return (cells, path);
        }

        [Theory]
        [InlineData("Langtons-Ant", "RL", 2500, 60, 50)]
        [InlineData("Ant-LLRR", "LLRR", 4000, 32, 32)]
        [InlineData("Ant-RLR", "RLR", 3000, 40, 40)]
        public void TheAntsRunAsTheirDefinitionsSay(string name, string turns, int steps, int width, int height)
        {
            var w = new RuleTableCA(name, width, height);
            w.Step(steps);
            Assert.Equal(Ant(turns, steps, width, height).Cells, w.State.ToArray());
        }

        [Fact]
        public void LangtonsAntBuildsItsHighway()
        {
            List<(int X, int Y)> path = Ant("RL", 11000, 80, 56).Path;
            for (int t = 9975; t < 10896; t++)
            {
                (int dx, int dy) = (path[t + 104].X - path[t].X, path[t + 104].Y - path[t].Y);
                Assert.Equal(t >= 9976, (dx, dy) == (-2, 2));
            }
        }

        [Fact]
        public void LlrrGrowsSymmetrically()
        {
            var w = new RuleTableCA("Ant-LLRR", 32, 32);
            w.Step(4000);
            byte[] colors = w.State.ToArray().Select(v => (byte)(v >= 4 ? (v - 4) / 4 : v)).ToArray();
            string[] rows = Text(colors, 32, 32);
            string[] mirrored = Text(colors, 32, 32, mirrored: true);
            Assert.True(rows.SequenceEqual(mirrored) || rows.SequenceEqual(rows.Reverse()));
        }

        // -- the format ----------------------------------------------------------------------

        [Theory]
        [InlineData("vonNeumann", "none", 1)]
        [InlineData("vonNeumann", "rotate4", 4)]
        [InlineData("vonNeumann", "rotate4reflect", 8)]
        [InlineData("vonNeumann", "reflect_horizontal", 2)]
        [InlineData("vonNeumann", "permute", 24)]
        [InlineData("Moore", "rotate4", 4)]
        [InlineData("Moore", "rotate8", 8)]
        [InlineData("Moore", "rotate4reflect", 8)]
        [InlineData("Moore", "rotate8reflect", 16)]
        [InlineData("Moore", "reflect_horizontal", 2)]
        [InlineData("Moore", "permute", 40320)]
        [InlineData("hexagonal", "rotate2", 2)]
        [InlineData("hexagonal", "rotate3", 3)]
        [InlineData("hexagonal", "rotate6", 6)]
        [InlineData("hexagonal", "rotate6reflect", 12)]
        [InlineData("hexagonal", "permute", 720)]
        [InlineData("oneDimensional", "reflect", 2)]
        [InlineData("oneDimensional", "permute", 2)]
        public void VariantsAreDistinctPermutations(string neighborhood, string symmetries, int count)
        {
            int[][] orders = RuleFileParser.VariantOrders(neighborhood, symmetries);
            Assert.Equal(count, orders.Length);
            Assert.Equal(count, orders.Select(o => string.Join(",", o)).Distinct().Count());
            int k = RuleFileParser.Ring(neighborhood).Length;
            Assert.Equal(Enumerable.Range(0, k), orders[0]);
            Assert.All(orders, o => Assert.Equal(Enumerable.Range(0, k), o.OrderBy(v => v)));
        }

        [Fact]
        public void ReflectionSwapsEastAndWest()
        {
            Assert.Equal(new[] { 0, 7, 6, 5, 4, 3, 2, 1 }, RuleFileParser.VariantOrders("Moore", "reflect")[1]);
            Assert.Equal(new[] { 1, 0 }, RuleFileParser.VariantOrders("oneDimensional", "reflect")[1]);
            Assert.Equal(new[] { 0, 3, 2, 1 }, RuleFileParser.VariantOrders("vonNeumann", "reflect_horizontal")[1]);
        }

        [Fact]
        public void ATreeWrittenAndReadBackIsTheSameTree()
        {
            foreach (string name in RuleTables.StarterNames)
            {
                RuleTable rule = RuleTables.Starter(name);
                RuleTable again = RuleTable.Parse("@RULE Again\n@TREE\n" + rule.TreeText());
                Assert.Equal(rule.TreeText(), again.TreeText());
                Assert.Equal(RuleSource.Tree, again.Source);
                Assert.Null(again.Neighborhood);
                Assert.Null(again.Symmetries);
            }
        }

        [Fact]
        public void TheGridWalksTheTreeAsTheCellFunctionDoes()
        {
            foreach (string name in RuleTables.StarterNames)
            {
                RuleTable rule = RuleTables.Starter(name);
                var rng = new Pcg32(9);
                var cells = new byte[20 * 16];
                for (int i = 0; i < cells.Length; i++)
                    cells[i] = (byte)(rng.NextU32() % (uint)rule.States);
                var w = new RuleTableCA(rule, 20, 16, cells, new Topology(Boundary.Torus));
                w.Step();
                for (int y = 0; y < 16; y++)
                    for (int x = 0; x < 20; x++)
                    {
                        byte At(int dx, int dy) => cells[((y + dy + 16) % 16) * 20 + (x + dx + 20) % 20];
                        byte expected = rule.NextState(
                            At(-1, -1), At(0, -1), At(1, -1), At(-1, 0), At(0, 0), At(1, 0), At(-1, 1), At(0, 1), At(1, 1));
                        Assert.Equal(expected, w.State[y * 20 + x]);
                    }
            }
        }

        [Fact]
        public void ErrorsCarryTheReasonAndTheLine()
        {
            Assert.False(RuleTable.TryParse("@RULE X\n@TABLE\nn_states:9\n", out RuleTable? rule, out RuleFileException? error));
            Assert.Null(rule);
            Assert.Equal(("'neighborhood' is missing", (int?)null), (error!.Reason, error.Line));
            var thrown = Assert.Throws<RuleFileException>(() => RuleTable.Parse("@RULE\n"));
            Assert.Equal("invalid rule file: line 1: '@RULE' has no name (spec/rule-files.md)", thrown.Message);
            Assert.IsAssignableFrom<FormatException>(thrown);
            Assert.Throws<ArgumentNullException>(() => RuleTable.Parse(null!));
        }

        // -- the grid family -----------------------------------------------------------------

        [Fact]
        public void Inits()
        {
            var w = new RuleTableCA("Byl-Loop", 10, 9);
            (int pw, int ph, byte[] pattern) = RuleTables.StarterPattern("Byl-Loop");
            Assert.Equal(Placed((pw, ph, pattern), 10, 9, 3, 2), w.State.ToArray());
            w.SeedBlank();
            Assert.All(w.State.ToArray(), v => Assert.Equal(0, v));

            var evo = new RuleTableCA("Evoloop", 20, 10);
            evo.SeedSoup(5, 0.4);
            var rng = new Pcg32(5);
            ulong threshold = (ulong)(0.4 * 4294967296.0);
            for (int i = 0; i < 200; i++)
            {
                uint draw = rng.NextU32();
                Assert.Equal(draw < threshold ? (byte)(1 + draw % 8) : (byte)0, evo.State[i]);
            }
            Assert.Throws<ArgumentException>(() => new RuleTableCA("Langtons-Loops", 14, 20));
            RuleTable renamed = RuleTable.Parse(RuleTables.Starter("Byl-Loop").Text.Replace("@RULE Byl-Loop", "@RULE B"));
            Assert.Throws<ArgumentException>(() => new RuleTableCA(renamed, 16, 16, new Topology(Boundary.Dead)));
            RuleTable copy = RuleTable.Parse(RuleTables.Starter("Byl-Loop").Text); // the same rule, read again
            Assert.Contains(new RuleTableCA(copy, 8, 8, new Topology(Boundary.Dead)).State.ToArray(), v => v != 0);
            Assert.Throws<ArgumentException>(() => new RuleTableCA(RuleTables.Starter("Byl-Loop"), 4, 4, new byte[] { 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 }));
        }

        [Fact]
        public void ResetReplaysTheInit()
        {
            var w = new RuleTableCA("Evoloop", 16, 16);
            byte[] starter = w.State.ToArray();
            w.Step(5);
            Assert.Equal(5, w.Generation);
            w.Reset(77); // the starter init draws nothing: a seed changes nothing
            Assert.Equal(0, w.Generation);
            Assert.Equal(starter, w.State.ToArray());
            w.SeedSoup(3);
            byte[] soup = w.State.ToArray();
            w.Step(2);
            w.Reset();
            Assert.Equal(soup, w.State.ToArray());
            w.Reset(4);
            Assert.NotEqual(soup, w.State.ToArray());
            var cells = Enumerable.Repeat((byte)2, 256).ToArray();
            w.SetState(cells, 7);
            Assert.Equal(7, w.Generation);
            w.SetState(new byte[256], 0, keepStart: true);
            w.Reset();
            Assert.Equal(cells, w.State.ToArray());
            Assert.Throws<ArgumentException>(() => w.SetState(Enumerable.Repeat((byte)9, 256).ToArray()));
            Assert.Throws<ArgumentException>(() => w.SetState(new byte[255]));
            Assert.Equal(cells, w.State.ToArray());
        }

        [Fact]
        public void CellsClearAndFrame()
        {
            var w = new RuleTableCA(RuleTables.Starter("Langtons-Loops"), 20, 16, new Topology(Boundary.Klein, 2, TopologyAxis.Y));
            Assert.Equal(8, w.States);
            Assert.Equal(Boundary.Klein, w.Boundary);
            Assert.Equal(w.State.ToArray(), w.Frame());
            w.SetCell(0, 0, 7);
            Assert.Equal(7, w.State[0]);
            Assert.Throws<ArgumentException>(() => w.SetCell(0, 0, 8));
            Assert.Throws<ArgumentOutOfRangeException>(() => w.SetCell(20, 0, 1));
            w.ClearRect(0, 0, 19, 15);
            Assert.All(w.State.ToArray(), v => Assert.Equal(0, v));
            Assert.Throws<ArgumentException>(() => w.WriteFrame(new byte[3]));
        }

        [Fact]
        public void AdvanceSelectionRunsTheRegionAlone()
        {
            var w = new RuleTableCA("Langtons-Loops", 40, 40);
            byte[] before = w.State.ToArray();
            w.AdvanceSelection(10, 10, 30, 30, 20);
            Assert.Equal(0, w.Generation);
            var alone = new byte[1600];
            for (int y = 10; y <= 30; y++)
                Array.Copy(before, y * 40 + 10, alone, y * 40 + 10, 21);
            var isolated = new RuleTableCA(RuleTables.Starter("Langtons-Loops"), 40, 40, alone);
            isolated.Step(20);
            for (int y = 0; y < 40; y++)
                for (int x = 0; x < 40; x++)
                {
                    bool inside = x >= 10 && x <= 30 && y >= 10 && y <= 30;
                    Assert.Equal(inside ? isolated.State[y * 40 + x] : before[y * 40 + x], w.State[y * 40 + x]);
                }
            byte[] now = w.State.ToArray();
            using var source = new CancellationTokenSource();
            source.Cancel();
            Assert.Throws<OperationCanceledException>(() => w.AdvanceOutside(0, 0, 5, 5, 1_000_000_000, source.Token));
            Assert.Equal(now, w.State.ToArray());
        }

        [Fact]
        public void StepAndWriteFrameAllocateNothing()
        {
            var w = new RuleTableCA(RuleTables.Starter("Evoloop"), 64, 48, new byte[64 * 48], new Topology(Boundary.Torus));
            w.SeedSoup(3, 0.3);
            var frame = new byte[64 * 48];
            w.Step(4);
            w.WriteFrame(frame);
            long before = GC.GetAllocatedBytesForCurrentThread();
            w.Step(10);
            w.WriteFrame(frame);
            Assert.Equal(0, GC.GetAllocatedBytesForCurrentThread() - before);
        }

        [Fact]
        public void DefaultPalettes()
        {
            foreach (string name in RuleTables.StarterNames) // no starter file gives colors
            {
                RuleTable rule = RuleTables.Starter(name);
                var grid = new RuleTableCA(rule, 8, 8, new byte[64]);
                byte[] expected = StatePalettes.ForMultiState(rule.States);
                Assert.Equal(expected, StatePalettes.Default(grid));
                Assert.Equal(expected, StatePalettes.Default(new MultiStateHashLife(rule)));
                Assert.Equal(Enumerable.Range(0, rule.States).Select(v => (byte)v).ToArray(), StatePalettes.FrameValues(grid));
                Assert.Empty(StatePalettes.DefaultZoomOrder(grid));
            }
            RuleTable colored = RuleTable.Parse(
                "@RULE C\n@TABLE\nn_states:4\nneighborhood:Moore\nsymmetries:none\n@COLORS\n3 1 2 3\n0 0 0 30 60 90\n2 5 5 5\n");
            byte[] palette = StatePalettes.ForRuleTable(colored);
            Assert.Equal(new byte[] { 0, 0, 0, 0, 0, 0, 5, 5, 5, 30, 60, 90 }, palette.Take(12).ToArray());
            Assert.All(palette.Skip(12), v => Assert.Equal(0, v));
            Assert.Throws<ArgumentNullException>(() => StatePalettes.ForRuleTable(null!));
        }

        [Fact]
        public void StampsCheckTheStates()
        {
            var pattern = new byte[] { 5, 7 };
            Assert.Null(Patterns.Compatible("ruletable", "ruletable", pattern, 8));
            Assert.Equal("pattern uses state 7, target has only 6 states", Patterns.Compatible("ruletable", "ruletable", pattern, 6));
            Assert.NotNull(Patterns.Compatible("ruletable", "wireworld", pattern));
        }

        // -- the plane and files -------------------------------------------------------------

        [Fact]
        public void ThePlaneRunsALoopAsTheGridDoes()
        {
            (int lw, int lh, byte[] loop) = Grid(LangtonFig6);
            var u = new MultiStateHashLife("Langtons-Loops");
            u.SetRect(-999_999_007, 99, loop, lw, lh);
            var w = new RuleTableCA(RuleTables.Starter("Langtons-Loops"), 48, 40, Placed((lw, lh, loop), 48, 40, 8, 14));
            foreach (int generation in new[] { 1, 40, 151, 200 })
            {
                u.Step(generation - (int)u.Generation);
                w.Step(generation - w.Generation);
                long x0 = -999_999_007 - 8, y0 = 99 - 14;
                Assert.Equal(w.State.ToArray(), u.GetRect(x0, y0, x0 + 47, y0 + 39));
                Assert.Equal(w.State.ToArray().Count(v => v != 0), (int)u.Population);
            }
        }

        [Fact]
        public void ThePlaneRefusesABackgroundThatChanges()
        {
            RuleTable flash = RuleTable.Parse(
                "@RULE Flash\n@TABLE\nn_states:2\nneighborhood:vonNeumann\nsymmetries:none\n0,0,0,0,0,1\n");
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife(flash));
            var w = new RuleTableCA(flash, 5, 4, new byte[20]);
            w.Step();
            Assert.All(w.State.ToArray(), v => Assert.Equal(1, v)); // a grid runs it as written
        }

        [Fact]
        public void ARuleAppendedToAnRleFile()
        {
            RuleTable mine = RuleTable.Parse(RuleTables.Starter("Byl-Loop").Text.Replace("@RULE Byl-Loop", "@RULE My-Byl"));
            (int w, int h, byte[] cells) = RuleTables.StarterPattern("Byl-Loop");
            string rle = Patterns.RleEncode(cells, w, h, "My-Byl");
            string text = RuleTables.Append(rle, mine);
            Assert.Equal(rle + mine.Text, text);
            RuleTable? found = RuleTables.Embedded(text);
            Assert.NotNull(found);
            Assert.Equal(mine.TreeText(), found!.TreeText());
            Assert.Null(RuleTables.Embedded(rle));
            Assert.Null(RuleTables.Embedded("x = 1, y = 1, rule = A!B\nA!\n"));
            var u = MultiStateHashLife.FromRle(text, null);
            Assert.Equal("My-Byl", u.Rule);
            Assert.Equal(12, (int)u.Population);
            Assert.Equal("My-Byl", MultiStateHashLife.FromRle(text, RuleTables.Starter("Byl-Loop")).Rule);
            string broken = rle + "@RULE Broken\n@TABLE\nn_states:1\n";
            Assert.Throws<RuleFileException>(() => RuleTables.Embedded(broken));
            Assert.ThrowsAny<FormatException>(() => MultiStateHashLife.FromRle(rle, null));
        }
    }
}
