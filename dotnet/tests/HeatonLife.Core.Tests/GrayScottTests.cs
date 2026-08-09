using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class GrayScottTests
    {
        [Fact]
        public void HomogeneousSteadyStateIsExactFixedPoint()
        {
            var sim = new GrayScott(16, 16);
            var state = new double[2 * 16 * 16];
            for (int i = 0; i < 16 * 16; i++)
                state[i] = 1.0; // U=1, V=0
            sim.SetState(state);
            sim.Step(10);
            Assert.Equal(state, sim.State.ToArray()); // bitwise: no reaction, no diffusion
        }

        [Fact]
        public void CenterInitKeepsSymmetry()
        {
            var sim = new GrayScott(65, 65, feed: 0.0367, kill: 0.0649);
            sim.SeedCenter();
            sim.Step(50);
            int w = 65, h = 65, cells = w * h;
            var state = sim.State;
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                {
                    double v = state[cells + y * w + x];
                    Assert.True(Math.Abs(v - state[cells + (h - 1 - y) * w + x]) < 1e-12);
                    Assert.True(Math.Abs(v - state[cells + y * w + (w - 1 - x)]) < 1e-12);
                    Assert.True(Math.Abs(v - state[cells + x * w + y]) < 1e-12); // transpose
                }
        }

        [Fact]
        public void MitosisFormsPatternAndStaysBounded()
        {
            var sim = new GrayScott(64, 64, feed: 0.0367, kill: 0.0649);
            sim.SeedSpots(20, 3);
            sim.Step(800);
            int cells = 64 * 64;
            double vSum = 0, vSumSq = 0;
            for (int i = 0; i < cells; i++)
            {
                double u = sim.State[i];
                double v = sim.State[cells + i];
                Assert.True(double.IsFinite(u) && double.IsFinite(v));
                Assert.True(u >= 0.0 && u <= 1.05);
                Assert.True(v >= 0.0 && v <= 1.0);
                vSum += v;
                vSumSq += v * v;
            }
            double mean = vSum / cells;
            double std = Math.Sqrt(vSumSq / cells - mean * mean);
            Assert.True(std > 0.01, "mitosis should form spatial structure");
        }

        [Fact]
        public void SpotsSeedingIsDeterministic()
        {
            var a = new GrayScott(48, 48);
            var b = new GrayScott(48, 48);
            a.SeedSpots(20, 5);
            b.SeedSpots(20, 5);
            a.Step(100);
            b.Step(100);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
            Assert.Equal(100, a.Generation);
            a.SeedSpots(20, 5);
            Assert.Equal(0, a.Generation);
            var fresh = new GrayScott(48, 48);
            fresh.SeedSpots(20, 5);
            Assert.Equal(fresh.State.ToArray(), a.State.ToArray());
        }

        [Fact]
        public void PresetsAllInRange()
        {
            foreach (var (name, fk) in GrayScott.Presets)
            {
                Assert.True(fk.Feed > 0.0 && fk.Feed < 0.12, name);
                Assert.True(fk.Kill > 0.0 && fk.Kill < 0.08, name);
            }
        }
    }
}
