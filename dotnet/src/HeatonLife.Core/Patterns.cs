using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text;

namespace HeatonLife
{
    /// <summary>A decoded RLE pattern: row-major cells plus the header's rule, if any.</summary>
    public sealed class RlePattern
    {
        public RlePattern(byte[] cells, int width, int height, string? rule)
        {
            Cells = cells;
            Width = width;
            Height = height;
            Rule = rule;
        }

        public byte[] Cells { get; }
        public int Width { get; }
        public int Height { get; }
        /// <summary>The header's rule string, or null when the RLE carried no rule.</summary>
        public string? Rule { get; }
    }

    /// <summary>
    /// Pattern operations (spec/patterns.md): Golly-compatible RLE in both dialects,
    /// transforms, and extract/stamp with the spec'd wrap/clip/transparency semantics.
    /// Patterns are family-bound artifacts — see <see cref="Compatible"/> — and every
    /// operation here is bit-exact against vectors/patterns/.
    /// </summary>
    public static class Patterns
    {
        // ---- RLE ----------------------------------------------------------------

        public static RlePattern RleDecode(string text)
        {
            var lines = new List<string>();
            foreach (string raw in text.Split('\n'))
            {
                string line = raw.TrimEnd('\r').Trim();
                if (line.Length > 0 && line[0] != '#')
                    lines.Add(line);
            }
            if (lines.Count == 0)
                throw new ArgumentException("empty RLE input");

            string? rule = null;
            int declaredW = 0, declaredH = 0;
            string body;
            if (TryParseHeader(lines[0], out declaredW, out declaredH, out rule))
                body = string.Concat(lines.GetRange(1, lines.Count - 1));
            else
                body = string.Concat(lines);

            // Dialect detection (spec/patterns.md): uppercase B/O are dead/alive in
            // two-state files but states 2/15 in extended RLE.
            bool extended = rule != null && !IsLifelikeRule(rule);
            foreach (char c in body)
            {
                if (c == '.' || (c >= 'A' && c <= 'X' && c != 'B' && c != 'O'))
                {
                    extended = true;
                    break;
                }
            }

            var rows = new List<List<byte>> { new List<byte>() };
            int count = 0;
            foreach (char c in body)
            {
                if (c >= '0' && c <= '9')
                {
                    count = count * 10 + (c - '0');
                }
                else if (c == 'b' || c == '.' || (!extended && c == 'B'))
                {
                    AppendRun(rows, 0, ref count);
                }
                else if (c == 'o' || (!extended && c == 'O'))
                {
                    AppendRun(rows, 1, ref count);
                }
                else if (extended && c >= 'A' && c <= 'X')
                {
                    AppendRun(rows, (byte)(c - 'A' + 1), ref count);
                }
                else if (c == '$')
                {
                    int repeat = Math.Max(count, 1);
                    for (int i = 0; i < repeat; i++)
                        rows.Add(new List<byte>());
                    count = 0;
                }
                else if (c == '!')
                {
                    break;
                }
                else if (char.IsWhiteSpace(c))
                {
                    continue;
                }
                else
                {
                    throw new ArgumentException($"unsupported RLE tag: '{c}'");
                }
            }

            int width = declaredW;
            foreach (var row in rows)
                width = Math.Max(width, row.Count);
            int height = Math.Max(rows.Count, declaredH);
            if (width == 0 || height == 0)
                throw new ArgumentException("RLE pattern has no cells");

            var cells = new byte[width * height];
            for (int y = 0; y < rows.Count; y++)
                for (int x = 0; x < rows[y].Count; x++)
                    cells[y * width + x] = rows[y][x];
            return new RlePattern(cells, width, height, rule);
        }

        /// <summary>Canonical RLE; dialect chosen by content (cells above 24 are unencodable).</summary>
        public static string RleEncode(ReadOnlySpan<byte> cells, int width, int height, string rule = "B3/S23")
        {
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
            sb.Append("x = ").Append(width).Append(", y = ").Append(height)
              .Append(", rule = ").Append(rule);
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
            string body = string.Concat(lines);
            bool extended = rule != null && !IsLifelikeRule(rule);
            foreach (char c in body)
            {
                if (c == '.' || (c >= 'A' && c <= 'X' && c != 'B' && c != 'O'))
                    extended = true;
            }
            if (extended)
                throw new FormatException("HashLife reads two-state RLE only (this file is extended RLE)");
            var universe = new HashLife(rule ?? "B3/S23", maxMemoryMb);

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
            {
                HashLife.CheckBox(x0, y0, x0 + width - 1, y0 + height - 1);
                universe.PasteBlocks(blocks, x0, y0 - 1, x0 + width - 1, y0 + height - 2, HashLifePasteMode.Or);
            }
            universe.SetGeneration(generation);
            return universe;
        }

        private static void ReadCxrle(string line, ref BigInteger posX, ref BigInteger posY, ref BigInteger generation)
        {
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
                    posX = ParseInteger(comma < 0 ? value : value.Substring(0, comma));
                    posY = ParseInteger(comma < 0 ? "" : value.Substring(comma + 1));
                }
                else if (key == "Gen")
                {
                    generation = ParseInteger(value);
                    if (generation.Sign < 0)
                        throw new FormatException($"#CXRLE Gen must be a non-negative generation, got {value}");
                }
            }
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

        private static BigInteger ParseInteger(string text)
        {
            int i = text.Length > 0 && (text[0] == '-' || text[0] == '+') ? 1 : 0;
            if (i == text.Length)
                throw new FormatException($"invalid integer '{text}' in #CXRLE");
            for (int j = i; j < text.Length; j++)
            {
                if (text[j] < '0' || text[j] > '9')
                    throw new FormatException($"invalid integer '{text}' in #CXRLE");
            }
            BigInteger magnitude = BigInteger.Parse(text.Substring(i), NumberStyles.None, CultureInfo.InvariantCulture);
            return text[0] == '-' ? -magnitude : magnitude;
        }

        /// <summary>Set <paramref name="length"/> cells from tree position (tx, ty) rightward.</summary>
        private static void AddRun(Dictionary<long, ulong> blocks, long tx, long ty, long length)
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
        /// <see cref="RleEncode"/> gives that rectangle. A pattern reaching outside the editing
        /// box throws <see cref="InvalidOperationException"/>; Macrocell carries it.
        /// </summary>
        public static string HashLifeToRle(HashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            BigInteger generation = universe.Generation;
            string gen = generation.Sign > 0 ? " Gen=" + generation.ToString(CultureInfo.InvariantCulture) : "";
            CellBox? found = universe.BoundingBox;
            if (found == null)
                return $"#CXRLE Pos=0,0{gen}\nx = 0, y = 0, rule = {universe.Rule}\n!\n";
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
            text.Append("x = ").Append((x1 - x0 + 1).ToString(CultureInfo.InvariantCulture))
                .Append(", y = ").Append((y1 - y0 + 1).ToString(CultureInfo.InvariantCulture))
                .Append(", rule = ").Append(universe.Rule).Append('\n');
            int lineLength = 0;
            for (long cy = y0; cy <= y1; cy++)
            {
                long pos = x0;
                if (rows.TryGetValue(cy, out List<long>? runs))
                {
                    for (int r = 0; r < runs.Count; r += 2)
                    {
                        long start = runs[r], length = runs[r + 1];
                        if (start > pos)
                            AppendToken(text, ref lineLength, start - pos, 'b');
                        AppendToken(text, ref lineLength, length, 'o');
                        pos = start + length;
                    }
                }
                AppendToken(text, ref lineLength, 1, cy < y1 ? '$' : '!');
            }
            text.Append('\n');
            return text.ToString();
        }

        /// <summary>One run token, wrapped as <see cref="RleEncode"/> wraps: a token that would
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
        {
            if (transparent && channels != 1)
                throw new ArgumentException("transparent stamping is defined for scalar payloads only");
            for (int row = 0; row < patternHeight; row++)
                for (int col = 0; col < patternWidth; col++)
                {
                    if (transparent && pattern[row * patternWidth + col] == 0)
                        continue;
                    if (!TargetIndex(gridWidth, gridHeight, x + col, y + row, torus, out int dst))
                        continue;
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

        private static void AppendRun(List<List<byte>> rows, byte value, ref int count)
        {
            int repeat = Math.Max(count, 1);
            List<byte> row = rows[rows.Count - 1];
            for (int i = 0; i < repeat; i++)
                row.Add(value);
            count = 0;
        }

        private static string Run(int length, int value, bool multistate)
        {
            string tag = multistate
                ? value == 0 ? "." : ((char)('A' + value - 1)).ToString()
                : value != 0 ? "o" : "b";
            return length == 1 ? tag : length.ToString() + tag;
        }

        private static bool TryParseHeader(string line, out int width, out int height, out string? rule)
        {
            width = height = 0;
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

        private static bool ExpectNumber(string line, ref int pos, out int value)
        {
            SkipWs(line, ref pos);
            value = 0;
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

        /// <summary>Strict Life-like rulestring shape (^[Bb][0-8]*/[Ss][0-8]*$), for dialect detection.</summary>
        private static bool IsLifelikeRule(string rule)
        {
            int pos = 0;
            if (pos >= rule.Length || (rule[pos] != 'B' && rule[pos] != 'b'))
                return false;
            pos++;
            while (pos < rule.Length && rule[pos] >= '0' && rule[pos] <= '8')
                pos++;
            if (pos >= rule.Length || rule[pos] != '/')
                return false;
            pos++;
            if (pos >= rule.Length || (rule[pos] != 'S' && rule[pos] != 's'))
                return false;
            pos++;
            while (pos < rule.Length && rule[pos] >= '0' && rule[pos] <= '8')
                pos++;
            return pos == rule.Length;
        }

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
