using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// PNG I/O conformance: replay vectors/png-io/ decode pins (spec/png-io.md).
    /// Input PNGs come from the Python reference encoder; the decoded grids are
    /// bit-exact. Expected grids are read with the test project's independent
    /// PNG reader, so the library decoder never validates itself.
    /// </summary>
    public class PngIoConformanceTests
    {
        public static IEnumerable<object[]> Cases()
        {
            foreach (string dir in Directory.GetDirectories(
                         Path.Combine(TestPaths.VectorRoot(), "png-io")))
                yield return new object[] { Path.GetFileName(dir) };
        }

        [Theory]
        [MemberData(nameof(Cases))]
        public void Vector(string caseName)
        {
            string caseDir = Path.Combine(TestPaths.VectorRoot(), "png-io", caseName);
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(caseDir, "params.json")));
            var root = doc.RootElement;
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            Assert.Equal("decode", root.GetProperty("kind").GetString());
            int scale = root.GetProperty("scale").GetInt32();

            byte[] input = File.ReadAllBytes(
                Path.Combine(caseDir, root.GetProperty("input").GetString()));
            byte[] decoded = PngGrid.DecodeRgb(input, scale, out int width, out int height);

            var (expectedWidth, expectedHeight, channels, expected) = Png.Read(
                Path.Combine(caseDir, root.GetProperty("grid").GetProperty("file").GetString()));
            Assert.Equal(3, channels);
            Assert.Equal(expectedWidth, width);
            Assert.Equal(expectedHeight, height);
            Assert.Equal(expected, decoded);
        }
    }
}
