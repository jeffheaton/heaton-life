using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Render conformance: rebuild every colormap LUT and replay frame indexing, and
    /// (0.7.0) fractal color and the phase lookup, against vectors/render/ — the same
    /// files the Python suite replays. Bit-exact tier: RGB bytes must match exactly
    /// (spec/render.md, spec/fractal-color.md); float64 outputs compare by value, every
    /// NaN equal to every NaN. 0.7.0 cases are strict: an unknown key fails the case.
    /// </summary>
    public class RenderConformanceTests
    {
        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "render")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), "render", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            if (root.GetProperty("spec_version").GetString() == "0.7.0")
            {
                RunColorCase(caseName, caseDir, root);
                return;
            }
            switch (root.GetProperty("kind").GetString())
            {
                case "lut":
                    RunLut(caseName, caseDir, root);
                    break;
                case "apply":
                    RunApply(caseName, caseDir, root);
                    break;
                case "frame":
                    RunFrame(caseName, caseDir, root);
                    break;
                case "fractal-render":
                    RunFractalRender(caseName, caseDir, root);
                    break;
                case "palette":
                    RunPalette(caseName, caseDir, root);
                    break;
                case "palette-shade":
                    RunShade(caseName, caseDir, root);
                    break;
                case "window":
                    RunWindow(caseName, caseDir, root);
                    break;
                default:
                    throw new InvalidDataException($"unknown render kind in {caseName}");
            }
        }

        private static void RunLut(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string outputFile = root.GetProperty("output").GetProperty("file").GetString()!;
            var (width, height, channels, expected) = Png.Read(Path.Combine(caseDir, outputFile));
            Assert.Equal(3, channels);
            Assert.Equal(256, width * height);
            byte[] got = Colormaps.Get(root.GetProperty("cmap").GetString()!);
            Assert.True(got.AsSpan().SequenceEqual(expected), $"render/{caseName}: RGB mismatch");
        }

        private static void RunApply(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string outputFile = root.GetProperty("output").GetProperty("file").GetString()!;
            var (width, height, channels, expected) = Png.Read(Path.Combine(caseDir, outputFile));
            Assert.Equal(3, channels);
            double[] frame = ReadF64(
                Path.Combine(caseDir, root.GetProperty("input").GetProperty("file").GetString()!));
            Assert.Equal(width * height, frame.Length);
            byte[] got = Colormaps.ApplyFloat(frame, Colormaps.Get(root.GetProperty("cmap").GetString()!));
            Assert.True(got.AsSpan().SequenceEqual(expected), $"render/{caseName}: RGB mismatch");
        }

        private static void RunFrame(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            string simFamily = root.GetProperty("sim_family").GetString()!;
            var p = root.GetProperty("params");
            string inputFile = root.GetProperty("input").GetProperty("file").GetString()!;
            string outputFile = root.GetProperty("output").GetProperty("file").GetString()!;
            int width = p.GetProperty("width").GetInt32();
            int height = p.GetProperty("height").GetInt32();

            switch (simFamily)
            {
                case "lifelike":
                    {
                        var sim = new LifeLike(
                            p.GetProperty("rule").GetString()!, width, height,
                            p.GetProperty("boundary").GetString() == "dead" ? Boundary.Dead : Boundary.Torus);
                        sim.SetState(ReadGrayBinarized(Path.Combine(caseDir, inputFile)));
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "lifelike-history": // a History rule: the state PNG and the frame are the states
                    {
                        var sim = new LifeLike(
                            p.GetProperty("rule").GetString()!, width, height,
                            p.GetProperty("boundary").GetString() == "dead" ? Boundary.Dead : Boundary.Torus);
                        var (_, _, channels, pixels) = Png.Read(Path.Combine(caseDir, inputFile));
                        Assert.Equal(1, channels);
                        sim.SetState(pixels);
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "cyclic":
                    {
                        var sim = new Cyclic(
                            p.GetProperty("states").GetInt32(), width, height,
                            p.GetProperty("threshold").GetInt32(), p.GetProperty("reach").GetInt32(),
                            p.GetProperty("neighborhood").GetString() == "vonneumann"
                                ? Neighborhood.VonNeumann
                                : Neighborhood.Moore);
                        var (_, _, _, pixels) = Png.Read(Path.Combine(caseDir, inputFile));
                        sim.SetState(pixels); // cyclic encoding: raw state values
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "wireworld":
                    {
                        var (_, _, _, pixels) = Png.Read(Path.Combine(caseDir, inputFile));
                        var cells = new byte[pixels.Length];
                        for (int i = 0; i < pixels.Length; i++)
                            cells[i] = (byte)(pixels[i] / 85); // wireworld encoding: state * 85
                        var sim = new Wireworld(
                            width, height, cells,
                            p.GetProperty("boundary").GetString() == "torus" ? Boundary.Torus : Boundary.Dead);
                        AssertByteFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "grayscott":
                    {
                        var sim = new GrayScott(
                            width, height,
                            p.GetProperty("du").GetDouble(), p.GetProperty("dv").GetDouble(),
                            p.GetProperty("feed").GetDouble(), p.GetProperty("kill").GetDouble(),
                            p.GetProperty("dt").GetDouble());
                        sim.SetState(ReadF64(Path.Combine(caseDir, inputFile)));
                        AssertFloatFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                case "boids":
                    {
                        var sim = new Boids(
                            p.GetProperty("count").GetInt32(), width, height,
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
                            p.TryGetProperty("dimensions", out var dims) ? dims.GetInt32() : 2,
                            p.TryGetProperty("depth", out var boidsDepth) ? boidsDepth.GetInt32() : 256);
                        sim.SetState(ReadF64(Path.Combine(caseDir, inputFile)));
                        AssertFloatFrame(caseName, caseDir, outputFile, sim.Frame());
                        break;
                    }
                default:
                    throw new InvalidDataException($"no frame builder for '{simFamily}'");
            }
        }

        private static void RunFractalRender(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("epsilon", root.GetProperty("tier").GetString());
            double epsilon = root.GetProperty("epsilon").GetDouble();
            var p = root.GetProperty("params");
            var vp = root.GetProperty("viewport");
            var viewport = new Viewport(
                vp.GetProperty("center_re").GetString()!,
                vp.GetProperty("center_im").GetString()!,
                vp.GetProperty("zoom_log10").GetDouble());
            int width = root.GetProperty("size")[0].GetInt32();
            int height = root.GetProperty("size")[1].GetInt32();
            double[] produced = root.GetProperty("sim_family").GetString() switch
            {
                "mandelbrot" => new Mandelbrot(
                        p.GetProperty("max_iter").GetInt32(),
                        p.GetProperty("escape_radius").GetDouble())
                    .Render(width, height, viewport),
                "newton" => new Newton(
                        p.GetProperty("degree").GetInt32(),
                        p.GetProperty("max_iter").GetInt32())
                    .Render(width, height, viewport),
                "julia" => new Julia(
                        p.GetProperty("c_re").GetDouble(),
                        p.GetProperty("c_im").GetDouble(),
                        p.GetProperty("max_iter").GetInt32(),
                        p.GetProperty("escape_radius").GetDouble())
                    .Render(width, height, viewport),
                var other => throw new InvalidDataException($"no fractal-render builder for '{other}'"),
            };
            double[] expected = ReadF64(
                Path.Combine(caseDir, root.GetProperty("output").GetProperty("file").GetString()!));
            Assert.Equal(expected.Length, produced.Length);
            double maxDiff = 0;
            for (int i = 0; i < expected.Length; i++)
                maxDiff = Math.Max(maxDiff, Math.Abs(produced[i] - expected[i]));
            Assert.True(maxDiff <= epsilon, $"render/{caseName}: max |Δ| = {maxDiff:g3} (ε = {epsilon:g1})");
        }

        private static readonly Dictionary<string, string[]> StrictKeys = new Dictionary<string, string[]>
        {
            ["lut"] = new[] { "cmap", "output" },
            ["stretch"] = new[] { "input", "output" },          // plus one of "measured" / "stretch"
            ["phase"] = new[] { "input", "zoom_log10", "phase", "output" },
            ["frequency"] = new[] { "counts", "input", "target_cycles_per_step", "max_cycles_per_iteration", "expected" },
            ["phase-apply"] = new[] { "cmap", "wrap", "interior", "antialias", "dither", "frame_index", "input", "output" },
            ["shade"] = new[] { "rgb", "input", "shade", "output" },
        };

        private static void RunColorCase(string caseName, string caseDir, JsonElement root)
        {
            string kind = root.GetProperty("kind").GetString()!;
            Assert.True(StrictKeys.ContainsKey(kind), $"render/{caseName}: unknown kind {kind}");
            var allowed = new HashSet<string> { "spec_version", "family", "tier", "kind" };
            allowed.UnionWith(StrictKeys[kind]);
            if (kind == "stretch")
                allowed.Add(root.TryGetProperty("measured", out _) ? "measured" : "stretch");
            var names = new HashSet<string>();
            foreach (var property in root.EnumerateObject())
                names.Add(property.Name);
            Assert.True(names.SetEquals(allowed), $"render/{caseName}: unexpected keys {string.Join(", ", names)}");
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            Assert.Equal("render", root.GetProperty("family").GetString());
            string File(string key) => Path.Combine(caseDir, root.GetProperty(key).GetProperty("file").GetString()!);
            switch (kind)
            {
                case "lut":
                    RunLut(caseName, caseDir, root);
                    break;
                case "stretch":
                    {
                        double[] mu = ReadF64(File("input"));
                        var render = new double[mu.Length];
                        if (root.TryGetProperty("measured", out var measured))
                        {
                            bool got = FractalColor.TryMeasureStretch(mu, new double[mu.Length], out var stretch);
                            if (measured.ValueKind == JsonValueKind.Null)
                            {
                                Assert.False(got);
                            }
                            else
                            {
                                Assert.True(got);
                                Assert.Equal(Bits(measured, "lo"), stretch.Lo);
                                Assert.Equal(Bits(measured, "hi"), stretch.Hi);
                                FractalColor.ApplyStretch(mu, stretch, render);
                            }
                        }
                        else
                        {
                            var given = root.GetProperty("stretch");
                            FractalColor.ApplyStretch(mu, new Stretch(Bits(given, "lo"), Bits(given, "hi")), render);
                        }
                        AssertFloatFrame(caseName, caseDir, root.GetProperty("output").GetProperty("file").GetString()!, render);
                        break;
                    }
                case "phase":
                    {
                        double[] mu = ReadF64(File("input"));
                        var ph = root.GetProperty("phase");
                        AssertKeySet(ph, caseName, "cycles_per_iteration", "cycles_per_octave", "phase_offset", "anchor");
                        var parameters = new PhaseParams(
                            Bits(ph, "cycles_per_iteration"), Bits(ph, "cycles_per_octave"), Bits(ph, "phase_offset"), Bits(ph, "anchor"));
                        var t = new double[mu.Length];
                        FractalColor.DepthPhase(mu, Bits(root, "zoom_log10"), parameters, t);
                        AssertFloatFrame(caseName, caseDir, root.GetProperty("output").GetProperty("file").GetString()!, t);
                        break;
                    }
                case "frequency":
                    {
                        double[] mu = ReadF64(File("input"));
                        byte[] raw = System.IO.File.ReadAllBytes(File("counts"));
                        var counts = new int[raw.Length / 4];
                        Buffer.BlockCopy(raw, 0, counts, 0, raw.Length);
                        int width = root.GetProperty("input").GetProperty("shape")[1].GetInt32();
                        bool got = FractalColor.TryMeasureFrequency(
                            counts, mu, width, Bits(root, "target_cycles_per_step"), Bits(root, "max_cycles_per_iteration"),
                            new double[2 * mu.Length], out var frequency);
                        var expected = root.GetProperty("expected");
                        if (expected.ValueKind == JsonValueKind.Null)
                        {
                            Assert.False(got);
                        }
                        else
                        {
                            AssertKeySet(expected, caseName, "cycles_per_iteration", "anchor");
                            Assert.True(got);
                            Assert.Equal(Bits(expected, "cycles_per_iteration"), frequency.CyclesPerIteration);
                            Assert.Equal(Bits(expected, "anchor"), frequency.Anchor);
                        }
                        break;
                    }
                case "phase-apply":
                    {
                        double[] t = ReadF64(File("input"));
                        int width = root.GetProperty("input").GetProperty("shape")[1].GetInt32();
                        var interior = root.GetProperty("interior");
                        var wrap = root.GetProperty("wrap").GetString() switch
                        {
                            "cyclic" => PhaseWrap.Cyclic,
                            "mirror" => PhaseWrap.Mirror,
                            var other => throw new InvalidDataException($"unknown wrap '{other}'"),
                        };
                        var rgb = new byte[t.Length * 3];
                        Colormaps.ApplyPhase(
                            t, width, Colormaps.Get(root.GetProperty("cmap").GetString()!), rgb, wrap,
                            root.GetProperty("antialias").GetBoolean(), Bits(root, "dither"),
                            root.GetProperty("frame_index").GetUInt32(),
                            (byte)interior[0].GetInt32(), (byte)interior[1].GetInt32(), (byte)interior[2].GetInt32());
                        var (_, _, channels, expected) = Png.Read(File("output"));
                        Assert.Equal(3, channels);
                        Assert.True(rgb.AsSpan().SequenceEqual(expected), $"render/{caseName}: RGB mismatch");
                        // The RGBA path writes the same colors.
                        var rgba = new byte[t.Length * 4];
                        Colormaps.ApplyPhaseRgba(
                            t, width, Colormaps.Get(root.GetProperty("cmap").GetString()!), rgba, wrap,
                            root.GetProperty("antialias").GetBoolean(), Bits(root, "dither"),
                            root.GetProperty("frame_index").GetUInt32(),
                            (byte)interior[0].GetInt32(), (byte)interior[1].GetInt32(), (byte)interior[2].GetInt32());
                        for (int i = 0; i < t.Length; i++)
                            Assert.True(rgba[4 * i] == rgb[3 * i] && rgba[4 * i + 1] == rgb[3 * i + 1]
                                && rgba[4 * i + 2] == rgb[3 * i + 2] && rgba[4 * i + 3] == 255, $"render/{caseName}: RGBA");
                        break;
                    }
                case "shade":
                    {
                        double[] distance = ReadF64(File("input"));
                        int width = root.GetProperty("input").GetProperty("shape")[1].GetInt32();
                        var sh = root.GetProperty("shade");
                        AssertKeySet(sh, caseName, "width", "strength", "dense_release");
                        var parameters = new ShadeParams(Bits(sh, "width"), Bits(sh, "strength"), Bits(sh, "dense_release"));
                        var (_, _, inChannels, input) = Png.Read(File("rgb"));
                        Assert.Equal(3, inChannels);
                        byte[] rgb = (byte[])input.Clone();
                        FractalColor.ShadeRgb(rgb, distance, width, parameters, new double[2 * distance.Length]);
                        var (_, _, channels, expected) = Png.Read(File("output"));
                        Assert.Equal(3, channels);
                        Assert.True(rgb.AsSpan().SequenceEqual(expected), $"render/{caseName}: RGB mismatch");
                        var rgba = new byte[distance.Length * 4];
                        for (int i = 0; i < distance.Length; i++)
                        {
                            rgba[4 * i] = input[3 * i];
                            rgba[4 * i + 1] = input[3 * i + 1];
                            rgba[4 * i + 2] = input[3 * i + 2];
                            rgba[4 * i + 3] = 7;
                        }
                        FractalColor.ShadeRgba(rgba, distance, width, parameters, new double[2 * distance.Length]);
                        for (int i = 0; i < distance.Length; i++)
                            Assert.True(rgba[4 * i] == rgb[3 * i] && rgba[4 * i + 1] == rgb[3 * i + 1]
                                && rgba[4 * i + 2] == rgb[3 * i + 2] && rgba[4 * i + 3] == 7, $"render/{caseName}: RGBA");
                        break;
                    }
            }
        }

        // State palettes and windows of grids (spec/render.md, 0.16.0): strict, every key known.

        private static void RunPalette(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            byte[] palette;
            if (root.TryGetProperty("builder", out var builder))
            {
                AssertKeySet(root, caseName, "spec_version", "family", "tier", "kind", "builder", "output");
                string name = builder.GetProperty("name").GetString()!;
                switch (name)
                {
                    case "history":
                        AssertKeySet(builder, caseName, "name");
                        palette = StatePalettes.ForHistory();
                        break;
                    case "generations":
                        AssertKeySet(builder, caseName, "name", "states");
                        palette = StatePalettes.ForGenerations(builder.GetProperty("states").GetInt32());
                        break;
                    case "multistate":
                        AssertKeySet(builder, caseName, "name", "states");
                        palette = StatePalettes.ForMultiState(builder.GetProperty("states").GetInt32());
                        break;
                    case "gradient":
                        AssertKeySet(builder, caseName, "name", "states", "first", "last", "background");
                        palette = StatePalettes.Gradient(
                            builder.GetProperty("states").GetInt32(),
                            Color(builder.GetProperty("first")),
                            Color(builder.GetProperty("last")),
                            Color(builder.GetProperty("background")));
                        break;
                    default:
                        throw new InvalidDataException($"render/{caseName}: unknown palette builder '{name}'");
                }
            }
            else
            {
                bool hasCmap = root.TryGetProperty("cmap", out var cmap);
                var keys = new List<string>
                {
                    "spec_version", "family", "tier", "kind", "world", "frame_values", "zoom_order", "output",
                };
                if (hasCmap)
                    keys.Add("cmap");
                AssertKeySet(root, caseName, keys.ToArray());
                var world = root.GetProperty("world");
                string family = world.GetProperty("family").GetString()!;
                byte[] values, order;
                switch (family)
                {
                    case "hashlife":
                        {
                            AssertKeySet(world, caseName, "family", "rule");
                            var universe = new HashLife(world.GetProperty("rule").GetString()!);
                            values = StatePalettes.FrameValues(universe);
                            order = StatePalettes.DefaultZoomOrder(universe);
                            palette = hasCmap
                                ? StatePalettes.FromColormap(universe, Colormaps.Get(cmap.GetString()!))
                                : StatePalettes.Default(universe);
                            break;
                        }
                    case "hashlife-multistate":
                        {
                            AssertKeySet(world, caseName, "family", "rule");
                            var universe = new MultiStateHashLife(world.GetProperty("rule").GetString()!);
                            values = StatePalettes.FrameValues(universe);
                            order = StatePalettes.DefaultZoomOrder(universe);
                            palette = hasCmap
                                ? StatePalettes.FromColormap(universe, Colormaps.Get(cmap.GetString()!))
                                : StatePalettes.Default(universe);
                            break;
                        }
                    default:
                        {
                            ISimulation sim = PaletteWorld(caseName, world, family);
                            values = StatePalettes.FrameValues(sim);
                            order = StatePalettes.DefaultZoomOrder(sim);
                            palette = hasCmap
                                ? StatePalettes.FromColormap(sim, Colormaps.Get(cmap.GetString()!))
                                : StatePalettes.Default(sim);
                            break;
                        }
                }
                Assert.Equal(Ints(root.GetProperty("frame_values")), values);
                Assert.Equal(Ints(root.GetProperty("zoom_order")), order);
            }
            var (width, height, channels, expected) = Png.Read(
                Path.Combine(caseDir, root.GetProperty("output").GetProperty("file").GetString()!));
            Assert.Equal(3, channels);
            Assert.Equal(256, width * height);
            Assert.True(palette.AsSpan().SequenceEqual(expected), $"render/{caseName}: palette mismatch");
        }

        private static ISimulation PaletteWorld(string caseName, JsonElement world, string family)
        {
            switch (family)
            {
                case "lifelike":
                    AssertKeySet(world, caseName, "family", "rule");
                    return new LifeLike(world.GetProperty("rule").GetString()!, 8, 8);
                case "elementary":
                    AssertKeySet(world, caseName, "family", "rule");
                    return new Elementary(world.GetProperty("rule").GetInt32(), 8, 8);
                case "cyclic":
                    AssertKeySet(world, caseName, "family", "states");
                    return new Cyclic(world.GetProperty("states").GetInt32(), 8, 8);
                case "wireworld":
                    AssertKeySet(world, caseName, "family");
                    return new Wireworld(16, 16);
                case "generations":
                    AssertKeySet(world, caseName, "family", "rule");
                    return new Generations(world.GetProperty("rule").GetString()!, 8, 8);
                default:
                    throw new InvalidDataException($"render/{caseName}: no palette world '{family}'");
            }
        }

        private static void RunShade(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            AssertKeySet(root, caseName, "spec_version", "family", "tier", "kind", "background", "color", "output");
            byte[] shade = StatePalettes.Shade(Color(root.GetProperty("background")), Color(root.GetProperty("color")));
            var (width, height, channels, expected) = Png.Read(
                Path.Combine(caseDir, root.GetProperty("output").GetProperty("file").GetString()!));
            Assert.Equal(3, channels);
            Assert.Equal(256, width * height);
            Assert.True(shade.AsSpan().SequenceEqual(expected), $"render/{caseName}: shade mismatch");
        }

        private static void RunWindow(string caseName, string caseDir, JsonElement root)
        {
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            AssertKeySet(
                root, caseName, "spec_version", "family", "tier", "kind", "x0", "y0", "width", "height",
                "out_width", "out_height", "mode", "order", "input", "output");
            var (gridWidth, gridHeight, channels, cells) = Png.Read(
                Path.Combine(caseDir, root.GetProperty("input").GetProperty("file").GetString()!));
            Assert.Equal(1, channels);
            var shape = root.GetProperty("input").GetProperty("shape");
            Assert.Equal((gridHeight, gridWidth), (shape[0].GetInt32(), shape[1].GetInt32()));
            int outWidth = root.GetProperty("out_width").GetInt32();
            int outHeight = root.GetProperty("out_height").GetInt32();
            GridWindowMode mode = root.GetProperty("mode").GetString() switch
            {
                "nearest" => GridWindowMode.Nearest,
                "state" => GridWindowMode.State,
                "density" => GridWindowMode.Density,
                var other => throw new InvalidDataException($"render/{caseName}: unknown window mode '{other}'"),
            };
            var output = new byte[outWidth * outHeight];
            GridWindow.Sample(
                cells, gridWidth, gridHeight,
                root.GetProperty("x0").GetInt32(), root.GetProperty("y0").GetInt32(),
                root.GetProperty("width").GetInt32(), root.GetProperty("height").GetInt32(),
                output, outWidth, outHeight, mode, Ints(root.GetProperty("order")));
            var (expectedWidth, expectedHeight, expectedChannels, expected) = Png.Read(
                Path.Combine(caseDir, root.GetProperty("output").GetProperty("file").GetString()!));
            Assert.Equal(1, expectedChannels);
            Assert.Equal((outWidth, outHeight), (expectedWidth, expectedHeight));
            Assert.True(output.AsSpan().SequenceEqual(expected), $"render/{caseName}: window mismatch");
        }

        private static (byte R, byte G, byte B) Color(JsonElement triple)
        {
            Assert.Equal(3, triple.GetArrayLength());
            return ((byte)triple[0].GetInt32(), (byte)triple[1].GetInt32(), (byte)triple[2].GetInt32());
        }

        private static byte[] Ints(JsonElement array)
        {
            var values = new byte[array.GetArrayLength()];
            int i = 0;
            foreach (var item in array.EnumerateArray())
                values[i++] = checked((byte)item.GetInt32());
            return values;
        }

        /// <summary>A double from its IEEE-754 bit pattern ("0x" + 16 hex digits).</summary>
        private static double Bits(JsonElement parent, string key)
        {
            string text = parent.GetProperty(key).GetString()!;
            Assert.True(text.StartsWith("0x", StringComparison.Ordinal) && text.Length == 18, text);
            return BitConverter.Int64BitsToDouble(
                long.Parse(text.Substring(2), System.Globalization.NumberStyles.HexNumber, System.Globalization.CultureInfo.InvariantCulture));
        }

        private static void AssertKeySet(JsonElement element, string caseName, params string[] expected)
        {
            var names = new HashSet<string>();
            foreach (var property in element.EnumerateObject())
                names.Add(property.Name);
            Assert.True(names.SetEquals(expected), $"render/{caseName}: unexpected keys {string.Join(", ", names)}");
        }

        private static void AssertByteFrame(string caseName, string caseDir, string outputFile, byte[] frame)
        {
            var (_, _, channels, expected) = Png.Read(Path.Combine(caseDir, outputFile));
            Assert.Equal(1, channels);
            Assert.True(frame.AsSpan().SequenceEqual(expected), $"render/{caseName}: frame mismatch");
        }

        private static void AssertFloatFrame(string caseName, string caseDir, string outputFile, double[] frame)
        {
            double[] expected = ReadF64(Path.Combine(caseDir, outputFile));
            Assert.Equal(expected.Length, frame.Length);
            for (int i = 0; i < expected.Length; i++)
                Assert.True(
                    frame[i].Equals(expected[i]),
                    $"render/{caseName}: frame mismatch at {i}: {frame[i]:R} != {expected[i]:R}");
        }

        private static byte[] ReadGrayBinarized(string path)
        {
            var (_, _, channels, pixels) = Png.Read(path);
            Assert.Equal(1, channels);
            var state = new byte[pixels.Length];
            for (int i = 0; i < pixels.Length; i++)
                state[i] = (byte)(pixels[i] > 0 ? 1 : 0);
            return state;
        }

        private static double[] ReadF64(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            var values = new double[bytes.Length / 8];
            Buffer.BlockCopy(bytes, 0, values, 0, bytes.Length);
            return values;
        }

        [Fact]
        public void WireworldAnchorsLandOnStateColors()
        {
            byte[] lut = Colormaps.Get("wireworld");
            // state * 85 -> exact anchor colors for the four Wireworld states
            Assert.Equal(new byte[] { 0, 0, 0 }, new[] { lut[0], lut[1], lut[2] });
            Assert.Equal(new byte[] { 70, 130, 255 }, new[] { lut[85 * 3], lut[85 * 3 + 1], lut[85 * 3 + 2] });
            Assert.Equal(new byte[] { 255, 80, 60 }, new[] { lut[170 * 3], lut[170 * 3 + 1], lut[170 * 3 + 2] });
            Assert.Equal(new byte[] { 255, 210, 70 }, new[] { lut[255 * 3], lut[255 * 3 + 1], lut[255 * 3 + 2] });
        }

        [Fact]
        public void IndexedApplyIsDirectLookup()
        {
            byte[] lut = Colormaps.Get("fire");
            var frame = new byte[] { 0, 85, 170, 255 };
            byte[] rgb = Colormaps.ApplyIndexed(frame, lut);
            for (int i = 0; i < frame.Length; i++)
                for (int c = 0; c < 3; c++)
                    Assert.Equal(lut[frame[i] * 3 + c], rgb[i * 3 + c]);
        }
    }
}
