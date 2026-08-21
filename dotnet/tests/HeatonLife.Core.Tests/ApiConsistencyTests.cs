using System;
using System.Collections.Generic;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>The Unity-facing API contract: interfaces, ctor defaults, RGBA paths.</summary>
    public class ApiConsistencyTests
    {
        /// <summary>Every family, built at its constructor defaults.</summary>
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

        /// <summary>A family's frame, read polymorphically, as comparable bytes.</summary>
        private static byte[] FrameBytes(ISimulation sim)
        {
            switch (sim)
            {
                case IIndexedFrameSource indexed:
                {
                    var frame = new byte[sim.Width * sim.Height];
                    indexed.WriteFrame(frame);
                    return frame;
                }
                case IRgbFrameSource rgb:
                {
                    var frame = new byte[sim.Width * sim.Height * 3];
                    rgb.WriteFrame(frame);
                    return frame;
                }
                case IFloatFrameSource floats:
                {
                    var frame = new double[sim.Width * sim.Height];
                    floats.WriteFrame(frame);
                    var bytes = new byte[frame.Length * 8];
                    Buffer.BlockCopy(frame, 0, bytes, 0, bytes.Length);
                    return bytes;
                }
                default:
                    throw new InvalidOperationException($"{sim.GetType().Name} has no frame interface");
            }
        }

        /// <summary>
        /// Reset is the counterpart of the Python protocol's reset(seed=None)
        /// (core/protocols.py). Before it existed a host could not re-seed a world
        /// through ISimulation at all and had to switch on the concrete family.
        /// The contract: replay the stored init exactly, and put Generation back to 0.
        /// </summary>
        [Fact]
        public void EveryFamilyReplaysItsInitThroughTheInterface()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                string name = sim.GetType().Name;
                byte[] born = FrameBytes(sim);
                Assert.Equal(0, sim.Generation);

                sim.Step(5);
                Assert.Equal(5, sim.Generation);

                sim.Reset();
                Assert.Equal(0, sim.Generation);
                Assert.True(
                    FrameBytes(sim).AsSpan().SequenceEqual(born),
                    $"{name}: Reset() must reproduce the world it was born with");

                // And it is repeatable, not a one-shot restore.
                sim.Step(3);
                sim.Reset();
                Assert.Equal(0, sim.Generation);
                Assert.True(FrameBytes(sim).AsSpan().SequenceEqual(born), $"{name}: second Reset()");
            }
        }

        /// <summary>
        /// Reset(seed) replays the same STRATEGY under a new seed. Families whose
        /// init consumes no draws (Wireworld's clock, Elementary's single cell) are
        /// seed-independent by spec, so for them a new seed must change nothing.
        /// </summary>
        [Fact]
        public void ResetWithASeedRerollsOnlyTheSeededFamilies()
        {
            foreach (ISimulation sim in AllFamilies())
            {
                string name = sim.GetType().Name;
                byte[] born = FrameBytes(sim);
                sim.Reset(4242);
                Assert.Equal(0, sim.Generation);
                bool changed = !FrameBytes(sim).AsSpan().SequenceEqual(born);

                bool seedFree = sim is Wireworld || sim is Elementary;
                if (seedFree)
                    Assert.False(changed, $"{name}: init consumes no draws, so a seed cannot matter");
                else
                    Assert.True(changed, $"{name}: a new seed must reroll a seeded init");

                // Re-seeding is deterministic: the same seed twice gives the same world.
                byte[] first = FrameBytes(sim);
                sim.Step(2);
                sim.Reset(4242);
                Assert.True(FrameBytes(sim).AsSpan().SequenceEqual(first), $"{name}: reseed determinism");
            }
        }

        /// <summary>
        /// A world restored from an explicit grid replays THAT grid and ignores the
        /// seed — the reference's "array" init (python ca/lifelike.py reset()).
        /// </summary>
        [Fact]
        public void ResetAfterSetStateReplaysTheLoadedGrid()
        {
            var sim = new LifeLike("B3/S23", 8, 8);
            var glider = new byte[64];
            glider[0 * 8 + 1] = 1;
            glider[1 * 8 + 2] = 1;
            glider[2 * 8 + 0] = glider[2 * 8 + 1] = glider[2 * 8 + 2] = 1;
            sim.SetState(glider);

            sim.Step(7);
            Assert.NotEqual(glider, sim.State.ToArray());

            sim.Reset();
            Assert.Equal(glider, sim.State.ToArray());
            Assert.Equal(0, sim.Generation);

            // Even with a seed: an explicit grid is not re-randomised.
            sim.Step(3);
            sim.Reset(777);
            Assert.Equal(glider, sim.State.ToArray());
        }

        /// <summary>
        /// Density is a probability, and the reference rejects anything outside
        /// [0, 1] (python init/seeding.py). C# used to cast it straight through: 1.5
        /// filled every cell and a negative density became an unchecked
        /// double-to-ulong conversion, so you got a silently degenerate world where
        /// Python raised.
        /// </summary>
        [Theory]
        [InlineData(1.5)]
        [InlineData(-0.1)]
        [InlineData(double.NaN)]
        [InlineData(double.PositiveInfinity)]
        public void SeedingRejectsADensityOutsideZeroToOne(double density)
        {
            var life = new LifeLike("B3/S23", 8, 8);
            Assert.Throws<ArgumentOutOfRangeException>(() => life.SeedSoup(density, 0));
            Assert.Throws<ArgumentOutOfRangeException>(() => life.SeedBlob(density, 0));
        }

        [Theory]
        [InlineData(0.0)]
        [InlineData(0.35)]
        [InlineData(1.0)]
        public void SeedingAcceptsTheWholeClosedInterval(double density)
        {
            var life = new LifeLike("B3/S23", 8, 8);
            life.SeedSoup(density, 0);
            life.SeedBlob(density, 0);
        }

        [Fact]
        public void EveryFamilyImplementsItsFrameInterface()
        {
            var sims = new ISimulation[]
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
            foreach (var sim in sims)
            {
                // Polymorphic drive: step, then produce a frame through the interface.
                sim.Step();
                Assert.True(sim.Generation >= 1);
                switch (sim)
                {
                    case IIndexedFrameSource indexed:
                    {
                        var frame = new byte[sim.Width * sim.Height];
                        indexed.WriteFrame(frame);
                        break;
                    }
                    case IRgbFrameSource rgb:
                    {
                        var frame = new byte[sim.Width * sim.Height * 3];
                        rgb.WriteFrame(frame);
                        break;
                    }
                    case IFloatFrameSource floats:
                    {
                        var frame = new double[sim.Width * sim.Height];
                        floats.WriteFrame(frame);
                        foreach (double v in frame)
                            Assert.True(v >= 0.0 && v <= 1.0);
                        break;
                    }
                    default:
                        Assert.Fail($"{sim.GetType().Name} implements no frame interface");
                        break;
                }
            }
            Assert.IsAssignableFrom<IIndexedFrameSource>(sims[0]);
            Assert.IsAssignableFrom<IRgbFrameSource>(sims[4]);
            Assert.IsAssignableFrom<IFloatFrameSource>(sims[5]);
        }

        [Fact]
        public void ConstructorsMatchPythonDefaultInits()
        {
            // Every constructor yields the Python default init for its family.
            var lifelike = new LifeLike("B3/S23", 24, 24);
            var lifelikeExplicit = new LifeLike("B3/S23", 24, 24);
            lifelikeExplicit.SeedSoup(0.35, 0);
            Assert.Equal(lifelikeExplicit.State.ToArray(), lifelike.State.ToArray());

            var cyclic = new Cyclic(14, 24, 24);
            var cyclicExplicit = new Cyclic(14, 24, 24);
            cyclicExplicit.SeedSoup(0);
            Assert.Equal(cyclicExplicit.State.ToArray(), cyclic.State.ToArray());

            var mergelife = new MergeLife(MergeLife.DefaultRule, 24, 24);
            var mergelifeExplicit = new MergeLife(MergeLife.DefaultRule, 24, 24);
            mergelifeExplicit.SeedSoup(0);
            Assert.Equal(mergelifeExplicit.State.ToArray(), mergelife.State.ToArray());

            var grayscott = new GrayScott(24, 24);
            var grayscottExplicit = new GrayScott(24, 24);
            grayscottExplicit.SeedSpots(20, 0); // Python default is spots, not center
            Assert.Equal(grayscottExplicit.State.ToArray(), grayscott.State.ToArray());
        }

        [Fact]
        public void SetCellPaintsWithoutResettingGeneration()
        {
            var sim = new LifeLike("B3/S23", 16, 16);
            sim.Step(5);
            Assert.Equal(5, sim.Generation);
            sim.SetCell(3, 4, 1);
            Assert.Equal(5, sim.Generation); // painting must not reset the run
            Assert.Equal(1, sim.State[4 * 16 + 3]);
            sim.SetCell(3, 4, 0);
            Assert.Equal(0, sim.State[4 * 16 + 3]);

            var boids = new Boids(4, 64, 64);
            boids.Step(2);
            boids.SetBoid(1, 10.0, 20.0, 1.5, -0.5);
            Assert.Equal(2, boids.Generation);
            Assert.Equal(10.0, boids.State[1 * 4 + 0]);
            Assert.Equal(-0.5, boids.State[1 * 4 + 3]);
        }

        [Fact]
        public void RgbaOverloadsAddOpaqueAlpha()
        {
            byte[] lut = Colormaps.Get("ice");
            var frame = new double[] { 0.0, 0.25, 0.5, 1.0 };
            byte[] rgb = Colormaps.ApplyFloat(frame, lut);
            var rgba = new byte[16];
            Colormaps.ApplyFloatRgba(frame, lut, rgba);
            for (int i = 0; i < 4; i++)
            {
                Assert.Equal(rgb[i * 3], rgba[i * 4]);
                Assert.Equal(rgb[i * 3 + 1], rgba[i * 4 + 1]);
                Assert.Equal(rgb[i * 3 + 2], rgba[i * 4 + 2]);
                Assert.Equal(255, rgba[i * 4 + 3]);
            }

            var indexFrame = new byte[] { 0, 85, 170, 255 };
            var rgba2 = new byte[16];
            Colormaps.ApplyIndexedRgba(indexFrame, lut, rgba2);
            byte[] rgb2 = Colormaps.ApplyIndexed(indexFrame, lut);
            var rgba3 = new byte[16];
            Colormaps.RgbToRgba(rgb2, rgba3);
            Assert.Equal(rgba3, rgba2);
        }

        [Theory]
        [InlineData("B3/S23", "B3/S23")]
        [InlineData("b3/s23", "B3/S23")]
        [InlineData("  B36 / S23 ", "B36/S23")]
        [InlineData("B62/S823", "B26/S238")] // canonical sorts digits
        [InlineData("B/S", "B/S")]
        public void RuleStringCanonicalizes(string input, string expected)
        {
            Assert.Equal(expected, RuleString.Canonical(input));
        }

        [Theory]
        [InlineData("B3S23")]
        [InlineData("3/23")]
        [InlineData("B9/S2")]
        [InlineData("B3/S23x")]
        [InlineData("")]
        public void RuleStringRejectsInvalid(string bad)
        {
            Assert.Throws<ArgumentException>(() => RuleString.Parse(bad));
        }

        [Fact]
        public void IntoBufferFractalOverloadsMatchAllocating()
        {
            var field = new Mandelbrot(200);
            var vp = new Viewport("-0.5", "0.0", 0.0);
            int[] allocated = field.Iterations(32, 32, vp);
            var buffer = new int[32 * 32];
            field.Iterations(32, 32, vp, buffer);
            Assert.Equal(allocated, buffer);

            var newton = new Newton(3, 60);
            var (roots, iters) = newton.Basins(32, 32, vp);
            var rootsBuf = new int[32 * 32];
            var itersBuf = new int[32 * 32];
            newton.Basins(32, 32, vp, rootsBuf, itersBuf);
            Assert.Equal(roots, rootsBuf);
            Assert.Equal(iters, itersBuf);
        }

        [Fact]
        public void RenderIsInUnitRangeWithBlackInterior()
        {
            var field = new Julia();
            var (render, counts) = field.RenderAndCounts(48, 48, new Viewport("0.0", "0.0", 0.0));
            var seen = new List<double>();
            for (int i = 0; i < render.Length; i++)
            {
                Assert.True(render[i] >= 0.0 && render[i] <= 1.0);
                if (counts[i] < 0)
                    Assert.Equal(0.0, render[i]); // interior stays black
                else
                    seen.Add(render[i]);
            }
            Assert.True(seen.Count > 0);
        }
    }
}
