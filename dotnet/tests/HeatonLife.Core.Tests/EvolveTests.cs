using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace HeatonLife.Tests
{
    public class EvolveTests
    {

        /// <summary>
        /// The evolve entry points must offer the same defaults as the Python
        /// reference, where Evolver() and score_genome(genome) both work with no
        /// further arguments (evolve/ga.py, evolve/objective.py). C# required
        /// width/height and five more, so the two ports read differently for no
        /// reason. Checked by REFLECTION rather than by running an evaluation: the
        /// declared default is the contract, and a full scoring run at the default
        /// 100x100 x 5 cycles x 1000 steps is far too slow for a unit test.
        ///
        /// Parameter ORDER is deliberately NOT aligned with Python — matching it
        /// would move `objective` to first and break every caller for cosmetics.
        /// </summary>
        [Fact]
        public void EvolveEntryPointsCarryTheReferenceDefaults()
        {
            var ctor = typeof(Evolver).GetConstructors()[0];
            var expectedCtor = new Dictionary<string, object>
            {
                ["width"] = 100,
                ["height"] = 100,        // python size=(100, 100)
                ["populationSize"] = 100,
                ["crossoverRate"] = 0.75,
                ["tournamentRounds"] = 5,
                ["evalCycles"] = 5,
                ["patience"] = 1000,
                ["maxSteps"] = 1000,
                ["seed"] = 0UL,
            };
            AssertDefaults(ctor.GetParameters(), expectedCtor, "Evolver(..)");

            var score = typeof(MergeLifeObjective).GetMethod(nameof(MergeLifeObjective.ScoreGenome));
            var expectedScore = new Dictionary<string, object>
            {
                ["cycles"] = 5,
                ["width"] = 100,
                ["height"] = 100,
                ["seed"] = 0UL,
                ["maxSteps"] = 1000,
            };
            AssertDefaults(score!.GetParameters(), expectedScore, "ScoreGenome(..)");

            // Only the genome is required, exactly as in Python.
            foreach (var p in score.GetParameters())
                if (p.Name != "genome")
                    Assert.True(p.IsOptional, $"ScoreGenome({p.Name}) should be optional");
        }

        private static void AssertDefaults(
            System.Reflection.ParameterInfo[] parameters,
            Dictionary<string, object> expected,
            string what)
        {
            foreach (var p in parameters)
            {
                if (!expected.TryGetValue(p.Name!, out object? want))
                    continue;
                Assert.True(p.IsOptional, $"{what}: {p.Name} should have a default");
                Assert.Equal(want, p.DefaultValue);
                expected.Remove(p.Name!);
            }
            Assert.True(expected.Count == 0, $"{what}: never saw {string.Join(", ", expected.Keys)}");
        }

        private const string RedWorld = "e542-5f79-9341-f31e-6c6b-7f08-8773-7068";

        [Fact]
        public void LargestRectangleKnownCases()
        {
            bool[] mask =
            {
                true, true, true,
                true, true, false,
                true, false, false,
            };
            Assert.Equal(4, MergeLifeObjective.LargestRectangleArea(mask, 3, 3)); // 2x2 top-left
            Assert.Equal(15, MergeLifeObjective.LargestRectangleArea(
                Enumerable.Repeat(true, 15).ToArray(), 5, 3));
            Assert.Equal(0, MergeLifeObjective.LargestRectangleArea(new bool[15], 5, 3));
            bool[] ragged =
            {
                true, false, true, true, true,
                true, true, true, true, false,
                false, true, true, true, false,
            };
            Assert.Equal(6, MergeLifeObjective.LargestRectangleArea(ragged, 5, 3));
        }

        [Fact]
        public void LargestRectangleMatchesBruteForce()
        {
            var rng = new Pcg32(1);
            const int h = 7, w = 9;
            for (int trial = 0; trial < 20; trial++)
            {
                var mask = new bool[h * w];
                for (int i = 0; i < mask.Length; i++)
                    mask[i] = rng.NextU32() / 4294967296.0 < 0.6;

                int brute = 0;
                for (int y0 = 0; y0 < h; y0++)
                    for (int y1 = y0; y1 < h; y1++)
                        for (int x0 = 0; x0 < w; x0++)
                            for (int x1 = x0; x1 < w; x1++)
                            {
                                bool all = true;
                                for (int y = y0; y <= y1 && all; y++)
                                    for (int x = x0; x <= x1 && all; x++)
                                        all = mask[y * w + x];
                                if (all)
                                    brute = Math.Max(brute, (y1 - y0 + 1) * (x1 - x0 + 1));
                            }
                Assert.Equal(brute, MergeLifeObjective.LargestRectangleArea(mask, w, h));
            }
        }

        [Fact]
        public void MutateIsADigitSwap()
        {
            var rng = new Pcg32(7);
            string child = GaOperators.Mutate(RedWorld, rng);
            Assert.NotEqual(RedWorld, child);
            Assert.Equal(RedWorld.OrderBy(c => c), child.OrderBy(c => c)); // permutation
            for (int i = 0; i < RedWorld.Length; i++)
                Assert.Equal(RedWorld[i] == '-', child[i] == '-'); // dashes must not move
        }

        [Fact]
        public void MutateDegenerateGenomeUnchanged()
        {
            const string flat = "0000-0000-0000-0000-0000-0000-0000-0000";
            Assert.Equal(flat, GaOperators.Mutate(flat, new Pcg32(1)));
        }

        [Fact]
        public void CrossoverChildrenAreComplementarySplices()
        {
            const string other = "a07f-c000-0000-0000-0000-0000-ff80-807f";
            var (first, second) = GaOperators.Crossover(RedWorld, other, new Pcg32(3));
            Assert.Equal(RedWorld.Length, first.Length);
            Assert.Equal(RedWorld.Length, second.Length);
            // Each position comes from one parent in first and the other in second.
            for (int i = 0; i < first.Length; i++)
            {
                bool fromP1 = first[i] == RedWorld[i];
                bool fromP2 = second[i] == other[i];
                Assert.True(fromP1 == fromP2 || RedWorld[i] == other[i]);
            }
        }

        [Fact]
        public void TournamentPrefersExtremes()
        {
            var scores = new double[] { -5.0, 10.0, 0.0 };
            var rng = new Pcg32(2);
            int bestWins = 0, worstWins = 0;
            for (int i = 0; i < 50; i++)
            {
                if (GaOperators.TournamentSelect(scores, 3, rng) == 1)
                    bestWins++;
                if (GaOperators.TournamentSelect(scores, 3, rng, worst: true) == 0)
                    worstWins++;
            }
            // P(extreme wins best-of-3 uniform draws) = 1 - (2/3)^3 ≈ 0.70
            Assert.True(bestWins > 25, $"best-of-3 should usually pick the max ({bestWins}/50)");
            Assert.True(worstWins > 25, $"worst-of-3 should usually pick the min ({worstWins}/50)");
        }

        [Fact]
        public void ScoreGenomeIsDeterministic()
        {
            var a = MergeLifeObjective.ScoreGenome(
                RedWorld, MergeLifeObjective.PaperObjective, 2, 32, 32, 5, 200);
            var b = MergeLifeObjective.ScoreGenome(
                RedWorld, MergeLifeObjective.PaperObjective, 2, 32, 32, 5, 200);
            Assert.Equal(a.Score, b.Score);
            Assert.Equal(a.TimeStep, b.TimeStep);
        }
    }
}
