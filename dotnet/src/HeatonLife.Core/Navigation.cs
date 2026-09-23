using System;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// Exact viewport arithmetic (spec/navigation.md): pan, zoom about a point, and the
    /// pixel offset between two viewports, on decimal centers of any length. The offset
    /// is the float64 a render computes for that pixel, added to the center's exact
    /// value, and the sum is rounded ONCE to a number of decimal places set by the frame
    /// (<see cref="CenterPlaces"/>) — never by the center's digits or the orbit's bits —
    /// so repeating a pan at one zoom never changes the orbit's working precision.
    ///
    /// Pixel offsets are in pixels of a width × height frame from its center: dx to the
    /// right, dy DOWN (the row direction of spec/fractals.md "Pixel mapping"), fractional
    /// allowed. A move whose offsets are both exactly zero keeps the center strings, so a
    /// pan of (0, 0) returns the viewport unchanged; any other move prints both components
    /// at the frame's places. An off-center reference is carried over:
    /// choosing it is the host's job. The Python reference's heaton_life.fractal.navigation.
    /// </summary>
    public static class Navigation
    {
        /// <summary>
        /// Decimal places a moved center is printed with: max(ceil(zoom), 0) plus the number
        /// of decimal digits of max(width, height), plus 2 — a grid of at most 1/400 pixel.
        /// </summary>
        public static int CenterPlaces(double zoomLog10, int width, int height)
        {
            RequireFrame(width, height);
            RequireZoom(zoomLog10);
            int digits = 0;
            for (int n = Math.Max(width, height); n > 0; n /= 10)
                digits++;
            return (int)Math.Max(Math.Ceiling(zoomLog10), 0.0) + digits + 2;
        }

        /// <summary>
        /// The viewport recentered on the point now (dx, dy) pixels from its center (dx
        /// right, dy down) — a click passes the clicked pixel's offset, a drag minus the
        /// drag. The offset is fl(dx·ps) and −fl(dy·ps) at the current zoom's pixel scale:
        /// exactly the offsets a render of this frame gives that pixel.
        /// </summary>
        public static Viewport Pan(Viewport viewport, double dx, double dy, int width, int height)
            => Pan(viewport, dx, dy, width, height, viewport.ZoomLog10);

        /// <summary>
        /// <see cref="Pan(Viewport,double,double,int,int)"/>, landing at
        /// <paramref name="zoomLog10"/>: the offset uses the current zoom's pixel scale, the
        /// center is printed at the new zoom's places (a click that recenters and zooms).
        /// </summary>
        public static Viewport Pan(Viewport viewport, double dx, double dy, int width, int height, double zoomLog10)
        {
            if (viewport == null)
                throw new ArgumentNullException(nameof(viewport));
            RequireFrame(width, height);
            RequireFinite(dx, nameof(dx));
            RequireFinite(dy, nameof(dy));
            int places = CenterPlaces(zoomLog10, width, height);
            double ps = FractalEngine.PixelScale(width, viewport);
            double offsetRe = dx * ps;
            double offsetIm = -dy * ps;
            return Moved(viewport, ExactOffset(offsetRe), ExactOffset(offsetIm), zoomLog10, places);
        }

        /// <summary>
        /// The viewport at <paramref name="zoomLog10"/> with the point at pixel offset
        /// (dx, dy) held fixed (a cursor-anchored wheel or pinch). The center moves by the
        /// exact difference fl(dx·ps0) − fl(dx·ps1), so the anchor pixel's rendered
        /// coordinate is the same in both frames up to the one rounding to places.
        /// </summary>
        public static Viewport ZoomAt(Viewport viewport, double dx, double dy, int width, int height, double zoomLog10)
        {
            if (viewport == null)
                throw new ArgumentNullException(nameof(viewport));
            RequireFrame(width, height);
            RequireFinite(dx, nameof(dx));
            RequireFinite(dy, nameof(dy));
            int places = CenterPlaces(zoomLog10, width, height);
            double ps0 = FractalEngine.PixelScale(width, viewport);
            double ps1 = FractalEngine.PixelScale(width, zoomLog10);
            Rational shiftRe = ExactOffset(dx * ps0) - ExactOffset(dx * ps1);
            Rational shiftIm = ExactOffset(-dy * ps0) - ExactOffset(-dy * ps1);
            return Moved(viewport, shiftRe, shiftIm, zoomLog10, places);
        }

        /// <summary>
        /// Where <paramref name="to"/>'s center lies from <paramref name="from"/>'s, in
        /// pixels of from's frame (x right, y down): each the exact difference of the decimal
        /// centers divided by from's pixel scale, rounded once (ties to even; ±∞ past the
        /// range; an exact zero, "0.1" against "0.10", is +0.0). to's zoom does not enter;
        /// <paramref name="height"/> is taken for symmetry and not used.
        /// </summary>
        public static (double Dx, double Dy) PixelDelta(Viewport from, Viewport to, int width, int height)
        {
            if (from == null)
                throw new ArgumentNullException(nameof(from));
            if (to == null)
                throw new ArgumentNullException(nameof(to));
            RequireFrame(width, height);
            Rational ps = Rational.Of(FractalEngine.PixelScale(width, from));
            Rational across = (Rational.Of(to.CenterRe) - Rational.Of(from.CenterRe)) / ps;
            Rational down = (Rational.Of(from.CenterIm) - Rational.Of(to.CenterIm)) / ps;
            return (across.ToDouble(), down.ToDouble());
        }

        /// <summary>
        /// The same value written positionally with the same number of decimal places the
        /// precision rule counts: "1e-5" → "0.00001", "2.5E1" → "25", "0.10" → "0.10",
        /// "-0.0" → "0.0". For writing centers where a reader expects no exponent.
        /// </summary>
        public static string Positional(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            return DecimalText.Positional(text);
        }

        /// <summary>
        /// The viewport at zoomLog10 with its center shifted exactly and printed at places —
        /// or with its center strings as they were when both shifts are exactly zero.
        /// </summary>
        private static Viewport Moved(Viewport viewport, Rational shiftRe, Rational shiftIm, double zoomLog10, int places)
        {
            bool still = shiftRe.IsZero && shiftIm.IsZero;
            return new Viewport(
                still ? viewport.CenterRe : Printed(Rational.Of(viewport.CenterRe) + shiftRe, places),
                still ? viewport.CenterIm : Printed(Rational.Of(viewport.CenterIm) + shiftIm, places),
                zoomLog10,
                viewport.ReferenceRe,
                viewport.ReferenceIm);
        }

        /// <summary>sum rounded half away from zero to places fraction digits.</summary>
        private static string Printed(Rational sum, int places)
        {
            BigInteger scaled = sum.Numerator * BigInteger.Pow(10, places);
            BigInteger whole = BigInteger.DivRem(BigInteger.Abs(scaled), sum.Denominator, out BigInteger remainder);
            if ((remainder << 1) >= sum.Denominator)
                whole += BigInteger.One;
            return DecimalText.FormatScaled(scaled.Sign < 0 ? -whole : whole, places);
        }

        private static Rational ExactOffset(double offset)
        {
            if (double.IsNaN(offset) || double.IsInfinity(offset))
                throw new ArgumentException($"the offset overflows float64: {offset}");
            return Rational.Of(offset);
        }

        private static void RequireFrame(int width, int height)
        {
            if (width < 1 || height < 1)
                throw new ArgumentOutOfRangeException(nameof(width), $"frame must be at least 1x1, got {width}x{height}");
        }

        /// <summary>A zoom the pixel scale can take: finite, |z| &lt;= 300 (spec/pow10.md's domain).</summary>
        private static void RequireZoom(double zoomLog10)
        {
            RequireFinite(zoomLog10, nameof(zoomLog10));
            if (Math.Abs(zoomLog10) > 300.0)
                throw new ArgumentOutOfRangeException(nameof(zoomLog10), $"zoom must lie within [-300, 300], got {zoomLog10}");
        }

        private static void RequireFinite(double value, string name)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
                throw new ArgumentException($"{name} must be finite, got {value}", name);
        }

        /// <summary>An exact rational, denominator positive; no normalization is needed here.</summary>
        private readonly struct Rational
        {
            internal readonly BigInteger Numerator;
            internal readonly BigInteger Denominator;

            private Rational(BigInteger numerator, BigInteger denominator)
            {
                Numerator = numerator;
                Denominator = denominator;
            }

            internal bool IsZero => Numerator.IsZero;

            /// <summary>The exact value of a grammar-valid decimal string.</summary>
            internal static Rational Of(string text)
            {
                DecimalText.Scan(text, out bool negative, out BigInteger digits, out int netExponent);
                BigInteger signed = negative ? -digits : digits;
                return netExponent >= 0
                    ? new Rational(signed * BigInteger.Pow(10, netExponent), BigInteger.One)
                    : new Rational(signed, BigInteger.Pow(10, -netExponent));
            }

            /// <summary>The exact value of a finite double: mantissa × 2^exponent.</summary>
            internal static Rational Of(double value)
            {
                if (value == 0.0)
                    return new Rational(BigInteger.Zero, BigInteger.One);
                long raw = BitConverter.DoubleToInt64Bits(value);
                int exponent = (int)((raw >> 52) & 0x7FF);
                long mantissa = raw & 0xFFFFFFFFFFFFFL;
                if (exponent == 0)
                    exponent = 1;                 // subnormal
                else
                    mantissa |= 1L << 52;         // restore the implicit bit
                exponent -= 1075;                 // value = mantissa × 2^exponent
                BigInteger signed = raw < 0 ? -(BigInteger)mantissa : mantissa;
                return exponent >= 0
                    ? new Rational(signed << exponent, BigInteger.One)
                    : new Rational(signed, BigInteger.One << -exponent);
            }

            public static Rational operator +(Rational a, Rational b) =>
                new Rational(a.Numerator * b.Denominator + b.Numerator * a.Denominator, a.Denominator * b.Denominator);

            public static Rational operator -(Rational a, Rational b) =>
                new Rational(a.Numerator * b.Denominator - b.Numerator * a.Denominator, a.Denominator * b.Denominator);

            /// <summary>a / b for a positive b.</summary>
            public static Rational operator /(Rational a, Rational b) =>
                new Rational(a.Numerator * b.Denominator, a.Denominator * b.Numerator);

            /// <summary>One correct rounding (ties to even), ±∞ past the range, +0.0 for zero.</summary>
            internal double ToDouble()
            {
                if (Numerator.IsZero)
                    return 0.0;
                return DecimalText.RatioToDouble(Numerator.Sign < 0, BigInteger.Abs(Numerator), Denominator);
            }
        }
    }
}
