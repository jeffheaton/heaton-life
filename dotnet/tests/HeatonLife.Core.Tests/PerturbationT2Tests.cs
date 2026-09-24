using System;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>The T2 pixel loop's host behavior (spec/deep-zoom.md "T2"); its arithmetic is the vectors' job.</summary>
    public class PerturbationT2Tests
    {
        /// <summary>
        /// A T2 pixel can run for millions of iterations, so the loop itself polls its token
        /// (every 2^16 iterations), not only the row loop around it.
        /// </summary>
        [Fact]
        public void ThePixelLoopPollsForCancellation()
        {
            var orbit = new PerturbationT2.Orbit(
                new[] { 0.25, 0.25 }, new[] { 0.125, 0.125 }, ReferenceOrbit.SmallSamples.Empty);   // |2Z| < 1: delta only shrinks
            FloatExp delta = FloatExp.Normalize(1.0, -3000);

            int Run(int maxIter, CancellationToken token) => PerturbationT2.Perturb(
                orbit, orbit, delta, delta, FloatExp.Zero, FloatExp.Zero, maxIter, 1000.0,
                false, FloatExp.Zero, FloatExp.Zero, FloatExp.Zero, false,
                out _, out _, out _, out _, out _, token);

            Assert.Equal(-1, Run(70_000, CancellationToken.None));   // never escapes
            using var cancel = new CancellationTokenSource();
            cancel.Cancel();
            Assert.Equal(-1, Run(65_535, cancel.Token));              // no poll before 2^16
            Assert.ThrowsAny<OperationCanceledException>(() => Run(70_000, cancel.Token));
        }
    }
}
