using System;
using System.Threading;

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
            CenterRe = Validate(centerRe, nameof(centerRe));
            CenterIm = Validate(centerIm, nameof(centerIm));
            ZoomLog10 = zoomLog10;
        }

        private double _centerReDouble;
        private double _centerImDouble;
        private int _projected;                                 // 1 once both projections are stored

        /// <summary>
        /// Float64 projection of the center (T0 only — collapses past zoom ~1e13): the
        /// double nearest the decimal, rounded once, computed from the digits rather
        /// than by <c>double.Parse</c>, whose rounding is only guaranteed on .NET Core.
        /// Computed on first use: a T1 render never needs it, and a host that builds a
        /// Viewport per frame should not pay for a long center's bignum every frame.
        /// </summary>
        public double CenterReDouble
        {
            get
            {
                Project();
                return _centerReDouble;
            }
        }

        /// <summary>Float64 projection of the center (T0 only).</summary>
        public double CenterImDouble
        {
            get
            {
                Project();
                return _centerImDouble;
            }
        }

        private void Project()
        {
            if (Volatile.Read(ref _projected) != 0)
                return;
            // Racing threads compute the same values; the flag publishes them after the stores.
            _centerReDouble = DecimalText.ToDouble(CenterRe);
            _centerImDouble = DecimalText.ToDouble(CenterIm);
            Volatile.Write(ref _projected, 1);
        }

        private static string Validate(string value, string name)
        {
            if (value == null)
                throw new ArgumentNullException(name);
            try
            {
                DecimalText.NetExponent(value);
            }
            catch (ArgumentException)
            {
                throw new ArgumentException($"Viewport.{name} is not a valid decimal string: '{value}'", name);
            }
            return value;
        }
    }
}
