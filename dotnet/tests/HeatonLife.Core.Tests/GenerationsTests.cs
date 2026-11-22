using System;
using System.Linq;
using System.Numerics;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Generations (spec/generations.md): the rule's two spellings, canonical form and reasons;
    /// the grid family against a cell-by-cell oracle on every topology and against Life at C = 2;
    /// editing; RLE's two-letter tags; the unbounded plane (multi-state HashLife), with the
    /// two-state HashLife refusing Generations rules; and steps and frames that allocate nothing.
    /// The C# counterpart of python/tests/test_generations.py.
    /// </summary>
    public class GenerationsTests
    {
        /// <summary>Incompressible test input of states below <paramref name="states"/> from an
        /// integer hash (simulation randomness stays PCG32).</summary>
        private static byte[] States(int height, int width, int states, uint seed)
        {
            var cells = new byte[height * width];
            for (int i = 0; i < cells.Length; i++)
            {
                uint v = unchecked((uint)i * 0x9E3779B1u + seed);
                v ^= v >> 15;
                v = unchecked(v * 0x85EBCA6Bu);
                v ^= v >> 13;
                cells[i] = (byte)((v >> 5) % (uint)states);
            }
            return cells;
        }

        /// <summary>One generation cell by cell through the rule's cell function, the halo giving
        /// the block past the edges: independent of the family's step.</summary>
        private static byte[] OracleStep(byte[] state, int width, int height, GenerationsRule rule, Topology topology)
        {
            var halo = new Halo(topology, width, height);
            var padded = new byte[halo.Length];
            halo.Fill(state, padded);
            int stride = halo.Columns;
            var next = new byte[state.Length];
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    int up = y * stride + x, mid = up + stride, down = mid + stride;
                    next[y * width + x] = rule.NextState(
                        padded[up], padded[up + 1], padded[up + 2],
                        padded[mid], padded[mid + 1], padded[mid + 2],
                        padded[down], padded[down + 1], padded[down + 2]);
                }
            }
            return next;
        }

        // -- rules ------------------------------------------------------------------------------

        [Theory]
        [InlineData("345/2/4", "B2/S345/C4", 4)]
        [InlineData("B2/S345/C4", "B2/S345/C4", 4)]
        [InlineData("/2/3", "B2/S/C3", 3)]
        [InlineData(" b2/s/c3\t", "B2/S/C3", 3)]
        [InlineData("B2/S/C003", "B2/S/C3", 3)]
        [InlineData("23/3/2", "B3/S23/C2", 2)]
        [InlineData("332/33/5", "B3/S23/C5", 5)]
        [InlineData("B2a/S23/C5", "B2a/S23/C5", 5)]
        [InlineData("B2/S34H/C5", "B2/S34H/C5", 5)]
        [InlineData("B1/S1V/C256", "B1/S1V/C256", 256)]
        [InlineData("B2/S345 / c4", "B2/S345/C4", 4)]
        public void BothSpellingsCompileToOneCanonicalForm(string text, string canonical, int states)
        {
            GenerationsRule rule = GenerationsRule.Compile(text);
            Assert.Equal(canonical, rule.Canonical);
            Assert.Equal(states, rule.States);
            Assert.Equal(rule, GenerationsRule.Compile(rule.Canonical));
            Assert.Equal<StateRule>(rule, StateRules.Compile(text));
        }

        [Theory]
        [InlineData("B3/S23", "expected '/C' and the number of states at the end")]
        [InlineData("B3/S23/C1", "a Generations rule has 2 to 256 states")]
        [InlineData("B3/S23/C257", "a Generations rule has 2 to 256 states")]
        [InlineData("B3/S23/C0000000000000000000003000", "a Generations rule has 2 to 256 states")]
        [InlineData("B9/S/C3", "expected '/' after the birth counts")]
        [InlineData("life/C3", "expected B…/S… or MAP…")]
        public void RefusalsCarryTheirReason(string text, string reason)
        {
            Assert.False(GenerationsRule.TryCompile(text, out GenerationsRule? rule, out string? why));
            Assert.Null(rule);
            Assert.Equal(reason, why);
            ArgumentException thrown = Assert.Throws<ArgumentException>(() => GenerationsRule.Compile(text));
            Assert.Contains("invalid Generations rule", thrown.Message);
            Assert.Contains(reason, thrown.Message);
            Assert.Throws<ArgumentNullException>(() => GenerationsRule.Compile(null!));
        }

        [Fact]
        public void TheCellFunctionFollowsTheSpecTable()
        {
            GenerationsRule rule = GenerationsRule.Compile("B2/S23/C5");
            Assert.Equal(1, rule.NextState(1, 1, 0, 0, 0, 0, 0, 0, 0)); // born of two live neighbors
            Assert.Equal(0, rule.NextState(2, 2, 0, 0, 0, 0, 0, 0, 0)); // dying neighbors are dead ones
            Assert.Equal(1, rule.NextState(1, 1, 0, 0, 1, 0, 0, 0, 0)); // survives with two
            Assert.Equal(2, rule.NextState(0, 0, 0, 0, 1, 0, 0, 0, 0)); // starts dying
            Assert.Equal(new byte[] { 3, 4, 0 }, new byte[] { 2, 3, 4 }.Select(s => rule.NextState(1, 1, 1, 1, s, 1, 1, 1, 1)).ToArray());
            Assert.Equal(0, GenerationsRule.Compile("B3/S23/C2").NextState(0, 0, 0, 0, 1, 0, 0, 0, 0));
        }

        // -- the grid ---------------------------------------------------------------------------

        [Theory]
        [InlineData("B2/S/C3", "torus", 0, "x")]
        [InlineData("B2/S345/C4", "dead", 0, "x")]
        [InlineData("B2/S34H/C5", "klein", 0, "y")]
        [InlineData("B1/S1V/C4", "cross", 0, "x")]
        [InlineData("B2-a/S12/C7", "sphere", 0, "x")]
        [InlineData("B01/S1/C4", "torus", 3, "x")]
        public void AStepIsTheCellFunctionEverywhere(string text, string boundary, int shift, string axis)
        {
            GenerationsRule rule = GenerationsRule.Compile(text);
            Topology topology = Topology.Parse(boundary, shift, axis);
            byte[] expect = States(14, 14, rule.States, 7);
            var world = new Generations(text, 14, 14, topology);
            world.SetState(expect);
            for (int g = 1; g <= 6; g++)
            {
                expect = OracleStep(expect, 14, 14, rule, topology);
                world.Step();
                Assert.True(expect.AsSpan().SequenceEqual(world.State), $"{text} at {g}");
            }
        }

        [Fact]
        public void TwoStatesIsLife()
        {
            var world = new Generations("B36/S23/C2", 40, 30);
            var life = new LifeLike("B36/S23", 40, 30);
            world.SeedSoup(0.4, 3);
            life.SeedSoup(0.4, 3);
            foreach (int n in new[] { 1, 5, 30 })
            {
                world.Step(n);
                life.Step(n);
                Assert.True(life.State.SequenceEqual(world.State));
            }
        }

        [Fact]
        public void ADyingCellTakesItsCountToDie()
        {
            var world = new Generations("B2/S/C6", 8, 8, Boundary.Dead);
            var cells = new byte[64];
            cells[4 * 8 + 4] = 3;
            world.SetState(cells);
            foreach (int state in new[] { 4, 5 })
            {
                world.Step();
                Assert.Equal(state, world.State[4 * 8 + 4]);
                Assert.Equal(state, world.State.ToArray().Sum(c => c));
            }
            world.Step();
            Assert.True(world.State.ToArray().All(c => c == 0));
        }

        [Fact]
        public void FramesAndStateChecks()
        {
            var world = new Generations("345/2/4", 16, 12, new Topology(Boundary.Klein, 0, TopologyAxis.Y));
            Assert.Equal("B2/S345/C4", world.Rule);
            Assert.Equal(4, world.States);
            Assert.Equal(new Topology(Boundary.Klein, 0, TopologyAxis.Y), world.Topology);
            var small = new Generations("B2/S345/C4", 4, 1, Boundary.Dead);
            small.SetState(new byte[] { 0, 1, 2, 3 });
            Assert.Equal(new byte[] { 0, 255, 170, 85 }, small.Frame());
            Assert.Contains("0 to 3", Assert.Throws<ArgumentException>(() => small.SetState(new byte[] { 0, 4, 0, 0 })).Message);
            Assert.Equal(new byte[] { 0, 1, 2, 3 }, small.State.ToArray()); // a refused state changes nothing
            small.Step(2);
            small.SetState(new byte[] { 1, 0, 0, 0 }, 9, keepStart: true);
            Assert.Equal(9, small.Generation);
            small.Reset();
            Assert.Equal(new byte[] { 0, 1, 2, 3 }, small.State.ToArray());
            Assert.Equal(0, small.Generation);
            Assert.Throws<ArgumentOutOfRangeException>(() => small.SetCell(0, 0, 4));
            var many = new Generations("B3/S23/C256", 3, 1);
            many.SetState(new byte[] { 1, 128, 255 });
            Assert.Equal(new byte[] { 255, 128, 1 }, many.Frame());
            Assert.Throws<ArgumentException>(() => new Generations("B3/S23", 4, 4));
        }

        [Fact]
        public void EditingTools()
        {
            var world = new Generations("B2/S/C3", 20, 16, Boundary.Dead);
            world.SetState(new byte[20 * 16]);
            world.FillRandom(2, 3, 13, 10, 0.4, 11);
            var life = new LifeLike("B3/S23", 20, 16);
            life.SetState(new byte[20 * 16]);
            life.FillRandom(2, 3, 13, 10, 0.4, 11);
            Assert.True(life.State.SequenceEqual(world.State)); // the life-like soup, each live cell 1
            Assert.Contains(world.State.ToArray(), c => c == 1);
            byte[] start = States(16, 20, 3, 5);
            world.SetState(start);
            var whole = new Generations("B2/S/C3", 20, 16, Boundary.Dead);
            whole.SetState(start);
            world.AdvanceSelection(0, 0, 19, 15, 4);
            whole.Step(4);
            Assert.True(whole.State.SequenceEqual(world.State));
            Assert.Equal(0, world.Generation);
            world.ClearRect(0, 0, 4, 4);
            for (int y = 0; y < 5; y++)
                for (int x = 0; x < 5; x++)
                    Assert.Equal(0, world.State[y * 20 + x]);
            Assert.NotNull(Patterns.Compatible("generations", "generations", new byte[] { 3 }, 3));
            Assert.Null(Patterns.Compatible("generations", "generations", new byte[] { 2 }, 3));
        }

        [Fact]
        public void StepsAndFramesAllocateNothing()
        {
            var world = new Generations("B2/S345/C4", 64, 48, new Topology(Boundary.Klein, 1));
            var frame = new byte[64 * 48];
            world.Step(2); // warm up
            world.WriteFrame(frame);
            Assert.Equal(0, Allocations.Least(() =>
            {
                world.Step(20);
                world.WriteFrame(frame);
            }));
        }

        // -- RLE ----------------------------------------------------------------------------------

        [Fact]
        public void EveryStateRoundTripsThroughRle()
        {
            byte[] grid = Enumerable.Range(0, 256).Select(v => (byte)v).ToArray();
            string text = Patterns.RleEncode(grid, 16, 16, "/2/256");
            Assert.Contains("rule = B2/S/C256", text);
            Assert.Contains("yO", text);
            Assert.Contains("pA", text);
            RlePattern decoded = Patterns.RleDecode(text);
            Assert.Equal("B2/S/C256", decoded.Rule);
            Assert.Equal(grid, decoded.Cells);
            var world = new Generations(decoded.Rule!, 16, 16, Boundary.Dead);
            world.SetState(decoded.Cells);
            Assert.Equal(256, world.States);
        }

        [Theory]
        [InlineData("pZ!")]
        [InlineData("yP!")]
        [InlineData("p!")]
        [InlineData("p3A!")]
        [InlineData("zA!")]
        public void ABrokenTwoLetterTagIsRefused(string body)
        {
            ArgumentException thrown = Assert.Throws<ArgumentException>(
                () => Patterns.RleDecode($"x = 1, y = 1, rule = B2/S/C256\n{body}"));
            Assert.Contains("unsupported RLE tag", thrown.Message);
        }

        [Theory]
        [InlineData("2p A!")]
        [InlineData("2p\nA!")]
        public void WhitespaceInsideATwoLetterTagIsIgnored(string body)
        {
            string text = $"x = 2, y = 1, rule = B2/S/C256\n{body}";
            Assert.Equal(new byte[] { 25, 25 }, Patterns.RleDecode(text).Cells);
            Assert.Equal(new byte[] { 25, 25 }, MultiStateHashLife.FromRle(text).GetRect(0, 0, 1, 0));
        }

        // -- the unbounded plane -----------------------------------------------------------------

        [Theory]
        [InlineData("B2/S345/C4")]
        [InlineData("/2/3")]
        [InlineData("B3/S23/C9")]
        [InlineData("B2/S34H/C5")]
        public void ThePlaneAgreesWithTheGridWhileThePatternStaysInside(string text)
        {
            GenerationsRule rule = GenerationsRule.Compile(text);
            var grid = new byte[60 * 60];
            byte[] patch = States(16, 16, rule.States, 9);
            for (int y = 0; y < 16; y++)
                Array.Copy(patch, y * 16, grid, (22 + y) * 60 + 22, 16);
            var world = new Generations(text, 60, 60, Boundary.Dead);
            world.SetState(grid);
            var u = new MultiStateHashLife(text);
            u.SetRect(-17, 40, grid, 60, 60);
            foreach (int n in new[] { 1, 2, 4, 8, 6 }) // to generation 21: the pattern can't reach the edge
            {
                world.Step(n);
                u.Step(n);
                Assert.True(u.GetRect(-17, 40, 42, 99).AsSpan().SequenceEqual(world.State), $"{text} at {u.Generation}");
                Assert.Equal(world.State.ToArray().Count(c => c != 0), (int)u.Population);
            }
        }

        [Fact]
        public void TheTwoStateUniverseRefusesGenerationsRules()
        {
            foreach (string text in new[] { "B2/S345/C4", "345/2/4", "B3/S23/C2" })
                Assert.Contains("Generations rule", Assert.Throws<ArgumentException>(() => new HashLife(text)).Message);
            var u = new HashLife();
            Assert.Contains("MultiStateHashLife", Assert.Throws<ArgumentException>(() => u.Rule = "/2/3").Message);
            Assert.Contains("has B0: its first generation", Assert.Throws<ArgumentException>(() => new MultiStateHashLife("B0/S/C3")).Message);
            Assert.Equal("B2/S345/C4", new MultiStateHashLife("345/2/4").Rule);
            Assert.Equal(BigInteger.Zero, u.Population);
        }
    }
}
