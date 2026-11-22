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
            string? rule, BigInteger generation, PatternMetadata metadata, BoundedGrid? boundedGrid = null)
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
            BoundedGrid = boundedGrid;
        }

        public PatternFormat Format { get; }

        /// <summary>Row-major cell values: 0/1, or RLE's states up to 255.</summary>
        public byte[] Cells { get; }

        public int Width { get; }

        public int Height { get; }

        /// <summary>Where the grid's top-left cell sits in the file's own coordinates (y grows downward).</summary>
        public BigInteger X { get; }

        public BigInteger Y { get; }

        /// <summary>The file's rule, or null when it names none; an RLE header's without its
        /// bounded-grid suffix.</summary>
        public string? Rule { get; }

        public BigInteger Generation { get; }

        public PatternMetadata Metadata { get; }

        /// <summary>The world a bounded file names (spec/formats.md "Bounded grids"), or null; the
        /// cells are that whole world unless trimmed.</summary>
        public BoundedGrid? BoundedGrid { get; }
    }

    /// <summary>A pattern file read into a HashLife universe, with its format and metadata, and a
    /// Macrocell timeline's frames (spec/formats.md "Reading into the unbounded universe").</summary>
    public sealed class PatternUniverse
    {
        internal PatternUniverse(
            PatternFormat format, HashLife universe, PatternMetadata metadata,
            IReadOnlyList<HashLifeSnapshot> frames, BigInteger? step)
        {
            Format = format;
            Universe = universe;
            Metadata = metadata;
            Frames = frames;
            Step = step;
        }

        public PatternFormat Format { get; }

        /// <summary>The universe, at the file's own root and generation (a timeline's too).</summary>
        public HashLife Universe { get; }

        public PatternMetadata Metadata { get; }

        /// <summary>A timeline's frames, snapshots of <see cref="Universe"/> in order (frame i at
        /// generation Frames[0].Generation + i × <see cref="Step"/>); empty for any other file.</summary>
        public IReadOnlyList<HashLifeSnapshot> Frames { get; }

        /// <summary>A timeline's step, or null for a file that is no timeline.</summary>
        public BigInteger? Step { get; }
    }

    /// <summary>
    /// A pattern file read into a universe that exists (spec/formats.md "Reading into a universe
    /// that exists"): its format, a snapshot of its cells and generation in that universe, its
    /// rule in canonical form, its metadata, and a timeline's frames and step. The universe itself
    /// is unchanged. The Python reference's heaton_life.ca.hashlife.PatternSnapshot.
    /// </summary>
    public sealed class PatternSnapshot
    {
        internal PatternSnapshot(
            PatternFormat format, HashLifeSnapshot snapshot, string rule, PatternMetadata metadata,
            IReadOnlyList<HashLifeSnapshot> frames, BigInteger? step)
        {
            Format = format;
            Snapshot = snapshot;
            Rule = rule;
            Metadata = metadata;
            Frames = frames;
            Step = step;
        }

        public PatternFormat Format { get; }

        /// <summary>The file's cells and generation, a snapshot of the universe it was read into.</summary>
        public HashLifeSnapshot Snapshot { get; }

        /// <summary>The file's rule in canonical form, B3/S23 when it names none.</summary>
        public string Rule { get; }

        public PatternMetadata Metadata { get; }

        /// <summary>A timeline's frames, snapshots of the same universe in order; empty for any
        /// other file.</summary>
        public IReadOnlyList<HashLifeSnapshot> Frames { get; }

        /// <summary>A timeline's step, or null for a file that is no timeline.</summary>
        public BigInteger? Step { get; }
    }

    /// <summary>
    /// What <see cref="PatternFiles.Read(byte[], long?, bool)"/> without trimming gives, except the
    /// cells, found without making the grid (spec/formats.md "Measuring"). Every number is exact.
    /// </summary>
    public sealed class PatternExtent
    {
        internal PatternExtent(
            PatternFormat format, BigInteger width, BigInteger height, BigInteger x, BigInteger y, string? rule,
            BigInteger generation, PatternMetadata metadata, bool twoState, BoundedGrid? boundedGrid = null)
        {
            Format = format;
            Width = width;
            Height = height;
            X = x;
            Y = y;
            Rule = rule;
            Generation = generation;
            Metadata = metadata;
            TwoState = twoState;
            BoundedGrid = boundedGrid;
        }

        public PatternFormat Format { get; }

        /// <summary>The grid's width; 0 (and so is the height) for a pattern that reading
        /// refuses as empty.</summary>
        public BigInteger Width { get; }

        public BigInteger Height { get; }

        /// <summary>Where the grid's top-left cell sits in the file's own coordinates (y grows downward).</summary>
        public BigInteger X { get; }

        public BigInteger Y { get; }

        /// <summary>The file's rule, or null when it names none.</summary>
        public string? Rule { get; }

        public BigInteger Generation { get; }

        public PatternMetadata Metadata { get; }

        /// <summary>False for an extended RLE file, whatever states it uses: only a two-state file
        /// can be read into the unbounded universe.</summary>
        public bool TwoState { get; }

        /// <summary>The world a bounded file names, or null: only a file without one can be read
        /// into the unbounded universe.</summary>
        public BoundedGrid? BoundedGrid { get; }
    }

    /// <summary>
    /// Pattern files in every format, recognized by content (spec/formats.md): RLE, Macrocell,
    /// plaintext, Life 1.05, Life 1.06, and PNG and BMP images, any of them gzip-compressed.
    /// <see cref="Detect(byte[])"/> names a file's format; <see cref="Read(byte[], long?, bool)"/>
    /// gives its cells as a dense grid; <see cref="Measure(byte[])"/> gives all of that but the
    /// cells, without making the grid; <see cref="ReadUniverse(byte[], int)"/> places it in a
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
        /// What <see cref="Read(byte[], long?, bool)"/> without trimming would give, except the
        /// cells, found without making the grid (spec/formats.md "Measuring"): the format, the
        /// grid's size and position, the rule, the generation, the metadata, and whether the cells
        /// have two states. No cell is kept, so a pattern too large for any grid measures as easily
        /// as a glider: RLE by its counted extent, plaintext by its rows, Life 1.0x by its cells'
        /// coordinates, Macrocell from its tree without a universe, and an image from its header (a
        /// picture's extent is the picture: its pixels are not decoded). Text is checked as the
        /// readers check it, an image only as far as its pixel data. A pattern that reading refuses
        /// as empty measures 0 × 0 at (0, 0).
        /// </summary>
        public static PatternExtent Measure(byte[] data) => Measure(Recognize(data));

        /// <summary>Text (a string, say from the clipboard) measured as a file's text.</summary>
        public static PatternExtent Measure(string text) => Measure(Recognize(text));

        /// <summary>
        /// A two-state pattern file of any format in a HashLife universe (spec/formats.md
        /// "Reading into the unbounded universe"), placed as its format says; the rule is the
        /// file's, or B3/S23 without one. A Macrocell file with a <c>#FRAMES</c> line is a timeline:
        /// the result also gives its frames and step, and a malformed timeline throws
        /// <see cref="FormatException"/>.
        /// </summary>
        public static PatternUniverse ReadUniverse(byte[] data, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
            => ReadUniverse(Recognize(data), maxMemoryMb);

        /// <summary>Text in a HashLife universe.</summary>
        public static PatternUniverse ReadUniverse(string text, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
            => ReadUniverse(Recognize(text), maxMemoryMb);

        /// <summary>
        /// A two-state pattern file of any format read into <paramref name="universe"/>'s own store
        /// as a snapshot (spec/formats.md "Reading into a universe that exists"), with its format,
        /// rule, metadata and a timeline's frames: read and refused as
        /// <see cref="ReadUniverse(byte[], int)"/> reads and refuses it, while the universe's cells,
        /// generation, rule and earlier snapshots stay as they were.
        /// <see cref="HashLife.ReadSnapshot(byte[])"/> is the same.
        /// </summary>
        public static PatternSnapshot ReadSnapshot(HashLife universe, byte[] data)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            return ReadSnapshot(universe, Recognize(data));
        }

        /// <summary>Text read into a universe that exists, as a snapshot.</summary>
        public static PatternSnapshot ReadSnapshot(HashLife universe, string text)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            return ReadSnapshot(universe, Recognize(text));
        }

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

        /// <summary>A plaintext or Life 1.0x file's live cells, with what else it says. A measure
        /// keeps no run, only their bounding box.</summary>
        private sealed class LiveRuns
        {
            private readonly bool _keep;

            public LiveRuns(bool keep)
            {
                _keep = keep;
            }

            public readonly List<LiveRun> Runs = new List<LiveRun>();
            public long Width;
            public long Height;
            public string? Rule;
            public PatternMetadata Metadata = PatternMetadata.Empty;

            /// <summary>The live cells' bounding box, widened as each run arrives; null without any.</summary>
            public CellBox? Box;

            public void Add(LiveRun run)
            {
                if (_keep)
                    Runs.Add(run);
                BigInteger last = run.X + run.Length - 1;
                if (Box == null)
                {
                    Box = new CellBox(run.X, run.Y, last, run.Y);
                    return;
                }
                CellBox b = Box.Value;
                Box = new CellBox(
                    BigInteger.Min(b.X0, run.X), BigInteger.Min(b.Y0, run.Y), BigInteger.Max(b.X1, last),
                    BigInteger.Max(b.Y1, run.Y));
            }
        }

        private static void RowRuns(string row, BigInteger x, BigInteger y, int number, bool plaintext, LiveRuns runs)
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

        private static LiveRuns Plaintext(string text, bool keep)
        {
            var notes = new MetadataReader();
            var result = new LiveRuns(keep);
            List<string> lines = TextLines.Split(text);
            long rows = 0;
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
                    continue;
                }
                string row = TextLines.StripEnd(lines[i]);
                RowRuns(row, BigInteger.Zero, rows, i + 1, plaintext: true, result);
                rows++;
                if (row.Length > 0)
                {
                    result.Width = Math.Max(result.Width, row.Length);
                    result.Height = rows; // blank lines at the end are not rows
                }
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
        /// <summary>A rule in survival/birth order (<c>23/3</c>) as <c>B…/S…</c> (<c>B3/S23</c>),
        /// each side's digits sorted and repeats dropped; any other text as written
        /// (spec/formats.md "Rules in survival/birth order"). Life 1.05's <c>#R</c> and an RLE
        /// header's rule are read this way.</summary>
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
        private static LiveRuns Life(string text, bool blocks, bool keep)
        {
            List<string> lines = TextLines.Split(text);
            int header = 0;
            while (TextLines.Strip(lines[header]).Length == 0)
                header++;
            var notes = new MetadataReader();
            var result = new LiveRuns(keep);
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
                    RowRuns(TextLines.StripEnd(lines[i]), bx, by + row, number, plaintext: false, result);
                    row++;
                }
                else if (stripped.Length > 0)
                {
                    var (x, y) = Cell(stripped, number, "a cell");
                    result.Add(new LiveRun(x, y, 1));
                }
            }
            result.Metadata = notes.Result();
            return result;
        }

        private static LiveRuns Runs(Recognized found, bool keep = true) => found.Format switch
        {
            PatternFormat.Plaintext => Plaintext(found.Text!, keep),
            PatternFormat.Life105 => Life(found.Text!, blocks: true, keep),
            PatternFormat.Life106 => Life(found.Text!, blocks: false, keep),
            _ => throw new InvalidOperationException($"{FormatName(found.Format)} is not read as runs"),
        };

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
            CellBox? liveBox = live.Box;
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
            bool placed = Patterns.Cxrle(text, out BigInteger x, out BigInteger y, out BigInteger generation);
            BoundedGrid? world = Patterns.RleBoundedGrid(text); // from the header alone
            if (world == null)
            {
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
            RleExtent extent = Patterns.RleMeasure(text);
            Bounded(world, extent, placed, ref x, ref y, out BigInteger left, out BigInteger top);
            if (trim)
            {
                RlePattern box = Patterns.RleDecode(text, maxCells, trim: true);
                CellBox live = extent.Live!.Value; // a trimmed decode has a live cell
                return new PatternFile(
                    PatternFormat.Rle, box.Cells, box.Width, box.Height, x + live.X0, y + live.Y0, box.Rule,
                    generation, Patterns.RleMetadata(text), world);
            }
            // The whole world, the pattern placed in it (spec/formats.md "Bounded grids").
            Check(world.Width, world.Height, maxCells);
            var cells = new byte[(long)world.Width * world.Height];
            Patterns.PlaceRle(text, cells, world.Width, x - left, y - top);
            return new PatternFile(
                PatternFormat.Rle, cells, world.Width, world.Height, left, top, extent.Rule, generation,
                Patterns.RleMetadata(text), world);
        }

        /// <summary>
        /// A bounded file's pattern in its world (spec/formats.md "Bounded grids"): moves
        /// (<paramref name="x"/>, <paramref name="y"/>) to the pattern's top-left — <c>#CXRLE
        /// Pos</c> when <paramref name="placed"/>, else its decoded size's half up and left of the
        /// origin — and gives the world's top-left (the world is centered on the origin). A pattern
        /// with a live cell past its world is refused.
        /// </summary>
        private static void Bounded(
            BoundedGrid world, RleExtent extent, bool placed, ref BigInteger x, ref BigInteger y,
            out BigInteger left, out BigInteger top)
        {
            left = -(world.Width / 2);
            top = -(world.Height / 2);
            if (!placed)
            {
                x = -BigInteger.Divide(extent.Width, 2);
                y = -BigInteger.Divide(extent.Height, 2);
            }
            if (extent.Live is CellBox live
                && (x + live.X0 < left || y + live.Y0 < top
                    || x + live.X1 >= left + world.Width || y + live.Y1 >= top + world.Height))
                throw new ArgumentException($"the pattern reaches past its bounded grid ({world.Suffix})");
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

        // ---- measuring --------------------------------------------------------------------------

        private static PatternExtent Measure(Recognized found)
        {
            PatternFormat format = found.Format;
            if (format == PatternFormat.Png || format == PatternFormat.Bmp)
            {
                var (width, height) = format == PatternFormat.Png
                    ? PngGrid.MeasureLive(found.Data!)
                    : PatternImages.BmpMeasure(found.Data!);
                return new PatternExtent(format, width, height, 0, 0, null, 0, PatternMetadata.Empty, twoState: true);
            }
            if (format == PatternFormat.Rle)
                return MeasureRle(found.Text!);
            if (format == PatternFormat.Macrocell)
            {
                CellBox? box = Macrocell.Measure(
                    found.Text!, out string rule, out BigInteger generation, out PatternMetadata metadata);
                return Boxed(format, box, rule, generation, metadata);
            }
            LiveRuns live = Runs(found, keep: false);
            if (format == PatternFormat.Plaintext)
            {
                bool empty = live.Width == 0 || live.Height == 0;
                return new PatternExtent(
                    format, empty ? 0 : live.Width, empty ? 0 : live.Height, 0, 0, null, 0, live.Metadata, twoState: true);
            }
            return Boxed(format, live.Box, live.Rule, 0, live.Metadata);
        }

        /// <summary>The extent of a format whose grid is its live cells' bounding box.</summary>
        private static PatternExtent Boxed(
            PatternFormat format, CellBox? found, string? rule, BigInteger generation, PatternMetadata metadata)
        {
            if (found == null)
                return new PatternExtent(format, 0, 0, 0, 0, rule, generation, metadata, twoState: true);
            CellBox box = found.Value;
            return new PatternExtent(
                format, box.X1 - box.X0 + 1, box.Y1 - box.Y0 + 1, box.X0, box.Y0, rule, generation, metadata,
                twoState: true);
        }

        private static PatternExtent MeasureRle(string text)
        {
            // The #CXRLE line: position and generation, checked as a read checks them.
            bool placed = Patterns.Cxrle(text, out BigInteger x, out BigInteger y, out BigInteger generation);
            RleExtent extent = Patterns.RleMeasure(text);
            BigInteger width = extent.Width, height = extent.Height;
            BoundedGrid? world = extent.BoundedGrid;
            if (world != null)
            {
                // The world, whatever the pattern's own size.
                Bounded(world, extent, placed, ref x, ref y, out BigInteger left, out BigInteger top);
                x = left;
                y = top;
                width = world.Width;
                height = world.Height;
            }
            else if (width.IsZero || height.IsZero)
            {
                width = height = x = y = BigInteger.Zero;
            }
            return new PatternExtent(
                PatternFormat.Rle, width, height, x, y, extent.Rule, generation, Patterns.RleMetadata(text),
                twoState: !extent.Extended, world);
        }

        // ---- reading into the unbounded universe -----------------------------------------------

        private static PatternUniverse ReadUniverse(Recognized found, int maxMemoryMb)
        {
            var universe = new HashLife(maxMemoryMb: maxMemoryMb);
            Reading read = ReadInto(universe, found);
            universe.Rule = read.Rule;
            universe.Adopt(read.Root, read.Level, read.Generation);
            return new PatternUniverse(found.Format, universe, read.Metadata, Snapshots(universe, read), read.Step);
        }

        private static PatternSnapshot ReadSnapshot(HashLife universe, Recognized found)
        {
            Reading read = ReadInto(universe, found);
            HashLifeSnapshot snapshot = universe.SnapshotAt(read.Root, read.Level, read.Generation);
            return new PatternSnapshot(
                found.Format, snapshot, read.Rule, read.Metadata, Snapshots(universe, read), read.Step);
        }

        private static IReadOnlyList<HashLifeSnapshot> Snapshots(HashLife universe, Reading read)
        {
            if (read.Frames == null)
                return Array.Empty<HashLifeSnapshot>();
            var frames = new HashLifeSnapshot[read.Frames.Count];
            for (int i = 0; i < frames.Length; i++)
            {
                var (root, level, generation) = read.Frames[i];
                frames[i] = universe.SnapshotAt(root, level, generation);
            }
            return frames;
        }

        /// <summary>A file read into a store: its tree, generation, rule, metadata, and a
        /// timeline's step and frames, the universe not yet any of them.</summary>
        private sealed class Reading
        {
            public int Root;
            public int Level;
            public BigInteger Generation;
            public string Rule = "B3/S23";
            public PatternMetadata Metadata = PatternMetadata.Empty;
            public BigInteger? Step;
            public List<(int Root, int Level, BigInteger Generation)>? Frames;
        }

        /// <summary>Read a two-state pattern file of any format into <paramref name="universe"/>'s
        /// store, placed as its format says, without changing the universe's state or rule.</summary>
        private static Reading ReadInto(HashLife universe, Recognized found)
        {
            PatternFormat format = found.Format;
            var read = new Reading();
            if (format == PatternFormat.Rle)
            {
                (read.Root, read.Level, read.Generation, read.Rule) = Patterns.BuildRle(universe, found.Text!);
                read.Metadata = Patterns.RleMetadata(found.Text!);
                return read;
            }
            if (format == PatternFormat.Macrocell)
            {
                Macrocell.Built built = Macrocell.Build(universe, found.Text!);
                var timeline = Macrocell.TimelineFrames(universe.Store, built);
                read.Root = built.Root;
                read.Level = built.Level;
                read.Generation = built.Generation;
                read.Rule = built.Rule;
                read.Metadata = built.Metadata;
                if (timeline != null)
                {
                    read.Step = timeline.Value.Step;
                    read.Frames = timeline.Value.Frames;
                }
                return read;
            }
            if (format == PatternFormat.Png || format == PatternFormat.Bmp)
            {
                byte[] image = format == PatternFormat.Png
                    ? PngGrid.DecodeLive(found.Data!, null, out int width, out int height)
                    : PatternImages.BmpLive(found.Data!, null, out width, out height);
                (read.Root, read.Level) = universe.Build(
                    () => universe.SetRect(0, 0, image, width, height, HashLifePasteMode.Or));
                return read;
            }
            LiveRuns live = Runs(found);
            // A file names its rule, never a preset (spec/formats.md "Reading into the unbounded
            // universe"): the universe's rule check refuses one.
            read.Rule = HashLife.CheckedRule(live.Rule ?? "B3/S23");
            read.Metadata = live.Metadata;
            (read.Root, read.Level) = universe.Build(() => Place(universe, live));
            return read;
        }

        /// <summary>Paste live runs, refusing any cell outside the editing box (spec/hashlife.md).</summary>
        private static void Place(HashLife universe, LiveRuns live)
        {
            List<LiveRun> runs = live.Runs;
            CellBox? found = live.Box;
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
