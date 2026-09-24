namespace HeatonLife
{
    /// <summary>
    /// Presentation noise (spec/rng.md "Presentation noise"): Chris Wellons' triple32 hash,
    /// as Heaton Fractal uses it. Not simulation randomness — no state and no draw order,
    /// so rows can be colored in any order or in parallel with the same result. The
    /// Python reference's heaton_life.render.dither.
    /// </summary>
    public static class Dither
    {
        /// <summary>The hash on one 32-bit value (all arithmetic mod 2^32).</summary>
        public static uint Triple32(uint x)
        {
            unchecked
            {
                x ^= x >> 17;
                x *= 0xED5AD4BBu;
                x ^= x >> 11;
                x *= 0xAC4C1B51u;
                x ^= x >> 15;
                x *= 0x31848BABu;
                x ^= x >> 14;
                return x;
            }
        }

        /// <summary>
        /// D = triple32(seed) - triple32(seed ^ 0x68BC21EB) for the pixel at column
        /// <paramref name="x"/>, row <paramref name="y"/>: an exact integer in (-2^32, 2^32),
        /// so D * 2^-32 is triangular on (-1, 1). <paramref name="frameIndex"/> is 0 for
        /// stills and interactive views; <paramref name="channel"/> is 0..2.
        /// </summary>
        public static long Tpdf(int x, int y, uint frameIndex, int channel)
        {
            if (x < 0 || y < 0 || channel < 0 || channel > 2)
                throw new System.ArgumentException("x, y must be non-negative and channel in 0..2");
            uint seed = unchecked(
                (uint)x * 0x9E3779B9u ^ (uint)y * 0x85EBCA6Bu ^ frameIndex * 0xC2B2AE35u ^ (uint)channel * 0x27D4EB2Fu);
            return (long)Triple32(seed) - Triple32(seed ^ 0x68BC21EBu);
        }
    }
}
