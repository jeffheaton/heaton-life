using System;

namespace HeatonLife
{
    /// <summary>
    /// Advance Selection and Advance Outside for the byte-grid families whose blank is 0:
    /// life-like, wireworld, and cyclic (spec/patterns.md "Editing a region"). A family blanks a
    /// copy with <see cref="Isolate"/>, runs its own generations on it under its own rule and
    /// boundary, and takes back what did not advance with <see cref="Merge"/>. The Python
    /// reference's heaton_life.ca._advance.AdvanceRegion.
    /// </summary>
    internal static class GridRegion
    {
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
