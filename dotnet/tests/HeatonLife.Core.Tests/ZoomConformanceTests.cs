using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Zoom movie vectors (spec/zoom.md, 0.13.0): the schedule, the plan's frame progress,
    /// zooms and speeds, the movie budgets, the survey's stations, its patience rule, and
    /// whole surveys with real Mandelbrot probes must match the Python reference bit for
    /// bit. Strict: an unknown key fails the case.
    /// </summary>
    public class ZoomConformanceTests
    {
        [Fact]
        public void Schedules()
        {
            using var doc = Load("schedules", "schedules");
            foreach (var c in doc.RootElement.GetProperty("schedules").EnumerateArray())
            {
                AssertKeys(c, "segments", "duration", "resolved", "samples");
                var seg = c.GetProperty("segments");
                var resolved = new ZoomSchedule(F(seg[0]), F(seg[1]), F(seg[2]), F(seg[3]))
                    .Resolved(F(c.GetProperty("duration")));
                double[] got =
                {
                    resolved.Duration, resolved.HoldStart, resolved.EaseIn, resolved.EaseOut,
                    resolved.HoldEnd, resolved.Cruise, resolved.EffectiveSeconds, resolved.PeakOverAverage,
                };
                var expected = c.GetProperty("resolved");
                for (int i = 0; i < got.Length; i++)
                    Assert.Equal(expected[i].GetString(), Bits(got[i]));
                foreach (var s in c.GetProperty("samples").EnumerateArray())
                {
                    AssertKeys(s, "t", "progress", "speed_fraction");
                    double t = F(s.GetProperty("t"));
                    Assert.True(s.GetProperty("progress").GetString() == Bits(resolved.Progress(t)),
                        $"progress({t}): got {Bits(resolved.Progress(t))}");
                    Assert.True(s.GetProperty("speed_fraction").GetString() == Bits(resolved.SpeedFraction(t)),
                        $"speed_fraction({t}): got {Bits(resolved.SpeedFraction(t))}");
                }
            }
        }

        [Fact]
        public void Plans()
        {
            using var doc = Load("plans", "plans");
            foreach (var c in doc.RootElement.GetProperty("plans").EnumerateArray())
            {
                AssertKeys(c, "start_zoom", "end_zoom", "frames", "fps", "schedule", "progress", "zooms", "speeds");
                var seg = c.GetProperty("schedule");
                var plan = new ZoomPlan(F(c.GetProperty("start_zoom")), F(c.GetProperty("end_zoom")),
                    c.GetProperty("frames").GetInt32(), c.GetProperty("fps").GetInt32(),
                    new ZoomSchedule(F(seg[0]), F(seg[1]), F(seg[2]), F(seg[3])));
                double[] zooms = plan.Zooms();
                var expectedProgress = c.GetProperty("progress");
                var expectedZooms = c.GetProperty("zooms");
                var expectedSpeeds = c.GetProperty("speeds");
                Assert.Equal(expectedZooms.GetArrayLength(), zooms.Length);
                for (int f = 0; f < plan.Frames; f++)
                {
                    Assert.True(expectedProgress[f].GetString() == Bits(plan.Progress(f)), $"frame {f}: progress {Bits(plan.Progress(f))}");
                    Assert.True(expectedZooms[f].GetString() == Bits(zooms[f]), $"frame {f}: zoom {Bits(zooms[f])}");
                    Assert.True(expectedSpeeds[f].GetString() == Bits(plan.Speed(f)), $"frame {f}: speed {Bits(plan.Speed(f))}");
                }
            }
        }

        [Fact]
        public void Budgets()
        {
            using var doc = Load("budgets", "ramps", "measured");
            foreach (var r in doc.RootElement.GetProperty("ramps").EnumerateArray())
            {
                AssertKeys(r, "zoom", "target", "user_limit", "max_iter");
                double zoom = F(r.GetProperty("zoom")), target = F(r.GetProperty("target"));
                var limit = r.GetProperty("user_limit");
                int got = limit.ValueKind == JsonValueKind.Null
                    ? IterationPolicy.MovieMaxIter(zoom, target)
                    : IterationPolicy.MovieMaxIter(zoom, target, limit.GetInt32());
                Assert.Equal(r.GetProperty("max_iter").GetInt32(), got);
            }
            foreach (var c in doc.RootElement.GetProperty("measured").EnumerateArray())
            {
                AssertKeys(c, "knots", "rows");
                var knots = new List<(double Zoom, int Need)>();
                foreach (var k in c.GetProperty("knots").EnumerateArray())
                    knots.Add((F(k[0]), k[1].GetInt32()));
                var array = knots.ToArray();
                foreach (var row in c.GetProperty("rows").EnumerateArray())
                {
                    AssertKeys(row, "zoom", "need", "max_iter");
                    double zoom = F(row.GetProperty("zoom"));
                    Assert.Equal(row.GetProperty("need").GetInt32(), IterationPolicy.NeedAt(zoom, array));
                    Assert.Equal(row.GetProperty("max_iter").GetInt32(), IterationPolicy.MeasuredMaxIter(zoom, array));
                }
            }
        }

        [Fact]
        public void Stations()
        {
            using var doc = Load("stations", "stations");
            foreach (var c in doc.RootElement.GetProperty("stations").EnumerateArray())
            {
                AssertKeys(c, "start_zoom", "end_zoom", "spacing_octaves", "stations");
                var plan = new ZoomPlan(F(c.GetProperty("start_zoom")), F(c.GetProperty("end_zoom")), 2, 1);
                double[] got = ZoomSurvey.Stations(plan, c.GetProperty("spacing_octaves").GetInt32());
                var expected = c.GetProperty("stations");
                Assert.Equal(expected.GetArrayLength(), got.Length);
                for (int i = 0; i < got.Length; i++)
                    Assert.Equal(expected[i].GetString(), Bits(got[i]));
            }
        }

        [Fact]
        public void Probes()
        {
            using var doc = Load("probes", "probes");
            foreach (var c in doc.RootElement.GetProperty("probes").EnumerateArray())
            {
                AssertKeys(c, "name", "points", "zoom", "cap", "patient", "budget", "expected");
                string name = c.GetProperty("name").GetString()!;
                var points = new List<long>();
                foreach (var p in c.GetProperty("points").EnumerateArray())
                    points.Add(p.GetInt64());
                var asked = new List<int>();
                (int[] Counts, byte[] Status) Probe(int budget)
                {
                    asked.Add(budget);
                    var counts = new int[points.Count];
                    var status = new byte[points.Count];
                    for (int i = 0; i < points.Count; i++)
                    {
                        long v = points[i];
                        bool escaped = v > 0 && v <= budget;
                        counts[i] = escaped ? (int)v : -1;
                        status[i] = (byte)(escaped ? PixelStatus.Escaped
                            : v == -2 ? PixelStatus.CardioidOrBulb : PixelStatus.Exhausted);
                    }
                    return (counts, status);
                }
                var budgetElement = c.GetProperty("budget");
                int? budget = budgetElement.ValueKind == JsonValueKind.Null ? (int?)null : budgetElement.GetInt32();
                var station = ZoomSurvey.ProbeStation(Probe, F(c.GetProperty("zoom")), c.GetProperty("cap").GetInt32(),
                    c.GetProperty("patient").GetBoolean(), budget);
                var e = c.GetProperty("expected");
                AssertKeys(e, "budgets", "budget", "need", "escaped", "unresolved", "samples");
                var expectedBudgets = new List<int>();
                foreach (var b in e.GetProperty("budgets").EnumerateArray())
                    expectedBudgets.Add(b.GetInt32());
                Assert.Equal(string.Join(",", expectedBudgets), string.Join(",", asked));
                Assert.Equal(e.GetProperty("budget").GetInt32(), station.Budget);
                var need = e.GetProperty("need");
                Assert.Equal(need.ValueKind == JsonValueKind.Null ? (int?)null : need.GetInt32(), station.Need);
                Assert.Equal(e.GetProperty("escaped").GetInt32(), station.Escaped);
                Assert.Equal(e.GetProperty("unresolved").GetInt32(), station.Unresolved);
                Assert.Equal(e.GetProperty("samples").GetInt32(), station.Samples);
            }
        }

        [Fact]
        public void Surveys()
        {
            using var doc = Load("surveys", "probe_size", "surveys");
            var size = doc.RootElement.GetProperty("probe_size");
            Assert.Equal(ZoomSurvey.ProbeWidth, size[0].GetInt32());
            Assert.Equal(ZoomSurvey.ProbeHeight, size[1].GetInt32());
            foreach (var c in doc.RootElement.GetProperty("surveys").EnumerateArray())
            {
                AssertKeys(c, "name", "family", "center_re", "center_im", "plan", "user_limit", "expected");
                string name = c.GetProperty("name").GetString()!;
                Assert.Equal("mandelbrot", c.GetProperty("family").GetString());
                var p = c.GetProperty("plan");
                AssertKeys(p, "start_zoom", "end_zoom", "frames", "fps");
                var plan = new ZoomPlan(F(p.GetProperty("start_zoom")), F(p.GetProperty("end_zoom")),
                    p.GetProperty("frames").GetInt32(), p.GetProperty("fps").GetInt32());
                string re = c.GetProperty("center_re").GetString()!, im = c.GetProperty("center_im").GetString()!;
                var limitElement = c.GetProperty("user_limit");
                int? limit = limitElement.ValueKind == JsonValueKind.Null ? (int?)null : limitElement.GetInt32();
                var asked = new List<(double Zoom, int Budget)>();
                var stations = ZoomSurvey.Survey(plan, (zoom, budget) =>
                {
                    asked.Add((zoom, budget));
                    return new Mandelbrot(budget).CountsAndStatus(ZoomSurvey.ProbeWidth, ZoomSurvey.ProbeHeight,
                        new Viewport(re, im, zoom));
                }, limit);
                var e = c.GetProperty("expected");
                AssertKeys(e, "stations", "max_iter");
                var expected = e.GetProperty("stations");
                Assert.Equal(expected.GetArrayLength(), stations.Length);
                for (int i = 0; i < stations.Length; i++)
                {
                    var x = expected[i];
                    var s = stations[i];
                    AssertKeys(x, "zoom", "budgets", "budget", "need", "escaped", "unresolved", "samples");
                    Assert.Equal(x.GetProperty("zoom").GetString(), Bits(s.ZoomLog10));
                    var budgets = new List<int>();
                    foreach (var b in x.GetProperty("budgets").EnumerateArray())
                        budgets.Add(b.GetInt32());
                    var mine = new List<int>();
                    foreach (var (zoom, budget) in asked)
                        if (zoom == s.ZoomLog10)
                            mine.Add(budget);
                    Assert.True(string.Join(",", budgets) == string.Join(",", mine), $"{name} station {i}: asked {string.Join(",", mine)}");
                    Assert.Equal(x.GetProperty("budget").GetInt32(), s.Budget);
                    var need = x.GetProperty("need");
                    Assert.Equal(need.ValueKind == JsonValueKind.Null ? (int?)null : need.GetInt32(), s.Need);
                    Assert.Equal(x.GetProperty("escaped").GetInt32(), s.Escaped);
                    Assert.Equal(x.GetProperty("unresolved").GetInt32(), s.Unresolved);
                    Assert.Equal(x.GetProperty("samples").GetInt32(), s.Samples);
                }
                var maxIter = e.GetProperty("max_iter");
                double[] zooms = plan.Zooms();
                Assert.Equal(maxIter.GetArrayLength(), zooms.Length);
                for (int f = 0; f < zooms.Length; f++)
                    Assert.True(maxIter[f].GetInt32() == ZoomSurvey.MaxIter(zooms[f], plan, stations, limit), $"{name} frame {f}");
            }
        }

        private static JsonDocument Load(string name, params string[] keys)
        {
            string path = Path.Combine(TestPaths.VectorRoot(), "zoom", name, "params.json");
            var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            var all = new List<string> { "spec_version", "family", "tier" };
            all.AddRange(keys);
            AssertKeys(root, all.ToArray());
            Assert.Equal("0.13.0", root.GetProperty("spec_version").GetString());
            Assert.Equal("zoom", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            return doc;
        }

        private static void AssertKeys(JsonElement element, params string[] keys)
        {
            var seen = new HashSet<string>();
            foreach (var property in element.EnumerateObject())
                seen.Add(property.Name);
            Assert.True(seen.SetEquals(keys), $"keys: {string.Join(",", seen)}");
        }

        private static double F(JsonElement element) =>
            BitConverter.Int64BitsToDouble(long.Parse(element.GetString()!.Substring(2), NumberStyles.HexNumber, CultureInfo.InvariantCulture));

        private static string Bits(double value) => $"0x{BitConverter.DoubleToInt64Bits(value):X16}";
    }
}
