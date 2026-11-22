using System;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// A byte-grid family that <see cref="GridRegion.Advance"/> advances: its current cells, its
    /// generation, and one generation of its own rule and boundary that polls a token as it goes
    /// (each row, say) and throws <see cref="GridRegion.Canceled"/>'s exception when it is canceled.
    /// </summary>
    internal interface IRegionWorld
    {
        /// <summary>The cells, row-major; a family may swap buffers each generation.</summary>
        byte[] Cells { get; }

        int Generation { get; }

        void StepOnce(CancellationToken cancellationToken);
    }

    /// <summary>
    /// Advance Selection and Advance Outside for the byte-grid families whose blank is 0:
    /// life-like, wireworld, cyclic, and generations (spec/patterns.md "Editing a region"). A
    /// family blanks a copy with <see cref="Isolate"/>, runs its own generations on it under its
    /// own rule and boundary, and takes back what did not advance with <see cref="Merge"/>;
    /// <see cref="Advance"/> does all three and can be canceled. The Python reference's
    /// heaton_life.ca._advance.AdvanceRegion.
    /// </summary>
    internal static class GridRegion
    {
        /// <summary>
        /// Advance Selection (<paramref name="outside"/> false) or Advance Outside on a world's
        /// own cells: isolate, run <paramref name="n"/> generations, merge. A canceled token
        /// stops it between generations, or within one where the world's step polls it, with
        /// <see cref="OperationCanceledException"/> (spec/patterns.md "Canceling"); then, as after
        /// any exception, the world's cells are put back exactly as they were. The generation is
        /// never changed, and n = 0 runs nothing and checks no token, as HashLife's step does.
        /// </summary>
        internal static void Advance(
            IRegionWorld world, int width, int height, int x0, int y0, int x1, int y1, int n, bool outside,
            CancellationToken cancellationToken)
        {
            byte[] saved = Isolate(world.Cells, width, height, x0, y0, x1, y1, n, outside);
            try
            {
                for (int s = 0; s < n; s++)
                {
                    if (cancellationToken.IsCancellationRequested)
                        throw Canceled(cancellationToken, world.Generation);
                    world.StepOnce(cancellationToken);
                }
            }
            catch
            {
                saved.CopyTo(world.Cells, 0); // the world as it was: no partial result
                throw;
            }
            Merge(world.Cells, saved, width, height, x0, y0, x1, y1, outside);
        }

        /// <summary>What a canceled advance throws: what a canceled HashLife step throws.</summary>
        internal static OperationCanceledException Canceled(CancellationToken cancellationToken, int generation)
            => new OperationCanceledException(
                $"canceled; the world is at generation {generation}", cancellationToken);

        /// <summary>
        /// Check the region and the count, save the cells, and blank in place everything outside
        /// the region (Advance Selection) or the region itself (Advance Outside). Returns the
        /// saved cells; nothing has changed when it throws.
        /// </summary>
        internal static byte[] Isolate(
            byte[] cells, int width, int height, int x0, int y0, int x1, int y1, int n, bool outside)
        {
            Patterns.CheckRegion(width, height, x0, y0, x1, y1);
            if (n < 0)
                throw new ArgumentOutOfRangeException(nameof(n), n, "cannot advance backward");
            var saved = (byte[])cells.Clone();
            for (int y = 0; y < height; y++)
            {
                bool rowInside = y >= y0 && y <= y1;
                for (int x = 0; x < width; x++)
                {
                    bool inside = rowInside && x >= x0 && x <= x1;
                    if (inside == outside)
                        cells[y * width + x] = 0;
                }
            }
            return saved;
        }

        /// <summary>
        /// After the generations, keep the part that advanced — the region, or for Advance
        /// Outside everything else — and put the saved cells back everywhere else.
        /// </summary>
        internal static void Merge(
            byte[] cells, byte[] saved, int width, int height, int x0, int y0, int x1, int y1, bool outside)
        {
            for (int y = 0; y < height; y++)
            {
                bool rowInside = y >= y0 && y <= y1;
                for (int x = 0; x < width; x++)
                {
                    bool inside = rowInside && x >= x0 && x <= x1;
                    if (inside == outside)
                        cells[y * width + x] = saved[y * width + x];
                }
            }
        }
    }
}
