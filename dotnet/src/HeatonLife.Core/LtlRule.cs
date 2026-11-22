using System;
using System.Globalization;

namespace HeatonLife
{
    /// <summary>The neighborhood of a Larger than Life rule (spec/ltl.md "Neighborhoods").</summary>
    public enum LtlNeighborhood
    {
        /// <summary>The Moore box: |dx| ≤ r and |dy| ≤ r. Written <c>NM</c>.</summary>
        Moore,

        /// <summary>The von Neumann diamond: |dx| + |dy| ≤ r. Written <c>NN</c>.</summary>
        VonNeumann,

        /// <summary>The circle: dx² + dy² ≤ r² + r. Written <c>NC</c>.</summary>
        Circular,
    }

    /// <summary>
    /// A Larger than Life rule (spec/ltl.md "The rule"): the range r (1 to 500), the number of
    /// states (2 to 256), whether the middle cell counts itself, the inclusive survival and
    /// birth ranges of counts, and the neighborhood. <see cref="Parse"/> reads either form of
    /// the rule text, and <see cref="Canonical"/> writes the canonical one. The Python
    /// reference's heaton_life.ca.ltl.LtlRule.
    /// </summary>
    public sealed class LtlRule : IEquatable<LtlRule>
    {
        /// <summary>The largest range.</summary>
        public const int MaxRange = 500;

        /// <summary>The most states a rule may have.</summary>
        public const int MaxStates = 256;

        /// <summary>The most cells a neighborhood holds (the box at range 500), and so the largest
        /// count a rule may name.</summary>
        public const int MaxCount = (2 * MaxRange + 1) * (2 * MaxRange + 1);

        /// <summary>Bosco's Rule, the classic Larger than Life rule.</summary>
        public const string Bosco = "R5,C0,M1,S34..58,B34..45,NM";

        private const int Past = 1_000_000_001; // a number past every limit, for any longer one
        private readonly int[] _halfWidths;

        private LtlRule(
            int range, int states, bool middle, int survivalMin, int survivalMax, int birthMin, int birthMax,
            LtlNeighborhood neighborhood)
        {
            Range = range;
            States = states;
            Middle = middle;
            SurvivalMin = survivalMin;
            SurvivalMax = survivalMax;
            BirthMin = birthMin;
            BirthMax = birthMax;
            Neighborhood = neighborhood;
            _halfWidths = HalfWidths(range, neighborhood);
            int size = 0;
            foreach (int w in _halfWidths)
                size += 2 * w + 1;
            Size = size;
        }

        public int Range { get; }

        /// <summary>2 to 256: state 0 dead, 1 alive, 2 and up dying.</summary>
        public int States { get; }

        /// <summary>Whether a cell counts itself (<c>M1</c>).</summary>
        public bool Middle { get; }

        public int SurvivalMin { get; }

        public int SurvivalMax { get; }

        public int BirthMin { get; }

        public int BirthMax { get; }

        public LtlNeighborhood Neighborhood { get; }

        /// <summary>The cells of the neighborhood, the cell itself included.</summary>
        public int Size { get; }

        /// <summary>w(dy) for dy from −r to r: row dy of the neighborhood holds |dx| ≤ w(dy).</summary>
        public ReadOnlySpan<int> HalfWidthSpan => _halfWidths;

        /// <summary><c>R&lt;r&gt;,C&lt;c&gt;,M&lt;m&gt;,S&lt;min&gt;..&lt;max&gt;,B&lt;min&gt;..&lt;max&gt;,N&lt;M|N|C&gt;</c>,
        /// <c>c</c> 0 for two states.</summary>
        public string Canonical
        {
            get
            {
                string hood = Neighborhood == LtlNeighborhood.Moore ? "M" : Neighborhood == LtlNeighborhood.VonNeumann ? "N" : "C";
                return "R" + Text(Range) + ",C" + Text(States == 2 ? 0 : States) + ",M" + (Middle ? "1" : "0")
                    + ",S" + Text(SurvivalMin) + ".." + Text(SurvivalMax) + ",B" + Text(BirthMin) + ".." + Text(BirthMax)
                    + ",N" + hood;
            }
        }

        public override string ToString() => Canonical;

        /// <summary>w(dy) for dy from −<paramref name="range"/> to <paramref name="range"/>
        /// (spec/ltl.md "Neighborhoods"); the circle's by an exact integer square root.</summary>
        public static int[] HalfWidths(int range, LtlNeighborhood neighborhood)
        {
            if (range < 1 || range > MaxRange)
                throw new ArgumentOutOfRangeException(nameof(range), range, $"the range is 1 to {MaxRange}");
            var widths = new int[2 * range + 1];
            long reach = (long)range * range + range;
            for (int dy = -range; dy <= range; dy++)
            {
                widths[dy + range] = neighborhood switch
                {
                    LtlNeighborhood.Moore => range,
                    LtlNeighborhood.VonNeumann => range - Math.Abs(dy),
                    _ => ISqrt(reach - (long)dy * dy),
                };
            }
            return widths;
        }

        private static int ISqrt(long value)
        {
            var root = (long)Math.Sqrt(value);
            while (root * root > value)
                root--;
            while ((root + 1) * (root + 1) <= value)
                root++;
            return (int)root;
        }

        /// <summary>The rule a text names, in either form of spec/ltl.md ("Rule text"). Throws
        /// <see cref="ArgumentException"/> whose message is <c>invalid Larger than Life rule
        /// '&lt;text&gt;': &lt;reason&gt; (spec/ltl.md)</c>.</summary>
        public static LtlRule Parse(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            if (!TryParse(text, out LtlRule? rule, out string? reason))
                throw new ArgumentException($"invalid Larger than Life rule '{text}': {reason} (spec/ltl.md)");
            return rule!;
        }

        /// <summary><see cref="Parse"/> without throwing: true and the rule, or false and the reason
        /// for the first problem found (spec/ltl.md "Reasons"). Null reads as empty text.</summary>
        public static bool TryParse(string? text, out LtlRule? rule, out string? reason)
        {
            reason = Read(text ?? "", out rule);
            return reason == null;
        }

        /// <summary>Why the unbounded universe refuses <paramref name="text"/> (spec/ltl.md
        /// "Topologies"): a message when it names a Larger than Life rule, else null.</summary>
        internal static string? Refusal(string? text)
        {
            string? reason = PlaneReason(text);
            return reason == null ? null : reason + " (spec/ltl.md)";
        }

        /// <summary><see cref="Refusal"/> without the page: the reason spec/hashlife-multistate.md
        /// "Names" gives for a Larger than Life rule, or null for text that names none.</summary>
        internal static string? PlaneReason(string? text)
        {
            if (text == null || !TryParse(text, out LtlRule? rule, out _))
                return null;
            return $"{rule!.Canonical} is a Larger than Life rule: it runs on a bounded grid, never on the "
                + "unbounded plane";
        }

        private static string Text(int value) => value.ToString(CultureInfo.InvariantCulture);

        /// <summary>A number as written: its value (any past 10⁹ as 10⁹ + 1) and its digits
        /// without leading zeros, for reasons.</summary>
        private readonly struct Number
        {
            public Number(int value, string text)
            {
                Value = value;
                Digits = text;
            }

            public int Value { get; }

            public string Digits { get; }
        }

        private static bool IsDigits(string text)
        {
            if (text.Length == 0)
                return false;
            foreach (char c in text)
            {
                if (c < '0' || c > '9')
                    return false;
            }
            return true;
        }

        private static bool ReadNumber(string digits, out Number number)
        {
            number = default;
            if (!IsDigits(digits))
                return false;
            string text = digits.TrimStart('0');
            if (text.Length == 0)
                text = "0";
            number = new Number(text.Length > 9 ? Past : int.Parse(text, NumberStyles.None, CultureInfo.InvariantCulture), text);
            return true;
        }

        private static bool Lettered(string field, char letter, out Number number)
        {
            number = default;
            if (field.Length < 2 || (field[0] != letter && field[0] != char.ToLowerInvariant(letter)))
                return false;
            return ReadNumber(field.Substring(1), out number);
        }

        private static bool Span(string field, char letter, out Number low, out Number high)
        {
            low = high = default;
            if (field.Length < 2 || (field[0] != letter && field[0] != char.ToLowerInvariant(letter)))
                return false;
            string rest = field.Substring(1);
            int dots = rest.IndexOf("..", StringComparison.Ordinal);
            if (dots < 0)
                return false;
            return ReadNumber(rest.Substring(0, dots), out low) && ReadNumber(rest.Substring(dots + 2), out high);
        }

        /// <summary>The reason a text is no rule, or null with the rule it names.</summary>
        private static string? Read(string text, out LtlRule? rule)
        {
            rule = null;
            int start = 0, end = text.Length;
            while (start < end && RuleString.IsSpace(text[start]))
                start++;
            while (end > start && RuleString.IsSpace(text[end - 1]))
                end--;
            string body = text.Substring(start, end - start);
            bool longForm = body.Length > 0 && (body[0] == 'R' || body[0] == 'r');
            if (!longForm && (body.Length == 0 || body[0] < '0' || body[0] > '9'))
                return "expected R…,C…,M…,S…,B…,N… or five numbers r,bmin,bmax,smin,smax";
            string[] fields = body.Split(',');
            Number range, count, sMin, sMax, bMin, bMax;
            bool middle;
            var hood = LtlNeighborhood.Moore;
            if (longForm)
            {
                if (fields.Length < 5 || fields.Length > 6)
                    return "expected the fields R, C, M, S, B and N, in that order";
                if (!Lettered(fields[0], 'R', out range))
                    return $"expected R and the range, not '{fields[0]}'";
                if (!Lettered(fields[1], 'C', out count))
                    return $"expected C and the number of states, not '{fields[1]}'";
                if (fields[2] != "M0" && fields[2] != "M1" && fields[2] != "m0" && fields[2] != "m1")
                    return $"expected M0 or M1, not '{fields[2]}'";
                middle = fields[2][1] == '1';
                if (!Span(fields[3], 'S', out sMin, out sMax))
                    return $"expected S and a range of counts S<min>..<max>, not '{fields[3]}'";
                if (!Span(fields[4], 'B', out bMin, out bMax))
                    return $"expected B and a range of counts B<min>..<max>, not '{fields[4]}'";
                if (fields.Length == 6)
                {
                    string field = fields[5];
                    if (field.Length != 2 || (field[0] != 'N' && field[0] != 'n'))
                        return $"expected NM, NN or NC, not '{field}'";
                    switch (field[1])
                    {
                        case 'M':
                        case 'm':
                            hood = LtlNeighborhood.Moore;
                            break;
                        case 'N':
                        case 'n':
                            hood = LtlNeighborhood.VonNeumann;
                            break;
                        case 'C':
                        case 'c':
                            hood = LtlNeighborhood.Circular;
                            break;
                        default:
                            return $"expected NM, NN or NC, not '{field}'";
                    }
                }
            }
            else
            {
                if (fields.Length != 5 || !ReadNumber(fields[0], out range) || !ReadNumber(fields[1], out bMin)
                    || !ReadNumber(fields[2], out bMax) || !ReadNumber(fields[3], out sMin)
                    || !ReadNumber(fields[4], out sMax))
                    return "expected five numbers r,bmin,bmax,smin,smax";
                count = new Number(0, "0");
                middle = true;
            }
            if (range.Value < 1 || range.Value > MaxRange)
                return $"the range is 1 to {MaxRange}, not {range.Digits}";
            if (count.Value == 1 || count.Value > MaxStates)
                return $"C is 0 or 2 (two states) or 3 to {MaxStates}, not {count.Digits}";
            string? empty = Empty('S', sMin, sMax) ?? Empty('B', bMin, bMax);
            if (empty != null)
                return empty;
            rule = new LtlRule(
                range.Value, Math.Max(count.Value, 2), middle, sMin.Value, sMax.Value, bMin.Value, bMax.Value, hood);
            return null;
        }

        private static string? Empty(char letter, Number low, Number high)
        {
            if (Math.Max(low.Value, high.Value) > MaxCount)
                return $"a count is at most {MaxCount}";
            if (low.Value > high.Value)
                return $"{letter}{low.Digits}..{high.Digits} is empty";
            return null;
        }

        public bool Equals(LtlRule? other)
            => other != null && Range == other.Range && States == other.States && Middle == other.Middle
                && SurvivalMin == other.SurvivalMin && SurvivalMax == other.SurvivalMax
                && BirthMin == other.BirthMin && BirthMax == other.BirthMax && Neighborhood == other.Neighborhood;

        public override bool Equals(object? obj) => Equals(obj as LtlRule);

        public override int GetHashCode() => Canonical.GetHashCode();
    }
}
