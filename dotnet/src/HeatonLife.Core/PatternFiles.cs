using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>The pattern file formats (spec/formats.md); <see cref="PatternFiles.FormatName"/>
    /// gives each one's name in the spec and the vectors.</summary>
    public enum PatternFormat
    {
        Rle,
        Macrocell,
        Plaintext,
        Life105,
        Life106,
        Png,
        Bmp,
    }

    /// <summary>A pattern file read into a grid (spec/formats.md "Reading into a grid").</summary>
    public sealed class PatternFile
    {
        internal PatternFile(
            PatternFormat format, byte[] cells, int width, int height, BigInteger x, BigInteger y,
            string? rule, BigInteger generation, PatternMetadata metadata)
        {
            Format = format;
            Cells = cells;
            Width = width;
            Height = height;
            X = x;
            Y = y;
            Rule = rule;
            Generation = generation;
            Metadata = metadata;
        }

        public PatternFormat Format { get; }

        /// <summary>Row-major cell values: 0/1, or RLE's states up to 24.</summary>
        public byte[] Cells { get; }

        public int Width { get; }

        public int Height { get; }

        /// <summary>Where the grid's top-left cell sits in the file's own coordinates (y grows downward).</summary>
        public BigInteger X { get; }

        public BigInteger Y { get; }

        /// <summary>The file's rule, or null when it names none.</summary>
        public string? Rule { get; }

        public BigInteger Generation { get; }

        public PatternMetadata Metadata { get; }
    }

    /// <summary>A pattern file read into a HashLife universe, with its format and metadata.</summary>
    public sealed class PatternUniverse
    {
        internal PatternUniverse(PatternFormat format, HashLife universe, PatternMetadata metadata)
        {
            Format = format;
            Universe = universe;
            Metadata = metadata;
        }

        public PatternFormat Format { get; }

        public HashLife Universe { get; }

        public PatternMetadata Metadata { get; }
    }

    /// <summary>
    /// Pattern files in every format, recognized by content (spec/formats.md): RLE, Macrocell,
    /// plaintext, Life 1.05, Life 1.06, and PNG and BMP images, any of them gzip-compressed.
    /// <see cref="Detect(byte[])"/> names a file's format; <see cref="Read(byte[], long?, bool)"/>
    /// gives its cells as a dense grid; <see cref="ReadUniverse(byte[], int)"/> places it in a
    /// HashLife universe. Content that can't be read throws <see cref="FormatException"/>; a
    /// pattern past the decode limit or outside the editing box throws an
    /// <see cref="ArgumentException"/>. The Python reference's heaton_life.init.formats.
    /// </summary>
    public static class PatternFiles
    {
        /// <summary>The format's name in the spec and the vectors: "rle", "macrocell",
        /// "plaintext", "life-1.05", "life-1.06", "png" or "bmp".</summary>
        public static string FormatName(PatternFormat format) => format switch
        {
            PatternFormat.Rle => "rle",
            PatternFormat.Macrocell => "macrocell",
            PatternFormat.Plaintext => "plaintext",
            PatternFormat.Life105 => "life-1.05",
            PatternFormat.Life106 => "life-1.06",
            PatternFormat.Png => "png",
            PatternFormat.Bmp => "bmp",
            _ => throw new ArgumentOutOfRangeException(nameof(format), format, "unknown pattern format"),
        };

        /// <summary>A file's format, from its bytes alone (spec/formats.md "Detection").</summary>
        public static PatternFormat Detect(byte[] data) => Recognize(data).Format;

        /// <summary>The format of text (no gzip, no image), as for a file's text.</summary>
        public static PatternFormat Detect(string text) => Recognize(text).Format;

        /// <summary>
        /// A pattern file of any format as a dense grid (spec/formats.md "Reading into a grid").
        /// The grid past <paramref name="maxCells"/> (width × height; null lifts the limit) is
        /// refused before memory is asked for, and so is an image past it, trimmed or not. With
        /// <paramref name="trim"/> the grid is cut to its live cells' bounding box and (X, Y)
        /// moves with it. Macrocell and Life 1.0x always give that box.
        /// </summary>
        public static PatternFile Read(byte[] data, long? maxCells = Patterns.DefaultMaxCells, bool trim = false)
            => Read(Recognize(data), maxCells, trim);

        /// <summary>Text (a string, say from the clipboard) as a dense grid.</summary>
        public static PatternFile Read(string text, long? maxCells = Patterns.DefaultMaxCells, bool trim = false)
            => Read(Recognize(text), maxCells, trim);

        /// <summary>
        /// A two-state pattern file of any format in a HashLife universe (spec/formats.md
        /// "Reading into the unbounded universe"), placed as its format says; the rule is the
        /// file's, or B3/S23 without one.
        /// </summary>
        public static PatternUniverse ReadUniverse(byte[] data, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
            => ReadUniverse(Recognize(data), maxMemoryMb);

        /// <summary>Text in a HashLife universe.</summary>
        public static PatternUniverse ReadUniverse(string text, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
            => ReadUniverse(Recognize(text), maxMemoryMb);

        // ---- detection ----------------------------------------------------------------------

        private readonly struct Recognized
        {
            public Recognized(PatternFormat format, byte[]? data, string? text)
            {
                Format = format;
                Data = data;
                Text = text;
            }

            public readonly PatternFormat Format;
            public readonly byte[]? Data;
            public readonly string? Text;
        }

        private static Recognized Recognize(byte[] data)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            data = PatternText.Inflate(data);
            if (PngGrid.HasSignature(data))
                return new Recognized(PatternFormat.Png, data, null);
            if (PatternImages.IsBmp(data))
                return new Recognized(PatternFormat.Bmp, data, null);
            if (Array.IndexOf(data, (byte)0) >= 0)
                throw new FormatException("not a pattern file: the data is binary and no known image");
            return Recognize(PatternText.Decode(data));
        }

        private static Recognized Recognize(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            List<string> lines = TextLines.Split(text);
            string first = "";
            foreach (string line in lines)
            {
                first = TextLines.Strip(line);
                if (first.Length > 0)
                    break;
            }
            if (first.Length == 0)
                throw new FormatException("the pattern file is empty");
            PatternFormat format;
            if (first.StartsWith("[M2]", StringComparison.Ordinal))
                format = PatternFormat.Macrocell;
            else if (first.StartsWith("#Life 1.05", StringComparison.Ordinal))
                format = PatternFormat.Life105;
            else if (first.StartsWith("#Life 1.06", StringComparison.Ordinal))
                format = PatternFormat.Life106;
            else if (first[0] == '!')
                format = PatternFormat.Plaintext;
            else
                format = Unlabeled(lines);
            return new Recognized(format, null, text);
        }

        /// <summary>Detection's last rules: an RLE header first (after <c>#</c> lines), or
        /// nothing but plaintext cells, or else RLE.</summary>
        private static PatternFormat Unlabeled(List<string> lines)
        {
            bool cellsOnly = true;
            string? top = null;
            foreach (string raw in lines)
            {
                string line = TextLines.Strip(raw);
                if (line.Length == 0)
                    continue;
                if (top == null && line[0] != '#')
                    top = line;
                foreach (char c in line)
                {
                    if (c != '.' && c != 'O' && c != '*')
                    {
                        cellsOnly = false;
                        break;
                    }
                }
            }
            if (top != null && Patterns.IsRleHeader(top))
                return PatternFormat.Rle;
            return cellsOnly ? PatternFormat.Plaintext : PatternFormat.Rle;
        }

        // ---- the text formats ---------------------------------------------------------------

        /// <summary>A run of live cells at (X, Y) in the file's own coordinates.</summary>
        internal readonly struct LiveRun
        {
            public LiveRun(BigInteger x, BigInteger y, long length)
            {
                X = x;
                Y = y;
                Length = length;
            }

            public readonly BigInteger X;
            public readonly BigInteger Y;
            public readonly long Length;
        }

        /// <summary>A plaintext or Life 1.0x file's live cells, with what else it says.</summary>
        private sealed class LiveRuns
        {
            public readonly List<LiveRun> Runs = new List<LiveRun>();
            public long Width;
            public long Height;
            public string? Rule;
            public PatternMetadata Metadata = PatternMetadata.Empty;
        }

        private static void RowRuns(string row, BigInteger x, BigInteger y, int number, bool plaintext, List<LiveRun> runs)
        {
            int start = -1;
            for (int i = 0; i < row.Length; i++)
            {
                char c = row[i];
                if (c == 'O' || c == '*')
                {
                    if (start < 0)
                        start = i;
                    continue;
                }
                if (c != '.')
                {
                    string alive = plaintext ? "O*" : "*O";
                    throw new FormatException($"line {number}: '{c}' is not a cell ('.' dead, '{alive}' alive)");
                }
                if (start >= 0)
                {
                    runs.Add(new LiveRun(x + start, y, i - start));
                    start = -1;
                }
            }
            if (start >= 0)
                runs.Add(new LiveRun(x + start, y, row.Length - start));
        }

        private static LiveRuns Plaintext(string text)
        {
            var notes = new MetadataReader();
            var rows = new List<(int Number, string Row)>();
            List<string> lines = TextLines.Split(text);
            for (int i = 0; i < lines.Count; i++)
            {
                string stripped = TextLines.Strip(lines[i]);
                if (stripped.Length > 0 && stripped[0] == '!')
                {
                    string body = stripped.Substring(1);
                    if (body.StartsWith("Name:", StringComparison.Ordinal))
                        notes.Name(body.Substring(5));
                    else if (body.StartsWith("Author:", StringComparison.Ordinal))
                        notes.Author(body.Substring(7));
                    else
                        notes.Comment(body);
                }
                else
                {
                    rows.Add((i + 1, TextLines.StripEnd(lines[i])));
                }
            }
            while (rows.Count > 0 && rows[rows.Count - 1].Row.Length == 0)
                rows.RemoveAt(rows.Count - 1); // blank lines at the end are not rows
            var result = new LiveRuns { Height = rows.Count };
            for (int y = 0; y < rows.Count; y++)
            {
                RowRuns(rows[y].Row, BigInteger.Zero, y, rows[y].Number, plaintext: true, result.Runs);
                result.Width = Math.Max(result.Width, rows[y].Row.Length);
            }
            result.Metadata = notes.Result();
            return result;
        }

        /// <summary>An optional '-' and ASCII digits, any size.</summary>
        private static bool TrySigned(string text, out BigInteger value)
        {
            value = BigInteger.Zero;
            bool negative = text.Length > 0 && text[0] == '-';
            int start = negative ? 1 : 0;
            if (start == text.Length)
                return false;
            for (int i = start; i < text.Length; i++)
            {
                if (text[i] < '0' || text[i] > '9')
                    return false;
            }
            value = BigInteger.Parse(text.Substring(start), NumberStyles.None, CultureInfo.InvariantCulture);
            if (negative)
                value = -value;
            return true;
        }

        private static (BigInteger X, BigInteger Y) Cell(string text, int number, string what)
        {
            List<string> fields = TextLines.SplitSpace(text);
            if (fields.Count == 2 && TrySigned(fields[0], out BigInteger x) && TrySigned(fields[1], out BigInteger y))
                return (x, y);
            throw new FormatException($"line {number}: {what} needs two integers 'x y', got '{text}'");
        }

        /// <summary>Life 1.05's survival/birth digits as B…/S…; other text as written.</summary>
        internal static string LifeRule(string value)
        {
            int slash = value.IndexOf('/');
            if (slash >= 0 && value.IndexOf('/', slash + 1) < 0)
            {
                var survival = new bool[9];
                var birth = new bool[9];
                bool digits = true;
                for (int i = 0; i < value.Length && digits; i++)
                {
                    char c = value[i];
                    if (i == slash)
                        continue;
                    if (c < '0' || c > '8')
                        digits = false;
                    else if (i < slash)
                        survival[c - '0'] = true;
                    else
                        birth[c - '0'] = true;
                }
                if (digits)
                {
                    var rule = new System.Text.StringBuilder("B");
                    for (int d = 0; d < 9; d++)
                    {
                        if (birth[d])
                            rule.Append((char)('0' + d));
                    }
                    rule.Append("/S");
                    for (int d = 0; d < 9; d++)
                    {
                        if (survival[d])
                            rule.Append((char)('0' + d));
                    }
                    return rule.ToString();
                }
            }
            return value;
        }

        /// <summary>Life 1.05 (<paramref name="blocks"/>: #P blocks of rows) or Life 1.06 (a cell a line).</summary>
        private static LiveRuns Life(string text, bool blocks)
        {
            List<string> lines = TextLines.Split(text);
            int header = 0;
            while (TextLines.Strip(lines[header]).Length == 0)
                header++;
            var notes = new MetadataReader();
            var result = new LiveRuns();
            BigInteger bx = BigInteger.Zero, by = BigInteger.Zero;
            long row = 0;
            for (int i = header + 1; i < lines.Count; i++)
            {
                int number = i + 1;
                string stripped = TextLines.Strip(lines[i]);
                if (stripped.Length > 0 && stripped[0] == '#')
                {
                    string tag = stripped.Length >= 2 ? stripped.Substring(0, 2) : stripped;
                    string value = TextLines.Strip(stripped.Length >= 2 ? stripped.Substring(2) : "");
                    if (tag == "#D" || tag == "#C")
                    {
                        notes.Comment(value);
                    }
                    else if (tag == "#N")
                    {
                        result.Rule = "B3/S23";
                    }
                    else if (tag == "#R")
                    {
                        if (value.Length > 0)
                            result.Rule = LifeRule(value);
                    }
                    else if (tag == "#P" && blocks)
                    {
                        (bx, by) = Cell(value, number, "#P");
                        row = 0;
                    }
                }
                else if (blocks)
                {
                    RowRuns(TextLines.StripEnd(lines[i]), bx, by + row, number, plaintext: false, result.Runs);
                    row++;
                }
                else if (stripped.Length > 0)
                {
                    var (x, y) = Cell(stripped, number, "a cell");
                    result.Runs.Add(new LiveRun(x, y, 1));
                }
            }
            result.Metadata = notes.Result();
            return result;
        }

        private static LiveRuns Runs(Recognized found) => found.Format switch
        {
            PatternFormat.Plaintext => Plaintext(found.Text!),
            PatternFormat.Life105 => Life(found.Text!, blocks: true),
            PatternFormat.Life106 => Life(found.Text!, blocks: false),
            _ => throw new InvalidOperationException($"{FormatName(found.Format)} is not read as runs"),
        };

        private static CellBox? Box(List<LiveRun> runs)
        {
            if (runs.Count == 0)
                return null;
            BigInteger x0 = runs[0].X, y0 = runs[0].Y, x1 = runs[0].X + runs[0].Length - 1, y1 = runs[0].Y;
            foreach (LiveRun run in runs)
            {
                x0 = BigInteger.Min(x0, run.X);
                y0 = BigInteger.Min(y0, run.Y);
                x1 = BigInteger.Max(x1, run.X + run.Length - 1);
                y1 = BigInteger.Max(y1, run.Y);
            }
            return new CellBox(x0, y0, x1, y1);
        }

        // ---- reading into a grid ------------------------------------------------------------

        private static void Check(BigInteger width, BigInteger height, long? maxCells)
        {
            if (maxCells != null && width * height > maxCells.Value)
                throw new ArgumentException(
                    $"the pattern is {width} x {height} cells, past the limit of {maxCells.Value}");
            if (width * height > int.MaxValue)
                throw new ArgumentException($"the pattern is {width} x {height} cells, more than one array holds");
        }

        private static byte[] Grid(List<LiveRun> runs, BigInteger x0, BigInteger y0, int width, int height)
        {
            var cells = new byte[(long)width * height];
            foreach (LiveRun run in runs)
            {
                int at = (int)(run.Y - y0) * width + (int)(run.X - x0);
                cells.AsSpan(at, (int)run.Length).Fill(1);
            }
            return cells;
        }

        private static PatternFile Trimmed(PatternFormat format, byte[] cells, int width, int height)
        {
            int top = -1, bottom = -1, left = width, right = -1;
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    if (cells[y * width + x] == 0)
                        continue;
                    if (top < 0)
                        top = y;
                    bottom = y;
                    left = Math.Min(left, x);
                    right = Math.Max(right, x);
                }
            }
            if (top < 0)
                throw new FormatException("the pattern has no live cells");
            int w = right - left + 1, h = bottom - top + 1;
            var box = new byte[w * h];
            for (int y = 0; y < h; y++)
                Array.Copy(cells, (top + y) * width + left, box, y * w, w);
            return new PatternFile(format, box, w, h, left, top, null, BigInteger.Zero, PatternMetadata.Empty);
        }

        private static PatternFile Read(Recognized found, long? maxCells, bool trim)
        {
            PatternFormat format = found.Format;
            if (format == PatternFormat.Png || format == PatternFormat.Bmp)
            {
                byte[] image = format == PatternFormat.Png
                    ? PngGrid.DecodeLive(found.Data!, maxCells, out int width, out int height)
                    : PatternImages.BmpLive(found.Data!, maxCells, out width, out height);
                if (trim)
                    return Trimmed(format, image, width, height);
                return new PatternFile(format, image, width, height, 0, 0, null, BigInteger.Zero, PatternMetadata.Empty);
            }
            if (format == PatternFormat.Rle)
                return ReadRle(found.Text!, maxCells, trim);
            if (format == PatternFormat.Macrocell)
                return ReadMacrocell(found.Text!, maxCells);
            LiveRuns live = Runs(found);
            if (format == PatternFormat.Plaintext && !trim)
            {
                if (live.Width == 0 || live.Height == 0)
                    throw new FormatException("the plaintext pattern has no cells");
                Check(live.Width, live.Height, maxCells);
                byte[] grid = Grid(live.Runs, 0, 0, (int)live.Width, (int)live.Height);
                return new PatternFile(format, grid, (int)live.Width, (int)live.Height, 0, 0, live.Rule, 0, live.Metadata);
            }
            CellBox? liveBox = Box(live.Runs);
            if (liveBox == null)
                throw new FormatException("the pattern has no live cells");
            CellBox box = liveBox.Value;
            BigInteger boxWidth = box.X1 - box.X0 + 1, boxHeight = box.Y1 - box.Y0 + 1;
            Check(boxWidth, boxHeight, maxCells);
            byte[] cells = Grid(live.Runs, box.X0, box.Y0, (int)boxWidth, (int)boxHeight);
            return new PatternFile(format, cells, (int)boxWidth, (int)boxHeight, box.X0, box.Y0, live.Rule, 0, live.Metadata);
        }

        private static PatternFile ReadRle(string text, long? maxCells, bool trim)
        {
            Patterns.Cxrle(text, out BigInteger x, out BigInteger y, out BigInteger generation);
            RlePattern decoded = Patterns.RleDecode(text, maxCells, trim);
            if (trim)
            {
                CellBox live = Patterns.RleMeasure(text).Live!.Value; // a trimmed decode has a live cell
                x += live.X0;
                y += live.Y0;
            }
            return new PatternFile(
                PatternFormat.Rle, decoded.Cells, decoded.Width, decoded.Height, x, y, decoded.Rule, generation,
                Patterns.RleMetadata(text));
        }

        private static PatternFile ReadMacrocell(string text, long? maxCells)
        {
            HashLife universe = Macrocell.ReadWithMetadata(text, HashLife.DefaultMaxMemoryMb, out PatternMetadata metadata);
            CellBox? found = universe.BoundingBox;
            if (found == null)
                throw new FormatException("the Macrocell pattern has no live cells");
            CellBox box = found.Value;
            BigInteger width = box.X1 - box.X0 + 1, height = box.Y1 - box.Y0 + 1;
            Check(width, height, maxCells);
            byte[] cells = universe.CellsAnywhere(box.X0, box.Y0, box.X1, box.Y1);
            return new PatternFile(
                PatternFormat.Macrocell, cells, (int)width, (int)height, box.X0, box.Y0, universe.Rule,
                universe.Generation, metadata);
        }

        // ---- reading into the unbounded universe -----------------------------------------------

        private static PatternUniverse ReadUniverse(Recognized found, int maxMemoryMb)
        {
            PatternFormat format = found.Format;
            if (format == PatternFormat.Rle)
            {
                HashLife rle = Patterns.RleToHashLife(found.Text!, maxMemoryMb);
                return new PatternUniverse(format, rle, Patterns.RleMetadata(found.Text!));
            }
            if (format == PatternFormat.Macrocell)
            {
                HashLife mc = Macrocell.ReadWithMetadata(found.Text!, maxMemoryMb, out PatternMetadata metadata);
                return new PatternUniverse(format, mc, metadata);
            }
            if (format == PatternFormat.Png || format == PatternFormat.Bmp)
            {
                byte[] image = format == PatternFormat.Png
                    ? PngGrid.DecodeLive(found.Data!, null, out int width, out int height)
                    : PatternImages.BmpLive(found.Data!, null, out width, out height);
                var pictured = new HashLife(maxMemoryMb: maxMemoryMb);
                pictured.SetRect(0, 0, image, width, height, HashLifePasteMode.Or);
                return new PatternUniverse(format, pictured, PatternMetadata.Empty);
            }
            LiveRuns live = Runs(found);
            var universe = new HashLife(live.Rule ?? "B3/S23", maxMemoryMb);
            Place(universe, live.Runs);
            return new PatternUniverse(format, universe, live.Metadata);
        }

        /// <summary>Paste live runs, refusing any cell outside the editing box (spec/hashlife.md).</summary>
        private static void Place(HashLife universe, List<LiveRun> runs)
        {
            CellBox? found = Box(runs);
            if (found == null)
                return;
            CellBox box = found.Value;
            const long limit = HashLife.EditLimit;
            if (BigInteger.Abs(box.X0) > limit || BigInteger.Abs(box.Y0) > limit
                || BigInteger.Abs(box.X1) > limit || BigInteger.Abs(box.Y1) > limit)
                throw new ArgumentOutOfRangeException(
                    null,
                    $"{box} reaches outside the editing box |x|, |y| <= 1,000,000,000 (spec/hashlife.md \"Editing\")");
            var blocks = new Dictionary<long, ulong>();
            foreach (LiveRun run in runs)
                Patterns.AddRun(blocks, (long)run.X, (long)run.Y - 1, run.Length); // tree row: one above the cell's y
            universe.PasteBlocks(
                blocks, (long)box.X0, (long)box.Y0 - 1, (long)box.X1, (long)box.Y1 - 1, HashLifePasteMode.Or);
        }
    }

    /// <summary>How a pattern file's bytes become text (spec/formats.md "Bytes and text").</summary>
    internal static class PatternText
    {
        /// <summary>Gzip bytes inflated, once; any other bytes as they are. The stream is one
        /// member, whole: its CRC-32 and length are checked, and a stream cut short, damaged, or
        /// followed by more bytes is refused (the BCL's reader stops quietly at a cut).</summary>
        internal static byte[] Inflate(byte[] data)
        {
            if (data.Length < 2 || data[0] != 0x1f || data[1] != 0x8b)
                return data;
            byte[] inflated;
            try
            {
                using var source = new MemoryStream(data);
                using var gzip = new GZipStream(source, CompressionMode.Decompress);
                using var output = new MemoryStream();
                gzip.CopyTo(output);
                inflated = output.ToArray();
            }
            catch (InvalidDataException e)
            {
                throw new FormatException($"broken gzip data: {e.Message}", e);
            }
            // One whole member ends with its trailer: the CRC-32 and length of what it holds.
            if (data.Length < 18)
                throw new FormatException("broken gzip data: the stream is cut short");
            int end = data.Length;
            uint crc = (uint)(data[end - 8] | data[end - 7] << 8 | data[end - 6] << 16 | data[end - 5] << 24);
            uint size = (uint)(data[end - 4] | data[end - 3] << 8 | data[end - 2] << 16 | data[end - 1] << 24);
            if (size != (uint)inflated.Length || crc != PngGrid.Crc32(inflated))
                throw new FormatException("broken gzip data: cut short, damaged, or more than one member");
            return inflated;
        }

        /// <summary>UTF-8 when the bytes are valid UTF-8 (one leading byte-order mark dropped),
        /// otherwise Latin-1, a character per byte.</summary>
        internal static string Decode(byte[] data)
        {
            if (!TryUtf8(data, out string? text))
                return HashLife.Latin1(data, 0, data.Length);
            return text.Length > 0 && text[0] == '\uFEFF' ? text.Substring(1) : text;
        }

        /// <summary>Strict UTF-8 (Unicode's well-formed byte sequences: no overlong forms, no
        /// surrogates, nothing past U+10FFFF), decoded by hand so every runtime agrees.</summary>
        private static bool TryUtf8(byte[] data, out string text)
        {
            var chars = new char[data.Length];
            int count = 0, i = 0;
            text = "";
            while (i < data.Length)
            {
                int b = data[i];
                if (b < 0x80)
                {
                    chars[count++] = (char)b;
                    i++;
                    continue;
                }
                int need, low = 0x80, high = 0xBF, code;
                if (b >= 0xC2 && b <= 0xDF)
                {
                    need = 1;
                    code = b & 0x1F;
                }
                else if (b >= 0xE0 && b <= 0xEF)
                {
                    need = 2;
                    code = b & 0x0F;
                    if (b == 0xE0)
                        low = 0xA0;
                    else if (b == 0xED)
                        high = 0x9F;
                }
                else if (b >= 0xF0 && b <= 0xF4)
                {
                    need = 3;
                    code = b & 0x07;
                    if (b == 0xF0)
                        low = 0x90;
                    else if (b == 0xF4)
                        high = 0x8F;
                }
                else
                {
                    return false;
                }
                if (i + need >= data.Length)
                    return false; // the sequence is cut off
                for (int j = 1; j <= need; j++)
                {
                    int c = data[i + j];
                    int lo = j == 1 ? low : 0x80, hi = j == 1 ? high : 0xBF;
                    if (c < lo || c > hi)
                        return false;
                    code = (code << 6) | (c & 0x3F);
                }
                i += need + 1;
                if (code >= 0x10000)
                {
                    code -= 0x10000;
                    chars[count++] = (char)(0xD800 + (code >> 10));
                    chars[count++] = (char)(0xDC00 + (code & 0x3FF));
                }
                else
                {
                    chars[count++] = (char)code;
                }
            }
            text = new string(chars, 0, count);
            return true;
        }
    }
}
