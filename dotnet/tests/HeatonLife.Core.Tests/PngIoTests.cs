using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// PNG grid I/O unit tests (spec/png-io.md): the round-trip law at several
    /// scales, MergeLife's export convenience, and input validation.
    /// </summary>
    public class PngIoTests
    {
        private static byte[] Grid(int width, int height)
        {
            var grid = new byte[width * height * 3];
            for (int i = 0; i < grid.Length; i++)
                grid[i] = (byte)((i * 11 + 5) % 256);
            return grid;
        }

        [Theory]
        [InlineData(1)]
        [InlineData(2)]
        [InlineData(3)]
        [InlineData(8)]
        public void RoundTripLaw(int scale)
        {
            byte[] grid = Grid(7, 6);
            byte[] png = PngGrid.EncodeRgb(grid, 7, 6, scale);
            byte[] decoded = PngGrid.DecodeRgb(png, scale, out int width, out int height);
            Assert.Equal(7, width);
            Assert.Equal(6, height);
            Assert.Equal(grid, decoded);
        }

        [Fact]
        public void MergeLifeExportsItsLattice()
        {
            var sim = new MergeLife(MergeLife.DefaultGenome, 16, 16);
            sim.SeedSoup(3);
            byte[] png = sim.ToPng(4);
            byte[] decoded = PngGrid.DecodeRgb(png, 4, out int width, out int height);
            Assert.Equal(16, width);
            Assert.Equal(16, height);
            Assert.Equal(sim.State.ToArray(), decoded);
        }

        [Fact]
        public void ScaleMustDivideDimensions()
        {
            byte[] png = PngGrid.EncodeRgb(Grid(7, 6), 7, 6, 2); // 14x12
            Assert.Throws<ArgumentException>(
                () => PngGrid.DecodeRgb(png, 4, out _, out _));
        }

        [Fact]
        public void RejectsBadInputs()
        {
            Assert.Throws<ArgumentException>(
                () => PngGrid.EncodeRgb(new byte[5], 7, 6, 1));
            Assert.Throws<ArgumentException>(
                () => PngGrid.EncodeRgb(Grid(7, 6), 7, 6, 0));
            Assert.Throws<ArgumentException>(
                () => PngGrid.DecodeRgb(new byte[] { 1, 2, 3 }, 1, out _, out _));
        }
    }
}
