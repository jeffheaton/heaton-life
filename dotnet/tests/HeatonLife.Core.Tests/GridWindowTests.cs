using System;
using System.Collections.Generic;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Sampling a window of a grid (spec/render.md "Sampling a window of a grid"): what each
    /// pixel covers, its nearest cell, and the three modes, against a direct reading of the spec.
    /// </summary>
    public class GridWindowTests
    {
        private static (int Start, int End) Covered(int start, int cells, int outs, int i)
        {
            long first = (2L * i * cells + outs - 1) / (2L * outs);
            long end = (2L * (i + 1) * cells + outs - 1) / (2L * outs);
            return (start + (int)first, start + (int)end);
        }

        private static byte[] Reference(
            byte[] grid, int gridWidth, int x0, int y0, int width, int height,
            int outWidth, int outHeight, GridWindowMode mode, byte[] order)
        {
            var ranking = new List<int>();
            foreach (byte v in order)
                ranking.Add(v);
            for (int v = 1; v < 256; v++)
                if (Array.IndexOf(order, (byte)v) < 0)
                    ranking.Add(v);
            var output = new byte[outWidth * outHeight];
            for (int j = 0; j < outHeight; j++)
            {
                var rows = Covered(y0, height, outHeight, j);
                for (int i = 0; i < outWidth; i++)
                {
                    var columns = Covered(x0, width, outWidth, i);
                    var values = new List<byte>();
                    for (int r = rows.Start; r < rows.End; r++)
                        for (int c = columns.Start; c < columns.End; c++)
                            values.Add(grid[r * gridWidth + c]);
                    byte value;
                    if (mode == GridWindowMode.Nearest)
                    {
                        int r = y0 + (2 * j + 1) * height / (2 * outHeight);
                        int c = x0 + (2 * i + 1) * width / (2 * outWidth);
                        Assert.InRange(r, rows.Start, rows.End - 1);
                        Assert.InRange(c, columns.Start, columns.End - 1);
                        value = grid[r * gridWidth + c];
                    }
                    else if (mode == GridWindowMode.State)
                    {
                        value = 0;
                        foreach (int v in ranking)
                        {
                            if (values.Contains((byte)v))
                            {
                                value = (byte)v;
                                break;
                            }
                        }
                    }
                    else
                    {
                        int live = 0;
                        foreach (byte v in values)
                            if (v != 0)
                                live++;
                        value = (byte)((255 * live + values.Count - 1) / values.Count);
                    }
                    output[j * outWidth + i] = value;
                }
            }
            return output;
        }

        [Fact]
        public void ThePixelsShareOutTheWindow()
        {
            for (int cells = 1; cells < 40; cells++)
            {
                for (int outs = 1; outs <= cells; outs++)
                {
                    int next = 0;
                    for (int i = 0; i < outs; i++)
                    {
                        var (start, end) = Covered(0, cells, outs, i);
                        Assert.Equal(next, start);
                        Assert.True(end > start);
                        for (int c = start; c < end; c++) // the cells whose centers lie in the share
                            Assert.True(2L * i * cells <= (2L * c + 1) * outs && (2L * c + 1) * outs < 2L * (i + 1) * cells);
                        next = end;
                    }
                    Assert.Equal(cells, next);
                }
            }
        }

        [Fact]
        public void EveryModeMatchesTheSpecReadDirectly()
        {
            var rng = new Random(12);
            byte[] palette = { 0, 0, 0, 1, 2, 3, 6, 200, 255 };
            for (int trial = 0; trial < 60; trial++)
            {
                int gridWidth = rng.Next(1, 40), gridHeight = rng.Next(1, 40);
                var grid = new byte[gridWidth * gridHeight];
                for (int k = 0; k < grid.Length; k++)
                    grid[k] = palette[rng.Next(palette.Length)];
                for (int window = 0; window < 6; window++)
                {
                    int width = rng.Next(1, gridWidth + 1), height = rng.Next(1, gridHeight + 1);
                    int x0 = rng.Next(0, gridWidth - width + 1), y0 = rng.Next(0, gridHeight - height + 1);
                    int outWidth = rng.Next(1, width + 1), outHeight = rng.Next(1, height + 1);
                    var choices = new List<byte> { 1, 2, 3, 6, 200, 255 };
                    var order = new List<byte>();
                    for (int k = rng.Next(0, 4); k > 0; k--)
                    {
                        int pick = rng.Next(choices.Count);
                        order.Add(choices[pick]);
                        choices.RemoveAt(pick);
                    }
                    foreach (GridWindowMode mode in new[] { GridWindowMode.Nearest, GridWindowMode.State, GridWindowMode.Density })
                    {
                        var output = new byte[outWidth * outHeight];
                        GridWindow.Sample(grid, gridWidth, gridHeight, x0, y0, width, height, output, outWidth, outHeight, mode, order.ToArray());
                        Assert.Equal(
                            Reference(grid, gridWidth, x0, y0, width, height, outWidth, outHeight, mode, order.ToArray()),
                            output);
                    }
                }
            }
        }

        [Fact]
        public void ALoneLiveCellNeverVanishes()
        {
            int misses = 0;
            for (int y = 0; y < 61; y += 7)
            {
                for (int x = 0; x < 97; x += 5)
                {
                    var grid = new byte[97 * 61];
                    grid[y * 97 + x] = 1;
                    foreach (var (w, h) in new[] { (13, 7), (40, 30), (1, 1), (96, 60) })
                    {
                        var output = new byte[w * h];
                        GridWindow.Sample(grid, 97, 61, 0, 0, 97, 61, output, w, h);
                        Assert.Equal(1, Count(output));
                        GridWindow.Sample(grid, 97, 61, 0, 0, 97, 61, output, w, h, GridWindowMode.Density);
                        Assert.Equal(1, Count(output));
                        GridWindow.Sample(grid, 97, 61, 0, 0, 97, 61, output, w, h, GridWindowMode.Nearest);
                        if (Count(output) == 0)
                            misses++;
                    }
                }
            }
            Assert.True(misses > 0, "nearest sampling does lose lone cells, which is the point");
        }

        [Fact]
        public void AsManyPixelsAsCellsIsTheWindowItself()
        {
            var rng = new Random(5);
            var grid = new byte[41 * 30];
            rng.NextBytes(grid);
            var output = new byte[33 * 20];
            foreach (GridWindowMode mode in new[] { GridWindowMode.Nearest, GridWindowMode.State, GridWindowMode.Density })
            {
                GridWindow.Sample(grid, 41, 30, 7, 4, 33, 20, output, 33, 20, mode);
                for (int r = 0; r < 20; r++)
                {
                    for (int c = 0; c < 33; c++)
                    {
                        byte cell = grid[(4 + r) * 41 + 7 + c];
                        byte expected = mode == GridWindowMode.Density ? (byte)(cell != 0 ? 255 : 0) : cell;
                        Assert.Equal(expected, output[r * 33 + c]);
                    }
                }
            }
        }

        [Fact]
        public void TheZoomOrderPicksAmongTheStatesAPixelCovers()
        {
            byte[] grid = { 2, 1, 0, 0, 0, 5, 4, 0, 3, 0, 0, 6 };
            var one = new byte[1];
            GridWindow.Sample(grid, 4, 3, 0, 0, 4, 3, one, 1, 1);
            Assert.Equal(1, one[0]);
            GridWindow.Sample(grid, 4, 3, 0, 0, 4, 3, one, 1, 1, GridWindowMode.State, new byte[] { 6 });
            Assert.Equal(6, one[0]);
            byte[] order = StatePalettes.DefaultZoomOrder(new LifeLike("B3/S23History", 8, 8));
            GridWindow.Sample(grid, 4, 3, 0, 0, 4, 3, one, 1, 1, GridWindowMode.State, order);
            Assert.Equal(3, one[0]);
            byte[] marked = { 2, 2, 5, 2, 2, 2, 4, 2, 2 };
            GridWindow.Sample(marked, 3, 3, 0, 0, 3, 3, one, 1, 1);
            Assert.Equal(2, one[0]); // lowest first hides the marks behind the envelope
            GridWindow.Sample(marked, 3, 3, 0, 0, 3, 3, one, 1, 1, GridWindowMode.State, order);
            Assert.Equal(5, one[0]);
            var blank = new byte[25];
            var four = new byte[4];
            GridWindow.Sample(blank, 5, 5, 0, 0, 5, 5, four, 2, 2);
            Assert.Equal(new byte[4], four);
        }

        [Fact]
        public void DensityCountsTheNonZeroCellsRoundingUp()
        {
            var grid = new byte[12];
            grid[0] = 9;
            var one = new byte[1];
            GridWindow.Sample(grid, 4, 3, 0, 0, 4, 3, one, 1, 1, GridWindowMode.Density);
            Assert.Equal(22, one[0]); // ⌈255/12⌉
            Array.Fill(grid, (byte)7);
            GridWindow.Sample(grid, 4, 3, 0, 0, 4, 3, one, 1, 1, GridWindowMode.Density);
            Assert.Equal(255, one[0]);
        }

        [Fact]
        public void SamplingAllocatesNothing()
        {
            var rng = new Random(9);
            var grid = new byte[300 * 200];
            rng.NextBytes(grid);
            var output = new byte[70 * 41];
            byte[] order = { 3, 5, 1 };
            var modes = new[] { GridWindowMode.Nearest, GridWindowMode.State, GridWindowMode.Density };
            foreach (GridWindowMode mode in modes)
                GridWindow.Sample(grid, 300, 200, 10, 7, 280, 190, output, 70, 41, mode, order); // warm up
            long before = GC.GetAllocatedBytesForCurrentThread();
            foreach (GridWindowMode mode in modes)
                GridWindow.Sample(grid, 300, 200, 10, 7, 280, 190, output, 70, 41, mode, order);
            Assert.Equal(before, GC.GetAllocatedBytesForCurrentThread());
        }

        [Theory]
        [InlineData(-1, 0, 4, 4, 2, 2)]
        [InlineData(0, 0, 11, 4, 2, 2)]
        [InlineData(0, 7, 4, 4, 2, 2)]
        [InlineData(0, 0, 0, 4, 1, 1)]
        [InlineData(0, 0, 4, 4, 5, 2)]
        [InlineData(0, 0, 4, 4, 2, 0)]
        [InlineData(8, 0, 3, 4, 2, 2)]
        public void AWindowInsideTheGridAndSizesInRange(int x0, int y0, int width, int height, int outWidth, int outHeight)
        {
            var output = new byte[Math.Max(outWidth * outHeight, 0)];
            Assert.Throws<ArgumentOutOfRangeException>(
                () => GridWindow.Sample(new byte[100], 10, 10, x0, y0, width, height, output, outWidth, outHeight));
        }

        [Fact]
        public void BadOrdersBuffersAndGridsAreRefusedWritingNothing()
        {
            var grid = new byte[16];
            grid[5] = 1;
            var output = new byte[4];
            output[0] = 77;
            foreach (byte[] order in new[] { new byte[] { 0 }, new byte[] { 3, 3 }, new byte[] { 1, 2, 1 } })
                Assert.Throws<ArgumentException>(
                    () => GridWindow.Sample(grid, 4, 4, 0, 0, 4, 4, output, 2, 2, GridWindowMode.State, order));
            Assert.Equal(77, output[0]);
            Assert.Throws<ArgumentException>(() => GridWindow.Sample(grid, 4, 4, 0, 0, 4, 4, new byte[5], 2, 2));
            Assert.Throws<ArgumentException>(() => GridWindow.Sample(grid, 5, 4, 0, 0, 4, 4, output, 2, 2));
            Assert.Throws<ArgumentOutOfRangeException>(
                () => GridWindow.Sample(grid, 4, 4, 0, 0, 4, 4, output, 2, 2, (GridWindowMode)7));
        }

        private static int Count(byte[] values)
        {
            int count = 0;
            foreach (byte v in values)
                if (v != 0)
                    count++;
            return count;
        }
    }
}
