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
    /// Rule files conformance: replay vectors/ruletable-files/ — every file read and compiled to
    /// its canonical tree with the data its other sections hold, and the reason each refused text
    /// gets (spec/rule-files.md, bit-exact). As strict as the Python runner
    /// (python/tests/test_ruletable_files_vectors.py): an unknown key or spec_version fails.
    /// </summary>
    public class RuleTableFilesConformanceTests
    {
        private static readonly string[] SpecVersions = { "0.16.0" };
        private static readonly string[] Common = { "spec_version", "family", "tier", "kind" };
        private static readonly string[] CompileKeys =
        {
            "input", "tree", "name", "states", "neighbors", "neighborhood", "symmetries", "source", "description",
            "colors", "names", "icons",
        };

        private static string Root => Path.Combine(TestPaths.VectorRoot(), "ruletable-files");

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Root).OrderBy(d => d, StringComparer.Ordinal))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Fact]
        public void BothKindsHaveCases()
        {
            var kinds = new HashSet<string>();
            foreach (object[] c in Cases())
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, (string)c[0], "params.json")));
                kinds.Add(doc.RootElement.GetProperty("kind").GetString()!);
            }
            Assert.Equal(new HashSet<string> { "compile", "reasons" }, kinds);
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string dir = Path.Combine(Root, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "params.json"), Encoding.UTF8));
            JsonElement meta = doc.RootElement;
            string kind = meta.GetProperty("kind").GetString()!;
            Assert.Equal("ruletable-files", meta.GetProperty("family").GetString());
            Assert.Equal("bit-exact", meta.GetProperty("tier").GetString());
            Assert.Contains(meta.GetProperty("spec_version").GetString(), SpecVersions);
            var keys = new HashSet<string>(meta.EnumerateObject().Select(p => p.Name));
            var expected = new HashSet<string>(Common.Concat(kind == "compile" ? CompileKeys : new[] { "cases" }));
            Assert.True(keys.SetEquals(expected), $"{caseName}: keys {string.Join(", ", keys)}");
            if (kind == "compile")
                Compile(dir, meta);
            else
                Reasons(meta);
        }

        private static void Compile(string dir, JsonElement meta)
        {
            string text = new UTF8Encoding(false).GetString(File.ReadAllBytes(Path.Combine(dir, meta.GetProperty("input").GetString()!)));
            RuleTable rule = RuleTable.Parse(text);
            Assert.Equal(File.ReadAllText(Path.Combine(dir, meta.GetProperty("tree").GetString()!)), rule.TreeText());
            Assert.Equal(meta.GetProperty("name").GetString(), rule.Name);
            Assert.Equal(meta.GetProperty("states").GetInt32(), rule.States);
            Assert.Equal(meta.GetProperty("neighbors").GetInt32(), rule.Neighbors);
            Assert.Equal(Nullable(meta.GetProperty("neighborhood")), rule.Neighborhood);
            Assert.Equal(Nullable(meta.GetProperty("symmetries")), rule.Symmetries);
            Assert.Equal(meta.GetProperty("source").GetString(), rule.Source == RuleSource.Table ? "table" : "tree");
            Assert.Equal(meta.GetProperty("description").GetString(), rule.Description);

            JsonElement colors = meta.GetProperty("colors");
            Assert.Equal(colors.GetArrayLength(), rule.Colors.Count);
            for (int i = 0; i < rule.Colors.Count; i++)
            {
                RuleColor color = rule.Colors[i];
                JsonElement entry = colors[i];
                if (color.IsGradient)
                {
                    Assert.Equal(Rgb(entry.GetProperty("from")), color.Start);
                    Assert.Equal(Rgb(entry.GetProperty("to")), color.End!.Value);
                    Assert.Equal(2, entry.EnumerateObject().Count());
                }
                else
                {
                    Assert.Equal(entry.GetProperty("state").GetInt32(), color.State);
                    Assert.Equal(Rgb(entry.GetProperty("rgb")), color.Start);
                    Assert.Equal(2, entry.EnumerateObject().Count());
                }
            }

            JsonElement names = meta.GetProperty("names");
            Assert.Equal(names.GetArrayLength(), rule.Names.Count);
            for (int i = 0; i < rule.Names.Count; i++)
            {
                Assert.Equal(names[i].GetProperty("state").GetInt32(), rule.Names[i].State);
                Assert.Equal(names[i].GetProperty("name").GetString(), rule.Names[i].Name);
            }

            JsonElement icons = meta.GetProperty("icons");
            if (icons.ValueKind == JsonValueKind.Null)
            {
                Assert.Null(rule.Icons);
                return;
            }
            Assert.NotNull(rule.Icons);
            if (icons.TryGetProperty("style", out JsonElement style))
            {
                Assert.Equal(style.GetString(), rule.Icons!.Style);
                Assert.Empty(rule.Icons.Sets);
                return;
            }
            Assert.Null(rule.Icons!.Style);
            JsonElement sets = icons.GetProperty("sets");
            Assert.Equal(sets.GetArrayLength(), rule.Icons.Sets.Count);
            for (int i = 0; i < rule.Icons.Sets.Count; i++)
            {
                RuleIconSet set = rule.Icons.Sets[i];
                JsonElement entry = sets[i];
                Assert.Equal(entry.GetProperty("width").GetInt32(), set.Width);
                JsonElement palette = entry.GetProperty("colors");
                Assert.Equal(palette.GetArrayLength(), set.Colors.Count);
                for (int c = 0; c < set.Colors.Count; c++)
                {
                    Assert.Equal(palette[c][0].GetString(), set.Colors[c].Key);
                    Assert.Equal(Nullable(palette[c][1]), set.Colors[c].Color);
                }
                Assert.Equal(entry.GetProperty("rows").EnumerateArray().Select(r => r.GetString()!).ToArray(), set.Rows.ToArray());
            }
        }

        private static void Reasons(JsonElement meta)
        {
            foreach (JsonElement entry in meta.GetProperty("cases").EnumerateArray())
            {
                Assert.Equal(3, entry.EnumerateObject().Count());
                string text = entry.GetProperty("text").GetString()!;
                string reason = entry.GetProperty("reason").GetString()!;
                int? line = entry.GetProperty("line").ValueKind == JsonValueKind.Null
                    ? (int?)null
                    : entry.GetProperty("line").GetInt32();
                var error = Assert.Throws<RuleFileException>(() => RuleTable.Parse(text));
                Assert.True(reason == error.Reason && line == error.Line,
                    $"{text}: expected '{reason}' at {line}, got '{error.Reason}' at {error.Line}");
                string where = line == null ? "" : $"line {line}: ";
                Assert.Equal($"invalid rule file: {where}{reason} (spec/rule-files.md)", error.Message);
                Assert.False(RuleTable.TryParse(text, out RuleTable? none, out RuleFileException? again));
                Assert.Null(none);
                Assert.Equal(reason, again!.Reason);
            }
        }

        private static string? Nullable(JsonElement value)
            => value.ValueKind == JsonValueKind.Null ? null : value.GetString();

        private static (byte R, byte G, byte B) Rgb(JsonElement value)
            => ((byte)value[0].GetInt32(), (byte)value[1].GetInt32(), (byte)value[2].GetInt32());
    }
}
