using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// A grid running a rule table (spec/ruletable.md): any rule a rule file defines
    /// (<see cref="RuleTable"/>), on every topology of spec/topology.md. Each cell's next state is
    /// the rule's canonical tree walked over its 3 × 3 block, read from the grid's halo (blank 0
    /// past a dead edge). State is a flat row-major byte grid of values 0 to S − 1; the frame is
    /// the states themselves. <see cref="Step"/> and <see cref="WriteFrame"/> allocate nothing.
    /// Bit-exact tier. The Python reference's heaton_life.ca.ruletable.RuleTableCA.
    /// </summary>
    public sealed class RuleTableCA : IIndexedFrameSource, IRegionWorld
    {
        private readonly Halo _halo; // the cells past the edges (spec/topology.md "The halo")
        private readonly byte[] _padded; // the halo each generation reads
        private readonly int[] _offsets; // each walked cell's offset in the halo from the center
        private byte[] _cells;
        private byte[] _scratch;

        /// <summary>A world of the starter set's rule <paramref name="rule"/> (by name), seeded
        /// with its starter pattern, as the Python constructor's default init does.</summary>
        public RuleTableCA(string rule, int width, int height, Boundary boundary = Boundary.Dead)
            : this(RuleTables.Starter(rule), width, height, new Topology(boundary))
        {
        }

        /// <summary>A world of <paramref name="rule"/> on any topology, seeded with the rule's
        /// starter pattern (<see cref="SeedStarter"/>): a rule without one throws
        /// <see cref="ArgumentException"/>; build its world from cells instead.</summary>
        public RuleTableCA(RuleTable rule, int width, int height, Topology topology)
            : this(rule, width, height, topology, null)
        {
            SeedStarter();
        }

        /// <summary>A world of <paramref name="rule"/> from explicit cells (row-major, values 0 to
        /// S − 1), mirroring Python's init=array.</summary>
        public RuleTableCA(RuleTable rule, int width, int height, ReadOnlySpan<byte> cells, Topology topology)
            : this(rule, width, height, topology, null)
        {
            SetState(cells);
        }

        /// <summary>A world of <paramref name="rule"/> from explicit cells, with a boundary.</summary>
        public RuleTableCA(RuleTable rule, int width, int height, ReadOnlySpan<byte> cells, Boundary boundary = Boundary.Dead)
            : this(rule, width, height, cells, new Topology(boundary))
        {
        }

        private RuleTableCA(RuleTable rule, int width, int height, Topology topology, object? unused)
        {
            Rule = rule ?? throw new ArgumentNullException(nameof(rule));
            _halo = new Halo(topology, width, height);
            _padded = new byte[_halo.Length];
            Width = width;
            Height = height;
            Topology = topology;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            int stride = _halo.Columns;
            int[] order = rule.Neighbors == 8 ? RuleFileParser.TreeOrder8 : RuleFileParser.TreeOrder4;
            _offsets = new int[order.Length];
            for (int i = 0; i < order.Length; i++)
            {
                int cell = order[i]; // the block's cells: NW N NE / W C E / SW S SE
                _offsets[i] = (cell / 3 - 1) * stride + (cell % 3 - 1);
            }
        }

        /// <summary>The world's rule table.</summary>
        public RuleTable Rule { get; }

        /// <summary>S: the rule's number of states.</summary>
        public int States => Rule.States;

        public int Width { get; }

        public int Height { get; }

        /// <summary>How the grid's edges join (spec/topology.md).</summary>
        public Topology Topology { get; }

        /// <summary>The topology's boundary: <see cref="Topology"/>.Boundary.</summary>
        public Boundary Boundary => Topology.Boundary;

        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        // --- seeding and reset ---------------------------------------------------
        // How this world was last seeded, so Reset can replay it (the Python reference keeps
        // init, density and seed on its params and re-dispatches in reset()).
        private Action<uint> _replayInit = _ => { };
        private uint _seed;

        private void Remember(uint seed, Action<uint> replay)
        {
            _seed = seed;
            _replayInit = replay;
        }

        /// <summary>
        /// spec/ruletable.md "Initialization", starter: the rule's starter pattern, its top-left
        /// cell at ((Width − w) / 2, (Height − h) / 2). A rule without a starter pattern (one that
        /// isn't the starter set's rule of its name), or a grid it doesn't fit, throws
        /// <see cref="ArgumentException"/> and changes nothing. Consumes no draws.
        /// </summary>
        public void SeedStarter()
        {
            RuleTable? starter = RuleTables.StarterOrNull(Rule.Name);
            if (starter == null || (!ReferenceEquals(starter, Rule) && starter.TreeText() != Rule.TreeText()))
                throw new ArgumentException($"{Rule.Name} has no starter pattern (spec/ruletable.md)");
            (int w, int h, byte[] pattern) = RuleTables.StarterPattern(Rule.Name);
            if (w > Width || h > Height)
                throw new ArgumentException(
                    $"the starter pattern of {Rule.Name} is {w} x {h} cells, bigger than the {Width} x {Height} grid");
            Array.Clear(_cells, 0, _cells.Length);
            int x0 = (Width - w) / 2, y0 = (Height - h) / 2;
            for (int y = 0; y < h; y++)
                Array.Copy(pattern, y * w, _cells, (y0 + y) * Width + x0, w);
            Generation = 0;
            Remember(_seed, _ => SeedStarter());
        }

        /// <summary>spec/ruletable.md "Initialization", blank: every cell 0. No draws.</summary>
        public void SeedBlank()
        {
            Array.Clear(_cells, 0, _cells.Length);
            Generation = 0;
            Remember(_seed, _ => SeedBlank());
        }

        /// <summary>
        /// spec/ruletable.md "Initialization", soup: PCG32 seq 0, one draw per cell row-major; a
        /// cell is 0 unless its draw is below ⌊density · 2³²⌋, and then 1 + (draw mod (S − 1)).
        /// </summary>
        public void SeedSoup(uint seed, double density = 0.35)
        {
            ulong threshold = Seeding.Threshold(density);
            var rng = new Pcg32(seed);
            uint others = (uint)(States - 1);
            for (int i = 0; i < _cells.Length; i++)
            {
                uint draw = rng.NextU32();
                _cells[i] = draw < threshold ? (byte)(1 + draw % others) : (byte)0;
            }
            Generation = 0;
            Remember(seed, s => SeedSoup(s, density));
        }

        /// <inheritdoc />
        public void Reset(uint? seed = null)
        {
            if (seed.HasValue)
                _seed = seed.Value;
            _replayInit(_seed);
        }

        /// <summary>Load an explicit grid (row-major, Height × Width entries, values 0 to
        /// S − 1). A grid of the wrong size, or a state the rule lacks, throws and changes
        /// nothing.</summary>
        public void SetState(ReadOnlySpan<byte> cells)
        {
            CheckCells(cells);
            cells.CopyTo(_cells);
            Generation = 0;
            var snapshot = (byte[])_cells.Clone();
            Remember(_seed, _ =>
            {
                Array.Copy(snapshot, _cells, _cells.Length);
                Generation = 0;
            });
        }

        /// <summary>Restore a saved state at a given generation.</summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation)
        {
            SetState(cells);
            Generation = generation;
        }

        /// <summary>
        /// Load a grid at a given generation (spec/README.md "A world's state and its start").
        /// Without <paramref name="keepStart"/> it is <see cref="SetState(ReadOnlySpan{byte}, int)"/>:
        /// the grid also becomes the start <see cref="Reset"/> returns to. With it the start stays
        /// as it was and nothing is copied for it.
        /// </summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation, bool keepStart)
        {
            if (!keepStart)
            {
                SetState(cells, generation);
                return;
            }
            CheckCells(cells);
            cells.CopyTo(_cells);
            Generation = generation;
        }

        private void CheckCells(ReadOnlySpan<byte> cells)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
            {
                if (cells[i] >= States)
                    throw new ArgumentException(
                        $"{Rule.Name} has states 0 to {States - 1}; the cells hold {cells[i]}");
            }
        }

        /// <summary>Paint one cell in place (0 to S − 1); does not change the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            if (value >= States)
                throw new ArgumentException($"{Rule.Name} has states 0 to {States - 1}, not {value}");
            _cells[y * Width + x] = value;
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family's blank, 0
        /// (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            Patterns.CheckRegion(Width, Height, x0, y0, x1, y1);
            for (int y = y0; y <= y1; y++)
                Array.Clear(_cells, y * Width + x0, x1 - x0 + 1);
        }

        /// <summary>
        /// Advance Selection (spec/patterns.md "Editing a region"): the inclusive region evolves
        /// <paramref name="n"/> generations as if nothing else existed; cells outside it and
        /// <see cref="Generation"/> are untouched. A canceled <paramref name="cancellationToken"/>
        /// stops it promptly with <see cref="OperationCanceledException"/> and leaves the world
        /// exactly as it was.
        /// </summary>
        public void AdvanceSelection(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: false, cancellationToken);

        /// <summary>Advance Outside: Advance Selection's mirror image; the region keeps its
        /// cells.</summary>
        public void AdvanceOutside(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: true, cancellationToken);

        byte[] IRegionWorld.Cells => _cells;

        void IRegionWorld.StepOnce(CancellationToken cancellationToken) => StepOnce(cancellationToken);

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>The frame (spec/ruletable.md "Frames"): the states themselves, for a palette
        /// of a color per state. Allocates nothing.</summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame == null)
                throw new ArgumentNullException(nameof(frame));
            if (frame.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} bytes, got {frame.Length}");
            Array.Copy(_cells, frame, _cells.Length);
        }

        /// <summary>Allocating convenience for <see cref="WriteFrame"/>.</summary>
        public byte[] Frame()
        {
            var frame = new byte[_cells.Length];
            WriteFrame(frame);
            return frame;
        }

        private void StepOnce(CancellationToken cancellationToken = default)
        {
            int w = Width, h = Height, stride = _halo.Columns, states = States;
            byte[] p = _padded;
            int[] kids = Rule.Children;
            int root = Rule.Root * states;
            int[] offsets = _offsets;
            int levels = offsets.Length;
            _halo.Fill(_cells, p, 0);
            for (int y = 0; y < h; y++)
            {
                // Polled each row, so even a big grid stops within a generation (spec/patterns.md
                // "Canceling"); Step's default token is never canceled.
                if (cancellationToken.IsCancellationRequested)
                    throw GridRegion.Canceled(cancellationToken, Generation);
                int mid = (y + 1) * stride + 1; // the halo index of (0, y)
                for (int x = 0; x < w; x++)
                {
                    int at = mid + x;
                    int node = kids[root + p[at + offsets[0]]];
                    for (int level = 1; level < levels - 1; level++)
                        node = kids[node * states + p[at + offsets[level]]];
                    _scratch[y * w + x] = (byte)kids[node * states + p[at + offsets[levels - 1]]];
                }
            }
            (_cells, _scratch) = (_scratch, _cells);
        }
    }

    /// <summary>
    /// The rule-table starter set and rules carried by RLE files (spec/ruletable.md "The
    /// starter set", "Files"). The starter files are the library's own, embedded in the assembly
    /// from python/src/heaton_life/ca/rules/. The Python reference's starter_rule,
    /// starter_pattern, embedded_rule and append_rule.
    /// </summary>
    public static class RuleTables
    {
        private static readonly string[] Names =
        {
            "Langtons-Loops", "Byl-Loop", "Evoloop", "Langtons-Ant", "Ant-LLRR", "Ant-RLR",
        };

        private static readonly Dictionary<string, RuleTable> Cache = new Dictionary<string, RuleTable>();

        /// <summary>The starter set's names, in order.</summary>
        public static IReadOnlyList<string> StarterNames => Names;

        /// <summary>The starter set's spelling of <paramref name="name"/> (ASCII case ignored),
        /// or null.</summary>
        private static string? StarterName(string name)
        {
            foreach (string starter in Names)
            {
                if (starter.Length != name.Length)
                    continue;
                bool same = true;
                for (int i = 0; same && i < name.Length; i++)
                    same = AsciiLower(starter[i]) == AsciiLower(name[i]);
                if (same)
                    return starter;
            }
            return null;
        }

        private static char AsciiLower(char c) => c >= 'A' && c <= 'Z' ? (char)(c + ('a' - 'A')) : c;

        private static string Resource(string file)
        {
            using Stream? stream = typeof(RuleTables).Assembly.GetManifestResourceStream("HeatonLife.Rules." + file)
                ?? throw new InvalidOperationException($"the starter set's {file} is missing from the assembly");
            using var reader = new StreamReader(stream, new UTF8Encoding(false));
            return reader.ReadToEnd();
        }

        /// <summary>The starter set's rule of that name (ASCII case ignored); any other name
        /// throws <see cref="ArgumentException"/>.</summary>
        public static RuleTable Starter(string name)
        {
            if (name == null)
                throw new ArgumentNullException(nameof(name));
            return StarterOrNull(name) ?? throw new ArgumentException(
                $"'{name}' is not in the starter set ({string.Join(", ", Names)}; spec/ruletable.md)", nameof(name));
        }

        /// <summary><see cref="Starter"/> for a name in the starter set, null for any other.</summary>
        public static RuleTable? StarterOrNull(string name)
        {
            if (name == null)
                throw new ArgumentNullException(nameof(name));
            string? found = StarterName(name);
            if (found == null)
                return null;
            lock (Cache)
            {
                if (!Cache.TryGetValue(found, out RuleTable? rule))
                {
                    rule = RuleTable.Parse(Resource(found + ".rule"));
                    Cache[found] = rule;
                }
                return rule;
            }
        }

        /// <summary>The starter pattern of a starter rule: the cells of the publication's figure
        /// (spec/ruletable.md "The starter set"), a new array each call.</summary>
        public static (int Width, int Height, byte[] Cells) StarterPattern(string name)
        {
            RuleTable rule = Starter(name);
            RlePattern pattern = Patterns.RleDecode(Resource(rule.Name + ".rle"));
            return (pattern.Width, pattern.Height, pattern.Cells);
        }

        /// <summary>
        /// The rule file appended to an RLE or Macrocell pattern (spec/ruletable.md "Files"): in RLE
        /// from the first line after the pattern's <c>!</c> that starts with <c>@RULE</c>, in
        /// Macrocell (a text whose first line that isn't blank starts with <c>[M2]</c>) from the
        /// first line after the header that starts with <c>@RULE</c>; null when the text has none.
        /// Its text is <see cref="AppendedText"/>'s, the same whichever file carries the rule. An
        /// appended text that is no rule file throws <see cref="RuleFileException"/>.
        /// </summary>
        public static RuleTable? Embedded(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            List<string> lines = TextLines.Split(text); // spec/formats.md "Lines"
            var stripped = new string[lines.Count];
            for (int i = 0; i < stripped.Length; i++)
                stripped[i] = TextLines.Strip(lines[i]);
            int first = 0;
            while (first < stripped.Length && stripped[first].Length == 0)
                first++;
            int after;
            if (first < stripped.Length && stripped[first].StartsWith("[M2]", StringComparison.Ordinal))
            {
                after = first + 1;
            }
            else
            {
                int index = 0;
                while (index < stripped.Length
                    && (stripped[index].Length == 0 || stripped[index].StartsWith("#", StringComparison.Ordinal)))
                    index++;
                if (index < stripped.Length && Patterns.TryParseHeader(stripped[index], out _, out _, out _))
                    index++;
                while (index < lines.Count && lines[index].IndexOf('!') < 0)
                    index++;
                after = index + 1;
            }
            for (int later = after; later < stripped.Length; later++)
            {
                if (stripped[later].StartsWith("@RULE", StringComparison.Ordinal))
                    return RuleTable.Parse(AppendedText(text, later));
            }
            return null;
        }

        /// <summary>
        /// The text of a rule file appended to a pattern file whose <c>@RULE</c> line is line
        /// <paramref name="line"/> of <paramref name="text"/> (spec/formats.md "Lines"): the rest of
        /// the text from the start of that line, a final line end included, with <c>\r\n</c> and
        /// <c>\r</c> read as <c>\n</c> (spec/ruletable.md "Files"). Every carrier, and both ports,
        /// give a rule this one text.
        /// </summary>
        internal static string AppendedText(string text, int line)
            => TextLines.Rest(text, line).Replace("\r\n", "\n").Replace('\r', '\n');

        /// <summary>A pattern file's text, RLE or Macrocell, with <paramref name="rule"/>'s file
        /// appended after it (spec/ruletable.md "Files"), so the pattern carries its rule.</summary>
        public static string Append(string rle, RuleTable rule)
        {
            if (rle == null)
                throw new ArgumentNullException(nameof(rle));
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            string body = rle.EndsWith("\n", StringComparison.Ordinal) ? rle : rle + "\n";
            string text = rule.Text.Replace("\r\n", "\n").Replace('\r', '\n');
            return body + text + (text.EndsWith("\n", StringComparison.Ordinal) ? "" : "\n");
        }
    }
}
