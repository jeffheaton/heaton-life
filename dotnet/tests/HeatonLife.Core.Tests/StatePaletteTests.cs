using System;
using System.Collections.Generic;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// State palettes (spec/render.md "State palettes"): each family's default, a colormap's
    /// palette, the named palettes, the shade, and the zoom order that goes with a palette.
    /// </summary>
    public class StatePaletteTests
    {
        /// <summary>Every grid family with byte states, stepped a little, with its states as a frame.</summary>
        private static IEnumerable<(IIndexedFrameSource World, byte[] States)> Worlds()
        {
            var life = new LifeLike("B3/S23", 24, 20);
            life.SeedSoup(0.35, 1);
            life.Step(3);
            yield return (life, life.State.ToArray());
            var history = new LifeLike("B3/S23History", 24, 20);
            history.SeedSoup(0.35, 1);
            history.Step(9);
            yield return (history, history.State.ToArray());
            var elementary = new Elementary(30, 40, 24);
            elementary.Step(30);
            yield return (elementary, elementary.Diagram.ToArray());
            var cyclic = new Cyclic(14, 24, 20);
            cyclic.SeedSoup(4);
            cyclic.Step(5);
            yield return (cyclic, cyclic.State.ToArray());
            var wire = new Wireworld(16, 16);
            wire.Step(4);
            yield return (wire, wire.State.ToArray());
            var generations = new Generations("B2/S345/C6", 24, 20);
            generations.SeedSoup(0.35, 5);
            generations.Step(6);
            yield return (generations, generations.State.ToArray());
        }

        public static IEnumerable<object[]> ColormapNames()
        {
            foreach (string name in Colormaps.Names)
                yield return new object[] { name };
        }

        [Theory]
        [MemberData(nameof(ColormapNames))]
        public void AColormapsPaletteShowsTheStatesAsTheColormapShowsTheFrame(string cmap)
        {
            byte[] lut = Colormaps.Get(cmap);
            foreach (var (world, states) in Worlds())
            {
                var frame = new byte[world.Width * world.Height];
                world.WriteFrame(frame);
                byte[] palette = StatePalettes.FromColormap(world, lut);
                Assert.Equal(Colormaps.ApplyIndexed(frame, lut), Colormaps.ApplyIndexed(states, palette));
                int count = StatePalettes.FrameValues(world).Length;
                for (int i = count * 3; i < 768; i++)
                    Assert.Equal(0, palette[i]);
            }
        }

        [Fact]
        public void FrameValuesAreEachStatesFrameByte()
        {
            foreach (var (world, states) in Worlds())
            {
                byte[] values = StatePalettes.FrameValues(world);
                Assert.Equal(0, values[0]);
                var frame = new byte[world.Width * world.Height];
                world.WriteFrame(frame);
                for (int i = 0; i < frame.Length; i++)
                    Assert.Equal(frame[i], values[states[i]]);
            }
            Assert.Equal(new byte[] { 0, 255 }, StatePalettes.FrameValues(new HashLife()));
            Assert.Equal(new byte[] { 0, 1, 2, 3 }, StatePalettes.FrameValues(new MultiStateHashLife("WireWorld")));
            Assert.Equal(new byte[] { 0, 255 }, StatePalettes.FrameValues(new Cyclic(2, 8, 8)));
        }

        [Fact]
        public void EachFamilyHasTheDefaultTheSpecGives()
        {
            foreach (var (world, _) in Worlds())
            {
                byte[] expected = world switch
                {
                    LifeLike life when life.States == 2 => StatePalettes.FromColormap(world, Colormaps.Get("phosphor")),
                    LifeLike _ => StatePalettes.ForHistory(),
                    Elementary _ => StatePalettes.FromColormap(world, Colormaps.Get("gray")),
                    Cyclic _ => StatePalettes.FromColormap(world, Colormaps.Get("rainbow")),
                    Wireworld _ => StatePalettes.FromColormap(world, Colormaps.Get("wireworld")),
                    Generations g => StatePalettes.ForGenerations(g.States),
                    _ => throw new InvalidOperationException(),
                };
                Assert.Equal(expected, StatePalettes.Default(world));
                if (world is Generations)
                    Assert.Equal(StatePalettes.FromColormap(world, Colormaps.Get("fire")), StatePalettes.Default(world));
            }
            byte[] two = StatePalettes.Default(new LifeLike("B3/S23", 8, 8));
            Assert.Equal(new byte[] { 6, 10, 6, 170, 255, 190, 0 }, two.AsSpan(0, 7).ToArray());
            Assert.Equal(two, StatePalettes.Default(new HashLife("B3/S23")));
        }

        [Fact]
        public void AUniversesPaletteIsItsRulesOnAGrid()
        {
            Assert.Equal(
                StatePalettes.Default(new Wireworld(16, 16)),
                StatePalettes.Default(new MultiStateHashLife("WireWorld")));
            Assert.Equal(StatePalettes.ForHistory(), StatePalettes.Default(new MultiStateHashLife("B36/S23History")));
            foreach (var (rule, count) in new[] { ("B2/S/C3", 3), ("B2/S345/C4", 4), ("B3/S23/C256", 256) })
            {
                byte[] plane = StatePalettes.Default(new MultiStateHashLife(rule));
                Assert.Equal(StatePalettes.Default(new Generations(rule, 8, 8)), plane);
                Assert.Equal(StatePalettes.ForGenerations(count), plane);
            }
        }

        [Fact]
        public void LargerThanLifeTakesPhosphorOrGenerations()
        {
            var two = new LargerThanLife("R5,C0,M1,S34..58,B34..45,NM", 40, 32);
            two.SeedSoup(0.5, 2);
            two.Step(2);
            var many = new LargerThanLife("R2,C5,M0,S3..8,B4..6,NM", 40, 32);
            many.SeedSoup(0.5, 3);
            many.Step(6);
            Assert.Equal(new byte[] { 0, 255 }, StatePalettes.FrameValues(two));
            Assert.Equal(new byte[] { 0, 1, 2, 3, 4 }, StatePalettes.FrameValues(many));
            Assert.Equal(StatePalettes.FromColormap(two, Colormaps.Get("phosphor")), StatePalettes.Default(two));
            Assert.Equal(StatePalettes.ForGenerations(5), StatePalettes.Default(many));
            Assert.Empty(StatePalettes.DefaultZoomOrder(two));
            Assert.Empty(StatePalettes.DefaultZoomOrder(many));
            Assert.Equal(new[] { 0, 1 }, Distinct(two.State));
            Assert.Equal(new[] { 0, 1, 2, 3, 4 }, Distinct(many.State)); // every state is shown
            foreach (LargerThanLife world in new[] { two, many })
            {
                byte[] states = world.State.ToArray();
                byte[] frame = world.Frame();
                foreach (string cmap in new[] { "phosphor", "fire", "rainbow" })
                {
                    byte[] lut = Colormaps.Get(cmap);
                    Assert.Equal(
                        Colormaps.ApplyIndexed(frame, lut),
                        Colormaps.ApplyIndexed(states, StatePalettes.FromColormap(world, lut)));
                }
            }
        }

        private static int[] Distinct(ReadOnlySpan<byte> cells)
        {
            var seen = new SortedSet<int>();
            foreach (byte cell in cells)
                seen.Add(cell);
            var values = new int[seen.Count];
            seen.CopyTo(values);
            return values;
        }

        [Fact]
        public void HistorysColors()
        {
            byte[] palette = StatePalettes.ForHistory();
            Assert.Equal(
                new byte[]
                {
                    0, 0, 0, 0, 255, 0, 0, 0, 160, 255, 255, 255, 255, 0, 0, 255, 255, 0, 128, 128, 128,
                },
                palette.AsSpan(0, 21).ToArray());
            for (int i = 21; i < 768; i++)
                Assert.Equal(0, palette[i]);
            palette[3] = 9; // a copy each time
            Assert.Equal(0, StatePalettes.ForHistory()[3]);
        }

        [Theory]
        [InlineData(2)]
        [InlineData(3)]
        [InlineData(4)]
        [InlineData(5)]
        [InlineData(17)]
        [InlineData(64)]
        [InlineData(255)]
        [InlineData(256)]
        public void GenerationsPaletteIsFireAtTheFade(int count)
        {
            byte[] fire = Colormaps.Get("fire");
            byte[] palette = StatePalettes.ForGenerations(count);
            Assert.Equal(new byte[] { 0, 0, 0 }, palette.AsSpan(0, 3).ToArray());
            for (int s = 1; s < count; s++)
            {
                int entry = 255 * (count - s) / (count - 1);
                Assert.Equal(fire.AsSpan(entry * 3, 3).ToArray(), palette.AsSpan(s * 3, 3).ToArray());
            }
            Assert.Equal(fire.AsSpan(255 * 3, 3).ToArray(), palette.AsSpan(3, 3).ToArray());
        }

        [Theory]
        [InlineData(2)]
        [InlineData(3)]
        [InlineData(8)]
        [InlineData(100)]
        [InlineData(256)]
        public void TheMultiStatePaletteGivesEveryStateItsOwnHue(int count)
        {
            byte[] rainbow = Colormaps.Get("rainbow");
            byte[] palette = StatePalettes.ForMultiState(count);
            var seen = new HashSet<int>();
            Assert.Equal(new byte[] { 0, 0, 0 }, palette.AsSpan(0, 3).ToArray());
            for (int s = 1; s < count; s++)
            {
                int entry = 255 * (s - 1) / (count - 1);
                Assert.Equal(rainbow.AsSpan(entry * 3, 3).ToArray(), palette.AsSpan(s * 3, 3).ToArray());
                Assert.True(seen.Add((palette[s * 3] << 16) | (palette[s * 3 + 1] << 8) | palette[s * 3 + 2]));
            }
            Assert.DoesNotContain(0, seen);
        }

        [Fact]
        public void AGradientRunsFromFirstToLastRoundingHalfToEven()
        {
            byte[] palette = StatePalettes.Gradient(6, (255, 0, 0), (0, 0, 255));
            Assert.Equal(
                new byte[] { 0, 0, 0, 255, 0, 0, 191, 0, 64, 128, 0, 128, 64, 0, 191, 0, 0, 255, 0, 0, 0 },
                palette.AsSpan(0, 21).ToArray());
            byte[] ties = StatePalettes.Gradient(4, (0, 0, 3), (1, 3, 0), (9, 8, 7));
            Assert.Equal(new byte[] { 9, 8, 7, 0, 0, 3, 0, 2, 2, 1, 3, 0 }, ties.AsSpan(0, 12).ToArray());
            byte[] two = StatePalettes.Gradient(2, (1, 2, 3), (4, 5, 6));
            Assert.Equal(new byte[] { 0, 0, 0, 1, 2, 3, 0, 0, 0 }, two.AsSpan(0, 9).ToArray());
            byte[] big = StatePalettes.Gradient(256, (0, 0, 0), (100, 100, 100));
            for (int k = 0; k < 255; k++)
                Assert.Equal((byte)Math.Round(100.0 * k / 254.0), big[(k + 1) * 3]);
        }

        [Fact]
        public void TheShadeIsTheTwoAnchorColormap()
        {
            Assert.Equal(Colormaps.Get("gray"), StatePalettes.Shade((0, 0, 0), (255, 255, 255)));
            var rng = new Random(7);
            for (int trial = 0; trial < 200; trial++)
            {
                var b = ((byte)rng.Next(256), (byte)rng.Next(256), (byte)rng.Next(256));
                var c = ((byte)rng.Next(256), (byte)rng.Next(256), (byte)rng.Next(256));
                byte[] shade = StatePalettes.Shade(b, c);
                for (int v = 0; v < 256; v++)
                {
                    double x = v == 255 ? 1.0 : v * (1.0 / 255.0); // the LUT construction's samples
                    Assert.Equal((byte)Math.Round(x * (c.Item1 - b.Item1) + b.Item1), shade[v * 3]);
                    Assert.Equal((byte)Math.Round(x * (c.Item2 - b.Item2) + b.Item2), shade[v * 3 + 1]);
                    Assert.Equal((byte)Math.Round(x * (c.Item3 - b.Item3) + b.Item3), shade[v * 3 + 2]);
                }
            }
        }

        [Fact]
        public void TheZoomOrderGoesWithThePalette()
        {
            var order = new byte[] { 3, 5, 1, 4, 6, 2 };
            Assert.Equal(order, StatePalettes.DefaultZoomOrder(new LifeLike("B3/S23History", 8, 8)));
            Assert.Equal(order, StatePalettes.DefaultZoomOrder(new LifeLike("B2/S34HHistory", 8, 8)));
            var universe = new MultiStateHashLife("LifeHistory");
            Assert.Equal(order, StatePalettes.DefaultZoomOrder(universe));
            universe.ZoomOrder = StatePalettes.DefaultZoomOrder(universe); // the host sets it
            Assert.Equal(order, universe.ZoomOrder);
            foreach (ISimulation world in new ISimulation[]
            {
                new LifeLike("B3/S23", 8, 8), new Generations("B2/S/C3", 8, 8), new Wireworld(16, 16),
                new Cyclic(5, 8, 8), new Elementary(90, 8, 8),
            })
                Assert.Empty(StatePalettes.DefaultZoomOrder(world));
            Assert.Empty(StatePalettes.DefaultZoomOrder(new HashLife()));
            Assert.Empty(StatePalettes.DefaultZoomOrder(new MultiStateHashLife("WireWorld")));
            Assert.Empty(StatePalettes.DefaultZoomOrder(new MultiStateHashLife("B2/S/C3")));
        }

        [Fact]
        public void WorldsWithoutByteStatesHaveNoPalette()
        {
            var gray = new GrayScott(8, 8);
            Assert.Throws<ArgumentException>(() => StatePalettes.FrameValues(gray));
            Assert.Throws<ArgumentException>(() => StatePalettes.Default(gray));
            Assert.Throws<ArgumentException>(() => StatePalettes.DefaultZoomOrder(gray));
            Assert.Throws<ArgumentException>(() => StatePalettes.FromColormap(gray, Colormaps.Get("gray")));
            Assert.Throws<ArgumentNullException>(() => StatePalettes.Default((ISimulation)null!));
            Assert.Throws<ArgumentException>(
                () => StatePalettes.FromColormap(new LifeLike("B3/S23", 8, 8), new byte[767]));
        }

        [Theory]
        [InlineData(0)]
        [InlineData(1)]
        [InlineData(257)]
        [InlineData(-3)]
        public void APaletteIsFor2To256States(int count)
        {
            Assert.Throws<ArgumentOutOfRangeException>(() => StatePalettes.ForGenerations(count));
            Assert.Throws<ArgumentOutOfRangeException>(() => StatePalettes.ForMultiState(count));
            Assert.Throws<ArgumentOutOfRangeException>(() => StatePalettes.Gradient(count, (0, 0, 0), (1, 1, 1)));
        }

        /// <summary>Super's 26 colors (spec/render.md "Default palettes"): History's for states 0–6
        /// and none twice; its zoom order extends History's, every on state before every off one and
        /// the envelopes last ("Zoomed out").</summary>
        [Fact]
        public void SupersPaletteAndZoomOrder()
        {
            byte[] palette = StatePalettes.ForSuper();
            byte[] history = StatePalettes.ForHistory();
            Assert.Equal(768, palette.Length);
            for (int i = 0; i < 21; i++)
                Assert.Equal(history[i], palette[i]); // states 0–6 are History's
            var colors = new HashSet<(byte, byte, byte)>();
            for (int s = 0; s < 26; s++)
                colors.Add((palette[3 * s], palette[3 * s + 1], palette[3 * s + 2]));
            Assert.Equal(26, colors.Count);
            Assert.Equal(((byte)255, (byte)216, (byte)255), (palette[39], palette[40], palette[41])); // 13: white is 3's
            for (int i = 78; i < palette.Length; i++)
                Assert.Equal(0, palette[i]);
            byte[] order = StatePalettes.DefaultZoomOrder(new LifeLike("B3/S23Super", 8, 8));
            var sorted = (byte[])order.Clone();
            Array.Sort(sorted);
            for (int i = 0; i < 25; i++)
                Assert.Equal(i + 1, sorted[i]);
            var historyOnly = new List<byte>();
            foreach (byte v in order)
            {
                if (v < 7)
                    historyOnly.Add(v);
            }
            Assert.Equal(new byte[] { 3, 5, 1, 4, 6, 2 }, historyOnly.ToArray());
            for (int i = 0; i < 13; i++)
                Assert.Equal(1, order[i] & 1); // the 13 on states first
            Assert.Equal(new byte[] { 2, 10, 12 }, new[] { order[22], order[23], order[24] });
            foreach (LifeLike world in new[] { new LifeLike("B3/S23Super", 8, 8), new LifeLike("B2/S013VSuper", 8, 8) })
            {
                Assert.Equal(palette, StatePalettes.Default(world));
                Assert.Equal(order, StatePalettes.DefaultZoomOrder(world));
                Assert.Equal(26, StatePalettes.FrameValues(world).Length);
            }
            var universe = new MultiStateHashLife("LifeSuper");
            Assert.Equal(palette, StatePalettes.Default(universe));
            Assert.Equal(order, StatePalettes.DefaultZoomOrder(universe));
            universe.ZoomOrder = StatePalettes.DefaultZoomOrder(universe); // the host sets it
            Assert.Equal(history, StatePalettes.Default(new LifeLike("LifeHistory", 8, 8)));
        }
    }
}
