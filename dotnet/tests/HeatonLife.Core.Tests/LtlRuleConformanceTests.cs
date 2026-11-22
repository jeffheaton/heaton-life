using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Larger than Life conformance: replay vectors/ltl-rules/ — rule texts to their canonical form
    /// and parts, or the reason a text is no rule, and each neighborhood's half-widths and size at
    /// chosen ranges (spec/ltl.md "Vector encoding"). As strict as the Python runner
    /// (python/tests/test_ltl_rule_vectors.py).
    /// </summary>
    public class LtlRuleConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.16.0" };
        private static readonly string[] CaseKeys = { "spec_version", "family", "tier", "kind", "cases" };
        private static readonly string[] RuleKeys =
            { "input", "canonical", "range", "states", "middle", "survival", "birth", "neighborhood", "size" };
        private static readonly string[] ErrorKeys = { "input", "error", "reason" };
        private static readonly string[] HoodKeys = { "neighborhood", "range", "half_widths", "size" };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "ltl-rules");

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Root).OrderBy(d => d, StringComparer.Ordinal))
            {
                if (File.Exists(Path.Combine(dir, "params.json")))
                    yield return new object[] { Path.GetFileName(dir) };
            }
        }

        [Fact]
        public void EveryKindHasVectors()
        {
            var kinds = new HashSet<string>();
            foreach (object[] c in Cases())
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, (string)c[0], "params.json")));
                kinds.Add(doc.RootElement.GetProperty("kind").GetString()!);
            }
            Assert.Equal(new HashSet<string> { "rules", "neighborhoods" }, kinds);
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, caseName, "params.json")));
            JsonElement root = doc.RootElement;
            AssertKeys(root, CaseKeys);
            Assert.Contains(root.GetProperty("spec_version").GetString(), SpecVersions);
            Assert.Equal("ltl-rules", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string kind = root.GetProperty("kind").GetString()!;
            foreach (JsonElement entry in root.GetProperty("cases").EnumerateArray())
            {
                switch (kind)
                {
                    case "neighborhoods":
                        Neighborhood(entry);
                        break;
                    case "rules":
                        Rule(entry);
                        break;
                    default:
                        throw new InvalidDataException($"unknown kind '{kind}' in {caseName}");
                }
            }
        }

        private static void Neighborhood(JsonElement entry)
        {
            AssertKeys(entry, HoodKeys);
            int[] widths = LtlRule.HalfWidths(entry.GetProperty("range").GetInt32(), Hood(entry));
            Assert.Equal(entry.GetProperty("half_widths").EnumerateArray().Select(w => w.GetInt32()), widths);
            Assert.Equal(entry.GetProperty("size").GetInt32(), widths.Sum(w => 2 * w + 1));
        }

        private static void Rule(JsonElement entry)
        {
            string text = entry.GetProperty("input").GetString()!;
            if (entry.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
            {
                AssertKeys(entry, ErrorKeys);
                string reason = entry.GetProperty("reason").GetString()!;
                Assert.False(LtlRule.TryParse(text, out LtlRule? none, out string? found), text);
                Assert.Null(none);
                Assert.Equal(reason, found);
                ArgumentException thrown = Assert.Throws<ArgumentException>(() => LtlRule.Parse(text));
                Assert.Equal($"invalid Larger than Life rule '{text}': {reason} (spec/ltl.md)", thrown.Message);
                return;
            }
            AssertKeys(entry, RuleKeys);
            LtlRule rule = LtlRule.Parse(text);
            Assert.True(LtlRule.TryParse(text, out LtlRule? same, out string? noReason), text);
            Assert.Null(noReason);
            Assert.Equal(rule, same);
            Assert.Equal(entry.GetProperty("canonical").GetString(), rule.Canonical);
            Assert.Equal(entry.GetProperty("range").GetInt32(), rule.Range);
            Assert.Equal(entry.GetProperty("states").GetInt32(), rule.States);
            Assert.Equal(entry.GetProperty("middle").GetBoolean(), rule.Middle);
            Assert.Equal(Pair(entry.GetProperty("survival")), (rule.SurvivalMin, rule.SurvivalMax));
            Assert.Equal(Pair(entry.GetProperty("birth")), (rule.BirthMin, rule.BirthMax));
            Assert.Equal(Hood(entry), rule.Neighborhood);
            Assert.Equal(entry.GetProperty("size").GetInt32(), rule.Size);
            Assert.Equal(rule, LtlRule.Parse(rule.Canonical)); // the canonical text names the same rule
        }

        private static (int, int) Pair(JsonElement pair)
        {
            Assert.Equal(2, pair.GetArrayLength());
            return (pair[0].GetInt32(), pair[1].GetInt32());
        }

        private static LtlNeighborhood Hood(JsonElement entry) => entry.GetProperty("neighborhood").GetString() switch
        {
            "moore" => LtlNeighborhood.Moore,
            "vonneumann" => LtlNeighborhood.VonNeumann,
            "circular" => LtlNeighborhood.Circular,
            var other => throw new InvalidDataException($"unknown neighborhood '{other}'"),
        };

        private static void AssertKeys(JsonElement element, string[] keys)
        {
            var found = new HashSet<string>(element.EnumerateObject().Select(p => p.Name));
            Assert.Equal(new HashSet<string>(keys), found);
        }
    }
}
