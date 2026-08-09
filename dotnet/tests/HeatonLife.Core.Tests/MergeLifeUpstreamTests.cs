using System;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Replays the upstream cross-engine conformance vectors
    /// (vectors/mergelife-upstream/, from github.com/jeffheaton/mergelife). Passing them
    /// means this port is byte-identical with the reference Python/JS/Java/C engines.
    /// Per the upstream contract, the LCG and FNV-1a helpers are implemented
    /// independently here in the test harness; only the engine under test is shared code.
    /// </summary>
    public class MergeLifeUpstreamTests
    {
        public static IEnumerable<object[]> Cases()
        {
            string path = Path.Combine(TestPaths.VectorRoot(), "mergelife-upstream", "vectors.txt");
            foreach (string rawLine in File.ReadAllLines(path))
            {
                string line = rawLine.Trim();
                if (line.Length == 0 || line.StartsWith("#"))
                    continue;
                string[] parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                yield return new object[]
                {
                    parts[0], // rule
                    int.Parse(parts[1]), // rows
                    int.Parse(parts[2]), // cols
                    uint.Parse(parts[3]), // seed
                    int.Parse(parts[4]), // steps
                    parts[5], // fnv1a64 digest
                };
            }
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void UpstreamConformance(string rule, int rows, int cols, uint seed, int steps, string digest)
        {
            var sim = new MergeLife(rule, cols, rows);
            sim.SetState(LcgLattice(seed, rows, cols));
            sim.Step(steps);
            Assert.Equal(digest, Fnv1a64(sim.State));
        }

        /// <summary>Upstream spec PRNG: 32-bit LCG, one byte (state &gt;&gt; 24) per advance, row-major RGB.</summary>
        private static byte[] LcgLattice(uint seed, int rows, int cols)
        {
            uint state = seed;
            var flat = new byte[rows * cols * 3];
            for (int i = 0; i < flat.Length; i++)
            {
                state = unchecked(state * 1664525u + 1013904223u);
                flat[i] = (byte)(state >> 24);
            }
            return flat;
        }

        private static string Fnv1a64(ReadOnlySpan<byte> data)
        {
            ulong hash = 0xCBF29CE484222325UL;
            foreach (byte b in data)
            {
                hash ^= b;
                hash = unchecked(hash * 0x100000001B3UL);
            }
            return hash.ToString("x16");
        }
    }
}
