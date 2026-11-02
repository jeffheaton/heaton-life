using System;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// Where a HashLife frame looks (spec/hashlife.md "View and render"): its top-left pixel
    /// (X, Y) in the pixel plane of magnification <see cref="Mag"/>, in tree coordinates (cell
    /// y − 1). At <c>Mag ≥ 0</c> each cell is a 2^Mag-pixel square, up to <see cref="MaxMag"/>
    /// (1:32); at <c>Mag &lt; 0</c> each pixel is an aligned block of 2^−Mag
    /// cells — one quadtree node — so a frame costs the same at any scale.
    ///
    /// The static functions are exact integer arithmetic (floor division and shifts on unbounded
    /// integers), so every port moves views identically and a host keeps no copy of the math.
    /// The Python reference's heaton_life.ca.hashlife.view.
    /// </summary>
    public readonly struct LifeView : IEquatable<LifeView>
    {
        /// <summary>32 pixels per cell, the deepest zoom.</summary>
        public const int MaxMag = 5;

        public LifeView(BigInteger x, BigInteger y, int mag)
        {
            if (mag > MaxMag)
                throw new ArgumentOutOfRangeException(
                    nameof(mag), mag, $"mag {mag} is past the deepest zoom ({MaxMag}: 32 px per cell)");
            X = x;
            Y = y;
            Mag = mag;
        }

        public BigInteger X { get; }

        public BigInteger Y { get; }

        public int Mag { get; }

        /// <summary>Drag the picture by (dx, dy) pixels: what was under pixel (i, j) is now under
        /// (i + dx, j + dy).</summary>
        public static LifeView Pan(LifeView view, long dx, long dy)
            => new LifeView(view.X - dx, view.Y - dy, view.Mag);

        /// <summary>
        /// Zoom by 2^steps (steps &gt; 0 in, &lt; 0 out), one doubling at a time, keeping pixel
        /// (i, j) over the same point: in, the pixel plane doubles (x' = 2(x + i) − i); out, it
        /// halves, flooring (x' = ⌊(x + i) / 2⌋ − i). Zooming in stops at <see cref="MaxMag"/>.
        /// </summary>
        public static LifeView ZoomAt(LifeView view, long i, long j, int steps)
        {
            BigInteger x = view.X, y = view.Y;
            int mag = view.Mag;
            int count = steps < 0 ? -steps : steps;
            for (int n = 0; n < count; n++)
            {
                if (steps > 0)
                {
                    if (mag == MaxMag)
                        break;
                    x = 2 * (x + i) - i;
                    y = 2 * (y + j) - j;
                    mag++;
                }
                else
                {
                    x = FloorShift(x + i, 1) - i;
                    y = FloorShift(y + j, 1) - j;
                    mag--;
                }
            }
            return new LifeView(x, y, mag);
        }

        /// <summary>The cell under pixel (i, j); zoomed out, the top-left cell of the pixel's block.</summary>
        public static (BigInteger X, BigInteger Y) CellAt(LifeView view, long i, long j)
        {
            BigInteger px = view.X + i, py = view.Y + j;
            if (view.Mag >= 0)
                return (FloorShift(px, view.Mag), FloorShift(py, view.Mag) + 1);
            int s = -view.Mag;
            return (ShiftUp(px, s), ShiftUp(py, s) + 1);
        }

        /// <summary>The cell under the frame's center pixel (width div 2, height div 2).</summary>
        public static (BigInteger X, BigInteger Y) CenterCell(LifeView view, long width, long height)
            => CellAt(view, FloorHalf(width), FloorHalf(height));

        /// <summary>The view of width × height pixels whose center pixel (width div 2, height div 2)
        /// shows cell (x, y) — or, zoomed out, the block holding it.</summary>
        public static LifeView Centered(BigInteger x, BigInteger y, int mag, long width, long height)
        {
            if (mag >= 0)
                return new LifeView(ShiftUp(x, mag) - FloorHalf(width), ShiftUp(y - 1, mag) - FloorHalf(height), mag);
            int s = -mag;
            return new LifeView(FloorShift(x, s) - FloorHalf(width), FloorShift(y - 1, s) - FloorHalf(height), mag);
        }

        /// <summary>
        /// The deepest view (mag ≤ <see cref="MaxMag"/>) whose frame holds the inclusive box,
        /// centered on it; an empty universe (null) gives the origin at 1:1.
        /// </summary>
        public static LifeView Fit(CellBox? box, long width, long height)
        {
            if (box == null)
                return Centered(BigInteger.Zero, BigInteger.Zero, 0, width, height);
            CellBox b = box.Value;
            BigInteger ty0 = b.Y0 - 1, ty1 = b.Y1 - 1;
            // A box straddling an axis never fits a frame one pixel across; give up once every
            // span has shrunk to its last pixel instead of searching forever.
            long bits = Math.Max(
                Math.Max(BitLength(b.X0), BitLength(b.X1)), Math.Max(BitLength(ty0), BitLength(ty1)));
            for (int mag = MaxMag; ; mag--)
            {
                BigInteger left, right, top, bottom;
                if (mag >= 0)
                {
                    left = ShiftUp(b.X0, mag);
                    right = ShiftUp(b.X1 + 1, mag) - 1;
                    top = ShiftUp(ty0, mag);
                    bottom = ShiftUp(ty1 + 1, mag) - 1;
                }
                else
                {
                    int s = -mag;
                    left = FloorShift(b.X0, s);
                    right = FloorShift(b.X1, s);
                    top = FloorShift(ty0, s);
                    bottom = FloorShift(ty1, s);
                }
                if (right - left < width && bottom - top < height)
                    return new LifeView(
                        FloorShift(left + right, 1) - FloorHalf(width), FloorShift(top + bottom, 1) - FloorHalf(height), mag);
                if (-mag > bits + 1)
                    throw new ArgumentException($"no view of {width} x {height} pixels holds {b}");
            }
        }

        /// <summary>⌊v / 2^s⌋, shifting only non-negative values (runtimes have disagreed on
        /// BigInteger's shift of negatives).</summary>
        internal static BigInteger FloorShift(BigInteger v, int s)
            => v.Sign >= 0 ? v >> s : -((-v - 1) >> s) - 1;

        /// <summary>v · 2^s.</summary>
        internal static BigInteger ShiftUp(BigInteger v, int s)
            => v.Sign >= 0 ? v << s : -((-v) << s);

        private static long FloorHalf(long v) => v >> 1;

        private static long BitLength(BigInteger v)
        {
            BigInteger magnitude = v.Sign >= 0 ? v : -v - 1;
            long bits = 0;
            while (!magnitude.IsZero)
            {
                magnitude >>= 1;
                bits++;
            }
            return bits;
        }

        public bool Equals(LifeView other) => X == other.X && Y == other.Y && Mag == other.Mag;

        public override bool Equals(object? obj) => obj is LifeView other && Equals(other);

        public override int GetHashCode() => X.GetHashCode() ^ (Y.GetHashCode() * 31) ^ Mag;

        public override string ToString() => $"LifeView({X}, {Y}, {Mag})";

        public static bool operator ==(LifeView a, LifeView b) => a.Equals(b);

        public static bool operator !=(LifeView a, LifeView b) => !a.Equals(b);
    }
}
