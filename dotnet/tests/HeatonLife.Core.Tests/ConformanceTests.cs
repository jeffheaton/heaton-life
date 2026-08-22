using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Replays the shared conformance vectors in ../../vectors/ — the same files the
    /// Python suite replays. One codec per family, mirroring the Python side's
    /// conformance.py. Bit-exact families must match byte-for-byte; epsilon families
    /// must stay within the max absolute deviation declared in the vector's params.json.
    /// </summary>
    public class ConformanceTests
    {
        /// <summary>Bit-exact families the C# port implements; cases are auto-discovered.</summary>
        private static readonly string[] ByteFamilies =
            { "lifelike", "elementary", "cyclic", "wireworld", "mergelife" };

        /// <summary>ε-tier (float64) families the C# port implements.</summary>
        private static readonly string[] FloatFamilies =
            { "grayscott", "lenia-classic", "lenia-asymptotic", "lenia-flow", "boids" };

        public static IEnumerable<object[]> Cases()
        {
            foreach (string family in ByteFamilies)
                foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), family)))
                    yield return new object[] { family, Path.GetFileName(dir) };
            foreach (string family in FloatFamilies)
                foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), family)))
                    yield return new object[] { family, Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string family, string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), family, caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            string tier = root.GetProperty("tier").GetString()!;
            if (tier == "bit-exact")
                RunBitExact(family, caseName, caseDir, root);
            else if (tier == "epsilon")
                RunEpsilon(family, caseName, caseDir, root);
            else
                throw new InvalidDataException($"unknown tier '{tier}' in {family}/{caseName}");
        }

        private static void RunBitExact(string family, string caseName, string caseDir, JsonElement root)
        {
            var p = root.GetProperty("params");
            var checkpoints = root.GetProperty("checkpoints");

            byte[]? initial = null;
            if (p.GetProperty("init").GetString() == "array")
            {
                string first = checkpoints[0].GetProperty("file").GetString()!;
                initial = DecodeState(family, Path.Combine(caseDir, first));
            }
            var sim = BuildSim(family, p, initial);

            int current = 0;
            foreach (var checkpoint in checkpoints.EnumerateArray())
            {
                int step = checkpoint.GetProperty("step").GetInt32();
                string file = checkpoint.GetProperty("file").GetString()!;
                sim.Step(step - current);
                current = step;
                byte[] expected = DecodeState(family, Path.Combine(caseDir, file));
                byte[] actual = sim.State();
                Assert.True(
                    actual.AsSpan().SequenceEqual(expected),
                    $"{family}/{caseName}: state mismatch at step {step}");
            }
        }

        private static void RunEpsilon(string family, string caseName, string caseDir, JsonElement root)
        {
            double epsilon = root.GetProperty("epsilon").GetDouble();
            var p = root.GetProperty("params");
            var sim = BuildFloatSim(family, p);

            int current = 0;
            foreach (var checkpoint in root.GetProperty("checkpoints").EnumerateArray())
            {
                int step = checkpoint.GetProperty("step").GetInt32();
                string file = checkpoint.GetProperty("file").GetString()!;
                long expectedLength = 1;
                foreach (var dim in checkpoint.GetProperty("shape").EnumerateArray())
                    expectedLength *= dim.GetInt64();
                sim.Step(step - current);
                current = step;
                double[] expected = ReadF64(Path.Combine(caseDir, file));
                Assert.Equal(expectedLength, expected.Length);
                double[] actual = sim.State();
                Assert.Equal(expected.Length, actual.Length);
                double maxDiff = 0;
                int argMax = -1;
                for (int i = 0; i < expected.Length; i++)
                {
                    double diff = Math.Abs(actual[i] - expected[i]);
                    if (diff > maxDiff)
                    {
                        maxDiff = diff;
                        argMax = i;
                    }
                }
                Assert.True(
                    maxDiff <= epsilon,
                    $"{family}/{caseName}: max |Δ| = {maxDiff:g3} at flat index {argMax} " +
                    $"(step {step}, ε = {epsilon:g1})");
            }
        }

        /// <summary>Raw little-endian float64, the ε-tier checkpoint encoding.</summary>
        private static double[] ReadF64(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            if (!BitConverter.IsLittleEndian)
                throw new PlatformNotSupportedException("vector .f64 files are little-endian");
            var values = new double[bytes.Length / 8];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
        }

        private sealed class Sim
        {
            public Sim(Action<int> step, Func<byte[]> state)
            {
                Step = step;
                State = state;
            }

            public Action<int> Step { get; }
            public Func<byte[]> State { get; }
        }

        private sealed class FloatSim
        {
            public FloatSim(Action<int> step, Func<double[]> state)
            {
                Step = step;
                State = state;
            }

            public Action<int> Step { get; }
            public Func<double[]> State { get; }
        }

        /// <summary>Rebuild an ε-tier simulation from a vector's params (float families always rebuild; no array init).</summary>
        private static FloatSim BuildFloatSim(string family, JsonElement p)
        {
            string init = p.GetProperty("init").GetString()!;
            int width = p.GetProperty("width").GetInt32();
            int height = p.GetProperty("height").GetInt32();
            switch (family)
            {
                case "grayscott":
                    {
                        var sim = new GrayScott(
                            width,
                            height,
                            p.GetProperty("du").GetDouble(),
                            p.GetProperty("dv").GetDouble(),
                            p.GetProperty("feed").GetDouble(),
                            p.GetProperty("kill").GetDouble(),
                            p.GetProperty("dt").GetDouble());
                        if (init == "spots")
                            sim.SeedSpots(p.GetProperty("spots").GetInt32(), p.GetProperty("seed").GetUInt32());
                        else if (init == "center")
                            sim.SeedCenter();
                        else
                            throw new InvalidDataException($"unsupported grayscott init '{init}'");
                        return new FloatSim(sim.Step, () => sim.State.ToArray());
                    }
                case "lenia-classic":
                case "lenia-asymptotic":
                case "lenia-flow":
                    {
                        int radius = p.GetProperty("radius").GetInt32();
                        double mu = p.GetProperty("mu").GetDouble();
                        double sigma = p.GetProperty("sigma").GetDouble();
                        double dt = p.GetProperty("dt").GetDouble();
                        LeniaBase sim = family switch
                        {
                            "lenia-classic" => new ClassicLenia(width, height, radius, mu, sigma, dt),
                            "lenia-asymptotic" => new AsymptoticLenia(width, height, radius, mu, sigma, dt),
                            _ => new FlowLenia(
                                width, height, radius, mu, sigma, dt, p.GetProperty("theta").GetDouble()),
                        };
                        if (init == "blobs")
                            sim.SeedBlobs(p.GetProperty("blobs").GetInt32(), p.GetProperty("seed").GetUInt32());
                        else if (init == "soup")
                            sim.SeedSoup(p.GetProperty("density").GetDouble(), p.GetProperty("seed").GetUInt32());
                        else
                            throw new InvalidDataException($"unsupported lenia init '{init}'");
                        return new FloatSim(sim.Step, () => sim.State.ToArray());
                    }
                case "boids":
                    {
                        var sim = new Boids(
                            p.GetProperty("count").GetInt32(),
                            width,
                            height,
                            p.GetProperty("perception").GetDouble(),
                            p.GetProperty("separation_radius").GetDouble(),
                            p.GetProperty("w_separation").GetDouble(),
                            p.GetProperty("w_alignment").GetDouble(),
                            p.GetProperty("w_cohesion").GetDouble(),
                            p.GetProperty("max_speed").GetDouble(),
                            p.GetProperty("min_speed").GetDouble(),
                            p.GetProperty("max_force").GetDouble(),
                            p.GetProperty("boundary").GetString() == "bounce"
                                ? BoidsBoundary.Bounce
                                : BoidsBoundary.Wrap,
                            // Older 2D cases predate these keys.
                            p.TryGetProperty("dimensions", out var dims) ? dims.GetInt32() : 2,
                            p.TryGetProperty("depth", out var boidsDepth) ? boidsDepth.GetInt32() : 256);
                        if (init == "random")
                            sim.SeedRandom(p.GetProperty("seed").GetUInt32());
                        else
                            throw new InvalidDataException($"unsupported boids init '{init}'");
                        return new FloatSim(sim.Step, () => sim.State.ToArray());
                    }
                default:
                    throw new InvalidDataException($"no float builder for family '{family}'");
            }
        }

        /// <summary>Vector file -> state bytes, per-family encoding (see conformance.py).</summary>
        private static byte[] DecodeState(string family, string path)
        {
            var (width, _, channels, pixels) = Png.Read(path);
            int expectedChannels = family == "mergelife" ? 3 : 1;
            Assert.Equal(expectedChannels, channels);
            switch (family)
            {
                case "lifelike": // pixel = state * 255
                    {
                        var state = new byte[pixels.Length];
                        for (int i = 0; i < pixels.Length; i++)
                            state[i] = (byte)(pixels[i] > 0 ? 1 : 0);
                        return state;
                    }
                case "elementary": // 1 x width, pixel = tape * 255
                    {
                        var state = new byte[width];
                        for (int i = 0; i < width; i++)
                            state[i] = (byte)(pixels[i] > 0 ? 1 : 0);
                        return state;
                    }
                case "cyclic": // pixel = raw state
                    return pixels;
                case "wireworld": // pixel = state * 85
                    {
                        var state = new byte[pixels.Length];
                        for (int i = 0; i < pixels.Length; i++)
                            state[i] = (byte)(pixels[i] / 85);
                        return state;
                    }
                case "mergelife": // RGB, raw bytes
                    return pixels;
                default:
                    throw new InvalidDataException($"no codec for family '{family}'");
            }
        }

        /// <summary>Rebuild the simulation from a vector's params, mirroring conformance.build_sim.</summary>
        private static Sim BuildSim(string family, JsonElement p, byte[]? initial)
        {
            string init = p.GetProperty("init").GetString()!;
            int width = p.GetProperty("width").GetInt32();
            int height = p.GetProperty("height").GetInt32();
            switch (family)
            {
                case "lifelike":
                    {
                        var sim = new LifeLike(
                            p.GetProperty("rule").GetString()!, width, height, ParseBoundary(p));
                        if (initial != null)
                            sim.SetState(initial);
                        else if (init == "soup")
                            sim.SeedSoup(p.GetProperty("density").GetDouble(), p.GetProperty("seed").GetUInt32());
                        else if (init == "blob")
                            sim.SeedBlob(p.GetProperty("density").GetDouble(), p.GetProperty("seed").GetUInt32());
                        else if (init == "single")
                            sim.SeedSingle();
                        else
                            throw new InvalidDataException($"unsupported lifelike init '{init}'");
                        return new Sim(sim.Step, () => sim.State.ToArray());
                    }
                case "elementary":
                    {
                        var sim = new Elementary(
                            p.GetProperty("rule").GetInt32(), width, height, ParseBoundary(p));
                        if (initial != null)
                            sim.SetState(initial);
                        else if (init == "single")
                            sim.SeedSingle();
                        else if (init == "soup")
                            sim.SeedSoup(p.GetProperty("density").GetDouble(), p.GetProperty("seed").GetUInt32());
                        else
                            throw new InvalidDataException($"unsupported elementary init '{init}'");
                        return new Sim(sim.Step, () => sim.State.ToArray());
                    }
                case "cyclic":
                    {
                        var sim = new Cyclic(
                            p.GetProperty("states").GetInt32(),
                            width,
                            height,
                            p.GetProperty("threshold").GetInt32(),
                            p.GetProperty("reach").GetInt32(),
                            p.GetProperty("neighborhood").GetString() == "vonneumann"
                                ? Neighborhood.VonNeumann
                                : Neighborhood.Moore);
                        if (initial != null)
                            sim.SetState(initial);
                        else if (init == "soup")
                            sim.SeedSoup(p.GetProperty("seed").GetUInt32());
                        else
                            throw new InvalidDataException($"unsupported cyclic init '{init}'");
                        return new Sim(sim.Step, () => sim.State.ToArray());
                    }
                case "wireworld":
                    {
                        var sim = new Wireworld(width, height, ParseBoundary(p));
                        if (initial != null)
                            sim.SetState(initial);
                        else if (init == "clock")
                            sim.SeedClock();
                        else
                            throw new InvalidDataException($"unsupported wireworld init '{init}'");
                        return new Sim(sim.Step, () => sim.State.ToArray());
                    }
                case "mergelife":
                    {
                        var sim = new MergeLife(p.GetProperty("genome").GetString()!, width, height);
                        if (initial != null)
                            sim.SetState(initial);
                        else if (init == "soup")
                            sim.SeedSoup(p.GetProperty("seed").GetUInt32());
                        else
                            throw new InvalidDataException($"unsupported mergelife init '{init}'");
                        return new Sim(sim.Step, () => sim.State.ToArray());
                    }
                default:
                    throw new InvalidDataException($"no builder for family '{family}'");
            }
        }

        private static Boundary ParseBoundary(JsonElement p) =>
            p.GetProperty("boundary").GetString() == "dead" ? Boundary.Dead : Boundary.Torus;
    }
}
