using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Life-like rule conformance: replay vectors/rules/ — rule text to its canonical string,
    /// neighborhood and table, or an error and, where a case pins one, its reason (spec/rules.md
    /// "Vector encoding", "Reasons"). As strict as the
    /// Python runner (python/tests/test_rule_vectors.py): an unknown key or spec_version fails.
    /// </summary>
    public class RuleConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.16.0" };
        private static readonly string[] CaseKeys = { "spec_version", "family", "tier", "cases" };
        private static readonly string[] RuleKeys = { "input", "canonical", "neighborhood", "table" };
        private static readonly string[] VariantKeys = { "input", "canonical", "neighborhood", "table", "states", "base" };
        private static readonly string[] ErrorKeys = { "input", "error" };
        private static readonly string[] ReasonKeys = { "input", "error", "reason" };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "rules");

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Root).OrderBy(d => d, StringComparer.Ordinal))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Fact]
        public void EveryRuleClassHasVectors()
        {
            var names = new HashSet<string>(Cases().Select(c => (string)c[0]));
            foreach (string name in new[]
            {
                "totalistic", "isotropic", "isotropic-classes", "map", "hexagonal", "von-neumann", "errors", "reasons",
                "history", "history-two-state", "super", "super-two-state",
            })
                Assert.Contains(name, names);
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, caseName, "params.json")));
            JsonElement root = doc.RootElement;
            // spec 0.16.0: a file may compile its texts with variants allowed (spec/rules.md).
            bool variants = root.TryGetProperty("variants", out JsonElement flag) && flag.GetBoolean();
            AssertKeys(root, root.TryGetProperty("variants", out _) ? CaseKeys.Append("variants").ToArray() : CaseKeys);
            Assert.Contains(root.GetProperty("spec_version").GetString(), SpecVersions);
            Assert.Equal("rules", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            foreach (JsonElement entry in root.GetProperty("cases").EnumerateArray())
            {
                string text = entry.GetProperty("input").GetString()!;
                if (entry.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                {
                    bool pinned = entry.TryGetProperty("reason", out JsonElement want);
                    AssertKeys(entry, pinned ? ReasonKeys : ErrorKeys);
                    if (!variants)
                        Assert.False(RuleString.TryCompile(text, out _), text);
                    Assert.False(RuleString.TryCompile(text, variants, out LifeRule? none, out string? reason), text);
                    Assert.Null(none);
                    Assert.NotNull(reason);
                    ArgumentException thrown = Assert.Throws<ArgumentException>(() => RuleString.Compile(text, variants));
                    Assert.StartsWith($"invalid rule '{text}': {reason} (spec/rules.md)", thrown.Message);
                    if (pinned)
                        Assert.True(want.GetString() == reason, $"{text}: {reason}");
                    continue;
                }
                AssertKeys(entry, variants ? VariantKeys : RuleKeys);
                Assert.True(RuleString.TryCompile(text, variants, out LifeRule? compiled, out string? noReason), text);
                Assert.Null(noReason);
                LifeRule rule = RuleString.Compile(text, variants);
                Assert.Equal(rule.Canonical, compiled!.Canonical);
                Assert.True(entry.GetProperty("canonical").GetString() == rule.Canonical, text);
                Assert.True(entry.GetProperty("neighborhood").GetString() == Name(rule.Neighborhood), text);
                Assert.True(entry.GetProperty("table").GetString() == Hex(rule.Table), text);
                if (variants)
                {
                    Assert.True(entry.GetProperty("states").GetInt32() == rule.States, text);
                    Assert.True(entry.GetProperty("base").GetString() == rule.Base.Canonical, text);
                }
                // The canonical string compiles to the same rule (spec/rules.md "Canonical form").
                LifeRule again = RuleString.Compile(rule.Canonical, variants);
                Assert.Equal(rule.Canonical, again.Canonical);
                Assert.Equal(rule.Variant, again.Variant);
                Assert.True(rule.Table.SequenceEqual(again.Table), text);
            }
        }

        private static void AssertKeys(JsonElement element, string[] expected)
        {
            var keys = new HashSet<string>(element.EnumerateObject().Select(p => p.Name));
            Assert.True(keys.SetEquals(expected), $"keys {string.Join(", ", keys)}");
        }

        /// <summary>The vectors' spelling of a neighborhood.</summary>
        internal static string Name(RuleNeighborhood neighborhood) => neighborhood switch
        {
            RuleNeighborhood.Moore => "moore",
            RuleNeighborhood.Hexagonal => "hexagonal",
            _ => "vonneumann",
        };

        /// <summary>spec/rules.md "Vector encoding": 128 lowercase hex digits, entry 0 in the
        /// first digit's high bit.</summary>
        internal static string Hex(ReadOnlySpan<byte> table)
        {
            var sb = new StringBuilder(128);
            for (int i = 0; i < table.Length; i += 4)
            {
                int digit = (table[i] << 3) | (table[i + 1] << 2) | (table[i + 2] << 1) | table[i + 3];
                sb.Append("0123456789abcdef"[digit]);
            }
            return sb.ToString();
        }
    }
}
