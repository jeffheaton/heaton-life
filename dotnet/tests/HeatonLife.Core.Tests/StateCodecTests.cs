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
