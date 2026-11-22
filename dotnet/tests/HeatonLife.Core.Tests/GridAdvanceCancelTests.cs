using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Canceling grid Advance Selection and Advance Outside (spec/patterns.md "Canceling"): a
    /// canceled token stops the advance with what a canceled HashLife step throws and leaves the
    /// world exactly as it was; an advance nobody cancels gives the same cells as ever. The Python
    /// suite checks the same with cancel() (python/tests/test_advance_cancel.py).
    /// </summary>
    public class GridAdvanceCancelTests
    {
        private const int X0 = 20, Y0 = 30, X1 = 120, Y1 = 110;

        /// <summary>A grid world seen through what the tests need.</summary>
        private sealed class World
        {
            public World(
                Func<byte[]> state, Func<int> generation, Action<int> step, Action<int> reset,
                Action<int, bool, CancellationToken> advance)
            {
                State = state;
                Generation = generation;
                Step = step;
                Reset = reset;
                Advance = advance;
            }

            public Func<byte[]> State { get; }
            public Func<int> Generation { get; }
            public Action<int> Step { get; }
            public Action<int> Reset { get; }
            public Action<int, bool, CancellationToken> Advance { get; } // n, outside, token
        }

        private static byte[] Soup(int size, double density, uint seed)
        {
            var life = new LifeLike("B3/S23", size, size, Boundary.Dead);
            life.SeedSoup(density, seed);
            return life.State.ToArray();
        }

        private static World Make(string family, int size)
        {
            switch (family)
            {
                case "lifelike":
                    {
                        var life = new LifeLike("B3/S23", size, size);
                        life.SeedSoup(0.35, 11);
                        return new World(
                            () => life.State.ToArray(), () => life.Generation, n => life.Step(n), _ => life.Reset(),
                            (n, outside, token) =>
                            {
                                if (outside)
                                    life.AdvanceOutside(X0, Y0, X1, Y1, n, token);
                                else
                                    life.AdvanceSelection(X0, Y0, X1, Y1, n, token);
                            });
                    }
                case "wireworld":
                    {
                        byte[] a = Soup(size, 0.5, 12), b = Soup(size, 0.5, 13);
                        byte[] states = a.Zip(b, (x, y) => (byte)(x + 2 * y)).ToArray();
                        var wire = new Wireworld(size, size, states, Boundary.Torus);
                        return new World(
                            () => wire.State.ToArray(), () => wire.Generation, n => wire.Step(n), _ => wire.Reset(),
                            (n, outside, token) =>
                            {
                                if (outside)
                                    wire.AdvanceOutside(X0, Y0, X1, Y1, n, token);
                                else
                                    wire.AdvanceSelection(X0, Y0, X1, Y1, n, token);
                            });
                    }
                case "generations":
                    {
                        // Star Wars: births and survival among live cells, dying states between.
                        var generations = new Generations("B2/S345/C4", size, size);
                        generations.SeedSoup(0.35, 15);
                        return new World(
                            () => generations.State.ToArray(), () => generations.Generation, n => generations.Step(n),
                            _ => generations.Reset(),
                            (n, outside, token) =>
                            {
                                if (outside)
                                    generations.AdvanceOutside(X0, Y0, X1, Y1, n, token);
                                else
                                    generations.AdvanceSelection(X0, Y0, X1, Y1, n, token);
                            });
                    }
                default:
                    {
                        var cyclic = new Cyclic(8, size, size, threshold: 2, reach: 2);
                        cyclic.SeedSoup(14);
                        return new World(
                            () => cyclic.State.ToArray(), () => cyclic.Generation, n => cyclic.Step(n), _ => cyclic.Reset(),
                            (n, outside, token) =>
                            {
                                if (outside)
                                    cyclic.AdvanceOutside(X0, Y0, X1, Y1, n, token);
                                else
                                    cyclic.AdvanceSelection(X0, Y0, X1, Y1, n, token);
                            });
                    }
            }
        }

        public static IEnumerable<object[]> Cases()
        {
            foreach (string family in new[] { "lifelike", "wireworld", "cyclic", "generations" })
            {
                yield return new object[] { family, false };
                yield return new object[] { family, true };
            }
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void ATokenCanceledBeforeTheCallLeavesTheWorldAsItWas(string family, bool outside)
        {
            World world = Make(family, 160);
            world.Step(3);
            byte[] before = world.State();
            using var source = new CancellationTokenSource();
            source.Cancel();
            OperationCanceledException e = Assert.Throws<OperationCanceledException>(
                () => world.Advance(5, outside, source.Token));
            Assert.Equal(source.Token, e.CancellationToken);
            Assert.Equal(before, world.State());
            Assert.Equal(3, world.Generation());
            // As HashLife's step: an advance of 0 generations runs nothing and checks nothing.
            world.Advance(0, outside, source.Token);
            Assert.Equal(before, world.State());
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void ACancelFromAnotherThreadMidwayLeavesTheWorldAsItWas(string family, bool outside)
        {
            World world = Make(family, 512);
            byte[] start = world.State();
            world.Step(2);
            byte[] before = world.State();
            using var source = new CancellationTokenSource();
            source.CancelAfter(TimeSpan.FromMilliseconds(150)); // a timer thread cancels it
            var clock = Stopwatch.StartNew();
            Assert.Throws<OperationCanceledException>(() => world.Advance(1_000_000_000, outside, source.Token));
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(30), $"took {clock.Elapsed} to stop");
            Assert.Equal(before, world.State());
            Assert.Equal(2, world.Generation());
            world.Reset(0); // the start is untouched too
            Assert.Equal(start, world.State());
        }

        [Fact]
        public void ABigGridStopsWithinAGeneration()
        {
            // One generation of a 2048-square cyclic grid of reach 3 is far longer than the wait:
            // the step polls its token each row, so the advance stops inside the first generation.
            var cyclic = new Cyclic(8, 2048, 2048, threshold: 3, reach: 3);
            cyclic.SeedSoup(5);
            byte[] before = cyclic.State.ToArray();
            using var source = new CancellationTokenSource();
            source.CancelAfter(TimeSpan.FromMilliseconds(20));
            var clock = Stopwatch.StartNew();
            Assert.Throws<OperationCanceledException>(
                () => cyclic.AdvanceSelection(0, 0, 2047, 2047, 1_000, source.Token));
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(30), $"took {clock.Elapsed} to stop");
            Assert.Equal(before, cyclic.State.ToArray());
            Assert.Equal(0, cyclic.Generation);
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void AnUncanceledAdvanceIsUnchanged(string family, bool outside)
        {
            World plain = Make(family, 160), tokened = Make(family, 160);
            using var source = new CancellationTokenSource(); // never canceled
            plain.Advance(7, outside, default);
            tokened.Advance(7, outside, source.Token);
            Assert.Equal(plain.State(), tokened.State());
            Assert.Equal(0, tokened.Generation());
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void AfterACancelTheNextAdvanceRunsAsEver(string family, bool outside)
        {
            World canceled = Make(family, 160), fresh = Make(family, 160);
            using (var source = new CancellationTokenSource())
            {
                source.Cancel();
                Assert.Throws<OperationCanceledException>(() => canceled.Advance(4, outside, source.Token));
            }
            canceled.Advance(4, outside, default);
            fresh.Advance(4, outside, default);
            Assert.Equal(fresh.State(), canceled.State());
        }

        [Fact]
        public void HashLifeThrowsTheSame()
        {
            // The grids mirror the unbounded universe: the same exception, the world as it was.
            var universe = new HashLife();
            universe.FillRandom(-20, -20, 19, 19, 0.4, 3);
            string before = universe.ToMacrocell();
            using var source = new CancellationTokenSource();
            source.Cancel();
            Assert.Throws<OperationCanceledException>(() => universe.AdvanceSelection(-5, -5, 5, 5, 10, source.Token));
            Assert.Equal(before, universe.ToMacrocell());
        }
    }
}
