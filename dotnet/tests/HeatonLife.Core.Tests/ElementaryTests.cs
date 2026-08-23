using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class ElementaryTests
    {
        [Fact]
        public void Rule110FirstStepFromSingle()
        {
            var sim = new Elementary(110, 11, 8);
            const int c = 5;
            sim.Step();
            var expected = new byte[11];
            expected[c - 1] = 1; // (0,0,1) -> bit 1 of 110 -> 1
            expected[c] = 1; // (0,1,0) -> bit 2 of 110 -> 1
            // (1,0,0) -> bit 4 of 110 -> 0
            Assert.Equal(expected, sim.State.ToArray());
        }

        [Fact]
        public void Rule90IsXorOfNeighbors()
        {
            var sim = new Elementary(90, 64, 8);
            sim.SeedSoup(0.5, 3);
            byte[] tape = sim.State.ToArray();
            sim.Step();
            var expected = new byte[64];
            for (int i = 0; i < 64; i++)
                expected[i] = (byte)(tape[(i - 1 + 64) % 64] ^ tape[(i + 1) % 64]);
            Assert.Equal(expected, sim.State.ToArray());
        }

        [Fact]
        public void Rule254FillsWithDeadBoundary()
        {
            var sim = new Elementary(254, 9, 8, Boundary.Dead);
            sim.Step(4); // spreads one cell per side per step
            foreach (byte cell in sim.State)
                Assert.Equal(1, cell);
        }

        [Fact]
        public void TorusWraps()
        {
            var sim = new Elementary(254, 8, 8); // 254: any live neighbor -> alive
            var tape = new byte[8];
            tape[0] = 1;
            sim.SetState(tape);
            sim.Step();
            Assert.Equal(1, sim.State[7]); // wrapped around the left edge
        }

        [Fact]
        public void DiagramRecordsHistoryThenScrolls()
        {
            var sim = new Elementary(30, 16, 4);
            sim.Step(2);
            byte[] diagram = sim.Diagram.ToArray();
            Assert.True(RowAny(diagram, 0) && RowAny(diagram, 2));
            Assert.False(RowAny(diagram, 3)); // not yet reached
            byte[] row2 = Row(diagram, 2);
            sim.Step(1); // fills last row
            sim.Step(1); // forces scroll
            diagram = sim.Diagram.ToArray();
            Assert.Equal(row2, Row(diagram, 1)); // scrolled up by one
        }

        /// <summary>
        /// A tape restored together with its diagram is the same world the diagram
        /// came from — it shows the same picture, steps on identically, and Reset
        /// replays the tape from a fresh diagram like the tape-only restore does.
        /// </summary>
        [Fact]
        public void SetStateWithDiagramRestoresThePicture()
        {
            var sim = new Elementary(110, 16, 8);
            sim.Step(12); // past the diagram's height: it has scrolled
            byte[] tape = sim.State.ToArray();
            byte[] diagram = sim.Diagram.ToArray();

            var restored = new Elementary(110, 16, 8);
            restored.SetState(tape, diagram, 12);
            Assert.Equal(12, restored.Generation);
            Assert.Equal(tape, restored.State.ToArray());
            Assert.Equal(diagram, restored.Diagram.ToArray());

            sim.Step(2);
            restored.Step(2);
            Assert.Equal(sim.Diagram.ToArray(), restored.Diagram.ToArray());

            restored.Reset();
            Assert.Equal(0, restored.Generation);
            Assert.Equal(tape, restored.State.ToArray());
            Assert.Equal(tape, restored.Diagram.ToArray().AsSpan(0, 16).ToArray());

            Assert.Throws<ArgumentException>(() => restored.SetState(tape, new byte[3], 0));
        }

        [Fact]
        public void SoupSeedingIsDeterministic()
        {
            var a = new Elementary(110, 64, 16);
            var b = new Elementary(110, 64, 16);
            a.SeedSoup(0.5, 9);
            b.SeedSoup(0.5, 9);
            a.Step(20);
            b.Step(20);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
            Assert.Equal(20, a.Generation);
            a.SeedSoup(0.5, 9); // reseeding resets to the same initial tape
            Assert.Equal(0, a.Generation);
            b.SeedSoup(0.5, 9);
            Assert.Equal(b.State.ToArray(), a.State.ToArray());
        }

        private static byte[] Row(byte[] diagram, int row)
        {
            var result = new byte[16];
            System.Array.Copy(diagram, row * 16, result, 0, 16);
            return result;
        }

        private static bool RowAny(byte[] diagram, int row)
        {
            for (int x = 0; x < 16; x++)
                if (diagram[row * 16 + x] != 0)
                    return true;
            return false;
        }
    }
}
