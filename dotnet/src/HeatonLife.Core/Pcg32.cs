namespace HeatonLife
{
    /// <summary>
    /// PCG32 (XSH-RR) — the spec-pinned RNG (spec/rng.md). Matches pcg_basic and the
    /// Python implementation exactly; simulation state must only be seeded through this.
    /// </summary>
    public sealed class Pcg32
    {
        private const ulong Mult = 6364136223846793005UL;

        private ulong _state;
        private readonly ulong _inc;

        public Pcg32(ulong seed, ulong seq = 0)
        {
            _state = 0;
            _inc = (seq << 1) | 1UL;
            NextU32();
            _state += seed;
            NextU32();
        }

        public uint NextU32()
        {
            ulong old = _state;
            _state = unchecked(old * Mult + _inc);
            uint xorshifted = (uint)(((old >> 18) ^ old) >> 27);
            int rot = (int)(old >> 59);
            return (xorshifted >> rot) | (xorshifted << ((32 - rot) & 31));
        }
    }
}
