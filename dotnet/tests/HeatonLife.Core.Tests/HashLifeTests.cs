using System;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// HashLife (spec/hashlife.md): known answers, the dense engine as oracle, editing in the
    /// ±10⁹ box, snapshots, cancellation, results that never depend on the memory budget, and
    /// the store's own promises (collection in flight, no allocation once warm). The C#
    /// counterpart of python/tests/test_hashlife.py.
    /// </summary>
    public class HashLifeTests
    {
        private const long Limit = HashLife.EditLimit;

        private static (byte[] Cells, int Width, int Height) Builtin(string name)
        {
            RlePattern p = BuiltinPatterns.All.First(b => b.Name == name).Decode();
            return (p.Cells, p.Width, p.Height);
        }

        private static HashLife Universe(string name, string rule = "B3/S23", long x = 0, long y = 0, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            var u = new HashLife(rule, maxMemoryMb);
            var (cells, width, height) = Builtin(name);
            u.SetRect(x, y, cells, width, height);
            return u;
        }

        /// <summary>Incompressible test input from an integer hash (simulation randomness stays PCG32).</summary>
        private static byte[] Noise(int height, int width, uint seed)
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
                cells[i] = (byte)(v >> 31);
            }
            return cells;
        }

        /// <summary>The whole state as its bounding box and that box's cells.</summary>
        private static (CellBox? Box, byte[] Cells) Cells(HashLife u)
        {
            CellBox? box = u.BoundingBox;
            if (box == null)
                return (null, Array.Empty<byte>());
            CellBox b = box.Value;
            return (box, u.GetRect((long)b.X0, (long)b.Y0, (long)b.X1, (long)b.Y1));
        }

        private static void SameCells(HashLife expected, HashLife actual)
        {
            var (boxA, cellsA) = Cells(expected);
            var (boxB, cellsB) = Cells(actual);
            Assert.Equal(boxA, boxB);
            Assert.True(cellsA.AsSpan().SequenceEqual(cellsB));
        }

        // -- known answers ----------------------------------------------------------------------

        [Theory]
        [InlineData("R-pentomino", 1103, 116)]
        [InlineData("Acorn", 5206, 633)]
        public void MethuselahsSettleToTheirPopulations(string name, int generation, int population)
        {
            HashLife u = Universe(name);
            u.Step(generation - 1);
            Assert.NotEqual(population, (int)u.Population);
            u.Step(1);
            Assert.Equal(population, (int)u.Population);
            u.Step(1 << 20);
            Assert.Equal(population, (int)u.Population);
        }

        [Fact]
        public void AGliderCrossesPast64BitCoordinates()
        {
            HashLife u = Universe("Glider");
            BigInteger m = BigInteger.One << 62;
            u.Step(4 * m + 4);
            Assert.Equal(new CellBox(m + 1, m + 1, m + 3, m + 3), u.BoundingBox);
            Assert.Equal(5, (int)u.Population);
            Assert.Equal(4 * m + 4, u.Generation);
        }

        [Fact]
        public void TheGunsPopulationGrowsWithoutBound()
        {
            HashLife gun = Universe("Gosper glider gun");
            BigInteger n = BigInteger.Pow(2, 200);
            gun.Step(n);
            Assert.True(gun.Population > 5 * (n / 30));
            Assert.True(gun.BoundingBox!.Value.X1 > BigInteger.Pow(2, 197));
        }

        // -- the dense engine as oracle ---------------------------------------------------------

        [Theory]
        [InlineData("B3/S23", 40, new[] { 1, 2, 5, 10, 33, 100, 211 })]
        [InlineData("B36/S23", 40, new[] { 1, 3, 17, 64, 150 })]
        [InlineData("B3678/S34678", 40, new[] { 1, 2, 9, 40, 120 })]
        [InlineData("B3/S12345", 32, new[] { 1, 4, 23, 80 })]
        [InlineData("B2/S", 12, new[] { 1, 2, 5, 13, 30, 41 })]
        [InlineData("B1357/S1357", 12, new[] { 1, 3, 7, 15, 31, 45 })]
        public void AgreesWithTheDenseEngine(string rule, int start, int[] checkpoints)
        {
            // Mixed step sizes against LifeLike on a dead-boundary grid the pattern never reaches.
            const int Size = 192;
            var grid = new byte[Size * Size];
            var soup = new byte[start * start];
            Seeding.Soup(soup, 0.4, 11);
            int lo = (Size - start) / 2;
            for (int y = 0; y < start; y++)
                Array.Copy(soup, y * start, grid, (lo + y) * Size + lo, start);
            var dense = new LifeLike(rule, Size, Size, Boundary.Dead);
            dense.SetState(grid);
            var u = new HashLife(rule);
            u.SetRect(-90, 7, grid, Size, Size); // anywhere: the plane has no preferred origin
            int current = 0;
            foreach (int gen in checkpoints)
            {
                dense.Step(gen - current);
                u.Step(gen - current);
                current = gen;
                Assert.Equal(gen, (int)u.Generation);
                Assert.True(u.GetRect(-90, 7, -90 + Size - 1, 7 + Size - 1).AsSpan().SequenceEqual(dense.State), $"generation {gen}");
                CellBox box = u.BoundingBox!.Value;
                Assert.True(box.X0 > -90 && box.X1 < -90 + Size - 1, "pattern reached the dense grid's edge");
            }
        }

        // -- editing ----------------------------------------------------------------------------

        [Fact]
        public void CellsRoundTripThroughRectanglesAnywhereInTheBox()
        {
            var u = new HashLife();
            byte[] a = Noise(37, 53, 1);
            foreach (var (x, y) in new[] { (-13L, 7L), (Limit - 52, -Limit), (-Limit, Limit - 36) })
            {
                u.SetRect(x, y, a, 53, 37);
                Assert.True(u.GetRect(x, y, x + 52, y + 36).AsSpan().SequenceEqual(a));
            }
            Assert.Equal(3 * a.Count(c => c != 0), (int)u.Population);
        }

        [Fact]
        public void PasteModesMatchAPlainGrid()
        {
            var u = new HashLife();
            var mirror = new byte[70 * 90];
            const long X0 = -40, Y0 = -33;
            var modes = new[]
            {
                HashLifePasteMode.Copy, HashLifePasteMode.Or, HashLifePasteMode.Xor,
                HashLifePasteMode.Copy, HashLifePasteMode.Xor, HashLifePasteMode.Or,
            };
            for (int i = 0; i < modes.Length; i++)
            {
                int h = 21 + i, w = 34 - i;
                byte[] piece = Noise(h, w, (uint)(10 + i));
                int px = 3 * i + 1, py = 5 * i + 2;
                for (int y = 0; y < h; y++)
                {
                    for (int x = 0; x < w; x++)
                    {
                        ref byte cell = ref mirror[(py + y) * 90 + px + x];
                        byte p = piece[y * w + x];
                        cell = modes[i] switch
                        {
                            HashLifePasteMode.Copy => p,
                            HashLifePasteMode.Or => (byte)(cell | p),
                            _ => (byte)(cell ^ p),
                        };
                    }
                }
                u.SetRect(X0 + px, Y0 + py, piece, w, h, modes[i]);
                Assert.True(u.GetRect(X0, Y0, X0 + 89, Y0 + 69).AsSpan().SequenceEqual(mirror), modes[i].ToString());
            }
            Assert.Equal(mirror.Count(c => c != 0), (int)u.Population);
        }

        [Fact]
        public void SetGetAndClear()
        {
            var u = new HashLife();
            u.SetCell(5, -9, true);
            u.SetCell(-1_000_000, 777_777, true);
            Assert.True(u.GetCell(5, -9) && u.GetCell(-1_000_000, 777_777));
            Assert.False(u.GetCell(6, -9) || u.GetCell(-Limit, Limit));
            Assert.Equal(new CellBox(-1_000_000, -9, 5, 777_777), u.BoundingBox);
            u.SetCell(5, -9, false);
            Assert.Equal(1, (int)u.Population);
            var ones = Enumerable.Repeat((byte)1, 41 * 41).ToArray();
            u.SetRect(-20, -20, ones, 41, 41);
            u.ClearRect(-3, -2, 4, 6);
            Assert.Equal(41 * 41 - 8 * 9 + 1, (int)u.Population);
            Assert.Equal(0, (int)u.PopulationIn(-3, -2, 4, 6));
            u.Clear();
            Assert.Equal(0, (int)u.Population);
            Assert.Null(u.BoundingBox);
        }

        [Fact]
        public void PopulationAndBoxMatchTheCells()
        {
            var u = new HashLife();
            byte[] a = Noise(60, 45, 3);
            u.SetRect(100, -500, a, 45, 60);
            int minX = 45, minY = 60, maxX = -1, maxY = -1;
            for (int y = 0; y < 60; y++)
            {
                for (int x = 0; x < 45; x++)
                {
                    if (a[y * 45 + x] == 0)
                        continue;
                    minX = Math.Min(minX, x);
                    maxX = Math.Max(maxX, x);
                    minY = Math.Min(minY, y);
                    maxY = Math.Max(maxY, y);
                }
            }
            Assert.Equal(new CellBox(100 + minX, -500 + minY, 100 + maxX, -500 + maxY), u.BoundingBox);
            foreach (var (x0, y0, x1, y1) in new[] { (100, -500, 144, -441), (110, -480, 120, -470), (0, 0, 5, 5), (90, -510, 101, -499) })
            {
                int count = 0;
                for (int y = Math.Max(y0, -500); y <= Math.Min(y1, -441); y++)
                    for (int x = Math.Max(x0, 100); x <= Math.Min(x1, 144); x++)
                        count += a[(y + 500) * 45 + x - 100];
                Assert.Equal(count, (int)u.PopulationIn(x0, y0, x1, y1));
            }
            // Queries reach past the editing box.
            BigInteger far = BigInteger.Pow(10, 30);
            Assert.Equal(a.Count(c => c != 0), (int)u.PopulationIn(-far, -far, far, far));
            Assert.Equal(0, (int)u.PopulationIn(far, far, far + 5, far + 5));
        }

        [Fact]
        public void FillRandomIsTheLifelikeSoup()
        {
            var u = new HashLife();
            u.SetRect(-5, -3, Enumerable.Repeat((byte)1, 24 * 40).ToArray(), 40, 24);
            u.FillRandom(-5, -3, 34, 20, 0.4, 7);
            var soup = new byte[24 * 40];
            Seeding.Soup(soup, 0.4, 7);
            Assert.True(u.GetRect(-5, -3, 34, 20).AsSpan().SequenceEqual(soup));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.FillRandom(0, 0, 3, 3, 1.5, 1));
        }

        public static TheoryData<Action<HashLife>> OutsideTheBox() => new TheoryData<Action<HashLife>>
        {
            u => u.SetCell(Limit + 1, 0, true),
            u => u.GetCell(0, -Limit - 1),
            u => u.GetRect(Limit - 1, 0, Limit + 1, 0),
            u => u.ClearRect(-Limit - 1, 0, 0, 0),
            u => u.SetRect(Limit, 0, new byte[] { 1, 1 }, 2, 1),
            u => u.FillRandom(0, Limit, 0, Limit + 1, 0.5, 1),
            u => u.SetCell(long.MaxValue, 0, true),
            u => u.SetRect(long.MaxValue - 1, 0, new byte[] { 1, 1, 1 }, 3, 1, HashLifePasteMode.Or),
        };

        [Theory]
        [MemberData(nameof(OutsideTheBox))]
        public void EditingStopsAtTheBox(Action<HashLife> call)
        {
            var u = new HashLife();
            u.SetCell(Limit, -Limit, true); // the corners themselves are inside
            string before = u.ToMacrocell();
            var e = Assert.ThrowsAny<ArgumentException>(() => call(u));
            Assert.Contains("editing box", e.Message);
            Assert.Equal(1, (int)u.Population);
            Assert.Equal(before, u.ToMacrocell());
        }

        [Fact]
        public void TheBoxCornersAreInsideForEveryEdit()
        {
            var u = new HashLife();
            foreach (var (x, y) in new[] { (Limit, Limit), (-Limit, -Limit), (Limit, -Limit), (-Limit, Limit) })
            {
                u.SetCell(x, y, true);
                Assert.True(u.GetCell(x, y));
            }
            Assert.Equal(4, (int)u.Population);
            Assert.Equal(new CellBox(-Limit, -Limit, Limit, Limit), u.BoundingBox);
            u.ClearRect(-Limit, -Limit, -Limit, -Limit);
            Assert.Equal(3, (int)u.Population);
            u.FillRandom(Limit - 7, Limit - 7, Limit, Limit, 1.0, 3);
            Assert.Equal(66, (int)u.Population);
            Assert.True(u.GetRect(Limit - 7, Limit - 7, Limit, Limit).All(c => c == 1));
            // Both files carry it compactly: RLE spends one k$ token on each run of empty rows.
            foreach (HashLife back in new[] { HashLife.FromMacrocell(u.ToMacrocell()), HashLife.FromRle(u.ToRle()) })
            {
                Assert.Equal(u.BoundingBox, back.BoundingBox);
                Assert.Equal(u.ToMacrocell(), back.ToMacrocell());
            }
        }

        [Fact]
        public void RulesBudgetsAndStepsAreValidated()
        {
            Assert.Contains("B0", Assert.Throws<ArgumentException>(() => new HashLife("B03/S23")).Message);
            Assert.Throws<ArgumentException>(() => new HashLife("not a rule"));
            Assert.Throws<ArgumentOutOfRangeException>(() => new HashLife(maxMemoryMb: 9));
            var u = new HashLife("b36 / s32", 64);
            Assert.Equal("B36/S23", u.Rule);
            Assert.Equal(64, u.MaxMemoryMb);
            Assert.Throws<ArgumentOutOfRangeException>(() => u.Step(-1));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.MaxMemoryMb = 9);
            Assert.Equal(64, u.MaxMemoryMb);
            Assert.Throws<ArgumentException>(() => u.Rule = "B0/S8");
            Assert.Equal("B36/S23", u.Rule);
        }

        [Fact]
        public void RuleChangesKeepTheCells()
        {
            HashLife u = Universe("Replicator (HighLife)");
            u.Step(12);
            u.Rule = "B36/S23";
            u.Step(20);
            HashLife v = Universe("Replicator (HighLife)");
            v.Step(12);
            var w = new HashLife("B36/S23");
            CellBox box = v.BoundingBox!.Value;
            var (x0, y0, x1, y1) = ((long)box.X0, (long)box.Y0, (long)box.X1, (long)box.Y1);
            w.SetRect(x0, y0, v.GetRect(x0, y0, x1, y1), (int)(x1 - x0 + 1), (int)(y1 - y0 + 1));
            w.Step(20);
            SameCells(w, u);
        }

        // -- snapshots, memory, cancellation ----------------------------------------------------

        [Fact]
        public void SnapshotsSurviveCollectionAndRestore()
        {
            HashLife u = Universe("Acorn", maxMemoryMb: 10);
            HashLifeSnapshot start = u.Snapshot();
            u.Step(300);
            HashLifeSnapshot mid = u.Snapshot();
            string middle = u.ToMacrocell();
            // Enough work at the floor budget to collect in flight, more than once.
            u.Step(700);
            u.FillRandom(-256, -256, 255, 255, 0.35, 21);
            u.Step(256);
            u.CollectGarbage();
            Assert.True(u.Store.InFlightCollections > 0);
            u.Restore(start);
            Assert.Equal(0, (int)u.Generation);
            Assert.Equal(7, (int)u.Population);
            u.Restore(mid);
            Assert.Equal(300, (int)u.Generation);
            Assert.Equal(middle, u.ToMacrocell());
            Assert.Equal(300, (int)mid.Generation);
            Assert.Contains("another universe", Assert.Throws<ArgumentException>(() => new HashLife().Restore(mid)).Message);
            GC.KeepAlive(start);
        }

        [Fact]
        public void ResultsDoNotDependOnTheBudget()
        {
            byte[] a = Noise(160, 160, 5);
            var roomy = new HashLife();
            roomy.SetRect(0, 0, a, 160, 160);
            roomy.Step(1500);
            roomy.Step(BigInteger.Pow(2, 40) + 12345);
            var tight = new HashLife(maxMemoryMb: 10);
            tight.SetRect(0, 0, a, 160, 160);
            foreach (int n in new[] { 1, 1, 1000, 498 }) // a mix of sub-step sizes under constant pressure
                tight.Step(n);
            tight.Step(BigInteger.Pow(2, 40) + 12345);
            Assert.True(tight.Collections > 0);
            Assert.True(tight.Store.InFlightCollections > 0);
            Assert.Equal(roomy.Generation, tight.Generation);
            Assert.Equal(roomy.ToMacrocell(), tight.ToMacrocell());
        }

        [Fact]
        public void AStepThatCannotFitIsSplitUntilItDoes()
        {
            // A soup whose 2^8 sub-step outgrows the floor budget: it keeps collecting in flight,
            // is abandoned and halved, and still lands on the same cells as a roomy run.
            var roomy = new HashLife();
            roomy.FillRandom(-384, -384, 383, 383, 0.5, 21);
            roomy.Step(256);
            var tight = new HashLife(maxMemoryMb: 10);
            tight.FillRandom(-384, -384, 383, 383, 0.5, 21);
            tight.Step(256);
            Assert.True(tight.Store.Aborts > 0, "the run never needed to split a sub-step");
            Assert.Equal(256, (int)tight.Generation);
            Assert.Equal(roomy.ToMacrocell(), tight.ToMacrocell());
        }

        [Fact]
        public void AUniverseTooBigForItsBudgetRefusesToStepUnchanged()
        {
            var u = new HashLife(maxMemoryMb: 10);
            u.FillRandom(0, 0, 2999, 2999, 0.5, 9); // ~190k nodes, most of the floor budget
            Assert.True(u.MemoryUsed > 6L << 20);
            string before = u.ToMacrocell();
            var e = Assert.Throws<HashLifeMemoryException>(() => u.Step(1));
            Assert.Contains("MaxMemoryMb = 10", e.Message);
            Assert.Equal(0, (int)u.Generation);
            Assert.Equal(before, u.ToMacrocell());
            u.MaxMemoryMb = 2000;
            u.Step(1);
            Assert.Equal(1, (int)u.Generation);
        }

        [Fact]
        public void ACanceledStepStopsAtACompletedSubStep()
        {
            var u = new HashLife();
            u.SetRect(0, 0, Noise(256, 256, 2), 256, 256);
            using var cts = new CancellationTokenSource();
            long nodes = u.NodeCount;
            // Cancel from another thread once the 2^20 sub-step is well under way.
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
                // One generation, then 2^20 in a single sub-step.
                var e = Assert.Throws<OperationCanceledException>(() => u.Step((1 << 20) + 1, cts.Token));
                Assert.Equal(cts.Token, e.CancellationToken);
            }
            finally
            {
                cts.Cancel();
                watcher.Join();
            }
            Assert.Equal(1, (int)u.Generation);
            HashLife fresh = new HashLife();
            fresh.SetRect(0, 0, Noise(256, 256, 2), 256, 256);
            fresh.Step(1);
            Assert.Equal(fresh.ToMacrocell(), u.ToMacrocell());
            u.Step(1); // the next step runs with its own token
            Assert.Equal(2, (int)u.Generation);
        }

        [Fact]
        public void AStepCanceledBeforeItStartsChangesNothing()
        {
            HashLife u = Universe("R-pentomino");
            string before = u.ToMacrocell();
            using var cts = new CancellationTokenSource();
            cts.Cancel();
            Assert.Throws<OperationCanceledException>(() => u.Step(1000, cts.Token));
            Assert.Equal(0, (int)u.Generation);
            Assert.Equal(before, u.ToMacrocell());
            u.Step(0, cts.Token); // nothing to do, nothing to cancel
        }

        [Fact]
        public void StepAllocatesNothingOnceWarm()
        {
            // At the floor budget the arena reaches its cap and collects, between sub-steps and
            // in flight; from then on a step builds nodes but never touches the managed heap.
            // (Only an abandoned sub-step allocates: it unwinds with an exception.)
            var u = new HashLife(maxMemoryMb: 10);
            for (int round = 0; round < 3; round++)
            {
                // A fresh soup each round (pasting allocates, so it happens before the clock).
                u.Clear();
                u.FillRandom(-256, -256, 255, 255, 0.35, (ulong)(21 + round));
                int inFlight = u.Store.InFlightCollections, aborts = u.Store.Aborts;
                long before = GC.GetAllocatedBytesForCurrentThread();
                u.Step(256);
                for (int i = 0; i < 50; i++)
                    u.Step(1);
                long allocated = GC.GetAllocatedBytesForCurrentThread() - before;
                Assert.True(u.Store.InFlightCollections > inFlight, $"round {round} never collected in flight");
                Assert.Equal(aborts, u.Store.Aborts);
                if (round == 2) // rounds 0 and 1 grew the arena and the stacks
                    Assert.Equal(0, allocated);
            }
        }

        [Fact]
        public void WriteFrameAllocatesNothingOnceWarm()
        {
            HashLife u = Universe("Gosper glider gun", x: -18, y: -4);
            u.Step(BigInteger.Pow(2, 70)); // a root far past 64-bit coordinates
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
                u.WriteFrame(frame, 128, 96, view, HashLifeRenderMode.Any);
                u.WriteFrame(frame, 128, 96, view, HashLifeRenderMode.Density);
            }
            long before = GC.GetAllocatedBytesForCurrentThread();
            for (int round = 0; round < 5; round++)
            {
                foreach (LifeView view in views)
                {
                    u.WriteFrame(frame, 128, 96, view, HashLifeRenderMode.Any);
                    u.WriteFrame(frame, 128, 96, view, HashLifeRenderMode.Density);
                }
            }
            Assert.Equal(0, GC.GetAllocatedBytesForCurrentThread() - before);
        }

        // -- files ------------------------------------------------------------------------------

        [Theory]
        [InlineData("gun.rle")]
        [InlineData("gun.mc")]
        [InlineData("gun.mc.gz")]
        public void FilesRoundTrip(string name)
        {
            HashLife u = Universe("Gosper glider gun", x: -18, y: -4);
            u.Step(777);
            byte[] data = u.EncodeFile(name);
            HashLife back = HashLife.Load(data);
            Assert.Equal(u.ToMacrocell(), back.ToMacrocell());
            Assert.Equal(777, (int)back.Generation);
            if (name.EndsWith(".gz", StringComparison.Ordinal))
                Assert.Equal(new byte[] { 0x1f, 0x8b }, data.Take(2).ToArray());
        }

        [Fact]
        public void SavingRefusesUnknownExtensionsAndRlePastTheBox()
        {
            var u = new HashLife();
            Assert.Contains("extension", Assert.Throws<ArgumentException>(() => u.EncodeFile("gun.cells")).Message);
            u.SetCell(Limit, 0, true);
            HashLife far = HashLife.FromMacrocell(u.ToMacrocell().Replace("#R B3/S23", "#R B3/S23\n#C far"));
            Assert.StartsWith($"#CXRLE Pos={Limit},0", far.ToRle());
            HashLife glider = Universe("Glider");
            glider.Step(4 * (Limit + 1)); // it walks out of the box on its own
            Assert.Contains("Macrocell", Assert.Throws<InvalidOperationException>(() => glider.ToRle()).Message);
            Assert.Equal(glider.BoundingBox, HashLife.FromMacrocell(glider.ToMacrocell()).BoundingBox);
        }

        [Fact]
        public void MacrocellReadsLenientSpellings()
        {
            // CRLF line ends, blank lines, leading spaces, and gzip all occur in published files.
            string text = "[M2] (example 1.0)\r\n#R B3/S23\r\n\r\n  **$**$\r\n4 0 0 0 1\r\n";
            HashLife u = HashLife.FromMacrocell(text);
            Assert.Equal(4, (int)u.Population);
            Assert.Equal(new CellBox(0, 1, 1, 2), u.BoundingBox);
            HashLife gz = HashLife.FromMacrocell(u.EncodeFile("block.mc.gz"));
            Assert.Equal(u.ToMacrocell(), gz.ToMacrocell());
            Assert.Throws<FormatException>(() => HashLife.FromMacrocell("[M2]\n#G -5\n*$\n"));
            Assert.Throws<FormatException>(() => HashLife.FromMacrocell("[M2]\n4 1 0 0 0 0\n"));
            Assert.Throws<FormatException>(() => HashLife.FromMacrocell("[M2]\n0 0 0 0 0\n"));
        }

        [Fact]
        public void RleReadsLikeTheReference()
        {
            // Counts may not be split from their tags; dead runs and rows may be huge as long
            // as no live cell leaves the box.
            Assert.Throws<FormatException>(() => HashLife.FromRle("x = 3, y = 1\n3 o!\n"));
            Assert.Throws<FormatException>(() => HashLife.FromRle("x = 3, y = 1\n3o2"));
            HashLife u = HashLife.FromRle("#CXRLE Pos=-5,-5 Gen=12345678901234567890123\nbo99999999999999999999b$!\n");
            Assert.Equal(1, (int)u.Population);
            Assert.Equal(BigInteger.Parse("12345678901234567890123"), u.Generation);
            Assert.ThrowsAny<ArgumentException>(() => HashLife.FromRle("o99999999999999999999bo!"));
            HashLife empty = HashLife.FromRle("#CXRLE Pos=99999999999999999999,0\n5b!\n");
            Assert.Equal(0, (int)empty.Population);
            Assert.Throws<FormatException>(() => HashLife.FromRle("#CXRLE Gen=-1\no!"));
        }

        // -- views and frames -------------------------------------------------------------------

        [Fact]
        public void FramesMatchTheCellsAtEveryScale()
        {
            var u = new HashLife();
            var soup = new byte[48 * 64];
            Seeding.Soup(soup, 0.4, 2);
            u.SetRect(-30, -20, soup, 64, 48);
            byte[] cells = u.GetRect(-40, -31, 59, 48); // tree rows −32..47: aligned to 2 and 4
            Assert.True(u.Frame(100, 80, new LifeView(-40, -32, 0)).AsSpan().SequenceEqual(cells.Select(c => (byte)(c * 255)).ToArray()));
            byte[] up = u.Frame(400, 320, new LifeView(-160, -128, 2));
            for (int y = 0; y < 320; y++)
                for (int x = 0; x < 400; x++)
                    Assert.Equal(cells[(y / 4) * 100 + x / 4] * 255, up[y * 400 + x]);
            foreach (int s in new[] { 1, 2 })
            {
                int f = 1 << s, w = 100 / f, h = 80 / f;
                var view = new LifeView(-40 >> s, -32 >> s, -s);
                byte[] any = u.Frame(w, h, view);
                byte[] density = u.Frame(w, h, view, HashLifeRenderMode.Density);
                for (int by = 0; by < h; by++)
                {
                    for (int bx = 0; bx < w; bx++)
                    {
                        int pop = 0;
                        for (int dy = 0; dy < f; dy++)
                            for (int dx = 0; dx < f; dx++)
                                pop += cells[(by * f + dy) * 100 + bx * f + dx];
                        Assert.Equal(pop > 0 ? 255 : 0, any[by * w + bx]);
                        Assert.Equal((255 * pop + f * f - 1) / (f * f), density[by * w + bx]);
                    }
                }
            }
            Assert.Throws<ArgumentOutOfRangeException>(() => u.Frame(4, 4, new LifeView(0, 0, 0), (HashLifeRenderMode)7));
            Assert.Contains("deepest zoom", Assert.Throws<ArgumentOutOfRangeException>(() => new LifeView(0, 0, 6)).Message);
        }

        [Fact]
        public void DensityIsExactAtEveryScale()
        {
            // One cell gives ⌈255 / 4^s⌉ at every s, through the long, split-long, and BigInteger
            // paths (s ≤ 27, 28..31, ≥ 32).
            var u = new HashLife();
            u.SetCell(0, 1, true);
            var frame = new byte[4];
            for (int s = 3; s <= 70; s++)
            {
                u.WriteFrame(frame, 2, 2, new LifeView(-1, -1, -s), HashLifeRenderMode.Density);
                Assert.Equal(new byte[] { 0, 0, 0, (byte)(s == 3 ? 4 : 1) }, frame);
            }
            // The split-long arithmetic against BigInteger, across the whole population range.
            var rng = new Pcg32(99);
            for (int s = 3; s <= 31; s++)
            {
                BigInteger area = BigInteger.One << (2 * s);
                for (int i = 0; i < 2000; i++)
                {
                    long pop = i switch
                    {
                        0 => 0,
                        1 => 1,
                        2 => (long)area,
                        3 => (long)area - 1,
                        _ => (long)(((ulong)rng.NextU32() << 32 | rng.NextU32()) % ((ulong)area + 1)),
                    };
                    var want = (byte)((255 * new BigInteger(pop) + area - 1) / area);
                    Assert.Equal(want, HashLifeStore.DensityOf(pop, s));
                }
            }
            var full = new HashLife();
            full.SetRect(0, 1, Enumerable.Repeat((byte)1, 64 * 64).ToArray(), 64, 64);
            full.WriteFrame(frame, 2, 2, new LifeView(-1, -1, -6), HashLifeRenderMode.Density);
            Assert.Equal(new byte[] { 0, 0, 0, 255 }, frame);
            full.WriteFrame(frame, 2, 2, new LifeView(-1, -1, -7), HashLifeRenderMode.Density);
            Assert.Equal(new byte[] { 0, 0, 0, 64 }, frame); // ⌈255 · 4096 / 16384⌉
        }

        [Fact]
        public void ViewArithmeticRoundTrips()
        {
            foreach (var view in new[] { new LifeView(-7, 13, 0), new LifeView(BigInteger.Pow(3, 50), -BigInteger.Pow(3, 50), -20), new LifeView(5, -5, 4) })
            {
                Assert.Equal(view, LifeView.Pan(LifeView.Pan(view, 9, -4), -9, 4));
                if (view.Mag < 5)
                    Assert.Equal(view, LifeView.ZoomAt(LifeView.ZoomAt(view, 17, 3, 1), 17, 3, -1));
            }
            foreach (var (x, y, mag) in new[] { (0, 0, 0), (-17, 23, 4), (5, -1, 5) })
                Assert.Equal((new BigInteger(x), new BigInteger(y)), LifeView.CenterCell(LifeView.Centered(x, y, mag, 101, 77), 101, 77));
            var box = new CellBox(-1000, -20, 1000, 20);
            LifeView fitted = LifeView.Fit(box, 640, 480);
            var tl = LifeView.CellAt(fitted, 0, 0);
            var br = LifeView.CellAt(fitted, 639, 479);
            Assert.True(tl.X <= box.X0 && tl.Y <= box.Y0 && br.X >= box.X1 && br.Y >= box.Y1);
            Assert.Equal(5, LifeView.Fit(new CellBox(0, 0, 2, 2), 640, 480).Mag);
            // A box straddling an axis can't fit one pixel; Fit says so instead of searching forever.
            Assert.Throws<ArgumentException>(() => LifeView.Fit(new CellBox(-1, 0, 0, 0), 1, 1));
        }

        [Theory]
        [InlineData(1, 50, -5, 3, 7, 9)] // straddles x = 0 in a frame 1 pixel wide
        [InlineData(50, 1, 3, -5, 9, 7)] // straddles tree row 0 in a frame 1 pixel high
        [InlineData(0, 5, 3, 5, 9, 7)]   // a frame 0 pixels across holds nothing
        public void FitThrowsWhenNoViewHoldsTheBox(long width, long height, long x0, long y0, long x1, long y1)
        {
            Assert.Throws<ArgumentException>(() => LifeView.Fit(new CellBox(x0, y0, x1, y1), width, height));
        }

        [Fact]
        public void FitOnePixelFramesWhenNothingStraddles()
        {
            Assert.Equal(new LifeView(0, 0, -4), LifeView.Fit(new CellBox(3, 5, 9, 7), 1, 1));
            Assert.Equal(new LifeView(0, -1, 0), LifeView.Fit(new CellBox(0, 0, 0, 0), 1, 1));
            Assert.Equal(-3, LifeView.Fit(new CellBox(-5, 3, 7, 9), 2, 2).Mag);
            BigInteger big = BigInteger.Pow(10, 30);
            Assert.Throws<ArgumentException>(() => LifeView.Fit(new CellBox(-big, 1, big, 1), 1, 10));
        }

        [Fact]
        public void FramesFarOutMatchBlockPopulations()
        {
            // Past the root's own size a frame shows at most its four quarters, at any distance.
            var u = new HashLife();
            u.SetRect(-1, 0, new byte[] { 1, 1, 1, 1 }, 2, 2); // one cell in each quarter of the root
            var (glider, width, height) = Builtin("Glider");
            u.SetRect(5, -40, glider, width, height);
            u.SetRect(-90, 70, glider, width, height);
            var frame = new byte[36];
            foreach (int s in Enumerable.Range(1, 12).Concat(new[] { 600, 5000 }))
            {
                BigInteger block = BigInteger.One << s, area = block * block;
                foreach (var mode in new[] { HashLifeRenderMode.Any, HashLifeRenderMode.Density })
                {
                    u.WriteFrame(frame, 6, 6, new LifeView(-3, -3, -s), mode);
                    for (int j = 0; j < 6; j++)
                    {
                        for (int i = 0; i < 6; i++)
                        {
                            BigInteger bx = i - 3, by = j - 3;
                            BigInteger p = u.PopulationIn(bx * block, by * block + 1, (bx + 1) * block - 1, (by + 1) * block);
                            int want = mode == HashLifeRenderMode.Any ? (p.IsZero ? 0 : 255) : (int)((255 * p + area - 1) / area);
                            Assert.Equal(want, frame[j * 6 + i]);
                        }
                    }
                }
            }
        }

        // -- file numbers and row ends ----------------------------------------------------------

        [Theory]
        [InlineData("-5")]
        [InlineData("+5")]
        [InlineData("1_0")]
        [InlineData("٣")]
        [InlineData("")]
        [InlineData("5x")]
        public void GenerationsAreAsciiDigits(string value)
        {
            Assert.Throws<FormatException>(() => HashLife.FromMacrocell($"[M2]\n#G {value}\n*$\n"));
            Assert.Throws<FormatException>(() => HashLife.FromRle($"#CXRLE Gen={value}\nx = 1, y = 1\no!\n"));
        }

        [Theory]
        [InlineData("+5")]
        [InlineData("1_0")]
        [InlineData("٣")]
        [InlineData("")]
        [InlineData("--5")]
        [InlineData("5-")]
        public void PositionsAreAsciiDigitsAfterAnOptionalMinus(string value)
        {
            Assert.Throws<FormatException>(() => HashLife.FromRle($"#CXRLE Pos={value},0\nx = 1, y = 1\no!\n"));
            Assert.Throws<FormatException>(() => HashLife.FromRle($"#CXRLE Pos=0,{value}\nx = 1, y = 1\no!\n"));
        }

        [Fact]
        public void FileNumbersAcceptPlainDigits()
        {
            HashLife u = HashLife.FromRle("#CXRLE Pos=-3,007 Gen=0012\nx = 1, y = 1\no!\n");
            Assert.Equal(new CellBox(-3, 7, -3, 7), u.BoundingBox);
            Assert.Equal(12, (int)u.Generation);
            Assert.Equal(7, (int)HashLife.FromMacrocell("[M2]\n#G 007\n*$\n").Generation);
            Assert.Throws<FormatException>(() => HashLife.FromMacrocell("[M2]\n*$\n4 0 0 0 ١\n"));
        }

        [Fact]
        public void RleWritesARunOfRowEndsAsOneToken()
        {
            var grid = new byte[7 * 3];
            grid[0] = grid[3 * 3 + 1] = grid[6 * 3 + 2] = 1;
            Assert.Equal("x = 3, y = 7, rule = B3/S23\no3$bo3$2bo!\n", Patterns.RleEncode(grid, 3, 7));
            var u = new HashLife();
            u.SetRect(-3, -Limit, new byte[] { 1, 1, 1, 1 }, 2, 2);
            u.SetRect(0, Limit - 1, new byte[] { 1, 1, 1, 1 }, 2, 2);
            string text = u.ToRle(); // two billion rows, one token for the empty ones
            Assert.EndsWith("x = 5, y = 2000000001, rule = B3/S23\n2o$2o1999999998$3b2o$3b2o!\n", text);
            Assert.Equal(u.ToMacrocell(), HashLife.FromRle(text).ToMacrocell());
        }

        // -- the deepest tree (spec/hashlife.md "Depth") ------------------------------------------

        [Fact]
        public void StepsStopAtTheDeepestTree()
        {
            HashLife u = Universe("Glider");
            string start = u.ToMacrocell();
            BigInteger tooFar = BigInteger.One << (HashLife.MaxLevel - 2);
            foreach (BigInteger n in new[] { tooFar, tooFar + 1 }) // refused before anything runs
            {
                Assert.Throws<ArgumentOutOfRangeException>(() => u.Step(n));
                Assert.Equal((start, BigInteger.Zero), (u.ToMacrocell(), u.Generation));
            }
            BigInteger deepest = BigInteger.One << (HashLife.MaxLevel - 3); // the largest sub-step: a level-512 root
            for (int i = 0; i < 4; i++)
                u.Step(deepest);
            BigInteger m = deepest; // a glider moves (m, m) in 4m generations
            Assert.Equal(new CellBox(m, m, m + 2, m + 2), u.BoundingBox);
            string state = u.ToMacrocell();
            foreach (BigInteger n in new[] { deepest, BigInteger.One }) // spread past what level 512 steps
            {
                Assert.Contains("spread too far", Assert.Throws<InvalidOperationException>(() => u.Step(n)).Message);
                Assert.Equal((state, 4 * deepest), (u.ToMacrocell(), u.Generation));
            }
            // Everything else still works at that depth.
            Assert.Equal(5, (int)u.Population);
            Assert.Equal(5, (int)u.PopulationIn(m, m, m + 2, m + 2));
            Assert.Contains(u.Frame(2, 2, new LifeView(m >> 2, (m - 1) >> 2, -2), HashLifeRenderMode.Density), b => b > 0);
            HashLifeSnapshot snapshot = u.Snapshot();
            u.Clear();
            u.Restore(snapshot);
            Assert.Equal(state, HashLife.FromMacrocell(u.ToMacrocell()).ToMacrocell());
        }

        [Fact]
        public void MacrocellNodesStopAtTheDeepestLevel()
        {
            static string Chain(int top) // one cell in the far corner of a level-`top` tree
            {
                var text = new StringBuilder("[M2]\n*$\n4 0 0 0 1\n");
                for (int k = 5; k <= top; k++)
                    text.Append($"{k} 0 0 0 {k - 3}\n");
                return text.ToString();
            }
            HashLife u = HashLife.FromMacrocell(Chain(HashLife.MaxLevel));
            BigInteger corner = (BigInteger.One << (HashLife.MaxLevel - 1)) - 8;
            Assert.Equal(new CellBox(corner, corner + 1, corner, corner + 1), u.BoundingBox);
            Assert.Equal(Chain(HashLife.MaxLevel).Replace("[M2]", "[M2] (heaton-life)\n#R B3/S23"), u.ToMacrocell());
            Assert.Contains(
                "deepest tree",
                Assert.Throws<FormatException>(() => HashLife.FromMacrocell(Chain(HashLife.MaxLevel + 1))).Message);
        }
    }
}
