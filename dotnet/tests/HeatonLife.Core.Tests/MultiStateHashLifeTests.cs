using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Multi-state HashLife (spec/hashlife-multistate.md): state rules, the grid Wireworld and the
    /// two-state HashLife as oracles, editing with states, snapshots, budgets, cancellation, frames
    /// under a zoom order, zero allocation once warm, and the multi-state Macrocell and RLE files.
    /// The Python reference's tests/test_hashlife_multistate.py.
    /// </summary>
    public class MultiStateHashLifeTests
    {
        /// <summary>A two-state Life-like rule as a state rule: the multi-state engine must run it
        /// exactly as the two-state engine does.</summary>
        private sealed class LifeStates : StateRule
        {
            private readonly byte[] _table;

            public LifeStates(string rule = "B3/S23")
            {
                LifeRule compiled = RuleString.Compile(rule);
                _table = compiled.Table.ToArray();
                Canonical = "Life-" + compiled.Canonical.Replace('/', '-');
            }

            public override string Canonical { get; }

            public override int States => 2;

            public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
                => _table[nw << 8 | n << 7 | ne << 6 | w << 5 | c << 4 | e << 3 | sw << 2 | s << 1 | se];
        }

        /// <summary>Three states that move: 0 ready, 1 firing, 2 refractory.</summary>
        private sealed class BriansBrain : StateRule
        {
            public override string Canonical => "Test-Brain";

            public override int States => 3;

            public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
            {
                if (c == 1)
                    return 2;
                if (c == 2)
                    return 0;
                int firing = (nw == 1 ? 1 : 0) + (n == 1 ? 1 : 0) + (ne == 1 ? 1 : 0) + (w == 1 ? 1 : 0)
                    + (e == 1 ? 1 : 0) + (sw == 1 ? 1 : 0) + (s == 1 ? 1 : 0) + (se == 1 ? 1 : 0);
                return (byte)(firing == 2 ? 1 : 0);
            }
        }

        /// <summary>S states that count up wherever any neighbor is non-zero.</summary>
        private sealed class Cycle : StateRule
        {
            private readonly int _states;

            public Cycle(int states, string? name = null)
            {
                _states = states;
                Canonical = name ?? $"Test-Cycle-{states}";
            }

            public override string Canonical { get; }

            public override int States => _states;

            public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
            {
                if (c == 0)
                    return (byte)((nw | n | ne | w | e | sw | s | se) != 0 ? 1 : 0);
                return (byte)(c + 1 < _states ? c + 1 : 1);
            }
        }

        private sealed class Lit : StateRule
        {
            public override string Canonical => "Test-Lit";

            public override int States => 3;

            public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se) => 1;
        }

        /// <summary>Incompressible test input from an integer hash (simulation randomness stays PCG32).</summary>
        private static byte[] Noise(int height, int width, uint seed, int states = 2)
        {
            var cells = new byte[height * width];
            for (int i = 0; i < cells.Length; i++)
            {
                uint v = unchecked((uint)i * 0x9E3779B1u + seed);
                v ^= v >> 15;
                v = unchecked(v * 0x85EBCA6Bu);
                v ^= v >> 13;
                v = unchecked(v * 0xC2B2AE35u);
                v ^= v >> 16;
                cells[i] = (byte)((v >> 8) % (uint)states);
            }
            return cells;
        }

        /// <summary>Half conductor, a few heads and tails: chaotic for a while, then periodic.</summary>
        private static byte[] WireSoup(int height, int width, uint seed)
        {
            byte[] roll = Noise(height, width, seed, 20);
            return roll.Select(r => (byte)(r < 9 ? 3 : r == 18 ? 1 : r == 19 ? 2 : 0)).ToArray();
        }

        private static (CellBox? Box, string Cells) State(MultiStateHashLife u)
        {
            CellBox? box = u.BoundingBox;
            if (box == null)
                return (null, "");
            CellBox b = box.Value;
            return (box, Convert.ToBase64String(u.GetRect((long)b.X0, (long)b.Y0, (long)b.X1, (long)b.Y1)));
        }

        private static (CellBox? Box, string Cells) State(HashLife u)
        {
            CellBox? box = u.BoundingBox;
            if (box == null)
                return (null, "");
            CellBox b = box.Value;
            return (box, Convert.ToBase64String(u.GetRect((long)b.X0, (long)b.Y0, (long)b.X1, (long)b.Y1)));
        }

        private static byte[] ClockLoop(int size)
        {
            var w = new Wireworld(size, size);
            w.SeedClock();
            return w.State.ToArray();
        }

        // -- state rules ----------------------------------------------------------------------------

        [Theory]
        [InlineData("WireWorld")]
        [InlineData("wireworld")]
        [InlineData(" WIREWORLD\t")]
        [InlineData("\u3000WireWorld\u2028")]
        public void NamesIgnoreAsciiCaseAndEndWhitespace(string name)
        {
            Assert.Same(WireworldRule.Instance, StateRules.Compile(name));
            Assert.Equal("WireWorld", new MultiStateHashLife(name).Rule);
        }

        [Theory]
        [InlineData("Wire World")]
        [InlineData("WireWorld!")]
        [InlineData("")]
        [InlineData("B3/S23")]
        [InlineData("\u212aireworld")]
        public void OtherTextNamesNoRule(string name)
            => Assert.Throws<ArgumentException>(() => StateRules.Compile(name));

        private const string Known =
            "known: WireWorld, Langtons-Loops, Byl-Loop, Evoloop, Langtons-Ant, Ant-LLRR, Ant-RLR, "
            + "History rules such as B3/S23History, Super rules such as B3/S23Super, and Generations "
            + "rules such as B2/S345/C4";

        private const string B0 =
            " has B0: its first generation would turn the whole plane on, and the unbounded "
            + "universe's background must stay 0; a grid runs it";

        [Theory]
        [InlineData("B03/S23History", "B03/S23History" + B0, "spec/history.md \"On the unbounded plane\"")]
        [InlineData(" b0/s8super ", "B0/S8Super" + B0, "spec/super.md \"On the unbounded plane\"")]
        [InlineData("B03/S23/C3", "B03/S23/C3" + B0, "spec/generations.md \"The unbounded plane\"")]
        [InlineData("23/03/3", "B03/S23/C3" + B0, "spec/generations.md \"The unbounded plane\"")]
        [InlineData(
            "R2,C0,M1,S2..3,B3..3",
            "R2,C0,M1,S2..3,B3..3,NM is a Larger than Life rule: it runs on a bounded grid, never on the unbounded plane",
            "spec/ltl.md")]
        [InlineData("B3/S23", "'B3/S23' is not a state rule (" + Known + ")", "spec/hashlife-multistate.md \"Names\"")]
        [InlineData(" it's\t", "' it's\t' is not a state rule (" + Known + ")", "spec/hashlife-multistate.md \"Names\"")]
        [InlineData("", "'' is not a state rule (" + Known + ")", "spec/hashlife-multistate.md \"Names\"")]
        public void NamesGiveReasons(string name, string reason, string page)
        {
            // spec/hashlife-multistate.md "Names", "Reasons": the reason bare, and the message the
            // reason and the page that says why (and .NET's note of the parameter).
            Assert.False(StateRules.TryCompile(name, out StateRule? rule, out string? why));
            Assert.Null(rule);
            Assert.Equal(reason, why);
            ArgumentException error = Assert.Throws<ArgumentException>(() => StateRules.Compile(name));
            Assert.StartsWith($"{reason} ({page})", error.Message, StringComparison.Ordinal);
            Assert.Equal("name", error.ParamName);
        }

        [Theory]
        [InlineData("WireWorld")]
        [InlineData("evoloop")]
        [InlineData("B3/S23History")]
        [InlineData("LifeSuper")]
        [InlineData("345/2/4")]
        [InlineData("B2/S/C3")]
        public void NamedRulesHaveNoReason(string name)
        {
            Assert.True(StateRules.TryCompile(name, out StateRule? rule, out string? reason));
            Assert.Null(reason);
            Assert.Equal(StateRules.Compile(name), rule); // the same object, or for Generations an equal one
            Assert.Same(rule, StateRules.Check(rule));
        }

        [Fact]
        public void NullReadsAsEmptyText()
        {
            Assert.False(StateRules.TryCompile(null, out _, out string? reason));
            Assert.Equal("'' is not a state rule (" + Known + ")", reason);
            Assert.Throws<ArgumentNullException>(() => StateRules.Compile(null!));
        }

        [Theory]
        [InlineData("B0/S/C3")]
        [InlineData("B03/S23/C3")]
        [InlineData("B0/S8History")]
        [InlineData("B0/S8Super")]
        [InlineData("B0123478/S01234678/C5")]
        public void EveryNamedRuleRuns(string name)
        {
            // A name gives only rules Check passes: a Generations rule with B0 is refused at its
            // name, as History and Super rules are (spec/hashlife-multistate.md "Names").
            Assert.False(StateRules.TryCompile(name, out _, out string? reason));
            Assert.Contains(" has B0: ", reason, StringComparison.Ordinal);
            ArgumentException error = Assert.Throws<ArgumentException>(() => new MultiStateHashLife(name));
            Assert.Contains(" has B0: ", error.Message, StringComparison.Ordinal);
        }

        [Fact]
        public void RulesThatCannotRunAreRefused()
        {
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife(new Lit()));
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife(new Cycle(257)));
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife(new Cycle(1)));
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife(new Cycle(5, "two words")));
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife(new Cycle(5, "a,b")));
            Assert.Equal(256, new MultiStateHashLife(new Cycle(256)).States);
        }

        [Fact]
        public void TheWireworldRuleIsTheSpecTable()
        {
            StateRule f = WireworldRule.Instance;
            Assert.Equal(0, f.NextState(0, 1, 1, 1, 0, 1, 1, 1, 1));
            Assert.Equal(2, f.NextState(0, 0, 0, 0, 1, 0, 0, 0, 0));
            Assert.Equal(3, f.NextState(3, 3, 3, 3, 2, 3, 3, 3, 3));
            for (int heads = 0; heads <= 8; heads++)
            {
                byte[] b = Enumerable.Range(0, 8).Select(i => (byte)(i < heads ? 1 : 3)).ToArray();
                Assert.Equal(heads == 1 || heads == 2 ? 1 : 3, f.NextState(b[0], b[1], b[2], b[3], 3, b[4], b[5], b[6], b[7]));
            }
        }

        // -- oracles --------------------------------------------------------------------------------

        [Theory]
        [InlineData(0L, 0L)]
        [InlineData(-37L, 5L)]
        [InlineData(1_000_000_000L - 63, -1_000_000_000L)]
        public void WireworldAgreesWithTheGrid(long x, long y)
        {
            byte[] grid = WireSoup(64, 64, 11);
            for (int i = 0; i < 64; i++)
                grid[i] = 3; // conductor along the edge: the dead boundary never matters
            var u = new MultiStateHashLife();
            u.SetRect(x, y, grid, 64, 64);
            var w = new Wireworld(64, 64, grid);
            foreach (int n in new[] { 1, 1, 2, 5, 17, 64, 200, 1024 })
            {
                u.Step(n);
                w.Step(n);
                Assert.True(u.GetRect(x, y, x + 63, y + 63).AsSpan().SequenceEqual(w.State), $"generation {u.Generation}");
                Assert.Equal(w.State.ToArray().Count(c => c != 0), (int)u.Population);
            }
        }

        [Fact]
        public void TheClockLandsWhereItsPeriodSays()
        {
            var u = new MultiStateHashLife();
            u.SetRect(10, -4, ClockLoop(16), 16, 16);
            u.Step(1); // the electron settles onto its cycle
            var start = State(u);
            const int period = 40; // a 12 × 12 loop's 44 cells, less the four corners it cuts
            u.Step(period);
            Assert.Equal(start, State(u));
            BigInteger big = BigInteger.Pow(2, 200) + 7;
            u.Step(big);
            var reference = new MultiStateHashLife();
            reference.SetRect(10, -4, ClockLoop(16), 16, 16);
            reference.Step(1 + (int)((period + big) % period));
            Assert.Equal(State(reference), State(u));
            Assert.Equal(1 + period + big, u.Generation);
        }

        [Theory]
        [InlineData("B3/S23", new[] { 1, 3, 60, 500, 4096 })]
        [InlineData("B36/S23", new[] { 1, 3, 60, 500, 4096 })]
        [InlineData("B2/S", new[] { 1, 3, 20 })]
        [InlineData("B3/S12345", new[] { 1, 3, 20 })]
        public void TwoStateRulesRunAsTheTwoStateEngineRunsThem(string rule, int[] steps)
        {
            var u = new MultiStateHashLife(new LifeStates(rule));
            var h = new HashLife(rule);
            byte[] a = Noise(48, 40, 3);
            u.SetRect(-20, 7, a, 40, 48);
            h.SetRect(-20, 7, a, 40, 48);
            foreach (int n in steps)
            {
                u.Step(n);
                h.Step(n);
                Assert.Equal(State(h), State(u));
                Assert.Equal(h.Population, u.Population);
            }
        }

        [Fact]
        public void AGliderCrossesPast64BitCoordinates()
        {
            var u = new MultiStateHashLife(new LifeStates());
            u.SetRect(0, 0, new byte[] { 0, 1, 0, 0, 0, 1, 1, 1, 1 }, 3, 3);
            BigInteger m = BigInteger.Pow(2, 62);
            u.Step(4 * m);
            Assert.Equal(new CellBox(m, m, m + 2, m + 2), u.BoundingBox);
            Assert.Equal(5, (int)u.Population);
        }

        [Fact]
        public void MovingStatesStopAtTheDeepestTree()
        {
            var sb = new StringBuilder("[M2]\n#R Test-Brain\n1 0 0 1 1\n");
            for (int k = 2; k <= MultiStateHashLife.MaxLevel; k++)
                sb.Append(k).Append(" 0 0 0 ").Append(k - 1).Append('\n');
            MultiStateHashLife far = MultiStateHashLife.FromMacrocell(sb.ToString(), new BriansBrain());
            BigInteger corner = BigInteger.Pow(2, MultiStateHashLife.MaxLevel - 1) - 2;
            Assert.Equal(new CellBox(corner, corner + 2, corner + 1, corner + 2), far.BoundingBox);
            string state = far.ToMacrocell();
            Assert.Throws<InvalidOperationException>(() => far.Step(1));
            Assert.Equal(state, far.ToMacrocell());
            Assert.Equal(0, (int)far.Generation);
            var u = new MultiStateHashLife(new BriansBrain());
            Assert.Throws<ArgumentOutOfRangeException>(() => u.Step(BigInteger.Pow(2, MultiStateHashLife.MaxLevel - 2)));
        }

        [Fact]
        public void ResultsDoNotDependOnTheBudget()
        {
            byte[] a = WireSoup(150, 150, 4);
            var roomy = new MultiStateHashLife();
            roomy.SetRect(0, 0, a, 150, 150);
            roomy.Step(300);
            var tight = new MultiStateHashLife(maxMemoryMb: 10);
            tight.SetRect(0, 0, a, 150, 150);
            foreach (int n in new[] { 1, 1, 200, 98 })
                tight.Step(n);
            Assert.Equal(State(roomy), State(tight));
        }

        [Fact]
        public void TheBudgetHoldsUnderChaos()
        {
            byte[] a = Noise(256, 256, 7, 3);
            var roomy = new MultiStateHashLife(new BriansBrain());
            roomy.SetRect(0, 0, a, 256, 256);
            roomy.Step(600);
            var tight = new MultiStateHashLife(new BriansBrain(), maxMemoryMb: 10);
            tight.SetRect(0, 0, a, 256, 256);
            foreach (int n in new[] { 1, 99, 500 })
                tight.Step(n);
            Assert.True(tight.Store.InFlightCollections > 0 || tight.Collections > 0);
            Assert.Equal(roomy.ToMacrocell(), tight.ToMacrocell());
        }

        [Fact]
        public void AUniverseTooBigForItsBudgetRefusesToStepUnchanged()
        {
            var u = new MultiStateHashLife(new Cycle(7), maxMemoryMb: 10);
            u.SetRect(0, 0, Noise(1600, 1600, 9, 7), 1600, 1600); // loading never fails for budget
            string before = u.ToMacrocell();
            Assert.Throws<HashLifeMemoryException>(() => u.Step(1));
            Assert.Equal(before, u.ToMacrocell());
            Assert.Equal(0, (int)u.Generation);
            u.MaxMemoryMb = 4000;
            u.Step(1);
            Assert.Equal(1, (int)u.Generation);
        }

        [Fact]
        public void ACanceledStepStopsAtACompletedSubStep()
        {
            var u = new MultiStateHashLife(new BriansBrain());
            u.SetRect(0, 0, Noise(256, 256, 2, 3), 256, 256);
            using var cts = new CancellationTokenSource();
            long nodes = u.NodeCount;
            var watcher = new Thread(() =>
            {
                while (!cts.IsCancellationRequested)
                {
                    if (u.NodeCount > nodes + 400_000)
                        cts.Cancel();
                    else
                        Thread.Sleep(1);
                }
            });
            watcher.Start();
            try
            {
                var e = Assert.Throws<OperationCanceledException>(() => u.Step((1 << 20) + 1, cts.Token));
                Assert.Equal(cts.Token, e.CancellationToken);
            }
            finally
            {
                cts.Cancel();
                watcher.Join();
            }
            Assert.Equal(1, (int)u.Generation);
            var fresh = new MultiStateHashLife(new BriansBrain());
            fresh.SetRect(0, 0, Noise(256, 256, 2, 3), 256, 256);
            fresh.Step(1);
            Assert.Equal(fresh.ToMacrocell(), u.ToMacrocell());
            u.Step(1);
            Assert.Equal(2, (int)u.Generation);
        }

        [Fact]
        public void ARuleObjectRunsAsItsName()
        {
            byte[] a = WireSoup(40, 40, 8);
            var byName = new MultiStateHashLife("WireWorld");
            var byObject = new MultiStateHashLife(WireworldRule.Instance);
            foreach (MultiStateHashLife u in new[] { byName, byObject })
            {
                u.SetRect(3, 3, a, 40, 40);
                u.Step(77);
            }
            Assert.Equal(byName.ToMacrocell(), byObject.ToMacrocell());
        }

        [Fact]
        public void StepAllocatesNothingOnceWarm()
        {
            var u = new MultiStateHashLife(new BriansBrain(), maxMemoryMb: 10);
            for (int round = 0; round < 3; round++)
            {
                u.Clear();
                u.SetRect(-128, -128, Noise(256, 256, (uint)(21 + round), 3), 256, 256);
                int aborts = u.Store.Aborts;
                long before = GC.GetAllocatedBytesForCurrentThread();
                u.Step(64);
                for (int i = 0; i < 30; i++)
                    u.Step(1);
                long allocated = GC.GetAllocatedBytesForCurrentThread() - before;
                Assert.Equal(aborts, u.Store.Aborts);
                if (round == 2) // rounds 0 and 1 grew the arena and the stacks
                    Assert.Equal(0, allocated);
            }
        }

        [Fact]
        public void WriteFrameAllocatesNothingOnceWarm()
        {
            var u = new MultiStateHashLife();
            u.SetRect(-30, -20, WireSoup(40, 60, 5), 60, 40);
            u.Step(BigInteger.Pow(2, 70));
            u.ZoomOrder = new byte[] { 2 };
            var views = new[]
            {
                new LifeView(-60, -40, 2),
                new LifeView(-30, -20, 0),
                new LifeView(-33, -17, -40),
                new LifeView(-20, -20, -3),
                new LifeView(BigInteger.Pow(2, 66), BigInteger.Pow(2, 66), -1),
                new LifeView(-BigInteger.Pow(3, 60), BigInteger.Pow(3, 60), 5),
            };
            var frame = new byte[128 * 96];
            foreach (LifeView view in views)
            {
                u.WriteFrame(frame, 128, 96, view, MultiStateRenderMode.State);
                u.WriteFrame(frame, 128, 96, view, MultiStateRenderMode.Density);
            }
            // Up to three measured batches, one of which must allocate nothing: a frame that
            // allocates does so in every batch, while the runtime's one-off work under a loaded
            // machine (tiering up the warm methods) does not repeat.
            long allocated = -1;
            for (int attempt = 0; attempt < 3 && allocated != 0; attempt++)
            {
                long before = GC.GetAllocatedBytesForCurrentThread();
                for (int round = 0; round < 5; round++)
                {
                    foreach (LifeView view in views)
                    {
                        u.WriteFrame(frame, 128, 96, view, MultiStateRenderMode.State);
                        u.WriteFrame(frame, 128, 96, view, MultiStateRenderMode.Density);
                    }
                }
                allocated = GC.GetAllocatedBytesForCurrentThread() - before;
            }
            Assert.Equal(0, allocated);
        }

        // -- editing --------------------------------------------------------------------------------

        [Fact]
        public void CellsAndRectanglesHoldStates()
        {
            var u = new MultiStateHashLife(new Cycle(9));
            byte[] a = Noise(29, 31, 1, 9);
            foreach (var (x, y) in new[] { (-13L, 7L), (1_000_000_000L - 30, -1_000_000_000L), (-1_000_000_000L, 1_000_000_000L - 28) })
            {
                u.SetRect(x, y, a, 31, 29);
                Assert.True(u.GetRect(x, y, x + 30, y + 28).AsSpan().SequenceEqual(a));
            }
            Assert.Equal(3 * a.Count(c => c != 0), (int)u.Population);
            u.SetCell(5, -9, 8);
            Assert.Equal(8, u.GetCell(5, -9));
            Assert.Equal(0, u.GetCell(6, -9));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.SetCell(0, 0, 9));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.SetRect(0, 0, new byte[] { 9, 9, 9, 9 }, 2, 2));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.SetCell(1_000_000_001, 0, 1));
            u.Clear();
            Assert.Null(u.BoundingBox);
            Assert.Equal(0, (int)u.Population);
        }

        [Fact]
        public void PasteModesMatchTheGridStamp()
        {
            var u = new MultiStateHashLife(new Cycle(6));
            var mirror = new byte[40 * 50];
            HashLifePasteMode[] modes = { HashLifePasteMode.Copy, HashLifePasteMode.Or, HashLifePasteMode.Copy, HashLifePasteMode.Or };
            for (int i = 0; i < modes.Length; i++)
            {
                int h = 11 + i, w = 17 - i, px = 3 * i + 1, py = 4 * i + 2;
                byte[] piece = Noise(h, w, (uint)(10 + i), 6);
                for (int y = 0; y < h; y++)
                    for (int x = 0; x < w; x++)
                    {
                        byte p = piece[y * w + x];
                        if (modes[i] == HashLifePasteMode.Copy || p != 0)
                            mirror[(py + y) * 50 + px + x] = p;
                    }
                u.SetRect(-20 + px, -9 + py, piece, w, h, modes[i]);
                Assert.True(u.GetRect(-20, -9, 29, 30).AsSpan().SequenceEqual(mirror), modes[i].ToString());
            }
            var two = new MultiStateHashLife(new Cycle(6));
            byte[] grid = Noise(20, 20, 3);
            two.SetRect(0, 0, grid, 20, 20);
            foreach (HashLifePasteMode mode in new[] { HashLifePasteMode.Xor, HashLifePasteMode.And })
            {
                byte[] piece = Noise(7, 9, 4);
                for (int y = 0; y < 7; y++)
                    for (int x = 0; x < 9; x++)
                    {
                        int at = (3 + y) * 20 + 2 + x;
                        grid[at] = (byte)(mode == HashLifePasteMode.Xor ? grid[at] ^ piece[y * 9 + x] : grid[at] & piece[y * 9 + x]);
                    }
                two.SetRect(2, 3, piece, 9, 7, mode);
                Assert.True(two.GetRect(0, 0, 19, 19).AsSpan().SequenceEqual(grid), mode.ToString());
            }
            string before = two.ToMacrocell();
            Assert.Throws<ArgumentException>(() => two.SetRect(0, 0, new byte[] { 2, 2, 2, 2 }, 2, 2, HashLifePasteMode.Xor));
            two.SetCell(30, 30, 4);
            Assert.Throws<ArgumentException>(() => two.SetRect(29, 29, Enumerable.Repeat((byte)1, 9).ToArray(), 3, 3, HashLifePasteMode.And));
            two.SetCell(30, 30, 0);
            Assert.Equal(before, two.ToMacrocell());
        }

        [Theory]
        [InlineData(true)]
        [InlineData(false)]
        public void TurnsAndFlipsMatchAPlainGrid(bool clockwise)
        {
            var u = new MultiStateHashLife(new Cycle(7));
            byte[] a = Noise(9, 14, 5, 7);
            u.SetRect(-3, 2, a, 14, 9);
            CellBox turned = u.RotateRect(-3, 2, 10, 10, clockwise);
            byte[] want = clockwise ? Patterns.Rotate90(a, 14, 9) : Patterns.Rotate90Ccw(a, 14, 9);
            Assert.True(u.GetRect((long)turned.X0, (long)turned.Y0, (long)turned.X1, (long)turned.Y1).AsSpan().SequenceEqual(want));
            Assert.Equal(a.Count(c => c != 0), (int)u.Population);
            u.RotateRect((long)turned.X0, (long)turned.Y0, (long)turned.X1, (long)turned.Y1, !clockwise);
            Assert.True(u.GetRect(-3, 2, 10, 10).AsSpan().SequenceEqual(a));
            u.FlipRect(-3, 2, 10, 10, horizontal: true);
            Assert.True(u.GetRect(-3, 2, 10, 10).AsSpan().SequenceEqual(Patterns.FlipH(a, 14, 9)));
            u.FlipRect(-3, 2, 10, 10, horizontal: false);
            Assert.True(u.GetRect(-3, 2, 10, 10).AsSpan().SequenceEqual(Patterns.FlipV(Patterns.FlipH(a, 14, 9), 14, 9)));
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public void AdvancingPartMatchesTheGrid(bool outside)
        {
            byte[] grid = WireSoup(40, 40, 6);
            var u = new MultiStateHashLife();
            u.SetRect(0, 0, grid, 40, 40);
            var w = new Wireworld(40, 40, grid);
            if (outside)
            {
                w.AdvanceOutside(8, 5, 30, 33, 13);
                u.AdvanceOutside(8, 5, 30, 33, 13);
            }
            else
            {
                w.AdvanceSelection(8, 5, 30, 33, 13);
                u.AdvanceSelection(8, 5, 30, 33, 13);
            }
            Assert.True(u.GetRect(0, 0, 39, 39).AsSpan().SequenceEqual(w.State));
            Assert.Equal(0, (int)u.Generation);
        }

        [Fact]
        public void EveryEditMatchesTheTwoStateEngine()
        {
            var u = new MultiStateHashLife(new LifeStates("B36/S23"));
            var h = new HashLife("B36/S23");
            byte[] a = Noise(50, 60, 7);
            u.SetRect(-30, -20, a, 60, 50);
            h.SetRect(-30, -20, a, 60, 50);
            u.ClearRect(-10, -10, 5, 3);
            h.ClearRect(-10, -10, 5, 3);
            u.ClearOutside(-28, -19, 25, 28);
            h.ClearOutside(-28, -19, 25, 28);
            Assert.Equal(h.RotateRect(-25, -15, 0, 3, true), u.RotateRect(-25, -15, 0, 3, true));
            u.FlipRect(-5, -5, 20, 20, horizontal: false);
            h.FlipRect(-5, -5, 20, 20, horizontal: false);
            u.AdvanceSelection(-20, -20, 10, 10, 37);
            h.AdvanceSelection(-20, -20, 10, 10, 37);
            u.AdvanceOutside(-10, -10, 0, 0, 9);
            h.AdvanceOutside(-10, -10, 0, 0, 9);
            u.Step(100);
            h.Step(100);
            Assert.Equal(State(h), State(u));
            foreach (var (x0, y0, x1, y1) in new[] { (-50, -50, 50, 50), (-3, -7, 4, 9), (100, 100, 200, 200) })
            {
                Assert.Equal(h.BoundingBoxIn(x0, y0, x1, y1), u.BoundingBoxIn(x0, y0, x1, y1));
                Assert.Equal(h.PopulationIn(x0, y0, x1, y1), u.PopulationIn(x0, y0, x1, y1));
            }
            Assert.Equal(h.PopulationIn(-BigInteger.Pow(10, 30), -1, BigInteger.Pow(10, 30), 1), u.PopulationIn(-BigInteger.Pow(10, 30), -1, BigInteger.Pow(10, 30), 1));
        }

        [Fact]
        public void ARuleChangeKeepsCellsAndRefusesMissingStates()
        {
            var u = new MultiStateHashLife(new Cycle(9));
            u.SetRect(0, 0, Noise(10, 10, 2, 5), 10, 10); // states up to 4
            HashLifeSnapshot snap = u.Snapshot();
            Assert.Throws<ArgumentException>(() => u.Rule = "WireWorld");
            Assert.Equal("Test-Cycle-9", u.Rule);
            u.ClearRect(0, 0, 9, 9);
            u.SetRect(0, 0, Noise(10, 10, 2, 4), 10, 10);
            u.Rule = "WireWorld";
            Assert.Equal(4, u.States);
            Assert.Throws<ArgumentException>(() => u.Restore(snap)); // it holds a 4 that WireWorld lacks
            u.StateRule = new Cycle(9);
            u.Restore(snap);
            Assert.Equal(4, u.GetRect(0, 0, 9, 9).Max());
        }

        // -- snapshots ------------------------------------------------------------------------------

        [Fact]
        public void SnapshotsSurviveCollectionAndBelongToOneUniverse()
        {
            var u = new MultiStateHashLife();
            u.SetRect(0, 0, WireSoup(50, 50, 3), 50, 50);
            HashLifeSnapshot start = u.Snapshot();
            var first = State(u);
            u.Step(90);
            HashLifeSnapshot mid = u.Snapshot();
            var middle = State(u);
            u.Step(300);
            u.CollectGarbage();
            u.Restore(start);
            Assert.Equal((0, first), ((int)u.Generation, State(u)));
            u.Restore(mid);
            Assert.Equal((90, middle), ((int)u.Generation, State(u)));
            Assert.Throws<ArgumentException>(() => new MultiStateHashLife().Restore(mid));
            Assert.Throws<ArgumentException>(() => new HashLife().Restore(mid));
            Assert.Throws<ArgumentException>(() => u.Restore(new HashLife().Snapshot()));
            mid.Release();
            Assert.Throws<ArgumentException>(() => u.Restore(mid));
        }

        [Fact]
        public void MeasuredNodesAreTheMacrocellLines()
        {
            var u = new MultiStateHashLife();
            u.SetRect(0, 0, ClockLoop(16), 16, 16);
            HashLifeSnapshot one = u.Snapshot();
            u.Step(5);
            HashLifeSnapshot two = u.Snapshot();
            u.SetCell(40, 40, 3);
            int lines = u.ToMacrocell().Split('\n').Count(line => line.Length > 0 && char.IsDigit(line[0]));
            SnapshotFootprint footprint = u.MeasureSnapshots(new[] { two, one, two });
            Assert.Equal(lines, footprint.UniverseNodes);
            Assert.Equal(0, footprint.Added[2]);
            Assert.Equal(footprint.Added.Sum(), footprint.Nodes);
            Assert.Equal(footprint.Nodes * 40, footprint.EstimatedBytes);
            Assert.Equal(0, new MultiStateHashLife().MeasureSnapshots(Array.Empty<HashLifeSnapshot>()).UniverseNodes);
            one.Release();
            Assert.Equal(new long[] { 0 }, u.MeasureSnapshots(new[] { one }).Added.ToArray());
        }

        // -- frames ---------------------------------------------------------------------------------

        private static int Shown(IEnumerable<byte> block, byte[] order)
        {
            var present = new HashSet<int>(block.Where(v => v != 0).Select(v => (int)v));
            foreach (byte state in order)
            {
                if (present.Contains(state))
                    return state;
            }
            return present.Count == 0 ? 0 : present.Min();
        }

        [Theory]
        [InlineData(new byte[0])]
        [InlineData(new byte[] { 3 })]
        [InlineData(new byte[] { 2, 1 })]
        [InlineData(new byte[] { 5, 4, 3, 2, 1 })]
        public void FramesMatchTheCellsAtEveryScale(byte[] order)
        {
            var u = new MultiStateHashLife(new Cycle(6));
            u.SetRect(-30, -20, Noise(48, 64, 2, 6), 64, 48);
            u.ZoomOrder = order;
            byte[] cells = u.GetRect(-40, -31, 55, 48); // 96 × 80, tree rows -32..47: aligned to 2, 4 and 8
            Assert.True(u.Frame(96, 80, new LifeView(-40, -32, 0)).AsSpan().SequenceEqual(cells));
            byte[] density = u.Frame(96, 80, new LifeView(-40, -32, 0), MultiStateRenderMode.Density);
            Assert.True(density.AsSpan().SequenceEqual(cells.Select(c => (byte)(c != 0 ? 255 : 0)).ToArray()));
            byte[] up = u.Frame(384, 320, new LifeView(-160, -128, 2));
            for (int py = 0; py < 320; py += 7)
                for (int px = 0; px < 384; px += 5)
                    Assert.Equal(cells[(py >> 2) * 96 + (px >> 2)], up[py * 384 + px]);
            for (int s = 1; s <= 3; s++)
            {
                int f = 1 << s, w = 96 / f, h = 80 / f;
                byte[] frame = u.Frame(w, h, new LifeView(-40 >> s, -32 >> s, -s));
                byte[] dense = u.Frame(w, h, new LifeView(-40 >> s, -32 >> s, -s), MultiStateRenderMode.Density);
                for (int by = 0; by < h; by++)
                    for (int bx = 0; bx < w; bx++)
                    {
                        var block = new List<byte>();
                        for (int y = 0; y < f; y++)
                            for (int x = 0; x < f; x++)
                                block.Add(cells[(by * f + y) * 96 + bx * f + x]);
                        Assert.Equal(Shown(block, order), frame[by * w + bx]);
                        int p = block.Count(v => v != 0);
                        Assert.Equal((255 * p + f * f - 1) / (f * f), dense[by * w + bx]);
                    }
            }
        }

        [Fact]
        public void FramesFarOutShowTheQuarters()
        {
            var u = new MultiStateHashLife(new Cycle(6));
            u.SetRect(-1, 0, new byte[] { 5, 4, 3, 2 }, 2, 2); // one cell in each quarter
            u.ZoomOrder = new byte[] { 4, 2 };
            foreach (int s in new[] { 2, 9, 600 })
            {
                byte[] frame = u.Frame(4, 4, new LifeView(-2, -2, -s));
                Assert.Equal(new byte[] { 0, 0, 0, 0, 0, 5, 4, 0, 0, 3, 2, 0, 0, 0, 0, 0 }, frame);
            }
            Assert.Equal(1, u.Frame(2, 2, new LifeView(-1, -1, -40), MultiStateRenderMode.Density).Max());
        }

        [Fact]
        public void TheZoomOrderIsChecked()
        {
            var u = new MultiStateHashLife();
            Assert.Throws<ArgumentException>(() => u.ZoomOrder = new byte[] { 0 });
            Assert.Throws<ArgumentException>(() => u.ZoomOrder = new byte[] { 1, 1 });
            u.ZoomOrder = new byte[] { 3, 1 };
            byte[] copy = u.ZoomOrder;
            copy[0] = 2;
            Assert.Equal(new byte[] { 3, 1 }, u.ZoomOrder);
        }

        // -- files ----------------------------------------------------------------------------------

        [Theory]
        [InlineData("clock.rle")]
        [InlineData("clock.mc")]
        [InlineData("clock.mc.gz")]
        public void FilesRoundTrip(string name)
        {
            var u = new MultiStateHashLife();
            u.SetRect(-7, 3, ClockLoop(16), 16, 16);
            u.Step(9);
            var notes = new PatternMetadata("Clock", "nobody", new[] { "a loop" });
            MultiStatePatternUniverse found = MultiStateFiles.ReadUniverse(u.EncodeFile(name, notes));
            Assert.Equal(u.ToMacrocell(), found.Universe.ToMacrocell());
            Assert.Equal(notes, found.Metadata);
            Assert.Equal(name.EndsWith(".rle", StringComparison.Ordinal) ? PatternFormat.Rle : PatternFormat.Macrocell, found.Format);
        }

        [Fact]
        public void MacrocellReadsBothLeafSyntaxesAndWritesLevelOneLeaves()
        {
            var two = new HashLife();
            two.SetRect(-3, -2, Noise(19, 23, 5), 23, 19);
            string text = two.ToMacrocell().Replace("#R B3/S23", "#R life-b3-s23"); // names the object
            MultiStateHashLife asStates = MultiStateHashLife.FromMacrocell(text, new LifeStates());
            CellBox box = two.BoundingBox!.Value;
            Assert.Equal(box, asStates.BoundingBox);
            Assert.True(asStates.GetRect((long)box.X0, (long)box.Y0, (long)box.X1, (long)box.Y1)
                .AsSpan().SequenceEqual(two.GetRect((long)box.X0, (long)box.Y0, (long)box.X1, (long)box.Y1)));
            Assert.DoesNotContain(asStates.ToMacrocell().Split('\n'), line => line.StartsWith(".") || line.StartsWith("*") || line.StartsWith("$"));
            Assert.Equal("[M2] (heaton-life)\n#R WireWorld\n1 0 0 0 0\n", new MultiStateHashLife().ToMacrocell());
            var one = new MultiStateHashLife();
            one.SetCell(0, 0, 3);
            Assert.EndsWith("\n1 0 3 0 0\n", one.ToMacrocell());
        }

        [Theory]
        [InlineData("[M2]\n#R WireWorld\n1 0 4 0 0\n")]
        [InlineData("[M2]\n1 0 256 0 0\n")]
        [InlineData("[M2]\n#R Langton\n1 0 1 0 0\n")]
        [InlineData("[M2]\n1 0 1 0 0\n3 1 0 0 0\n")]
        [InlineData("[M2]\n2 1 0 0 0\n")]
        [InlineData("[M2]\n0 0 0 0 0\n")]
        [InlineData("[M2]\n#G -1\n1 0 1 0 0\n")]
        [InlineData("[M2]\n")]
        [InlineData("x = 1, y = 1\n1 0 1 0 0\n")]
        public void MacrocellRefusals(string text)
        {
            Exception e = Assert.ThrowsAny<Exception>(() => MultiStateHashLife.FromMacrocell(text));
            Assert.True(e is FormatException || e is ArgumentException, e.ToString());
        }

        [Fact]
        public void RleReadsEitherDialectAndWritesCanonically()
        {
            MultiStateHashLife u = MultiStateHashLife.FromRle("#CXRLE Pos=-4,7 Gen=12\nx = 3, y = 2, rule = WireWorld\nCBA$.2C!");
            Assert.Equal(12, (int)u.Generation);
            Assert.Equal(new byte[] { 3, 2, 1, 0, 3, 3 }, u.GetRect(-4, 7, -2, 8));
            Assert.Equal("#CXRLE Pos=-4,7 Gen=12\nx = 3, y = 2, rule = WireWorld\nCBA$.2C!\n", u.ToRle());
            MultiStateHashLife heads = MultiStateHashLife.FromRle("x = 3, y = 1\nobo!");
            Assert.Equal("WireWorld", heads.Rule);
            Assert.Equal("#CXRLE Pos=0,0\nx = 3, y = 1, rule = WireWorld\nobo!\n", heads.ToRle());
            Assert.ThrowsAny<Exception>(() => MultiStateHashLife.FromRle("x = 1, y = 1, rule = WireWorld\nD!"));
            Assert.ThrowsAny<Exception>(() => MultiStateHashLife.FromRle("#CXRLE Pos=1000000000,0\nx = 2, y = 1\n2C!"));
            Assert.ThrowsAny<Exception>(() => MultiStateHashLife.FromRle("x = 1, y = 1, rule = WireWorld\n999999999999C!"));
            var many = new MultiStateHashLife(new Cycle(256));
            many.SetCell(0, 0, 25);
            many.SetCell(3, 0, 255);
            string[] lines = many.ToRle().Split('\n');
            Assert.Equal("pA2.yO!", lines[lines.Length - 2]); // every state writes (spec/patterns.md)
            Assert.Contains(
                "bounded grid",
                Assert.Throws<FormatException>(() => MultiStateHashLife.FromRle("x = 3, y = 1, rule = WireWorld:T30,20\nCBA!")).Message);
        }

        [Fact]
        public void LoadingByContentRefusesTwoStateFormats()
        {
            Assert.Throws<FormatException>(() => MultiStateFiles.ReadUniverse(Encoding.ASCII.GetBytes("!Name: x\n.O.\n")));
            using var output = new MemoryStream();
            using (var gzip = new GZipStream(output, CompressionLevel.Optimal, leaveOpen: true))
            {
                byte[] text = Encoding.ASCII.GetBytes("x = 2, y = 1, rule = WireWorld\nAC!");
                gzip.Write(text, 0, text.Length);
            }
            Assert.Equal(2, (int)MultiStateFiles.ReadUniverse(output.ToArray()).Universe.Population);
        }

        [Fact]
        public void ReadSnapshotLeavesTheUniverseAlone()
        {
            var u = new MultiStateHashLife();
            u.SetRect(0, 0, ClockLoop(16), 16, 16);
            HashLifeSnapshot before = u.Snapshot();
            var state = (u.ToMacrocell(), u.Generation, u.Rule);
            var other = new MultiStateHashLife();
            other.SetRect(100, 100, WireSoup(12, 12, 1), 12, 12);
            other.Step(3);
            PatternSnapshot found = u.ReadSnapshot(Encoding.ASCII.GetBytes(other.ToMacrocell()));
            Assert.Equal(state, (u.ToMacrocell(), u.Generation, u.Rule));
            Assert.Equal("WireWorld", found.Rule);
            Assert.Equal(PatternFormat.Macrocell, found.Format);
            Assert.Empty(found.Frames);
            u.Restore(found.Snapshot);
            Assert.Equal(other.ToMacrocell(), u.ToMacrocell());
            u.Restore(before);
            Assert.Equal(state.Item1, u.ToMacrocell());
            Assert.Equal("WireWorld", u.ReadSnapshot("x = 1, y = 1\no!").Rule);
            Assert.ThrowsAny<Exception>(() => u.ReadSnapshot("[M2]\n#R Nothing\n1 0 1 0 0\n"));
            Assert.Equal(state, (u.ToMacrocell(), u.Generation, u.Rule));
        }

        [Fact]
        public void TimelinesRoundTrip()
        {
            var u = new MultiStateHashLife();
            var (w, h, cells) = Wireworld.ParseText("TH#####\n#.....#\n#######");
            u.SetRect(0, 0, cells, w, h);
            var frames = new List<HashLifeSnapshot>();
            for (int i = 0; i < 4; i++)
            {
                frames.Add(u.Snapshot());
                u.Step(3);
            }
            string text = MultiStateMacrocell.WriteTimeline(u, frames, new PatternMetadata("Loop"));
            Assert.Contains("#FRAMES 4 0 3^1", text);
            MultiStateTimeline timeline = MultiStateMacrocell.ReadTimeline(text);
            Assert.Equal(3, (int)timeline.Step);
            Assert.Equal("Loop", timeline.Metadata.Name);
            for (int i = 0; i < 4; i++)
            {
                u.Restore(frames[i]);
                timeline.Universe.Restore(timeline.Frames[i]);
                Assert.Equal(u.ToMacrocell(), timeline.Universe.ToMacrocell());
            }
            MultiStatePatternUniverse found = MultiStateFiles.ReadUniverse(text);
            Assert.Equal(4, found.Frames.Count);
            Assert.Equal(3, (int)found.Step!.Value);
            Assert.Throws<ArgumentException>(() => MultiStateMacrocell.WriteTimeline(u, new[] { frames[0], frames[1], frames[3] }));
        }

        // -- live cells (spec/hashlife-multistate.md "Observables") ---------------------------------

        private static long LiveByHand(MultiStateHashLife u, long x0, long y0, long x1, long y1, bool odd)
            => u.GetRect(x0, y0, x1, y1).LongCount(c => odd ? (c & 1) != 0 : c != 0);

        [Theory]
        [InlineData("B3/S23History")]
        [InlineData("B36/S23Super")]
        [InlineData("B2/S345/C4")]
        [InlineData("WireWorld")]
        public void LiveCellsAreTheOnCellsUnderHistoryAndSuper(string rule)
        {
            // Under History and Super the live cells are the odd states, an envelope and the marks
            // that are off left out; under every other rule they are the non-zero cells.
            bool odd = rule.EndsWith("History", StringComparison.Ordinal) || rule.EndsWith("Super", StringComparison.Ordinal);
            var u = new MultiStateHashLife(rule);
            byte[] soup = Noise(40, 50, 5, u.States);
            u.SetRect(-20, -9, soup, 50, 40);
            foreach (int n in new[] { 0, 1, 7, 30 })
            {
                u.Step(n);
                CellBox b = u.BoundingBox!.Value;
                long x0 = (long)b.X0 - 3, y0 = (long)b.Y0 - 3, x1 = (long)b.X1 + 3, y1 = (long)b.Y1 + 3;
                Assert.Equal(LiveByHand(u, x0, y0, x1, y1, odd), (long)u.LivePopulation);
                Assert.Equal(u.LivePopulation, u.LivePopulationIn(x0, y0, x1, y1));
                foreach (var (a, c, d, e) in new[] { (x0 + 3, y0 + 3, x0 + 12, y0 + 10), (-5L, -5L, 4L, 6L), (x1 - 6, y0 + 3, x1 + 37, y1 - 5) })
                    Assert.Equal(LiveByHand(u, a, c, d, e, odd), (long)u.LivePopulationIn(a, c, d, e));
                if (odd)
                {
                    Assert.True(u.LivePopulation < u.Population); // the envelope is off
                }
                else
                {
                    Assert.Equal(u.Population, u.LivePopulation);
                    Assert.Equal(u.PopulationIn(x0, y0, x1, y1), u.LivePopulationIn(x0, y0, x1, y1));
                }
            }
            BigInteger far = BigInteger.Pow(10, 30);
            Assert.Equal(BigInteger.Zero, u.LivePopulationIn(far, far, far + 5, far + 5));
            Assert.Equal(BigInteger.Zero, u.LivePopulationIn(5, 5, 4, 4)); // an empty rectangle
        }

        [Fact]
        public void LiveCellsFollowTheRuleAndSurviveCollection()
        {
            var u = new MultiStateHashLife("B3/S23History", 10);
            u.SetRect(0, 0, new byte[] { 0, 1, 0, 0, 0, 1, 1, 1, 1 }, 3, 3); // a glider
            u.Step(64);
            Assert.Equal(5, (int)u.LivePopulation); // its trail is the envelope
            Assert.True(u.Population > 5);
            u.Rule = "B3/S23Super"; // states 0-6 mean the same
            Assert.Equal(5, (int)u.LivePopulation);
            u.Rule = "B3/S23/C7"; // a Generations rule of seven states: every non-zero cell lives
            Assert.Equal(u.Population, u.LivePopulation);
            u.Rule = "B3/S23History";
            u.CollectGarbage();
            Assert.Equal(5, (int)u.LivePopulation);
            u.SetCell(1000, 1000, 4); // marked off
            u.SetCell(1001, 1000, 3); // marked on
            Assert.Equal(6, (int)u.LivePopulation);
            Assert.Equal(1, (int)u.LivePopulationIn(1000, 1000, 1001, 1000));
            u.Clear();
            Assert.Equal(BigInteger.Zero, u.LivePopulation);
            Assert.Equal(BigInteger.Zero, u.LivePopulationIn(-9, -9, 9, 9));
        }

        // -- measuring and naming the rule (spec/hashlife-multistate.md "Pattern I/O") ---------------

        private static void MeasureAgreesWithReading(byte[] data, StateRule? rule = null)
        {
            PatternExtent extent = MultiStateFiles.Measure(data, rule);
            MultiStatePatternUniverse read = MultiStateFiles.ReadUniverse(data, rule);
            MultiStateHashLife u = read.Universe;
            Assert.Equal(read.Format, extent.Format);
            CellBox? box = u.BoundingBox;
            if (box == null)
            {
                Assert.Equal((BigInteger.Zero, BigInteger.Zero, BigInteger.Zero, BigInteger.Zero), (extent.Width, extent.Height, extent.X, extent.Y));
            }
            else
            {
                CellBox b = box.Value;
                Assert.Equal((b.X0, b.Y0, b.X1 - b.X0 + 1, b.Y1 - b.Y0 + 1), (extent.X, extent.Y, extent.Width, extent.Height));
            }
            Assert.Equal(read.RuleNamed ? u.Rule : null, extent.Rule);
            Assert.Equal(u.Generation, extent.Generation);
            Assert.Equal(read.Metadata, extent.Metadata);
            Assert.Null(extent.BoundedGrid);
            if (data.All(c => c < 128)) // a text file measures the same handed over as text
                Assert.Equal(extent.Width, MultiStateFiles.Measure(Encoding.ASCII.GetString(data), rule).Width);
        }

        [Fact]
        public void MeasuringGivesWhatReadingGives()
        {
            var files = new List<byte[]>();
            foreach (string text in new[]
            {
                "[M2]\n#R WireWorld\n#G 12\n#N Name\n1 0 3 0 0\n", // a lone leaf: tree (0, -1)
                "[M2]\n1 0 0 1 0\n", // names no rule
                "[M2]\n#R LifeSuper\n1 0 25 0 0\n1 7 0 0 13\n2 1 0 0 2\n3 0 0 0 3\n",
                "[M2]\n#R B3/S23History\n1 0 0 0 0\n2 0 0 0 0\n", // every cell 0
                "[M2]\n#R B2/S345/C4\n$$...*$\n4 0 1 0 1\n", // a two-state leaf
                "#CXRLE Pos=-4,7 Gen=12\nx = 9, y = 3, rule = WireWorld\n3.CBA$$.2C!",
                "x = 2, y = 2\n$bo!", // names no rule
                "x = 3, y = 1, rule = B2/S345/C4\n0C2.A!",
                "#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#L 3.A$.BC\n",
            })
            {
                files.Add(Encoding.UTF8.GetBytes(text));
            }
            var two = new HashLife();
            two.SetRect(-3, -2, Noise(23, 19, 5), 19, 23);
            files.Add(Encoding.UTF8.GetBytes(two.ToMacrocell().Replace("#R B3/S23\n", "")));
            var wire = new MultiStateHashLife();
            wire.SetRect(-1000, 77, ClockLoop(16), 16, 16);
            wire.Step(5);
            files.Add(Encoding.UTF8.GetBytes(wire.ToMacrocell()));
            using (var buffer = new MemoryStream())
            {
                using (var gzip = new GZipStream(buffer, CompressionLevel.Optimal, leaveOpen: true))
                {
                    byte[] rle = Encoding.UTF8.GetBytes(wire.ToRle());
                    gzip.Write(rle, 0, rle.Length);
                }
                files.Add(buffer.ToArray());
            }
            foreach (byte[] data in files)
                MeasureAgreesWithReading(data);
            MeasureAgreesWithReading(Encoding.UTF8.GetBytes("x = 1, y = 1\nE!"), StateRules.Compile("B3/S23History"));
        }

        [Fact]
        public void TheMeasureSaysHowTheFileWritesItsCells()
        {
            Assert.False(MultiStateFiles.Measure("[M2]\n#R WireWorld\n1 0 3 0 0\n").TwoState);
            Assert.True(MultiStateFiles.Measure("[M2]\n#R WireWorld\n$$...*$\n").TwoState);
            Assert.False(MultiStateFiles.Measure("x = 2, y = 1, rule = WireWorld\n2o!").TwoState);
            Assert.True(MultiStateFiles.Measure("x = 2, y = 1\n2o!").TwoState);
            Assert.False(MultiStateFiles.Measure("#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#L A\n").TwoState);
            PatternExtent empty = MultiStateFiles.Measure("[M2]\n1 0 0 0 0\n");
            Assert.True(empty.Width.IsZero && empty.Height.IsZero && empty.X.IsZero && empty.Y.IsZero);
            Assert.Null(empty.Rule);
        }

        [Theory]
        [InlineData("!Name: x\n.O.\n")] // plaintext
        [InlineData("[M2]\n#R Nothing\n1 0 1 0 0\n")]
        [InlineData("[M2]\n#R B3/S23\n1 0 1 0 0\n")]
        [InlineData("[M2]\n#R WireWorld\n1 0 4 0 0\n")]
        [InlineData("[M2]\n1 0 5 0 0\n")] // no rule: the reader's, WireWorld
        [InlineData("[M2]\n#R B03/S23History\n1 0 1 0 0\n")]
        [InlineData("[M2]\n2 1 0 0 0\n")]
        [InlineData("x = 3, y = 1, rule = WireWorld:T30,20\nCBA!")]
        [InlineData("#CXRLE Pos=1000000000,0\nx = 2, y = 1\n2C!")]
        [InlineData("x = 1, y = 1, rule = WireWorld\n999999999999C!")]
        [InlineData("x = 1, y = 1, rule = R2,C0,M1,S2..3,B3..3\no!")]
        [InlineData("#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#BOARD 20x20\n#L A\n")]
        [InlineData("#MCell 4.20\n#GAME Life\n#RULE 23/3\n#L A\n")]
        public void MeasuringRefusesWhatReadingRefuses(string text)
        {
            foreach (Action read in new Action[] { () => MultiStateFiles.Measure(text), () => MultiStateFiles.ReadUniverse(text) })
            {
                Exception? error = Record.Exception(read);
                Assert.True(error is FormatException || error is ArgumentException, $"{text}: {error?.GetType().Name ?? "read"}");
            }
        }

        [Theory]
        [InlineData("[M2]\n#R WireWorld\n1 0 3 0 0\n", true)]
        [InlineData("[M2]\n1 0 1 0 0\n", false)]
        [InlineData("x = 1, y = 1, rule = WireWorld\nC!", true)]
        [InlineData("x = 1, y = 1\no!", false)]
        [InlineData("#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#L A\n", true)]
        public void TheReaderSaysWhetherAFileNamedItsRule(string text, bool named)
        {
            MultiStatePatternUniverse read = MultiStateFiles.ReadUniverse(text, StateRules.Compile("B3/S23History"));
            Assert.Equal(named, read.RuleNamed);
            Assert.Equal(!named, read.Universe.Rule == "B3/S23History");
        }
    }
}
