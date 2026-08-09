using System;
using System.Globalization;

namespace HeatonLife
{
    /// <summary>
    /// Viewport: the arbitrary-precision fractal position contract (spec/deep-zoom.md).
    /// Centers are decimal strings of unlimited length; zoom is log10 of magnification.
    /// The center is never *stored* as float64 — that is the whole point (float64
    /// pixelates near zoom 1e13, and deep zoom must not be a retrofit). Float64
    /// projections are provided for the T0 tier only.
    /// </summary>
    public sealed class Viewport
    {
        public string CenterRe { get; }
        public string CenterIm { get; }
        public double ZoomLog10 { get; }

        public Viewport(string centerRe = "-0.5", string centerIm = "0.0", double zoomLog10 = 0.0)
        {
            CenterRe = Validate(centerRe, nameof(centerRe));
            CenterIm = Validate(centerIm, nameof(centerIm));
            ZoomLog10 = zoomLog10;
        }

        /// <summary>Float64 projection of the center (T0 only — collapses past zoom ~1e13).</summary>
        public double CenterReDouble => double.Parse(CenterRe, CultureInfo.InvariantCulture);

        /// <summary>Float64 projection of the center (T0 only).</summary>
        public double CenterImDouble => double.Parse(CenterIm, CultureInfo.InvariantCulture);

        private static string Validate(string value, string name)
        {
            if (value == null)
                throw new ArgumentNullException(name);
            if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out _))
                throw new ArgumentException($"Viewport.{name} is not a valid decimal string: '{value}'");
            return value;
        }
    }
}
