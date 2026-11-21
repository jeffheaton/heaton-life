using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The rule model (spec/rules.md): the letter classes against facts LifeWiki publishes, the
    /// canonical form, the neighborhoods, MAP strings, and the legacy counts API. The Python
    /// suite's tests/test_rulestring.py, test for test.
    /// </summary>
    public class RuleStringTests
    {
        private const string Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

        /// <summary>Every letter class as the neighbor arrangements it holds, from one-class rules.</summary>
        private static Dictionary<string, HashSet<int>> Classes()
        {
            var classes = new Dictionary<string, HashSet<int>>();
            for (int n = 0; n <= 8; n++)
            {
                string letters = n > 0 && n < 8 ? "cekainyqjrtwz" : " ";
                foreach (char letter in letters)
                {
                    string name = letter == ' ' ? $"{n}" : $"{n}{letter}";
                    if (!RuleString.TryCompile($"B{name}/S", out LifeRule? rule))
                        continue;
                    var members = new HashSet<int>();
                    for (int i = 0; i < LifeRule.TableSize; i++)
                        if (rule.Table[i] != 0)
                            members.Add(i);
                    classes[name] = members;
                }
            }
            return classes;
        }

        private static int Bits(int v)
        {
            int count = 0;
            for (; v != 0; v &= v - 1)
                count++;
            return count;
        }

        [Fact]
        public void LetterClassesDivideTheArrangements()
        {
            Dictionary<string, HashSet<int>> classes = Classes();
            Assert.Equal(51, classes.Count);
            var seen = new HashSet<int>();
            foreach (var (name, members) in classes)
            {
                Assert.False(seen.Overlaps(members), name);
                seen.UnionWith(members);
                Assert.All(members, m => Assert.True(Bits(m) == name[0] - '0' && (m & 16) == 0, name));
            }
            Assert.Equal(256, seen.Count);
        }

        [Fact]
        public void LetterClassesAreClosedUnderTheSquaresSymmetries()
        {
            static int Turn(int m) // a quarter turn: NW->NE->SE->SW, N->E->S->W
            {
                int[][] rings = { new[] { 256, 64, 1, 4 }, new[] { 128, 8, 2, 32 } };
                int result = 0;
                foreach (int[] ring in rings)
                    for (int k = 0; k < 4; k++)
                        if ((m & ring[k]) != 0)
                            result |= ring[(k + 1) % 4];
                return result;
            }

            static int Mirror(int m) // left-right: NW<->NE, W<->E, SW<->SE
            {
                int result = m & (128 | 2);
                foreach (var (a, b) in new[] { (256, 64), (32, 8), (4, 1) })
                    result |= ((m & a) != 0 ? b : 0) | ((m & b) != 0 ? a : 0);
                return result;
            }

            foreach (var (name, members) in Classes())
            {
                Assert.True(members.SetEquals(members.Select(Turn)), name);
                Assert.True(members.SetEquals(members.Select(Mirror)), name);
            }
        }

        [Fact]
        public void HighCountsAreComplementsAndFourPairsUpAsPublished()
        {
            Dictionary<string, HashSet<int>> classes = Classes();
            HashSet<int> Flipped(string name) => new HashSet<int>(classes[name].Select(m => m ^ 0x1EF));
            foreach (string name in classes.Keys)
            {
                int n = name[0] - '0';
                if (n != 4)
                    Assert.True(Flipped(name).SetEquals(classes[$"{8 - n}{name.Substring(1)}"]), name);
            }
            // LifeWiki's black/white reversal table pairs the count-4 classes like this.
            foreach (string pair in new[] { "ce", "it", "nr", "yj", "qw", "kk", "aa", "zz" })
                Assert.True(Flipped($"4{pair[0]}").SetEquals(classes[$"4{pair[1]}"]), pair);
        }

        [Fact]
        public void VonNeumannClassesMatchThePublishedEquivalences()
        {
            // LifeWiki "von Neumann emulation": the classes that look alike to N, W, E, S alone.
            var groups = new Dictionary<string, string>
            {
                ["0"] = "0 1c 2n 2c 3c 4c",
                ["1"] = "1e 2a 2k 3i 3n 3y 3q 4n 4y 5e",
                ["2e"] = "2e 3k 3a 3j 4k 4a 4q 4w 5a 5j 5k 6e",
                ["2i"] = "2i 3r 4i 4t 4z 5r 6i",
                ["3"] = "3e 4j 4r 5i 5n 5y 5q 6a 6k 7e",
                ["4"] = "4e 5c 6c 6n 7c 8",
            };
            Dictionary<string, HashSet<int>> classes = Classes();

            static string Orthogonal(int m)
            {
                bool n = (m & 128) != 0, w = (m & 32) != 0, e = (m & 8) != 0, s = (m & 2) != 0;
                int count = (n ? 1 : 0) + (w ? 1 : 0) + (e ? 1 : 0) + (s ? 1 : 0);
                if (count == 2)
                    return (n && s) || (w && e) ? "2i" : "2e";
                return count.ToString(System.Globalization.CultureInfo.InvariantCulture);
            }

            var listed = new List<string>();
            foreach (var (group, names) in groups)
            {
                foreach (string name in names.Split(' '))
                {
                    listed.Add(name);
                    Assert.True(classes[name].All(m => Orthogonal(m) == group), name);
                }
            }
            Assert.Equal(classes.Keys.OrderBy(k => k, StringComparer.Ordinal), listed.OrderBy(k => k, StringComparer.Ordinal));
        }

        [Fact]
        public void AVonNeumannRuleIsItsPublishedIsotropicTwin()
        {
            Assert.True(RuleString.Compile("B1/SV").Table.SequenceEqual(RuleString.Compile("B1e2ak3inqy4ny5e/S").Table));
        }

        [Theory]
        [InlineData("B3/S2-i34q", "B3/S2-i34q")]
        [InlineData("B2-a/S12", "B2-a/S12")]
        [InlineData("B2ci3ai4c8/S02ae3eijkq4iz5ar6i7e", "B2ci3ai4c8/S02ae3eijkq4iz5ar6i7e")]
        [InlineData("b2cekin/s12", "B2-a/S12")]
        [InlineData("B2CEKIN/S12", "B2-a/S12")]
        [InlineData("B4-eijryz/S", "B4acknqtw/S")] // eight characters either way: the letters win
        [InlineData("B1-c/S", "B1e/S")]
        [InlineData("B2a2c/S", "B2ac/S")]
        [InlineData("B2-a2a/S", "B2/S")]
        [InlineData("B2-cekain/S", "B/S")]
        [InlineData("B3a2c/S", "B2c3a/S")]
        [InlineData("b2 / s34h", "B2/S34H")]
        [InlineData("B1/sv", "B1/SV")]
        [InlineData("B33/S233", "B3/S23")]
        public void CanonicalForms(string text, string canonical)
        {
            Assert.Equal(canonical, RuleString.Canonical(text));
            Assert.Equal(canonical, RuleString.Canonical(canonical));
        }

        [Fact]
        public void WhitespaceIsTheSpecsList()
        {
            Assert.Equal("B3/S23", RuleString.Canonical((char)0xA0 + "B3/S23" + (char)0x3000));
            Assert.Equal("B3/S23", RuleString.Canonical("B3" + (char)0x2028 + "/" + (char)0x85 + "S23"));
            foreach (int space in new[] { 0x200B, 0x1C, 0x180E })
                Assert.Throws<ArgumentException>(() => RuleString.Compile((char)space + "B3/S23"));
        }

        [Fact]
        public void OnlyAsciiSpellsARule()
        {
            foreach (string text in new[] { "B" + (char)0x663 + "/S23", (char)0xFF22 + "3/S23", "B2" + (char)0x212A + "/S" })
                Assert.Throws<ArgumentException>(() => RuleString.Compile(text));
        }

        [Fact]
        public void NeighborhoodsIgnoreTheCellsTheyLack()
        {
            ReadOnlySpan<byte> hexagonal = RuleString.Compile("B2/S34H").Table;
            ReadOnlySpan<byte> vonNeumann = RuleString.Compile("B2/S013V").Table;
            for (int i = 0; i < LifeRule.TableSize; i++)
            {
                Assert.Equal(hexagonal[i], hexagonal[i ^ 64]); // NE
                Assert.Equal(hexagonal[i], hexagonal[i ^ 4]); // SW
                foreach (int corner in new[] { 256, 64, 4, 1 })
                    Assert.Equal(vonNeumann[i], vonNeumann[i ^ corner]);
            }
            // Neither is isotropic in the square's sense: a hexagonal rule sees NW but not NE.
            Assert.NotEqual(hexagonal[256 | 128], hexagonal[64 | 128]);
            Assert.Equal(RuleNeighborhood.Hexagonal, RuleString.Compile("B2/S34H").Neighborhood);
            Assert.Equal(RuleNeighborhood.VonNeumann, RuleString.Compile("B2/S013V").Neighborhood);
        }

        private static string Map(string bits, int length = 86)
        {
            bits = bits.PadRight(length * 6, '0');
            var sb = new StringBuilder("MAP");
            for (int i = 0; i < length * 6; i += 6)
                sb.Append(Alphabet[Convert.ToInt32(bits.Substring(i, 6), 2)]);
            return sb.ToString();
        }

        private static string Bits(ReadOnlySpan<byte> table)
        {
            var sb = new StringBuilder(table.Length);
            foreach (byte b in table)
                sb.Append((char)('0' + b));
            return sb.ToString();
        }

        /// <summary>A hexagonal or von Neumann rule's own table: the Moore order of its cells.</summary>
        private static string OwnEntries(LifeRule rule)
        {
            int[] cells = rule.Neighborhood == RuleNeighborhood.Hexagonal
                ? new[] { 256, 128, 32, 16, 8, 2, 1 }
                : new[] { 128, 32, 16, 8, 2 };
            var sb = new StringBuilder();
            for (int i = 0; i < 1 << cells.Length; i++)
            {
                int index = 0;
                for (int k = 0; k < cells.Length; k++)
                    if (((i >> (cells.Length - 1 - k)) & 1) != 0)
                        index += cells[k];
                sb.Append((char)('0' + rule.Table[index]));
            }
            return sb.ToString();
        }

        [Fact]
        public void MapStringsRoundTripEveryTable()
        {
            var rng = new Pcg32(7);
            for (int trial = 0; trial < 20; trial++)
            {
                var bits = new StringBuilder();
                for (int i = 0; i < LifeRule.TableSize; i++)
                    bits.Append((char)('0' + (rng.NextU32() >> 31)));
                LifeRule rule = RuleString.Compile(Map(bits.ToString()));
                Assert.Equal(bits.ToString(), Bits(rule.Table));
                Assert.Equal(rule.Canonical, RuleString.Compile(rule.Canonical).Canonical);
                Assert.Equal(rule.Canonical, RuleString.Compile(rule.Canonical + "==").Canonical);
            }
            // Totalistic tables written as MAP strings run the same, but keep their notation.
            LifeRule life = RuleString.Compile("B3/S23");
            LifeRule asMap = RuleString.Compile(Map(Bits(life.Table)));
            Assert.True(asMap.Table.SequenceEqual(life.Table));
            Assert.StartsWith("MAP", asMap.Canonical);
            foreach (var (text, length) in new[] { ("B2/S34H", 22), ("B2/S013V", 6) })
            {
                LifeRule rule = RuleString.Compile(text);
                LifeRule twin = RuleString.Compile(Map(OwnEntries(rule), length));
                Assert.True(twin.Table.SequenceEqual(rule.Table), text);
                Assert.Equal(rule.Neighborhood, twin.Neighborhood);
            }
        }

        [Fact]
        public void ParseAnswersOnlyOuterTotalisticMooreRules()
        {
            var (birth, survive) = RuleString.Parse(Map(Bits(RuleString.Compile("B3/S23").Table)));
            Assert.Equal(new[] { false, false, false, true, false, false, false, false, false }, birth);
            Assert.Equal(new[] { false, false, true, true, false, false, false, false, false }, survive);
            var (birth2, survive2) = RuleString.Parse("B3cekainyqjr/S2cekain3");
            Assert.Equal(birth, birth2);
            Assert.Equal(survive, survive2);
            foreach (string rule in new[] { "B2-a/S12", "B2/S34H", "B/SV" })
                Assert.Contains("RuleString.Compile", Assert.Throws<ArgumentException>(() => RuleString.Parse(rule)).Message);
        }

        [Fact]
        public void B0()
        {
            Assert.True(RuleString.Compile("B03/S23").HasB0);
            Assert.True(RuleString.Compile("MAPg" + new string('A', 85)).HasB0);
            Assert.False(RuleString.Compile("B3/S23").HasB0);
            Assert.False(RuleString.TryCompile(null, out _));
        }


        [Fact]
        public void TryCompileGivesTheRuleOrTheReason()
        {
            // spec/rules.md "Reasons": no exception, and the reason is what Compile's message carries.
            Assert.True(RuleString.TryCompile("b3 / s32", out LifeRule? rule, out string? reason));
            Assert.Equal("B3/S23", rule!.Canonical);
            Assert.Null(reason);
            Assert.False(RuleString.TryCompile(null, out rule, out reason));
            Assert.Null(rule);
            Assert.Equal("expected B\u2026/S\u2026 or MAP\u2026", reason);
            foreach (string text in new[] { "B9/S23", "B3/S23 x", "B1kn/S", "B2/S7H", "MAP", "it's" })
            {
                Assert.False(RuleString.TryCompile(text, out _, out reason));
                ArgumentException thrown = Assert.Throws<ArgumentException>(() => RuleString.Compile(text));
                Assert.StartsWith($"invalid rule '{text}': {reason} (spec/rules.md)", thrown.Message);
            }
        }

        [Theory]
        [InlineData("B1a/S23 x", "unexpected ' x' after the survival counts")] // the shape comes first
        [InlineData("B7/S2aH", "the hexagonal neighborhood has 6 neighbors")] // then birth before survival
        [InlineData("B1nk/S", "n is not a letter class of 1")] // the first undefined letter as written
        [InlineData("B1Kn/S", "k is not a letter class of 1")] // in lowercase
        [InlineData("B3/S23\u200b", "unexpected '\u200b' after the survival counts")] // quoted as written
        [InlineData(" \tB3/S23 H \u3000", "unexpected ' H' after the survival counts")] // ends stripped
        public void TheReasonIsTheFirstProblemFound(string text, string reason)
        {
            Assert.False(RuleString.TryCompile(text, out _, out string? found));
            Assert.Equal(reason, found);
        }
    }
}
