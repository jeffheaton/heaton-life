using Xunit;

namespace HeatonLife.Tests
{
    public class Pcg32Tests
    {
        [Fact]
        public void KnownAnswer_Seed42_Seq54()
        {
            // spec/rng.md: the pcg_basic reference outputs, pinned across languages.
            var rng = new Pcg32(42, 54);
            uint[] expected =
            {
                0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B, 0xCBED606E,
            };
            foreach (uint value in expected)
                Assert.Equal(value, rng.NextU32());
        }

        [Fact]
        public void SeedAndSequenceMatter()
        {
            Assert.NotEqual(new Pcg32(1).NextU32(), new Pcg32(2).NextU32());
            Assert.NotEqual(new Pcg32(1, 0).NextU32(), new Pcg32(1, 1).NextU32());
        }
    }
}
