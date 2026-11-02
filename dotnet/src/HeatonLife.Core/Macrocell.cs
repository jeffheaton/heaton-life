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
    /// Macrocell (<c>.mc</c>, <c>.mc.gz</c>) — Golly's native HashLife format (spec/macrocell.md).
    /// A file lists a pattern's distinct quadtree nodes, children before parents, so a regular
    /// pattern of trillions of cells fits in a few lines. Reading follows Golly's two-state
    /// reader (and its multistate syntax when every state is 0 or 1); writing is canonical, so
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
            if (data.Length >= 2 && data[0] == 0x1f && data[1] == 0x8b)
            {
                using var source = new MemoryStream(data);
                using var gzip = new GZipStream(source, CompressionMode.Decompress);
                using var inflated = new MemoryStream();
                gzip.CopyTo(inflated);
                data = inflated.ToArray();
            }
            return Read(HashLife.Latin1(data, 0, data.Length), maxMemoryMb);
        }

        /// <summary>
        /// A universe from Macrocell text, placed as Golly places it: a level-k root covers x in
        /// [−2^(k−1), 2^(k−1) − 1] and y in [−2^(k−1) + 1, 2^(k−1)]. <c>#R</c> sets the rule,
        /// <c>#G</c> the generation; other <c>#</c> lines (comments, timeline frames) are skipped.
        /// Malformed text throws <see cref="FormatException"/>.
        /// </summary>
        public static HashLife Read(string text, int maxMemoryMb = HashLife.DefaultMaxMemoryMb)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            List<string> lines = TextLines.Split(text);
            if (lines.Count == 0 || !TextLines.StripStart(lines[0]).StartsWith("[M2]", StringComparison.Ordinal))
                throw new FormatException("not a Macrocell file: the first line must start with [M2]");
            var universe = new HashLife(maxMemoryMb: maxMemoryMb);
            HashLifeStore store = universe.Store;
            BigInteger generation = BigInteger.Zero;
            // Each node as (value, level): a store id for level ≥ 3, a spread bitmap below.
            var values = new List<long>();
            var levels = new List<int>();

            for (int index = 1; index < lines.Count; index++)
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
                            universe.Rule = TextLines.Strip(line.Substring(2));
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
                    continue;
                }
                if (line[0] == '.' || line[0] == '*' || line[0] == '$')
                {
                    values.Add(store.Leaf(LeafBits(line, number)));
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
                    long nw = Child(values, levels, fields[1], 1, number, store), ne = Child(values, levels, fields[2], 1, number, store);
                    long sw = Child(values, levels, fields[3], 1, number, store), se = Child(values, levels, fields[4], 1, number, store);
                    values.Add(nw | ne << 2 | sw << 16 | se << 18);
                    levels.Add(2);
                }
                else if (level == 3)
                {
                    long nw = Child(values, levels, fields[1], 2, number, store), ne = Child(values, levels, fields[2], 2, number, store);
                    long sw = Child(values, levels, fields[3], 2, number, store), se = Child(values, levels, fields[4], 2, number, store);
                    values.Add(store.Leaf(HashLifeLeaves.Compose((ulong)nw, (ulong)ne, (ulong)sw, (ulong)se)));
                    levels.Add(3);
                }
                else if (level >= 4)
                {
                    if (level > HashLifeStore.MaxLevel)
                        throw new FormatException($"line {number}: level {level} is past the deepest tree, level {HashLifeStore.MaxLevel}");
                    int k = (int)level;
                    int nw = (int)Child(values, levels, fields[1], k - 1, number, store);
                    int ne = (int)Child(values, levels, fields[2], k - 1, number, store);
                    int sw = (int)Child(values, levels, fields[3], k - 1, number, store);
                    int se = (int)Child(values, levels, fields[4], k - 1, number, store);
                    values.Add(store.Join(nw, ne, sw, se));
                    levels.Add(k);
                }
                else
                {
                    throw new FormatException($"line {number}: level must be at least 1");
                }
            }
            if (values.Count == 0)
                throw new FormatException("Macrocell file has no nodes");

            long rootValue = values[values.Count - 1];
            int rootLevel = levels[levels.Count - 1];
            if (rootLevel < 3)
            {
                // A 2×2 or 4×4 root, centered in a leaf.
                rootValue = store.Leaf((ulong)rootValue << (rootLevel == 1 ? 27 : 18));
                rootLevel = 3;
            }
            int root = (int)rootValue;
            if (rootLevel == 3)
            {
                // A leaf root becomes the center of a level-4 root.
                ulong b = store.Bits(root);
                ulong sq = HashLifeLeaves.Square4;
                int nw = store.Leaf(HashLifeLeaves.Compose(0, 0, 0, b & sq));
                int ne = store.Leaf(HashLifeLeaves.Compose(0, 0, (b >> 4) & sq, 0));
                int sw = store.Leaf(HashLifeLeaves.Compose(0, (b >> 32) & sq, 0, 0));
                int se = store.Leaf(HashLifeLeaves.Compose((b >> 36) & sq, 0, 0, 0));
                root = store.Join(nw, ne, sw, se);
                rootLevel = 4;
            }
            universe.Adopt(root, rootLevel, generation);
            return universe;
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

        private static long Child(List<long> values, List<int> levels, long index, int level, int number, HashLifeStore store)
        {
            if (index == 0)
                return level >= 3 ? store.Empty(level) : 0;
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
        /// nodes in Golly's order — depth-first, children NW, NE, SW, SE before their parent,
        /// each once — with LF line ends.
        /// </summary>
        public static string Write(HashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            HashLifeStore store = universe.Store;
            var text = new StringBuilder();
            text.Append(Header).Append('\n');
            text.Append("#R ").Append(universe.Rule).Append('\n');
            BigInteger generation = universe.Generation;
            if (generation.Sign > 0)
                text.Append("#G ").Append(generation.ToString(CultureInfo.InvariantCulture)).Append('\n');
            var (root, level) = universe.Minimal();
            if (level == 3)
            {
                AppendLeaf(text, store.Bits(root));
                return text.ToString();
            }
            var index = new Dictionary<int, int>();
            var stack = new Stack<(int Node, int Level, bool Ready)>();
            stack.Push((root, level, false));
            while (stack.Count > 0)
            {
                var (n, k, ready) = stack.Pop();
                if (index.ContainsKey(n))
                    continue;
                if (k == 3)
                {
                    AppendLeaf(text, store.Bits(n));
                    index[n] = index.Count + 1;
                    continue;
                }
                int e = store.Empty(k - 1);
                if (ready)
                {
                    text.Append(k.ToString(CultureInfo.InvariantCulture));
                    for (int q = 0; q < 4; q++)
                    {
                        int kid = store.Kid(n, q);
                        text.Append(' ').Append((kid == e ? 0 : index[kid]).ToString(CultureInfo.InvariantCulture));
                    }
                    text.Append('\n');
                    index[n] = index.Count + 1;
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
            return text.ToString();
        }

        /// <summary>A leaf line as Golly writes it: rows through the last live one, each without
        /// its trailing '.' and ended by '$'; the empty leaf is "$".</summary>
        private static void AppendLeaf(StringBuilder text, ulong bits)
        {
            int last = -1;
            for (int r = 0; r < 8; r++)
            {
                if (((bits >> (8 * r)) & 0xFF) != 0)
                    last = r;
            }
            if (last < 0)
            {
                text.Append("$\n");
                return;
            }
            for (int r = 0; r <= last; r++)
            {
                int row = (int)((bits >> (8 * r)) & 0xFF);
                for (int x = 0; row >> x != 0; x++)
                    text.Append(((row >> x) & 1) != 0 ? '*' : '.');
                text.Append('$');
            }
            text.Append('\n');
        }
    }

    /// <summary>Line splitting and whitespace exactly as the Python reference's str methods
    /// (<c>splitlines</c>, <c>strip</c>, <c>split</c>), so the readers agree on every file.</summary>
    internal static class TextLines
    {
        internal static bool IsSpace(char c) => char.IsWhiteSpace(c) || (c >= '\x1c' && c <= '\x1f');

        private static bool IsBreak(char c)
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

        internal static string StripStart(string text)
        {
            int start = 0;
            while (start < text.Length && IsSpace(text[start]))
                start++;
            return start == 0 ? text : text.Substring(start);
        }
    }
}
