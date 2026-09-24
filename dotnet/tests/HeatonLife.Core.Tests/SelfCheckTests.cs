using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The platform self-check (spec/self-check.md): every check passes on this runtime, the
    /// shared names match the Python reference's, the software fma's answers are what the
    /// hardware fma gives, gating fails closed, and a run leaves the orbit cache alone.
    /// (Python's suite proves the embedded data is what the generator derives from the vectors.)
    /// </summary>
    public class SelfCheckTests
    {
        [Fact]
        public void EveryCheckPasses()
        {
            bool ok = SelfCheck.Run(out string report);
            Assert.True(ok, report);
            Assert.StartsWith("heaton-life " + HeatonLifeVersion.Version + " self-check: ", report);
        }

        [Fact]
        public void NamesAreTheSharedList()
        {
            var expected = new List<string> { "fp-contract", "fma" };
            expected.AddRange(SelfCheckData.SharedNames);
            Assert.Equal(expected, SelfCheck.Names);
            Assert.Equal(expected, SelfCheck.RunAll().Select(r => r.Name));
        }

        [Fact]
        public void FmaAnswersAreTheHardwareFma()
        {
            foreach (var (a, b, c, expected) in SelfCheckData.Fma)
            {
                double fused = Math.FusedMultiplyAdd(D(a), D(b), D(c));
                Assert.Equal(expected, unchecked((ulong)BitConverter.DoubleToInt64Bits(fused)));
            }
        }

        [Fact]
        public void GatingFailsClosed()
        {
            var results = SelfCheck.RunAll();
            Assert.True(SelfCheck.Passed(results, SelfCheckScope.All));
            var broken = results.Select(r => r.Name == "floatexp" ? Failed(r) : r).ToArray();
            Assert.False(SelfCheck.Passed(broken, SelfCheckScope.T2));
            Assert.True(SelfCheck.Passed(broken, SelfCheckScope.T0 | SelfCheckScope.T1 | SelfCheckScope.Simulations));
            var missing = results.Where(r => r.Name != "julia-t1").ToArray();
            Assert.False(SelfCheck.Passed(missing, SelfCheckScope.T1));
            Assert.True(SelfCheck.Passed(missing, SelfCheckScope.T0));
            var contract = results.Select(r => r.Name == "fp-contract" ? Failed(r) : r).ToArray();
            foreach (SelfCheckScope scope in Enum.GetValues(typeof(SelfCheckScope)))
                Assert.False(SelfCheck.Passed(contract, scope));
            // Results from several runs together: any FAIL for a check fails its scopes.
            var failure = contract.First(r => r.Name == "fp-contract");
            Assert.False(SelfCheck.Passed(new[] { failure }.Concat(results).ToArray(), SelfCheckScope.Simulations));
            Assert.False(SelfCheck.Passed(results.Concat(new[] { failure }).ToArray(), SelfCheckScope.Simulations));
        }

        [Fact]
        public void PassingDetailIsEmpty()
        {
            foreach (var result in SelfCheck.RunAll())
            {
                Assert.Equal("", result.Detail);
                Assert.True(result.Milliseconds >= 0.0);
            }
        }

        private static SelfCheck.Result Failed(SelfCheck.Result r) =>
            new SelfCheck.Result(r.Name, r.Scope, false, "broken", r.Milliseconds);

        private static double D(ulong bits) => BitConverter.Int64BitsToDouble(unchecked((long)bits));
    }

    /// <summary>
    /// A self-check run leaves the process-wide orbit cache as it found it (spec/self-check.md).
    /// In the "orbit cache" collection: it asserts on shared cache state, so it runs alone.
    /// </summary>
    [Collection("orbit cache")]
    public class SelfCheckCacheTests
    {
        [Fact]
        public void ARunLeavesTheOrbitCacheAlone()
        {
            ReferenceOrbit.ClearCache();
            ReferenceOrbit.Mandelbrot("-0.75", "0.1", 20.0, 500);
            var before = ReferenceOrbit.CacheUsage;
            Assert.All(SelfCheck.RunAll(), r => Assert.True(r.Passed, r.Name + ": " + r.Detail));
            Assert.Equal(before, ReferenceOrbit.CacheUsage);
            Assert.True(ReferenceOrbit.IsCached(ReferenceOrbit.Kind.Mandelbrot, "-0.75", "0.1", 20.0, 0.0, 0.0));
        }

        [Fact]
        public void UncachedOrbitsAreNotStored()
        {
            const string re = "-0.7436438870371587047521915061147741", im = "0.1318259042053119704931320563851391";
            ReferenceOrbit.ClearCache();
            (double[] Re, double[] Im) inside;
            using (ReferenceOrbit.Uncached())
                inside = ReferenceOrbit.Mandelbrot(re, im, 21.0, 300);
            Assert.False(ReferenceOrbit.IsCached(ReferenceOrbit.Kind.Mandelbrot, re, im, 21.0, 0.0, 0.0));
            var outside = ReferenceOrbit.Mandelbrot(re, im, 21.0, 300);
            Assert.True(ReferenceOrbit.IsCached(ReferenceOrbit.Kind.Mandelbrot, re, im, 21.0, 0.0, 0.0));
            Assert.Equal(outside.Re, inside.Re);
            Assert.Equal(outside.Im, inside.Im);
        }
    }
}
