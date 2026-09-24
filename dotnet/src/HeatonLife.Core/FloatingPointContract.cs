using System;
using System.Runtime.CompilerServices;

namespace HeatonLife
{
    /// <summary>
    /// The platform contract bit-exact results rest on (spec/deep-zoom.md "Platform
    /// contract"): IEEE-754 binary64 for every operation, no contraction of a·b ± c into a
    /// fused multiply-add, no x87 extended precision or range, and gradual underflow (no
    /// flush-to-zero, no denormals-are-zero). RyuJIT on x64 and ARM64 meets it; a C++
    /// backend (IL2CPP) meets it only when built without contraction. A host runs
    /// <see cref="Violation"/> inside its real player: the canaries read their inputs
    /// from an array at run time, so no compiler can fold them away.
    /// </summary>
    internal static class FloatingPointContract
    {
        // 1 + 2^-30, 1 + 2^-31, 1, 2^-1022, 0.5, 0.75, 2^-60, 2^60, 1 + 2^-52, 2^-40
        private static readonly double[] Inputs =
        {
            1.0000000009313226, 1.0000000004656613, 1.0, 2.2250738585072014E-308, 0.5, 0.75,
            8.673617379884035E-19, 1.152921504606847E+18, 1.0000000000000002, 9.094947017729282E-13,
        };

        /// <summary>Null when this runtime meets the contract, else what it breaks.</summary>
        internal static string? Violation() => Check(Inputs);

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static string? Check(double[] v)
        {
            double a = v[0], b = v[1], one = v[2], tiny = v[3], half = v[4], threeQuarters = v[5];
            double down = v[6], up = v[7], next = v[8], small = v[9];

            // T2's fast-step shape, (t_r·w_r − t_i·w_i) + dcS: each product rounds before the
            // subtraction. Fused either way, the result picks up a 2^-60 or 2^-62 term.
            double shape = (a * a - b * b) + small;
            if (shape != 9.322320693172514E-10)   // 2^-30 + 2^-40 exactly
                return "a·b − c·d is contracted into a fused multiply-add";
            double sum = a * a + -one;
            if (sum != 1.862645149230957E-09)   // 2^-29: a·a rounds to 1 + 2^-29 first
                return "a·b + c is contracted into a fused multiply-add";

            // Gradual underflow: a product rounds once into the subnormals (ties to even) ...
            if (next * tiny * half != 1.1125369292536007E-308)   // 2^-1023
                return "a subnormal product is flushed to zero or misrounded (FTZ)";
            if (tiny * threeQuarters == 0.0)
                return "a subnormal product is flushed to zero (FTZ)";
            // ... and a subnormal operand is not read as zero.
            double sub = tiny * half;
            if (sub * 2.0 != tiny)
                return "a subnormal operand is read as zero (DAZ)";

            // No extended range: 2^-1082 is not a double, so it underflows to 0 before the
            // scale back up.
            if (tiny * down * up != 0.0)
                return "an intermediate keeps extended exponent range (x87)";
            // No extended precision: (1 + 2^-52) + 2^-53 ties to even at double precision.
            if ((next + 1.1102230246251565E-16) - one != 4.440892098500626E-16)
                return "an intermediate keeps extended precision (x87)";
            return null;
        }

        /// <summary>Throws when this runtime breaks the contract (a host's self-check).</summary>
        internal static void Verify()
        {
            string? violation = Violation();
            if (violation != null)
                throw new InvalidOperationException("HeatonLife's floating-point contract is broken on this runtime: " + violation);
        }
    }
}
