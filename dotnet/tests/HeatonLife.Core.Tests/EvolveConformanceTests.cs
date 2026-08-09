using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Evolve conformance: replay vectors/evolve/ — objective stats per seeded run,
    /// GA operator sequences, and one end-to-end mini evolution run. Bit-exact tier;
    /// the same files the Python suite replays (spec/evolve.md).
    /// </summary>
    public class EvolveConformanceTests
    {
        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "evolve")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), "evolve", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string kind = root.GetProperty("kind").GetString()!;
            var p = root.GetProperty("params");
            switch (kind)
            {
                case "objective":
                    RunObjective(caseDir, root, p);
                    break;
                case "operators":
                    RunOperators(root, p);
                    break;
                case "run":
                    RunMiniEvolution(caseDir, root, p);
                    break;
                default:
                    throw new InvalidDataException($"unknown evolve kind '{kind}'");
            }
        }

        private static void RunObjective(string caseDir, JsonElement root, JsonElement p)
        {
            Assert.Equal("paper", p.GetProperty("objective").GetString());
            string genome = p.GetProperty("genome").GetString()!;
            int width = p.GetProperty("width").GetInt32();
            int height = p.GetProperty("height").GetInt32();
            int cycles = p.GetProperty("cycles").GetInt32();
            ulong seed = p.GetProperty("seed").GetUInt64();
            int maxSteps = p.GetProperty("max_steps").GetInt32();

            var outputs = root.GetProperty("outputs");
            double[] expectedRuns = ReadF64(
                Path.Combine(caseDir, outputs.GetProperty("runs").GetProperty("file").GetString()!));
            Assert.Equal(cycles * 6, expectedRuns.Length);

            double maxScore = double.NegativeInfinity;
            double totalSteps = 0;
            for (int i = 0; i < cycles; i++)
            {
                var stats = MergeLifeObjective.RunOnce(genome, width, height, seed + (ulong)i, maxSteps);
                double score = MergeLifeObjective.ScoreStats(stats, MergeLifeObjective.PaperObjective);
                double[] row =
                {
                    stats.Steps, stats.Foreground, stats.Active, stats.Rect, stats.Mage, score,
                };
                for (int c = 0; c < 6; c++)
                    Assert.True(
                        row[c].Equals(expectedRuns[i * 6 + c]),
                        $"cycle {i} column {c}: {row[c]:R} != {expectedRuns[i * 6 + c]:R}");
                maxScore = Math.Max(maxScore, score);
                totalSteps += stats.Steps;
            }
            double[] expectedScore = ReadF64(
                Path.Combine(caseDir, outputs.GetProperty("score").GetProperty("file").GetString()!));
            Assert.Equal(expectedScore[0], maxScore);
            Assert.Equal(expectedScore[1], totalSteps);

            // The public entry point agrees with the per-cycle replay.
            var (score2, steps2) = MergeLifeObjective.ScoreGenome(
                genome, MergeLifeObjective.PaperObjective, cycles, width, height, seed, maxSteps);
            Assert.Equal(maxScore, score2);
            Assert.Equal(totalSteps, steps2);
        }

        private static void RunOperators(JsonElement root, JsonElement p)
        {
            var expected = root.GetProperty("expected");
            string genome = p.GetProperty("genome").GetString()!;

            var rng = new Pcg32(p.GetProperty("mutate_seed").GetUInt64());
            string current = genome;
            foreach (var m in expected.GetProperty("mutations").EnumerateArray())
            {
                current = GaOperators.Mutate(current, rng);
                Assert.Equal(m.GetString(), current);
            }

            rng = new Pcg32(p.GetProperty("crossover_seed").GetUInt64());
            string parent2 = p.GetProperty("parent2").GetString()!;
            foreach (var pair in expected.GetProperty("crossovers").EnumerateArray())
            {
                var (first, second) = GaOperators.Crossover(genome, parent2, rng);
                Assert.Equal(pair[0].GetString(), first);
                Assert.Equal(pair[1].GetString(), second);
            }

            rng = new Pcg32(p.GetProperty("tournament_seed").GetUInt64());
            int rounds = p.GetProperty("tournament_rounds").GetInt32();
            var scores = new List<double>();
            foreach (var s in p.GetProperty("tournament_scores").EnumerateArray())
                scores.Add(s.GetDouble());
            foreach (var winner in expected.GetProperty("winners_best").EnumerateArray())
                Assert.Equal(winner.GetInt32(), GaOperators.TournamentSelect(scores, rounds, rng));
            foreach (var winner in expected.GetProperty("winners_worst").EnumerateArray())
                Assert.Equal(
                    winner.GetInt32(), GaOperators.TournamentSelect(scores, rounds, rng, worst: true));
        }

        private static void RunMiniEvolution(string caseDir, JsonElement root, JsonElement p)
        {
            Assert.Equal("paper", p.GetProperty("objective").GetString());
            var evolver = new Evolver(
                p.GetProperty("width").GetInt32(),
                p.GetProperty("height").GetInt32(),
                p.GetProperty("population_size").GetInt32(),
                p.GetProperty("crossover_rate").GetDouble(),
                p.GetProperty("tournament_rounds").GetInt32(),
                p.GetProperty("eval_cycles").GetInt32(),
                p.GetProperty("patience").GetInt32(),
                p.GetProperty("max_steps").GetInt32(),
                p.GetProperty("seed").GetUInt64());
            var best = evolver.Run(p.GetProperty("max_evals").GetInt32());

            var expected = root.GetProperty("expected");
            Assert.Equal(expected.GetProperty("best_genome").GetString(), best.Genome);
            Assert.Equal(expected.GetProperty("evals").GetInt32(), evolver.Evals);
            var expectedPopulation = expected.GetProperty("population");
            Assert.Equal(expectedPopulation.GetArrayLength(), evolver.Population.Count);
            for (int i = 0; i < evolver.Population.Count; i++)
                Assert.Equal(expectedPopulation[i].GetString(), evolver.Population[i].Genome);
            double[] expectedBest = ReadF64(
                Path.Combine(
                    caseDir,
                    expected.GetProperty("best_score").GetProperty("file").GetString()!));
            Assert.Equal(expectedBest[0], best.Score);
        }

        private static double[] ReadF64(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            var values = new double[bytes.Length / 8];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
        }
    }
}
