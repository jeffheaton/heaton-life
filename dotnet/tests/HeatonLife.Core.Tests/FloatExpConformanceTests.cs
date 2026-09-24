using System;
using System.Collections.Generic;
using System.IO;
using System.Numerics;
using System.Text.Json;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Floatexp vectors (spec/floatexp.md): each operation at its boundaries must reproduce
    /// the Python reference bit for bit. Strict: an unknown key or operation fails the case.
    /// </summary>
    public class FloatExpConformanceTests
    {
        private static readonly Dictionary<string, string[]> Keys = new Dictionary<string, string[]>
        {
            ["add"] = new[] { "a", "b" },
            ["mul"] = new[] { "a", "b" },
            ["compare"] = new[] { "a", "b" },
            ["div"] = new[] { "a", "b" },
            ["to_double"] = new[] { "a" },
            ["from_fixed"] = new[] { "value", "bits" },
            ["normalize"] = new[] { "value", "exponent" },
        };

        [Fact]
        public void Operations()
        {
            var names = new List<string>();
            foreach (string dir in Directory.GetDirectories(Path.Combine(TestPaths.VectorRoot(), "floatexp")))
                names.Add(Path.GetFileName(dir));
            names.Sort(StringComparer.Ordinal);
            Assert.Equal(new[] { "division", "operations" }, names);
            var seen = new HashSet<string>();
            foreach (string name in names)
                Replay(Path.Combine(TestPaths.VectorRoot(), "floatexp", name, "params.json"), seen);
            Assert.True(seen.SetEquals(Keys.Keys));
        }

        private static void Replay(string path, HashSet<string> seen)
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            Assert.Equal("0.10.0", root.GetProperty("spec_version").GetString());
            Assert.Equal("floatexp", root.GetProperty("family").GetString());
            Assert.Equal("bit-exact", root.GetProperty("tier").GetString());
            foreach (var c in root.GetProperty("cases").EnumerateArray())
            {
                string op = c.GetProperty("op").GetString()!;
                string note = c.GetProperty("note").GetString()!;
                Assert.True(Keys.ContainsKey(op), $"unknown operation {op}");
                seen.Add(op);
                var expectedKeys = new HashSet<string>(Keys[op]) { "op", "expected", "note" };
                var present = new HashSet<string>();
                foreach (var property in c.EnumerateObject())
                    present.Add(property.Name);
                Assert.True(present.SetEquals(expectedKeys), $"{op} ({note}): unexpected keys");
                var expected = c.GetProperty("expected");
                switch (op)
                {
                    case "add":
                        AssertX(expected, FloatExp.Add(X(c.GetProperty("a")), X(c.GetProperty("b"))), note);
                        break;
                    case "mul":
                        AssertX(expected, FloatExp.Mul(X(c.GetProperty("a")), X(c.GetProperty("b"))), note);
                        break;
                    case "div":
                        AssertX(expected, FloatExp.Div(X(c.GetProperty("a")), X(c.GetProperty("b"))), note);
                        break;
                    case "compare":
                        Assert.True(expected.GetInt32() == FloatExp.Compare(X(c.GetProperty("a")), X(c.GetProperty("b"))), note);
                        break;
                    case "to_double":
                        Assert.Equal(expected.GetString(), Bits(X(c.GetProperty("a")).ToDouble()));
                        break;
                    case "from_fixed":
                        AssertX(expected, FloatExp.FromFixed(BigInteger.Parse(c.GetProperty("value").GetString()!), c.GetProperty("bits").GetInt32()), note);
                        break;
                    default:
                        AssertX(expected, FloatExp.Normalize(Double(c.GetProperty("value").GetString()!), c.GetProperty("exponent").GetInt64()), note);
                        break;
                }
            }
        }

        [Fact]
        public void ThisRuntimeMeetsTheFloatingPointContract()
        {
            Assert.Null(FloatingPointContract.Violation());
            FloatingPointContract.Verify();
        }

        [Theory]
        [InlineData(-300.5, "0x3FFB1B75833790CA", -999)]
        [InlineData(-320.0, "0x3FFFA01712E8F047", -1064)]
        [InlineData(-996.5, "0x3FF9F7C393991048", -3311)]
        [InlineData(-9000.0, "0x3FF90E9C5BFAC594", -29898)]
        [InlineData(10000.0, "0x3FF3709D450AAD7E", 33219)]
        public void Pow10XKnownAnswers(double x, string mantissa, int exponent)
        {
            var (m, n) = Pow10.ComputeX(x);
            Assert.Equal(mantissa, Bits(m));
            Assert.Equal(exponent, n);
        }

        private static FloatExp X(JsonElement pair) =>
            FloatExp.Normalize(Double(pair[0].GetString()!), pair[1].GetInt64());

        private static void AssertX(JsonElement expected, FloatExp got, string note)
        {
            Assert.True(expected[0].GetString() == Bits(got.M) && expected[1].GetInt64() == got.E,
                $"{note}: got [{Bits(got.M)}, {got.E}], want [{expected[0].GetString()}, {expected[1].GetInt64()}]");
        }

        private static double Double(string bits) =>
            BitConverter.Int64BitsToDouble(unchecked((long)Convert.ToUInt64(bits.Substring(2), 16)));

        private static string Bits(double value) => $"0x{BitConverter.DoubleToInt64Bits(value):X16}";
    }
}
