using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Rules with B0 on the unbounded plane (spec/hashlife.md "Rules with B0", spec/rules.md "B0
    /// and the background"): the universe holds the cells that differ from the background, B0
    /// with Smax runs as its black/white reversal, and B0 without Smax alternates two phase tables
    /// with every step of two or more generations at an even start. Checked against a torus,
    /// which runs the rule on the plane's own cells, for every rule form. The Python reference's
    /// tests/test_hashlife_b0.py.
    /// </summary>
    public class HashLifeB0Tests
    {
        private const string Base64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        /// <summary>A MAP rule with a random table that has B0, with or without Smax.</summary>
        private static string MapRule(uint seed, bool smax)
        {
            var bits = new byte[516];
            var rng = new Pcg32(seed);
            for (int i = 0; i < 512; i++)
                bits[i] = (byte)(rng.NextU32() < 0x4CCCCCCDu ? 1 : 0); // about 0.3
            bits[0] = 1;
            bits[511] = (byte)(smax ? 1 : 0);
            return MapOf(bits);
        }

        /// <summary>A Moore MAP string writing a 512-entry table (every neighborhood's table is a
        /// Moore table); any entries past 512 are the last character's unused bits.</summary>
        private static string MapOf(IReadOnlyList<byte> table)
        {
            var chars = new char[86];
            for (int c = 0; c < 86; c++)
            {
                int value = 0;
                for (int b = 0; b < 6; b++)
                {
                    int i = c * 6 + b;
                    value = (value << 1) | (i < 512 ? table[i] : 0);
                }
                chars[c] = Base64[value];
            }
            return "MAP" + new string(chars);
        }

        // B0 without Smax (the phases alternate), then B0 with Smax (the reversal), in every form.
        public static TheoryData<string> AllB0Rules()
        {
            var data = new TheoryData<string>();
            foreach (string rule in new[]
            {
                "B0/S", "B03/S23", "B01/S1", "B02a/S12-a", "B0/S2H", "B0/S013V", MapRule(7, false),
                "B0123478/S01234678", "B0/S8", "B01c/S8", "B0/S6H", "B0/S4V", MapRule(8, true),
            })
            {
                data.Add(rule);
            }
            return data;
        }

        private static byte[] SoupCells(int size, uint seed, double density = 0.4)
        {
            var cells = new byte[size * size];
            Seeding.Soup(cells, density, seed);
            return cells;
        }

        private static HashLife SoupUniverse(string rule, uint seed = 1, int size = 16)
        {
            var u = new HashLife(rule);
            u.SetRect(-size / 2, -size / 2, SoupCells(size, seed), size, size);
            return u;
        }

        /// <summary>The node lines of the universe's canonical Macrocell text: its cells alone.</summary>
        private static string[] Nodes(HashLife u)
            => u.ToMacrocell().Split('\n').Where(l => l.Length > 0 && l[0] != '[' && l[0] != '#').ToArray();

        [Fact]
        public void TheBackgroundOfEachKindOfRule()
        {
            LifeRule life = RuleString.Compile("B3/S23");
            LifeRule strobe = RuleString.Compile("B03/S23");
            LifeRule reversed = RuleString.Compile("B0123478/S01234678");
            Assert.Equal((false, false), (life.HasB0, life.HasSmax));
            Assert.Equal((true, false), (strobe.HasB0, strobe.HasSmax));
            Assert.Equal((true, true), (reversed.HasB0, reversed.HasSmax));
            Assert.True(RuleString.Compile("B3/S238").HasSmax);
            foreach (BigInteger g in new[] { 0, 1, 2, 3, (BigInteger.One << 64) + 1, BigInteger.Pow(10, 40) })
            {
                Assert.False(life.BackgroundAlive(g));
                Assert.True(reversed.BackgroundAlive(g)); // alive from generation 0 on
                Assert.Equal(!g.IsEven, strobe.BackgroundAlive(g));
            }
            Assert.Throws<ArgumentOutOfRangeException>(() => strobe.BackgroundAlive(-1));
            // Smax is the all-alive block's entry in every neighborhood: S6 hexagonal, S4 von Neumann.
            Assert.True(RuleString.Compile("B0/S6H").HasSmax);
            Assert.False(RuleString.Compile("B0/S5H").HasSmax);
            Assert.True(RuleString.Compile("B0/S4V").HasSmax);
            Assert.False(RuleString.Compile("B0/S3V").HasSmax);
        }

        /// <summary>spec/hashlife.md "Oracles": a torus big enough that nothing meets itself holds
        /// the plane's own cells, which are the universe's XOR the background.</summary>
        [Theory]
        [MemberData(nameof(AllB0Rules))]
        public void ATorusRunsThePlaneTheUniverseStandsFor(string rule)
        {
            LifeRule compiled = RuleString.Compile(rule);
            const int size = 80, patch = 12, off = (size - patch) / 2;
            byte[] cells = SoupCells(patch, 3);
            var u = new HashLife(rule);
            u.SetRect(0, 0, cells, patch, patch);
            byte alive = (byte)(compiled.BackgroundAlive(0) ? 1 : 0); // with Smax, alive from the start
            var plane = new byte[size * size];
            for (int i = 0; i < plane.Length; i++)
                plane[i] = alive;
            for (int y = 0; y < patch; y++)
                for (int x = 0; x < patch; x++)
                    plane[(off + y) * size + off + x] = (byte)(cells[y * patch + x] ^ alive);
            var torus = new LifeLike(rule, size, size, Boundary.Torus);
            torus.SetState(plane);
            for (int step = 0; step < 18; step++)
            {
                Assert.Equal(compiled.BackgroundAlive(u.Generation), u.BackgroundAlive);
                byte[] view = u.GetRect(-off, -off, size - off - 1, size - off - 1);
                byte background = (byte)(u.BackgroundAlive ? 1 : 0);
                for (int i = 0; i < view.Length; i++)
                    view[i] ^= background;
                Assert.True(view.AsSpan().SequenceEqual(torus.State), $"{rule} at generation {u.Generation}");
                u.Step(1);
                torus.Step();
            }
        }

        // The reversals of B2/S34H and B2/S013V: rules whose reversals are tame enough to jump.
        [Theory]
        [InlineData("B0123478/S01234678")]
        [InlineData("B01456/S012356H")]
        [InlineData("B02/S0134V")]
        public void B0WithSmaxRunsAsItsReversal(string rule)
        {
            ReadOnlySpan<byte> table = RuleString.Compile(rule).Table;
            var reversal = new byte[512];
            for (int i = 0; i < 512; i++)
                reversal[i] = (byte)(1 - table[511 - i]);
            HashLife a = SoupUniverse(rule, 5, 20);
            var b = new HashLife(MapOf(reversal));
            b.SetRect(-10, -10, SoupCells(20, 5), 20, 20);
            foreach (BigInteger n in new[] { 1, 2, 7, 100, (BigInteger.One << 40) + 3 })
            {
                a.Step(n);
                b.Step(n);
                Assert.True(a.BackgroundAlive);
                Assert.Equal(b.Population, a.Population);
                Assert.Equal(b.BoundingBox, a.BoundingBox);
                Assert.Equal(Nodes(b), Nodes(a));
            }
        }

        [Fact]
        public void LifeAndItsReversalAgreeCellForCell()
        {
            byte[] rPentomino = { 0, 1, 1, 1, 1, 0, 0, 1, 0 };
            var anti = new HashLife("B0123478/S01234678");
            var life = new HashLife("B3/S23");
            anti.SetRect(-1, -1, rPentomino, 3, 3);
            life.SetRect(-1, -1, rPentomino, 3, 3);
            anti.Step(1103);
            life.Step(1103);
            Assert.Equal(new BigInteger(116), anti.Population);
            Assert.Equal(Nodes(life), Nodes(anti));
        }

        [Theory]
        [InlineData("B03/S23")]
        [InlineData("B0/S")]
        [InlineData("B01/S1")]
        [InlineData("B0/S2H")]
        [InlineData("B0123478/S01234678")]
        public void AJumpIsItsSingleGenerations(string rule)
        {
            for (int start = 0; start < 4; start++)
            {
                foreach (int n in new[] { 1, 2, 3, 5, 8, 13, 32, 37 })
                {
                    HashLife jumped = SoupUniverse(rule, (uint)start + 7);
                    HashLife stepped = SoupUniverse(rule, (uint)start + 7);
                    jumped.Step(start);
                    stepped.Step(start);
                    jumped.Step(n);
                    for (int i = 0; i < n; i++)
                        stepped.Step(1);
                    Assert.Equal(new BigInteger(start + n), jumped.Generation);
                    Assert.Equal(stepped.ToMacrocell(), jumped.ToMacrocell());
                }
            }
        }

        /// <summary>Steps past 2^64 take the BigInteger path, from an odd generation as well.</summary>
        [Fact]
        public void AJumpPastTwoToTheSixtyFourKeepsTheParities()
        {
            BigInteger big = (BigInteger.One << 64) + 5;
            foreach (int start in new[] { 1, 2 })
            {
                var dilated = new HashLife("B0/S"); // a cell grows to its block and back, period 2
                dilated.SetCell(0, 0, true);
                dilated.Step(start);
                dilated.Step(big);
                Assert.Equal(big + start, dilated.Generation);
                bool odd = !dilated.Generation.IsEven;
                Assert.Equal(odd, dilated.BackgroundAlive);
                Assert.Equal(new BigInteger(odd ? 9 : 1), dilated.Population);
            }
            HashLife a = SoupUniverse("B02a/S12-a", 11, 24), b = SoupUniverse("B02a/S12-a", 11, 24);
            a.Step(1);
            b.Step(1);
            a.Step((BigInteger.One << 64) + 3);
            b.Step(3);
            b.Step(BigInteger.One << 64);
            Assert.Equal(b.ToMacrocell(), a.ToMacrocell());
        }

        /// <summary>spec/hashlife.md "Memory": sub-steps split under a small budget keep the parities.</summary>
        [Fact]
        public void ATightBudgetChangesNothing()
        {
            var roomy = new HashLife("B03/S23");
            var tight = new HashLife("B03/S23");
            tight.Store.MaxNodes = 3000; // below the 10 MiB floor, so the store must collect and split
            foreach (HashLife u in new[] { roomy, tight })
            {
                u.SetRect(-20, -20, SoupCells(40, 21, 0.45), 40, 40);
                u.Step(1);
                u.Step((1 << 7) + 1);
            }
            Assert.True(tight.Collections > 0);
            Assert.Equal(roomy.ToMacrocell(), tight.ToMacrocell());
        }

        [Fact]
        public void TheGenerationAndTheRuleSayWhatTheCellsStandFor()
        {
            var u = new HashLife("B03/S23");
            u.SetRect(0, 0, Glider, 3, 3);
            u.Step(3);
            Assert.Equal((new BigInteger(3), true), (u.Generation, u.BackgroundAlive));
            string[] cells = Nodes(u);
            u.SetGeneration(4); // the other parity: no cell of the universe changes
            Assert.False(u.BackgroundAlive);
            Assert.Equal(cells, Nodes(u));
            u.SetGeneration(3);
            u.Rule = "B0123478/S01234678"; // keeps the cells; the background is alive throughout
            Assert.True(u.BackgroundAlive);
            Assert.Equal(cells, Nodes(u));
            u.Rule = "B3/S23";
            Assert.False(u.BackgroundAlive);
            Assert.Equal(cells, Nodes(u));
        }

        /// <summary>Where the background is alive a live cell of the universe is a dead cell of the
        /// plane: to give the plane's cell a state, set the universe's to that XOR background.</summary>
        [Fact]
        public void EditingWritesTheUniversesCells()
        {
            var u = new HashLife("B0/S"); // births on an empty block only: the background flips
            u.Step(1);
            Assert.Equal((BigInteger.Zero, true), (u.Population, u.BackgroundAlive));
            u.SetCell(5, 5, true); // the plane's cell (5, 5) dies
            Assert.False(u.GetCell(5, 5) ^ u.BackgroundAlive);
            u.Step(1);
            // On the plane every live cell dies (B0/S keeps none), and (5, 5) stays dead: its eight
            // neighbors were alive, and only a cell whose block is empty is born.
            Assert.Equal((BigInteger.Zero, false), (u.Population, u.BackgroundAlive));
        }

        /// <summary>B0/S runs as P₀ = "any live cell in the block" from a dead background and P₁ =
        /// "the whole block alive" from a live one: a single cell grows to its block and back.</summary>
        [Fact]
        public void DilationAndErosion()
        {
            var u = new HashLife("B0/S");
            u.SetCell(0, 0, true);
            u.Step(1);
            Assert.Equal(new BigInteger(9), u.Population);
            Assert.Equal(new CellBox(-1, -1, 1, 1), u.BoundingBox);
            u.Step(1);
            Assert.Equal(BigInteger.One, u.Population);
            u.Step((BigInteger.One << 64) + 1);
            Assert.Equal(new BigInteger(9), u.Population);
            Assert.True(u.BackgroundAlive);
        }

        /// <summary>spec/hashlife.md "Rules with B0": the selection's cells after n generations are
        /// put back as they are; over a selection that holds everything, that is what Step gives.</summary>
        [Theory]
        [InlineData("B03/S23")]
        [InlineData("B0123478/S01234678")]
        public void AdvancingPartOfTheUniverseWorksOnItsCells(string rule)
        {
            HashLife u = SoupUniverse(rule, 9, 12);
            u.Step(1);
            HashLife stepped = HashLife.FromMacrocell(u.ToMacrocell());
            stepped.Step(5);
            u.AdvanceSelection(-200, -200, 200, 200, 5);
            Assert.Equal(BigInteger.One, u.Generation);
            Assert.Equal(Nodes(stepped), Nodes(u));
            u.AdvanceOutside(-200, -200, 200, 200, 3); // the outside holds no cell to evolve
            Assert.Equal(Nodes(stepped), Nodes(u));
        }

        [Theory]
        [InlineData("B03/S23")]
        [InlineData("B0123478/S01234678")]
        [InlineData("B0/S2H")]
        [InlineData("B01c/S8")]
        public void FilesRoundTrip(string rule)
        {
            foreach (int generation in new[] { 0, 1, 2, 5 })
            {
                HashLife u = SoupUniverse(rule, 13, 10);
                u.Step(generation);
                string mc = u.ToMacrocell(), rle = u.ToRle();
                Assert.Contains($"#R {u.Rule}\n", mc);
                foreach (HashLife again in new[]
                {
                    HashLife.FromMacrocell(mc),
                    HashLife.FromRle(rle),
                    PatternFiles.ReadUniverse(mc).Universe,
                    HashLife.Load(System.Text.Encoding.ASCII.GetBytes(rle)),
                })
                {
                    Assert.Equal(u.Rule, again.Rule);
                    Assert.Equal(new BigInteger(generation), again.Generation);
                    Assert.Equal(u.BackgroundAlive, again.BackgroundAlive);
                    Assert.Equal(mc, again.ToMacrocell());
                }
                foreach (string name in new[] { "a.mc", "a.mc.gz", "a.rle" })
                    Assert.Equal(mc, HashLife.Load(u.EncodeFile(name)).ToMacrocell());
                var host = new HashLife();
                PatternSnapshot found = host.ReadSnapshot(mc);
                Assert.Equal(u.Rule, found.Rule);
                host.Rule = found.Rule;
                host.Restore(found.Snapshot);
                Assert.Equal(mc, host.ToMacrocell());
            }
        }

        [Fact]
        public void ATimelineOfAlternatingPhasesRoundTrips()
        {
            HashLife u = SoupUniverse("B03/S23", 17, 8);
            var frames = new List<HashLifeSnapshot>();
            for (int i = 0; i < 4; i++)
            {
                frames.Add(u.Snapshot());
                u.Step(3); // frames at generations 0, 3, 6, 9: both parities
            }
            MacrocellTimeline timeline = Macrocell.ReadTimeline(Macrocell.WriteTimeline(u, frames));
            Assert.Equal(
                new BigInteger[] { 0, 3, 6, 9 },
                timeline.Frames.Select(f => f.Generation).ToArray());
            for (int i = 0; i < 4; i++)
            {
                timeline.Universe.Restore(timeline.Frames[i]);
                u.Restore(frames[i]);
                Assert.Equal(u.ToMacrocell(), timeline.Universe.ToMacrocell());
                Assert.Equal(!timeline.Frames[i].Generation.IsEven, timeline.Universe.BackgroundAlive);
            }
        }

        [Fact]
        public void AB0MacrocellFileMeasuresAndReadsIntoAGrid()
        {
            var u = new HashLife("B0123478/S01234678");
            u.SetRect(3, -4, Glider, 3, 3);
            string mc = u.ToMacrocell();
            PatternExtent extent = PatternFiles.Measure(mc);
            Assert.Equal(
                (new BigInteger(3), new BigInteger(-4), new BigInteger(3), new BigInteger(3)),
                (extent.X, extent.Y, extent.Width, extent.Height));
            Assert.Equal("B0123478/S01234678", extent.Rule);
            Assert.True(extent.TwoState);
            PatternFile grid = PatternFiles.Read(mc);
            Assert.Equal(Glider, grid.Cells); // the cells as written
            Assert.Equal("B0123478/S01234678", grid.Rule);
        }

        [Fact]
        public void FramesShowTheUniversesCells()
        {
            var u = new HashLife("B0/S");
            u.SetCell(0, 0, true);
            u.Step(1); // the background is alive; the universe holds the dead block's nine cells
            byte[] frame = u.Frame(5, 5, new LifeView(-2, -3, 0));
            Assert.Equal(9 * 255, frame.Sum(v => v));
            for (int y = 1; y < 4; y++)
                for (int x = 1; x < 4; x++)
                    Assert.Equal(255, frame[y * 5 + x]);
        }
    }
}
