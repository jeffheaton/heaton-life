using System;
using System.Collections.Generic;
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
