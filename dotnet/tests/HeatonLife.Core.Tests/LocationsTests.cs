using System;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Locations (spec/locations.md): the framing identities and edges the vectors do not
    /// enumerate. The Python suite's test_locations.py.
    /// </summary>
    public class LocationsTests
    {
        [Fact]
        public void KfAndF3FrameByTheHeight()
        {
            var loc = Locations.ParseKfr("Re: -0.5\nIm: 0\nZoom: 1e10\n");
            Assert.True(Math.Abs(loc.ToViewport(512, 512).ZoomLog10 - 10.0) <= 1e-12);
            foreach (var (width, height) in new[] { (1920, 1080), (1080, 1920), (333, 777) })
            {
                double spacing = FractalEngine.PixelScale(width, loc.ToViewport(width, height).ZoomLog10);
                double kf = 4 / (1e10 * height);
                Assert.True(Math.Abs(spacing - kf) <= 1e-12 * kf, $"{width}x{height}");
            }
        }

        [Fact]
        public void DecimalLog10ReachesPastTheFloatRange()
        {
            Assert.True(Math.Abs(Locations.DecimalLog10("2.15e2836") - (2836 + Math.Log10(2.15))) <= 1e-9);
            Assert.Equal(5000.0, Locations.DecimalLog10("1" + new string('0', 5000)));
            foreach (string bad in new[] { "0", "-1", "0.000" })
                Assert.ThrowsAny<ArgumentException>(() => Locations.DecimalLog10(bad));
        }

        [Fact]
        public void Edges()
        {
            Assert.ThrowsAny<ArgumentException>(() => Locations.HeatonFractalJournal(Array.Empty<(string, string, double)>()));
            Assert.ThrowsAny<ArgumentException>(() => Locations.ParseKfr("Re: 0,5\nIm: 0\n"));
            var loc = Locations.ParseKfr("Re: 1.5e-3\nIm: -2E1\nZoom: 1\n");
            Assert.Equal(("0.0015", "-20"), (loc.CenterRe, loc.CenterIm));
            Assert.ThrowsAny<ArgumentException>(() => loc.ToViewport(0, 10));
            Assert.ThrowsAny<ArgumentException>(() => Locations.HeatonFractalPreset("0", "0", "1.0", double.NaN, null));
            Assert.ThrowsAny<ArgumentException>(() => Locations.HeatonFractalPreset("0", "0", "1.0", 3.0, 0));
            Assert.ThrowsAny<ArgumentException>(() => Locations.HeatonFractalPreset("0", "0", null!, 3.0, null));
            var noDepth = Locations.HeatonFractalPreset("0", "0", "1.0", null, null);
            Assert.Null(noDepth.HalfHeightLog10);
            Assert.Equal(new[] { "no-scale" }, noDepth.Warnings);
        }
    }
}
