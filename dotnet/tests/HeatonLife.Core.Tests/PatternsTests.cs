using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class PatternsTests
    {
        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        [Fact]
        public void Rotate90IsClockwiseAndFourTurnsAreIdentity()
        {
            var pattern = new byte[] { 1, 2, 3, 4 };
            byte[] rotated = Patterns.Rotate90(pattern, 2, 2);
            Assert.Equal(new byte[] { 3, 1, 4, 2 }, rotated);
            byte[] result = pattern;
            for (int i = 0; i < 4; i++)
                result = Patterns.Rotate90(result, 2, 2);
            Assert.Equal(pattern, result);
        }

        [Fact]
        public void FlipsMirrorAndInvolute()
        {
            Assert.Equal(
                new byte[] { 0, 1, 0, 1, 0, 0, 1, 1, 1 },
                Patterns.FlipH(Glider, 3, 3));
            Assert.Equal(
                new byte[] { 1, 1, 1, 0, 0, 1, 0, 1, 0 },
                Patterns.FlipV(Glider, 3, 3));
            Assert.Equal(Glider, Patterns.FlipH(Patterns.FlipH(Glider, 3, 3), 3, 3));
            Assert.Equal(Glider, Patterns.FlipV(Patterns.FlipV(Glider, 3, 3), 3, 3));
        }

        [Fact]
        public void TransformsMoveChannelsTogether()
        {
            var rgb = new byte[] { 10, 20, 30, 40, 50, 60 }; // 1x2, RGB
            byte[] rotated = Patterns.Rotate90(rgb, 2, 1, channels: 3); // -> 1x2 vertical
            Assert.Equal(new byte[] { 10, 20, 30, 40, 50, 60 }, rotated);
        }

        [Fact]
        public void ExtractWrapsOnTorusAndZeroFillsDead()
        {
            var grid = new byte[16];
            for (int i = 0; i < 16; i++)
                grid[i] = (byte)i;
            Assert.Equal(
                new byte[] { 15, 12, 3, 0 },
                Patterns.Extract(grid, 4, 4, 1, 3, 3, 2, 2, torus: true));
            Assert.Equal(
                new byte[] { 15, 0, 0, 0 },
                Patterns.Extract(grid, 4, 4, 1, 3, 3, 2, 2, torus: false));
        }

        [Fact]
        public void StampWrapsClipsAndRespectsTransparency()
        {
            var grid = new byte[16];
            Patterns.Stamp(grid, 4, 4, 1, Glider, 3, 3, 2, 2, torus: true);
            Assert.Equal(1, grid[2 * 4 + 3]);
            Assert.Equal(1, grid[3 * 4 + 0]);
            Assert.Equal(1, grid[0 * 4 + 2]);

            grid = new byte[16];
            Patterns.Stamp(grid, 4, 4, 1, Glider, 3, 3, 2, 2, torus: false);
            int alive = 0;
            foreach (byte cell in grid)
                alive += cell;
            Assert.Equal(1, alive); // only the in-range live cell landed

            grid = new byte[9];
            Array.Fill(grid, (byte)7);
            Patterns.Stamp(grid, 3, 3, 1, Glider, 3, 3, 0, 0, torus: true, transparent: true);
            Assert.Equal(7, grid[0]);
            Assert.Equal(1, grid[1]);

            grid = new byte[9];
            Array.Fill(grid, (byte)7);
            Patterns.Stamp(grid, 3, 3, 1, Glider, 3, 3, 0, 0, torus: true, transparent: false);
            Assert.Equal(0, grid[0]);
        }

        [Fact]
        public void TransparentRejectedForChannelPayloads()
        {
            var rgbGrid = new byte[4 * 4 * 3];
            var rgbPattern = new byte[2 * 2 * 3];
            Assert.Throws<ArgumentException>(() =>
                Patterns.Stamp(rgbGrid, 4, 4, 3, rgbPattern, 2, 2, 0, 0, torus: true, transparent: true));
        }

        [Fact]
        public void CompatibilityIsFamilyBound()
        {
            Assert.NotNull(Patterns.Compatible("lifelike", "wireworld", Glider));
            Assert.NotNull(Patterns.Compatible("lifelike", "mergelife", Glider));
            Assert.Null(Patterns.Compatible("lifelike", "lifelike", Glider));
            var highState = new byte[] { 13 };
            Assert.Null(Patterns.Compatible("cyclic", "cyclic", highState, targetStates: 14));
            Assert.NotNull(Patterns.Compatible("cyclic", "cyclic", highState, targetStates: 6));
        }

        [Fact]
        public void MultistateRleRoundTrips()
        {
            var diode = new byte[] { 0, 3, 3, 0, 1, 3, 0, 3, 0, 3, 3, 2 };
            string text = Patterns.RleEncode(diode, 4, 3, rule: "WireWorld");
            RlePattern decoded = Patterns.RleDecode(text);
            Assert.Equal("WireWorld", decoded.Rule);
            Assert.Equal(4, decoded.Width);
            Assert.Equal(3, decoded.Height);
            Assert.Equal(diode, decoded.Cells);
        }

        [Fact]
        public void TwoStateRleStillRoundTrips()
        {
            string text = Patterns.RleEncode(Glider, 3, 3);
            Assert.Contains("o", text);
            Assert.DoesNotContain(".", text);
            RlePattern decoded = Patterns.RleDecode(text);
            Assert.Equal(Glider, decoded.Cells);
        }

        [Fact]
        public void RleRejectsUnencodableStates()
        {
            Assert.Throws<ArgumentException>(() => Patterns.RleEncode(new byte[] { 25 }, 1, 1));
        }

        [Fact]
        public void SetStateWithGenerationRestoresTheCounter()
        {
            var sim = new LifeLike("B3/S23", 16, 16);
            sim.Step(3);
            byte[] saved = sim.State.ToArray();
            var restored = new LifeLike("B3/S23", 16, 16);
            restored.SetState(saved, 40312);
            Assert.Equal(40312, restored.Generation);
            Assert.Equal(saved, restored.State.ToArray());
        }
    }
}
