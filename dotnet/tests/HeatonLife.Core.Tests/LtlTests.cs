using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Larger than Life (spec/ltl.md): the rule text and its reasons, the neighborhoods, every
    /// generation against a direct sum over the neighborhood on every topology, range 1 as Life,
    /// the world's least size, editing and frames, zero allocation, files, and the universes'
    /// refusals. The Python suite checks the same (python/tests/test_ltl.py).
    /// </summary>
    public class LtlTests
    {
        private static readonly Topology[] Topologies =
        {
            new Topology(Boundary.Dead),
            new Topology(Boundary.Torus),
            Topology.Parse("torus", 3, "x"),
            Topology.Parse("klein", 0, "y"),
            Topology.Parse("klein", 1, "x"),
            new Topology(Boundary.Cross),
            new Topology(Boundary.Sphere),
        };

        /// <summary>A grid of every state (alive, state 1, the most common), from PCG32 draws.</summary>
        private static byte[] Mixed(int width, int height, int states, uint seed)
        {
            var rng = new Pcg32(seed);
            var cells = new byte[width * height];
            for (int i = 0; i < cells.Length; i++)
            {
                uint draw = rng.NextU32();
                cells[i] = (byte)(states > 2 && draw % 3 == 0 ? 2 + (draw >> 8) % (uint)(states - 2) : (draw >> 4) & 1);
            }
            return cells;
        }

        /// <summary>One generation by spec/ltl.md's table, each count summed cell by cell over the
        /// neighborhood and every point past an edge located through the topology.</summary>
        private static byte[] DirectStep(byte[] cells, int width, int height, LtlRule rule, Topology topology)
        {
            int r = rule.Range;
            int[] widths = rule.HalfWidthSpan.ToArray();
            var next = new byte[cells.Length];
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    int count = 0;
                    for (int dy = -r; dy <= r; dy++)
                    {
                        for (int dx = -widths[dy + r]; dx <= widths[dy + r]; dx++)
                        {
                            if (!rule.Middle && dx == 0 && dy == 0)
                                continue;
                            if (topology.Locate(x + dx, y + dy, width, height, out int cx, out int cy)
                                && cells[cy * width + cx] == 1)
                                count++;
                        }
                    }
                    int state = cells[y * width + x];
                    int after = state == 0
                        ? (count >= rule.BirthMin && count <= rule.BirthMax ? 1 : 0)
                        : state == 1
                            ? (count >= rule.SurvivalMin && count <= rule.SurvivalMax ? 1 : rule.States > 2 ? 2 : 0)
                            : (state + 1 < rule.States ? state + 1 : 0);
                    next[y * width + x] = (byte)after;
                }
            }
            return next;
        }

        // -- the rule text ------------------------------------------------------------------------

        [Theory]
        [InlineData(LtlRule.Bosco, LtlRule.Bosco)]
        [InlineData("5,34,45,34,58", LtlRule.Bosco)]
        [InlineData("r5,c2,m1,s34..58,b34..45", LtlRule.Bosco)]
        [InlineData("  R005,C00,M1,S034..58,B34..045,nm\t", LtlRule.Bosco)]
        [InlineData("R1,C3,M0,S2..3,B3..3,NC", "R1,C3,M0,S2..3,B3..3,NC")]
        [InlineData("R500,C256,M0,S0..1002001,B0..0,NN", "R500,C256,M0,S0..1002001,B0..0,NN")]
        public void ARuleReadsAndWritesCanonically(string text, string canonical)
        {
            LtlRule rule = LtlRule.Parse(text);
            Assert.Equal(canonical, rule.Canonical);
            Assert.Equal(canonical, rule.ToString());
            Assert.Equal(rule, LtlRule.Parse(canonical));
            Assert.Equal(rule.GetHashCode(), LtlRule.Parse(canonical).GetHashCode());
        }

        [Theory]
        [InlineData("", "expected R…,C…,M…,S…,B…,N… or five numbers r,bmin,bmax,smin,smax")]
        [InlineData("B3/S23", "expected R…,C…,M…,S…,B…,N… or five numbers r,bmin,bmax,smin,smax")]
        [InlineData("R5,C0,M1,S34..58", "expected the fields R, C, M, S, B and N, in that order")]
        [InlineData("R5,C0,M1,S1..2,B1..2,NM,X", "expected the fields R, C, M, S, B and N, in that order")]
        [InlineData("Rx,C0,M1,S1..2,B1..2", "expected R and the range, not 'Rx'")]
        [InlineData("R5,K0,M1,S1..2,B1..2", "expected C and the number of states, not 'K0'")]
        [InlineData("R5,C0,M2,S1..2,B1..2", "expected M0 or M1, not 'M2'")]
        [InlineData("R5,C0,M1,S1-2,B1..2", "expected S and a range of counts S<min>..<max>, not 'S1-2'")]
        [InlineData("R5,C0,M1,S1..2,B1", "expected B and a range of counts B<min>..<max>, not 'B1'")]
        [InlineData("R5,C0,M1,S1..2,B1..2,NX", "expected NM, NN or NC, not 'NX'")]
        [InlineData("R5, C0,M1,S1..2,B1..2", "expected C and the number of states, not ' C0'")]
        [InlineData("5,34,45,34", "expected five numbers r,bmin,bmax,smin,smax")]
        [InlineData("5,34,45,34,5x", "expected five numbers r,bmin,bmax,smin,smax")]
        [InlineData("R0,C0,M1,S1..2,B1..2", "the range is 1 to 500, not 0")]
        [InlineData("R501,C0,M1,S1..2,B1..2", "the range is 1 to 500, not 501")]
        [InlineData("R5,C1,M1,S1..2,B1..2", "C is 0 or 2 (two states) or 3 to 256, not 1")]
        [InlineData("R5,C257,M1,S1..2,B1..2", "C is 0 or 2 (two states) or 3 to 256, not 257")]
        [InlineData("R5,C0,M1,S1..1002002,B1..2", "a count is at most 1002001")]
        [InlineData("R5,C0,M1,S9..2,B1..2", "S9..2 is empty")]
        [InlineData("R5,C0,M1,S1..2,B09..2", "B9..2 is empty")]
        [InlineData("R٥,C0,M1,S1..2,B1..2", "expected R and the range, not 'R٥'")] // Arabic-Indic 5
        public void ATextThatIsNoRuleSaysWhy(string text, string reason)
        {
            Assert.False(LtlRule.TryParse(text, out LtlRule? rule, out string? found));
            Assert.Null(rule);
            Assert.Equal(reason, found);
            ArgumentException e = Assert.Throws<ArgumentException>(() => LtlRule.Parse(text));
            Assert.Equal($"invalid Larger than Life rule '{text}': {reason} (spec/ltl.md)", e.Message);
        }

        // -- the neighborhoods --------------------------------------------------------------------

        [Theory]
        [InlineData(1)]
        [InlineData(2)]
        [InlineData(3)]
        [InlineData(4)]
        [InlineData(5)]
        [InlineData(7)]
        [InlineData(12)]
        [InlineData(20)]
        [InlineData(50)]
        [InlineData(137)]
        [InlineData(500)]
        public void EachNeighborhoodHoldsTheCellsTheSpecNames(int r)
        {
            var inside = new Dictionary<LtlNeighborhood, Func<long, long, bool>>
            {
                [LtlNeighborhood.Moore] = (dx, dy) => Math.Abs(dx) <= r && Math.Abs(dy) <= r,
                [LtlNeighborhood.VonNeumann] = (dx, dy) => Math.Abs(dx) + Math.Abs(dy) <= r,
                [LtlNeighborhood.Circular] = (dx, dy) => dx * dx + dy * dy <= (long)r * r + r,
            };
            foreach (var hood in inside)
            {
                int[] widths = LtlRule.HalfWidths(r, hood.Key);
                Assert.Equal(2 * r + 1, widths.Length);
                for (int dy = -r; dy <= r; dy++)
                {
                    int w = widths[dy + r];
                    Assert.True(hood.Value(w, dy) && !hood.Value(w + 1, dy), $"{hood.Key} r {r} dy {dy}");
                }
            }
            Assert.Equal((2 * r + 1) * (2 * r + 1), LtlRule.HalfWidths(r, LtlNeighborhood.Moore).Sum(w => 2 * w + 1));
            Assert.Equal(2 * r * (r + 1) + 1, LtlRule.HalfWidths(r, LtlNeighborhood.VonNeumann).Sum(w => 2 * w + 1));
            if (r == 1)
                Assert.Equal(new[] { 1, 1, 1 }, LtlRule.HalfWidths(1, LtlNeighborhood.Circular)); // the 3 × 3 box
        }

        // -- evolution ----------------------------------------------------------------------------

        public static IEnumerable<object[]> TopologyHoods()
        {
            for (int t = 0; t < Topologies.Length; t++)
                foreach (char hood in "MNC")
                    yield return new object[] { t, hood };
        }

        /// <summary>
        /// The prefix sums count what a direct sum counts, on every topology and neighborhood: a
        /// few generations of mixed grids, under rules whose ranges sit about the middle of each
        /// neighborhood's counts so that births, survivals and deaths all happen.
        /// </summary>
        [Theory]
        [MemberData(nameof(TopologyHoods))]
        public void EveryGenerationIsADirectSumOnEveryTopology(int which, char hood)
        {
            Topology topology = Topologies[which];
            foreach ((int r, int middle, int states) in new[] { (1, 0, 2), (2, 1, 4), (3, 0, 3), (4, 1, 2) })
            {
                int n = LtlRule.Parse($"R{r},C0,M1,S0..0,B0..0,N{hood}").Size;
                var rule = LtlRule.Parse(
                    $"R{r},C{(states == 2 ? 0 : states)},M{middle},S{n / 5}..{3 * n / 5},B{n / 4}..{n / 2},N{hood}");
                int size = 2 * r + 3;
                // Even across: a shifted Klein bottle's twisted side.
                int width = topology.Boundary == Boundary.Sphere ? size : size + 3, height = size;
                var world = new LargerThanLife(rule, width, height, topology);
                world.SetState(Mixed(width, height, rule.States, (uint)(r * 10 + middle)));
                for (int s = 0; s < 4; s++)
                {
                    byte[] expected = DirectStep(world.State.ToArray(), width, height, rule, topology);
                    world.Step();
                    Assert.Equal(expected, world.State.ToArray());
                }
                Assert.Equal(4, world.Generation);
            }
        }

        public static IEnumerable<object[]> LifeTopologies()
        {
            yield return new object[] { "torus", 0, "x" };
            yield return new object[] { "dead", 0, "x" };
            yield return new object[] { "klein", 1, "x" };
            yield return new object[] { "sphere", 0, "x" };
        }

        [Theory]
        [MemberData(nameof(LifeTopologies))]
        public void Range1WithTheMiddleOutIsLife(string boundary, int shift, string axis)
        {
            Topology topology = Topology.Parse(boundary, shift, axis);
            var ltl = new LargerThanLife("R1,C0,M0,S2..3,B3..3,NM", 40, 40, topology);
            var life = new LifeLike("B3/S23", 40, 40, topology);
            ltl.SeedSoup(0.4, 9);
            life.SeedSoup(0.4, 9);
            for (int s = 0; s < 25; s++)
            {
                ltl.Step();
                life.Step();
                Assert.Equal(life.State.ToArray(), ltl.State.ToArray());
            }
        }

        [Fact]
        public void AWorldIsAtLeast2rPlus1CellsOnASide()
        {
            ArgumentException e = Assert.Throws<ArgumentException>(() => new LargerThanLife(LtlRule.Bosco, 10, 40));
            Assert.Equal("a Larger than Life world of range 5 is at least 11 cells wide and high (spec/ltl.md)", e.Message);
            Assert.Throws<ArgumentException>(() => new LargerThanLife(LtlRule.Bosco, 40, 10, new Topology(Boundary.Dead)));
            var sphere = new LargerThanLife(LtlRule.Bosco, 11, 11, new Topology(Boundary.Sphere)); // its halo reaches
            sphere.Step(3);
            Assert.Throws<TopologyException>(() => new LargerThanLife(LtlRule.Bosco, 12, 11, new Topology(Boundary.Sphere)));
        }

        // -- editing, frames, allocation ----------------------------------------------------------

        [Fact]
        public void EditingToolsAndFrames()
        {
            var world = new LargerThanLife("R2,C4,M1,S3..9,B4..6,NM", 30, 20);
            Assert.Equal(new Topology(Boundary.Torus), world.Topology);
            Assert.Equal(Boundary.Torus, world.Boundary);
            world.SeedSoup(0.4, 2);
            byte[] start = world.State.ToArray();
            world.Step(3);
            byte[] frame = world.Frame();
            Assert.True(frame.Max() <= 3); // the states themselves
            Assert.Equal(world.State.ToArray(), frame);
            ArgumentException past = Assert.Throws<ArgumentException>(
                () => world.SetState(Enumerable.Repeat((byte)4, 600).ToArray()));
            Assert.Contains("past this rule's 4 states", past.Message);
            Assert.Throws<ArgumentException>(() => world.SetCell(1, 1, 4));
            byte[] shown = world.State.ToArray();
            world.SetState(start, 5, keepStart: true);
            Assert.Equal(5, world.Generation);
            world.Reset();
            Assert.Equal(start, world.State.ToArray()); // the start stayed the soup
            Assert.Equal(0, world.Generation);
            world.SetState(shown, 3);
            world.ClearRect(0, 0, 9, 9);
            for (int y = 0; y < 10; y++)
                for (int x = 0; x < 10; x++)
                    Assert.Equal(0, world.State[y * 30 + x]);
            world.FillRandom(0, 0, 9, 9, 0.5, 4);
            var soup = new byte[100];
            Seeding.Soup(soup, 0.5, 4);
            for (int y = 0; y < 10; y++)
                Assert.Equal(soup.Skip(y * 10).Take(10), world.State.Slice(y * 30, 10).ToArray());
            byte[] before = world.State.ToArray();
            world.AdvanceSelection(2, 2, 25, 15, 4);
            Assert.Equal(3, world.Generation);
            Assert.NotEqual(before, world.State.ToArray());
            world.Reset();
            Assert.Equal(shown, world.State.ToArray()); // SetState without keepStart moved the start
            var two = new LargerThanLife(LtlRule.Bosco, 32, 32);
            two.SeedSoup(0.5, 1);
            Assert.All(two.Frame(), b => Assert.True(b == 0 || b == 255));
            Assert.Equal(two.State.ToArray().Select(c => (byte)(c * 255)), two.Frame());
        }

        [Fact]
        public void APatternStampsOnlyWithinTheTargetsStates()
        {
            byte[] cells = { 0, 1, 4 };
            Assert.Null(Patterns.Compatible("ltl", "ltl", cells, targetStates: 5));
            Assert.NotNull(Patterns.Compatible("ltl", "ltl", cells, targetStates: 4));
            Assert.NotNull(Patterns.Compatible("lifelike", "ltl", new byte[] { 0, 1 }));
        }

        [Theory]
        [InlineData("R5,C0,M1,S34..58,B34..45,NM")]
        [InlineData("R4,C6,M0,S12..30,B14..20,NN")]
        [InlineData("R7,C3,M1,S60..110,B50..80,NC")]
        public void StepAndWriteFrameAllocateNothing(string text)
        {
            var world = new LargerThanLife(text, 64, 48, Topology.Parse("torus", 5, "y"));
            world.SeedSoup(0.5, 3);
            var frame = new byte[64 * 48];
            world.Step(4);
            world.WriteFrame(frame);
            Assert.Equal(0, Allocations.Least(() =>
            {
                world.Step(10);
                world.WriteFrame(frame);
            }));
        }

        // -- files and the universes --------------------------------------------------------------

        [Theory]
        [InlineData(LtlRule.Bosco)]
        [InlineData("R2,C5,M0,S2..7,B3..5,NN")]
        public void AWorldRoundTripsThroughRleWithItsTopology(string text)
        {
            Topology klein = Topology.Parse("klein", 0, "y");
            var world = new LargerThanLife(text, 40, 30, klein);
            world.SeedSoup(0.45, 6);
            world.Step(5);
            string saved = Patterns.RleEncode(world.State, 40, 30, world.Rule.Canonical, null, world.Topology);
            PatternFile found = PatternFiles.Read(saved);
            Assert.Equal(world.Rule.Canonical, found.Rule);
            Assert.Equal(new BoundedGrid(40, 30, klein), found.BoundedGrid);
            Assert.Equal(world.State.ToArray(), found.Cells);
            var again = new LargerThanLife(found.Rule!, 40, 30, found.BoundedGrid!.Topology);
            again.SetState(found.Cells);
            again.Step(3);
            world.Step(3);
            Assert.Equal(world.State.ToArray(), again.State.ToArray());
        }

        /// <summary>RLE's two-letter tags (spec/patterns.md) carry the dying states past 24, so a
        /// world of up to 256 states saves and reads back as itself; the text is the Python
        /// suite's, byte for byte.</summary>
        [Fact]
        public void AWorldPast24StatesWritesTwoLetterTags()
        {
            var world = new LargerThanLife("R1,C256,M1,S2..3,B3..3,NM", 5, 3);
            var cells = new byte[5 * 3];
            new byte[] { 24, 25, 48, 49, 255 }.CopyTo(cells, 0);
            world.SetState(cells);
            string text = Patterns.RleEncode(world.State, 5, 3, world.Rule.Canonical, null, world.Topology);
            Assert.Equal("x = 5, y = 3, rule = R1,C256,M1,S2..3,B3..3,NM:T5,3\nXpApXqAyO2$!\n", text);
            PatternFile found = PatternFiles.Read(text);
            Assert.Equal(world.Rule.Canonical, found.Rule);
            Assert.Equal(new BoundedGrid(5, 3, world.Topology), found.BoundedGrid);
            Assert.Equal(cells, found.Cells);
            var many = new LargerThanLife("R2,C48,M0,S3..8,B4..6,NM", 30, 24);
            many.SeedSoup(0.5, 8);
            many.Step(60);
            Assert.True(many.State.ToArray().Max() > 24); // dying states past 24, reached by the run itself
            string saved = Patterns.RleEncode(many.State, 30, 24, many.Rule.Canonical, null, many.Topology);
            Assert.Equal(many.State.ToArray(), PatternFiles.Read(saved).Cells);
        }

        [Fact]
        public void NeitherUniverseRunsLargerThanLife()
        {
            string reason = $"{LtlRule.Bosco} is a Larger than Life rule: it runs on a bounded grid, never on the unbounded plane (spec/ltl.md)";
            void Refused(Action run)
            {
                Exception e = Assert.ThrowsAny<Exception>(run);
                Assert.True(e is ArgumentException || e is FormatException, $"refused with {e.GetType().Name}: {e.Message}");
                Assert.Contains(reason, e.Message);
            }
            Refused(() => new HashLife(LtlRule.Bosco));
            var universe = new HashLife();
            Refused(() => universe.Rule = "5,34,45,34,58");
            Assert.Equal("B3/S23", universe.Rule);
            Refused(() => PatternFiles.ReadUniverse($"x = 3, y = 1, rule = {LtlRule.Bosco}\n3o!\n"));
            Refused(() => PatternFiles.ReadUniverse($"[M2]\n#R {LtlRule.Bosco}\n$$$$$$$$.***$\n"));
            Refused(() => Patterns.RleToHashLife($"x = 3, y = 1, rule = r5,c2,m1,s34..58,b34..45\n3o!\n"));
            Refused(() => new MultiStateHashLife(LtlRule.Bosco));
            Refused(() => MultiStateFiles.ReadUniverse($"x = 3, y = 1, rule = {LtlRule.Bosco}\n3A!\n"));
            // A file's bounded grid is refused first, as for any rule (spec/patterns.md).
            Exception bounded = Assert.ThrowsAny<Exception>(
                () => PatternFiles.ReadUniverse($"x = 3, y = 1, rule = {LtlRule.Bosco}:T40,30\n3o!\n"));
            Assert.Contains("the unbounded universe has no bounded grid", bounded.Message);
            Exception multi = Assert.ThrowsAny<Exception>(
                () => MultiStateFiles.ReadUniverse($"x = 3, y = 1, rule = {LtlRule.Bosco}:T40,30\n3A!\n"));
            Assert.Contains("the unbounded universe has no bounded grid", multi.Message);
        }
    }
}
