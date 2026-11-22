using System;

namespace HeatonLife
{
    /// <summary>
    /// A world a bounded-grid suffix names (spec/topology.md "The bounded-grid suffix"): its size
    /// and <see cref="Topology"/>, written after a rule as <c>B3/S23:T30,20</c>. <see cref="Parse"/>
    /// reads a suffix and <see cref="Suffix"/> writes the canonical one. The Python reference's
    /// heaton_life.core.topology.BoundedGrid.
    /// </summary>
    public sealed class BoundedGrid : IEquatable<BoundedGrid>
    {
        /// <summary>The largest side, and the largest shift, a suffix may name.</summary>
        public const int MaxSide = 2_000_000_000;

        /// <summary>A world; throws <see cref="TopologyException"/> for a side below 1 or past
        /// <see cref="MaxSide"/>, a shift past it, or a topology the size can't have.</summary>
        public BoundedGrid(int width, int height, Topology topology)
        {
            if (width == 0 || height == 0)
                throw TopologyException.Invalid("a side of 0 (an unbounded strip or tube) is not supported");
            if (width < 0 || height < 0 || width > MaxSide || height > MaxSide
                || topology.Shift > MaxSide || topology.Shift < -MaxSide)
                throw TopologyException.Invalid($"a side or a shift is at most {MaxSide}");
            topology.Check(width, height);
            Width = width;
            Height = height;
            Topology = topology;
        }

        public int Width { get; }

        public int Height { get; }

        public Topology Topology { get; }

        /// <summary>The canonical suffix, the <c>:</c> included: <c>:T30,20</c>,
        /// <c>:K30*+1,20</c>, <c>:S30</c>.</summary>
        public string Suffix
        {
            get
            {
                if (Topology.Boundary == Boundary.Sphere)
                    return ":S" + Width.ToString(System.Globalization.CultureInfo.InvariantCulture);
                string marks = Topology.Boundary == Boundary.Klein ? "*" : "";
                if (Topology.Shift != 0)
                    marks += (Topology.Shift > 0 ? "+" : "-") + Digits(Math.Abs((long)Topology.Shift));
                bool onWidth = Topology.Axis == TopologyAxis.X;
                char letter = Topology.Boundary switch
                {
                    Boundary.Dead => 'P',
                    Boundary.Torus => 'T',
                    Boundary.Klein => 'K',
                    _ => 'C',
                };
                return ":" + letter + Digits(Width) + (onWidth ? marks : "") + "," + Digits(Height)
                    + (onWidth ? "" : marks);
            }
        }

        public override string ToString() => Suffix;

        /// <summary>
        /// The world a suffix names (<c>:T30,20</c>, the <c>:</c> included). Throws
        /// <see cref="TopologyException"/>, whose message is <c>invalid bounded grid '&lt;text&gt;':
        /// &lt;reason&gt; (spec/topology.md)</c>, with the reason for the first problem found.
        /// </summary>
        public static BoundedGrid Parse(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            if (!TryParse(text, out BoundedGrid? grid, out string? reason))
                throw Invalid(text, reason!);
            return grid!;
        }

        /// <summary>
        /// <see cref="Parse"/> without throwing: true and the grid, or false and the reason
        /// (spec/topology.md "The bounded-grid suffix", "Reasons"). Null reads as empty text.
        /// </summary>
        public static bool TryParse(string? text, out BoundedGrid? grid, out string? reason)
        {
            grid = null;
            reason = Read(text ?? "", out grid);
            return reason == null;
        }

        /// <summary>
        /// A rule's text split at its suffix (spec/topology.md "In a rule's text"): the rule is
        /// everything before the first <c>:</c>, which this returns, and <paramref name="grid"/>
        /// the world the rest names, without the whitespace at its end; null without a <c>:</c>.
        /// A bad suffix throws its <see cref="TopologyException"/>.
        /// </summary>
        public static string SplitRule(string text, out BoundedGrid? grid)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            int colon = text.IndexOf(':');
            if (colon < 0)
            {
                grid = null;
                return text;
            }
            int end = text.Length;
            while (end > colon && RuleString.IsSpace(text[end - 1]))
                end--;
            grid = Parse(text.Substring(colon, end - colon));
            return text.Substring(0, colon);
        }

        private static TopologyException Invalid(string text, string reason)
            => new TopologyException($"invalid bounded grid '{text}': {reason} (spec/topology.md)", reason);

        private static string Digits(long value) => value.ToString(System.Globalization.CultureInfo.InvariantCulture);

        /// <summary>One side as written: its size (any past <see cref="MaxSide"/> as one more), a
        /// <c>*</c>, and its shift (0 without one).</summary>
        private struct Side
        {
            public long Size;
            public bool Star;
            public long Shift;
        }

        /// <summary>The reason a suffix is no bounded grid, or null with the grid it names.</summary>
        private static string? Read(string text, out BoundedGrid? grid)
        {
            grid = null;
            if (text.Length == 0 || text[0] != ':')
                return "a bounded grid starts with ':'";
            Boundary boundary;
            switch (text.Length < 2 ? '\0' : text[1])
            {
                case 'P':
                case 'p':
                    boundary = Boundary.Dead;
                    break;
                case 'T':
                case 't':
                    boundary = Boundary.Torus;
                    break;
                case 'K':
                case 'k':
                    boundary = Boundary.Klein;
                    break;
                case 'C':
                case 'c':
                    boundary = Boundary.Cross;
                    break;
                case 'S':
                case 's':
                    boundary = Boundary.Sphere;
                    break;
                default:
                    return "expected P, T, K, C or S after ':'";
            }
            int pos = 2;
            var sides = new Side[2];
            int count = 0;
            while (true)
            {
                string? problem = Number(text, ref pos, out long size);
                if (problem != null)
                    return problem;
                var side = new Side { Size = size };
                if (pos < text.Length && text[pos] == '*')
                {
                    side.Star = true;
                    pos++;
                }
                if (pos < text.Length && (text[pos] == '+' || text[pos] == '-'))
                {
                    bool negative = text[pos] == '-';
                    pos++;
                    problem = Number(text, ref pos, out long shift);
                    if (problem != null)
                        return problem;
                    side.Shift = negative ? -shift : shift;
                }
                sides[count++] = side;
                if (count == 2 || pos >= text.Length || text[pos] != ',')
                    break;
                pos++;
            }
            if (pos < text.Length)
                return $"unexpected '{text.Substring(pos)}' in the bounded grid";
            if (count == 1)
                sides[1] = new Side { Size = sides[0].Size }; // one side: a square, marks on the width

            Side width = sides[0], height = sides[1];
            string? plain = Topology.Plain(boundary);
            if (plain != null)
            {
                if (width.Star || height.Star || width.Shift != 0 || height.Shift != 0)
                    return $"{plain} has no shift or twist";
            }
            else if (boundary == Boundary.Torus)
            {
                if (width.Star || height.Star)
                    return "a torus has no twist";
                if (width.Shift != 0 && height.Shift != 0)
                    return "a torus shifts one side only";
            }
            else if (width.Star == height.Star)
            {
                return "a Klein bottle twists one side: '*' after its width or its height";
            }
            else if ((width.Star ? height.Shift : width.Shift) != 0)
            {
                return "a Klein bottle shifts only its twisted side";
            }
            if (width.Size == 0 || height.Size == 0)
                return "a side of 0 (an unbounded strip or tube) is not supported";
            if (Math.Max(Math.Max(width.Size, height.Size), Math.Max(Math.Abs(width.Shift), Math.Abs(height.Shift))) > MaxSide)
                return $"a side or a shift is at most {MaxSide}";
            TopologyAxis axis = boundary == Boundary.Klein
                ? (width.Star ? TopologyAxis.X : TopologyAxis.Y)
                : (height.Shift != 0 ? TopologyAxis.Y : TopologyAxis.X);
            long along = axis == TopologyAxis.X ? width.Shift : height.Shift;
            try
            {
                grid = new BoundedGrid((int)width.Size, (int)height.Size, new Topology(boundary, (int)along, axis));
            }
            catch (TopologyException e)
            {
                return e.Reason; // the topology's own errors with the size
            }
            return null;
        }

        /// <summary>Reads ASCII digits at <paramref name="pos"/> as a number, any past
        /// <see cref="MaxSide"/> as <see cref="MaxSide"/> + 1; the reason when there are none.</summary>
        private static string? Number(string text, ref int pos, out long value)
        {
            value = 0;
            int start = pos;
            while (pos < text.Length && text[pos] >= '0' && text[pos] <= '9')
            {
                value = Math.Min(value * 10 + (text[pos] - '0'), (long)MaxSide + 1);
                pos++;
            }
            if (pos == start)
                return $"expected a number after '{text[pos - 1]}'";
            return null;
        }

        public bool Equals(BoundedGrid? other)
            => other != null && Width == other.Width && Height == other.Height && Topology == other.Topology;

        public override bool Equals(object? obj) => Equals(obj as BoundedGrid);

        public override int GetHashCode() => (Width * 397 ^ Height) * 31 + Topology.GetHashCode();
    }
}
