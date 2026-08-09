using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class WireworldTests
    {
        [Fact]
        public void ParseTextReadsAllStates()
        {
            var (width, height, cells) = Wireworld.ParseText(".#H\nT..");
            Assert.Equal(3, width);
            Assert.Equal(2, height);
            Assert.Equal(
                new byte[]
                {
                    Wireworld.Empty, Wireworld.Conductor, Wireworld.Head,
                    Wireworld.Tail, Wireworld.Empty, Wireworld.Empty,
                },
                cells);
        }

        [Fact]
        public void ElectronMovesAlongWire()
        {
            // head at x=2 fires the conductor at x=3; head decays to tail.
            var grid = new byte[24];
            grid[1 * 8 + 1] = Wireworld.Tail;
            grid[1 * 8 + 2] = Wireworld.Head;
            grid[1 * 8 + 3] = Wireworld.Conductor;
            grid[1 * 8 + 4] = Wireworld.Conductor;
            var sim = new Wireworld(8, 3, grid); // array ctor: too small for a clock
            sim.Step();
            Assert.Equal(Wireworld.Conductor, sim.State[1 * 8 + 1]); // tail -> conductor
            Assert.Equal(Wireworld.Tail, sim.State[1 * 8 + 2]); // head -> tail
            Assert.Equal(Wireworld.Head, sim.State[1 * 8 + 3]); // conductor next to one head -> head
            Assert.Equal(Wireworld.Conductor, sim.State[1 * 8 + 4]); // too far: stays conductor
        }

        [Fact]
        public void ConductorWithThreeHeadsDoesNotFire()
        {
            var grid = new byte[30];
            grid[1 * 6 + 1] = Wireworld.Head;
            grid[2 * 6 + 1] = Wireworld.Head;
            grid[3 * 6 + 1] = Wireworld.Head;
            grid[2 * 6 + 2] = Wireworld.Conductor;
            var sim = new Wireworld(6, 5, grid);
            sim.Step();
            Assert.Equal(Wireworld.Conductor, sim.State[2 * 6 + 2]); // 3 head neighbors: no fire
        }

        [Fact]
        public void EmptyStaysEmpty()
        {
            var sim = new Wireworld(8, 8, new byte[64]);
            sim.Step(3);
            foreach (byte cell in sim.State)
                Assert.Equal(Wireworld.Empty, cell);
        }

        [Fact]
        public void DefaultConstructorSeedsClockOrThrows()
        {
            var seeded = new Wireworld(16, 16); // Python default init: clock
            Assert.Equal(1, CountState(seeded, Wireworld.Head));
            Assert.Throws<ArgumentException>(() => new Wireworld(6, 5)); // too small, like Python
        }

        [Fact]
        public void ClockLoopIsPeriodic()
        {
            // The electron cuts corners (Moore adjacency briefly doubles the head), so we
            // detect the period instead of predicting it from the perimeter.
            var sim = new Wireworld(16, 16);
            sim.SeedClock();
            sim.Step(); // the seeded configuration is a transient; step onto the attractor
            byte[] reference = sim.State.ToArray();
            int period = -1;
            for (int t = 1; t <= 100; t++)
            {
                sim.Step();
                int heads = CountState(sim, Wireworld.Head);
                Assert.True(heads >= 1 && heads <= 2, "electron must neither die nor explode");
                if (sim.State.SequenceEqual(reference))
                {
                    period = t;
                    break;
                }
            }
            Assert.True(period > 0, "clock loop must be periodic");
            Assert.True(period >= 20, $"suspiciously short period {period} for a 16x16 loop");
        }

        [Fact]
        public void ClockLoopHelperShape()
        {
            var sim = new Wireworld(20, 12);
            sim.SeedClock();
            Assert.Equal(240, sim.State.Length);
            Assert.Equal(1, CountState(sim, Wireworld.Head));
            Assert.Equal(1, CountState(sim, Wireworld.Tail));
        }

        private static int CountState(Wireworld sim, byte value)
        {
            int count = 0;
            foreach (byte cell in sim.State)
                if (cell == value)
                    count++;
            return count;
        }
    }
}
