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
        public void DecodeRefusesWhatItCannotHold()
        {
            // The limit lifted, a grid still has to fit one array.
            var lifted = Assert.Throws<ArgumentException>(
                () => Patterns.RleDecode("x = 100000, y = 100000\no!", null));
            Assert.Contains("more than one array holds", lifted.Message);
            // A declared size past an int used to wrap around; now it is just past the limit.
            var declared = Assert.Throws<ArgumentException>(
                () => Patterns.RleDecode("x = 99999999999999999999, y = 1\no!"));
            Assert.Contains("past the limit of 67108864", declared.Message);
            Assert.Equal(1L << 26, Patterns.DefaultMaxCells);
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
        public void RleWritesEveryByteState()
        {
            // Two-letter tags reach state 255 (spec/patterns.md), so every byte has a tag.
            Assert.EndsWith("\npA!\n", Patterns.RleEncode(new byte[] { 25 }, 1, 1));
            Assert.EndsWith("\nyO!\n", Patterns.RleEncode(new byte[] { 255 }, 1, 1));
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

        /// <summary>spec/patterns.md "Dialect detection": a header naming any Life-like rule
        /// makes uppercase B and O dead and alive.</summary>
        [Fact]
        public void AHeaderNamingAnyLifeLikeRuleIsTwoState()
        {
            foreach (string rule in new[] { "B2-a/S12", "B2/S34H", "B1/SV", "MAP" + new string('A', 86) })
            {
                RlePattern pattern = Patterns.RleDecode($"x = 2, y = 2, rule = {rule}\nOB$BO!");
                Assert.Equal(rule, pattern.Rule);
                Assert.Equal(new byte[] { 1, 0, 0, 1 }, pattern.Cells);
            }
            // A name that is not a rule in this grammar reads as extended: O 15, B 2.
            Assert.Equal(new byte[] { 15, 2, 2, 15 }, Patterns.RleDecode("x = 2, y = 2, rule = life\nOB$BO!").Cells);
        }

        // ---- a header's rule in survival/birth order (spec/formats.md "Rules in survival/birth order")

        [Theory]
        [InlineData("23/3", "B3/S23")]
        [InlineData("323/33", "B3/S23")] // sorted, repeats dropped
        [InlineData("/2", "B2/S")]
        [InlineData("3/", "B/S3")]
        [InlineData("/", "B/S")]
        [InlineData("23/3:T30,20", "B3/S23")] // the bounded-grid suffix comes off first
        public void ASurvivalBirthHeaderReadsAsBS(string header, string rule)
        {
            RlePattern read = Patterns.RleDecode($"x = 3, y = 1, rule = {header}\nOBO!\n");
            Assert.Equal(rule, read.Rule);
            Assert.Equal(new byte[] { 1, 0, 1 }, read.Cells); // two-state: uppercase B and O are dead and alive
        }

        [Theory]
        [InlineData("23/3/2")]
        [InlineData("9/3")]
        [InlineData("23/3a")]
        public void OtherSlashedRulesStayAsWritten(string header)
        {
            RlePattern read = Patterns.RleDecode($"x = 3, y = 1, rule = {header}\nOBO!\n");
            Assert.Equal(header, read.Rule);
            Assert.Equal(new byte[] { 15, 2, 15 }, read.Cells); // not Life-like: extended
        }

        [Fact]
        public void CanonicalRleWritesBSForASurvivalBirthRule()
        {
            string text = Patterns.RleEncode(new byte[] { 0, 1, 1 }, 3, 1, "23/36");
            Assert.StartsWith("x = 3, y = 1, rule = B36/S23\n", text);
            RlePattern read = Patterns.RleDecode("x = 3, y = 1, rule = 23/36\nb2o!\n");
            Assert.Equal("B36/S23", Patterns.RleDecode(Patterns.RleEncode(read.Cells, read.Width, read.Height, read.Rule!)).Rule);
            Assert.Equal("B36/S23", PatternFiles.ReadUniverse("x = 3, y = 1, rule = 23/36\nb2o!\n").Universe.Rule);
        }
    }
}
