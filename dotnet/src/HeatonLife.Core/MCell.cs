using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text;

namespace HeatonLife
{
    /// <summary>An MCell file's lines, read and checked: everything but the cells
    /// (spec/formats.md "MCell").</summary>
    internal sealed class MCellHeader
    {
        internal MCellHeader(
            string family, string rule, int states, BoundedGrid? board, PatternMetadata metadata, string data)
        {
            Family = family;
            Rule = rule;
            States = states;
            Board = board;
            Metadata = metadata;
            Data = data;
        }

        /// <summary>One of <see cref="MCell.Families"/>.</summary>
        public string Family { get; }

        /// <summary>The rule as the reader reports it: Life's as <c>B…/S…</c>, Generations' as
        /// written, and Larger than Life's without its whitespace.</summary>
        public string Rule { get; }

        /// <summary>The rule's number of states: 2 for Life.</summary>
        public int States { get; }

        public BoundedGrid? Board { get; }

        public PatternMetadata Metadata { get; }

        /// <summary>The <c>#L</c> lines' values joined, whitespace removed.</summary>
        public string Data { get; }

        /// <summary>Life files hold two states; the other families' files are multi-state.</summary>
        public bool TwoState => Family == "Life";
    }

    /// <summary>The cell data's decoded size and the inclusive box of its non-zero cells.</summary>
    internal readonly struct MCellExtent
    {
        public MCellExtent(BigInteger width, BigInteger height, CellBox? live)
        {
            Width = width;
            Height = height;
            Live = live;
        }

        public BigInteger Width { get; }

        public BigInteger Height { get; }

        public CellBox? Live { get; }
    }

    /// <summary>Receives each run of a non-zero state: (x, y, length, state).</summary>
    internal delegate void MCellRun(BigInteger x, BigInteger y, BigInteger length, int state);

    /// <summary>
    /// MCell files (<c>.mcl</c>) of the Life, Generations and Larger than Life families
    /// (spec/formats.md "MCell"): <c>#MCell</c> and a version, then <c>#GAME</c> (the family),
    /// <c>#RULE</c> (the rule, perhaps split over several lines), <c>#BOARD</c> and <c>#WRAP</c>
    /// (a world), <c>#D</c> (comments) and <c>#L</c> (cell data in extended RLE without a header).
    /// <see cref="PatternFiles"/> builds grids and extents on the reader here, both HashLife
    /// universes read through it, and <see cref="Patterns.McellEncode"/> writes a grid. The
    /// Python reference's heaton_life.init.mcell.
    /// </summary>
    internal static class MCell
    {
        /// <summary>The MCell families this library reads and writes.</summary>
        internal static readonly string[] Families = { "Life", "Generations", "Larger than Life" };

        /// <summary>The version the writer puts on its <c>#MCell</c> line: the one the format's
        /// description documents.</summary>
        internal const string Version = "4.00";

        private const int LineWidth = 70; // characters of cell data on one #L line
        private const long RunCap = 1L << 40; // a run past any editing box, for the universes' checks

        internal static FormatException Error(string reason) => new FormatException("invalid MCell file: " + reason);

        private static bool AsciiEquals(string a, string b)
        {
            if (a.Length != b.Length)
                return false;
            for (int i = 0; i < a.Length; i++)
            {
                char x = a[i], y = b[i];
                if (x >= 'A' && x <= 'Z')
                    x = (char)(x + 32);
                if (y >= 'A' && y <= 'Z')
                    y = (char)(y + 32);
                if (x != y)
                    return false;
            }
            return true;
        }

        private static bool IsDigits(string text)
        {
            if (text.Length == 0)
                return false;
            foreach (char c in text)
            {
                if (c < '0' || c > '9')
                    return false;
            }
            return true;
        }

        private static string WithoutSpace(string text)
        {
            var sb = new StringBuilder(text.Length);
            foreach (char c in text)
            {
                if (!TextLines.IsSpace(c))
                    sb.Append(c);
            }
            return sb.ToString();
        }

        /// <summary>A stripped line's keyword (its text up to its first whitespace) and value.</summary>
        private static void Keyword(string line, out string keyword, out string value)
        {
            for (int i = 0; i < line.Length; i++)
            {
                if (TextLines.IsSpace(line[i]))
                {
                    keyword = line.Substring(0, i);
                    value = TextLines.Strip(line.Substring(i));
                    return;
                }
            }
            keyword = line;
            value = "";
        }

        private static string LifeRule(string text)
        {
            int slash = text.IndexOf('/');
            bool digits = slash >= 0 && text.IndexOf('/', slash + 1) < 0;
            for (int i = 0; digits && i < text.Length; i++)
            {
                if (i != slash && (text[i] < '0' || text[i] > '8'))
                    digits = false;
            }
            if (!digits)
                throw Error($"a Life rule is survival/birth digits, such as 23/3, not '{text}'");
            return PatternFiles.LifeRule(text);
        }

        /// <summary>The rule a family reads from <paramref name="text"/>, as reported, and its
        /// number of states.</summary>
        private static string FamilyRule(string family, string text, out int states)
        {
            if (family == "Life")
            {
                states = 2;
                return LifeRule(text);
            }
            if (family == "Generations")
            {
                string[] parts = text.Split('/');
                if (parts.Length != 3 || (parts[0].Length > 0 && !IsDigits(parts[0]))
                    || (parts[1].Length > 0 && !IsDigits(parts[1])) || !IsDigits(parts[2]))
                    throw Error(
                        $"a Generations rule is survival/birth/states digits, such as 345/2/4, not '{text}'");
                if (!GenerationsRule.TryCompile(text, out GenerationsRule? generations, out string? reason))
                    throw Error($"invalid Generations rule '{text}': {reason} (spec/generations.md)");
                states = generations.States;
                return text;
            }
            string compact = WithoutSpace(text);
            if (!LtlRule.TryParse(compact, out LtlRule? ltl, out string? why))
                throw Error($"invalid Larger than Life rule '{compact}': {why} (spec/ltl.md)");
            states = ltl!.States;
            return compact;
        }

        private static (int Width, int Height) Board(string value)
        {
            int at = value.Length;
            for (int i = 0; i < value.Length; i++)
            {
                if (value[i] == 'x' || value[i] == 'X')
                {
                    at = i;
                    break;
                }
            }
            string width = TextLines.Strip(value.Substring(0, at));
            string height = at < value.Length ? TextLines.Strip(value.Substring(at + 1)) : "";
            if (IsDigits(width) && IsDigits(height))
            {
                BigInteger w = BigInteger.Parse(width, NumberStyles.None, CultureInfo.InvariantCulture);
                BigInteger h = BigInteger.Parse(height, NumberStyles.None, CultureInfo.InvariantCulture);
                if (w > 0 && w <= BoundedGrid.MaxSide && h > 0 && h <= BoundedGrid.MaxSide)
                    return ((int)w, (int)h);
            }
            throw Error($"#BOARD is <width>x<height>, not '{value}'");
        }

        /// <summary>
        /// An MCell file's lines, checked in spec/formats.md's order: the lines top to bottom,
        /// then the family, the rule, <c>#BOARD</c>, <c>#WRAP</c>. The cell data is checked when
        /// it is walked (<see cref="Runs"/>). Any problem throws <see cref="FormatException"/>,
        /// <c>invalid MCell file: &lt;reason&gt;</c>.
        /// </summary>
        internal static MCellHeader ReadHeader(string text)
        {
            List<string> lines = TextLines.Split(text);
            int first = -1;
            for (int i = 0; i < lines.Count && first < 0; i++)
            {
                if (TextLines.Strip(lines[i]).Length > 0)
                    first = i;
            }
            if (first < 0 || !TextLines.Strip(lines[first]).StartsWith("#MCell", StringComparison.Ordinal))
                throw Error("the first line does not start with '#MCell'");
            string game = "Life";
            var rules = new StringBuilder();
            bool ruled = false;
            string? board = null, wrap = null;
            var notes = new MetadataReader();
            var data = new StringBuilder();
            for (int i = first + 1; i < lines.Count; i++)
            {
                string stripped = TextLines.Strip(lines[i]);
                if (stripped.Length == 0)
                    continue;
                if (stripped[0] != '#')
                    throw Error($"line {i + 1} does not start with '#'");
                Keyword(stripped, out string keyword, out string value);
                switch (keyword)
                {
                    case "#GAME":
                        game = value;
                        break;
                    case "#RULE":
                        rules.Append(value);
                        ruled = true;
                        break;
                    case "#BOARD":
                        board = value;
                        break;
                    case "#WRAP":
                        wrap = value;
                        break;
                    case "#D":
                        notes.Comment(value);
                        break;
                    case "#L":
                        data.Append(value);
                        break;
                }
            }
            string? family = null;
            foreach (string known in Families)
            {
                if (AsciiEquals(known, game))
                    family = known;
            }
            if (family == null)
                throw Error($"the family '{game}' is not read here (Life, Generations and Larger than Life are)");
            string rule = FamilyRule(family, ruled ? rules.ToString() : "23/3", out int states);
            (int Width, int Height)? size = board == null ? null : Board(board);
            if (wrap != null && wrap != "0" && wrap != "1")
                throw Error($"#WRAP is 0 or 1, not '{wrap}'");
            BoundedGrid? world = null;
            if (size != null)
            {
                var topology = new Topology(wrap == "0" ? Boundary.Dead : Boundary.Torus);
                world = new BoundedGrid(size.Value.Width, size.Value.Height, topology);
            }
            return new MCellHeader(family, rule, states, world, notes.Result(), WithoutSpace(data.ToString()));
        }

        /// <summary>
        /// Walk the cell data (spec/formats.md "MCell", "Cell data"), handing each run of a
        /// non-zero state to <paramref name="emit"/> (a Life file's states as 1), and give its
        /// extent. Every problem in the data throws <see cref="FormatException"/>, the first one
        /// met from the data's start.
        /// </summary>
        internal static MCellExtent Runs(MCellHeader header, MCellRun? emit)
        {
            string data = header.Data;
            int states = header.States;
            bool life = header.TwoState;
            int n = data.Length;
            BigInteger x = BigInteger.Zero, y = BigInteger.Zero, width = BigInteger.Zero;
            bool items = false, any = false;
            BigInteger x0 = 0, y0 = 0, x1 = 0, y1 = 0;
            int i = 0;
            while (i < n)
            {
                int j = i;
                while (j < n && data[j] >= '0' && data[j] <= '9')
                    j++;
                if (j == n)
                    throw Error("a run count in the cell data has no state or '$' after it");
                BigInteger count = j > i
                    ? BigInteger.Parse(data.Substring(i, j - i), NumberStyles.None, CultureInfo.InvariantCulture)
                    : BigInteger.One;
                char tag = data[j];
                items = true;
                if (tag == '$')
                {
                    if (!count.IsZero)
                    {
                        y += count;
                        x = BigInteger.Zero;
                    }
                    i = j + 1;
                    continue;
                }
                int state;
                if (tag == '.')
                {
                    state = 0;
                    i = j + 1;
                }
                else if (tag >= 'A' && tag <= 'X')
                {
                    state = tag - 'A' + 1;
                    i = j + 1;
                }
                else if (tag >= 'a' && tag <= 'j')
                {
                    if (j + 1 == n || data[j + 1] < 'A' || data[j + 1] > 'X')
                        throw Error($"'{tag}' in the cell data has no state letter A to X after it");
                    state = 24 * (tag - 'a' + 1) + (data[j + 1] - 'A' + 1);
                    if (state > 255)
                        throw Error($"the cell data's state {state} is past 255");
                    i = j + 2;
                }
                else
                {
                    throw Error($"'{tag}' in the cell data is no run count, state or '$'");
                }
                if (!life && state >= states)
                    throw Error($"the cell data's state {state} is past the rule's {states} states");
                if (count.IsZero)
                    continue;
                if (state != 0)
                {
                    BigInteger last = x + count - 1;
                    if (!any)
                    {
                        x0 = x;
                        y0 = y;
                        x1 = last;
                        any = true;
                    }
                    else
                    {
                        x0 = BigInteger.Min(x0, x);
                        x1 = BigInteger.Max(x1, last);
                    }
                    y1 = y;
                    emit?.Invoke(x, y, count, life ? 1 : state);
                }
                x += count;
                width = BigInteger.Max(width, x);
            }
            return new MCellExtent(width, items ? y + 1 : BigInteger.Zero, any ? new CellBox(x0, y0, x1, y1) : (CellBox?)null);
        }

        /// <summary>
        /// Where a board's pattern and world sit (spec/formats.md "Bounded grids"): the pattern's
        /// top-left cell (its decoded size centered on the origin) and the world's (centered
        /// too). A live cell past the world throws <see cref="FormatException"/>.
        /// </summary>
        internal static void Placement(
            BoundedGrid world, MCellExtent extent, out BigInteger x0, out BigInteger y0, out BigInteger left,
            out BigInteger top)
        {
            left = -(world.Width / 2);
            top = -(world.Height / 2);
            x0 = -BigInteger.Divide(extent.Width, 2);
            y0 = -BigInteger.Divide(extent.Height, 2);
            if (extent.Live is CellBox live
                && (x0 + live.X0 < left || y0 + live.Y0 < top
                    || x0 + live.X1 >= left + world.Width || y0 + live.Y1 >= top + world.Height))
                throw Error($"the pattern reaches past its board ({world.Suffix})");
        }

        /// <summary>Why an unbounded universe refuses a file with a board (spec/formats.md).</summary>
        internal static string BoardRefusal(BoundedGrid world)
            => $"the unbounded universe has no bounded grid (the MCell board '{world.Suffix}'): "
                + "open the file in a grid world (spec/topology.md)";

        /// <summary>A run's coordinates for the universes' editing-box check: saturated, so a run
        /// past any box stays past it.</summary>
        internal static long Capped(BigInteger value) => (long)BigInteger.Max(-RunCap, BigInteger.Min(RunCap, value));

        // ---- writing ----------------------------------------------------------------------

        /// <summary><c>B&lt;birth&gt;/S&lt;survival&gt;</c> with digits only as
        /// <c>&lt;survival&gt;/&lt;birth&gt;</c>, else null.</summary>
        private static string? SurvivalBirth(string canonical)
        {
            int at = canonical.IndexOf("/S", StringComparison.Ordinal);
            if (at < 0 || canonical.Length == 0 || canonical[0] != 'B')
                return null;
            string birth = canonical.Substring(1, at - 1), survival = canonical.Substring(at + 2);
            foreach (char c in birth + survival)
            {
                if (c < '0' || c > '8')
                    return null;
            }
            return survival + "/" + birth;
        }

        /// <summary>The family, the <c>#RULE</c> text and the number of states MCell writes
        /// <paramref name="rule"/> with; a rule no family holds throws.</summary>
        private static (string Family, string Rule, int States) WriterRule(string rule)
        {
            string text = PatternFiles.LifeRule(rule); // 23/3 is B3/S23, as the RLE encoder reads it
            if (RuleString.TryCompile(text, true, out LifeRule? life, out _))
            {
                string? written = life.Variant == RuleVariant.None ? SurvivalBirth(life.Canonical) : null;
                if (written != null)
                    return ("Life", written, 2);
                throw new ArgumentException($"no MCell family holds the rule '{text}'");
            }
            if (GenerationsRule.TryCompile(text, out GenerationsRule? generations, out _))
            {
                string? written = SurvivalBirth(generations.Life.Canonical);
                if (written != null)
                    return ("Generations", written + "/" + generations.States.ToString(CultureInfo.InvariantCulture), generations.States);
                throw new ArgumentException($"no MCell family holds the rule '{text}'");
            }
            if (LtlRule.TryParse(text, out LtlRule? ltl, out _))
                return ("Larger than Life", ltl!.Canonical, ltl.States);
            throw new ArgumentException($"no MCell family holds the rule '{text}'");
        }

        private static string Tag(int state)
        {
            if (state == 0)
                return ".";
            if (state <= 24)
                return ((char)('A' + state - 1)).ToString();
            return new string(new[] { (char)('a' + (state - 1) / 24 - 1), (char)('A' + (state - 1) % 24) });
        }

        private static string Run(int length, string tag)
            => length == 1 ? tag : length.ToString(CultureInfo.InvariantCulture) + tag;

        /// <summary>The cell data's items: each row's runs without its trailing dead cells, row
        /// ends as <c>k$</c>, and the first row padded to the full width when no row reaches it.</summary>
        private static List<string> Items(ReadOnlySpan<byte> cells, int width, int height)
        {
            var ends = new int[height];
            int widest = 0;
            for (int y = 0; y < height; y++)
            {
                for (int x = width - 1; x >= 0; x--)
                {
                    if (cells[y * width + x] != 0)
                    {
                        ends[y] = x + 1;
                        break;
                    }
                }
                widest = Math.Max(widest, ends[y]);
            }
            bool pad = widest < width;
            var items = new List<string>();
            int pending = 0;
            for (int y = 0; y < height; y++)
            {
                int end = pad && y == 0 ? width : ends[y];
                if (y > 0)
                    pending++;
                if (end == 0)
                    continue;
                if (pending > 0)
                {
                    items.Add(Run(pending, "$"));
                    pending = 0;
                }
                int x = 0;
                while (x < end)
                {
                    byte state = cells[y * width + x];
                    int run = 1;
                    while (x + run < end && cells[y * width + x + run] == state)
                        run++;
                    items.Add(Run(run, Tag(state)));
                    x += run;
                }
            }
            if (pending > 0)
                items.Add(Run(pending, "$"));
            return items;
        }

        /// <summary>
        /// A grid as an MCell file (spec/formats.md "MCell", "Writing"): the family
        /// <paramref name="rule"/> belongs to, the board and its wrap when a
        /// <paramref name="topology"/> is given (the torus or the plane), the metadata as
        /// <c>#D</c> lines (name, author, comments), and the cell data, read back as the same
        /// grid. A rule no MCell family holds, any other topology, a state past the rule's, or a
        /// grid without rows or columns throws <see cref="ArgumentException"/>.
        /// </summary>
        internal static string Encode(
            ReadOnlySpan<byte> cells, int width, int height, string rule, PatternMetadata? metadata, Topology? topology)
        {
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            if (width <= 0 || height <= 0)
                throw new ArgumentException("an MCell pattern has at least one row and one column");
            if (cells.Length != (long)width * height)
                throw new ArgumentException($"expected {(long)width * height} cells, got {cells.Length}");
            var (family, written, states) = WriterRule(rule);
            int top = 0;
            foreach (byte cell in cells)
                top = Math.Max(top, cell);
            if (top >= states)
                throw new ArgumentException($"the cells hold state {top}, past the rule's {states} states");
            var sb = new StringBuilder();
            sb.Append("#MCell ").Append(Version).Append('\n');
            sb.Append("#GAME ").Append(family).Append('\n');
            sb.Append("#RULE ").Append(written).Append('\n');
            if (topology != null)
            {
                Topology t = topology.Value;
                var world = new BoundedGrid(width, height, t);
                if (t.Shift != 0 || (t.Boundary != Boundary.Torus && t.Boundary != Boundary.Dead))
                    throw new ArgumentException($"an MCell board is a torus or the plane, not '{world.Suffix}'");
                sb.Append("#BOARD ").Append(width.ToString(CultureInfo.InvariantCulture)).Append('x')
                    .Append(height.ToString(CultureInfo.InvariantCulture)).Append('\n');
                sb.Append("#WRAP ").Append(t.Boundary == Boundary.Torus ? '1' : '0').Append('\n');
            }
            foreach (string line in PatternMetadata.Lines(metadata))
                sb.Append("#D").Append(line, 2, line.Length - 2).Append('\n');
            var current = new StringBuilder();
            foreach (string item in Items(cells, width, height))
            {
                if (current.Length > 0 && current.Length + item.Length > LineWidth)
                {
                    sb.Append("#L ").Append(current).Append('\n');
                    current.Clear();
                }
                current.Append(item);
            }
            sb.Append("#L ").Append(current).Append('\n');
            return sb.ToString();
        }
    }
}
