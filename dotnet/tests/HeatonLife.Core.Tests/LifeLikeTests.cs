using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class LifeLikeTests
    {
        /// <summary>
        /// spec/lifelike.md "Initialization": single = one live cell at
        /// (width // 2, height // 2), consuming no draws. The family's third init
        /// strategy; it was missing from this port until 2026-08-21 because no
        /// vector exercised it (vectors/lifelike/replicator-single-64 now does).
        /// </summary>
        [Fact]
        public void SeedSingleLightsExactlyTheMiddleCell()
        {
            var sim = new LifeLike("B3/S23", 9, 7);
            sim.SeedSingle();
            byte[] state = sim.State.ToArray();
            int live = 0;
            foreach (byte cell in state)
                live += cell;
            Assert.Equal(1, live);
            Assert.Equal(1, state[(7 / 2) * 9 + (9 / 2)]);
            Assert.Equal(0, sim.Generation);
        }

        /// <summary>
        /// It consumes NO RNG draws, so it cannot depend on a seed — the property
        /// that makes it reproducible without one.
        /// </summary>
        [Fact]
        public void SeedSingleIsIndependentOfAnyPriorRngUse()
        {
            var fresh = new LifeLike("B3/S23", 16, 16);
            fresh.SeedSingle();

            var churned = new LifeLike("B3/S23", 16, 16);
            churned.SeedSoup(0.5, 12345);   // burn a whole grid's worth of draws
            churned.SeedSingle();

            Assert.Equal(fresh.State.ToArray(), churned.State.ToArray());
        }

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

        // -- every rule runs through its table (spec/lifelike.md, spec/rules.md) --------------

        private static string NoiseMap(ulong seed)
        {
            const string Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
            var rng = new Pcg32(seed);
            var bits = new int[516];
            for (int i = 0; i < 512; i++)
                bits[i] = (int)(rng.NextU32() >> 31);
            var sb = new System.Text.StringBuilder("MAP");
            for (int i = 0; i < 516; i += 6)
                sb.Append(Alphabet[(bits[i] << 5) | (bits[i + 1] << 4) | (bits[i + 2] << 3)
                    | (bits[i + 3] << 2) | (bits[i + 4] << 1) | bits[i + 5]]);
            return sb.ToString();
        }

        /// <summary>Against a direct evaluation of an arbitrary table: a mirrored or rotated
        /// weight order would pass an isotropic rule but not this one.</summary>
        [Theory]
        [InlineData(Boundary.Torus)]
        [InlineData(Boundary.Dead)]
        public void EachCellTakesTheTableEntryAtItsIndex(Boundary boundary)
        {
            string rule = NoiseMap(11);
            ReadOnlySpan<byte> table = RuleString.Compile(rule).Table;
            const int W = 13, H = 9;
            var sim = new LifeLike(rule, W, H, boundary);
            sim.SeedSoup(0.5, 3);
            byte[] state = sim.State.ToArray();
            sim.Step();
            int[,] weight = { { 256, 128, 64 }, { 32, 16, 8 }, { 4, 2, 1 } };
            for (int y = 0; y < H; y++)
            {
                for (int x = 0; x < W; x++)
                {
                    int index = 0;
                    for (int dy = -1; dy <= 1; dy++)
                    {
                        for (int dx = -1; dx <= 1; dx++)
                        {
                            int yy = y + dy, xx = x + dx;
                            if (boundary == Boundary.Torus)
                            {
                                yy = (yy + H) % H;
                                xx = (xx + W) % W;
                            }
                            else if (yy < 0 || yy >= H || xx < 0 || xx >= W)
                            {
                                continue;
                            }
                            index += weight[dy + 1, dx + 1] * state[yy * W + xx];
                        }
                    }
                    Assert.Equal(table[index], sim.State[y * W + x]);
                }
            }
        }

        [Fact]
        public void RulesAreCarriedCanonicalInAnyNotation()
        {
            Assert.Equal("B2-a/S12", new LifeLike("b2cekin/s12", 8, 8).Rule);
            Assert.Equal("B2/S34H", new LifeLike("b2/s34h", 8, 8).Rule);
            Assert.Equal(NoiseMap(2), new LifeLike(NoiseMap(2) + "==", 8, 8).Rule);
        }

        /// <summary>B0 on a torus: every dead cell without live neighbors is born at once.</summary>
        [Fact]
        public void B0RulesRunAsWritten()
        {
            var sim = new LifeLike("B0/S", 8, 8);
            sim.SetState(new byte[64]);
            sim.Step();
            Assert.All(sim.State.ToArray(), c => Assert.Equal(1, c));
            sim.Step(); // B0/S has no survival: everything dies
            Assert.All(sim.State.ToArray(), c => Assert.Equal(0, c));
        }
    }
}
