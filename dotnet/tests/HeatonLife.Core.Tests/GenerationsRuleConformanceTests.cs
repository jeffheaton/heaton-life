using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Generations rule conformance: replay vectors/generations-rules/ — rule texts in both
    /// spellings to their canonical forms, numbers of states, Life-like rules and tables, or the
    /// reasons a text is refused (spec/generations.md "Rules", "Vector encoding"). As strict as
    /// the Python runner (python/tests/test_generations_rules_vectors.py): an unknown key or
    /// spec_version fails.
    /// </summary>
    public class GenerationsRuleConformanceTests
    {
        private static readonly string[] CaseKeys = { "spec_version", "family", "tier", "cases" };
        private static readonly string[] RuleKeys = { "input", "canonical", "states", "life", "table" };
        private static readonly string[] ReasonKeys = { "input", "error", "reason" };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "generations-rules");

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Root).OrderBy(d => d, StringComparer.Ordinal))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Fact]
        public void BothCasesExist()
        {
            var names = new HashSet<string>(Cases().Select(c => (string)c[0]));
            Assert.True(names.SetEquals(new[] { "canonical", "reasons" }), string.Join(", ", names));
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, caseName, "params.json")));
            JsonElement root = doc.RootElement;
            AssertKeys(root, CaseKeys);
            Assert.Equal("0.16.0", root.GetProperty("spec_version").GetString());
            Assert.Equal("generations-rules", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            foreach (JsonElement entry in root.GetProperty("cases").EnumerateArray())
            {
                string text = entry.GetProperty("input").GetString()!;
                if (entry.TryGetProperty("error", out JsonElement error) && error.GetBoolean())
                {
                    AssertKeys(entry, ReasonKeys);
                    Assert.False(GenerationsRule.TryCompile(text, out GenerationsRule? none, out string? reason), text);
                    Assert.Null(none);
                    Assert.True(entry.GetProperty("reason").GetString() == reason, $"{text}: {reason}");
                    ArgumentException thrown = Assert.Throws<ArgumentException>(() => GenerationsRule.Compile(text));
                    Assert.StartsWith($"invalid Generations rule '{text}': {reason} (spec/generations.md)", thrown.Message);
                    continue;
                }
                AssertKeys(entry, RuleKeys);
                Assert.True(GenerationsRule.TryCompile(text, out GenerationsRule? compiled, out string? noReason), $"{text}: {noReason}");
                Assert.Null(noReason);
                GenerationsRule rule = GenerationsRule.Compile(text);
                Assert.Equal(rule, compiled);
                Assert.True(entry.GetProperty("canonical").GetString() == rule.Canonical, text);
                Assert.True(entry.GetProperty("states").GetInt32() == rule.States, text);
                Assert.True(entry.GetProperty("life").GetString() == rule.Life.Canonical, text);
                Assert.True(entry.GetProperty("table").GetString() == RuleConformanceTests.Hex(rule.Life.Table), text);
                Assert.Equal(rule, GenerationsRule.Compile(rule.Canonical)); // the canonical form is a fixed point
                if (rule.HasB0) // the plane refuses it at its name (spec/hashlife-multistate.md "Names")
                    Assert.False(StateRules.TryCompile(text, out _, out _), text);
                else
                    Assert.Equal<StateRule>(rule, StateRules.Compile(text)); // a name multi-state HashLife accepts
            }
        }

        private static void AssertKeys(JsonElement element, string[] expected)
        {
            var keys = new HashSet<string>(element.EnumerateObject().Select(p => p.Name));
            Assert.True(keys.SetEquals(expected), $"keys {string.Join(", ", keys)}");
        }
    }
}
