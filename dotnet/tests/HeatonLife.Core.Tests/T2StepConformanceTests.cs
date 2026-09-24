using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// T2 step vectors (spec/deep-zoom.md "T2"): the per-pixel loop on crafted orbits and
    /// pixels must reproduce the Python reference's count, final z and distance derivative
    /// bit for bit, on the rare paths no natural frame reaches. Strict: a key this runner
    /// does not know fails the case.
    /// </summary>
    public class T2StepConformanceTests
    {
        private static readonly string[] Keys =
        {
            "spec_version", "family", "tier", "orbit", "rebase_orbit", "delta0", "delta_c", "derivative",
            "max_iter", "escape_radius", "paths", "expected",
        };

        private static string Dir => Path.Combine(TestPaths.VectorRoot(), "t2-steps");

        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(Dir))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Fact]
        public void EveryCaseIsListed()
        {
            var names = new List<string>();
            foreach (object[] c in Cases())
                names.Add((string)c[0]);
            names.Sort(StringComparer.Ordinal);
            Assert.Equal(new[] { "delta-gap", "derivative-gap", "final-inf-imaginary", "final-inf-real", "huge-sample" }, names);
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Step(string name)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Dir, name, "params.json")));
            var root = doc.RootElement;
            AssertKeys(root, Keys);
            Assert.Equal("0.10.0", root.GetProperty("spec_version").GetString());
            Assert.Equal("t2-steps", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());

            var orbit = ReadOrbit(root.GetProperty("orbit"));
            var rebaseElement = root.GetProperty("rebase_orbit");
            var rebase = rebaseElement.ValueKind == JsonValueKind.Null ? orbit : ReadOrbit(rebaseElement);
            Pair(root.GetProperty("delta0"), out FloatExp d0r, out FloatExp d0i);
            Pair(root.GetProperty("delta_c"), out FloatExp dcr, out FloatExp dci);
            var derivative = root.GetProperty("derivative");
            bool track = derivative.ValueKind != JsonValueKind.Null;
            FloatExp dd0r = FloatExp.Zero, dd0i = FloatExp.Zero, add = FloatExp.Zero;
            bool hasAdd = false;
            if (track)
            {
                AssertKeys(derivative, new[] { "d0", "add" });
                Pair(derivative.GetProperty("d0"), out dd0r, out dd0i);
                var addElement = derivative.GetProperty("add");
                hasAdd = addElement.ValueKind != JsonValueKind.Null;
                if (hasAdd)
                    add = X(addElement);
            }

            int count = PerturbationT2.Perturb(
                orbit, rebase, d0r, d0i, dcr, dci,
                root.GetProperty("max_iter").GetInt32(), root.GetProperty("escape_radius").GetDouble(),
                track, dd0r, dd0i, add, hasAdd,
                out double finalRe, out double finalIm, out double dr, out double di, out long dExponent);

            var expected = root.GetProperty("expected");
            AssertKeys(expected, new[] { "count", "final", "derivative" });
            Assert.Equal(expected.GetProperty("count").GetInt32(), count);
            var final = expected.GetProperty("final");
            Assert.Equal(final[0].GetString(), Bits(finalRe));
            Assert.Equal(final[1].GetString(), Bits(finalIm));
            var d = expected.GetProperty("derivative");
            Assert.Equal(d[0].GetString(), Bits(dr));
            Assert.Equal(d[1].GetString(), Bits(di));
            Assert.Equal(d[2].GetInt64(), dExponent);
        }

        private static PerturbationT2.Orbit ReadOrbit(JsonElement element)
        {
            AssertKeys(element, new[] { "samples", "small" });
            var samples = element.GetProperty("samples");
            var re = new double[samples.GetArrayLength()];
            var im = new double[re.Length];
            int k = 0;
            foreach (var sample in samples.EnumerateArray())
            {
                re[k] = Double(sample[0].GetString()!);
                im[k] = Double(sample[1].GetString()!);
                k++;
            }
            var rows = element.GetProperty("small");
            var index = new int[rows.GetArrayLength()];
            var smallRe = new FloatExp[index.Length];
            var smallIm = new FloatExp[index.Length];
            k = 0;
            foreach (var row in rows.EnumerateArray())
            {
                index[k] = row[0].GetInt32();
                smallRe[k] = FloatExp.Normalize(Double(row[1].GetString()!), row[2].GetInt64());
                smallIm[k] = FloatExp.Normalize(Double(row[3].GetString()!), row[4].GetInt64());
                k++;
            }
            return new PerturbationT2.Orbit(re, im, new ReferenceOrbit.SmallSamples(index, smallRe, smallIm));
        }

        private static void Pair(JsonElement element, out FloatExp re, out FloatExp im)
        {
            if (element.ValueKind == JsonValueKind.Null)
            {
                re = FloatExp.Zero;
                im = FloatExp.Zero;
                return;
            }
            re = X(element[0]);
            im = X(element[1]);
        }

        private static FloatExp X(JsonElement pair) =>
            FloatExp.Normalize(Double(pair[0].GetString()!), pair[1].GetInt64());

        private static void AssertKeys(JsonElement element, string[] keys)
        {
            var present = new HashSet<string>();
            foreach (var property in element.EnumerateObject())
                present.Add(property.Name);
            Assert.True(present.SetEquals(keys), $"unexpected keys: {string.Join(", ", present)}");
        }

        private static double Double(string bits) =>
            BitConverter.Int64BitsToDouble(unchecked((long)Convert.ToUInt64(bits.Substring(2), 16)));

        private static string Bits(double value) => $"0x{BitConverter.DoubleToInt64Bits(value):X16}";
    }
}
