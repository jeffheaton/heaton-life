using System;

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

        /// <summary>Complex-plane distance between adjacent pixel centers (float64).</summary>
        public static double PixelScale(int width, Viewport viewport) =>
            Math.Pow(10.0, Math.Log10(BaseSpan / width) - viewport.ZoomLog10);

        /// <summary>Per-pixel real offset from the viewport center for column x.</summary>
        public static double OffsetRe(int x, int width, double pixelScale) =>
            (x + 0.5 - width / 2.0) * pixelScale;

        /// <summary>Per-pixel imaginary offset for row y; im decreases downward.</summary>
        public static double OffsetIm(int y, int height, double pixelScale) =>
            -(y + 0.5 - height / 2.0) * pixelScale;

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

        /// <summary>
        /// Software fused multiply-add: round(a*b + c) with a single rounding.
        /// netstandard2.1 has no Math.FusedMultiplyAdd, and Unity must run this, so it
        /// is built from error-free transforms (Dekker TwoProduct + TwoSum) — plain IEEE
        /// ops only, valid for the well-scaled magnitudes these iterations produce.
        /// The test suite pins it bitwise against the hardware intrinsic.
        /// </summary>
        internal static double Fma(double a, double b, double c)
        {
            const double split = 134217729.0; // 2^27 + 1, Veltkamp splitting constant
            double p = a * b;
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
        /// One z^2 + c pixel; returns the 1-based escape iteration or -1. On escape,
        /// the final z is reported for smooth coloring (zero when interior).
        /// </summary>
        internal static int EscapeZ2(
            double zr, double zi, double cr, double ci, int maxIter, double r2,
            out double finalRe, out double finalIm)
        {
            for (int it = 1; it <= maxIter; it++)
            {
                var (sr, si) = ComplexMul(zr, zi, zr, zi);
                zr = sr + cr;
                zi = si + ci;
                if (zr * zr + zi * zi > r2)
                {
                    finalRe = zr;
                    finalIm = zi;
                    return it;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
            return -1;
        }

        /// <summary>One Burning Ship pixel: z = (|Re z| + i |Im z|)^2 + c.</summary>
        internal static int EscapeShip(
            double zr, double zi, double cr, double ci, int maxIter, double r2,
            out double finalRe, out double finalIm)
        {
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
                    return it;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
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
        {
            if (progress == null)
            {
                ForRows(height, workers, row);
                return;
            }
            progress.Begin(height);
            Parallelism.For(height, workers, y =>
            {
                row(y);
                progress.Step();
            });
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
            int escaped = 0;
            foreach (double value in mu)
                if (value > 0.0)
                    escaped++;
            if (escaped == 0)
                return result; // sqrt(0) everywhere
            var sorted = new double[escaped];
            int k = 0;
            foreach (double value in mu)
                if (value > 0.0)
                    sorted[k++] = value;
            Array.Sort(sorted);
            double lo = Percentile(sorted, 1.0);
            double hi = Percentile(sorted, 99.0);
            for (int i = 0; i < mu.Length; i++)
            {
                double value = 0.0;
                if (mu[i] > 0.0)
                {
                    value = hi <= lo
                        ? 0.6 // featureless frame: one mid tone
                        : Math.Clamp((mu[i] - lo) / (hi - lo), 0.02, 1.0);
                }
                result[i] = Math.Sqrt(value);
            }
            return result;
        }

        /// <summary>
        /// numpy's 'linear' percentile on sorted data, including its lerp branch that
        /// switches to the b-anchored form at t >= 0.5.
        /// </summary>
        internal static double Percentile(double[] sorted, double q)
        {
            int n = sorted.Length;
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
}
