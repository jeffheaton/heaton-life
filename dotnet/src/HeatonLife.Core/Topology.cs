using System;

namespace HeatonLife
{
    /// <summary>
    /// A grid's topology (spec/topology.md "The topologies"): what lies past its edges. Life-like
    /// and Wireworld take all five; Elementary takes <see cref="Torus"/> and <see cref="Dead"/>.
    /// </summary>
    public enum Boundary
    {
        /// <summary>Left joined to right and top to bottom; one pair may be shifted. Params name: torus.</summary>
        Torus,

        /// <summary>The plane: nothing is joined, and past every edge lies the family's blank. Params name: dead.</summary>
        Dead,

        /// <summary>The Klein bottle: one pair of edges joined reversed (twisted), the other as on a
        /// torus; the twisted pair may be shifted. Params name: klein.</summary>
        Klein,

        /// <summary>The cross-surface: both pairs of edges joined reversed. Params name: cross.</summary>
        Cross,

        /// <summary>The sphere, square grids only: the top edge joined to the left one, the right
        /// edge to the bottom one. Params name: sphere.</summary>
        Sphere,
    }

    /// <summary>The pair of edges that carries a shift or a twist (spec/topology.md).</summary>
    public enum TopologyAxis
    {
        /// <summary>The top and bottom edges, which a cell crosses moving along y: crossing them
        /// shifts or mirrors its x. Params name: x.</summary>
        X,

        /// <summary>The left and right edges: crossing them shifts or mirrors y. Params name: y.</summary>
        Y,
    }

    /// <summary>
    /// A topology, a halo or a bounded-grid suffix that isn't one, with the <see cref="Reason"/>
    /// spec/topology.md gives for it (the same phrase in every port).
    /// </summary>
    public sealed class TopologyException : ArgumentException
    {
        public TopologyException(string message, string reason)
            : base(message)
        {
            Reason = reason;
        }

        /// <summary>The reason spec/topology.md "Errors" or "The bounded-grid suffix" gives.</summary>
        public string Reason { get; }

        internal static TopologyException Invalid(string reason)
            => new TopologyException($"invalid topology: {reason} (spec/topology.md)", reason);
    }

    /// <summary>
    /// How a grid's edges join (spec/topology.md): a <see cref="HeatonLife.Boundary"/>, and for a
    /// torus or a Klein bottle a <see cref="Shift"/> along an <see cref="Axis"/>. A Klein bottle's
    /// axis is its twisted pair; where the axis means nothing (no Klein bottle, no shift) it is
    /// <see cref="TopologyAxis.X"/>. The default value is the torus. The Python reference's
    /// heaton_life.core.topology.Topology.
    /// </summary>
    public readonly struct Topology : IEquatable<Topology>
    {
        // How a shift reads (spec/topology.md "Where a point past an edge lands"), each in this
        // one place. A torus's shift moves a cell that leaves across the bottom (right) edge
        // ShiftSense × Shift columns right (rows down); a shifted Klein bottle's twisted crossing
        // sends x to W − 1 + TwistSense × Shift − x.
        private const int ShiftSense = 1;
        private const int TwistSense = 1;

        /// <summary>A topology; throws <see cref="TopologyException"/> for a shift on the plane, the
        /// cross-surface or the sphere. An axis that means nothing becomes <see cref="TopologyAxis.X"/>.</summary>
        public Topology(Boundary boundary, int shift = 0, TopologyAxis axis = TopologyAxis.X)
        {
            if (boundary < Boundary.Torus || boundary > Boundary.Sphere)
                throw TopologyException.Invalid(
                    $"unknown boundary '{(int)boundary}': expected dead, torus, klein, cross or sphere");
            if (axis != TopologyAxis.X && axis != TopologyAxis.Y)
                throw TopologyException.Invalid($"unknown axis '{(int)axis}': expected x or y");
            if (shift != 0 && Plain(boundary) != null)
                throw TopologyException.Invalid($"{Plain(boundary)} has no shift");
            Boundary = boundary;
            Shift = shift;
            Axis = boundary != Boundary.Klein && shift == 0 ? TopologyAxis.X : axis;
        }

        public Boundary Boundary { get; }

        /// <summary>How far a cell moves along <see cref="Axis"/> when it crosses that pair of
        /// edges: a torus's shift, or a Klein bottle's on its twisted pair. 0 is none.</summary>
        public int Shift { get; }

        /// <summary>The pair of edges that carries the shift, or a Klein bottle's twist.</summary>
        public TopologyAxis Axis { get; }

        /// <summary>The topology from the names params use: <paramref name="boundary"/> is
        /// dead, torus, klein, cross or sphere, and <paramref name="axis"/> x or y.</summary>
        public static Topology Parse(string boundary, int shift = 0, string axis = "x")
        {
            if (boundary == null)
                throw new ArgumentNullException(nameof(boundary));
            if (axis == null)
                throw new ArgumentNullException(nameof(axis));
            Boundary kind = boundary switch
            {
                "torus" => Boundary.Torus,
                "dead" => Boundary.Dead,
                "klein" => Boundary.Klein,
                "cross" => Boundary.Cross,
                "sphere" => Boundary.Sphere,
                _ => throw TopologyException.Invalid(
                    $"unknown boundary '{boundary}': expected dead, torus, klein, cross or sphere"),
            };
            TopologyAxis pair = axis switch
            {
                "x" => TopologyAxis.X,
                "y" => TopologyAxis.Y,
                _ => throw TopologyException.Invalid($"unknown axis '{axis}': expected x or y"),
            };
            return new Topology(kind, shift, pair);
        }

        /// <summary>The boundary's name in params: torus, dead, klein, cross or sphere.</summary>
        public string Name => Boundary switch
        {
            Boundary.Torus => "torus",
            Boundary.Dead => "dead",
            Boundary.Klein => "klein",
            Boundary.Cross => "cross",
            _ => "sphere",
        };

        /// <summary>The axis's name in params: x or y.</summary>
        public string AxisName => Axis == TopologyAxis.X ? "x" : "y";

        /// <summary>
        /// Throws <see cref="TopologyException"/> unless a grid of <paramref name="width"/> ×
        /// <paramref name="height"/> cells can have this topology (spec/topology.md "Errors", 4 to 6).
        /// </summary>
        public void Check(int width, int height)
        {
            if (width < 1 || height < 1)
                throw TopologyException.Invalid("a grid has at least one row and one column");
            if (Boundary == Boundary.Sphere && width != height)
                throw TopologyException.Invalid("a sphere is square");
            int twisted = Axis == TopologyAxis.X ? width : height;
            if (Boundary == Boundary.Klein && Shift != 0 && twisted % 2 != 0)
                throw TopologyException.Invalid("a Klein bottle shifts only a side of even length");
        }

        /// <summary>
        /// The cell (<paramref name="cellX"/>, <paramref name="cellY"/>) the plane point
        /// (<paramref name="x"/>, <paramref name="y"/>) stands for on a grid of
        /// <paramref name="width"/> × <paramref name="height"/> cells, or false where it stands for
        /// none (past the plane's edge). spec/topology.md "Where a point past an edge lands": the
        /// cross-surface and the sphere reach one side's length past the grid, and a point farther
        /// out throws <see cref="ArgumentOutOfRangeException"/>.
        /// </summary>
        public bool Locate(long x, long y, int width, int height, out int cellX, out int cellY)
        {
            if (width < 1 || height < 1)
                throw new ArgumentOutOfRangeException(nameof(width), "a grid has at least one row and one column");
            cellX = cellY = 0;
            if (x >= 0 && x < width && y >= 0 && y < height)
            {
                cellX = (int)x;
                cellY = (int)y;
                return true;
            }
            switch (Boundary)
            {
                case Boundary.Dead:
                    return false;
                case Boundary.Torus:
                    if (Axis == TopologyAxis.X)
                    {
                        long k = FloorDiv(y, height);
                        cellX = (int)Mod(Mod(x, width) + Mod(k, width) * Mod(ShiftSense * (long)Shift, width), width);
                        cellY = (int)Mod(y, height);
                    }
                    else
                    {
                        long k = FloorDiv(x, width);
                        cellX = (int)Mod(x, width);
                        cellY = (int)Mod(Mod(y, height) + Mod(k, height) * Mod(ShiftSense * (long)Shift, height), height);
                    }
                    return true;
                case Boundary.Klein:
                    if (Axis == TopologyAxis.X)
                    {
                        bool mirrored = (FloorDiv(y, height) & 1) != 0;
                        cellX = (int)(mirrored ? Mod(width - 1 + Mod(TwistSense * (long)Shift, width) - Mod(x, width), width) : Mod(x, width));
                        cellY = (int)Mod(y, height);
                    }
                    else
                    {
                        bool mirrored = (FloorDiv(x, width) & 1) != 0;
                        cellX = (int)Mod(x, width);
                        cellY = (int)(mirrored ? Mod(height - 1 + Mod(TwistSense * (long)Shift, height) - Mod(y, height), height) : Mod(y, height));
                    }
                    return true;
            }
            long j = FloorDiv(x, width), kk = FloorDiv(y, height);
            if (j < -1 || j > 1 || kk < -1 || kk > 1)
                throw new ArgumentOutOfRangeException(
                    nameof(x), $"({x}, {y}) is past the reach of the {Name} formulas on a {width} x {height} grid (spec/topology.md)");
            long x1 = x - j * width, y1 = y - kk * height;
            if (Boundary == Boundary.Cross)
            {
                cellX = (int)(kk != 0 ? width - 1 - x1 : x1);
                cellY = (int)(j != 0 ? height - 1 - y1 : y1);
                return true;
            }
            long n = width; // a sphere
            if (j == 0) // above or below
            {
                cellX = (int)(kk < 0 ? -1 - y : 2 * n - 1 - y);
                cellY = (int)x;
            }
            else if (kk == 0) // left or right
            {
                cellX = (int)y;
                cellY = (int)(j < 0 ? -1 - x : 2 * n - 1 - x);
            }
            else // past a corner: half a turn about it
            {
                cellX = (int)(j < 0 ? -1 - x : 2 * n - 1 - x);
                cellY = (int)(kk < 0 ? -1 - y : 2 * n - 1 - y);
            }
            return true;
        }

        /// <summary>The name reasons give a topology without a shift, or null for a torus or a
        /// Klein bottle.</summary>
        internal static string? Plain(Boundary boundary) => boundary switch
        {
            Boundary.Dead => "the plane",
            Boundary.Cross => "the cross-surface",
            Boundary.Sphere => "the sphere",
            _ => null,
        };

        private static long FloorDiv(long a, long b)
        {
            long q = a / b;
            return (a % b != 0 && (a < 0) != (b < 0)) ? q - 1 : q;
        }

        private static long Mod(long a, long b)
        {
            long m = a % b;
            return m < 0 ? m + b : m;
        }

        public bool Equals(Topology other)
            => Boundary == other.Boundary && Shift == other.Shift && Axis == other.Axis;

        public override bool Equals(object? obj) => obj is Topology other && Equals(other);

        public override int GetHashCode() => ((int)Boundary * 397 ^ Shift) * 31 + (int)Axis;

        public static bool operator ==(Topology left, Topology right) => left.Equals(right);

        public static bool operator !=(Topology left, Topology right) => !left.Equals(right);

        public override string ToString() => $"Topology({Name}, shift {Shift}, axis {AxisName})";
    }

    /// <summary>
    /// The halo of radius <see cref="Radius"/> around a grid with a topology (spec/topology.md "The
    /// halo"): <see cref="Columns"/> × <see cref="Rows"/> cells, row-major, the grid in the middle
    /// and past its edges the cells its topology puts there (the blank on the plane). A family's
    /// step fills one from each generation with <see cref="Fill"/>, which allocates nothing, and
    /// reads every neighbor from it. The Python reference's heaton_life.core.topology.Halo.
    /// </summary>
    public sealed class Halo
    {
        private readonly int[] _targets; // halo indices past the grid's edges
        private readonly int[] _sources; // the cell each holds, or -1 for the blank

        /// <summary>A halo; throws <see cref="TopologyException"/> when the topology doesn't fit
        /// the size, the radius is below 1, or a cross-surface's or sphere's halo is deeper than
        /// the grid's shorter side.</summary>
        public Halo(Topology topology, int width, int height, int radius = 1)
        {
            topology.Check(width, height);
            if (radius < 1)
                throw TopologyException.Invalid("the halo radius is at least 1");
            bool folded = topology.Boundary == Boundary.Cross || topology.Boundary == Boundary.Sphere;
            if (folded && radius > Math.Min(width, height))
                throw TopologyException.Invalid("the halo is deeper than the grid");
            long columns = (long)width + 2 * radius, rows = (long)height + 2 * radius;
            if (columns * rows > int.MaxValue)
                throw new ArgumentOutOfRangeException(nameof(radius), "the halo holds more cells than one array can");
            Topology = topology;
            Width = width;
            Height = height;
            Radius = radius;
            Columns = (int)columns;
            Rows = (int)rows;
            int ring = Columns * Rows - width * height;
            _targets = new int[ring];
            _sources = new int[ring];
            int i = 0;
            for (int row = 0; row < Rows; row++)
            {
                bool band = row < radius || row >= height + radius; // a whole row past the grid
                for (int column = 0; column < Columns; column++)
                {
                    if (!band && column >= radius && column < width + radius)
                        continue;
                    _targets[i] = row * Columns + column;
                    _sources[i] = topology.Locate(column - radius, row - radius, width, height, out int x, out int y)
                        ? y * width + x
                        : -1;
                    i++;
                }
            }
        }

        public Topology Topology { get; }

        public int Width { get; }

        public int Height { get; }

        public int Radius { get; }

        /// <summary>The halo's width, <see cref="Width"/> + 2 × <see cref="Radius"/>: its row stride.</summary>
        public int Columns { get; }

        /// <summary>The halo's height, <see cref="Height"/> + 2 × <see cref="Radius"/>.</summary>
        public int Rows { get; }

        /// <summary>How many cells the halo holds.</summary>
        public int Length => Columns * Rows;

        /// <summary>
        /// Fills <paramref name="halo"/> (<see cref="Length"/> cells) from <paramref name="cells"/>
        /// (<see cref="Width"/> × <see cref="Height"/>, row-major): the cells in the middle, and past
        /// the edges the cells the topology puts there, <paramref name="blank"/> where it puts none.
        /// Allocates nothing.
        /// </summary>
        public void Fill(ReadOnlySpan<byte> cells, Span<byte> halo, byte blank = 0)
        {
            if (cells.Length != Width * Height)
                throw new ArgumentException($"expected {Width * Height} cells, got {cells.Length}");
            if (halo.Length != Length)
                throw new ArgumentException($"expected a halo of {Length} cells, got {halo.Length}");
            for (int y = 0; y < Height; y++)
                cells.Slice(y * Width, Width).CopyTo(halo.Slice((y + Radius) * Columns + Radius, Width));
            for (int i = 0; i < _targets.Length; i++)
            {
                int source = _sources[i];
                halo[_targets[i]] = source < 0 ? blank : cells[source];
            }
        }

        /// <summary>The cell the halo cell (<paramref name="column"/>, <paramref name="row"/>) holds,
        /// as its index y·<see cref="Width"/> + x, or −1 for the blank (spec/topology.md "Vector
        /// encoding").</summary>
        public int Source(int column, int row)
        {
            if (column < 0 || column >= Columns || row < 0 || row >= Rows)
                throw new ArgumentOutOfRangeException(nameof(column), $"({column}, {row}) is outside the halo");
            return Topology.Locate(column - Radius, row - Radius, Width, Height, out int x, out int y) ? y * Width + x : -1;
        }
    }
}
