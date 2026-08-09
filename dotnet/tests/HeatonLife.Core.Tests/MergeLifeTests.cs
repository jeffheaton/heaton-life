using System;
using System.Linq;
using Xunit;

namespace HeatonLife.Tests
{
    public class MergeLifeTests
    {
        [Fact]
        public void GenomeCanonicalization()
        {
            const string mixed = "E542-5F79-9341-F31E-6C6B-7F08-8773-7068";
            Assert.Equal("e542-5f79-9341-f31e-6c6b-7f08-8773-7068", MergeLife.CanonicalGenome(mixed));
            Assert.Equal(
                MergeLife.CanonicalGenome(mixed),
                MergeLife.CanonicalGenome(mixed.Replace("-", "")));
        }

        [Theory]
        [InlineData("")]
        [InlineData("e542")]
        [InlineData("zz42-zz42-zz42-zz42-zz42-zz42-zz42-zz42-")]
        [InlineData("e542-5f79-9341-f31e-6c6b-7f08-8773")]
        public void InvalidGenomesAreRejected(string bad)
        {
            Assert.NotNull(MergeLife.GenomeError(bad));
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
            Assert.Equal(0, rule[0].Limit); // 0x00 * 8, stable sort keeps genome order among ties
            var top = rule.First(e => e.Limit == 2048);
            Assert.Equal(127 / 127.0, top.Percent, 12);
        }

        [Fact]
        public void SoupDeterminismAndShapes()
        {
            var a = new MergeLife(MergeLife.DefaultGenome, 32, 24);
            var b = new MergeLife(MergeLife.DefaultGenome, 32, 24);
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
            var sim = new MergeLife(MergeLife.DefaultGenome, 32, 32);
            sim.SeedSoup(1);
            byte[] before = sim.State.ToArray();
            sim.Step();
            Assert.NotEqual(before, sim.State.ToArray());
        }

        [Fact]
        public void RandomGenomeIsValidAndDeterministic()
        {
            string g1 = MergeLife.RandomGenome(42);
            string g2 = MergeLife.RandomGenome(42);
            Assert.Equal(g1, g2);
            Assert.Null(MergeLife.GenomeError(g1));
            Assert.NotEqual(g1, MergeLife.RandomGenome(43));
        }
    }
}
