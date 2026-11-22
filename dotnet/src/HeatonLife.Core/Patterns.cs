using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text;

namespace HeatonLife
{
    /// <summary>
    /// How <see cref="Patterns.Stamp(byte[], int, int, int, ReadOnlySpan{byte}, int, int, int, int, bool, StampMode)"/>
    /// combines a pattern cell p with the target cell t it lands on (spec/patterns.md "Extract and stamp").
    /// </summary>
    public enum StampMode
    {
        /// <summary>t = p: every cell lands (opaque).</summary>
        Copy,

        /// <summary>Cells equal to the transparent value 0 are skipped; the rest land. The same as
        /// <c>transparent: true</c>.</summary>
        Or,

        /// <summary>t = t xor p, for two-state (0/1) cells: each cell toggles under a live pattern cell.</summary>
        Xor,

        /// <summary>t = t and p, for two-state (0/1) cells: a cell stays alive only where the pattern
        /// is alive too.</summary>
        And,
    }

    /// <summary>A decoded RLE pattern: row-major cells plus the header's rule, if any.</summary>
    public sealed class RlePattern
    {
        public RlePattern(byte[] cells, int width, int height, string? rule)
            : this(cells, width, height, rule, null)
        {
        }

        public RlePattern(byte[] cells, int width, int height, string? rule, BoundedGrid? boundedGrid)
        {
            Cells = cells;
            Width = width;
            Height = height;
            Rule = rule;
            BoundedGrid = boundedGrid;
        }

        public byte[] Cells { get; }
        public int Width { get; }
        public int Height { get; }
        /// <summary>The header's rule string without a bounded-grid suffix, or null when the RLE
        /// carried no rule.</summary>
        public string? Rule { get; }

        /// <summary>The world the header's bounded-grid suffix names (spec/topology.md), or null.
        /// The cells are the pattern as decoded; <see cref="PatternFiles.Read(string, long?, bool)"/>
        /// places it in its world.</summary>
        public BoundedGrid? BoundedGrid { get; }
    }

    /// <summary>
    /// What decoding an RLE text would give, found without making a grid (spec/patterns.md
    /// "Extent"). Every number is exact, however large the file's run counts are.
    /// </summary>
    public sealed class RleExtent
    {
        public RleExtent(
            BigInteger width, BigInteger height, CellBox? live, BigInteger population, string? rule, bool extended)
            : this(width, height, live, population, rule, extended, null)
        {
        }

        public RleExtent(
            BigInteger width, BigInteger height, CellBox? live, BigInteger population, string? rule, bool extended,
            BoundedGrid? boundedGrid)
        {
            Width = width;
            Height = height;
            Live = live;
            Population = population;
            Rule = rule;
            Extended = extended;
            BoundedGrid = boundedGrid;
        }

        /// <summary>The decoded grid's width: the larger of what the header declares and the body holds.</summary>
        public BigInteger Width { get; }
        public BigInteger Height { get; }
        /// <summary>The inclusive extremes of the non-zero cells, or null without any.</summary>
        public CellBox? Live { get; }
        /// <summary>How many cells are non-zero.</summary>
        public BigInteger Population { get; }

        /// <summary>The header's rule without a bounded-grid suffix, or null.</summary>
        public string? Rule { get; }
        public bool Extended { get; }

        /// <summary>The world the header's bounded-grid suffix names (spec/topology.md), or null.</summary>
        public BoundedGrid? BoundedGrid { get; }
    }

    /// <summary>
    /// Pattern operations (spec/patterns.md): RLE in both common dialects,
    /// transforms, and extract/stamp with the spec'd wrap/clip/transparency semantics.
    /// Patterns are family-bound artifacts — see <see cref="Compatible"/> — and every
    /// operation here is bit-exact against vectors/patterns/.
    /// </summary>
    public static class Patterns
    {
        // ---- RLE ----------------------------------------------------------------

        /// <summary>
        /// The decode limit's default (spec/patterns.md "The decode limit"): 67,108,864 cells,
        /// an 8192 × 8192 grid.
        /// </summary>
        public const long DefaultMaxCells = 1L << 26;

        /// <summary>
        /// What <see cref="RleDecode(string)"/> would give, without making it: the grid's size,
        /// the non-zero cells' box, and how many there are. A few bytes of RLE can describe more
        /// cells than memory holds (a run of a billion, a header that declares one), so measure
        /// a file that came from outside before decoding it.
        /// </summary>
        public static RleExtent RleMeasure(string text)
        {
            ParseRle(text, out BigInteger declaredW, out BigInteger declaredH, out string? rule,
                out string body, out bool extended, out BoundedGrid? bounded);
            return Measure(declaredW, declaredH, rule, body, extended, bounded);
        }

        /// <summary>Decodes under the default limit, <see cref="DefaultMaxCells"/>.</summary>
        public static RlePattern RleDecode(string text) => RleDecode(text, DefaultMaxCells);

        /// <summary>
        /// Decodes RLE text. The extent is found first, and a grid past
        /// <paramref name="maxCells"/> (width × height) is refused before any memory is asked
        /// for; null lifts the limit (an array still holds at most 2^31 − 1 cells). With
        /// <paramref name="trim"/> the grid is only the non-zero cells' bounding box: the
        /// header's size and any dead margin are dropped, the limit applies to that box, and a
        /// pattern with no such cell is an error.
        /// </summary>
        public static RlePattern RleDecode(string text, long? maxCells, bool trim = false)
        {
            ParseRle(text, out BigInteger declaredW, out BigInteger declaredH, out string? rule,
                out string body, out bool extended, out BoundedGrid? bounded);
            RleExtent extent = Measure(declaredW, declaredH, rule, body, extended, bounded);
            BigInteger left = BigInteger.Zero, top = BigInteger.Zero;
            BigInteger width = extent.Width, height = extent.Height;
            if (trim)
            {
                if (extent.Live == null)
                    throw new ArgumentException("RLE pattern has no live cells");
                CellBox live = extent.Live.Value;
                left = live.X0;
                top = live.Y0;
                width = live.X1 - live.X0 + 1;
                height = live.Y1 - live.Y0 + 1;
            }
            else if (width.IsZero || height.IsZero)
            {
                throw new ArgumentException("RLE pattern has no cells");
            }
            BigInteger area = width * height;
            if (maxCells != null && area > maxCells.Value)
                throw new ArgumentException(
                    $"RLE pattern is {width} x {height} cells, past the limit of {maxCells.Value}");
            if (area > int.MaxValue)
                throw new ArgumentException(
                    $"RLE pattern is {width} x {height} cells, more than one array holds");

            int w = (int)width;
            var cells = new byte[(int)area];
            foreach (RleRun run in Walk(body, extended))
            {
                if (run.State <= 0)
                    continue;
                int at = (int)(run.Y - top) * w + (int)(run.X - left);
                cells.AsSpan(at, (int)run.Length).Fill((byte)run.State);
            }
            return new RlePattern(cells, w, (int)height, rule, bounded);
        }

        /// <summary>The world an RLE header's bounded-grid suffix names, or null, read from the
        /// header alone (no cell is walked).</summary>
        internal static BoundedGrid? RleBoundedGrid(string text)
        {
            foreach (string raw in TextLines.Split(text))
            {
                string line = TextLines.Strip(raw);
                if (line.Length == 0 || line[0] == '#')
                    continue;
                if (!TryParseHeader(line, out _, out _, out string? rule) || rule == null)
                    return null;
                BoundedGrid.SplitRule(rule, out BoundedGrid? bounded);
                return bounded;
            }
            return null;
        }

        /// <summary>
        /// Writes the non-zero runs of an RLE text into <paramref name="world"/> (row-major,
        /// <paramref name="worldWidth"/> wide), each pattern cell (x, y) at (x + dx, y + dy): a
        /// bounded file's pattern placed in its world (spec/formats.md "Bounded grids"). Every
        /// non-zero cell must land inside, as the caller has checked from the extent.
        /// </summary>
        internal static void PlaceRle(string text, byte[] world, int worldWidth, BigInteger dx, BigInteger dy)
        {
            ParseRle(text, out _, out _, out _, out string body, out bool extended, out _);
            foreach (RleRun run in Walk(body, extended))
            {
                if (run.State <= 0)
                    continue;
                int at = (int)(run.Y + dy) * worldWidth + (int)(run.X + dx);
                world.AsSpan(at, (int)run.Length).Fill((byte)run.State);
            }
        }

        /// <summary>An RLE text as (declared width, declared height, rule, body, dialect, bounded
        /// grid): the rule is the header's text before a bounded-grid suffix.</summary>
        private static void ParseRle(
            string text, out BigInteger declaredW, out BigInteger declaredH, out string? rule,
            out string body, out bool extended, out BoundedGrid? bounded)
        {
            var lines = new List<string>();
            foreach (string raw in TextLines.Split(text)) // as the reference's splitlines and strip
            {
                string line = TextLines.Strip(raw);
                if (line.Length > 0 && line[0] != '#')
                    lines.Add(line);
            }
            if (lines.Count == 0)
                throw new ArgumentException("empty RLE input");

            bounded = null;
            if (TryParseHeader(lines[0], out declaredW, out declaredH, out rule))
            {
                body = string.Concat(lines.GetRange(1, lines.Count - 1));
                if (rule != null) // spec/patterns.md "Bounded grids", spec/formats.md "Rules in survival/birth order"
                    rule = PatternFiles.LifeRule(BoundedGrid.SplitRule(rule, out bounded));
            }
            else
            {
                body = string.Concat(lines);
            }

            // Dialect detection (spec/patterns.md): uppercase B/O are dead/alive in
            // two-state files but states 2/15 in extended RLE.
            extended = rule != null && !IsLifelikeRule(rule);
            foreach (char c in body)
            {
                if (c == '.' || (c >= 'A' && c <= 'X' && c != 'B' && c != 'O'))
                {
                    extended = true;
                    break;
                }
            }
        }

        /// <summary>One run of an RLE body; State −1 is the walk's last word: Y is the row count.</summary>
        private readonly struct RleRun
        {
            public RleRun(BigInteger x, BigInteger y, BigInteger length, int state)
            {
                X = x;
                Y = y;
                Length = length;
                State = state;
            }

            public readonly BigInteger X;
            public readonly BigInteger Y;
            public readonly BigInteger Length;
            public readonly int State;
        }

        /// <summary>
        /// The body as runs in file order, dead runs (State 0) included, and last of all a run
        /// of State −1 whose Y is how many rows it has. Measuring and decoding both read this,
        /// so they can't disagree, and neither holds more than a run.
        /// </summary>
        private static IEnumerable<RleRun> Walk(string body, bool extended)
        {
            BigInteger x = BigInteger.Zero, y = BigInteger.Zero, count = BigInteger.Zero;
            foreach (char c in body)
            {
                if (c >= '0' && c <= '9')
                {
                    count = count * 10 + (c - '0');
                }
                else if (c == 'b' || c == '.' || (!extended && c == 'B'))
                {
                    BigInteger length = BigInteger.Max(count, BigInteger.One);
                    yield return new RleRun(x, y, length, 0);
                    x += length;
                    count = BigInteger.Zero;
                }
                else if (c == 'o' || (!extended && c == 'O'))
                {
                    BigInteger length = BigInteger.Max(count, BigInteger.One);
                    yield return new RleRun(x, y, length, 1);
                    x += length;
                    count = BigInteger.Zero;
                }
                else if (extended && c >= 'A' && c <= 'X')
                {
                    BigInteger length = BigInteger.Max(count, BigInteger.One);
                    yield return new RleRun(x, y, length, c - 'A' + 1); // states 1..24 (B = 2, O = 15)
                    x += length;
                    count = BigInteger.Zero;
                }
                else if (c == '$')
                {
                    x = BigInteger.Zero;
                    y += BigInteger.Max(count, BigInteger.One);
                    count = BigInteger.Zero;
                }
                else if (c == '!')
                {
                    break;
                }
                else if (TextLines.IsSpace(c))
                {
                    continue;
                }
                else
                {
                    throw new ArgumentException($"unsupported RLE tag: '{c}'");
                }
            }
            yield return new RleRun(BigInteger.Zero, y + 1, BigInteger.Zero, -1);
        }

        private static RleExtent Measure(
            BigInteger declaredW, BigInteger declaredH, string? rule, string body, bool extended,
            BoundedGrid? bounded)
        {
            BigInteger longest = BigInteger.Zero, rows = BigInteger.Zero, population = BigInteger.Zero;
            bool any = false;
            BigInteger x0 = BigInteger.Zero, y0 = BigInteger.Zero, x1 = BigInteger.Zero, y1 = BigInteger.Zero;
            foreach (RleRun run in Walk(body, extended))
            {
                if (run.State < 0)
                {
                    rows = run.Y;
                    break;
                }
                longest = BigInteger.Max(longest, run.X + run.Length);
                if (run.State == 0)
                    continue;
                population += run.Length;
                BigInteger last = run.X + run.Length - 1;
                if (!any)
                {
                    any = true;
                    x0 = run.X;
                    y0 = run.Y;
                    x1 = last;
                }
                else
                {
                    x0 = BigInteger.Min(x0, run.X);
                    x1 = BigInteger.Max(x1, last);
                }
                y1 = run.Y; // rows only go down
            }
            return new RleExtent(
                BigInteger.Max(declaredW, longest), BigInteger.Max(declaredH, rows),
                any ? new CellBox(x0, y0, x1, y1) : (CellBox?)null, population, rule, extended, bounded);
        }

        /// <summary>
        /// The pattern's name (<c>#N</c>), author (<c>#O</c>), and comment lines (<c>#C</c>,
        /// <c>#c</c>) in file order (spec/formats.md "Metadata"). A <c>#CXRLE</c> first line is not
        /// a comment.
        /// </summary>
        public static PatternMetadata RleMetadata(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            var reader = new MetadataReader();
            bool first = true;
            foreach (string raw in TextLines.Split(text))
            {
                string line = TextLines.Strip(raw);
                if (line.Length == 0)
                    continue;
                if (first)
                {
                    first = false;
                    if (line.StartsWith("#CXRLE", StringComparison.Ordinal))
                        continue;
                }
                if (line[0] == '#')
                    reader.HashLine(line);
            }
            return reader.Result();
        }

        /// <summary>Whether a stripped line is an RLE header as the decoders read one
        /// (spec/formats.md "Detection").</summary>
        internal static bool IsRleHeader(string line) => TryParseHeader(line, out _, out _, out _);

        /// <summary>The <c>#CXRLE</c> first line's position and generation, or zeros without one.</summary>
        internal static bool Cxrle(string text, out BigInteger x, out BigInteger y, out BigInteger generation)
        {
            x = y = generation = BigInteger.Zero;
            foreach (string raw in TextLines.Split(text))
            {
                string line = TextLines.Strip(raw);
                if (line.Length == 0)
                    continue;
                return line.StartsWith("#CXRLE", StringComparison.Ordinal) && ReadCxrle(line, ref x, ref y, ref generation);
            }
            return false;
        }

        /// <summary>Canonical RLE; dialect chosen by content (cells above 24 are unencodable). The
        /// header names a Life-like rule in its canonical form (spec/rules.md), so it reads back as
        /// the same rule (one in survival/birth order, <c>23/3</c>, as <c>B3/S23</c>), and any other
        /// rule as given.</summary>
        public static string RleEncode(ReadOnlySpan<byte> cells, int width, int height, string rule = "B3/S23")
            => RleEncode(cells, width, height, rule, null);

        /// <summary>Canonical RLE with <paramref name="metadata"/>'s <c>#N</c>, <c>#O</c> and
        /// <c>#C</c> lines before the header (spec/formats.md "Metadata").</summary>
        public static string RleEncode(
            ReadOnlySpan<byte> cells, int width, int height, string rule, PatternMetadata? metadata)
            => RleEncode(cells, width, height, rule, metadata, null);

        /// <summary>
        /// Canonical RLE of a whole world with a <paramref name="topology"/> (spec/topology.md):
        /// the header's rule carries the world's bounded-grid suffix, <c>rule = B3/S23:T30,20</c>.
        /// Without one (null) it is <see cref="RleEncode(ReadOnlySpan{byte}, int, int, string, PatternMetadata?)"/>.
        /// </summary>
        public static string RleEncode(
            ReadOnlySpan<byte> cells, int width, int height, string rule, PatternMetadata? metadata,
            Topology? topology)
        {
            List<string> notes = PatternMetadata.Lines(metadata);
            string suffix = topology == null ? "" : new BoundedGrid(width, height, topology.Value).Suffix;
            if (cells.Length != width * height)
                throw new ArgumentException($"expected {width * height} cells, got {cells.Length}");
            int top = 0;
            foreach (byte cell in cells)
                top = Math.Max(top, cell);
            if (top > 24)
                throw new ArgumentException(
                    $"cell value {top} not RLE-encodable (extended RLE tops out at 24)");
            bool multistate = top > 1;

            var tokens = new List<string>();
            for (int y = 0; y < height; y++)
            {
                int runVal = -1;
                int runLen = 0;
                for (int x = 0; x < width; x++)
                {
                    int v = cells[y * width + x];
                    if (v == runVal)
                    {
                        runLen++;
                    }
                    else
                    {
                        if (runLen > 0)
                            tokens.Add(Run(runLen, runVal, multistate));
                        runVal = v;
                        runLen = 1;
                    }
                }
                if (runVal > 0) // trailing dead runs in a row are omitted by convention
                    tokens.Add(Run(runLen, runVal, multistate));
                tokens.Add(y < height - 1 ? "$" : "!");
            }
            tokens = RowEndRuns(tokens);

            var body = new List<string>();
            string line = "";
            foreach (string token in tokens)
            {
                if (line.Length + token.Length > 70)
                {
                    body.Add(line);
                    line = "";
                }
                line += token;
            }
            body.Add(line);

            var sb = new StringBuilder();
            foreach (string note in notes)
                sb.Append(note).Append('\n');
            sb.Append("x = ").Append(width).Append(", y = ").Append(height)
              .Append(", rule = ")
              .Append(RuleString.TryCompile(PatternFiles.LifeRule(rule), true, out LifeRule? life, out _)
                  ? life.Canonical
                  : rule)
              .Append(suffix);
            foreach (string bodyLine in body)
                sb.Append('\n').Append(bodyLine);
            sb.Append('\n');
            return sb.ToString();
        }

        // ---- RLE in the unbounded universe (spec/patterns.md "RLE in the unbounded universe") --

        private const long RunCap = 1L << 40; // run counts and offsets saturate here, far past the editing box

        /// <summary>
        /// A HashLife universe from two-state RLE, streamed run by run into quadtree leaves so a
        /// file never becomes a dense grid. <c>#CXRLE Pos=x,y Gen=n</c> on the first line places
        /// the pattern's top-left cell (at (0, 0) without it) and sets the generation; any other
        /// <c>#</c> line is a comment. The rule is the header's, or B3/S23. An extended file, a
        /// state above 1, or a cell outside the editing box is refused.
        /// </summary>
        public static HashLife RleToHashLife(string text, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            var universe = new HashLife(maxMemoryMb: maxMemoryMb);
            var (root, level, generation, rule) = BuildRle(universe, text);
            universe.Rule = rule;
            universe.Adopt(root, level, generation);
            return universe;
        }

        /// <summary>
        /// Two-state RLE read into <paramref name="universe"/>'s store without changing the
        /// universe: the pattern's tree, its generation and its rule in canonical form, refused
        /// as <see cref="RleToHashLife"/> refuses it.
        /// </summary>
        internal static (int Root, int Level, BigInteger Generation, string Rule) BuildRle(HashLife universe, string text)
        {
            var lines = new List<string>();
            foreach (string raw in TextLines.Split(text))
            {
                string line = TextLines.Strip(raw);
                if (line.Length > 0)
                    lines.Add(line);
            }
            BigInteger posX = BigInteger.Zero, posY = BigInteger.Zero, generation = BigInteger.Zero;
            if (lines.Count > 0 && lines[0].StartsWith("#CXRLE", StringComparison.Ordinal))
                ReadCxrle(lines[0], ref posX, ref posY, ref generation);
            lines.RemoveAll(line => line[0] == '#');
            string? rule = null;
            if (lines.Count > 0 && TryParseHeader(lines[0], out _, out _, out rule))
                lines.RemoveAt(0);
            if (rule != null)
            {
                rule = PatternFiles.LifeRule(BoundedGrid.SplitRule(rule, out BoundedGrid? bounded));
                if (bounded != null) // spec/patterns.md "RLE in the unbounded universe"
                    throw new FormatException(
                        $"the unbounded universe has no bounded grid ('{bounded.Suffix}' in the rule): open the file in a grid world (spec/topology.md)");
            }
            string body = string.Concat(lines);
            bool extended = rule != null && !IsLifelikeRule(rule);
            foreach (char c in body)
            {
                if (c == '.' || (c >= 'A' && c <= 'X' && c != 'B' && c != 'O'))
                    extended = true;
            }
            if (extended)
                throw new FormatException("HashLife reads two-state RLE only (this file is extended RLE)");
            string canonical = HashLife.CheckedRule(rule ?? "B3/S23");

            const long limit = HashLife.EditLimit;
            bool placed = BigInteger.Abs(posX) <= limit && BigInteger.Abs(posY) <= limit;
            long x0 = placed ? (long)posX : 0, y0 = placed ? (long)posY : 0;
            var blocks = new Dictionary<long, ulong>();
            long width = 0, height = 0, x = 0, y = 0;
            int i = 0;
            while (i < body.Length)
            {
                char c = body[i];
                if (TextLines.IsSpace(c))
                {
                    i++;
                    continue;
                }
                // A token is a run count and a tag (the reference's (\d*)(\S)); a count that
                // whitespace or the end follows leaves its own last digit as the tag.
                long count = 1;
                int start = i;
                while (i < body.Length && body[i] >= '0' && body[i] <= '9')
                    i++;
                if (i > start)
                {
                    if (i == body.Length || TextLines.IsSpace(body[i]))
                        throw new FormatException($"unsupported RLE tag: '{body[i - 1]}'");
                    count = 0;
                    for (int d = start; d < i; d++)
                        count = Math.Min(count * 10 + (body[d] - '0'), RunCap);
                }
                char tag = body[i++];
                if (tag == 'b' || tag == 'B')
                {
                    x = Math.Min(x + count, RunCap);
                }
                else if (tag == 'o' || tag == 'O')
                {
                    width = Math.Max(width, Math.Min(x + count, RunCap));
                    height = Math.Max(height, y + 1);
                    if (count > 0)
                    {
                        // A live cell outside the box dooms the file: refuse it now rather than
                        // spelling out a run that may be astronomically long.
                        if (!placed)
                            throw new ArgumentOutOfRangeException(
                                null, $"#CXRLE Pos={posX},{posY} lies outside the editing box |x|, |y| <= 1,000,000,000");
                        if (x0 + x + count - 1 > limit || y0 + y > limit)
                            HashLife.CheckBox(x0, y0, x0 + x + count - 1, y0 + y);
                        AddRun(blocks, x0 + x, y0 + y - 1, count);
                    }
                    x = Math.Min(x + count, RunCap);
                }
                else if (tag == '$')
                {
                    y = Math.Min(y + count, RunCap);
                    x = 0;
                }
                else if (tag == '!')
                {
                    break;
                }
                else
                {
                    throw new FormatException($"unsupported RLE tag: '{tag}'");
                }
            }
            if (blocks.Count > 0)
                HashLife.CheckBox(x0, y0, x0 + width - 1, y0 + height - 1);
            var (root, level) = universe.Build(() =>
            {
                if (blocks.Count > 0)
                    universe.PasteBlocks(blocks, x0, y0 - 1, x0 + width - 1, y0 + height - 2, HashLifePasteMode.Or);
            });
            return (root, level, generation, canonical);
        }

        /// <summary>Reads a <c>#CXRLE</c> line's fields; true when it gives a <c>Pos</c>.</summary>
        internal static bool ReadCxrle(string line, ref BigInteger posX, ref BigInteger posY, ref BigInteger generation)
        {
            bool placed = false;
            string[] fields = SplitSpace(line);
            for (int f = 1; f < fields.Length; f++)
            {
                string field = fields[f];
                int eq = field.IndexOf('=');
                string key = eq < 0 ? field : field.Substring(0, eq);
                string value = eq < 0 ? "" : field.Substring(eq + 1);
                if (key == "Pos")
                {
                    int comma = value.IndexOf(',');
                    posX = ParseInteger(comma < 0 ? value : value.Substring(0, comma), signed: true);
                    posY = ParseInteger(comma < 0 ? "" : value.Substring(comma + 1), signed: true);
                    placed = true;
                }
                else if (key == "Gen")
                {
                    generation = ParseInteger(value, signed: false);
                }
            }
            return placed;
        }

        private static string[] SplitSpace(string line)
        {
            var parts = new List<string>();
            int i = 0;
            while (i < line.Length)
            {
                if (TextLines.IsSpace(line[i]))
                {
                    i++;
                    continue;
                }
                int start = i;
                while (i < line.Length && !TextLines.IsSpace(line[i]))
                    i++;
                parts.Add(line.Substring(start, i - start));
            }
            return parts.ToArray();
        }

        /// <summary>A <c>#CXRLE</c> number (spec/patterns.md): ASCII digits, after an optional
        /// <c>-</c> where <paramref name="signed"/> (Pos); a generation takes digits only.</summary>
        private static BigInteger ParseInteger(string text, bool signed)
        {
            int i = signed && text.Length > 0 && text[0] == '-' ? 1 : 0;
            string kind = signed ? "an integer" : "a generation in digits";
            if (i == text.Length)
                throw new FormatException($"#CXRLE needs {kind}, got '{text}'");
            for (int j = i; j < text.Length; j++)
            {
                if (text[j] < '0' || text[j] > '9')
                    throw new FormatException($"#CXRLE needs {kind}, got '{text}'");
            }
            BigInteger magnitude = BigInteger.Parse(text.Substring(i), NumberStyles.None, CultureInfo.InvariantCulture);
            return text[0] == '-' ? -magnitude : magnitude;
        }

        /// <summary>Set <paramref name="length"/> cells from tree position (tx, ty) rightward.</summary>
        internal static void AddRun(Dictionary<long, ulong> blocks, long tx, long ty, long length)
        {
            long by = ty >> 3;
            int shift = (int)(ty & 7) * 8;
            while (length > 0)
            {
                long bx = tx >> 3;
                int offset = (int)(tx & 7);
                int take = (int)Math.Min(8 - offset, length);
                long key = HashLife.BlockKey(bx, by);
                blocks.TryGetValue(key, out ulong bits);
                blocks[key] = bits | (((1UL << take) - 1) << (offset + shift));
                tx += take;
                length -= take;
            }
        }

        /// <summary>
        /// The universe as RLE: <c>#CXRLE Pos=x0,y0</c> (with <c> Gen=n</c> past generation 0),
        /// then the canonical encoding of the bounding box — the same tokens and line breaks
        /// <see cref="RleEncode(ReadOnlySpan{byte}, int, int, string)"/> gives that rectangle. A pattern reaching outside the editing
        /// box throws <see cref="InvalidOperationException"/>; Macrocell carries it.
        /// </summary>
        public static string HashLifeToRle(HashLife universe) => HashLifeToRle(universe, null);

        /// <summary>The universe as RLE, <paramref name="metadata"/>'s lines right after the
        /// <c>#CXRLE</c> line (spec/formats.md "Metadata").</summary>
        public static string HashLifeToRle(HashLife universe, PatternMetadata? metadata)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            List<string> notes = PatternMetadata.Lines(metadata);
            var noteText = new StringBuilder();
            foreach (string note in notes)
                noteText.Append(note).Append('\n');
            BigInteger generation = universe.Generation;
            string gen = generation.Sign > 0 ? " Gen=" + generation.ToString(CultureInfo.InvariantCulture) : "";
            CellBox? found = universe.BoundingBox;
            if (found == null)
                return $"#CXRLE Pos=0,0{gen}\n{noteText}x = 0, y = 0, rule = {universe.Rule}\n!\n";
            CellBox box = found.Value;
            const long limit = HashLife.EditLimit;
            if (BigInteger.Abs(box.X0) > limit || BigInteger.Abs(box.X1) > limit
                || BigInteger.Abs(box.Y0) > limit || BigInteger.Abs(box.Y1) > limit)
                throw new InvalidOperationException(
                    $"the pattern {box} reaches outside the editing box |x|, |y| <= 1,000,000,000; "
                    + "RLE can't carry it — save as Macrocell");
            long x0 = (long)box.X0, y0 = (long)box.Y0, x1 = (long)box.X1, y1 = (long)box.Y1;

            // Every row's live runs, built leaf by leaf in x order (leaves never overlap).
            var leaves = new List<(long X, long Y, ulong Bits)>();
            universe.CollectLeaves(leaves);
            leaves.Sort((a, b) => a.Y != b.Y ? a.Y.CompareTo(b.Y) : a.X.CompareTo(b.X));
            var rows = new Dictionary<long, List<long>>(); // y → start, length, start, length, ...
            foreach (var (tx, ty, bits) in leaves)
            {
                for (int r = 0; r < 8; r++)
                {
                    int row = (int)((bits >> (8 * r)) & 0xFF);
                    if (row == 0)
                        continue;
                    long cy = ty + r + 1;
                    if (!rows.TryGetValue(cy, out List<long>? runs))
                    {
                        runs = new List<long>();
                        rows[cy] = runs;
                    }
                    int col = 0;
                    while (col < 8)
                    {
                        if (((row >> col) & 1) == 0)
                        {
                            col++;
                            continue;
                        }
                        int first = col;
                        while (col < 8 && ((row >> col) & 1) != 0)
                            col++;
                        long s = tx + first;
                        int n = runs.Count;
                        if (n > 0 && runs[n - 2] + runs[n - 1] == s)
                            runs[n - 1] += col - first;
                        else
                        {
                            runs.Add(s);
                            runs.Add(col - first);
                        }
                    }
                }
            }

            var text = new StringBuilder();
            text.Append("#CXRLE Pos=").Append(x0.ToString(CultureInfo.InvariantCulture)).Append(',')
                .Append(y0.ToString(CultureInfo.InvariantCulture)).Append(gen).Append('\n');
            text.Append(noteText);
            text.Append("x = ").Append((x1 - x0 + 1).ToString(CultureInfo.InvariantCulture))
                .Append(", y = ").Append((y1 - y0 + 1).ToString(CultureInfo.InvariantCulture))
                .Append(", rule = ").Append(universe.Rule).Append('\n');
            // Live rows only: the gap between two is one k$ token (spec/patterns.md), so the text
            // grows with the live rows, not the box's height.
            var liveRows = new List<long>(rows.Keys);
            liveRows.Sort();
            int lineLength = 0;
            long previous = y0;
            foreach (long cy in liveRows)
            {
                if (cy > y0)
                    AppendToken(text, ref lineLength, cy - previous, '$');
                List<long> runs = rows[cy];
                long pos = x0;
                for (int r = 0; r < runs.Count; r += 2)
                {
                    long start = runs[r], length = runs[r + 1];
                    if (start > pos)
                        AppendToken(text, ref lineLength, start - pos, 'b');
                    AppendToken(text, ref lineLength, length, 'o');
                    pos = start + length;
                }
                previous = cy;
            }
            AppendToken(text, ref lineLength, 1, '!');
            text.Append('\n');
            return text.ToString();
        }

        /// <summary>Write k ≥ 2 consecutive <c>$</c> tokens as one <c>k$</c> (spec/patterns.md
        /// "Encoding"): a run of empty rows costs one token.</summary>
        private static List<string> RowEndRuns(List<string> tokens)
        {
            var result = new List<string>(tokens.Count);
            int ends = 0;
            foreach (string token in tokens)
            {
                if (token == "$")
                {
                    ends++;
                    continue;
                }
                if (ends > 0)
                    result.Add(ends == 1 ? "$" : ends.ToString(CultureInfo.InvariantCulture) + "$");
                ends = 0;
                result.Add(token);
            }
            if (ends > 0)
                result.Add(ends == 1 ? "$" : ends.ToString(CultureInfo.InvariantCulture) + "$");
            return result;
        }

        /// <summary>One run token, wrapped as <see cref="RleEncode(ReadOnlySpan{byte}, int, int, string)"/> wraps: a token that would
        /// pass column 70 starts a new line.</summary>
        private static void AppendToken(StringBuilder text, ref int lineLength, long length, char tag)
        {
            string count = length == 1 ? "" : length.ToString(CultureInfo.InvariantCulture);
            int size = count.Length + 1;
            if (lineLength + size > 70)
            {
                text.Append('\n');
                lineLength = 0;
            }
            text.Append(count).Append(tag);
            lineLength += size;
        }

        // ---- Transforms (channels-aware: 1 = scalar, 2 = Gray-Scott, 3 = RGB) ----

        public static byte[] Rotate90(ReadOnlySpan<byte> cells, int width, int height, int channels = 1)
        {
            var result = new byte[cells.Length];
            RotateInto(cells, result, width, height, channels);
            return result;
        }

        public static double[] Rotate90(ReadOnlySpan<double> cells, int width, int height, int channels = 1)
        {
            var result = new double[cells.Length];
            RotateInto(cells, result, width, height, channels);
            return result;
        }

        /// <summary>Counter-clockwise quarter turn: result[y][x] = cells[x][width−1−y]; undoes
        /// <see cref="Rotate90(ReadOnlySpan{byte}, int, int, int)"/>.</summary>
        public static byte[] Rotate90Ccw(ReadOnlySpan<byte> cells, int width, int height, int channels = 1)
        {
            var result = new byte[cells.Length];
            RotateCcwInto(cells, result, width, height, channels);
            return result;
        }

        /// <summary>Counter-clockwise quarter turn: result[y][x] = cells[x][width−1−y]; undoes
        /// <see cref="Rotate90(ReadOnlySpan{double}, int, int, int)"/>.</summary>
        public static double[] Rotate90Ccw(ReadOnlySpan<double> cells, int width, int height, int channels = 1)
        {
            var result = new double[cells.Length];
            RotateCcwInto(cells, result, width, height, channels);
            return result;
        }

        public static byte[] FlipH(ReadOnlySpan<byte> cells, int width, int height, int channels = 1)
        {
            var result = new byte[cells.Length];
            FlipInto(cells, result, width, height, channels, horizontal: true);
            return result;
        }

        public static double[] FlipH(ReadOnlySpan<double> cells, int width, int height, int channels = 1)
        {
            var result = new double[cells.Length];
            FlipInto(cells, result, width, height, channels, horizontal: true);
            return result;
        }

        public static byte[] FlipV(ReadOnlySpan<byte> cells, int width, int height, int channels = 1)
        {
            var result = new byte[cells.Length];
            FlipInto(cells, result, width, height, channels, horizontal: false);
            return result;
        }

        public static double[] FlipV(ReadOnlySpan<double> cells, int width, int height, int channels = 1)
        {
            var result = new double[cells.Length];
            FlipInto(cells, result, width, height, channels, horizontal: false);
            return result;
        }

        // ---- Extract / stamp -----------------------------------------------------

        /// <summary>Copy a region out of a grid: torus wraps, dead boundaries read 0.</summary>
        public static byte[] Extract(
            ReadOnlySpan<byte> grid, int gridWidth, int gridHeight, int channels,
            int x, int y, int width, int height, bool torus)
        {
            var result = new byte[width * height * channels];
            ExtractInto(grid, result, gridWidth, gridHeight, channels, x, y, width, height, torus);
            return result;
        }

        /// <summary>Copy a region out of a grid: torus wraps, dead boundaries read 0.</summary>
        public static double[] Extract(
            ReadOnlySpan<double> grid, int gridWidth, int gridHeight, int channels,
            int x, int y, int width, int height, bool torus)
        {
            var result = new double[width * height * channels];
            ExtractInto(grid, result, gridWidth, gridHeight, channels, x, y, width, height, torus);
            return result;
        }

        /// <summary>
        /// Write a pattern into a grid in place: torus wraps, dead boundaries clip.
        /// Transparent skips 0-cells (scalar payloads only, per spec).
        /// </summary>
        public static void Stamp(
            byte[] grid, int gridWidth, int gridHeight, int channels,
            ReadOnlySpan<byte> pattern, int patternWidth, int patternHeight,
            int x, int y, bool torus, bool transparent = false)
            => Stamp(
                grid, gridWidth, gridHeight, channels, pattern, patternWidth, patternHeight, x, y, torus,
                transparent ? StampMode.Or : StampMode.Copy);

        /// <summary>
        /// Write a pattern into a grid in place, combining each pattern cell with the target cell
        /// it lands on by <paramref name="mode"/> (spec/patterns.md "Extract and stamp"): torus
        /// wraps, dead boundaries clip, and cells land in row-major order. Every mode but
        /// <see cref="StampMode.Copy"/> needs a scalar payload, and <see cref="StampMode.Xor"/> and
        /// <see cref="StampMode.And"/> need two-state cells: a pattern cell, or a target cell under
        /// the pattern, other than 0 or 1 throws before anything is written.
        /// </summary>
        public static void Stamp(
            byte[] grid, int gridWidth, int gridHeight, int channels,
            ReadOnlySpan<byte> pattern, int patternWidth, int patternHeight,
            int x, int y, bool torus, StampMode mode)
        {
            if (mode != StampMode.Copy && mode != StampMode.Or && mode != StampMode.Xor && mode != StampMode.And)
                throw new ArgumentOutOfRangeException(nameof(mode), mode, "unknown stamp mode");
            if (mode != StampMode.Copy && channels != 1)
                throw new ArgumentException($"stamp mode {mode} is defined for scalar payloads only");
            if (mode == StampMode.Xor || mode == StampMode.And)
            {
                for (int row = 0; row < patternHeight; row++)
                    for (int col = 0; col < patternWidth; col++)
                    {
                        if (pattern[row * patternWidth + col] > 1)
                            throw new ArgumentException($"stamp mode {mode} needs a two-state pattern (cells 0 and 1)");
                        if (TargetIndex(gridWidth, gridHeight, x + col, y + row, torus, out int dst) && grid[dst] > 1)
                            throw new ArgumentException(
                                $"stamp mode {mode} needs two-state cells; ({dst % gridWidth}, {dst / gridWidth}) holds {grid[dst]}");
                    }
            }
            for (int row = 0; row < patternHeight; row++)
                for (int col = 0; col < patternWidth; col++)
                {
                    byte p = pattern[(row * patternWidth + col) * channels];
                    if (mode == StampMode.Or && p == 0)
                        continue;
                    if (!TargetIndex(gridWidth, gridHeight, x + col, y + row, torus, out int dst))
                        continue;
                    if (mode == StampMode.Xor)
                        grid[dst] ^= p;
                    else if (mode == StampMode.And)
                        grid[dst] &= p;
                    else
                        for (int c = 0; c < channels; c++)
                            grid[dst * channels + c] = pattern[(row * patternWidth + col) * channels + c];
                }
        }

        /// <summary>
        /// Write a pattern into a grid in place: torus wraps, dead boundaries clip.
        /// Transparent skips 0.0-cells (scalar payloads only, per spec).
        /// </summary>
        public static void Stamp(
            double[] grid, int gridWidth, int gridHeight, int channels,
            ReadOnlySpan<double> pattern, int patternWidth, int patternHeight,
            int x, int y, bool torus, bool transparent = false)
        {
            if (transparent && channels != 1)
                throw new ArgumentException("transparent stamping is defined for scalar payloads only");
            for (int row = 0; row < patternHeight; row++)
                for (int col = 0; col < patternWidth; col++)
                {
                    if (transparent && pattern[row * patternWidth + col] == 0.0)
                        continue;
                    if (!TargetIndex(gridWidth, gridHeight, x + col, y + row, torus, out int dst))
                        continue;
                    for (int c = 0; c < channels; c++)
                        grid[dst * channels + c] = pattern[(row * patternWidth + col) * channels + c];
                }
        }

        // ---- Planar payloads (Gray-Scott state: all of plane 0, then plane 1) ----
        //
        // Layout adapters over the ops above: the spec defines patterns on cells
        // ((u, v) pairs travel as one cell); these run every plane through the
        // same window so a planar memory layout gets identical semantics.

        /// <summary>
        /// Extract from a planar grid: every plane is copied through the same
        /// window, so the planes travel together (spec/patterns.md — Gray-Scott's
        /// U and V move as one pattern). Result is planar with the same plane order.
        /// </summary>
        public static double[] ExtractPlanes(
            ReadOnlySpan<double> grid, int gridWidth, int gridHeight, int planes,
            int x, int y, int width, int height, bool torus)
        {
            int gridPlane = gridWidth * gridHeight;
            int patternPlane = width * height;
            var result = new double[patternPlane * planes];
            for (int p = 0; p < planes; p++)
            {
                double[] plane = Extract(
                    grid.Slice(p * gridPlane, gridPlane), gridWidth, gridHeight, 1,
                    x, y, width, height, torus);
                Array.Copy(plane, 0, result, p * patternPlane, patternPlane);
            }
            return result;
        }

        /// <summary>
        /// Write a planar pattern into a planar grid in place: torus wraps, dead
        /// boundaries clip. Opaque only — the planar family (Gray-Scott) has no
        /// transparent cell (spec/patterns.md).
        /// </summary>
        public static void StampPlanes(
            double[] grid, int gridWidth, int gridHeight, int planes,
            ReadOnlySpan<double> pattern, int patternWidth, int patternHeight,
            int x, int y, bool torus)
        {
            int gridPlane = gridWidth * gridHeight;
            int patternPlane = patternWidth * patternHeight;
            for (int row = 0; row < patternHeight; row++)
                for (int col = 0; col < patternWidth; col++)
                {
                    if (!TargetIndex(gridWidth, gridHeight, x + col, y + row, torus, out int dst))
                        continue;
                    for (int p = 0; p < planes; p++)
                        grid[p * gridPlane + dst] =
                            pattern[p * patternPlane + row * patternWidth + col];
                }
        }

        /// <summary>Rotate a planar pattern clockwise, every plane together.</summary>
        public static double[] Rotate90Planes(
            ReadOnlySpan<double> cells, int width, int height, int planes)
        {
            int plane = width * height;
            var result = new double[cells.Length];
            for (int p = 0; p < planes; p++)
                Array.Copy(
                    Rotate90(cells.Slice(p * plane, plane), width, height), 0,
                    result, p * plane, plane);
            return result;
        }

        /// <summary>Rotate a planar pattern counter-clockwise, every plane together.</summary>
        public static double[] Rotate90CcwPlanes(
            ReadOnlySpan<double> cells, int width, int height, int planes)
        {
            int plane = width * height;
            var result = new double[cells.Length];
            for (int p = 0; p < planes; p++)
                Array.Copy(
                    Rotate90Ccw(cells.Slice(p * plane, plane), width, height), 0,
                    result, p * plane, plane);
            return result;
        }

        /// <summary>Mirror a planar pattern left-right, every plane together.</summary>
        public static double[] FlipHPlanes(
            ReadOnlySpan<double> cells, int width, int height, int planes)
        {
            int plane = width * height;
            var result = new double[cells.Length];
            for (int p = 0; p < planes; p++)
                Array.Copy(
                    FlipH(cells.Slice(p * plane, plane), width, height), 0,
                    result, p * plane, plane);
            return result;
        }

        /// <summary>Mirror a planar pattern top-bottom, every plane together.</summary>
        public static double[] FlipVPlanes(
            ReadOnlySpan<double> cells, int width, int height, int planes)
        {
            int plane = width * height;
            var result = new double[cells.Length];
            for (int p = 0; p < planes; p++)
                Array.Copy(
                    FlipV(cells.Slice(p * plane, plane), width, height), 0,
                    result, p * plane, plane);
            return result;
        }

        // ---- Region editing (spec/patterns.md "Editing a region") ------------------

        /// <summary>
        /// Throw unless (x0, y0)..(x1, y1) is a region of a width × height grid: an inclusive
        /// rectangle with 0 ≤ x0 ≤ x1 &lt; width and 0 ≤ y0 ≤ y1 &lt; height.
        /// </summary>
        public static void CheckRegion(int width, int height, int x0, int y0, int x1, int y1)
        {
            if (!(0 <= x0 && x0 <= x1 && x1 < width && 0 <= y0 && y0 <= y1 && y1 < height))
                throw new ArgumentOutOfRangeException(
                    null,
                    $"region ({x0}, {y0})..({x1}, {y1}) is not an inclusive rectangle inside the {width}x{height} grid");
        }

        /// <summary>
        /// Random fill: the region of a two-state (0/1, one byte per cell) grid becomes the soup of
        /// a world its size — PCG32 stream 0 seeded with <paramref name="seed"/>, one draw per
        /// cell of the region in row-major order, alive iff draw &lt; ⌊density · 2^32⌋. These are
        /// the draws of <see cref="Seeding.Soup"/> for the region's width and height, and
        /// <see cref="HashLife.FillRandom"/> fills a rectangle of the same size and seed alike.
        /// </summary>
        public static void FillRandom(
            byte[] grid, int gridWidth, int gridHeight, int x0, int y0, int x1, int y1, double density, ulong seed)
        {
            if (grid == null)
                throw new ArgumentNullException(nameof(grid));
            if (grid.Length != (long)gridWidth * gridHeight)
                throw new ArgumentException($"expected {(long)gridWidth * gridHeight} cells, got {grid.Length}");
            CheckRegion(gridWidth, gridHeight, x0, y0, x1, y1);
            ulong threshold = Seeding.Threshold(density);
            var rng = new Pcg32(seed);
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    grid[y * gridWidth + x] = (byte)(rng.NextU32() < threshold ? 1 : 0);
        }

        /// <summary>
        /// The rectangle a quarter turn of the inclusive rectangle about its center lands on
        /// (spec/patterns.md "Editing a region"), for any integers and without turning anything:
        /// the rectangle <see cref="HashLife.RotateRect"/> returns, by the same formula
        /// (spec/hashlife.md "Rectangle transforms"). A grid turns a region onto it by stamping
        /// <see cref="Rotate90(ReadOnlySpan{byte}, int, int, int)"/> (clockwise) or
        /// <see cref="Rotate90Ccw(ReadOnlySpan{byte}, int, int, int)"/> of the region at its
        /// top-left, after clearing the region; a region that isn't square can turn past an edge,
        /// which is the caller's to refuse. Throws <see cref="ArgumentException"/> for an empty
        /// rectangle (x1 &lt; x0 or y1 &lt; y0).
        /// </summary>
        public static CellBox TurnedRect(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1, bool clockwise = true)
        {
            if (x1 < x0 || y1 < y0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
            (BigInteger s, BigInteger d) = TurnCenter(x0, y0, x1, y1);
            return clockwise
                ? new CellBox(s - y1, x0 + d, s - y0, x1 + d)
                : new CellBox(y0 - d, s - x1, y1 - d, s - x0);
        }

        /// <summary>The rectangle a quarter turn of <paramref name="box"/> about its center lands on:
        /// <see cref="TurnedRect(BigInteger, BigInteger, BigInteger, BigInteger, bool)"/>.</summary>
        public static CellBox TurnedRect(CellBox box, bool clockwise = true)
            => TurnedRect(box.X0, box.Y0, box.X1, box.Y1, clockwise);

        /// <summary>
        /// The (s, d) of a quarter turn of the inclusive rectangle (spec/hashlife.md "Rectangle
        /// transforms"): clockwise sends (x, y) to (s − y, x + d), counter-clockwise to
        /// (y − d, s − x). The center itself when it is a cell or a cell corner; otherwise the one
        /// of the two cells it lies between whose x + y is even, so turns never drift. Every
        /// division is exact (its numerator is even).
        /// </summary>
        internal static (BigInteger S, BigInteger D) TurnCenter(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            BigInteger sx = x0 + x1, sy = y0 + y1; // twice the center
            if ((sx - sy).IsEven)
                return ((sx + sy) / 2, (sy - sx) / 2);
            BigInteger s = (sx + sy + 1) / 2; // then down to the even candidate
            if (!s.IsEven)
                s -= 1;
            return sx.IsEven ? (s, s - sx) : (s, sy - s);
        }

        /// <summary>
        /// The spec compatibility check: patterns are family-bound (a glider cannot
        /// enter Wireworld or MergeLife); cyclic patterns must also fit the target's
        /// state count. Returns the rejection reason, or null when stampable.
        /// </summary>
        public static string? Compatible(
            string patternFamily, string targetFamily,
            ReadOnlySpan<byte> patternCells, int targetStates = 0)
        {
            if (patternFamily != targetFamily)
                return $"'{patternFamily}' patterns cannot be stamped into '{targetFamily}'";
            if (targetFamily == "cyclic" && targetStates > 0)
            {
                int top = 0;
                foreach (byte cell in patternCells)
                    top = Math.Max(top, cell);
                if (top >= targetStates)
                    return $"pattern uses state {top}, target has only {targetStates} states";
            }
            return null;
        }

        // ---- helpers -------------------------------------------------------------

        private static string Run(int length, int value, bool multistate)
        {
            string tag = multistate
                ? value == 0 ? "." : ((char)('A' + value - 1)).ToString()
                : value != 0 ? "o" : "b";
            return length == 1 ? tag : length.ToString() + tag;
        }

        internal static bool TryParseHeader(
            string line, out BigInteger width, out BigInteger height, out string? rule)
        {
            width = height = BigInteger.Zero;
            rule = null;
            int pos = 0;
            if (!ExpectKey(line, ref pos, 'x') || !ExpectNumber(line, ref pos, out width))
                return false;
            if (!ExpectChar(line, ref pos, ',') || !ExpectKey(line, ref pos, 'y')
                || !ExpectNumber(line, ref pos, out height))
                return false;
            int save = pos;
            if (ExpectChar(line, ref pos, ',') && ExpectWord(line, ref pos, "rule")
                && ExpectChar(line, ref pos, '='))
            {
                SkipWs(line, ref pos);
                int start = pos;
                while (pos < line.Length && !char.IsWhiteSpace(line[pos]))
                    pos++;
                if (pos > start)
                    rule = line.Substring(start, pos - start);
            }
            else
            {
                pos = save;
            }
            return true;
        }

        private static bool ExpectKey(string line, ref int pos, char key)
        {
            SkipWs(line, ref pos);
            if (pos >= line.Length || char.ToLowerInvariant(line[pos]) != key)
                return false;
            pos++;
            return ExpectChar(line, ref pos, '=');
        }

        private static bool ExpectWord(string line, ref int pos, string word)
        {
            SkipWs(line, ref pos);
            if (pos + word.Length > line.Length)
                return false;
            for (int i = 0; i < word.Length; i++)
                if (char.ToLowerInvariant(line[pos + i]) != word[i])
                    return false;
            pos += word.Length;
            return true;
        }

        private static bool ExpectChar(string line, ref int pos, char expected)
        {
            SkipWs(line, ref pos);
            if (pos >= line.Length || line[pos] != expected)
                return false;
            pos++;
            return true;
        }

        private static bool ExpectNumber(string line, ref int pos, out BigInteger value)
        {
            SkipWs(line, ref pos);
            value = BigInteger.Zero; // a header may declare more than an int holds
            int start = pos;
            while (pos < line.Length && line[pos] >= '0' && line[pos] <= '9')
            {
                value = value * 10 + (line[pos] - '0');
                pos++;
            }
            return pos > start;
        }

        private static void SkipWs(string line, ref int pos)
        {
            while (pos < line.Length && char.IsWhiteSpace(line[pos]))
                pos++;
        }

        /// <summary>A Life-like rule in any notation of spec/rules.md, for dialect detection.</summary>
        private static bool IsLifelikeRule(string rule) => RuleString.TryCompile(rule, out _);

        private static void RotateInto<T>(
            ReadOnlySpan<T> cells, T[] result, int width, int height, int channels)
        {
            // result[y][x] = cells[height-1-x][y]; result is height x width transposed.
            for (int y = 0; y < width; y++)
                for (int x = 0; x < height; x++)
                    for (int c = 0; c < channels; c++)
                        result[(y * height + x) * channels + c] =
                            cells[((height - 1 - x) * width + y) * channels + c];
        }

        private static void RotateCcwInto<T>(
            ReadOnlySpan<T> cells, T[] result, int width, int height, int channels)
        {
            // result[y][x] = cells[x][width-1-y]; result is height wide and width tall.
            for (int y = 0; y < width; y++)
                for (int x = 0; x < height; x++)
                    for (int c = 0; c < channels; c++)
                        result[(y * height + x) * channels + c] =
                            cells[(x * width + (width - 1 - y)) * channels + c];
        }

        private static void FlipInto<T>(
            ReadOnlySpan<T> cells, T[] result, int width, int height, int channels, bool horizontal)
        {
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    int srcX = horizontal ? width - 1 - x : x;
                    int srcY = horizontal ? y : height - 1 - y;
                    for (int c = 0; c < channels; c++)
                        result[(y * width + x) * channels + c] =
                            cells[(srcY * width + srcX) * channels + c];
                }
        }

        private static void ExtractInto<T>(
            ReadOnlySpan<T> grid, T[] result, int gridWidth, int gridHeight, int channels,
            int x, int y, int width, int height, bool torus)
        {
            if (width < 1 || height < 1)
                throw new ArgumentException("extract region must be at least 1x1");
            for (int row = 0; row < height; row++)
                for (int col = 0; col < width; col++)
                {
                    if (!SourceIndex(gridWidth, gridHeight, x + col, y + row, torus, out int src))
                        continue; // dead boundary: leave 0/default
                    for (int c = 0; c < channels; c++)
                        result[(row * width + col) * channels + c] = grid[src * channels + c];
                }
        }

        private static bool SourceIndex(int width, int height, int x, int y, bool torus, out int index)
            => TargetIndex(width, height, x, y, torus, out index);

        private static bool TargetIndex(int width, int height, int x, int y, bool torus, out int index)
        {
            if (torus)
            {
                x = ((x % width) + width) % width;
                y = ((y % height) + height) % height;
            }
            else if (x < 0 || x >= width || y < 0 || y >= height)
            {
                index = 0;
                return false;
            }
            index = y * width + x;
            return true;
        }
    }
}
