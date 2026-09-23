using System;

namespace HeatonLife
{
    /// <summary>
    /// Viewport: the arbitrary-precision fractal position contract (spec/deep-zoom.md).
    /// Centers are decimal strings of unlimited length; zoom is log10 of magnification.
    /// The center is never *stored* as float64 — that is the whole point (float64
    /// pixelates near zoom 1e13, and deep zoom must not be a retrofit). Float64
    /// projections are provided for the T0 tier only. Both centers follow the one
    /// decimal grammar every consumer shares (<see cref="DecimalText"/>, the Python
    /// reference's core/decimal_text.py): no NaN, no infinities, ASCII digits.
    /// </summary>
    public sealed class Viewport
    {
        public string CenterRe { get; }
        public string CenterIm { get; }
        public double ZoomLog10 { get; }

        public Viewport(string centerRe = "-0.5", string centerIm = "0.0", double zoomLog10 = 0.0)
        {
            CenterRe = centerRe ?? throw new ArgumentNullException(nameof(centerRe));
            CenterIm = centerIm ?? throw new ArgumentNullException(nameof(centerIm));
            CenterReDouble = Project(centerRe, nameof(centerRe));
            CenterImDouble = Project(centerIm, nameof(centerIm));
            ZoomLog10 = zoomLog10;
        }

        /// <summary>
        /// Float64 projection of the center (T0 only — collapses past zoom ~1e13): the
        /// double nearest the decimal, rounded once, computed from the digits rather
        /// than by <c>double.Parse</c>, whose rounding is only guaranteed on .NET Core.
        /// </summary>
        public double CenterReDouble { get; }

        /// <summary>Float64 projection of the center (T0 only).</summary>
        public double CenterImDouble { get; }

        private static double Project(string value, string name)
        {
            try
            {
                return DecimalText.ToDouble(value);
            }
            catch (ArgumentException)
            {
                throw new ArgumentException($"Viewport.{name} is not a valid decimal string: '{value}'", name);
            }
        }
    }
}
