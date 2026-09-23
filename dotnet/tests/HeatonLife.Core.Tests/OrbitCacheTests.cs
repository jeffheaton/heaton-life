using System;
using System.Threading;
using System.Threading.Tasks;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>Tests that assert what the process-wide orbit cache holds run alone.</summary>
    [CollectionDefinition("orbit cache", DisableParallelization = true)]
    public class OrbitCacheCollection
    {
    }

    /// <summary>
    /// The orbit cache and the host knobs that ride on it (spec/deep-zoom.md "Caching &amp;
    /// interactivity"): a cached orbit answers shorter requests as a prefix and longer
    /// ones by resuming from its exact state — both identical to computing afresh —
    /// eviction is least recently used under an entry and a byte cap, and a canceled
    /// orbit is never cached. RenderProgress shows whether an orbit ran at all, which is
    /// how these tests tell a hit from a recomputation.
    /// </summary>
    [Collection("orbit cache")]
    public class OrbitCacheTests
    {
        private const string SeahorseRe = "-0.743643887037158704752191506114774";
        private const string SeahorseIm = "0.131825904205311970493132056385139";
        private const string BetaRe = "1.27658194945592591790467276337476";
        private const string BetaIm = "-0.47966605489732779175475867397901";

        private static (double[] Re, double[] Im) Cached(
            ReferenceOrbit.Kind kind, string re, string im, double zoom, int maxIter,
            double cRe, double cIm, RenderProgress? progress = null, CancellationToken token = default)
            => ReferenceOrbit.Compute(kind, re, im, zoom, maxIter, cRe, cIm, progress, token);

        private static void AssertSameOrbit((double[] Re, double[] Im) expected, (double[] Re, double[] Im) actual)
        {
            Assert.Equal(expected.Re.Length, actual.Re.Length);
            for (int i = 0; i < expected.Re.Length; i++)
            {
                Assert.Equal(BitConverter.DoubleToInt64Bits(expected.Re[i]), BitConverter.DoubleToInt64Bits(actual.Re[i]));
                Assert.Equal(BitConverter.DoubleToInt64Bits(expected.Im[i]), BitConverter.DoubleToInt64Bits(actual.Im[i]));
            }
        }

        [Theory]
        [InlineData(0, SeahorseRe, SeahorseIm, 20.0, 0.0, 0.0)]            // Mandelbrot
        [InlineData(1, "0.1", "0.2", 13.0, -0.123, 0.745)]                  // Julia, off-center reference
        [InlineData(1, "0", "0", 13.0, -0.123, 0.745)]                      // Julia's critical orbit
        [InlineData(2, "-1.75", "-0.0000001", 15.0, 0.0, 0.0)]              // Burning Ship
        public void PrefixAndResumeMatchFreshOrbits(
            int kindIndex, string re, string im, double zoom, double cRe, double cIm)
        {
            var kind = (ReferenceOrbit.Kind)kindIndex;
            ReferenceOrbit.ClearCache();
            var freshShort = ReferenceOrbit.ComputeUncached(kind, re, im, zoom, 700, cRe, cIm, false);
            var freshLong = ReferenceOrbit.ComputeUncached(kind, re, im, zoom, 3000, cRe, cIm, false);
            Assert.Equal(701, freshShort.Re.Length);                   // premise: nothing escapes early
            Assert.Equal(3001, freshLong.Re.Length);

            // Short first, then long: the long one resumes where the short one stopped.
            AssertSameOrbit(freshShort, Cached(kind, re, im, zoom, 700, cRe, cIm));
            var resumed = new RenderProgress();
            AssertSameOrbit(freshLong, Cached(kind, re, im, zoom, 3000, cRe, cIm, resumed));
            Assert.Equal(3000 - 700, resumed.OrbitTotal);             // resumed, not recomputed

            // Now shorter again: a prefix of the cached orbit, no orbit work at all.
            var prefix = new RenderProgress();
            AssertSameOrbit(freshShort, Cached(kind, re, im, zoom, 700, cRe, cIm, prefix));
            Assert.Equal(RenderPhase.NotStarted, prefix.Phase);
        }

        [Fact]
        public void AnEscapedOrbitAnswersEveryLongerRequest()
        {
            ReferenceOrbit.ClearCache();
            var first = Cached(ReferenceOrbit.Kind.Mandelbrot, "2.0", "2.0", 13.0, 50, 0.0, 0.0);
            Assert.True(first.Re.Length < 50);
            var progress = new RenderProgress();
            var again = Cached(ReferenceOrbit.Kind.Mandelbrot, "2.0", "2.0", 13.0, 100000, 0.0, 0.0, progress);
            Assert.Same(first.Re, again.Re);
            Assert.Equal(RenderPhase.NotStarted, progress.Phase);
        }

        /// <summary>True when the orbit came from the cache (no orbit phase ran).</summary>
        private static bool IsHit(string re)
        {
            var progress = new RenderProgress();
            Cached(ReferenceOrbit.Kind.Mandelbrot, re, "0.1", 13.0, 100, 0.0, 0.0, progress);
            return progress.Phase == RenderPhase.NotStarted;
        }

        [Fact]
        public void EvictionIsLeastRecentlyUsedUnderBothCaps()
        {
            ReferenceOrbit.ClearCache();
            long limit = ReferenceOrbit.CacheByteLimit;
            try
            {
                // Centers inside the main cardioid: every orbit runs its full 101 samples.
                string Center(int i) => "-0.1" + i.ToString(System.Globalization.CultureInfo.InvariantCulture);
                for (int i = 0; i < 9; i++)
                {
                    Assert.Equal(101, Cached(ReferenceOrbit.Kind.Mandelbrot, Center(i), "0.1", 13.0, 100, 0.0, 0.0).Re.Length);
                    if (i > 0)
                        Assert.True(IsHit(Center(0)));                // keeps orbit 0 the most recently used
                }
                Assert.Equal(8, ReferenceOrbit.CacheUsage.Count);     // orbit 1, the oldest untouched, went
                Assert.False(IsHit(Center(1)));

                // A byte cap below one orbit still keeps the two most recent (a Julia frame's pair).
                ReferenceOrbit.CacheByteLimit = 0;
                Assert.Equal(2, ReferenceOrbit.CacheUsage.Count);

                // Room for exactly three: the three newest stay, the oldest goes.
                ReferenceOrbit.CacheByteLimit = 101 * 16 * 3;
                ReferenceOrbit.ClearCache();
                for (int i = 0; i < 4; i++)
                    Cached(ReferenceOrbit.Kind.Mandelbrot, "-0.2" + i, "0.1", 13.0, 100, 0.0, 0.0);
                Assert.Equal((3, 101L * 16 * 3), ReferenceOrbit.CacheUsage);
                Assert.True(IsHit("-0.23") && IsHit("-0.22") && IsHit("-0.21"));
                Assert.False(IsHit("-0.20"));
            }
            finally
            {
                ReferenceOrbit.CacheByteLimit = limit;
                ReferenceOrbit.ClearCache();
            }
        }

        /// <summary>Cancel <paramref name="action"/> once <paramref name="started"/> says it is under way.</summary>
        private static async Task ExpectCanceledOnce(Func<bool> started, Action<CancellationToken> action)
        {
            using var cancel = new CancellationTokenSource();
            var watcher = Task.Run(() =>
            {
                while (!started())
                    Thread.Yield();
                cancel.Cancel();
            });
            Assert.ThrowsAny<OperationCanceledException>(() => action(cancel.Token));
            await watcher;
        }

        [Fact]
        public async Task ACanceledOrbitIsNeverCached()
        {
            ReferenceOrbit.ClearCache();
            using var cancel = new CancellationTokenSource();
            cancel.Cancel();
            Assert.ThrowsAny<OperationCanceledException>(() =>
                Cached(ReferenceOrbit.Kind.Mandelbrot, SeahorseRe, SeahorseIm, 60.0, 200000, 0.0, 0.0, null, cancel.Token));
            Assert.Equal(0, ReferenceOrbit.CacheUsage.Count);

            // Cancel mid-orbit, once progress shows it running.
            var progress = new RenderProgress();
            await ExpectCanceledOnce(() => progress.OrbitCompleted >= ReferenceOrbit.PollInterval, token =>
                Cached(ReferenceOrbit.Kind.Julia, "0", "0", 60.0, 5_000_000, -0.123, 0.745, progress, token));
            Assert.Equal(0, ReferenceOrbit.CacheUsage.Count);
        }

        [Fact]
        public async Task ACanceledResumeKeepsTheOrbitItStartedFrom()
        {
            ReferenceOrbit.ClearCache();
            var shortOrbit = Cached(ReferenceOrbit.Kind.Julia, "0", "0", 60.0, 700, -0.123, 0.745);
            var progress = new RenderProgress();
            await ExpectCanceledOnce(() => progress.OrbitCompleted >= ReferenceOrbit.PollInterval, token =>
                Cached(ReferenceOrbit.Kind.Julia, "0", "0", 60.0, 5_000_000, -0.123, 0.745, progress, token));
            Assert.Equal(1, ReferenceOrbit.CacheUsage.Count);

            var hit = new RenderProgress();
            Assert.Same(shortOrbit.Re, Cached(ReferenceOrbit.Kind.Julia, "0", "0", 60.0, 700, -0.123, 0.745, hit).Re);
            Assert.Equal(RenderPhase.NotStarted, hit.Phase);
            var resumed = new RenderProgress();
            var longer = Cached(ReferenceOrbit.Kind.Julia, "0", "0", 60.0, 1000, -0.123, 0.745, resumed);
            Assert.Equal(300, resumed.OrbitTotal);
            AssertSameOrbit(ReferenceOrbit.ComputeUncached(ReferenceOrbit.Kind.Julia, "0", "0", 60.0, 1000, -0.123, 0.745, true), longer);
        }

        [Theory]
        [InlineData(1)]
        [InlineData(4)]
        public async Task ADeepRenderReportsItsOrbitPhaseAndCancelsBetweenRows(int workers)
        {
            ReferenceOrbit.ClearCache();
            var field = new Mandelbrot(maxIter: 3000, workers: workers);
            var viewport = new Viewport(SeahorseRe, SeahorseIm, 20.0);
            var progress = new RenderProgress();
            var counts = new int[32 * 32];
            var smooth = new double[32 * 32];
            field.Iterations(32, 32, viewport, counts, smooth, progress);
            Assert.Equal(RenderPhase.Pixels, progress.Phase);
            Assert.Equal(3000, progress.OrbitTotal);
            Assert.Equal(1.0, progress.OrbitFraction);
            Assert.Equal(32, progress.Completed);

            // The same progress object, reused: the orbit is cached now, so this frame
            // reports no orbit phase at all — nothing left over from the last one.
            field.Iterations(32, 32, viewport, counts, smooth, progress);
            Assert.Equal(0, progress.OrbitTotal);
            Assert.Equal(RenderPhase.Pixels, progress.Phase);

            // A token canceled once the first row is done stops the frame, serial or parallel.
            var third = new RenderProgress();
            var bigCounts = new int[256 * 256];
            await ExpectCanceledOnce(() => third.Completed >= 1, token =>
                field.Iterations(256, 256, viewport, bigCounts, null, third, token));
            Assert.True(third.Completed < 256);
        }

        /// <summary>
        /// A render against a cached orbit longer than it needs reads it in place: no copy
        /// proportional to the orbit (the perturbation index never passes max_iter).
        /// </summary>
        [Fact]
        public void RenderingFromALongerCachedOrbitCopiesNothing()
        {
            ReferenceOrbit.ClearCache();
            var viewport = new Viewport(SeahorseRe, SeahorseIm, 20.0);
            var counts = new int[16 * 16];
            var smooth = new double[16 * 16];
            new Mandelbrot(maxIter: 200000).Iterations(16, 16, viewport, counts, smooth);
            var shorter = new Mandelbrot(maxIter: 150000);
            shorter.Iterations(16, 16, viewport, counts, smooth);              // JIT
            long before = GC.GetAllocatedBytesForCurrentThread();
            shorter.Iterations(16, 16, viewport, counts, smooth);
            long allocated = GC.GetAllocatedBytesForCurrentThread() - before;
            Assert.True(allocated < 64 * 1024, $"{allocated} bytes for one frame");

            // And it is still the same frame as against the exact-length orbit.
            var exact = ReferenceOrbit.Mandelbrot(SeahorseRe, SeahorseIm, 20.0, 150000);
            Assert.Equal(new Mandelbrot(maxIter: 150000).Iterations(16, 16, viewport, exact.Re, exact.Im), counts);
        }
    }
}
