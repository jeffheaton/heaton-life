using System;
using System.Linq;
using System.Text.RegularExpressions;

namespace HeatonLife
{
    /// <summary>Life-like rulestrings: "B&lt;digits&gt;/S&lt;digits&gt;" (spec/lifelike.md).</summary>
    public static class RuleString
    {
        private static readonly Regex Pattern =
            new Regex(@"^\s*[Bb]([0-8]*)\s*/\s*[Ss]([0-8]*)\s*$", RegexOptions.Compiled);

        public static (bool[] Birth, bool[] Survive) Parse(string rule)
        {
            var match = Pattern.Match(rule);
            if (!match.Success)
                throw new ArgumentException($"invalid rulestring: '{rule}'");
            return (Digits(match.Groups[1].Value), Digits(match.Groups[2].Value));
        }

        public static string Canonical(string rule)
        {
            var (birth, survive) = Parse(rule);
            return $"B{Join(birth)}/S{Join(survive)}";
        }

        private static bool[] Digits(string text)
        {
            var set = new bool[9];
            foreach (char c in text)
                set[c - '0'] = true;
            return set;
        }

        private static string Join(bool[] set) =>
            string.Concat(Enumerable.Range(0, 9).Where(i => set[i]));
    }
}
