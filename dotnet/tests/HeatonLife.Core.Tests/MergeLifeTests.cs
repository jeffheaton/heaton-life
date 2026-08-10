using System;
using System.Linq;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    public class MergeLifeTests
    {
        [Fact]
        public void GenomeCanonicalization()
        {
            const string mixed = "E542-5F79-9341-F31E-6C6B-7F08-8773-7068";
            Assert.Equal("e542-5f79-9341-f31e-6c6b-7f08-8773-7068", MergeLife.CanonicalRule(mixed));
            Assert.Equal(
                MergeLife.CanonicalRule(mixed),
                MergeLife.CanonicalRule(mixed.Replace("-", "")));
        }

        [Theory]
        [InlineData("")]
        [InlineData("e542")]
        [InlineData("zz42-zz42-zz42-zz42-zz42-zz42-zz42-zz42-")]
        [InlineData("e542-5f79-9341-f31e-6c6b-7f08-8773")]
        public void InvalidGenomesAreRejected(string bad)
        {
            Assert.NotNull(MergeLife.RuleError(bad));
            Assert.Throws<ArgumentException>(() => new MergeLife(bad, 8, 8));
        }

        [Fact]
        public void RuleCompilationDetails()
        {
            // 0xff * 8 = 2040 is promoted to 2048 so the top sub-rule catches every count;
            // negative percents index the *next* key color at |pct|/128.
            var rule = MergeLife.CompileRule("ff7f-0080-0000-0000-0000-0000-0000-0000");
            Assert.Equal(2048, rule.Max(e => e.Limit));
            Assert.Equal(0, rule.Min(e => e.Limit));
            Assert.Equal(0, rule[0].Limit); // 0x00 * 8, stable sort keeps rule order among ties
            var top = rule.First(e => e.Limit == 2048);
            Assert.Equal(127 / 127.0, top.Percent, 12);
        }

        [Fact]
        public void SoupDeterminismAndShapes()
        {
            var a = new MergeLife(MergeLife.DefaultRule, 32, 24);
            var b = new MergeLife(MergeLife.DefaultRule, 32, 24);
            a.SeedSoup(11);
            b.SeedSoup(11);
            Assert.Equal(24 * 32 * 3, a.State.Length);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
            a.Step(5);
            b.Step(5);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
        }

        [Fact]
        public void StepChangesGrid()
        {
            var sim = new MergeLife(MergeLife.DefaultRule, 32, 32);
            sim.SeedSoup(1);
            byte[] before = sim.State.ToArray();
            sim.Step();
            Assert.NotEqual(before, sim.State.ToArray());
        }

        [Fact]
        public void DecodeRuleMatchesTheRuleTabTable()
        {
            var rows = MergeLife.DecodeRule(MergeLife.DefaultRule);
            Assert.Equal(8, rows.Length);
            var first = rows[0]; // the HeatonCA Rule-tab top row
            Assert.Equal((760, 0, 759), (first.Limit, first.RangeLow, first.RangeHigh));
            Assert.Equal((1, "Red", "Red"), (first.ColorIndex, first.ColorName, first.TargetName));
            Assert.Equal(((byte)255, (byte)0, (byte)0), (first.TargetR, first.TargetG, first.TargetB));
            Assert.Equal(((byte)0x5F, (sbyte)0x79), (first.RangeByte, first.PercentByte));
            Assert.Equal(95, (int)(first.Percent * 100));
            Assert.Equal(23, (int)(rows[7].Percent * 100)); // truncation, not rounding
        }

        [Fact]
        public void DecodeRuleNegativeSwapsTargetAndKeepsRawOctets()
        {
            var rows = MergeLife.DecodeRule("ff40-00c0-8020-407f-2081-6001-a0ff-e080");
            foreach (var row in rows)
            {
                if (row.ColorIndex == 0)
                {
                    Assert.Equal(2048, row.Limit);
                    Assert.Equal(0xFF, row.RangeByte); // raw, not limit/8
                }
                if (row.ColorIndex == 1)
                {
                    Assert.Equal(-0.5, row.Percent);
                    Assert.Equal(("Red", "Green"), (row.ColorName, row.TargetName));
                    Assert.Equal(-64, row.PercentByte);
                }
                if (row.ColorIndex == 7)
                    Assert.Equal((0, "Black"), (row.TargetIndex, row.TargetName)); // wrap
            }
        }

        [Fact]
        public void DecodeVectorsReplay()
        {
            string root = Path.Combine(TestPaths.VectorRoot(), "mergelife-decode");
            string[] cases = Directory.GetDirectories(root);
            Assert.NotEmpty(cases);
            foreach (string caseDir in cases)
            {
                using var doc = JsonDocument.Parse(
                    File.ReadAllText(Path.Combine(caseDir, "params.json")));
                var rows = MergeLife.DecodeRule(doc.RootElement.GetProperty("rule").GetString()!);
                var expected = doc.RootElement.GetProperty("expected_rows");
                Assert.Equal(expected.GetArrayLength(), rows.Length);
                for (int i = 0; i < rows.Length; i++)
                {
                    var row = rows[i];
                    var e = expected[i];
                    Assert.Equal(e.GetProperty("limit").GetInt32(), row.Limit);
                    Assert.Equal(e.GetProperty("range_low").GetInt32(), row.RangeLow);
                    Assert.Equal(e.GetProperty("range_high").GetInt32(), row.RangeHigh);
                    Assert.Equal(e.GetProperty("percent").GetDouble(), row.Percent);
                    Assert.Equal(e.GetProperty("color_index").GetInt32(), row.ColorIndex);
                    Assert.Equal(e.GetProperty("color_name").GetString(), row.ColorName);
                    Assert.Equal(e.GetProperty("target_index").GetInt32(), row.TargetIndex);
                    Assert.Equal(e.GetProperty("target_name").GetString(), row.TargetName);
                    var rgb = e.GetProperty("target_rgb");
                    Assert.Equal(
                        (rgb[0].GetInt32(), rgb[1].GetInt32(), rgb[2].GetInt32()),
                        ((int)row.TargetR, (int)row.TargetG, (int)row.TargetB));
                    Assert.Equal(e.GetProperty("range_byte").GetInt32(), row.RangeByte);
                    Assert.Equal(e.GetProperty("percent_byte").GetInt32(), row.PercentByte);
                }
            }
        }

        [Fact]
        public void RandomRuleIsValidAndDeterministic()
        {
            string g1 = MergeLife.RandomRule(42);
            string g2 = MergeLife.RandomRule(42);
            Assert.Equal(g1, g2);
            Assert.Null(MergeLife.RuleError(g1));
            Assert.NotEqual(g1, MergeLife.RandomRule(43));
        }
    }
}
