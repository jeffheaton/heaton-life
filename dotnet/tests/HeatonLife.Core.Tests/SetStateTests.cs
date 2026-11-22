using System;
using System.Linq;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// A world's state and its start (spec/README.md): SetState and StateCodec.Load on every
    /// family that keeps a start. By default the state becomes the start Reset returns to; with
    /// keepStart the start stays, so a host showing a saved frame or an undo point leaves Reset
    /// alone and allocates nothing. The Python reference's test_set_state.py.
    /// </summary>
    public class SetStateTests
    {
        private static ISimulation[] AllFamilies()
        {
            var life = new LifeLike("B3/S23", 16, 12);
            life.SeedSoup(0.35, 3);
            var elementary = new Elementary(30, 16, 8);
            elementary.SeedSoup(0.5, 5);
            return new ISimulation[]
            {
                life,
                elementary,
                new Cyclic(5, 16, 12),
                new Wireworld(16, 12),
                new MergeLife(MergeLife.DefaultRule, 16, 12),
                new GrayScott(16, 12),
                new ClassicLenia(32, 32, radius: 8),
                new AsymptoticLenia(32, 32, radius: 8),
                new FlowLenia(32, 32, radius: 8),
                new Boids(8, 64, 64),
            };
        }

        /// <summary>The state alone: an Elementary save's tape, without its diagram.</summary>
        private static byte[] StateOf(ISimulation sim)
        {
            byte[] saved = StateCodec.Save(sim);
            return sim is Elementary elementary ? saved.Take(elementary.Width).ToArray() : saved;
        }

        [Fact]
        public void KeepStartMovesTheWorldButNotItsStart()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                string name = sim.GetType().Name;
                byte[] born = StateCodec.Save(sim);
                sim.Step(3);
                byte[] later = StateCodec.Save(sim);
                Assert.False(born.SequenceEqual(later), name);
                sim.Reset();
                StateCodec.Load(sim, later, 9, keepStart: true);
                Assert.True(StateCodec.Save(sim).SequenceEqual(later), name);
                Assert.Equal(9, sim.Generation);
                sim.Reset();
                Assert.True(StateCodec.Save(sim).SequenceEqual(born), $"{name}: Reset must go to the start it had");
                Assert.Equal(0, sim.Generation);
            }
        }

        [Fact]
        public void ByDefaultTheStateBecomesTheStart()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                string name = sim.GetType().Name;
                byte[] born = StateCodec.Save(sim);
                sim.Step(3);
                byte[] later = StateCodec.Save(sim);
                StateCodec.Load(sim, later, 4);
                Assert.Equal(4, sim.Generation);
                byte[] laterState = StateOf(sim);
                StateCodec.Load(sim, born, 7, keepStart: true); // moving it again keeps the new start
                sim.Reset();
                Assert.True(StateOf(sim).SequenceEqual(laterState), name);
                Assert.Equal(0, sim.Generation);
            }
        }

        [Fact]
        public void ShowingAFrameAllocatesNothing()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                sim.Step(2);
                byte[] frame = StateCodec.Save(sim);
                StateCodec.Load(sim, frame, 2, keepStart: true); // warm up
                long before = GC.GetAllocatedBytesForCurrentThread();
                for (int i = 0; i < 10; i++)
                    StateCodec.Load(sim, frame, 2 + i, keepStart: true);
                long allocated = GC.GetAllocatedBytesForCurrentThread() - before;
                Assert.True(allocated == 0, $"{sim.GetType().Name} allocated {allocated} bytes showing ten frames");
            }
        }

        [Fact]
        public void TheWrongSizeChangesNothing()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                sim.Step(2);
                byte[] before = StateCodec.Save(sim);
                var wrong = new byte[before.Length + 8];
                foreach (bool keepStart in new[] { false, true })
                {
                    Assert.ThrowsAny<ArgumentException>(() => StateCodec.Load(sim, wrong, 5, keepStart));
                    Assert.True(StateCodec.Save(sim).SequenceEqual(before), sim.GetType().Name);
                    Assert.Equal(2, sim.Generation);
                }
            }
        }

        [Fact]
        public void ValuesTheInitRefusesChangeNothing()
        {
            var wire = new Wireworld(12, 12);
            byte[] before = wire.State.ToArray();
            byte[] bad = (byte[])before.Clone();
            bad[bad.Length - 1] = 4; // the last cell, after every good one
            foreach (bool keepStart in new[] { false, true })
            {
                Assert.Throws<ArgumentException>(() => wire.SetState(bad, 0, keepStart));
                Assert.True(wire.State.SequenceEqual(before));
            }
            var cyclic = new Cyclic(4, 8, 6);
            before = cyclic.State.ToArray();
            bad = (byte[])before.Clone();
            bad[bad.Length - 1] = 4;
            foreach (bool keepStart in new[] { false, true })
            {
                Assert.Throws<ArgumentException>(() => cyclic.SetState(bad, 0, keepStart));
                Assert.True(cyclic.State.SequenceEqual(before));
            }
            var life = new LifeLike("B3/S23", 8, 6);
            life.SetState(Enumerable.Repeat((byte)7, 48).ToArray(), 0, keepStart: true);
            Assert.True(life.State.ToArray().All(c => c == 1)); // nonzero is alive
        }

        [Fact]
        public void ElementaryTakesItsDiagramOrRestartsIt()
        {
            var sim = new Elementary(90, 16, 8);
            sim.Step(5);
            byte[] tape = sim.State.ToArray(), diagram = sim.Diagram.ToArray();
            sim.Reset();
            sim.SetState(tape, diagram, 5, keepStart: true);
            Assert.True(sim.Diagram.SequenceEqual(diagram));
            sim.SetState(tape, 5, keepStart: true); // the tape alone: in row 5, the rest blank
            Assert.True(sim.Diagram.Slice(5 * 16, 16).SequenceEqual(tape));
            Assert.Equal(tape.Sum(c => c), sim.Diagram.ToArray().Sum(c => c));
            sim.SetState(tape, 40, keepStart: true); // past the last row: in the last row
            Assert.True(sim.Diagram.Slice(7 * 16, 16).SequenceEqual(tape));
            sim.Reset();
            Assert.Equal(0, sim.Generation);
            Assert.Equal(1, sim.State.ToArray().Sum(c => c)); // the single cell it was born with
            Assert.Throws<ArgumentException>(() => sim.SetState(tape, new byte[3 * 16], 0, keepStart: true));
        }
    }
}
