using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using System.Text;

namespace HeatonLife
{
    /// <summary>What a self-check's failure invalidates (spec/self-check.md).</summary>
    [Flags]
    public enum SelfCheckScope
    {
        /// <summary>The cellular automata and the continuous families.</summary>
        Simulations = 1,

        /// <summary>Float64 fractal frames.</summary>
        T0 = 2,

        /// <summary>Perturbation: zooms past <see cref="FractalEngine.T0MaxZoom"/> (1e12).</summary>
        T1 = 4,

        /// <summary>Floatexp perturbation: zooms past <see cref="FractalEngine.T1MaxZoom"/> (1e290).</summary>
        T2 = 8,

        /// <summary>Colormaps, the phase lookup, fractal color.</summary>
        Color = 16,

        /// <summary>Zoom movie plans.</summary>
        Movies = 32,

        /// <summary>Everything.</summary>
        All = 63,
    }

    /// <summary>
    /// The platform self-check (spec/self-check.md). A host running the library where the
    /// test suites do not — Unity's IL2CPP or Mono, a phone, WASM — runs it inside its real
    /// player to learn whether that runtime reproduces the bit-exact contract. Every input
    /// and answer is embedded (<see cref="SelfCheckData"/>, generated from the vectors), so
    /// it needs no files, and it never throws: a check that throws is a FAIL with the
    /// exception's type and message. Orbits are computed outside the orbit cache, so a run
    /// leaves a host's cached orbits in place. Each check names what its failure
    /// invalidates; gate a feature with <see cref="Passed"/> — before rendering a frame whose
    /// <see cref="FractalEngine.TierOf"/> is T1, ask for <see cref="SelfCheckScope.T1"/>. The Python reference's
    /// heaton_life.self_check runs the same shared checks on the same answers.
    /// </summary>
    public static class SelfCheck
    {
        /// <summary>One check's outcome.</summary>
        public readonly struct Result
        {
            internal Result(string name, SelfCheckScope scope, bool passed, string detail, double milliseconds)
            {
                Name = name;
                Scope = scope;
                Passed = passed;
                Detail = detail;
                Milliseconds = milliseconds;
            }

            /// <summary>The check's stable name.</summary>
            public string Name { get; }

            /// <summary>What its failure invalidates.</summary>
            public SelfCheckScope Scope { get; }

            /// <summary>Whether it passed.</summary>
            public bool Passed { get; }

            /// <summary>"" when it passed; otherwise what differed.</summary>
            public string Detail { get; }

            /// <summary>How long it ran.</summary>
            public double Milliseconds { get; }
        }

        private sealed class Failed : Exception
        {
            internal Failed(string message)
                : base(message)
            {
            }
        }

        private const SelfCheckScope Fractals = SelfCheckScope.T0 | SelfCheckScope.T1 | SelfCheckScope.T2;

        private static readonly (string Name, SelfCheckScope Scope, Action Run)[] Checks =
        {
            ("fp-contract", SelfCheckScope.All, FpContract),
            ("fma", Fractals, SoftwareFma),
            ("pcg32", SelfCheckScope.Simulations, CheckPcg32),
            ("pow10", Fractals, CheckPow10),
            ("center-projection", Fractals, CenterProjection),
            ("turns", SelfCheckScope.T0, CheckTurns),
            ("floatexp", SelfCheckScope.T2, CheckFloatExp),
            ("reference-orbit", SelfCheckScope.T1 | SelfCheckScope.T2, CheckReferenceOrbit),
            ("navigation", Fractals, CheckNavigation),
            ("mergelife-upstream", SelfCheckScope.Simulations, CheckMergeLife),
            ("grayscott-100", SelfCheckScope.Simulations, CheckGrayScott),
            ("mandelbrot-t0", SelfCheckScope.T0, () => Render("mandelbrot-t0")),
            ("burning-ship-t0", SelfCheckScope.T0, () => Render("burning-ship-t0")),
            ("julia-t1", SelfCheckScope.T1, () => Render("julia-t1")),
            ("burning-ship-t1", SelfCheckScope.T1, () => Render("burning-ship-t1")),
            ("mandelbrot-t1-bla", SelfCheckScope.T1, () => Render("mandelbrot-t1-bla")),
            ("t2-steps", SelfCheckScope.T2, CheckT2Steps),
            ("mandelbrot-t2-bla", SelfCheckScope.T2, () => Render("mandelbrot-t2-bla")),
            ("julia-t2", SelfCheckScope.T2, () => Render("julia-t2")),
            ("zoom-plan", SelfCheckScope.Movies, CheckZoomPlan),
            ("color", SelfCheckScope.Color, CheckColor),
        };

        /// <summary>Every check's name, in run order (fp-contract first).</summary>
        public static IReadOnlyList<string> Names
        {
            get
            {
                var names = new string[Checks.Length];
                for (int i = 0; i < Checks.Length; i++)
                    names[i] = Checks[i].Name;
                return names;
            }
        }

        /// <summary>
        /// Run every check, in order, fp-contract first so the first FAIL is the root cause.
        /// Safe off the main thread; each run computes afresh.
        /// </summary>
        public static Result[] RunAll()
        {
            var results = new Result[Checks.Length];
            for (int i = 0; i < Checks.Length; i++)
            {
                var (name, scope, run) = Checks[i];
                var watch = Stopwatch.StartNew();
                bool passed;
                string detail;
                try
                {
                    run();
                    passed = true;
                    detail = "";
                }
                catch (Failed failed)
                {
                    passed = false;
                    detail = failed.Message;
                }
                catch (Exception ex)
                {
                    passed = false;
                    detail = ex.GetType().Name + ": " + (ex.InnerException ?? ex).Message;
                }
                results[i] = new Result(name, scope, passed, detail, watch.Elapsed.TotalMilliseconds);
            }
            return results;
        }

        /// <summary>Run every check; true only if all passed. <paramref name="report"/> is <see cref="Format"/>'s.</summary>
        public static bool Run(out string report)
        {
            var results = RunAll();
            report = Format(results);
            foreach (var result in results)
                if (!result.Passed)
                    return false;
            return true;
        }

        /// <summary>A report: a header with the library version and total time, then a line per check.</summary>
        public static string Format(Result[] results)
        {
            if (results == null)
                throw new ArgumentNullException(nameof(results));
            double total = 0.0;
            foreach (var result in results)
                total += result.Milliseconds;
            var text = new StringBuilder();
            text.Append("heaton-life ").Append(HeatonLifeVersion.Version).Append(" self-check: ")
                .Append(results.Length.ToString(CultureInfo.InvariantCulture)).Append(" checks, ")
                .Append(total.ToString("0.0", CultureInfo.InvariantCulture)).Append(" ms");
            foreach (var result in results)
            {
                text.Append('\n').Append(result.Passed ? "  PASS  " : "  FAIL  ").Append(result.Name)
                    .Append(" (").Append(result.Milliseconds.ToString("0.0", CultureInfo.InvariantCulture)).Append(" ms)");
                if (!result.Passed)
                    text.Append(" -- ").Append(result.Detail);
            }
            return text.ToString();
        }

        /// <summary>
        /// True when every check whose scope overlaps <paramref name="scope"/> ran and passed: a
        /// check missing from <paramref name="results"/> fails closed, and so does any FAIL for
        /// it (results from several runs may be passed together).
        /// </summary>
        public static bool Passed(Result[] results, SelfCheckScope scope)
        {
            if (results == null)
                throw new ArgumentNullException(nameof(results));
            foreach (var (name, checkScope, _) in Checks)
            {
                if ((checkScope & scope) == 0)
                    continue;
                bool seen = false;
                foreach (var result in results)
                {
                    if (result.Name != name)
                        continue;
                    if (!result.Passed)
                        return false;
                    seen = true;
                }
                if (!seen)
                    return false;
            }
            return true;
        }

        // --- helpers ------------------------------------------------------------------------

        private const ulong FnvOffset = 0xCBF29CE484222325UL;
        private const ulong FnvPrime = 0x100000001B3UL;
        private const ulong CanonicalNaN = 0x7FF8000000000000UL;

        private static ulong Fnv(ulong hash, byte value) => unchecked((hash ^ value) * FnvPrime);

        private static ulong DigestBytes(ReadOnlySpan<byte> data)
        {
            ulong hash = FnvOffset;
            foreach (byte b in data)
                hash = Fnv(hash, b);
            return hash;
        }

        private static ulong DigestInt32(ReadOnlySpan<int> values)
        {
            ulong hash = FnvOffset;
            foreach (int v in values)
            {
                uint u = unchecked((uint)v);
                for (int shift = 0; shift < 32; shift += 8)
                    hash = Fnv(hash, (byte)(u >> shift));
            }
            return hash;
        }

        private static ulong DigestUInt64(ReadOnlySpan<ulong> words)
        {
            ulong hash = FnvOffset;
            foreach (ulong w in words)
            {
                for (int shift = 0; shift < 64; shift += 8)
                    hash = Fnv(hash, (byte)(w >> shift));
            }
            return hash;
        }

        private static ulong DigestDoubles(IReadOnlyList<double> values, bool canonicalNaN)
        {
            var words = new ulong[values.Count];
            for (int i = 0; i < words.Length; i++)
                words[i] = canonicalNaN && double.IsNaN(values[i]) ? CanonicalNaN : Bits(values[i]);
            return DigestUInt64(words);
        }

        private static ulong Bits(double value) => unchecked((ulong)BitConverter.DoubleToInt64Bits(value));

        private static double Double(ulong bits) => BitConverter.Int64BitsToDouble(unchecked((long)bits));

        private static string Hex(ulong value) => "0x" + value.ToString("X16", CultureInfo.InvariantCulture);

        private static void Expect(ulong got, ulong want, string what)
        {
            if (got != want)
                throw new Failed(what + ": " + Hex(got) + " != " + Hex(want));
        }

        private static void Expect(long got, long want, string what)
        {
            if (got != want)
                throw new Failed(what + ": " + got.ToString(CultureInfo.InvariantCulture) + " != " + want.ToString(CultureInfo.InvariantCulture));
        }

        private static FloatExp X(ulong mantissa, long exponent) => FloatExp.Normalize(Double(mantissa), exponent);

        private static double[] Doubles(ulong[] bits)
        {
            var values = new double[bits.Length];
            for (int i = 0; i < values.Length; i++)
                values[i] = Double(bits[i]);
            return values;
        }

        // --- the checks ---------------------------------------------------------------------

        private static void FpContract()
        {
            string? violation = FloatingPointContract.Violation();
            if (violation != null)
                throw new Failed(violation);
        }

        /// <summary>
        /// The software fma against exactly rounded answers: the Dekker path, the slow paths,
        /// ties that only the product's rounding error breaks (a form that rounds twice gets
        /// them wrong), and exact residuals c = -round(a·b) (only a fused multiply-add returns
        /// the product's rounding error). Contraction as such is fp-contract's to detect.
        /// </summary>
        private static void SoftwareFma()
        {
            for (int i = 0; i < SelfCheckData.Fma.Length; i++)
            {
                var (a, b, c, expected) = SelfCheckData.Fma[i];
                Expect(Bits(FractalEngine.Fma(Double(a), Double(b), Double(c))), expected, "triple " + i.ToString(CultureInfo.InvariantCulture));
            }
        }

        private static void CheckPcg32()
        {
            var rng = new Pcg32(SelfCheckData.Pcg32Seed, SelfCheckData.Pcg32Seq);
            for (int i = 0; i < SelfCheckData.Pcg32Draws.Length; i++)
                Expect(rng.NextU32(), SelfCheckData.Pcg32Draws[i], "draw " + i.ToString(CultureInfo.InvariantCulture));
        }

        private static void CheckPow10()
        {
            foreach (var (x, value) in SelfCheckData.Pow10)
                Expect(Bits(Pow10.Compute(Double(x))), value, "pow10(" + Double(x).ToString("R", CultureInfo.InvariantCulture) + ")");
            foreach (var (x, mantissa, exponent) in SelfCheckData.Pow10X)
            {
                var (m, n) = Pow10.ComputeX(Double(x));
                string what = "pow10x(" + Double(x).ToString("R", CultureInfo.InvariantCulture) + ")";
                Expect(Bits(m), mantissa, what);
                Expect(n, exponent, what);
            }
        }

        private static void CenterProjection()
        {
            for (int i = 0; i < SelfCheckData.Centers.Length; i++)
            {
                var (text, expected) = SelfCheckData.Centers[i];
                Expect(Bits(new Viewport(text, "0").CenterReDouble), expected, "case " + i.ToString(CultureInfo.InvariantCulture));
            }
        }

        private static void CheckTurns()
        {
            foreach (var (k, n, re, im) in SelfCheckData.Turns)
            {
                var (gotRe, gotIm) = HeatonLife.Turns.Cis(k, n);
                string what = "cis_turns(" + k.ToString(CultureInfo.InvariantCulture) + ", " + n.ToString(CultureInfo.InvariantCulture) + ")";
                Expect(Bits(gotRe), re, what);
                Expect(Bits(gotIm), im, what);
            }
        }

        private static void CheckFloatExp()
        {
            for (int i = 0; i < SelfCheckData.FloatExp.Length; i++)
            {
                var (op, am, ae, bm, be, value, bits, em, ee) = SelfCheckData.FloatExp[i];
                string what = op + " #" + i.ToString(CultureInfo.InvariantCulture);
                FloatExp got;
                switch (op)
                {
                    case "add":
                        got = FloatExp.Add(X(am, ae), X(bm, be));
                        break;
                    case "mul":
                        got = FloatExp.Mul(X(am, ae), X(bm, be));
                        break;
                    case "div":
                        got = FloatExp.Div(X(am, ae), X(bm, be));
                        break;
                    case "compare":
                        Expect(FloatExp.Compare(X(am, ae), X(bm, be)), ee, what);
                        continue;
                    case "to_double":
                        Expect(Bits(X(am, ae).ToDouble()), em, what);
                        continue;
                    case "from_fixed":
                        got = FloatExp.FromFixed(BigInteger.Parse(value, CultureInfo.InvariantCulture), bits);
                        break;
                    case "normalize":
                        got = FloatExp.Normalize(Double(am), ae);
                        break;
                    default:
                        throw new Failed("unknown operation " + op);
                }
                Expect(Bits(got.M), em, what);
                Expect(got.E, ee, what);
            }
        }

        private static void CheckReferenceOrbit()
        {
            using (ReferenceOrbit.Uncached())
            {
                var (re, im) = ReferenceOrbit.Mandelbrot(SelfCheckData.OrbitRe, SelfCheckData.OrbitIm, SelfCheckData.OrbitZoom, SelfCheckData.OrbitMaxIter);
                Expect(re.Length, SelfCheckData.OrbitMaxIter + 1, "length");
                foreach (var (index, sampleRe, sampleIm) in SelfCheckData.OrbitSamples)
                {
                    string what = "Z[" + index.ToString(CultureInfo.InvariantCulture) + "]";
                    Expect(Bits(re[index]), sampleRe, what);
                    Expect(Bits(im[index]), sampleIm, what);
                }
                foreach (var (text, expected) in SelfCheckData.OrbitTies)
                {
                    var (tieRe, _) = ReferenceOrbit.Mandelbrot(text, "0", SelfCheckData.OrbitZoom, 1);
                    Expect(Bits(tieRe[1]), expected, "Z[1] at " + text.Substring(0, 12) + "...");
                }
            }
        }

        private static void CheckNavigation()
        {
            foreach (var n in SelfCheckData.Navigation)
            {
                var viewport = new Viewport(n.Re, n.Im, n.Zoom);
                Viewport got = n.Op == "pan"
                    ? (double.IsNaN(n.NewZoom)
                        ? HeatonLife.Navigation.Pan(viewport, n.Dx, n.Dy, n.Width, n.Height)
                        : HeatonLife.Navigation.Pan(viewport, n.Dx, n.Dy, n.Width, n.Height, n.NewZoom))
                    : HeatonLife.Navigation.ZoomAt(viewport, n.Dx, n.Dy, n.Width, n.Height, n.NewZoom);
                if (got.CenterRe != n.ExpectedRe || got.CenterIm != n.ExpectedIm || !got.ZoomLog10.Equals(n.ExpectedZoom))
                    throw new Failed(n.Op + ": the moved center differs");
            }
        }

        private static void CheckMergeLife()
        {
            int rows = SelfCheckData.MergeLifeRows, cols = SelfCheckData.MergeLifeCols;
            var lattice = new byte[rows * cols * 3];
            uint state = SelfCheckData.MergeLifeSeed;
            for (int i = 0; i < lattice.Length; i++)
            {
                state = unchecked(state * 1664525u + 1013904223u);
                lattice[i] = (byte)(state >> 24);
            }
            var sim = new MergeLife(SelfCheckData.MergeLifeRule, cols, rows);
            sim.SetState(lattice);
            sim.Step(SelfCheckData.MergeLifeSteps);
            Expect(DigestBytes(sim.State), SelfCheckData.MergeLifeDigest, "digest");
        }

        private static void CheckGrayScott()
        {
            var sim = new GrayScott(SelfCheckData.GrayScottWidth, SelfCheckData.GrayScottHeight,
                SelfCheckData.GrayScottDu, SelfCheckData.GrayScottDv, SelfCheckData.GrayScottFeed,
                SelfCheckData.GrayScottKill, SelfCheckData.GrayScottDt);
            sim.SeedCenter();
            sim.Step(SelfCheckData.GrayScottSteps);
            var state = sim.State;
            var values = new double[state.Length];
            state.CopyTo(values);
            Expect(DigestDoubles(values, false), SelfCheckData.GrayScottDigest, "digest");
        }

        private static void Render(string name)
        {
            var r = Array.Find(SelfCheckData.Renders, entry => entry.Name == name);
            if (r.Name == null)
                throw new Failed("no data for " + name);
            var viewport = new Viewport(r.Re, r.Im, r.Zoom);
            var counts = new int[r.Width * r.Height];
            using (ReferenceOrbit.Uncached())
            {
                int[]? applications = null;
                switch (r.Family)
                {
                    case "mandelbrot":
                        var mandelbrot = new Mandelbrot(r.MaxIter, r.EscapeRadius, 1, r.Bla);
                        applications = new int[counts.Length];
                        mandelbrot.Fields(r.Width, r.Height, viewport, counts, applications);
                        break;
                    case "julia":
                        new Julia(r.CRe, r.CIm, r.MaxIter, r.EscapeRadius).Iterations(r.Width, r.Height, viewport, counts);
                        break;
                    default:
                        new BurningShip(r.MaxIter, r.EscapeRadius).Iterations(r.Width, r.Height, viewport, counts);
                        break;
                }
                Expect(DigestInt32(counts), r.Iterations, "counts");
                if (!r.Bla)
                    return;
                Expect(DigestInt32(applications!), r.Applications, "BLA applications");
                var words = new List<double>();
                var entries = new List<int>();
                if (r.Zoom > FractalEngine.T1MaxZoom)
                {
                    var (re, im, small) = ReferenceOrbit.ComputeX(ReferenceOrbit.Kind.Mandelbrot, r.Re, r.Im, r.Zoom, r.MaxIter, 0.0, 0.0);
                    var orbit = new PerturbationT2.Orbit(re, im, small);
                    int samples = (int)Math.Min(re.Length, (long)r.MaxIter + 1);
                    var table = BlaTable.BuildX(re, im, orbit.Small, samples, r.EscapeRadius, BlaTable.FrameDcBoundExponent(r.Width, r.Height, viewport));
                    for (int level = 0; level < table.Levels; level++)
                    {
                        entries.Add(table.R[level].Length);
                        words.AddRange(table.Ar[level]);
                        words.AddRange(table.Ai[level]);
                        words.AddRange(table.Br[level]);
                        words.AddRange(table.Bi[level]);
                        foreach (FloatExp radius in table.R[level])
                            words.Add(radius.M);
                        foreach (FloatExp radius in table.R[level])
                            words.Add(radius.E);
                    }
                }
                else
                {
                    var (re, im) = ReferenceOrbit.Compute(ReferenceOrbit.Kind.Mandelbrot, r.Re, r.Im, r.Zoom, r.MaxIter, 0.0, 0.0);
                    int samples = (int)Math.Min(re.Length, (long)r.MaxIter + 1);
                    var table = BlaTable.Build(re, im, samples, r.EscapeRadius, BlaTable.FrameDcBound(r.Width, r.Height, viewport));
                    for (int level = 0; level < table.Levels; level++)
                    {
                        entries.Add(table.R[level].Length);
                        words.AddRange(table.Ar[level]);
                        words.AddRange(table.Ai[level]);
                        words.AddRange(table.Br[level]);
                        words.AddRange(table.Bi[level]);
                        words.AddRange(table.R[level]);
                    }
                }
                if (entries.Count != r.Entries.Length)
                    throw new Failed("BLA table levels: " + entries.Count.ToString(CultureInfo.InvariantCulture) + " != " + r.Entries.Length.ToString(CultureInfo.InvariantCulture));
                for (int level = 0; level < entries.Count; level++)
                    Expect(entries[level], r.Entries[level], "BLA table level " + level.ToString(CultureInfo.InvariantCulture));
                Expect(DigestDoubles(words, true), r.Table, "BLA table");
            }
        }

        private static PerturbationT2.Orbit Orbit(ulong[] samples, (int Index, ulong ReM, long ReE, ulong ImM, long ImE)[] small)
        {
            var re = new double[samples.Length / 2];
            var im = new double[re.Length];
            for (int i = 0; i < re.Length; i++)
            {
                re[i] = Double(samples[2 * i]);
                im[i] = Double(samples[2 * i + 1]);
            }
            var index = new int[small.Length];
            var smallRe = new FloatExp[small.Length];
            var smallIm = new FloatExp[small.Length];
            for (int i = 0; i < small.Length; i++)
            {
                index[i] = small[i].Index;
                smallRe[i] = X(small[i].ReM, small[i].ReE);
                smallIm[i] = X(small[i].ImM, small[i].ImE);
            }
            return new PerturbationT2.Orbit(re, im, new ReferenceOrbit.SmallSamples(index, smallRe, smallIm));
        }

        private static void Pair((ulong ReM, long ReE, ulong ImM, long ImE)? value, out FloatExp re, out FloatExp im)
        {
            if (value is (ulong, long, ulong, long) pair)
            {
                re = X(pair.Item1, pair.Item2);
                im = X(pair.Item3, pair.Item4);
            }
            else
            {
                re = FloatExp.Zero;
                im = FloatExp.Zero;
            }
        }

        private static void CheckT2Steps()
        {
            foreach (var c in SelfCheckData.T2Steps)
            {
                var orbit = Orbit(c.Samples, c.Small);
                var rebase = c.HasRebase ? Orbit(c.RebaseSamples, c.RebaseSmall) : orbit;
                Pair(c.Delta0, out FloatExp d0r, out FloatExp d0i);
                Pair(c.DeltaC, out FloatExp dcr, out FloatExp dci);
                Pair(c.D0, out FloatExp dd0r, out FloatExp dd0i);
                bool hasAdd = c.Add.HasValue;
                FloatExp add = hasAdd ? X(c.Add!.Value.M, c.Add.Value.E) : FloatExp.Zero;
                BlaTableX? table = null;
                if (c.DcExponent.HasValue)
                {
                    int samples = Math.Min(orbit.Re.Length, c.MaxIter + 1);
                    table = BlaTable.BuildX(orbit.Re, orbit.Im, orbit.Small, samples, c.EscapeRadius, c.DcExponent.Value);
                }
                int count = PerturbationT2.Perturb(
                    orbit, rebase, d0r, d0i, dcr, dci, c.MaxIter, c.EscapeRadius,
                    c.HasDerivative, dd0r, dd0i, add, hasAdd, table,
                    out double finalRe, out double finalIm, out double dr, out double di, out long dExponent, out int applied);
                Expect(count, c.Count, c.Name + ": count");
                Expect(Bits(finalRe), c.Final.Re, c.Name + ": final z");
                Expect(Bits(finalIm), c.Final.Im, c.Name + ": final z");
                Expect(Bits(dr), c.Derivative.Re, c.Name + ": derivative");
                Expect(Bits(di), c.Derivative.Im, c.Name + ": derivative");
                Expect(dExponent, c.Derivative.Exponent, c.Name + ": derivative");
                if (table == null)
                    continue;
                Expect(applied, c.Applications, c.Name + ": applications");
                var words = new List<double>();
                for (int level = 0; level < table.Levels; level++)
                {
                    words.AddRange(table.Ar[level]);
                    words.AddRange(table.Ai[level]);
                    words.AddRange(table.Br[level]);
                    words.AddRange(table.Bi[level]);
                    foreach (FloatExp radius in table.R[level])
                        words.Add(radius.M);
                    foreach (FloatExp radius in table.R[level])
                        words.Add(radius.E);
                }
                Expect(DigestDoubles(words, true), c.Table, c.Name + ": table");
            }
        }

        private static void CheckZoomPlan()
        {
            var bits = new List<ulong>();
            foreach (var p in SelfCheckData.ZoomPlans)
            {
                var schedule = new ZoomSchedule(Double(p.HoldStart), Double(p.EaseIn), Double(p.EaseOut), Double(p.HoldEnd));
                var plan = new ZoomPlan(Double(p.Start), Double(p.End), p.Frames, p.Fps, schedule);
                foreach (double zoom in plan.Zooms())
                    bits.Add(Bits(zoom));
            }
            Expect(DigestUInt64(bits.ToArray()), SelfCheckData.ZoomPlansDigest, "digest");
        }

        private static void CheckColor()
        {
            Expect(DigestBytes(Colormaps.Get(SelfCheckData.LutName)), SelfCheckData.LutDigest, SelfCheckData.LutName + " LUT");

            var frame = Doubles(SelfCheckData.ApplyFrame);
            Expect(DigestBytes(Colormaps.ApplyFloat(frame, Colormaps.Get(SelfCheckData.ApplyName))), SelfCheckData.ApplyDigest, "colormap");

            foreach (var lookup in SelfCheckData.Lookups)
            {
                double[] values = Doubles(lookup.T);
                var rgb = new byte[values.Length * 3];
                Colormaps.ApplyPhase(
                    values, lookup.Width, Colormaps.Get(lookup.Cmap), rgb, lookup.Mirror ? PhaseWrap.Mirror : PhaseWrap.Cyclic,
                    lookup.Antialias, lookup.Dither, lookup.FrameIndex, lookup.Interior[0], lookup.Interior[1], lookup.Interior[2]);
                Expect(DigestBytes(rgb), lookup.Digest, lookup.Name);
            }

            var mu = Doubles(SelfCheckData.PhaseMu);
            var parameters = new PhaseParams(
                Double(SelfCheckData.PhaseCyclesPerIteration), Double(SelfCheckData.PhaseCyclesPerOctave),
                Double(SelfCheckData.PhaseOffset), Double(SelfCheckData.PhaseAnchor));
            var t = new double[mu.Length];
            FractalColor.DepthPhase(mu, Double(SelfCheckData.PhaseZoom), parameters, t);
            Expect(DigestDoubles(t, true), SelfCheckData.PhaseDigest, "depth phase");
        }
    }
}
