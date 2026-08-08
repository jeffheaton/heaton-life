using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Replays the shared conformance vectors in ../../vectors/lifelike — the same
    /// files the Python suite replays. Bit-exact tier: grids must match exactly.
    /// </summary>
    public class ConformanceTests
    {
        public static IEnumerable<object[]> LifelikeCases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(VectorRoot(), "lifelike")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(LifelikeCases))]
        public void LifelikeVector(string caseName)
        {
            string caseDir = Path.Combine(VectorRoot(), "lifelike", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            var p = root.GetProperty("params");

            var sim = new LifeLike(
                p.GetProperty("rule").GetString()!,
                p.GetProperty("width").GetInt32(),
                p.GetProperty("height").GetInt32(),
                p.GetProperty("boundary").GetString() == "dead" ? Boundary.Dead : Boundary.Torus);

            var checkpoints = root.GetProperty("checkpoints");
            string init = p.GetProperty("init").GetString()!;
            if (init == "array")
            {
                string first = checkpoints[0].GetProperty("file").GetString()!;
                sim.SetState(LoadState(Path.Combine(caseDir, first)));
            }
            else if (init == "soup")
            {
                sim.SeedSoup(
                    p.GetProperty("density").GetDouble(),
                    (uint)p.GetProperty("seed").GetInt64());
            }
            else
            {
                throw new InvalidDataException($"unsupported init '{init}' in {caseName}");
            }

            int current = 0;
            foreach (var checkpoint in checkpoints.EnumerateArray())
            {
                int step = checkpoint.GetProperty("step").GetInt32();
                string file = checkpoint.GetProperty("file").GetString()!;
                sim.Step(step - current);
                current = step;
                byte[] expected = LoadState(Path.Combine(caseDir, file));
                Assert.True(
                    sim.State.SequenceEqual(expected),
                    $"{caseName}: state mismatch at step {step}");
            }
        }

        /// <summary>Vector PNGs for lifelike store pixel = state * 255.</summary>
        private static byte[] LoadState(string path)
        {
            var (_, _, pixels) = PngGray.Read(path);
            var state = new byte[pixels.Length];
            for (int i = 0; i < pixels.Length; i++)
                state[i] = (byte)(pixels[i] > 0 ? 1 : 0);
            return state;
        }

        private static string VectorRoot()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null)
            {
                string candidate = Path.Combine(dir.FullName, "vectors");
                if (Directory.Exists(candidate))
                    return candidate;
                dir = dir.Parent;
            }
            throw new DirectoryNotFoundException("could not locate the repo vectors/ directory");
        }
    }
}
