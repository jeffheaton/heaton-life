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
    ///
    /// A viewport may also carry an off-center <b>reference</b> (spec/deep-zoom.md
    /// "Off-center reference"): a T1 frame then iterates the reference's orbit and
    /// offsets every pixel by round64(center − reference), so a host can pan without a
    /// new orbit per frame. The reference is part of the frame's definition — counts
    /// can differ from the centered frame's on chaotic pixels — so it is explicit, never
    /// remembered by the library. T0 ignores it.
    /// </summary>
    public sealed class Viewport
    {
        public string CenterRe { get; }
        public string CenterIm { get; }
        public double ZoomLog10 { get; }

        /// <summary>The off-center reference's real part, or null for a centered frame.</summary>
        public string? ReferenceRe { get; }

        /// <summary>The off-center reference's imaginary part, or null for a centered frame.</summary>
        public string? ReferenceIm { get; }

        public Viewport(string centerRe = "-0.5", string centerIm = "0.0", double zoomLog10 = 0.0)
        {
            CenterRe = Validate(centerRe, nameof(centerRe));
            CenterIm = Validate(centerIm, nameof(centerIm));
            ZoomLog10 = zoomLog10;
        }

        /// <summary>
        /// A viewport whose T1 frames iterate the orbit of (referenceRe, referenceIm) — both
        /// parts, or neither (null, null) for a centered frame.
        /// </summary>
        public Viewport(string centerRe, string centerIm, double zoomLog10, string? referenceRe, string? referenceIm)
            : this(centerRe, centerIm, zoomLog10)
        {
            if ((referenceRe == null) != (referenceIm == null))
                throw new ArgumentException("a reference needs both parts, or neither");
            if (referenceRe == null)
                return;
            ReferenceRe = Validate(referenceRe, nameof(referenceRe));
            ReferenceIm = Validate(referenceIm!, nameof(referenceIm));
        }

        /// <summary>This viewport with the given reference (null, null for none).</summary>
        public Viewport WithReference(string? referenceRe, string? referenceIm)
            => new Viewport(CenterRe, CenterIm, ZoomLog10, referenceRe, referenceIm);

        /// <summary>True when T1 frames iterate a reference other than the center.</summary>
        public bool HasReference => ReferenceRe != null;

        /// <summary>The real part of the point a T1 frame iterates: the reference, else the center.</summary>
        public string OrbitCenterRe => ReferenceRe ?? CenterRe;

        /// <summary>The imaginary part of the point a T1 frame iterates.</summary>
        public string OrbitCenterIm => ReferenceIm ?? CenterIm;

        private double _referenceOffsetRe;
        private double _referenceOffsetIm;
        private int _offsetComputed;

        /// <summary>
        /// round64(center − reference), real part: exact from the decimal strings, rounded
        /// once; 0 without a reference. Every T1 pixel's delta is fl(this + its offset).
        /// </summary>
        public double ReferenceOffsetRe
        {
            get
            {
                ComputeOffset();
                return _referenceOffsetRe;
            }
        }

        /// <summary>round64(center − reference), imaginary part; 0 without a reference.</summary>
        public double ReferenceOffsetIm
        {
            get
            {
                ComputeOffset();
                return _referenceOffsetIm;
            }
        }

        private void ComputeOffset()
        {
            if (Volatile.Read(ref _offsetComputed) != 0)
                return;
            if (ReferenceRe != null)
            {
                _referenceOffsetRe = DecimalText.Difference(CenterRe, ReferenceRe);
                _referenceOffsetIm = DecimalText.Difference(CenterIm, ReferenceIm!);
            }
            Volatile.Write(ref _offsetComputed, 1);
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
