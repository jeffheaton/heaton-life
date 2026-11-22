using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// What a warm call allocates on this thread, measured so the runtime's own one-off work doesn't
    /// count: the least of up to three batches, stopping at the first that allocates nothing. The
    /// runtime can allocate on the calling thread once and unbidden (tiered compilation and on-stack
    /// replacement run there), so a single measurement can catch a few kilobytes that aren't the
    /// code's (7,408 bytes in HistoryTests on macos-latest, c8e7595, where a fresh process measures
    /// 0). An allocation the code makes on every call shows in every batch, so it still fails a test
    /// that wants 0.
    /// </summary>
    internal static class Allocations
    {
        internal static long Least(Action warmed, int batches = 3)
        {
            long least = long.MaxValue;
            for (int batch = 0; batch < batches && least != 0; batch++)
            {
                long before = GC.GetAllocatedBytesForCurrentThread();
                warmed();
                least = Math.Min(least, GC.GetAllocatedBytesForCurrentThread() - before);
            }
            return least;
        }
    }

    public class AllocationsTests
    {
        private static byte[]? _sink;

        [Fact]
        public void AnAllocationOnEveryCallStillShows()
        {
            Assert.True(Allocations.Least(() => _sink = new byte[1000]) >= 1000);
            Assert.Equal(0, Allocations.Least(() => { }));
        }
    }
}
