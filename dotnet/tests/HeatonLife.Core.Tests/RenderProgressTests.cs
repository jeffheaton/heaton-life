using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// RenderProgress is a host-side observation knob, the same category as the
    /// `workers` argument spec/fractals.md "Parallel rendering" sanctions. The
    /// contract that matters: watching the work must not change it.
    /// </summary>
    public class RenderProgressTests
    {
        [Fact]
        public void ObservingARenderDoesNotChangeIt()
        {
            var field = new Mandelbrot(300, workers: 4);
            var viewport = new Viewport("-0.743643887037151", "0.13182590420533", 3.0);

            var (plainRender, plainCounts) = field.RenderAndCounts(64, 48, viewport);
            var progress = new RenderProgress();
            var (watchedRender, watchedCounts) = field.RenderAndCounts(64, 48, viewport, progress);

            Assert.Equal(plainCounts, watchedCounts);
            Assert.Equal(plainRender, watchedRender);
        }

        [Fact]
        public void ProgressReachesEveryRow()
        {
            var progress = new RenderProgress();
            Assert.False(progress.Started);
            Assert.Equal(0.0, progress.Fraction);

            new Mandelbrot(200, workers: 4).RenderAndCounts(32, 48, new Viewport(), progress);

            Assert.True(progress.Started);
            Assert.Equal(48, progress.Total);          // rows, not pixels
            Assert.Equal(48, progress.Completed);
            Assert.Equal(1.0, progress.Fraction);
        }

        [Theory]
        [InlineData(1)]
        [InlineData(4)]
        public void EveryFamilyReportsAndStaysIdentical(int workers)
        {
            var viewport = new Viewport("-0.5", "0.0", 0.5);
            foreach (var progress in new[] { new RenderProgress() })
            {
                var julia = new Julia(workers: workers);
                Assert.Equal(
                    julia.RenderAndCounts(40, 30, viewport).Counts,
                    julia.RenderAndCounts(40, 30, viewport, progress).Counts);
                Assert.Equal(1.0, progress.Fraction);
            }
            var shipProgress = new RenderProgress();
            var ship = new BurningShip(workers: workers);
            Assert.Equal(
                ship.RenderAndCounts(40, 30, viewport).Counts,
                ship.RenderAndCounts(40, 30, viewport, shipProgress).Counts);
            Assert.Equal(1.0, shipProgress.Fraction);

            var newtonProgress = new RenderProgress();
            var newton = new Newton(3, 60, workers);
            Assert.Equal(
                newton.RenderAndCounts(40, 30, viewport).Counts,
                newton.RenderAndCounts(40, 30, viewport, newtonProgress).Counts);
            Assert.Equal(1.0, newtonProgress.Fraction);
        }
    }
}
