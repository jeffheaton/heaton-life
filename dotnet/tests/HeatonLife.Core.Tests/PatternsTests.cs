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

        [Fact]
        public void PlanarOpsMatchPerPlaneScalarOps()
        {
            // The planar helpers are layout adapters: every plane must go through
            // the same window/transform as the scalar ops run per plane.
            var grid = new double[]
            {
                1, 2, 3, 4,     // plane 0 (2x2)
                10, 20, 30, 40, // plane 1
            };
            double[] pattern = Patterns.ExtractPlanes(grid, 2, 2, 2, 1, 0, 2, 2, torus: true);
            double[] u = Patterns.Extract(
                new ReadOnlySpan<double>(grid, 0, 4), 2, 2, 1, 1, 0, 2, 2, torus: true);
            double[] v = Patterns.Extract(
                new ReadOnlySpan<double>(grid, 4, 4), 2, 2, 1, 1, 0, 2, 2, torus: true);
            for (int i = 0; i < 4; i++)
            {
                Assert.Equal(u[i], pattern[i]);
                Assert.Equal(v[i], pattern[4 + i]);
            }

            double[] rotated = Patterns.Rotate90Planes(pattern, 2, 2, 2);
            double[] flippedH = Patterns.FlipHPlanes(pattern, 2, 2, 2);
            double[] flippedV = Patterns.FlipVPlanes(pattern, 2, 2, 2);
            double[] ru = Patterns.Rotate90(u, 2, 2);
            double[] hu = Patterns.FlipH(u, 2, 2);
            double[] vu = Patterns.FlipV(u, 2, 2);
            for (int i = 0; i < 4; i++)
            {
                Assert.Equal(ru[i], rotated[i]);
                Assert.Equal(hu[i], flippedH[i]);
                Assert.Equal(vu[i], flippedV[i]);
            }

            // Stamping the extracted pattern into a blank grid of the same size
            // reproduces it plane for plane.
            var target = new double[8];
            Patterns.StampPlanes(target, 2, 2, 2, pattern, 2, 2, 0, 0, torus: true);
            Assert.Equal(pattern, target);
        }

        [Fact]
        public void PlanarStampClipsOnDeadBoundaries()
        {
            var grid = new double[2 * 9]; // 3x3, two planes
            var pattern = new[] { 1.0, 2.0, 10.0, 20.0 }; // 2x1, two planes
            Patterns.StampPlanes(grid, 3, 3, 2, pattern, 2, 1, 2, 0, torus: false);
            Assert.Equal(1.0, grid[2]);      // (2,0) plane 0 landed
            Assert.Equal(10.0, grid[9 + 2]); // (2,0) plane 1 landed with it
            for (int i = 0; i < grid.Length; i++)
                if (i != 2 && i != 11)
                    Assert.Equal(0.0, grid[i]); // the (3,0) cell clipped, nothing wrapped
        }
    }
}
