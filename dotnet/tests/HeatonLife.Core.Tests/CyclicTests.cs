using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class CyclicTests
    {
        [Fact]
        public void SuccessorAdvanceWithThresholdOne()
        {
            var sim = new Cyclic(4, 3, 3, threshold: 1);
            var grid = new byte[9];
            grid[1 * 3 + 2] = 1; // one neighbor of the center holds the successor state
            sim.SetState(grid);
            sim.Step();
            Assert.Equal(1, sim.State[1 * 3 + 1]); // center advanced 0 -> 1
        }

        [Fact]
        public void ThresholdBlocksAdvance()
        {
            var sim = new Cyclic(4, 3, 3, threshold: 2);
            var grid = new byte[9];
            grid[1 * 3 + 2] = 1;
            sim.SetState(grid);
            sim.Step();
            Assert.Equal(0, sim.State[1 * 3 + 1]); // one successor neighbor is not enough
        }

        [Fact]
        public void UniformGridIsFixedPoint()
        {
            var sim = new Cyclic(5, 8, 8);
            var grid = new byte[64];
            Array.Fill(grid, (byte)3);
            sim.SetState(grid);
            sim.Step(10);
            Assert.Equal(grid, sim.State.ToArray());
        }

        [Fact]
        public void WrapsFromLastStateToZero()
        {
            var sim = new Cyclic(4, 3, 3, threshold: 1);
            var grid = new byte[9];
            Array.Fill(grid, (byte)3);
            grid[1 * 3 + 1] = 2; // center's successor (3) surrounds it
            sim.SetState(grid);
            sim.Step();
            Assert.Equal(3, sim.State[1 * 3 + 1]);
            // now the center is 3; its successor is 0, but no neighbor is 0
            sim.Step();
            Assert.Equal(3, sim.State[1 * 3 + 1]);
        }

        [Fact]
        public void VonNeumannExcludesDiagonals()
        {
            var sim = new Cyclic(4, 3, 3, threshold: 1, reach: 1, Neighborhood.VonNeumann);
            var grid = new byte[9];
            grid[0] = 1; // diagonal neighbor of the center
            sim.SetState(grid);
            sim.Step();
            Assert.Equal(0, sim.State[1 * 3 + 1]);
        }

        [Fact]
        public void ReachTwoCountsDistantCells()
        {
            var sim = new Cyclic(4, 5, 5, threshold: 1, reach: 2);
            var grid = new byte[25];
            grid[2 * 5 + 4] = 1; // two cells away from the center
            sim.SetState(grid);
            sim.Step();
            Assert.Equal(1, sim.State[2 * 5 + 2]);
        }

        [Fact]
        public void SoupDeterminismAndRange()
        {
            var a = new Cyclic(14, 32, 32);
            var b = new Cyclic(14, 32, 32);
            a.SeedSoup(7);
            b.SeedSoup(7);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
            foreach (byte cell in a.State)
                Assert.True(cell < 14);
            a.Step(5);
            b.Step(5);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
        }

        [Fact]
        public void RejectsInitValuesOutsideStates()
        {
            var sim = new Cyclic(4, 2, 2);
            var grid = new byte[4];
            Array.Fill(grid, (byte)9);
            Assert.Throws<ArgumentException>(() => sim.SetState(grid));
        }
    }
}
