using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Behavior pins for the built-in pattern set (spec/patterns.md "Built-in
    /// patterns"): the encodings must BE the objects they claim — stills stay,
    /// oscillator periods hold, ships translate, the gun fires, the replicator
    /// copies itself, the Wireworld clock keeps circulating, and the diode
    /// passes electrons exactly one way.
    /// </summary>
    public class BuiltinPatternsTests
    {
        private static BuiltinPattern Builtin(string name)
        {
            foreach (BuiltinPattern pattern in BuiltinPatterns.All)
                if (pattern.Name == name)
                    return pattern;
            throw new InvalidOperationException($"no built-in named {name}");
        }

        /// <summary>An empty Life world with the named built-in stamped at (x, y).</summary>
        private static LifeLike StampedLife(string rule, int size, string name, int x, int y)
        {
            var world = new LifeLike(rule, size, size);
            var grid = new byte[size * size];
            RlePattern cells = Builtin(name).Decode();
            Patterns.Stamp(
                grid, size, size, 1, cells.Cells, cells.Width, cells.Height, x, y, torus: true);
            world.SetState(grid, 0);
            return world;
        }

        private static Wireworld StampedWireworld(int width, int height, string name, int x, int y)
        {
            var wire = new Wireworld(width, height); // ctor seeds its demo loop
            var grid = new byte[width * height];
            RlePattern cells = Builtin(name).Decode();
            Patterns.Stamp(
                grid, width, height, 1, cells.Cells, cells.Width, cells.Height, x, y, torus: false);
            wire.SetState(grid, 0);
            return wire;
        }

        private static int Population(ReadOnlySpan<byte> state)
        {
            int count = 0;
            foreach (byte cell in state)
                if (cell != 0)
                    count++;
            return count;
        }

        private static int CountState(ReadOnlySpan<byte> state, byte value)
        {
            int count = 0;
            foreach (byte cell in state)
                if (cell == value)
                    count++;
            return count;
        }

        /// <summary>Is `after` exactly `before` translated by some nonzero toroidal offset?</summary>
        private static bool TranslatedCopy(byte[] before, byte[] after, int size)
        {
            for (int dy = -4; dy <= 4; dy++)
                for (int dx = -4; dx <= 4; dx++)
                {
                    if (dx == 0 && dy == 0)
                        continue;
                    bool match = true;
                    for (int y = 0; y < size && match; y++)
                        for (int x = 0; x < size && match; x++)
                        {
                            int tx = ((x + dx) % size + size) % size;
                            int ty = ((y + dy) % size + size) % size;
                            match = after[ty * size + tx] == before[y * size + x];
                        }
                    if (match)
                        return true;
                }
            return false;
        }

        [Fact]
        public void SetIsWellformed()
        {
            var names = new System.Collections.Generic.HashSet<string>();
            foreach (BuiltinPattern pattern in BuiltinPatterns.All)
            {
                Assert.True(names.Add(pattern.Name), $"duplicate built-in name {pattern.Name}");
                Assert.True(
                    pattern.Family == "lifelike" || pattern.Family == "wireworld",
                    $"{pattern.Name} has unexpected family {pattern.Family}");
                RlePattern cells = pattern.Decode();
                Assert.True(Population(cells.Cells) > 0, $"{pattern.Name} decodes empty");
            }
        }

        [Theory]
        [InlineData("Block")]
        [InlineData("Beehive")]
        [InlineData("Loaf")]
        public void StillsStay(string name)
        {
            LifeLike world = StampedLife("B3/S23", 32, name, 12, 12);
            byte[] initial = world.State.ToArray();
            world.Step(2);
            Assert.Equal(initial, world.State.ToArray());
        }

        [Theory]
        [InlineData("Blinker", 2)]
        [InlineData("Toad", 2)]
        [InlineData("Beacon", 2)]
        [InlineData("Pulsar", 3)]
        [InlineData("Pentadecathlon", 15)]
        public void OscillatorPeriodsHold(string name, int period)
        {
            LifeLike world = StampedLife("B3/S23", 48, name, 18, 18);
            byte[] initial = world.State.ToArray();
            world.Step(1);
            Assert.NotEqual(initial, world.State.ToArray());
            world.Step(period - 1);
            Assert.Equal(initial, world.State.ToArray());
        }

        [Theory]
        [InlineData("Glider")]
        [InlineData("Lightweight spaceship")]
        [InlineData("Middleweight spaceship")]
        [InlineData("Heavyweight spaceship")]
        public void ShipsTranslate(string name)
        {
            LifeLike world = StampedLife("B3/S23", 48, name, 20, 20);
            byte[] initial = world.State.ToArray();
            world.Step(4);
            Assert.True(TranslatedCopy(initial, world.State.ToArray(), 48), $"{name} did not travel");
        }

        [Fact]
        public void GosperGunFires()
        {
            LifeLike world = StampedLife("B3/S23", 80, "Gosper glider gun", 4, 4);
            int before = Population(world.State);
            world.Step(120);
            Assert.True(Population(world.State) > before + 10, "gun did not fire");
        }

        [Fact]
        public void HighLifeReplicatorReplicates()
        {
            LifeLike world = StampedLife("B36/S23", 48, "Replicator (HighLife)", 20, 20);
            int before = Population(world.State);
            world.Step(12);
            Assert.Equal(2 * before, Population(world.State));
        }

        [Fact]
        public void WireworldClockKeepsTicking()
        {
            Wireworld wire = StampedWireworld(14, 9, "Clock", 3, 3);
            wire.Step(100);
            Assert.True(CountState(wire.State, Wireworld.Head) > 0, "clock died");
        }

        [Fact]
        public void WireworldDiodeIsOneWay()
        {
            // Electrons pass rightward…
            Wireworld wire = StampedWireworld(20, 9, "Diode (passes right)", 6, 3);
            wire.SetCell(6, 4, Wireworld.Tail);
            wire.SetCell(7, 4, Wireworld.Head);
            bool passed = false;
            for (int step = 0; step < 10 && !passed; step++)
            {
                wire.Step(1);
                for (int x = 11; x <= 13; x++)
                    passed |= wire.State[4 * wire.Width + x] == Wireworld.Head;
            }
            Assert.True(passed, "diode blocked the forward electron");
            // …and die leftward.
            wire = StampedWireworld(20, 9, "Diode (passes right)", 6, 3);
            wire.SetCell(13, 4, Wireworld.Tail);
            wire.SetCell(12, 4, Wireworld.Head);
            wire.Step(10);
            Assert.Equal(0, CountState(wire.State, Wireworld.Head));
        }
    }
}
