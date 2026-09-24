using System;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// cis_turns vectors (spec/turns.md): each (k, n) must give the Python reference's
    /// (cos 2πk/n, sin 2πk/n) bit for bit. Strict: an unknown key fails the case.
    /// </summary>
    public class TurnsConformanceTests
    {
        [Fact]
        public void KnownAnswers()
        {
            string path = Path.Combine(TestPaths.VectorRoot(), "turns", "known-answers", "params.json");
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            int rootKeys = 0;
            foreach (var property in root.EnumerateObject())
            {
                Assert.Contains(property.Name, new[] { "spec_version", "family", "tier", "cases" });
                rootKeys++;
            }
            Assert.Equal(4, rootKeys);
            Assert.Equal("0.12.0", root.GetProperty("spec_version").GetString());
            Assert.Equal("turns", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            foreach (var c in root.GetProperty("cases").EnumerateArray())
            {
                int keys = 0;
                foreach (var _ in c.EnumerateObject())
                    keys++;
                Assert.Equal(3, keys);
                long k = c.GetProperty("k").GetInt64(), n = c.GetProperty("n").GetInt64();
                var (re, im) = Turns.Cis(k, n);
                var expected = c.GetProperty("expected");
                Assert.True(expected[0].GetString() == Bits(re) && expected[1].GetString() == Bits(im),
                    $"cis_turns({k}, {n}): got [{Bits(re)}, {Bits(im)}]");
            }
        }

        [Fact]
        public void NewtonRootsArePinned()
        {
            // The cube roots of unity: -1/2 exactly, where libm's cos(2π/3) gives -0.49999999999999983.
            var (re, im) = Turns.Cis(1, 3);
            Assert.Equal(-0.5, re);
            Assert.Equal(0.8660254037844386, im);
        }

        private static string Bits(double value) => $"0x{BitConverter.DoubleToInt64Bits(value):X16}";
    }
}
