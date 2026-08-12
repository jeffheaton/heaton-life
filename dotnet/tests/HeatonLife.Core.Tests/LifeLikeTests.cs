using Xunit;

namespace HeatonLife.Tests
{
    public class LifeLikeTests
    {
        [Fact]
        public void BlinkerOscillates()
        {
            var sim = new LifeLike("B3/S23", 5, 5, Boundary.Dead);
            var grid = new byte[25];
            grid[2 * 5 + 1] = grid[2 * 5 + 2] = grid[2 * 5 + 3] = 1;
            sim.SetState(grid);
            sim.Step();
            var vertical = new byte[25];
            vertical[1 * 5 + 2] = vertical[2 * 5 + 2] = vertical[3 * 5 + 2] = 1;
            Assert.Equal(vertical, sim.State.ToArray());
            sim.Step();
            Assert.Equal(grid, sim.State.ToArray());
        }

        [Fact]
        public void GliderReturnsHomeOnTorus()
        {
            // bob$2bo$3o at the top-left corner of a 16x16 torus laps home in 64 steps.
            var sim = new LifeLike("B3/S23", 16, 16);
            var grid = new byte[256];
            grid[0 * 16 + 1] = 1;
            grid[1 * 16 + 2] = 1;
            grid[2 * 16 + 0] = grid[2 * 16 + 1] = grid[2 * 16 + 2] = 1;
            sim.SetState(grid);
            var initial = sim.State.ToArray();
            sim.Step(64);
            Assert.Equal(initial, sim.State.ToArray());
        }

        [Fact]
        public void SoupMatchesSpecDrawOrder()
        {
            var sim = new LifeLike("B3/S23", 8, 4);
            sim.SeedSoup(0.35, 42);
            // First draws of Pcg32(42, 0), alive iff draw < floor(0.35 * 2^32).
            var rng = new Pcg32(42);
            ulong threshold = (ulong)(0.35 * 4294967296.0);
            for (int i = 0; i < 32; i++)
                Assert.Equal(rng.NextU32() < threshold ? 1 : 0, sim.State[i]);
        }

        [Fact]
        public void ClearRectBlanksTheRectangleOnly()
        {
            var sim = new LifeLike("B3/S23", 8, 8);
            var grid = new byte[64];
            for (int i = 0; i < 64; i++)
                grid[i] = 1;
            sim.SetState(grid, 7);
            sim.ClearRect(1, 1, 3, 2);
            for (int y = 0; y < 8; y++)
                for (int x = 0; x < 8; x++)
                {
                    byte expected = (byte)(x >= 1 && x <= 3 && y >= 1 && y <= 2 ? 0 : 1);
                    Assert.Equal(expected, sim.State[y * 8 + x]);
                }
            Assert.Equal(7, sim.Generation); // clearing preserves the generation
        }
    }
}
