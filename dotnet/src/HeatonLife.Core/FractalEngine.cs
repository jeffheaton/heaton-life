using System;
using System.Numerics;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// Escape-time machinery shared by the fractal fields (spec/fractals.md).
    /// Counts convention: counts[i] = n where n is the 1-based iteration at which
    /// |z| first exceeds the escape radius; -1 if it never does within max_iter.
    /// All arithmetic is float64 with the reference implementation's exact operation
    /// order, so int32 outputs are bit-exact against the shared vectors.
    /// </summary>
    public static class FractalEngine
    {
        /// <summary>Beyond this, float64 pixel spacing collapses — perturbation takes over.</summary>
        public const double T0MaxZoom = 12.0;

        /// <summary>Beyond this, float64 pixel *deltas* underflow — future floatexp tier.</summary>
        public const double T1MaxZoom = 290.0;

        public const double BaseSpan = 4.0;

        /// <summary>
        /// Complex-plane distance between adjacent pixel centers (float64).
        /// spec/fractals.md "Pixel mapping": one float64 division, one
        /// deterministic power (spec/pow10.md), one float64 multiply. Never the
        /// historical Math.Pow(10, Math.Log10(4/width) - zoom) — its two libm
        /// calls made the bit-exact tier platform-dependent at fractional zooms.
        /// </summary>
        public static double PixelScale(int width, Viewport viewport) =>
            PixelScale(width, viewport.ZoomLog10);

        /// <summary>
        /// <see cref="PixelScale(int, Viewport)"/> for a zoom with no viewport at hand — the
        /// one expression every consumer shares, so a navigation step and a render agree.
        /// </summary>
        public static double PixelScale(int width, double zoomLog10) =>
            (BaseSpan / width) * Pow10.Compute(-zoomLog10);

        /// <summary>
        /// Whether the viewport's off-center reference lies within its frame — the
        /// suggested rule for keeping a reference while panning (spec/deep-zoom.md
        /// "Off-center reference"); true when there is none. Advisory: a frame is defined
        /// for any reference.
        /// </summary>
        public static bool ReferenceOnScreen(int width, int height, Viewport viewport)
        {
            double ps = PixelScale(width, viewport);
            return Math.Abs(viewport.ReferenceOffsetRe) <= width / 2.0 * ps
                && Math.Abs(viewport.ReferenceOffsetIm) <= height / 2.0 * ps;
        }

        /// <summary>Per-pixel real offset from the viewport center for column x.</summary>
        public static double OffsetRe(int x, int width, double pixelScale) =>
            (x + 0.5 - width / 2.0) * pixelScale;

        /// <summary>Per-pixel imaginary offset for row y; im decreases downward.</summary>
        public static double OffsetIm(int y, int height, double pixelScale) =>
            -(y + 0.5 - height / 2.0) * pixelScale;

        /// <summary>
        /// Column x's real delta from an off-center reference: fl(d + offset), with
        /// d = round64(center − reference) (<see cref="Viewport.ReferenceOffsetRe"/>) — one
        /// add, the components kept apart (spec/deep-zoom.md "Off-center reference"). Every
        /// family forms its deltas here; the test suites pin it against a shared table.
        /// </summary>
        internal static double DeltaRe(int x, int width, double pixelScale, double referenceOffsetRe) =>
            referenceOffsetRe + OffsetRe(x, width, pixelScale);

        /// <summary>Row y's imaginary delta from an off-center reference: fl(d + offset).</summary>
        internal static double DeltaIm(int y, int height, double pixelScale, double referenceOffsetIm) =>
            referenceOffsetIm + OffsetIm(y, height, pixelScale);

        /// <summary>
        /// The tier a zoom selects (spec/fractals.md "Tiering"), for a host deciding what
        /// a frame will cost before it asks: <see cref="FractalTier.T0"/> through 1e12,
        /// <see cref="FractalTier.T1"/> through 1e290, and <see cref="FractalTier.T2"/>
        /// beyond — reserved for floatexp, so rendering there throws today. What a family
        /// can render is its own MaxZoomLog10 (Newton stops at T0).
        /// </summary>
        public static FractalTier TierOf(double zoomLog10)
        {
            if (zoomLog10 <= T0MaxZoom)
                return FractalTier.T0;
            return zoomLog10 <= T1MaxZoom ? FractalTier.T1 : FractalTier.T2;
        }

        /// <summary>
        /// For families with NO perturbation tier — Newton only (spec/fractals.md:
        /// "float64 only, zoom &lt;= 1e12"; spec/deep-zoom.md: "no perturbation tier").
        /// The escape-time fields no longer use this: they reach T1 on their own now
        /// that <see cref="ReferenceOrbit"/> can produce a reference.
        /// </summary>
        internal static void RequireT0(Viewport viewport)
        {
            if (viewport.ZoomLog10 > T0MaxZoom)
                throw new ArgumentException(
                    $"zoom 1e{viewport.ZoomLog10:g} exceeds the float64 direct tier (1e{T0MaxZoom:g}); " +
                    "this family has no perturbation tier");
        }

        internal static void RequireT1(Viewport viewport)
        {
            if (viewport.ZoomLog10 > T1MaxZoom)
                throw new ArgumentException(
                    $"zoom 1e{viewport.ZoomLog10:g} exceeds the float64 perturbation tier " +
                    $"(~1e{T1MaxZoom:g}); the floatexp tier is not implemented yet");
        }

        /// <summary>
        /// Which tier renders this viewport. spec/deep-zoom.md: "Tier selection is
        /// automatic and invisible to the caller" — so the ZOOM decides, never
        /// whether the caller happened to hand us an orbit. Selecting on orbit
        /// presence let two callers with the same viewport get different counts,
        /// because T0 and T1 legitimately disagree on a few percent of boundary
        /// pixels (spec/fractals.md "Tiering"). At or below the T0 ceiling a
        /// supplied orbit is therefore ignored, which is exactly what the Python
        /// reference does — it tiers on zoom alone and takes no orbit at all.
        /// </summary>
        internal static bool IsPerturbationTier(Viewport viewport)
        {
            if (viewport.ZoomLog10 <= T0MaxZoom)
                return false;
            RequireT1(viewport);
            return true;
        }

        /// <summary>
        /// The reference's complex multiply, (a+bi)(c+di): NumPy's SIMD kernels contract
        /// one product per component into an FMA — real = fma(a, c, -(b*d)),
        /// imag = fma(a, d, b*c) — verified exhaustively against numpy 2.x. IEEE 754
        /// specifies fma exactly, so this is deterministic everywhere. Bit-exact fractal
        /// outputs require matching it wherever the reference runs its multiply ufunc.
        /// </summary>
        internal static (double Re, double Im) ComplexMul(double a, double b, double c, double d) =>
            (Fma(a, c, -(b * d)), Fma(a, d, b * c));

        /// <summary>2^-968: below this |a*b| the Dekker product's error term can underflow.</summary>
        private static readonly double TinyProduct = BitConverter.Int64BitsToDouble(55L << 52);

        /// <summary>
        /// 2^-914: an addend this large has a half-ulp (even one binade down) above any
        /// |a*b| &lt; 2^-968, so the correctly rounded sum is the addend itself.
        /// </summary>
        private static readonly double DominantAddend = BitConverter.Int64BitsToDouble(109L << 52);

        /// <summary>2^995: at or above this, Veltkamp's split (x * 2^27) or TwoSum can overflow.</summary>
        private static readonly double HugeOperand = BitConverter.Int64BitsToDouble(2018L << 52);

        private static bool IsFinite(double x) => !double.IsNaN(x) && !double.IsInfinity(x);

        /// <summary>
        /// Software fused multiply-add: round(a*b + c) with a single rounding, as IEEE 754
        /// defines it and NumPy's hardware FMA computes it. netstandard2.1 has no
        /// Math.FusedMultiplyAdd, and Unity must run this, so the common case is built
        /// from error-free transforms (Dekker TwoProduct + TwoSum) — plain IEEE ops. Those
        /// are exact only while the product's low bits stay representable, |a*b| &gt;=
        /// 2^-968; below that the exact sum is formed in integers and rounded once
        /// (spec/deep-zoom.md "Float-determinism gotchas"). Julia T1 lands there — its
        /// delta has no dc floor — and the Dekker form differed from the hardware in a
        /// third of such cases. The test suite pins the whole thing bitwise against the
        /// hardware intrinsic.
        /// </summary>
        internal static double Fma(double a, double b, double c)
        {
            const double split = 134217729.0; // 2^27 + 1, Veltkamp splitting constant
            double p = a * b;
            if (a == 0.0 || b == 0.0 || !IsFinite(a) || !IsFinite(b) || !IsFinite(c))
            {
                // Finite factors keep an exact finite product even where p overflowed,
                // so an infinite c wins (p + c would make inf - inf = NaN of it).
                if (double.IsInfinity(c) && IsFinite(a) && IsFinite(b))
                    return c;
                return p + c;                                  // an exact signed-zero product, or IEEE's inf/NaN rules
            }
            double absP = Math.Abs(p);
            if (absP < TinyProduct)
                return Math.Abs(c) >= DominantAddend ? c : ExactFma(a, b, c);
            if (Math.Abs(a) >= HugeOperand || Math.Abs(b) >= HugeOperand
                || absP >= HugeOperand || Math.Abs(c) >= HugeOperand)
                return ExactFma(a, b, c);                      // Veltkamp's split or TwoSum would overflow
            double ta = split * a;
            double ahi = ta - (ta - a);
            double alo = a - ahi;
            double tb = split * b;
            double bhi = tb - (tb - b);
            double blo = b - bhi;
            double e = ((ahi * bhi - p) + ahi * blo + alo * bhi) + alo * blo; // p + e == a*b
            double s = p + c;
            double v = s - p;
            double t = (p - (s - v)) + (c - v); // s + t == p + c
            return s + (t + e);
        }

        /// <summary>
        /// round(a*b + c) from the exact integer sum, for finite nonzero a and b and a
        /// finite c. Rare enough that BigInteger is affordable: it runs only where the
        /// product has left the range the error-free transforms cover.
        /// </summary>
        private static double ExactFma(double a, double b, double c)
        {
            Decompose(a, out BigInteger ma, out int ea);
            Decompose(b, out BigInteger mb, out int eb);
            BigInteger sum = ma * mb;
            int exponent = ea + eb;                            // value = sum * 2^exponent
            if (c != 0.0)
            {
                Decompose(c, out BigInteger mc, out int ec);
                int common = Math.Min(exponent, ec);
                sum = (sum << (exponent - common)) + (mc << (ec - common));
                exponent = common;
                if (sum.IsZero)
                    return 0.0;                                // exact cancellation: +0 under round-to-nearest
            }
            bool negative = sum.Sign < 0;
            BigInteger magnitude = negative ? -sum : sum;
            return exponent >= 0
                ? DecimalText.RatioToDouble(negative, magnitude << exponent, BigInteger.One)
                : DecimalText.RatioToDouble(negative, magnitude, BigInteger.One << -exponent);
        }

        /// <summary>A finite double as signed mantissa * 2^exponent, exactly.</summary>
        private static void Decompose(double value, out BigInteger mantissa, out int exponent)
        {
            long bits = BitConverter.DoubleToInt64Bits(value);
            int field = (int)((bits >> 52) & 0x7FF);
            long fraction = bits & 0xFFFFFFFFFFFFFL;
            if (field == 0)
            {
                exponent = -1074;                              // subnormal
            }
            else
            {
                fraction |= 1L << 52;
                exponent = field - 1075;
            }
            mantissa = bits < 0 ? -(BigInteger)fraction : fraction;
        }

        /// <summary>
        /// Whether c lies inside Mandelbrot's main cardioid or period-2 bulb by more than
        /// 1e-12 in the test's own measure — interior, provably, so a T0 render with an
        /// escape radius of at least 2 need not iterate it (its orbit stays within |z| &lt; 2;
        /// a smaller radius can be crossed, near 1.27 in the bulb) (spec/fractals.md
        /// "Interior shortcuts"). Plain float64, this operation order, as the Python
        /// reference's engine.cardioid_or_bulb.
        /// </summary>
        internal static bool CardioidOrBulb(double cr, double ci)
        {
            double xq = cr - 0.25;
            double q = xq * xq + ci * ci;
            return q * (q + xq) < 0.25 * (ci * ci) - 1e-12
                || (cr + 1.0) * (cr + 1.0) + ci * ci < 0.0625 - 1e-12;
        }

        /// <summary>
        /// One z^2 + c pixel; returns the 1-based escape iteration or -1. On escape,
        /// the final z is reported for smooth coloring (zero when interior). Exact cycle
        /// detection (spec/fractals.md "Interior shortcuts"): after the escape test at
        /// iteration n fails, a z_n equal (IEEE ==, both parts) to the state saved at the
        /// last power-of-two iteration is interior — the iteration is deterministic, so a
        /// repeated state repeats forever — and z_n is saved when n is a power of two.
        /// </summary>
        internal static int EscapeZ2(
            double zr, double zi, double cr, double ci, int maxIter, double r2,
            out double finalRe, out double finalIm, out PixelStatus status)
        {
            double savedRe = 0.0, savedIm = 0.0;
            bool haveSaved = false;
            for (int it = 1; it <= maxIter; it++)
            {
                var (sr, si) = ComplexMul(zr, zi, zr, zi);
                zr = sr + cr;
                zi = si + ci;
                if (zr * zr + zi * zi > r2)
                {
                    finalRe = zr;
                    finalIm = zi;
                    status = PixelStatus.Escaped;
                    return it;
                }
                if (haveSaved && zr == savedRe && zi == savedIm)
                {
                    finalRe = 0.0;
                    finalIm = 0.0;
                    status = PixelStatus.Cycle;
                    return -1;
                }
                if ((it & (it - 1)) == 0)
                {
                    savedRe = zr;
                    savedIm = zi;
                    haveSaved = true;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
            status = PixelStatus.Exhausted;
            return -1;
        }

        /// <summary>One Burning Ship pixel: z = (|Re z| + i |Im z|)^2 + c, with EscapeZ2's cycle detection.</summary>
        internal static int EscapeShip(
            double zr, double zi, double cr, double ci, int maxIter, double r2,
            out double finalRe, out double finalIm, out PixelStatus status)
        {
            double savedRe = 0.0, savedIm = 0.0;
            bool haveSaved = false;
            for (int it = 1; it <= maxIter; it++)
            {
                double fr = Math.Abs(zr);
                double fi = Math.Abs(zi);
                var (sr, si) = ComplexMul(fr, fi, fr, fi);
                zr = sr + cr;
                zi = si + ci;
                if (zr * zr + zi * zi > r2)
                {
                    finalRe = zr;
                    finalIm = zi;
                    status = PixelStatus.Escaped;
                    return it;
                }
                if (haveSaved && zr == savedRe && zi == savedIm)
                {
                    finalRe = 0.0;
                    finalIm = 0.0;
                    status = PixelStatus.Cycle;
                    return -1;
                }
                if ((it & (it - 1)) == 0)
                {
                    savedRe = zr;
                    savedIm = zi;
                    haveSaved = true;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
            status = PixelStatus.Exhausted;
            return -1;
        }

        /// <summary>
        /// Smooth iteration value for one pixel (spec/render.md, ε tier):
        /// mu = n + 1 - log2(log|z| / log R) for escaped pixels, 0 for interior.
        /// Public because the Python reference's `smooth_iterations` is: without it
        /// a consumer can only get the percentile-stretched render, never the raw mu.
        /// |z| uses sqrt(re² + im²); the reference's hypot may differ in the last
        /// ulp, absorbed by the ε tier.
        /// </summary>
        public static double SmoothMu(int count, double finalRe, double finalIm, double logEscapeRadius)
        {
            if (count <= 0)
                return 0.0;
            double absZ = Math.Sqrt(finalRe * finalRe + finalIm * finalIm);
            return count + 1.0 - Log2(Math.Log(absZ) / logEscapeRadius);
        }

        /// <summary>
        /// Row-parallel driver for the per-pixel loops (spec/fractals.md "Parallel
        /// rendering"): every pixel is independent and rows write disjoint slices,
        /// so the output is bit-identical for any worker count or schedule.
        /// </summary>
        public static void ForRows(int height, int workers, Action<int> row) =>
            Parallelism.For(height, workers, row);

        /// <summary>
        /// <see cref="ForRows(int,int,Action{int})"/> that also counts finished rows
        /// into <paramref name="progress"/> for a host's progress readout. Purely
        /// observational: the rows run exactly as before, so output is bit-identical
        /// with or without it (spec/fractals.md "Parallel rendering").
        /// </summary>
        public static void ForRows(int height, int workers, Action<int> row, RenderProgress? progress)
            => ForRows(height, workers, row, progress, CancellationToken.None);

        /// <summary>
        /// <see cref="ForRows(int,int,Action{int},RenderProgress)"/> that a host can cancel:
        /// the token is checked before each row, and a canceled render throws
        /// OperationCanceledException with the output buffers partly written. Like
        /// progress it only observes the work: rows that run, run exactly as before.
        /// </summary>
        public static void ForRows(
            int height, int workers, Action<int> row, RenderProgress? progress, CancellationToken cancellationToken)
        {
            progress?.Begin(height);
            Action<int> body = progress == null ? row : y =>
            {
                row(y);
                progress.Step();
            };
            Parallelism.For(height, workers, body, cancellationToken);
        }

        /// <summary>
        /// Map smooth iterations to [0, 1] for colormapping; interior stays 0
        /// (spec/render.md). Per-frame percentile contrast stretch between the 1st and
        /// 99th escaped percentiles, floor 0.02, then sqrt. Presentation only — counts
        /// are the conformance output and are untouched.
        /// </summary>
        public static double[] NormalizeRender(double[] mu)
        {
            var result = new double[mu.Length];
            NormalizeRender(mu, result, new double[mu.Length]);
            return result;
        }

        /// <summary>
        /// <see cref="NormalizeRender(double[])"/> into caller buffers, allocating nothing:
        /// <paramref name="render"/> receives the result and <paramref name="scratch"/> (at
        /// least as long as <paramref name="mu"/>) holds the sorted escaped values. The
        /// same arithmetic in the same order, so the output is identical — a host keeps
        /// the raw smooth values and re-normalizes (or recolors) without re-rendering.
        /// <paramref name="scratch"/> is overwritten and must not be <paramref name="mu"/>;
        /// <paramref name="render"/> may be either.
        /// </summary>
        public static void NormalizeRender(double[] mu, double[] render, double[] scratch)
        {
            if (mu == null)
                throw new ArgumentNullException(nameof(mu));
            if (render == null || render.Length != mu.Length)
                throw new ArgumentException($"expected a render buffer of {mu?.Length} values", nameof(render));
            if (scratch == null || scratch.Length < mu.Length)
                throw new ArgumentException($"expected a scratch buffer of at least {mu.Length} values", nameof(scratch));
            if (ReferenceEquals(scratch, mu))
                throw new ArgumentException("scratch is overwritten, so it cannot be the mu array", nameof(scratch));
            int escaped = 0;
            foreach (double value in mu)
                if (value > 0.0)
                    scratch[escaped++] = value;
            if (escaped == 0)
            {
                Array.Clear(render, 0, render.Length);          // sqrt(0) everywhere
                return;
            }
            Array.Sort(scratch, 0, escaped);
            double lo = Percentile(scratch, escaped, 1.0);
            double hi = Percentile(scratch, escaped, 99.0);
            for (int i = 0; i < mu.Length; i++)
            {
                double value = 0.0;
                if (mu[i] > 0.0)
                {
                    value = hi <= lo
                        ? 0.6 // featureless frame: one mid tone
                        : Math.Clamp((mu[i] - lo) / (hi - lo), 0.02, 1.0);
                }
                render[i] = Math.Sqrt(value);
            }
        }

        /// <summary>np.percentile's linear method over the first <paramref name="n"/> sorted values.</summary>
        internal static double Percentile(double[] sorted, int n, double q)
        {
            double virtualIndex = q / 100.0 * (n - 1);
            int lo = (int)Math.Floor(virtualIndex);
            if (lo < 0)
                lo = 0;
            if (lo > n - 1)
                lo = n - 1;
            double t = virtualIndex - lo;
            double a = sorted[lo];
            double b = sorted[Math.Min(lo + 1, n - 1)];
            double diff = b - a;
            return t >= 0.5 ? b - diff * (1.0 - t) : a + diff * t;
        }

        /// <summary>log2 via ln ratio (netstandard2.1 has no Math.Log2); ε tier absorbs the ulp.</summary>
        internal static double Log2(double x) => Math.Log(x) / Ln2;

        private const double Ln2 = 0.6931471805599453;
    }

    /// <summary>
    /// How a pixel's count was decided (spec/fractals.md "Status"). A host tells
    /// "needs more iterations" (Exhausted) from "interior" (CardioidOrBulb, Cycle).
    /// </summary>
    public enum PixelStatus : byte
    {
        /// <summary>The pixel escaped: its count is positive.</summary>
        Escaped = 0,

        /// <summary>max_iter was reached with nothing proved; more iterations might escape.</summary>
        Exhausted = 1,

        /// <summary>Mandelbrot at T0: inside the main cardioid or the period-2 bulb, not iterated.</summary>
        CardioidOrBulb = 2,

        /// <summary>T0: the float64 state repeated exactly, so the pixel never escapes.</summary>
        Cycle = 3,
    }

    /// <summary>The precision tiers of spec/deep-zoom.md, selected by zoom alone.</summary>
    public enum FractalTier
    {
        /// <summary>Direct float64 escape time (zoom &lt;= 1e12).</summary>
        T0 = 0,

        /// <summary>Float64 perturbation against a bignum reference orbit (zoom &lt;= 1e290).</summary>
        T1 = 1,

        /// <summary>Beyond 1e290: reserved for floatexp; no family renders it yet.</summary>
        T2 = 2,
    }
}
