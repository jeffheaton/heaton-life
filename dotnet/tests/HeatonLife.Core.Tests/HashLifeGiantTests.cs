using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Numerics;
using Xunit;
using Xunit.Abstractions;

namespace HeatonLife.Tests
{
    /// <summary>
    /// A fact that runs only when <c>HEATON_LIFE_PATTERNS</c> names a directory holding the
    /// pattern file (python/tools/fetch_patterns.py fills it); otherwise it reports as skipped.
    /// </summary>
    public sealed class GiantFactAttribute : FactAttribute
    {
        public GiantFactAttribute(string fileName)
        {
            string? cache = Environment.GetEnvironmentVariable("HEATON_LIFE_PATTERNS");
            if (string.IsNullOrEmpty(cache))
                Skip = "HEATON_LIFE_PATTERNS is not set; run python/tools/fetch_patterns.py";
            else if (!File.Exists(Path.Combine(cache, fileName)))
                Skip = $"{fileName} is not in {cache}; run python/tools/fetch_patterns.py";
        }
    }

    /// <summary>
    /// The giant HashLife patterns (spec/hashlife.md): the Caterpillar (Nivasch, Summers and
    /// Bell, 2004) and Annelid (Brithos, 2026) land where the Macrocell placement puts them
    /// and come back to themselves, moved, after one period — the checks of
    /// python/tests/test_hashlife_giants.py.
    /// Neither file has a stated license, so neither is committed; these run only when
    /// HEATON_LIFE_PATTERNS points at the cache python/tools/fetch_patterns.py fills.
    /// </summary>
    public class HashLifeGiantTests
    {
        private const int BudgetMb = 4000; // one period fits without collecting, so a run measures the stepping

        private static readonly (long Population, CellBox Box) Caterpillar =
            (11_967_399, new CellBox(0, 0, 4194, 330_720));

        private static readonly (long Population, CellBox Box) Annelid =
            (168_807_151, new CellBox(-3_511_772, -224, 1_653_126, 16_698_877));

        private readonly ITestOutputHelper _output;

        public HashLifeGiantTests(ITestOutputHelper output) => _output = output;

        private HashLife Load(string name)
        {
            string path = Path.Combine(Environment.GetEnvironmentVariable("HEATON_LIFE_PATTERNS")!, name);
            var clock = Stopwatch.StartNew();
            HashLife u = HashLife.Load(File.ReadAllBytes(path), BudgetMb);
            _output.WriteLine($"{name}: loaded in {clock.Elapsed.TotalSeconds:F2} s, {u.NodeCount:N0} nodes");
            return u;
        }

        private void TimedStep(HashLife u, int generations)
        {
            var clock = Stopwatch.StartNew();
            u.Step(generations);
            _output.WriteLine(
                $"  {generations} generations in {clock.Elapsed.TotalSeconds:F2} s: {u.NodeCount:N0} nodes, "
                + $"{u.MemoryUsed >> 20:N0} MiB, {u.Collections} collections");
        }

        private static (long X0, long Y0, long X1, long Y1) Longs(CellBox box)
            => ((long)box.X0, (long)box.Y0, (long)box.X1, (long)box.Y1);

        /// <summary>Populations of an n × n grid of regions splitting the box (integer edges).</summary>
        private static BigInteger[,] Regions(HashLife u, CellBox box, int n)
        {
            var (x0, y0, x1, y1) = Longs(box);
            long w = x1 - x0 + 1, h = y1 - y0 + 1;
            var counts = new BigInteger[n, n];
            for (int j = 0; j < n; j++)
            {
                for (int i = 0; i < n; i++)
                {
                    counts[j, i] = u.PopulationIn(
                        x0 + i * w / n, y0 + j * h / n, x0 + (i + 1) * w / n - 1, y0 + (j + 1) * h / n - 1);
                }
            }
            return counts;
        }

        /// <summary>A live cell of the inclusive rectangle, found by halving it (it must hold one).</summary>
        private static (long X, long Y) LiveCell(HashLife u, long x0, long y0, long x1, long y1)
        {
            while (x0 != x1 || y0 != y1)
            {
                if (x1 - x0 >= y1 - y0)
                {
                    long mid = (x0 + x1) >> 1;
                    if (!u.PopulationIn(x0, y0, mid, y1).IsZero)
                        x1 = mid;
                    else
                        x0 = mid + 1;
                }
                else
                {
                    long mid = (y0 + y1) >> 1;
                    if (!u.PopulationIn(x0, y0, x1, mid).IsZero)
                        y1 = mid;
                    else
                        y0 = mid + 1;
                }
            }
            return (x0, y0);
        }

        /// <summary>The Macrocell placement of a level-20 root puts the published file's top-left cell
        /// at (0, 0): the one-row y offset of spec/hashlife.md "Tree coordinates".</summary>
        [GiantFact("caterpillar.mc")]
        public void TheCaterpillarLandsAtTheOrigin()
        {
            HashLife u = Load("caterpillar.mc");
            Assert.Equal(Caterpillar.Population, (long)u.Population);
            Assert.Equal(Caterpillar.Box, u.BoundingBox);
            Assert.True(u.Generation.IsZero);
        }

        /// <summary>17c/45: after one period every row is the row 102 below it at generation 0.</summary>
        [GiantFact("caterpillar.mc")]
        public void TheCaterpillarMoves102CellsUpEvery270Generations()
        {
            HashLife u = Load("caterpillar.mc");
            HashLifeSnapshot start = u.Snapshot();
            TimedStep(u, 270);
            var (x0, y0, x1, y1) = Longs(Caterpillar.Box);
            Assert.Equal(270, (int)u.Generation);
            Assert.Equal(Caterpillar.Population, (long)u.Population);
            Assert.Equal(new CellBox(x0, y0 - 102, x1, y1 - 102), u.BoundingBox);
            HashLifeSnapshot end = u.Snapshot();
            const int Strip = 1 << 14; // 4,195 × 16,384 cells per comparison
            for (long top = y0; top <= y1; top += Strip)
            {
                long bottom = Math.Min(top + Strip - 1, y1);
                u.Restore(start);
                byte[] before = u.GetRect(x0, top, x1, bottom);
                u.Restore(end);
                byte[] after = u.GetRect(x0, top - 102, x1, bottom - 102);
                Assert.True(before.AsSpan().SequenceEqual(after), $"rows {top}..{bottom} differ");
            }
        }

        [GiantFact("annelid.mc.gz")]
        public void AnnelidLandsOnItsMeasuredBox()
        {
            HashLife u = Load("annelid.mc.gz");
            Assert.Equal(Annelid.Population, (long)u.Population);
            Assert.Equal(Annelid.Box, u.BoundingBox);
            Assert.Equal("B3/S23", u.Rule);
        }

        /// <summary>(28,3)c/84: one period moves the ship (−9, −84). The whole 169-million-cell
        /// state is too big to compare cell for cell, so the check is a 128 × 128 grid of region
        /// populations relative to the box, plus 512 × 512 windows compared exactly around a live
        /// cell of every occupied region on the grid's diagonals.</summary>
        [GiantFact("annelid.mc.gz")]
        public void AnnelidMoves9Left84UpEvery252Generations()
        {
            HashLife u = Load("annelid.mc.gz");
            const int N = 128;
            CellBox box = Annelid.Box;
            BigInteger[,] before = Regions(u, box, N);
            var (x0, y0, x1, y1) = Longs(box);
            long w = x1 - x0 + 1, h = y1 - y0 + 1;
            var cells = new List<(long X, long Y)>();
            for (int i = 0; i < N; i++)
            {
                foreach (int j in new[] { i, N - 1 - i })
                {
                    if (before[j, i].IsZero)
                        continue;
                    cells.Add(LiveCell(
                        u, x0 + i * w / N, y0 + j * h / N, x0 + (i + 1) * w / N - 1, y0 + (j + 1) * h / N - 1));
                }
            }
            Assert.True(cells.Count >= 8);
            var windows = new List<byte[]>();
            foreach (var (x, y) in cells)
                windows.Add(u.GetRect(x - 255, y - 255, x + 256, y + 256));

            TimedStep(u, 252);
            const long Dx = -9, Dy = -84;
            Assert.Equal(252, (int)u.Generation);
            Assert.Equal(Annelid.Population, (long)u.Population);
            var moved = new CellBox(x0 + Dx, y0 + Dy, x1 + Dx, y1 + Dy);
            Assert.Equal(moved, u.BoundingBox);
            BigInteger[,] after = Regions(u, moved, N);
            for (int j = 0; j < N; j++)
                for (int i = 0; i < N; i++)
                    Assert.True(before[j, i] == after[j, i], $"region ({i}, {j}) differs");
            for (int c = 0; c < cells.Count; c++)
            {
                var (x, y) = cells[c];
                byte[] now = u.GetRect(x + Dx - 255, y + Dy - 255, x + Dx + 256, y + Dy + 256);
                Assert.True(windows[c].AsSpan().SequenceEqual(now), $"the window around ({x}, {y}) differs");
            }
        }
    }
}
