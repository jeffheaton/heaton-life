using System;

namespace HeatonLife
{
    /// <summary>What a pixel of a sampled window holds (spec/render.md "Sampling a window of a grid").</summary>
    public enum GridWindowMode
    {
        /// <summary>The value of the cell under the pixel's center.</summary>
        Nearest = 0,

        /// <summary>
        /// Of the non-zero values among the pixel's cells, the first in the zoom order, or 0: in
        /// a two-state grid a pixel is live when any of its cells is.
        /// </summary>
        State = 1,

        /// <summary>⌈255 · p / n⌉ for a pixel that covers n cells, p of them not 0.</summary>
        Density = 2,
    }

    /// <summary>
    /// Sampling a window of a grid (spec/render.md "Sampling a window of a grid"): a grid world
    /// too big to show whole is shown a window at a time, with fewer pixels than cells. A pixel
    /// covers the cells whose centers lie in its share of the window, and its nearest cell, the
    /// one under its center, is always among them. The output is bytes, states or densities,
    /// to color with a <see cref="StatePalettes"/> palette or its shade. Allocates nothing.
    /// </summary>
    public static class GridWindow
    {
        /// <summary>
        /// Sample the window of <paramref name="width"/> × <paramref name="height"/> cells whose
        /// top-left cell is (<paramref name="x0"/>, <paramref name="y0"/>) of a row-major grid
        /// of bytes (a world's states, or a frame) into <paramref name="output"/>,
        /// <paramref name="outWidth"/> × <paramref name="outHeight"/> bytes row-major. The window
        /// lies inside the grid, with 1 ≤ outWidth ≤ width and 1 ≤ outHeight ≤ height.
        /// <paramref name="zoomOrder"/> lists distinct values from 1 to 255, shown first in its
        /// order, every other value after them in increasing order (empty: the lowest first);
        /// <see cref="GridWindowMode.State"/> uses it. Errors write nothing.
        /// </summary>
        public static void Sample(
            ReadOnlySpan<byte> cells,
            int gridWidth,
            int gridHeight,
            int x0,
            int y0,
            int width,
            int height,
            Span<byte> output,
            int outWidth,
            int outHeight,
            GridWindowMode mode = GridWindowMode.State,
            ReadOnlySpan<byte> zoomOrder = default)
        {
            if (gridWidth < 1 || gridHeight < 1 || (long)gridWidth * gridHeight != cells.Length)
                throw new ArgumentException(
                    $"a {gridWidth}x{gridHeight} grid is {(long)gridWidth * gridHeight} cells, got {cells.Length}",
                    nameof(cells));
            if (x0 < 0 || y0 < 0 || width < 1 || height < 1
                || (long)x0 + width > gridWidth || (long)y0 + height > gridHeight)
                throw new ArgumentOutOfRangeException(
                    nameof(width),
                    $"the window {width}x{height} at ({x0}, {y0}) leaves the {gridWidth}x{gridHeight} grid");
            if (outWidth < 1 || outWidth > width || outHeight < 1 || outHeight > height)
                throw new ArgumentOutOfRangeException(
                    nameof(outWidth),
                    $"a {width}x{height} window samples to 1x1 up to {width}x{height} pixels, not {outWidth}x{outHeight}");
            if (output.Length != (long)outWidth * outHeight)
                throw new ArgumentException(
                    $"expected {(long)outWidth * outHeight} output bytes, got {output.Length}", nameof(output));
            if (mode != GridWindowMode.Nearest && mode != GridWindowMode.State && mode != GridWindowMode.Density)
                throw new ArgumentOutOfRangeException(nameof(mode), $"unknown window mode {mode}");

            Span<byte> ranks = stackalloc byte[256];
            Span<byte> byRank = stackalloc byte[256];
            Ranks(zoomOrder, ranks, byRank);

            long w = width, h = height, ow = outWidth, oh = outHeight;
            int at = 0;
            for (int j = 0; j < outHeight; j++)
            {
                long rowStart = (2L * j * h + oh - 1) / (2 * oh);
                long rowEnd = (2L * (j + 1) * h + oh - 1) / (2 * oh);
                long nearestRow = y0 + (2L * j + 1) * h / (2 * oh);
                for (int i = 0; i < outWidth; i++)
                {
                    long columnStart = (2L * i * w + ow - 1) / (2 * ow);
                    long columnEnd = (2L * (i + 1) * w + ow - 1) / (2 * ow);
                    switch (mode)
                    {
                        case GridWindowMode.Nearest:
                            {
                                long column = x0 + (2L * i + 1) * w / (2 * ow);
                                output[at++] = cells[(int)(nearestRow * gridWidth + column)];
                                break;
                            }
                        case GridWindowMode.State:
                            {
                                int best = 255;
                                for (long r = rowStart; r < rowEnd && best != 0; r++)
                                {
                                    ReadOnlySpan<byte> row = cells.Slice(
                                        (int)((y0 + r) * gridWidth + x0 + columnStart),
                                        (int)(columnEnd - columnStart));
                                    for (int c = 0; c < row.Length; c++)
                                    {
                                        int rank = ranks[row[c]];
                                        if (rank < best)
                                        {
                                            best = rank;
                                            if (best == 0)
                                                break;
                                        }
                                    }
                                }
                                output[at++] = byRank[best];
                                break;
                            }
                        default:
                            {
                                long live = 0;
                                for (long r = rowStart; r < rowEnd; r++)
                                {
                                    ReadOnlySpan<byte> row = cells.Slice(
                                        (int)((y0 + r) * gridWidth + x0 + columnStart),
                                        (int)(columnEnd - columnStart));
                                    for (int c = 0; c < row.Length; c++)
                                    {
                                        if (row[c] != 0)
                                            live++;
                                    }
                                }
                                long n = (rowEnd - rowStart) * (columnEnd - columnStart);
                                output[at++] = (byte)((255 * live + n - 1) / n);
                                break;
                            }
                    }
                }
            }
        }

        /// <summary>
        /// Each value's place in a zoom order, lower shown first (0 last of all, at 255), and
        /// the value at each place. Throws for a list that is no zoom order.
        /// </summary>
        private static void Ranks(ReadOnlySpan<byte> order, Span<byte> ranks, Span<byte> byRank)
        {
            ranks.Fill(255);
            int place = 0;
            foreach (byte value in order)
            {
                if (value == 0 || ranks[value] != 255)
                    throw new ArgumentException(
                        "a zoom order lists distinct states from 1 to 255", "zoomOrder");
                ranks[value] = (byte)place++;
            }
            for (int value = 1; value < 256; value++)
            {
                if (ranks[value] == 255)
                    ranks[value] = (byte)place++;
            }
            ranks[0] = 255;
            for (int value = 1; value < 256; value++)
                byRank[ranks[value]] = (byte)value;
            byRank[255] = 0;
        }
    }
}
