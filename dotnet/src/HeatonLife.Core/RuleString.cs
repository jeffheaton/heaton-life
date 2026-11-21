using System;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Text;

namespace HeatonLife
{
    /// <summary>The neighbors a Life-like rule counts (spec/rules.md "Neighborhoods").</summary>
    public enum RuleNeighborhood
    {
        /// <summary>All eight neighbors; no suffix.</summary>
        Moore,

        /// <summary>NW, N, W, E, S, SE: Moore without NE and SW, a hexagonal grid sheared onto
        /// the square one. Suffix <c>H</c>.</summary>
        Hexagonal,

        /// <summary>N, W, E, S. Suffix <c>V</c>.</summary>
        VonNeumann,
    }

    /// <summary>
    /// A Life-like rule compiled to its transition table (spec/rules.md). <c>Table[i]</c> is the
    /// next state, 0 or 1, of a cell whose 3×3 block has neighborhood index i: NW 256, N 128,
    /// NE 64, W 32, the cell 16, E 8, SW 4, S 2, SE 1. Two rules behave identically exactly when
    /// their tables are equal, whatever their notations. Made by <see cref="RuleString.Compile"/>;
    /// the Python reference's <c>LifeRule</c>.
    /// </summary>
    public sealed class LifeRule
    {
        /// <summary>Entries in every rule's table: one per filling of the 3×3 block.</summary>
        public const int TableSize = 512;

        private readonly byte[] _table;

        internal LifeRule(string canonical, RuleNeighborhood neighborhood, byte[] table)
        {
            Canonical = canonical;
            Neighborhood = neighborhood;
            _table = table;
        }

        /// <summary>The rule's canonical string (spec/rules.md "Canonical form").</summary>
        public string Canonical { get; }

        /// <summary>The neighbors the rule's notation counts.</summary>
        public RuleNeighborhood Neighborhood { get; }

        /// <summary>The 512 next states, indexed by the neighborhood index.</summary>
        public ReadOnlySpan<byte> Table => _table;

        /// <summary>True when a dead cell with no live neighbors is born (<c>Table[0] == 1</c>).</summary>
        public bool HasB0 => _table[0] != 0;

        /// <inheritdoc />
        public override string ToString() => Canonical;
    }

    /// <summary>
    /// Life-like rules (spec/rules.md): rule text compiled to one 512-entry transition table.
    /// Every notation the spec defines compiles here: <c>B…/S…</c> with digits (outer-totalistic)
    /// or letter classes (isotropic non-totalistic), with an <c>H</c> (hexagonal) or <c>V</c>
    /// (von Neumann) suffix, and <c>MAP</c> strings. The parser is written by hand to the spec's
    /// grammar, without Regex, step for step like the Python reference's
    /// <c>heaton_life/ca/rulestring.py</c>.
    /// </summary>
    public static class RuleString
    {
        private const int Center = 16;      // the cell's own bit in the neighborhood index
        private const int Neighbors = 0x1EF; // every bit but the cell's own
        private const char Whole = '*';     // "every arrangement of the count": 0, 8, H and V
        private const string Letters = "cekainyqjrtwz";
        private const string Base64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

        // One arrangement of each letter class of counts 1-4, as its live neighbors
        // (spec/rules.md "Letter classes"). Counts 5-7 are the complements of 3-1.
        private static readonly (int Count, char Letter, string Cells)[] Representatives =
        {
            (1, 'c', "NW"), (1, 'e', "N"),
            (2, 'c', "NW NE"), (2, 'e', "N W"), (2, 'k', "N SE"), (2, 'a', "NW N"), (2, 'i', "N S"),
            (2, 'n', "NW SE"),
            (3, 'c', "NW NE SE"), (3, 'e', "N W E"), (3, 'k', "N W SE"), (3, 'a', "NW N W"),
            (3, 'i', "NW W SW"), (3, 'n', "NW NE W"), (3, 'y', "NW NE S"), (3, 'q', "NW W SE"),
            (3, 'j', "NE E S"), (3, 'r', "N NE S"),
            (4, 'c', "NW NE SW SE"), (4, 'e', "N W E S"), (4, 'k', "N NE W SE"), (4, 'a', "NW W SW S"),
            (4, 'i', "NW NE W E"), (4, 'n', "NW W SW SE"), (4, 'y', "NW NE SW S"), (4, 'q', "NW N W SE"),
            (4, 'j', "N W E SE"), (4, 'r', "N NE E S"), (4, 't', "NW N NE S"), (4, 'w', "NW W S SE"),
            (4, 'z', "NW N S SE"),
        };

        // The letters each count takes, alphabetical (the canonical spelling's order).
        private static readonly string[] LettersOf = BuildLettersOf();

        // Every letter class as the arrangements it holds (index bits of live neighbors).
        private static readonly Dictionary<(int Count, char Letter), int[]> Classes = BuildClasses();

        /// <summary>Compile rule text (spec/rules.md "Grammar") to its table and canonical
        /// string. Throws <see cref="ArgumentException"/> for text outside the grammar.</summary>
        public static LifeRule Compile(string rule)
        {
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            LifeRule? compiled = Build(rule, out string error);
            if (compiled == null)
                throw new ArgumentException(error, nameof(rule));
            return compiled;
        }

        /// <summary>Like <see cref="Compile"/>, but answers false instead of throwing.</summary>
        public static bool TryCompile(string? rule, [NotNullWhen(true)] out LifeRule? compiled)
        {
            compiled = rule == null ? null : Build(rule, out _);
            return compiled != null;
        }

        /// <summary>The canonical form of a rule, e.g. "b3 / s32" → "B3/S23" (spec/rules.md).</summary>
        public static string Canonical(string rule) => Compile(rule).Canonical;

        /// <summary>
        /// An outer-totalistic Moore rule as birth and survival flags by neighbor count. Only a
        /// rule whose table depends on nothing but the cell and its count of live neighbors has
        /// counts: isotropic letters that split a count, MAP strings that aren't outer-totalistic,
        /// and hexagonal or von Neumann rules throw <see cref="ArgumentException"/>.
        /// <see cref="Compile"/> gives every rule's table.
        /// </summary>
        public static (bool[] Birth, bool[] Survive) Parse(string rule)
        {
            LifeRule compiled = Compile(rule);
            var birth = new bool[9];
            var survive = new bool[9];
            var seen = new bool[2, 9];
            bool totalistic = compiled.Neighborhood == RuleNeighborhood.Moore;
            ReadOnlySpan<byte> table = compiled.Table;
            for (int index = 0; index < LifeRule.TableSize && totalistic; index++)
            {
                int side = (index & Center) != 0 ? 1 : 0;
                int count = PopCount(index & Neighbors);
                bool value = table[index] != 0;
                bool[] flags = side == 1 ? survive : birth;
                if (!seen[side, count])
                {
                    seen[side, count] = true;
                    flags[count] = value;
                }
                else if (flags[count] != value)
                {
                    totalistic = false;
                }
            }
            if (!totalistic)
                throw new ArgumentException(
                    $"{compiled.Canonical} is not an outer-totalistic Moore rule, so it has no birth "
                    + "and survival counts; RuleString.Compile gives its table (spec/rules.md)",
                    nameof(rule));
            return (birth, survive);
        }

        // -- the parser ---------------------------------------------------------------------------

        private static string Invalid(string text, string reason) => $"invalid rule '{text}': {reason} (spec/rules.md)";

        private static LifeRule? Build(string text, out string error)
        {
            int start = 0, end = text.Length;
            while (start < end && IsSpace(text[start]))
                start++;
            while (end > start && IsSpace(text[end - 1]))
                end--;
            if (end - start >= 3 && (text[start] == 'M' || text[start] == 'm')
                && (text[start + 1] == 'A' || text[start + 1] == 'a')
                && (text[start + 2] == 'P' || text[start + 2] == 'p'))
                return BuildMap(text, start + 3, end, out error);
            if (start < end && (text[start] == 'B' || text[start] == 'b'))
                return BuildBs(text, start + 1, end, out error);
            error = Invalid(text, "expected B…/S… or MAP…");
            return null;
        }

        private static LifeRule? BuildBs(string text, int pos, int end, out string error)
        {
            var birth = new List<(int Count, bool Minus, string Letters)>();
            if (!Groups(text, ref pos, end, birth, out error))
                return null;
            pos = SkipSpace(text, pos, end);
            if (pos >= end || text[pos] != '/')
            {
                error = Invalid(text, "expected '/' after the birth counts");
                return null;
            }
            pos = SkipSpace(text, pos + 1, end);
            if (pos >= end || (text[pos] != 'S' && text[pos] != 's'))
            {
                error = Invalid(text, "expected S after '/'");
                return null;
            }
            pos++;
            var survive = new List<(int Count, bool Minus, string Letters)>();
            if (!Groups(text, ref pos, end, survive, out error))
                return null;

            // What follows the survival counts names the neighborhood. A variant with more states
            // will add a suffix word here; until one is specified (spec/rules.md "Grammar"),
            // nothing else may follow.
            RuleNeighborhood neighborhood;
            if (pos == end)
            {
                neighborhood = RuleNeighborhood.Moore;
            }
            else if (end - pos == 1 && (text[pos] == 'H' || text[pos] == 'h'))
            {
                neighborhood = RuleNeighborhood.Hexagonal;
            }
            else if (end - pos == 1 && (text[pos] == 'V' || text[pos] == 'v'))
            {
                neighborhood = RuleNeighborhood.VonNeumann;
            }
            else
            {
                error = Invalid(text, $"unexpected '{text.Substring(pos, end - pos)}' after the survival counts");
                return null;
            }

            HashSet<(int Count, char Letter)>? born = Side(text, birth, neighborhood, out error);
            if (born == null)
                return null;
            HashSet<(int Count, char Letter)>? stays = Side(text, survive, neighborhood, out error);
            if (stays == null)
                return null;
            string suffix = neighborhood == RuleNeighborhood.Hexagonal ? "H"
                : neighborhood == RuleNeighborhood.VonNeumann ? "V" : "";
            string canonical = "B" + Spell(born, neighborhood) + "/S" + Spell(stays, neighborhood) + suffix;
            return new LifeRule(canonical, neighborhood, BsTable(born, stays, neighborhood));
        }

        private static int SkipSpace(string text, int pos, int end)
        {
            while (pos < end && IsSpace(text[pos]))
                pos++;
            return pos;
        }

        /// <summary>spec/rules.md "Grammar": the whitespace allowed at the ends and around the
        /// slash, listed by code point so every runtime agrees.</summary>
        private static bool IsSpace(char c)
        {
            int u = c;
            return (u >= 0x09 && u <= 0x0D) || u == 0x20 || u == 0x85 || u == 0xA0 || u == 0x1680
                || (u >= 0x2000 && u <= 0x200A) || u == 0x2028 || u == 0x2029 || u == 0x202F
                || u == 0x205F || u == 0x3000;
        }

        /// <summary>The letter class <paramref name="c"/> names, in either case. ASCII only.</summary>
        private static bool IsLetter(char c, out char letter)
        {
            letter = c >= 'A' && c <= 'Z' ? (char)(c + ('a' - 'A')) : c;
            return Letters.IndexOf(letter) >= 0;
        }

        /// <summary>One side's digit groups as written.</summary>
        private static bool Groups(
            string text, ref int pos, int end, List<(int Count, bool Minus, string Letters)> groups, out string error)
        {
            error = "";
            while (pos < end && text[pos] >= '0' && text[pos] <= '8')
            {
                int count = text[pos] - '0';
                pos++;
                bool minus = pos < end && text[pos] == '-';
                if (minus)
                    pos++;
                var letters = new StringBuilder();
                while (pos < end && IsLetter(text[pos], out char letter))
                {
                    letters.Append(letter);
                    pos++;
                }
                if (minus && letters.Length == 0)
                {
                    error = Invalid(text, $"'-' after {count} must be followed by letters");
                    return false;
                }
                groups.Add((count, minus, letters.ToString()));
            }
            return true;
        }

        /// <summary>The letter classes one side names (spec/rules.md "Birth and survival").</summary>
        private static HashSet<(int Count, char Letter)>? Side(
            string text, List<(int Count, bool Minus, string Letters)> groups, RuleNeighborhood neighborhood,
            out string error)
        {
            error = "";
            int limit = neighborhood == RuleNeighborhood.Moore ? 8
                : neighborhood == RuleNeighborhood.Hexagonal ? 6 : 4;
            var keys = new HashSet<(int Count, char Letter)>();
            foreach (var (count, minus, letters) in groups)
            {
                if (count > limit)
                {
                    error = Invalid(text, $"the {Name(neighborhood)} neighborhood has {limit} neighbors");
                    return null;
                }
                if (neighborhood != RuleNeighborhood.Moore)
                {
                    if (letters.Length > 0)
                    {
                        error = Invalid(text, $"letters are only defined for Moore rules, not {Name(neighborhood)}");
                        return null;
                    }
                    keys.Add((count, Whole));
                    continue;
                }
                string defined = LettersOf[count];
                if (letters.Length == 0)
                {
                    if (defined.Length == 0)
                        keys.Add((count, Whole));
                    foreach (char letter in defined)
                        keys.Add((count, letter));
                    continue;
                }
                if (defined.Length == 0)
                {
                    error = Invalid(text, $"{count} takes no letters");
                    return null;
                }
                foreach (char letter in letters)
                {
                    if (defined.IndexOf(letter) < 0)
                    {
                        error = Invalid(text, $"{letter} is not a letter class of {count}");
                        return null;
                    }
                }
                foreach (char letter in defined)
                {
                    if ((letters.IndexOf(letter) >= 0) != minus)
                        keys.Add((count, letter));
                }
            }
            return keys;
        }

        private static string Name(RuleNeighborhood neighborhood)
            => neighborhood == RuleNeighborhood.Hexagonal ? "hexagonal" : "von Neumann";

        /// <summary>One side in canonical form (spec/rules.md "Canonical form").</summary>
        private static string Spell(HashSet<(int Count, char Letter)> keys, RuleNeighborhood neighborhood)
        {
            var sb = new StringBuilder();
            for (int count = 0; count <= 8; count++)
            {
                bool present = false;
                var letters = new List<char>();
                foreach (var (n, letter) in keys)
                {
                    if (n != count)
                        continue;
                    present = true;
                    if (letter != Whole)
                        letters.Add(letter);
                }
                if (!present)
                    continue;
                letters.Sort();
                string defined = LettersOf[count];
                char digit = (char)('0' + count);
                if (neighborhood != RuleNeighborhood.Moore || letters.Count == 0 || letters.Count == defined.Length)
                {
                    sb.Append(digit);
                    continue;
                }
                var plus = new StringBuilder().Append(digit);
                foreach (char letter in letters)
                    plus.Append(letter);
                var minus = new StringBuilder().Append(digit).Append('-');
                foreach (char letter in defined) // already alphabetical
                {
                    if (!letters.Contains(letter))
                        minus.Append(letter);
                }
                sb.Append((minus.Length < plus.Length ? minus : plus).ToString());
            }
            return sb.ToString();
        }

        private static byte[] BsTable(
            HashSet<(int Count, char Letter)> born, HashSet<(int Count, char Letter)> stays,
            RuleNeighborhood neighborhood)
        {
            var table = new byte[LifeRule.TableSize];
            if (neighborhood == RuleNeighborhood.Moore)
            {
                var birth = new bool[LifeRule.TableSize];
                var survive = new bool[LifeRule.TableSize];
                foreach (var key in born)
                    foreach (int m in Classes[key])
                        birth[m] = true;
                foreach (var key in stays)
                    foreach (int m in Classes[key])
                        survive[m] = true;
                for (int index = 0; index < LifeRule.TableSize; index++)
                {
                    bool[] set = (index & Center) != 0 ? survive : birth;
                    table[index] = (byte)(set[index & Neighbors] ? 1 : 0);
                }
                return table;
            }
            int counted = neighborhood == RuleNeighborhood.Hexagonal ? 0x1AB : 0xAA;
            var birthCounts = new bool[9];
            var surviveCounts = new bool[9];
            foreach (var (count, _) in born)
                birthCounts[count] = true;
            foreach (var (count, _) in stays)
                surviveCounts[count] = true;
            for (int index = 0; index < LifeRule.TableSize; index++)
            {
                bool[] counts = (index & Center) != 0 ? surviveCounts : birthCounts;
                table[index] = (byte)(counts[PopCount(index & counted)] ? 1 : 0);
            }
            return table;
        }

        // -- MAP strings --------------------------------------------------------------------------

        private static LifeRule? BuildMap(string text, int start, int end, out string error)
        {
            error = "";
            int length = end - start;
            if (length >= 2 && text[end - 1] == '=' && text[end - 2] == '=')
                length -= 2;
            RuleNeighborhood neighborhood;
            int cells;
            switch (length)
            {
                case 86:
                    neighborhood = RuleNeighborhood.Moore;
                    cells = 9;
                    break;
                case 22:
                    neighborhood = RuleNeighborhood.Hexagonal;
                    cells = 7;
                    break;
                case 6:
                    neighborhood = RuleNeighborhood.VonNeumann;
                    cells = 5;
                    break;
                default:
                    error = Invalid(text, "a MAP payload is 86, 22 or 6 base64 characters, optionally followed by ==");
                    return null;
            }
            var values = new int[length];
            for (int i = 0; i < length; i++)
            {
                values[i] = Base64.IndexOf(text[start + i]);
                if (values[i] < 0)
                {
                    error = Invalid(text, "a MAP payload is 86, 22 or 6 base64 characters, optionally followed by ==");
                    return null;
                }
            }
            var entries = new byte[1 << cells];
            for (int i = 0; i < entries.Length; i++)
                entries[i] = (byte)((values[i / 6] >> (5 - i % 6)) & 1);
            var table = new byte[LifeRule.TableSize];
            for (int index = 0; index < LifeRule.TableSize; index++)
                table[index] = entries[Project(index, neighborhood)];
            var canonical = new StringBuilder("MAP");
            for (int at = 0; at < length * 6; at += 6)
            {
                int value = 0;
                for (int i = at; i < at + 6; i++)
                    value = (value << 1) | (i < entries.Length ? entries[i] : 0);
                canonical.Append(Base64[value]);
            }
            return new LifeRule(canonical.ToString(), neighborhood, table);
        }

        /// <summary>A Moore neighborhood index as the index of a MAP string's own neighborhood:
        /// the cells it has, in Moore order (spec/rules.md "MAP strings").</summary>
        private static int Project(int index, RuleNeighborhood neighborhood)
        {
            switch (neighborhood)
            {
                case RuleNeighborhood.Hexagonal: // NW N W C E S SE
                    return ((index >> 2) & 0x60) | ((index >> 1) & 0x1C) | (index & 0x3);
                case RuleNeighborhood.VonNeumann: // N W C E S
                    return ((index >> 3) & 0x10) | ((index >> 2) & 0xE) | ((index >> 1) & 0x1);
                default:
                    return index;
            }
        }

        // -- the letter classes -------------------------------------------------------------------

        private static string[] BuildLettersOf()
        {
            var lettersOf = new string[9];
            for (int n = 0; n <= 8; n++)
            {
                var letters = new List<char>();
                int from = Math.Min(n, 8 - n);
                foreach (var (count, letter, _) in Representatives)
                {
                    if (count == from && n > 0 && n < 8)
                        letters.Add(letter);
                }
                letters.Sort();
                lettersOf[n] = new string(letters.ToArray());
            }
            return lettersOf;
        }

        private static Dictionary<(int Count, char Letter), int[]> BuildClasses()
        {
            var classes = new Dictionary<(int Count, char Letter), int[]>
            {
                [(0, Whole)] = new[] { 0 },
                [(8, Whole)] = new[] { Neighbors },
            };
            foreach (var (count, letter, cells) in Representatives)
            {
                int mask = 0;
                foreach (string cell in cells.Split(' '))
                    mask |= Weight(cell);
                int[] members = Symmetric(mask);
                classes[(count, letter)] = members;
                if (count < 4)
                {
                    var flipped = new int[members.Length];
                    for (int i = 0; i < members.Length; i++)
                        flipped[i] = members[i] ^ Neighbors;
                    classes[(8 - count, letter)] = flipped;
                }
            }
            return classes;
        }

        private static int Weight(string cell)
        {
            switch (cell)
            {
                case "NW": return 256;
                case "N": return 128;
                case "NE": return 64;
                case "W": return 32;
                case "E": return 8;
                case "SW": return 4;
                case "S": return 2;
                case "SE": return 1;
                default: throw new ArgumentException($"no cell named {cell}", nameof(cell));
            }
        }

        /// <summary>An arrangement under the eight symmetries of the square (quarter turns,
        /// mirrored or not); cells are compass offsets (dx, dy) with y down.</summary>
        private static int[] Symmetric(int mask)
        {
            var cells = new List<(int Dx, int Dy)>();
            for (int dx = -1; dx <= 1; dx++)
                for (int dy = -1; dy <= 1; dy++)
                    if ((dx != 0 || dy != 0) && (mask & Bit(dx, dy)) != 0)
                        cells.Add((dx, dy));
            var images = new List<int>();
            for (int turn = 0; turn < 4; turn++)
            {
                int image = 0, mirror = 0;
                for (int i = 0; i < cells.Count; i++)
                {
                    cells[i] = (-cells[i].Dy, cells[i].Dx); // a quarter turn clockwise
                    image |= Bit(cells[i].Dx, cells[i].Dy);
                    mirror |= Bit(-cells[i].Dx, cells[i].Dy); // and its mirror image
                }
                if (!images.Contains(image))
                    images.Add(image);
                if (!images.Contains(mirror))
                    images.Add(mirror);
            }
            return images.ToArray();
        }

        /// <summary>The neighborhood-index weight of the cell at offset (dx, dy): NW 256 … SE 1.</summary>
        private static int Bit(int dx, int dy) => 1 << (4 - 3 * dy - dx);

        private static int PopCount(int v)
        {
            int count = 0;
            for (; v != 0; v &= v - 1)
                count++;
            return count;
        }
    }
}
