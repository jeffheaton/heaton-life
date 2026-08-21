using System;

namespace HeatonLife
{
    /// <summary>
    /// Seeded initial states (spec: init/seeding). Every strategy consumes its draws
    /// from PCG32 in row-major order regardless of masks, so implementations in any
    /// language agree bit-for-bit.
    /// </summary>
    public static class Seeding
    {
        /// <summary>
        /// Density is a probability. The Python reference rejects anything outside
        /// [0, 1] (init/seeding.py `_threshold`); C# used to cast it straight to a
        /// threshold, where 1.5 silently filled every cell and a NEGATIVE density
        /// became an unchecked double-to-ulong conversion — a degenerate grid
        /// instead of an error.
        /// </summary>
        private static ulong Threshold(double density)
        {
            if (!(density >= 0.0) || density > 1.0)
                throw new ArgumentOutOfRangeException(
                    nameof(density), density, "density must be in [0, 1]");
            return (ulong)(density * 4294967296.0);
        }

        /// <summary>
        /// Uniform random 0/1 fill: alive iff draw &lt; floor(density * 2^32).
        /// Consumes exactly one draw per cell.
        /// </summary>
        public static void Soup(byte[] cells, double density, uint seed)
        {
            var rng = new Pcg32(seed);
            ulong threshold = Threshold(density);
            for (int i = 0; i < cells.Length; i++)
                cells[i] = (byte)(rng.NextU32() < threshold ? 1 : 0);
        }

        /// <summary>
        /// One live cell at (width / 2, height / 2), everything else blank.
        /// Consumes NO draws — the deterministic seed, so it takes no RNG at all
        /// (spec/lifelike.md "Initialization").
        /// </summary>
        public static void Single(byte[] cells, int width, int height)
        {
            Array.Clear(cells, 0, cells.Length);
            cells[(height / 2) * width + (width / 2)] = 1;
        }

        /// <summary>
        /// Soup restricted to a centered disk; radius is a fraction of min(width, height).
        /// Consumes one draw per cell regardless of the mask, like the reference.
        /// </summary>
        public static void Blob(
            byte[] cells, int width, int height, double density, double radius, uint seed)
        {
            var rng = new Pcg32(seed);
            ulong threshold = Threshold(density);
            double r = radius * Math.Min(width, height);
            double r2 = r * r;
            int cx = width / 2, cy = height / 2;
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    bool alive = rng.NextU32() < threshold;
                    double dx = x - cx, dy = y - cy;
                    cells[y * width + x] = (byte)(alive && dx * dx + dy * dy <= r2 ? 1 : 0);
                }
        }
    }
}
