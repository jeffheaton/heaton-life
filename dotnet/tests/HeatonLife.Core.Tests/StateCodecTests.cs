using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// StateCodec is the C# counterpart of the Python reference's CODECS table.
    /// Its byte layout is a STORAGE contract — worlds saved by shipped builds are
    /// on users' disks in exactly this format — so these tests pin the layout, not
    /// just the round trip.
    /// </summary>
    public class StateCodecTests
    {
        private static ISimulation[] AllFamilies() => new ISimulation[]
        {
            new LifeLike("B3/S23", 16, 16),
            new Elementary(30, 16, 8),
            new Cyclic(4, 16, 16),
            new Wireworld(16, 16),
            new MergeLife(MergeLife.DefaultRule, 16, 16),
            new GrayScott(16, 16),
            new ClassicLenia(32, 32, radius: 8),
            new AsymptoticLenia(32, 32, radius: 8),
            new FlowLenia(32, 32, radius: 8),
            new Boids(8, 64, 64),
        };

        [Fact]
        public void EveryFamilyRoundTripsThroughTheCodec()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                string name = sim.GetType().Name;
                sim.Step(3);
                byte[] saved = StateCodec.Save(sim);
                int generation = sim.Generation;

                // Drive it somewhere else entirely, then restore.
                sim.Step(9);
                Assert.NotEqual(generation, sim.Generation);
                StateCodec.Load(sim, saved, generation);

                Assert.Equal(generation, sim.Generation);
                Assert.Equal(saved, StateCodec.Save(sim));

                // And the restored world evolves identically to the original.
                sim.Step(4);
                byte[] afterRestore = StateCodec.Save(sim);
                StateCodec.Load(sim, saved, generation);
                sim.Step(4);
                Assert.Equal(afterRestore, StateCodec.Save(sim));
                Assert.True(afterRestore.Length > 0, name);
            }
        }

        /// <summary>
        /// Doubles are explicit little-endian IEEE-754, written byte by byte — the
        /// layout already on disk in shipped saves, and the one that makes a world
        /// portable regardless of host endianness. 1.0 is 0x3FF0000000000000, so
        /// little-endian it is 00 00 00 00 00 00 F0 3F.
        /// </summary>
        [Fact]
        public void DoublesAreExplicitLittleEndian()
        {
            byte[] bytes = StateCodec.DoubleBytes(new double[] { 1.0 });
            Assert.Equal(new byte[] { 0, 0, 0, 0, 0, 0, 0xF0, 0x3F }, bytes);

            byte[] two = StateCodec.DoubleBytes(new double[] { -2.0, 0.5 });
            Assert.Equal(16, two.Length);
            Assert.Equal(new byte[] { 0, 0, 0, 0, 0, 0, 0, 0xC0 }, two.AsSpan(0, 8).ToArray());
            Assert.Equal(new byte[] { 0, 0, 0, 0, 0, 0, 0xE0, 0x3F }, two.AsSpan(8, 8).ToArray());
        }

        [Fact]
        public void DoubleBytesRoundTripsExactly()
        {
            var values = new[]
            {
                0.0, -0.0, 1.0, -1.0, 0.1, double.Epsilon,
                double.MaxValue, double.MinValue,
                double.PositiveInfinity, double.NegativeInfinity,
            };
            double[] back = StateCodec.BytesToDoubles(StateCodec.DoubleBytes(values));
            Assert.Equal(values.Length, back.Length);
            for (int i = 0; i < values.Length; i++)
                Assert.Equal(
                    BitConverter.DoubleToInt64Bits(values[i]),
                    BitConverter.DoubleToInt64Bits(back[i]));
        }

        /// <summary>Byte-state families serialize their grid verbatim — no framing.</summary>
        [Fact]
        public void ByteFamiliesSerializeTheGridVerbatim()
        {
            var life = new LifeLike("B3/S23", 16, 16);
            Assert.Equal(life.State.ToArray(), StateCodec.Save(life));
            Assert.Equal(16 * 16, StateCodec.Save(life).Length);

            var merge = new MergeLife(MergeLife.DefaultRule, 16, 16);
            Assert.Equal(16 * 16 * 3, StateCodec.Save(merge).Length); // RGB
        }

        /// <summary>
        /// Elementary saves carry the space-time diagram after the tape: the diagram
        /// is what the user sees and cannot be rebuilt from the tape, so a world saved
        /// without it reopened blank (2026-08-22). Tape-only saves — the layout before
        /// then — still load, with the diagram restarting in the generation's row.
        /// </summary>
        [Fact]
        public void ElementarySavesTheDiagramAndStillLoadsTapeOnlySaves()
        {
            var sim = new Elementary(30, 16, 8);
            sim.Step(5);
            byte[] saved = StateCodec.Save(sim);
            Assert.Equal(16 + 16 * 8, saved.Length);
            Assert.Equal(sim.State.ToArray(), saved.AsSpan(0, 16).ToArray());
            Assert.Equal(sim.Diagram.ToArray(), saved.AsSpan(16).ToArray());

            var restored = new Elementary(30, 16, 8);
            StateCodec.Load(restored, saved, 5);
            Assert.Equal(5, restored.Generation);
            Assert.Equal(sim.State.ToArray(), restored.State.ToArray());
            Assert.Equal(sim.Diagram.ToArray(), restored.Diagram.ToArray());

            // Tape only, at a generation inside the diagram: the tape sits in its row.
            var legacy = new Elementary(30, 16, 8);
            StateCodec.Load(legacy, sim.State.ToArray(), 5);
            Assert.Equal(5, legacy.Generation);
            Assert.Equal(sim.State.ToArray(), legacy.State.ToArray());
            byte[] diagram = legacy.Diagram.ToArray();
            for (int row = 0; row < 8; row++)
            {
                byte[] expected = row == 5 ? sim.State.ToArray() : new byte[16];
                Assert.Equal(expected, diagram.AsSpan(row * 16, 16).ToArray());
            }
            legacy.Step(3);
            restored.Step(3);
            Assert.Equal(restored.State.ToArray(), legacy.State.ToArray());

            // Tape only, past the diagram's height: the tape sits in the last row.
            var scrolled = new Elementary(30, 16, 8);
            StateCodec.Load(scrolled, sim.State.ToArray(), 100);
            Assert.Equal(100, scrolled.Generation);
            Assert.Equal(sim.State.ToArray(), scrolled.Diagram.ToArray().AsSpan(7 * 16, 16).ToArray());

            Assert.Throws<ArgumentException>(
                () => StateCodec.Load(new Elementary(30, 16, 8), new byte[17], 0));
        }

        [Fact]
        public void MalformedInputIsRejected()
        {
            Assert.Throws<ArgumentException>(() => StateCodec.BytesToDoubles(new byte[7]));
            Assert.Throws<ArgumentNullException>(() => StateCodec.BytesToDoubles(null!));
            Assert.Throws<ArgumentNullException>(
                () => StateCodec.Load(new LifeLike("B3/S23", 4, 4), null!, 0));
        }
    }
}
