using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text;

namespace HeatonLife
{
    /// <summary>
    /// Multi-state Macrocell files (spec/macrocell.md "Multi-state files"): the format of the
    /// two-state universe, with leaves of four states. <c>1 nw ne sw se</c> lines are 2 × 2 squares
    /// of states, higher levels name their children by line number, and <c>0</c> is a square of 0
    /// cells; reading also takes the two-state leaf lines, as states 0 and 1. Writing is canonical,
    /// and timelines read into snapshots and are written from them as for two states.
    /// The Python reference's heaton_life.ca.hashlife.multistate.macrocell.
    /// </summary>
    public static class MultiStateMacrocell
    {
        /// <summary>A universe from Macrocell bytes, gzip-compressed or not; <paramref name="rule"/>
        /// is the rule when the file names none (default WireWorld). Timeline lines are skipped.</summary>
        public static MultiStateHashLife Read(byte[] data, StateRule? rule = null, int maxMemoryMb = MultiStateHashLife.DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return Read(PatternText.Decode(PatternText.Inflate(data)), rule, maxMemoryMb);
        }

        /// <summary>A universe from Macrocell text, placed by tree coordinates.</summary>
        public static MultiStateHashLife Read(string text, StateRule? rule = null, int maxMemoryMb = MultiStateHashLife.DefaultMaxMemoryMb)
            => Parse(text, rule, maxMemoryMb).Universe;

        private static (MultiStateHashLife Universe, Built Built) Parse(string text, StateRule? rule, int maxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            StateRule fallback = MultiStateFiles.Fallback(rule);
            var universe = new MultiStateHashLife(fallback, maxMemoryMb);
            Built built = Build(universe, text, fallback);
            universe.StateRule = built.Rule;
            universe.Adopt(built.Root, built.Level, built.Generation);
            return (universe, built);
        }

        /// <summary>A Macrocell file's tree built in a universe's store, which it hasn't become.</summary>
        internal sealed class Built
        {
            public int Root;
            public int Level;
            public BigInteger Generation;
            public StateRule Rule = WireworldRule.Instance;
            public PatternMetadata Metadata = PatternMetadata.Empty;
            public readonly List<int> Nodes = new List<int>();
            public readonly List<int> Levels = new List<int>();
            public readonly List<(int Number, string Line)> FramesLines = new List<(int, string)>();
            public readonly List<(int Number, string Line)> FrameLines = new List<(int, string)>();
        }

        /// <summary>
        /// Read Macrocell text into <paramref name="universe"/>'s store without changing the
        /// universe: its root, level, generation and rule stay. <paramref name="fallback"/> is the
        /// rule when the file names none. A malformed file, or a state the rule lacks, throws
        /// <see cref="FormatException"/>.
        /// </summary>
        internal static Built Build(MultiStateHashLife universe, string text, StateRule fallback)
        {
            List<string> lines = TextLines.Split(text);
            int start = Macrocell.HeaderLine(lines);
            MultiStateStore store = universe.Store;
            var built = new Built();
            var notes = new MetadataReader();
            string? named = null;
            int top = 0; // the largest state seen
            for (int index = start + 1; index < lines.Count; index++)
            {
                int number = index + 1;
                string line = TextLines.Strip(lines[index]);
                if (line.Length == 0)
                    continue;
                if (line[0] == '#')
                {
                    if (line.StartsWith("#R", StringComparison.Ordinal))
                        named = TextLines.Strip(line.Substring(2));
                    else if (line.StartsWith("#G", StringComparison.Ordinal))
                        built.Generation = Macrocell.ParseGeneration(TextLines.Strip(line.Substring(2)), number);
                    else if (line.StartsWith("#FRAMES", StringComparison.Ordinal))
                        built.FramesLines.Add((number, line));
                    else if (line.StartsWith("#FRAME", StringComparison.Ordinal))
                        built.FrameLines.Add((number, line));
                    else
                        notes.HashLine(line);
                    continue;
                }
                if (line[0] == '.' || line[0] == '*' || line[0] == '$')
                {
                    ulong bits = Macrocell.LeafBits(line, number);
                    if (bits != 0)
                        top = Math.Max(top, 1);
                    built.Nodes.Add(BitsNode(store, bits));
                    built.Levels.Add(3);
                    continue;
                }
                long[] fields = Macrocell.NodeFields(line, number);
                long level = fields[0];
                if (level > MultiStateHashLife.MaxLevel)
                    throw new FormatException(
                        $"line {number}: level {level} is past the deepest tree, level {MultiStateHashLife.MaxLevel}");
                if (level == 0)
                    throw new FormatException($"line {number}: level must be at least 1");
                if (level == 1)
                {
                    int states = 0;
                    for (int i = 0; i < 4; i++)
                    {
                        long state = fields[i + 1];
                        if (state >= StateRules.MaxStates)
                            throw new FormatException($"line {number}: a state is at most {StateRules.MaxStates - 1}");
                        top = Math.Max(top, (int)state);
                        states |= (int)state << (8 * i);
                    }
                    built.Nodes.Add(store.Leaf(states));
                    built.Levels.Add(1);
                }
                else
                {
                    int k = (int)level;
                    int nw = Child(built, store, fields[1], k - 1, number), ne = Child(built, store, fields[2], k - 1, number);
                    int sw = Child(built, store, fields[3], k - 1, number), se = Child(built, store, fields[4], k - 1, number);
                    built.Nodes.Add(store.Join(nw, ne, sw, se));
                    built.Levels.Add(k);
                }
            }
            if (built.Nodes.Count == 0)
                throw new FormatException("Macrocell file has no nodes");
            built.Rule = named == null ? fallback : MultiStateFiles.FileRule(named, fallback);
            if (top >= built.Rule.States)
                throw new FormatException(
                    $"the file holds state {top}, which {built.Rule.Canonical} doesn't have ({built.Rule.States} states)");
            (built.Root, built.Level) = universe.Place(built.Nodes[built.Nodes.Count - 1], built.Levels[built.Levels.Count - 1]);
            built.Metadata = notes.Result();
            return built;
        }

        private static int Child(Built built, MultiStateStore store, long index, int level, int number)
        {
            if (index == 0)
                return store.Empty(level);
            if (index > built.Nodes.Count)
                throw new FormatException($"line {number}: node {index} is not defined yet");
            int found = built.Levels[(int)index - 1];
            if (found != level)
                throw new FormatException($"line {number}: node {index} has level {found}, not {level}");
            return built.Nodes[(int)index - 1];
        }

        /// <summary>A two-state 8 × 8 leaf (bit 8r + c is row r, column c) as a level-3 node of states.</summary>
        private static int BitsNode(MultiStateStore store, ulong bits)
        {
            Span<int> quads = stackalloc int[4];
            Span<int> leaves = stackalloc int[4];
            for (int q = 0; q < 4; q++)
            {
                int qx = 4 * (q & 1), qy = 4 * (q >> 1);
                for (int l = 0; l < 4; l++)
                {
                    int x = qx + 2 * (l & 1), y = qy + 2 * (l >> 1);
                    int states = (int)((bits >> (8 * y + x)) & 1)
                        | (int)((bits >> (8 * y + x + 1)) & 1) << 8
                        | (int)((bits >> (8 * y + x + 8)) & 1) << 16
                        | (int)((bits >> (8 * y + x + 9)) & 1) << 24;
                    leaves[l] = store.Leaf(states);
                }
                quads[q] = store.Join(leaves[0], leaves[1], leaves[2], leaves[3]);
            }
            return store.Join(quads[0], quads[1], quads[2], quads[3]);
        }

        /// <summary>The canonical Macrocell text of the universe (spec/macrocell.md "Multi-state
        /// files").</summary>
        public static string Write(MultiStateHashLife universe) => Write(universe, null);

        /// <summary>The canonical text with <paramref name="metadata"/>'s lines after <c>#R</c> and
        /// <c>#G</c>.</summary>
        public static string Write(MultiStateHashLife universe, PatternMetadata? metadata)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            var text = new StringBuilder();
            text.Append(Macrocell.Header).Append('\n');
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
        /// Append the node lines of tree (root, level ≥ 1) not written yet — post-order, children
        /// NW, NE, SW, SE, each node once — and return the root's line number. An empty child is 0
        /// and never gets a line, but an empty root does.
        /// </summary>
        private static int WriteTree(MultiStateStore store, int root, int level, List<string> nodes, Dictionary<int, int> index)
        {
            if (index.TryGetValue(root, out int known))
                return known;
            var stack = new Stack<(int Node, int Level, bool Ready)>();
            stack.Push((root, level, false));
            var line = new StringBuilder();
            while (stack.Count > 0)
            {
                var (n, k, ready) = stack.Pop();
                if (index.ContainsKey(n))
                    continue;
                line.Clear();
                if (k == 1)
                {
                    int states = store.States(n);
                    line.Append('1');
                    for (int i = 0; i < 4; i++)
                        line.Append(' ').Append(((states >> (8 * i)) & 0xFF).ToString(CultureInfo.InvariantCulture));
                    nodes.Add(line.ToString());
                    index[n] = nodes.Count;
                    continue;
                }
                int e = store.Empty(k - 1);
                if (ready)
                {
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

        // ---- timelines (spec/macrocell.md "Timelines") ------------------------------------------

        private static readonly BigInteger StepLimit = BigInteger.One << 4096;

        /// <summary>A multi-state timeline file's frames: one <c>#FRAMES count first step</c> line
        /// and a <c>#FRAME i n</c> line for every frame; anything else throws
        /// <see cref="FormatException"/>.</summary>
        public static MultiStateTimeline ReadTimeline(byte[] data, StateRule? rule = null, int maxMemoryMb = MultiStateHashLife.DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return ReadTimeline(PatternText.Decode(PatternText.Inflate(data)), rule, maxMemoryMb);
        }

        /// <summary>A multi-state timeline file's frames, from its text.</summary>
        public static MultiStateTimeline ReadTimeline(string text, StateRule? rule = null, int maxMemoryMb = MultiStateHashLife.DefaultMaxMemoryMb)
        {
            var (universe, built) = Parse(text, rule, maxMemoryMb);
            var timeline = TimelineFrames(universe, built)
                ?? throw new FormatException("not a timeline: the file has no #FRAMES line");
            var frames = new List<HashLifeSnapshot>(timeline.Frames.Count);
            foreach (var (root, level, generation) in timeline.Frames)
                frames.Add(universe.SnapshotAt(root, level, generation, built.Rule.States));
            return new MultiStateTimeline(universe, frames, timeline.Step, built.Metadata);
        }

        /// <summary>A file's timeline: its step, and each frame's root as (node, level, generation)
        /// in order, placed as a file's root is; or null for a file without a <c>#FRAMES</c> line.</summary>
        internal static (BigInteger Step, List<(int Root, int Level, BigInteger Generation)> Frames)? TimelineFrames(
            MultiStateHashLife universe, Built built)
        {
            if (built.FramesLines.Count == 0)
                return null;
            if (built.FramesLines.Count > 1)
                throw new FormatException($"line {built.FramesLines[1].Number}: a second #FRAMES line");
            var (number, line) = built.FramesLines[0];
            List<string> fields = TextLines.SplitSpace(line.Substring("#FRAMES".Length));
            if (fields.Count != 3)
                throw new FormatException($"line {number}: expected '#FRAMES count first step'");
            BigInteger count = Macrocell.Number(fields[0], number, "the frame count");
            BigInteger first = Macrocell.Number(fields[1], number, "the first generation");
            BigInteger step = Macrocell.Step(fields[2], number);
            if (count.IsZero)
                throw new FormatException($"line {number}: a timeline has at least one frame");
            var refs = new Dictionary<BigInteger, BigInteger>();
            foreach (var (frameNumber, frameLine) in built.FrameLines)
            {
                List<string> parts = TextLines.SplitSpace(frameLine.Substring("#FRAME".Length));
                if (parts.Count != 2)
                    throw new FormatException($"line {frameNumber}: expected '#FRAME index node'");
                BigInteger index = Macrocell.Number(parts[0], frameNumber, "a frame index");
                BigInteger node = Macrocell.Number(parts[1], frameNumber, "a frame's node");
                if (index >= count)
                    throw new FormatException($"line {frameNumber}: frame {index} is past the {count} frames");
                if (refs.ContainsKey(index))
                    throw new FormatException($"line {frameNumber}: frame {index} is given twice");
                if (node.IsZero || node > built.Nodes.Count)
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
            var frames = new List<(int Root, int Level, BigInteger Generation)>();
            for (int i = 0; i < (int)count; i++)
            {
                int node = (int)refs[i] - 1;
                var (root, level) = universe.Place(built.Nodes[node], built.Levels[node]);
                frames.Add((root, level, first + i * step));
            }
            return (step, frames);
        }

        /// <summary>
        /// The canonical timeline file of <paramref name="frames"/>, snapshots of
        /// <paramref name="universe"/> at evenly spaced generations (spec/macrocell.md "Timelines").
        /// The file's own root and <c>#G</c> are the last frame's. A frame holding a state the
        /// universe's rule lacks throws <see cref="ArgumentException"/>.
        /// </summary>
        public static string WriteTimeline(
            MultiStateHashLife universe, IReadOnlyList<HashLifeSnapshot> frames, PatternMetadata? metadata = null)
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
                if (frame.Released)
                    throw new ArgumentException("a released snapshot holds no cells to write", nameof(frames));
            }
            BigInteger step = frames.Count > 1 ? frames[1].Generation - frames[0].Generation : BigInteger.One;
            for (int i = 1; i < frames.Count; i++)
            {
                if (frames[i].Generation - frames[i - 1].Generation != step)
                    throw new ArgumentException("a timeline's frames are evenly spaced in generations", nameof(frames));
            }
            if (step.Sign <= 0 || step >= StepLimit)
                throw new ArgumentException($"a timeline's step is at least 1 and below 2^4096, not {step}", nameof(frames));
            foreach (HashLifeSnapshot frame in frames)
                universe.CheckStates(frame, nameof(frames)); // the file names the universe's rule
            var (b, e) = Macrocell.Power(step);
            var text = new StringBuilder();
            text.Append(Macrocell.Header).Append('\n');
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
            MultiStateStore store = universe.Store;
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
    /// A multi-state timeline file's frames: snapshots of one universe that holds every frame's
    /// nodes. <see cref="Universe"/> is left at the file's own root and <c>#G</c>; frame i is the
    /// universe at generation Frames[0].Generation + i × <see cref="Step"/>.
    /// The Python reference's heaton_life.ca.hashlife.MultiStateTimeline.
    /// </summary>
    public sealed class MultiStateTimeline
    {
        internal MultiStateTimeline(
            MultiStateHashLife universe, IReadOnlyList<HashLifeSnapshot> frames, BigInteger step, PatternMetadata metadata)
        {
            Universe = universe;
            Frames = frames;
            Step = step;
            Metadata = metadata;
        }

        public MultiStateHashLife Universe { get; }

        public IReadOnlyList<HashLifeSnapshot> Frames { get; }

        public BigInteger Step { get; }

        public PatternMetadata Metadata { get; }
    }

    /// <summary>
    /// A pattern file read into a new <see cref="MultiStateHashLife"/>, with its format and
    /// metadata. A Macrocell timeline also gives its <see cref="Frames"/> and <see cref="Step"/>.
    /// The Python reference's heaton_life.ca.hashlife.MultiStatePatternUniverse.
    /// </summary>
    public sealed class MultiStatePatternUniverse
    {
        internal MultiStatePatternUniverse(
            PatternFormat format, MultiStateHashLife universe, PatternMetadata metadata,
            IReadOnlyList<HashLifeSnapshot> frames, BigInteger? step)
        {
            Format = format;
            Universe = universe;
            Metadata = metadata;
            Frames = frames;
            Step = step;
        }

        public PatternFormat Format { get; }

        public MultiStateHashLife Universe { get; }

        public PatternMetadata Metadata { get; }

        /// <summary>A timeline's frames, snapshots of <see cref="Universe"/> in order; empty for any
        /// other file.</summary>
        public IReadOnlyList<HashLifeSnapshot> Frames { get; }

        /// <summary>A timeline's step, or null for a file that is no timeline.</summary>
        public BigInteger? Step { get; }
    }

    /// <summary>
    /// Pattern files into the unbounded multi-state universe (spec/hashlife-multistate.md
    /// "Pattern I/O"): Macrocell and RLE, gzip-compressed or not, recognized by content; the other
    /// formats hold two states and are refused. RLE reads either dialect and writes the canonical
    /// encoding behind a <c>#CXRLE</c> line. The Python reference's
    /// heaton_life.ca.hashlife.multistate.files and .rle.
    /// </summary>
    public static class MultiStateFiles
    {
        /// <summary>The rule a file that names none is read under, unless the reader is given another.</summary>
        public const string DefaultRule = "WireWorld";

        private const long RunCap = 1L << 40; // run counts and offsets saturate here, far past the editing box

        internal static StateRule Fallback(StateRule? rule) => StateRules.Check(rule ?? StateRules.Compile(DefaultRule));

        /// <summary>The rule a file names: <paramref name="given"/> when the name is its canonical
        /// name, ignoring ASCII case, else the rule of that name.</summary>
        internal static StateRule FileRule(string text, StateRule given)
        {
            if (StateRules.Names(text, given))
                return StateRules.Check(given);
            try
            {
                return StateRules.Check(StateRules.Compile(text));
            }
            catch (ArgumentException e)
            {
                throw new FormatException(e.Message, e);
            }
        }

        /// <summary>A Macrocell or RLE file's bytes (gzip-compressed or not) as a new universe; the
        /// rule is the file's, or <paramref name="rule"/> (default WireWorld) when it names none.</summary>
        public static MultiStatePatternUniverse ReadUniverse(
            byte[] data, StateRule? rule = null, int maxMemoryMb = MultiStateHashLife.DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return ReadUniverse(PatternFiles.Detect(data), () => Text(data), rule, maxMemoryMb);
        }

        /// <summary>A Macrocell or RLE file's text as a new universe.</summary>
        public static MultiStatePatternUniverse ReadUniverse(
            string text, StateRule? rule = null, int maxMemoryMb = MultiStateHashLife.DefaultMaxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            return ReadUniverse(PatternFiles.Detect(text), () => text, rule, maxMemoryMb);
        }

        private static MultiStatePatternUniverse ReadUniverse(
            PatternFormat format, Func<string> text, StateRule? rule, int maxMemoryMb)
        {
            StateRule fallback = Fallback(rule);
            var universe = new MultiStateHashLife(fallback, maxMemoryMb);
            Read read = ReadInto(universe, format, text, fallback);
            universe.StateRule = read.Rule;
            universe.Adopt(read.Root, read.Level, read.Generation);
            var frames = new List<HashLifeSnapshot>(read.Frames.Count);
            foreach (var (root, level, generation) in read.Frames)
                frames.Add(universe.SnapshotAt(root, level, generation, read.Rule.States));
            return new MultiStatePatternUniverse(read.Format, universe, read.Metadata, frames, read.Step);
        }

        /// <summary>A Macrocell or RLE file's bytes read into <paramref name="universe"/>'s own store
        /// as a snapshot, with its format, rule, metadata and a timeline's frames; a file that names
        /// no rule takes the universe's. The universe's state, rule and earlier snapshots stay.</summary>
        public static PatternSnapshot ReadSnapshot(MultiStateHashLife universe, byte[] data)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return ReadSnapshot(universe, PatternFiles.Detect(data), () => Text(data));
        }

        /// <summary>A Macrocell or RLE file's text read into <paramref name="universe"/>'s store.</summary>
        public static PatternSnapshot ReadSnapshot(MultiStateHashLife universe, string text)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            return ReadSnapshot(universe, PatternFiles.Detect(text), () => text);
        }

        private static PatternSnapshot ReadSnapshot(MultiStateHashLife universe, PatternFormat format, Func<string> text)
        {
            Read read = ReadInto(universe, format, text, universe.StateRule);
            int states = read.Rule.States;
            HashLifeSnapshot snapshot = universe.SnapshotAt(read.Root, read.Level, read.Generation, states);
            var frames = new List<HashLifeSnapshot>(read.Frames.Count);
            foreach (var (root, level, generation) in read.Frames)
                frames.Add(universe.SnapshotAt(root, level, generation, states));
            return new PatternSnapshot(read.Format, snapshot, read.Rule.Canonical, read.Metadata, frames, read.Step);
        }

        private static string Text(byte[] data) => PatternText.Decode(PatternText.Inflate(data));

        /// <summary>A file read into a store, the universe not yet any of it.</summary>
        private sealed class Read
        {
            public PatternFormat Format;
            public int Root;
            public int Level;
            public BigInteger Generation;
            public StateRule Rule = WireworldRule.Instance;
            public PatternMetadata Metadata = PatternMetadata.Empty;
            public BigInteger? Step;
            public List<(int Root, int Level, BigInteger Generation)> Frames = new List<(int, int, BigInteger)>();
        }

        private static Read ReadInto(MultiStateHashLife universe, PatternFormat format, Func<string> text, StateRule fallback)
        {
            if (format == PatternFormat.Rle)
            {
                string body = text();
                var (root, level, generation, rule) = BuildRle(universe, body, fallback);
                return new Read
                {
                    Format = format,
                    Root = root,
                    Level = level,
                    Generation = generation,
                    Rule = rule,
                    Metadata = Patterns.RleMetadata(body),
                };
            }
            if (format == PatternFormat.Macrocell)
            {
                MultiStateMacrocell.Built built = MultiStateMacrocell.Build(universe, text(), fallback);
                var timeline = MultiStateMacrocell.TimelineFrames(universe, built);
                var read = new Read
                {
                    Format = format,
                    Root = built.Root,
                    Level = built.Level,
                    Generation = built.Generation,
                    Rule = built.Rule,
                    Metadata = built.Metadata,
                };
                if (timeline != null)
                {
                    read.Step = timeline.Value.Step;
                    read.Frames = timeline.Value.Frames;
                }
                return read;
            }
            throw new FormatException(
                $"a multi-state universe reads Macrocell and RLE files; {PatternFiles.FormatName(format)} holds two states");
        }

        /// <summary>A universe from RLE text of either dialect; <paramref name="rule"/> is the rule
        /// when the header names none (default WireWorld).</summary>
        internal static MultiStateHashLife ReadRle(string text, StateRule? rule, int maxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            StateRule fallback = Fallback(rule);
            var universe = new MultiStateHashLife(fallback, maxMemoryMb);
            var (root, level, generation, found) = BuildRle(universe, text, fallback);
            universe.StateRule = found;
            universe.Adopt(root, level, generation);
            return universe;
        }

        /// <summary>
        /// RLE read into <paramref name="universe"/>'s store without changing the universe, streamed
        /// run by run into leaves: the pattern's tree, its generation and its rule. A state the rule
        /// lacks, or a non-zero cell outside the editing box, is refused.
        /// </summary>
        internal static (int Root, int Level, BigInteger Generation, StateRule Rule) BuildRle(
            MultiStateHashLife universe, string text, StateRule fallback)
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
                Patterns.ReadCxrle(lines[0], ref posX, ref posY, ref generation);
            lines.RemoveAll(line => line[0] == '#');
            string? named = null;
            if (lines.Count > 0 && Patterns.TryParseHeader(lines[0], out _, out _, out named))
                lines.RemoveAt(0);
            if (named != null) // spec/patterns.md "Bounded grids", spec/formats.md "Rules in survival/birth order"
            {
                named = PatternFiles.LifeRule(BoundedGrid.SplitRule(named, out BoundedGrid? bounded));
                if (bounded != null) // spec/patterns.md "RLE in the unbounded universe"
                    throw new FormatException(
                        $"the unbounded universe has no bounded grid ('{bounded.Suffix}' in the rule): open the file in a grid world (spec/topology.md)");
            }
            string body = string.Concat(lines);
            // Dialect detection (spec/patterns.md): extended iff the body holds '.', any state
            // letter other than B and O, a two-letter tag's prefix, or the header names something
            // other than a Life-like rule.
            bool extended = named != null && !RuleString.TryCompile(named, out _);
            foreach (char c in body)
            {
                if (Patterns.MarksExtended(c))
                    extended = true;
            }
            StateRule rule = named == null ? fallback : FileRule(named, fallback);

            const long limit = HashLife.EditLimit;
            bool placed = BigInteger.Abs(posX) <= limit && BigInteger.Abs(posY) <= limit;
            long x0 = placed ? (long)posX : 0, y0 = placed ? (long)posY : 0;
            var blocks = new Dictionary<long, int>();
            long width = 0, height = 0, x = 0, y = 0;
            int top = 0;
            char prefix = '\0'; // a two-letter tag's first letter, waiting for its second
            long pending = 1;   // and the count before it
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
                    bool dangling = i == body.Length || TextLines.IsSpace(body[i]);
                    if (prefix != '\0') // no count inside a two-letter tag
                        throw new FormatException(dangling && i - start == 1
                            ? $"unsupported RLE tag: '{prefix}{body[i - 1]}'"
                            : $"unsupported RLE tag: '{prefix}'");
                    if (dangling)
                        throw new FormatException($"unsupported RLE tag: '{body[i - 1]}'");
                    count = 0;
                    for (int d = start; d < i; d++)
                        count = Math.Min(count * 10 + (body[d] - '0'), RunCap);
                }
                char tag = body[i++];
                int state;
                if (prefix != '\0')
                {
                    if (!Patterns.TryTwoLetterState(prefix, tag, out state))
                        throw new FormatException($"unsupported RLE tag: '{prefix}{tag}'");
                    count = pending;
                    prefix = '\0';
                }
                else if (tag == 'b' || tag == '.' || (!extended && tag == 'B'))
                    state = 0;
                else if (tag == 'o' || (!extended && tag == 'O'))
                    state = 1;
                else if (extended && tag >= 'A' && tag <= 'X')
                    state = tag - 'A' + 1;
                else if (extended && tag >= 'p' && tag <= 'y') // the first letter of a state 25..255
                {
                    prefix = tag;
                    pending = count;
                    continue;
                }
                else if (tag == '$')
                {
                    y = Math.Min(y + count, RunCap);
                    x = 0;
                    continue;
                }
                else if (tag == '!')
                    break;
                else
                    throw new FormatException($"unsupported RLE tag: '{tag}'");
                if (state != 0)
                {
                    width = Math.Max(width, Math.Min(x + count, RunCap));
                    height = Math.Max(height, y + 1);
                    top = Math.Max(top, state);
                    if (count > 0)
                    {
                        // A cell outside the box dooms the file: refuse it now rather than
                        // spelling out a run that may be astronomically long.
                        if (!placed)
                            throw new ArgumentOutOfRangeException(
                                null, $"#CXRLE Pos={posX},{posY} lies outside the editing box |x|, |y| <= 1,000,000,000");
                        if (x0 + x + count - 1 > limit || y0 + y > limit)
                            HashLife.CheckBox(x0, y0, x0 + x + count - 1, y0 + y);
                        AddRun(blocks, x0 + x, y0 + y - 1, count, state);
                    }
                }
                x = Math.Min(x + count, RunCap);
            }
            if (prefix != '\0')
                throw new FormatException($"unsupported RLE tag: '{prefix}'");
            if (top >= rule.States)
                throw new FormatException(
                    $"the file holds state {top}, which {rule.Canonical} doesn't have ({rule.States} states)");
            if (blocks.Count > 0)
                HashLife.CheckBox(x0, y0, x0 + width - 1, y0 + height - 1);
            var (root, level) = universe.Build(() =>
            {
                if (blocks.Count > 0)
                    universe.PasteBlocks(blocks, x0, y0 - 1, x0 + width - 1, y0 + height - 2, HashLifePasteMode.Or);
            });
            return (root, level, generation, rule);
        }

        /// <summary>Set <paramref name="length"/> cells from tree position (tx, ty) rightward to
        /// <paramref name="state"/>, in the 2 × 2 leaves keyed by <see cref="HashLife.BlockKey"/>.</summary>
        private static void AddRun(Dictionary<long, int> blocks, long tx, long ty, long length, int state)
        {
            long by = ty >> 1;
            int row = (int)(ty & 1) * 16;
            for (long cx = tx; cx < tx + length; cx++)
            {
                long key = HashLife.BlockKey(cx >> 1, by);
                blocks.TryGetValue(key, out int states);
                blocks[key] = states | state << (row + (int)(cx & 1) * 8);
            }
        }

        /// <summary>
        /// The universe as RLE: <c>#CXRLE Pos=x0,y0</c> (with <c> Gen=n</c> past generation 0), then
        /// the canonical encoding of the bounding box's states, every state from 1 to 255 a tag.
        /// A pattern reaching outside the editing box throws <see cref="InvalidOperationException"/>;
        /// Macrocell carries it.
        /// </summary>
        internal static string WriteRle(MultiStateHashLife universe, PatternMetadata? metadata)
        {
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

            // Every row's runs of one state, built leaf by leaf in x order (leaves never overlap).
            var leaves = new List<(long X, long Y, int States)>();
            universe.CollectLeaves(leaves);
            leaves.Sort((a, b) => a.Y != b.Y ? a.Y.CompareTo(b.Y) : a.X.CompareTo(b.X));
            var rows = new Dictionary<long, List<long>>(); // y → start, length, state, start, length, state, ...
            int top = 0;
            foreach (var (tx, ty, states) in leaves)
            {
                for (int r = 0; r < 2; r++)
                {
                    for (int c = 0; c < 2; c++)
                    {
                        int state = (states >> (8 * (2 * r + c))) & 0xFF;
                        if (state == 0)
                            continue;
                        top = Math.Max(top, state);
                        long cy = ty + r + 1;
                        if (!rows.TryGetValue(cy, out List<long>? runs))
                        {
                            runs = new List<long>();
                            rows[cy] = runs;
                        }
                        long cx = tx + c;
                        int n = runs.Count;
                        if (n > 0 && runs[n - 3] + runs[n - 2] == cx && runs[n - 1] == state)
                        {
                            runs[n - 2]++;
                        }
                        else
                        {
                            runs.Add(cx);
                            runs.Add(1);
                            runs.Add(state);
                        }
                    }
                }
            }
            bool multistate = top > 1;

            var text = new StringBuilder();
            text.Append("#CXRLE Pos=").Append(x0.ToString(CultureInfo.InvariantCulture)).Append(',')
                .Append(y0.ToString(CultureInfo.InvariantCulture)).Append(gen).Append('\n');
            text.Append(noteText);
            text.Append("x = ").Append((x1 - x0 + 1).ToString(CultureInfo.InvariantCulture))
                .Append(", y = ").Append((y1 - y0 + 1).ToString(CultureInfo.InvariantCulture))
                .Append(", rule = ").Append(universe.Rule).Append('\n');
            // Live rows only: the gap between two is one k$ token (spec/patterns.md).
            var liveRows = new List<long>(rows.Keys);
            liveRows.Sort();
            int lineLength = 0;
            long previous = y0;
            foreach (long cy in liveRows)
            {
                if (cy > y0)
                    AppendToken(text, ref lineLength, cy - previous, "$");
                List<long> runs = rows[cy];
                long pos = x0;
                for (int r = 0; r < runs.Count; r += 3)
                {
                    long start = runs[r], length = runs[r + 1];
                    int state = (int)runs[r + 2];
                    if (start > pos)
                        AppendToken(text, ref lineLength, start - pos, multistate ? "." : "b");
                    AppendToken(text, ref lineLength, length, multistate ? Patterns.StateTag(state) : "o");
                    pos = start + length;
                }
                previous = cy;
            }
            AppendToken(text, ref lineLength, 1, "!");
            text.Append('\n');
            return text.ToString();
        }

        /// <summary>One run token, wrapped as canonical RLE wraps: a token that would pass column
        /// 70 starts a new line.</summary>
        private static void AppendToken(StringBuilder text, ref int lineLength, long length, string tag)
        {
            string count = length == 1 ? "" : length.ToString(CultureInfo.InvariantCulture);
            int size = count.Length + tag.Length;
            if (lineLength + size > 70)
            {
                text.Append('\n');
                lineLength = 0;
            }
            text.Append(count).Append(tag);
            lineLength += size;
        }
    }
}
