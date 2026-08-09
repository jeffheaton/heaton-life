using System;
using System.Text;

namespace HeatonLife
{
    /// <summary>
    /// Life-like rulestrings: "B&lt;digits&gt;/S&lt;digits&gt;" (spec/lifelike.md).
    /// Hand-rolled parser — no Regex, keeping the core lean under IL2CPP/AOT.
    /// Accepted grammar (whitespace-tolerant around tokens, digits 0-8 contiguous):
    /// ws* [Bb] digits* ws* '/' ws* [Ss] digits* ws*.
    /// </summary>
    public static class RuleString
    {
        public static (bool[] Birth, bool[] Survive) Parse(string rule)
        {
            int pos = 0;
            var birth = new bool[9];
            var survive = new bool[9];
            bool ok = SkipWhitespace(rule, ref pos)
                && Expect(rule, ref pos, 'B', 'b')
                && Digits(rule, ref pos, birth)
                && SkipWhitespace(rule, ref pos)
                && Expect(rule, ref pos, '/', '/')
                && SkipWhitespace(rule, ref pos)
                && Expect(rule, ref pos, 'S', 's')
                && Digits(rule, ref pos, survive)
                && SkipWhitespace(rule, ref pos)
                && pos == rule.Length;
            if (!ok)
                throw new ArgumentException($"invalid rulestring: '{rule}'");
            return (birth, survive);
        }

        public static string Canonical(string rule)
        {
            var (birth, survive) = Parse(rule);
            var sb = new StringBuilder("B");
            AppendDigits(sb, birth);
            sb.Append("/S");
            AppendDigits(sb, survive);
            return sb.ToString();
        }

        private static bool SkipWhitespace(string text, ref int pos)
        {
            while (pos < text.Length && char.IsWhiteSpace(text[pos]))
                pos++;
            return true;
        }

        private static bool Expect(string text, ref int pos, char upper, char lower)
        {
            if (pos < text.Length && (text[pos] == upper || text[pos] == lower))
            {
                pos++;
                return true;
            }
            return false;
        }

        private static bool Digits(string text, ref int pos, bool[] set)
        {
            while (pos < text.Length && text[pos] >= '0' && text[pos] <= '8')
                set[text[pos++] - '0'] = true;
            return true;
        }

        private static void AppendDigits(StringBuilder sb, bool[] set)
        {
            for (int i = 0; i < 9; i++)
                if (set[i])
                    sb.Append((char)('0' + i));
        }
    }
}
