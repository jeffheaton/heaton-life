using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Numerics;
using System.Text;

namespace HeatonLife
{
    /// <summary>
    /// Macrocell (<c>.mc</c>, <c>.mc.gz</c>) — HashLife's native file format (spec/macrocell.md).
    /// A file lists a pattern's distinct quadtree nodes, children before parents, so a regular
    /// pattern of trillions of cells fits in a few lines. Reading covers two-state files (and
    /// the multistate syntax when every state is 0 or 1); writing is canonical, so
    /// conforming ports write the same bytes for the same cells. The Python reference's
    /// heaton_life.ca.hashlife.macrocell.
    /// </summary>
    public static class Macrocell
    {
        public const string Header = "[M2] (heaton-life)";

        /// <summary>A universe from Macrocell bytes; gzip-compressed bytes (1f 8b) are inflated
        /// first, and the text is Latin-1.</summary>
        public static HashLife Read(byte[] data, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return Read(PatternText.Decode(PatternText.Inflate(data)), maxMemoryMb);
        }

        /// <summary>
        /// A universe from Macrocell text, placed by tree coordinates: a level-k root covers x in
        /// [−2^(k−1), 2^(k−1) − 1] and y in [−2^(k−1) + 1, 2^(k−1)]. <c>#R</c> sets the rule,
        /// <c>#G</c> the generation; other <c>#</c> lines (comments, timeline frames) are skipped.
        /// Malformed text throws <see cref="FormatException"/>.
        /// </summary>
        public static HashLife Read(string text, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            return Parse(text, maxMemoryMb).Universe;
        }

        /// <summary><see cref="Read(string, int)"/> and the file's <c>#N</c>, <c>#O</c> and <c>#C</c>
        /// lines (spec/macrocell.md "Metadata").</summary>
        internal static HashLife ReadWithMetadata(string text, int maxMemoryMb, out PatternMetadata metadata)
        {
            Parsed parsed = Parse(text, maxMemoryMb);
            metadata = parsed.Metadata;
            return parsed.Universe;
        }

        /// <summary>A file's lines read once: every node line as (value, level), <c>#G</c>, the
        /// metadata, and the timeline lines left for the timeline reader.</summary>
        private class NodeLines
        {
            public PatternMetadata Metadata = PatternMetadata.Empty;
            public BigInteger Generation = BigInteger.Zero;
            public readonly List<long> Values = new List<long>();
            public readonly List<int> Levels = new List<int>();
            public readonly List<(int Number, string Line)> FramesLines = new List<(int, string)>();
            public readonly List<(int Number, string Line)> FrameLines = new List<(int, string)>();
        }

        /// <summary>A file read into a universe, at its root and <c>#G</c>.</summary>
        private sealed class Parsed : NodeLines
        {
            public Parsed(HashLife universe)
            {
                Universe = universe;
            }

            public HashLife Universe { get; }
        }

        /// <summary>Where a file's nodes of level 3 and up go, as ids: a universe's store, or the
        /// boxes a measure keeps. Levels 1 and 2 are spread bitmaps in the leaf layout, made by
        /// the reader itself.</summary>
        private interface INodes
        {
            /// <summary>A level-3 node from its 8 × 8 bitmap (bit 8r + c is row r, column c).</summary>
            long Leaf(ulong bits);

            long Empty(int level);

            long Join(long nw, long ne, long sw, long se, int level);

            /// <summary>An <c>#R</c> line's rule; throws <see cref="ArgumentException"/> for one the
            /// universe can't run.</summary>
            void Rule(string text);
        }

        /// <summary>A file's nodes in a universe's store, its <c>#R</c> the universe's rule.</summary>
        private sealed class StoreNodes : INodes
        {
            private readonly HashLife _universe;
            private readonly HashLifeStore _store;

            public StoreNodes(HashLife universe)
            {
                _universe = universe;
                _store = universe.Store;
            }

            public long Leaf(ulong bits) => _store.Leaf(bits);

            public long Empty(int level) => _store.Empty(level);

            public long Join(long nw, long ne, long sw, long se, int level) => _store.Join((int)nw, (int)ne, (int)sw, (int)se);

            public void Rule(string text) => _universe.Rule = text;
        }

        /// <summary>A file's nodes as their live cells' boxes, each relative to its node's top-left
        /// corner; id 0 is every empty node. No universe is built (spec/formats.md
        /// "Measuring").</summary>
        private sealed class BoxNodes : INodes
        {
            public readonly List<CellBox?> Boxes = new List<CellBox?> { null };
            public string Canonical = "B3/S23";

            public long Leaf(ulong bits)
            {
                Boxes.Add(BitsBox(bits));
                return Boxes.Count - 1;
            }

            public long Empty(int level) => 0;

            public long Join(long nw, long ne, long sw, long se, int level)
            {
                BigInteger half = BigInteger.One << (level - 1);
                CellBox? box = Widen(null, Boxes[(int)nw], BigInteger.Zero, BigInteger.Zero);
                box = Widen(box, Boxes[(int)ne], half, BigInteger.Zero);
                box = Widen(box, Boxes[(int)sw], BigInteger.Zero, half);
                box = Widen(box, Boxes[(int)se], half, half);
                Boxes.Add(box);
                return Boxes.Count - 1;
            }

            public void Rule(string text) => Canonical = HashLife.CheckedRule(text);

            private static CellBox? Widen(CellBox? box, CellBox? part, BigInteger dx, BigInteger dy)
            {
                if (part == null)
                    return box;
                CellBox p = part.Value;
                BigInteger x0 = p.X0 + dx, y0 = p.Y0 + dy, x1 = p.X1 + dx, y1 = p.Y1 + dy;
                if (box == null)
                    return new CellBox(x0, y0, x1, y1);
                CellBox b = box.Value;
                return new CellBox(
                    BigInteger.Min(b.X0, x0), BigInteger.Min(b.Y0, y0), BigInteger.Max(b.X1, x1), BigInteger.Max(b.Y1, y1));
            }
        }

        /// <summary>The live cells' box in a leaf-layout bitmap (bit 8r + c is row r, column c), or null.</summary>
        private static CellBox? BitsBox(ulong bits)
        {
            if (bits == 0)
                return null;
            int top = -1, bottom = -1, columns = 0;
            for (int r = 0; r < 8; r++)
            {
                int row = (int)((bits >> (8 * r)) & 0xFF);
                if (row == 0)
                    continue;
                if (top < 0)
                    top = r;
                bottom = r;
                columns |= row;
            }
            int left = 0, right = 7;
            while ((columns & (1 << left)) == 0)
                left++;
            while ((columns & (1 << right)) == 0)
                right--;
            return new CellBox(left, top, right, bottom);
        }

        /// <summary>
        /// A Macrocell file's live cells' bounding box (null without any) in the universe's
        /// coordinates, its rule in canonical form, <c>#G</c> and metadata, read from its tree
        /// without building a universe (spec/formats.md "Measuring"). Refuses what reading
        /// refuses, but has no memory budget to run out of.
        /// </summary>
        internal static CellBox? Measure(string text, out string rule, out BigInteger generation, out PatternMetadata metadata)
        {
            List<string> lines = TextLines.Split(text);
            int start = HeaderLine(lines);
            var boxes = new BoxNodes();
            var read = new NodeLines();
            ReadLines(lines, start, boxes, read);
            rule = boxes.Canonical;
            generation = read.Generation;
            metadata = read.Metadata;
            long value = read.Values[read.Values.Count - 1];
            int level = read.Levels[read.Levels.Count - 1];
            CellBox? found = level >= 3 ? boxes.Boxes[(int)value] : BitsBox((ulong)value);
            if (found == null)
                return null;
            // A level-k root covers x in [-2^(k-1), 2^(k-1) - 1] and y in [-2^(k-1) + 1, 2^(k-1)].
            BigInteger left = -(BigInteger.One << (level - 1)), top = left + 1;
            CellBox box = found.Value;
            return new CellBox(left + box.X0, top + box.Y0, left + box.X1, top + box.Y1);
        }

        /// <summary>A node line as a root of level ≥ 4, placed by tree coordinates: a 2 × 2 or
        /// 4 × 4 square is centered in a leaf, and a leaf is the center of a level-4 root.</summary>
        private static (int Root, int Level) NormalizeRoot(HashLifeStore store, long value, int level)
        {
            if (level < 3)
            {
                value = store.Leaf((ulong)value << (level == 1 ? 27 : 18));
                level = 3;
            }
            int root = (int)value;
            if (level == 3)
            {
                ulong b = store.Bits(root);
                ulong sq = HashLifeLeaves.Square4;
                int nw = store.Leaf(HashLifeLeaves.Compose(0, 0, 0, b & sq));
                int ne = store.Leaf(HashLifeLeaves.Compose(0, 0, (b >> 4) & sq, 0));
                int sw = store.Leaf(HashLifeLeaves.Compose(0, (b >> 32) & sq, 0, 0));
                int se = store.Leaf(HashLifeLeaves.Compose((b >> 36) & sq, 0, 0, 0));
                root = store.Join(nw, ne, sw, se);
                level = 4;
            }
            return (root, level);
        }

        private static Parsed Parse(string text, int maxMemoryMb)
        {
            List<string> lines = TextLines.Split(text);
            int start = HeaderLine(lines);
            var universe = new HashLife(maxMemoryMb: maxMemoryMb);
            var parsed = new Parsed(universe);
            ReadLines(lines, start, new StoreNodes(universe), parsed);
            var (root, rootLevel) = NormalizeRoot(
                universe.Store, parsed.Values[parsed.Values.Count - 1], parsed.Levels[parsed.Levels.Count - 1]);
            universe.Adopt(root, rootLevel, parsed.Generation);
            return parsed;
        }

        /// <summary>The index of the <c>[M2]</c> header line, after any blank lines.</summary>
        private static int HeaderLine(List<string> lines)
        {
            int start = 0;
            while (start < lines.Count && TextLines.Strip(lines[start]).Length == 0)
                start++;
            if (start == lines.Count || !TextLines.Strip(lines[start]).StartsWith("[M2]", StringComparison.Ordinal))
                throw new FormatException("not a Macrocell file: the first line must start with [M2]");
            return start;
        }

        /// <summary>
        /// Every line after the header, checked, its nodes built in <paramref name="nodes"/>
        /// (spec/macrocell.md "Reading"): the one reading of the format, for a universe and for a
        /// measure alike.
        /// </summary>
        private static void ReadLines(List<string> lines, int start, INodes nodes, NodeLines into)
        {
            var notes = new MetadataReader();
            BigInteger generation = BigInteger.Zero;
            // Each node as (value, level): a node id for level ≥ 3, a spread bitmap below.
            List<long> values = into.Values;
            List<int> levels = into.Levels;

            for (int index = start + 1; index < lines.Count; index++)
            {
                int number = index + 1;
                string line = TextLines.Strip(lines[index]);
                if (line.Length == 0)
                    continue;
                if (line[0] == '#')
                {
                    if (line.StartsWith("#R", StringComparison.Ordinal))
                    {
                        try
                        {
                            nodes.Rule(TextLines.Strip(line.Substring(2)));
                        }
                        catch (ArgumentException e)
                        {
                            throw new FormatException($"line {number}: {e.Message}", e);
                        }
                    }
                    else if (line.StartsWith("#G", StringComparison.Ordinal))
                    {
                        generation = ParseGeneration(TextLines.Strip(line.Substring(2)), number);
                    }
                    else if (line.StartsWith("#FRAMES", StringComparison.Ordinal))
                    {
                        into.FramesLines.Add((number, line));
                    }
                    else if (line.StartsWith("#FRAME", StringComparison.Ordinal))
                    {
                        into.FrameLines.Add((number, line));
                    }
                    else
                    {
                        notes.HashLine(line);
                    }
                    continue;
                }
                if (line[0] == '.' || line[0] == '*' || line[0] == '$')
                {
                    values.Add(nodes.Leaf(LeafBits(line, number)));
                    levels.Add(3);
                    continue;
                }
                long[] fields = NodeFields(line, number);
                long level = fields[0];
                if (level == 1)
                {
                    if (fields[1] > 1 || fields[2] > 1 || fields[3] > 1 || fields[4] > 1)
                        throw new FormatException($"line {number}: HashLife cells are 0 or 1");
                    values.Add(fields[1] | fields[2] << 1 | fields[3] << 8 | fields[4] << 9);
                    levels.Add(1);
                }
                else if (level == 2)
                {
                    long nw = Child(values, levels, fields[1], 1, number, nodes), ne = Child(values, levels, fields[2], 1, number, nodes);
                    long sw = Child(values, levels, fields[3], 1, number, nodes), se = Child(values, levels, fields[4], 1, number, nodes);
                    values.Add(nw | ne << 2 | sw << 16 | se << 18);
                    levels.Add(2);
                }
                else if (level == 3)
                {
                    long nw = Child(values, levels, fields[1], 2, number, nodes), ne = Child(values, levels, fields[2], 2, number, nodes);
                    long sw = Child(values, levels, fields[3], 2, number, nodes), se = Child(values, levels, fields[4], 2, number, nodes);
                    values.Add(nodes.Leaf(HashLifeLeaves.Compose((ulong)nw, (ulong)ne, (ulong)sw, (ulong)se)));
                    levels.Add(3);
                }
                else if (level >= 4)
                {
                    if (level > HashLifeStore.MaxLevel)
                        throw new FormatException($"line {number}: level {level} is past the deepest tree, level {HashLifeStore.MaxLevel}");
                    int k = (int)level;
                    long nw = Child(values, levels, fields[1], k - 1, number, nodes);
                    long ne = Child(values, levels, fields[2], k - 1, number, nodes);
                    long sw = Child(values, levels, fields[3], k - 1, number, nodes);
                    long se = Child(values, levels, fields[4], k - 1, number, nodes);
                    values.Add(nodes.Join(nw, ne, sw, se, k));
                    levels.Add(k);
                }
                else
                {
                    throw new FormatException($"line {number}: level must be at least 1");
                }
            }
            if (values.Count == 0)
                throw new FormatException("Macrocell file has no nodes");
            into.Generation = generation;
            into.Metadata = notes.Result();
        }

        /// <summary>One or more ASCII digits, no sign (spec/macrocell.md "Reading").</summary>
        private static BigInteger ParseGeneration(string text, int number)
        {
            if (text.Length == 0)
                throw new FormatException($"line {number}: #G needs a generation in digits");
            for (int i = 0; i < text.Length; i++)
            {
                if (text[i] < '0' || text[i] > '9')
                    throw new FormatException($"line {number}: #G needs a generation in digits, got '{text}'");
            }
            return BigInteger.Parse(text, NumberStyles.None, CultureInfo.InvariantCulture);
        }

        /// <summary>The five decimal fields of <c>level nw ne sw se</c>.</summary>
        private static long[] NodeFields(string line, int number)
        {
            var fields = new long[5];
            int count = 0, i = 0;
            while (i < line.Length)
            {
                if (TextLines.IsSpace(line[i]))
                {
                    i++;
                    continue;
                }
                if (count == 5)
                    throw new FormatException($"line {number}: expected a leaf or 'level nw ne sw se'");
                long value = 0;
                while (i < line.Length && !TextLines.IsSpace(line[i]))
                {
                    char c = line[i];
                    if (c < '0' || c > '9')
                        throw new FormatException($"line {number}: expected a leaf or 'level nw ne sw se'");
                    value = value > (long.MaxValue - 9) / 10 ? long.MaxValue : value * 10 + (c - '0');
                    i++;
                }
                fields[count++] = value;
            }
            if (count != 5)
                throw new FormatException($"line {number}: expected a leaf or 'level nw ne sw se'");
            return fields;
        }

        private static long Child(List<long> values, List<int> levels, long index, int level, int number, INodes nodes)
        {
            if (index == 0)
                return level >= 3 ? nodes.Empty(level) : 0;
            if (index > values.Count)
                throw new FormatException($"line {number}: node {index} is not defined yet");
            int found = levels[(int)index - 1];
            if (found != level)
                throw new FormatException($"line {number}: node {index} has level {found}, not {level}");
            return values[(int)index - 1];
        }

        private static ulong LeafBits(string line, int number)
        {
            ulong bits = 0;
            int row = 0, column = 0;
            foreach (char c in line)
            {
                if (c == '$')
                {
                    row++;
                    column = 0;
                    if (row > 8)
                        throw new FormatException($"line {number}: a leaf has at most 8 rows");
                    continue;
                }
                if (row == 8)
                    throw new FormatException($"line {number}: a leaf has at most 8 rows");
                if ((c != '.' && c != '*') || column == 8)
                    throw new FormatException($"line {number}: leaf rows hold at most 8 of '.' and '*'");
                if (c == '*')
                    bits |= 1UL << (row * 8 + column);
                column++;
            }
            return bits;
        }

        /// <summary>
        /// The canonical Macrocell text of the universe (spec/macrocell.md "Writing"): the header,
        /// <c>#R</c>, <c>#G</c> when the generation is above 0, then the minimal root's distinct
        /// nodes in post-order — depth-first, children NW, NE, SW, SE before their parent,
        /// each once — with LF line ends.
        /// </summary>
        public static string Write(HashLife universe) => Write(universe, null);

        /// <summary>The canonical text with <paramref name="metadata"/>'s <c>#N</c>, <c>#O</c> and
        /// <c>#C</c> lines after <c>#R</c> and <c>#G</c> (spec/macrocell.md "Metadata").</summary>
        public static string Write(HashLife universe, PatternMetadata? metadata)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            var text = new StringBuilder();
            text.Append(Header).Append('\n');
            text.Append("#R ").Append(universe.Rule).Append('\n');
            BigInteger generation = universe.Generation;
            if (generation.Sign > 0)
                text.Append("#G ").Append(generation.ToString(CultureInfo.InvariantCulture)).Append('\n');
            foreach (string note in PatternMetadata.Lines(metadata))
                text.Append(note).Append('\n');
            var nodes = new List<string>();
            var (root, level) = universe.Minimal();
            WriteTree(universe.Store, root, level, nodes, new Dictionary<int, int>());
            foreach (string node in nodes)
                text.Append(node).Append('\n');
            return text.ToString();
        }

        /// <summary>
        /// Append the node lines of tree (root, level ≥ 3) not written yet — post-order, children
        /// NW, NE, SW, SE, each node once — and return the root's line number. <paramref name="index"/>
        /// maps each written node to its line; an empty child is 0 and never gets a line, but an
        /// empty root does.
        /// </summary>
        private static int WriteTree(HashLifeStore store, int root, int level, List<string> nodes, Dictionary<int, int> index)
        {
            if (index.TryGetValue(root, out int known))
                return known;
            if (level == 3)
            {
                nodes.Add(LeafLine(store.Bits(root)));
                index[root] = nodes.Count;
                return nodes.Count;
            }
            var stack = new Stack<(int Node, int Level, bool Ready)>();
            stack.Push((root, level, false));
            var line = new StringBuilder();
            while (stack.Count > 0)
            {
                var (n, k, ready) = stack.Pop();
                if (index.ContainsKey(n))
                    continue;
                if (k == 3)
                {
                    nodes.Add(LeafLine(store.Bits(n)));
                    index[n] = nodes.Count;
                    continue;
                }
                int e = store.Empty(k - 1);
                if (ready)
                {
                    line.Clear();
                    line.Append(k.ToString(CultureInfo.InvariantCulture));
                    for (int q = 0; q < 4; q++)
                    {
                        int kid = store.Kid(n, q);
                        line.Append(' ').Append((kid == e ? 0 : index[kid]).ToString(CultureInfo.InvariantCulture));
                    }
                    nodes.Add(line.ToString());
                    index[n] = nodes.Count;
                }
                else
                {
                    stack.Push((n, k, true));
                    for (int q = 3; q >= 0; q--)
                    {
                        int kid = store.Kid(n, q);
                        if (kid != e)
                            stack.Push((kid, k - 1, false));
                    }
                }
            }
            return index[root];
        }

        /// <summary>A leaf line in its compact form: rows through the last live one, each without
        /// its trailing '.' and ended by '$'; the empty leaf is "$".</summary>
        private static string LeafLine(ulong bits)
        {
            int last = -1;
            for (int r = 0; r < 8; r++)
            {
                if (((bits >> (8 * r)) & 0xFF) != 0)
                    last = r;
            }
            if (last < 0)
                return "$";
            var text = new StringBuilder();
            for (int r = 0; r <= last; r++)
            {
                int row = (int)((bits >> (8 * r)) & 0xFF);
                for (int x = 0; row >> x != 0; x++)
                    text.Append(((row >> x) & 1) != 0 ? '*' : '.');
                text.Append('$');
            }
            return text.ToString();
        }

        // ---- timelines (spec/macrocell.md "Timelines") ------------------------------------------

        /// <summary>A timeline's step is below 2^4096.</summary>
        private static readonly BigInteger StepLimit = BigInteger.One << 4096;

        /// <summary>A timeline file's frames (spec/macrocell.md "Timelines"): one
        /// <c>#FRAMES count first step</c> line and a <c>#FRAME i n</c> line for every frame;
        /// anything else throws <see cref="FormatException"/>.</summary>
        public static MacrocellTimeline ReadTimeline(byte[] data, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return ReadTimeline(PatternText.Decode(PatternText.Inflate(data)), maxMemoryMb);
        }

        /// <summary>A timeline file's frames, from its text.</summary>
        public static MacrocellTimeline ReadTimeline(string text, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            Parsed parsed = Parse(text, maxMemoryMb);
            if (parsed.FramesLines.Count == 0)
                throw new FormatException("not a timeline: the file has no #FRAMES line");
            if (parsed.FramesLines.Count > 1)
                throw new FormatException($"line {parsed.FramesLines[1].Number}: a second #FRAMES line");
            var (number, line) = parsed.FramesLines[0];
            List<string> fields = TextLines.SplitSpace(line.Substring("#FRAMES".Length));
            if (fields.Count != 3)
                throw new FormatException($"line {number}: expected '#FRAMES count first step'");
            BigInteger count = Number(fields[0], number, "the frame count");
            BigInteger first = Number(fields[1], number, "the first generation");
            BigInteger step = Step(fields[2], number);
            if (count.IsZero)
                throw new FormatException($"line {number}: a timeline has at least one frame");
            var refs = new Dictionary<BigInteger, BigInteger>();
            foreach (var (frameNumber, frameLine) in parsed.FrameLines)
            {
                List<string> parts = TextLines.SplitSpace(frameLine.Substring("#FRAME".Length));
                if (parts.Count != 2)
                    throw new FormatException($"line {frameNumber}: expected '#FRAME index node'");
                BigInteger index = Number(parts[0], frameNumber, "a frame index");
                BigInteger node = Number(parts[1], frameNumber, "a frame's node");
                if (index >= count)
                    throw new FormatException($"line {frameNumber}: frame {index} is past the {count} frames");
                if (refs.ContainsKey(index))
                    throw new FormatException($"line {frameNumber}: frame {index} is given twice");
                if (node.IsZero || node > parsed.Values.Count)
                    throw new FormatException($"line {frameNumber}: the file has no node {node}");
                refs[index] = node;
            }
            if (refs.Count != count)
            {
                BigInteger missing = BigInteger.Zero;
                while (refs.ContainsKey(missing))
                    missing++;
                throw new FormatException($"the timeline has no #FRAME line for frame {missing}");
            }
            HashLife universe = parsed.Universe;
            var frames = new List<HashLifeSnapshot>();
            for (int i = 0; i < (int)count; i++)
            {
                int node = (int)refs[i] - 1;
                var (root, level) = NormalizeRoot(universe.Store, parsed.Values[node], parsed.Levels[node]);
                frames.Add(universe.SnapshotAt(root, level, first + i * step));
            }
            return new MacrocellTimeline(universe, frames, step, parsed.Metadata);
        }

        private static BigInteger Number(string text, int number, string what)
        {
            for (int i = 0; i < text.Length; i++)
            {
                if (text[i] < '0' || text[i] > '9')
                    throw new FormatException($"line {number}: {what} must be ASCII digits, got '{text}'");
            }
            if (text.Length == 0)
                throw new FormatException($"line {number}: {what} must be ASCII digits");
            return BigInteger.Parse(text, NumberStyles.None, CultureInfo.InvariantCulture);
        }

        /// <summary>Digits or <c>b^e</c>, at least 1 and below 2^4096; a power is measured
        /// before it is computed.</summary>
        private static BigInteger Step(string text, int number)
        {
            BigInteger step;
            int caret = text.IndexOf('^');
            if (caret >= 0)
            {
                BigInteger b = Number(text.Substring(0, caret), number, "a step's base");
                BigInteger e = Number(text.Substring(caret + 1), number, "a step's exponent");
                if (e.IsZero || b.IsOne)
                    step = BigInteger.One;
                else if (b.IsZero)
                    step = BigInteger.Zero;
                else if ((BitLength(b) - 1) * e >= 4096)
                    throw new FormatException($"line {number}: the step {text} is not below 2^4096");
                else
                    step = BigInteger.Pow(b, (int)e);
            }
            else
            {
                step = Number(text, number, "the step");
            }
            if (step.Sign <= 0 || step >= StepLimit)
                throw new FormatException($"line {number}: the step must be at least 1 and below 2^4096");
            return step;
        }

        private static long BitLength(BigInteger value)
        {
            long bits = 0;
            byte[] bytes = value.ToByteArray(); // little-endian two's complement; value > 0
            int top = bytes.Length - 1;
            while (top > 0 && bytes[top] == 0)
                top--;
            for (int b = bytes[top]; b != 0; b >>= 1)
                bits++;
            return bits + 8L * top;
        }

        /// <summary>floor(n^(1/e)) for n ≥ 1, e ≥ 1, by Newton's method from above.</summary>
        private static BigInteger RootOf(BigInteger n, int e)
        {
            BigInteger x = BigInteger.One << (int)((BitLength(n) + e - 1) / e);
            while (true)
            {
                BigInteger y = ((e - 1) * x + n / BigInteger.Pow(x, e - 1)) / e;
                if (y >= x)
                    return x;
                x = y;
            }
        }

        /// <summary>(b, e) with step = b^e and b the smallest integer of at least 2 that works.</summary>
        internal static (BigInteger Base, int Exponent) Power(BigInteger step)
        {
            if (step.IsOne)
                return (2, 0);
            for (int e = (int)BitLength(step) - 1; e > 1; e--)
            {
                BigInteger b = RootOf(step, e);
                if (BigInteger.Pow(b, e) == step)
                    return (b, e);
            }
            return (step, 1);
        }

        /// <summary>
        /// The canonical timeline file of <paramref name="frames"/>, snapshots of
        /// <paramref name="universe"/> at evenly spaced generations (spec/macrocell.md
        /// "Timelines", "Writing"). The file's own root and <c>#G</c> are the last frame's.
        /// </summary>
        public static string WriteTimeline(
            HashLife universe, IReadOnlyList<HashLifeSnapshot> frames, PatternMetadata? metadata = null)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            if (frames == null)
                throw new ArgumentNullException(nameof(frames));
            if (frames.Count == 0)
                throw new ArgumentException("a timeline needs at least one frame", nameof(frames));
            foreach (HashLifeSnapshot frame in frames)
            {
                if (frame == null || !ReferenceEquals(frame.Owner, universe))
                    throw new ArgumentException("every frame must be a snapshot of the universe being written", nameof(frames));
            }
            BigInteger step = frames.Count > 1 ? frames[1].Generation - frames[0].Generation : BigInteger.One;
            for (int i = 1; i < frames.Count; i++)
            {
                if (frames[i].Generation - frames[i - 1].Generation != step)
                    throw new ArgumentException("a timeline's frames are evenly spaced in generations", nameof(frames));
            }
            if (step.Sign <= 0 || step >= StepLimit)
                throw new ArgumentException($"a timeline's step is at least 1 and below 2^4096, not {step}", nameof(frames));
            var (b, e) = Power(step);
            var text = new StringBuilder();
            text.Append(Header).Append('\n');
            text.Append("#R ").Append(universe.Rule).Append('\n');
            BigInteger last = frames[frames.Count - 1].Generation;
            if (last.Sign > 0)
                text.Append("#G ").Append(last.ToString(CultureInfo.InvariantCulture)).Append('\n');
            text.Append("#FRAMES ").Append(frames.Count.ToString(CultureInfo.InvariantCulture)).Append(' ')
                .Append(frames[0].Generation.ToString(CultureInfo.InvariantCulture)).Append(' ')
                .Append(b.ToString(CultureInfo.InvariantCulture)).Append('^')
                .Append(e.ToString(CultureInfo.InvariantCulture)).Append('\n');
            foreach (string note in PatternMetadata.Lines(metadata))
                text.Append(note).Append('\n');
            HashLifeStore store = universe.Store;
            var nodes = new List<string>();
            var index = new Dictionary<int, int>();
            var roots = new int[frames.Count];
            for (int i = 0; i < frames.Count; i++)
            {
                var (root, level) = universe.Minimal(frames[i].RootNode, frames[i].Level);
                roots[i] = WriteTree(store, root, level, nodes, index);
            }
            int lastRoot = roots[roots.Length - 1];
            if (lastRoot != nodes.Count)
                nodes.Add(nodes[lastRoot - 1]); // a reader without timelines loads the last frame
            foreach (string node in nodes)
                text.Append(node).Append('\n');
            for (int i = 0; i < roots.Length; i++)
            {
                text.Append("#FRAME ").Append(i.ToString(CultureInfo.InvariantCulture)).Append(' ')
                    .Append(roots[i].ToString(CultureInfo.InvariantCulture)).Append('\n');
            }
            return text.ToString();
        }
    }

    /// <summary>
    /// A timeline file's frames (spec/macrocell.md "Timelines"): snapshots of one universe that
    /// holds every frame's nodes. <see cref="Universe"/> is left at the file's own root and
    /// <c>#G</c>; frame i is the universe at generation Frames[0].Generation + i × <see cref="Step"/>.
    /// The Python reference's heaton_life.ca.hashlife.MacrocellTimeline.
    /// </summary>
    public sealed class MacrocellTimeline
    {
        internal MacrocellTimeline(
            HashLife universe, IReadOnlyList<HashLifeSnapshot> frames, BigInteger step, PatternMetadata metadata)
        {
            Universe = universe;
            Frames = frames;
            Step = step;
            Metadata = metadata;
        }

        public HashLife Universe { get; }

        public IReadOnlyList<HashLifeSnapshot> Frames { get; }

        public BigInteger Step { get; }

        public PatternMetadata Metadata { get; }
    }

    /// <summary>Line splitting and whitespace exactly as the Python reference's str methods
    /// (<c>splitlines</c>, <c>strip</c>, <c>split</c>), so the readers agree on every file.</summary>
    internal static class TextLines
    {
        internal static bool IsSpace(char c) => char.IsWhiteSpace(c) || (c >= '\x1c' && c <= '\x1f');

        internal static bool IsBreak(char c)
            => c == '\n' || c == '\r' || c == '\x0b' || c == '\x0c' || c == '\x1c' || c == '\x1d'
                || c == '\x1e' || c == '\x85' || c == (char)0x2028 || c == (char)0x2029;

        internal static List<string> Split(string text)
        {
            var lines = new List<string>();
            int start = 0, i = 0;
            while (i < text.Length)
            {
                char c = text[i];
                if (!IsBreak(c))
                {
                    i++;
                    continue;
                }
                lines.Add(text.Substring(start, i - start));
                i += c == '\r' && i + 1 < text.Length && text[i + 1] == '\n' ? 2 : 1;
                start = i;
            }
            if (start < text.Length)
                lines.Add(text.Substring(start));
            return lines;
        }

        internal static string Strip(string text)
        {
            int start = 0, end = text.Length;
            while (start < end && IsSpace(text[start]))
                start++;
            while (end > start && IsSpace(text[end - 1]))
                end--;
            return start == 0 && end == text.Length ? text : text.Substring(start, end - start);
        }

        /// <summary>The reference's <c>rstrip</c>: trailing whitespace removed.</summary>
        internal static string StripEnd(string text)
        {
            int end = text.Length;
            while (end > 0 && IsSpace(text[end - 1]))
                end--;
            return end == text.Length ? text : text.Substring(0, end);
        }

        /// <summary>The reference's <c>split()</c>: the runs of non-whitespace.</summary>
        internal static List<string> SplitSpace(string text)
        {
            var parts = new List<string>();
            int i = 0;
            while (i < text.Length)
            {
                if (IsSpace(text[i]))
                {
                    i++;
                    continue;
                }
                int start = i;
                while (i < text.Length && !IsSpace(text[i]))
                    i++;
                parts.Add(text.Substring(start, i - start));
            }
            return parts;
        }

        internal static string StripStart(string text)
        {
            int start = 0;
            while (start < text.Length && IsSpace(text[start]))
                start++;
            return start == 0 ? text : text.Substring(start);
        }
    }
}
