using System;
using System.Threading;

namespace HeatonLife
{
    /// <summary>Mandelbrot set: z &lt;- z^2 + c, c = pixel, z0 = 0 (spec/fractals.md). Bit-exact tier.</summary>
    public sealed class Mandelbrot
    {
        public int MaxIter { get; }

        /// <summary>Row-parallel worker count; output is identical for any value.</summary>
        public int Workers { get; }
        public double EscapeRadius { get; }

        public Mandelbrot(int maxIter = 500, double escapeRadius = 1000.0, int workers = 1)
        {
            if (maxIter < 1)
                throw new ArgumentException("max_iter must be positive");
            if (workers < 1)
                throw new ArgumentException("workers must be positive");
            MaxIter = maxIter;
            EscapeRadius = escapeRadius;
            Workers = workers;
        }

        /// <summary>
        /// Escape counts into <paramref name="counts"/>, tiered by zoom: T0 (direct float64)
        /// through 1e12, then T1 (perturbation against a reference orbit this call computes)
        /// through 1e290.
        /// </summary>
        public void Iterations(int width, int height, Viewport viewport, int[] counts)
            => Compute(width, height, viewport, null, null, counts, null);

        /// <summary>Escape counts, row-major (height, width), tiered by zoom through 1e290.</summary>
        public int[] Iterations(int width, int height, Viewport viewport)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, counts);
            return counts;
        }

        /// <summary>
        /// T1 (perturbation + rebasing) escape counts against a precomputed reference orbit
        /// for the viewport's reference point (<see cref="Viewport.OrbitCenterRe"/>: its center
        /// unless it names another) — Z_0..Z_n as parallel re/im arrays. Zoom &lt;= 1e290.
        /// </summary>
        public void Iterations(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm, int[] counts)
            => Compute(width, height, viewport, orbitRe, orbitIm, counts, null);

        /// <summary>T1 escape counts, allocating. Zoom &lt;= 1e290.</summary>
        public int[] Iterations(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, orbitRe, orbitIm, counts);
            return counts;
        }

        /// <summary>One computation, both consumers: the smooth render in [0,1] and the raw counts.</summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, RenderProgress? progress = null)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, null, null, counts, mu, progress);
            return (FractalEngine.NormalizeRender(mu), counts);
        }

        /// <summary>T1 variant of <see cref="RenderAndCounts(int,int,Viewport,RenderProgress)"/>.</summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm,
            RenderProgress? progress = null)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, orbitRe, orbitIm, counts, mu, progress);
            return (FractalEngine.NormalizeRender(mu), counts);
        }

        /// <summary>
        /// Escape counts and raw smooth values into caller buffers. Nothing is allocated per
        /// pixel, per iteration, or in proportion to the frame — only a T1 reference orbit
        /// the cache does not already hold, and a few small objects per call. The smooth
        /// value is spec/fractals.md's mu = n + 1 - log2(log|z| / log R), 0 where interior,
        /// before any normalization (<see cref="FractalEngine.NormalizeRender(double[], double[], double[])"/>
        /// makes the same render <see cref="Render(int,int,Viewport)"/> returns), so a host
        /// can recolor without re-rendering. <paramref name="smooth"/> may be null. Tiered
        /// by zoom through <see cref="MaxZoomLog10"/>.
        ///
        /// <paramref name="progress"/> and <paramref name="cancellationToken"/> only observe
        /// and stop the work: output is bit-identical with or without them. A canceled
        /// render throws OperationCanceledException with the buffers partly written, and
        /// a canceled reference orbit is never cached.
        /// </summary>
        public void Iterations(
            int width, int height, Viewport viewport, int[] counts, double[]? smooth,
            RenderProgress? progress = null, CancellationToken cancellationToken = default)
            => Compute(width, height, viewport, null, null, counts, smooth, progress, cancellationToken);

        /// <summary>
        /// <see cref="RenderAndCounts(int,int,Viewport,RenderProgress)"/> that a host can
        /// cancel (OperationCanceledException); a superseded frame stops within a row.
        /// </summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, RenderProgress? progress, CancellationToken cancellationToken)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, null, null, counts, mu, progress, cancellationToken);
            return (FractalEngine.NormalizeRender(mu), counts);
        }

        /// <summary>The deepest zoom this family renders: the T1 ceiling (spec/fractals.md "Tiering").</summary>
        public double MaxZoomLog10 => FractalEngine.T1MaxZoom;

        /// <summary>Smooth-colored field in [0,1] (Field protocol); interior is 0. ε tier.</summary>
        public double[] Render(int width, int height, Viewport viewport)
            => RenderAndCounts(width, height, viewport).Render;

        /// <summary>T1 variant of <see cref="Render(int,int,Viewport)"/>.</summary>
        public double[] Render(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm)
            => RenderAndCounts(width, height, viewport, orbitRe, orbitIm).Render;

        private void Compute(
            int width,
            int height,
            Viewport viewport,
            double[]? orbitRe,
            double[]? orbitIm,
            int[] counts,
            double[]? mu,
            RenderProgress? progress = null,
            CancellationToken cancellationToken = default)
        {
            if (counts.Length != width * height)
                throw new ArgumentException($"expected {width * height} counts, got {counts.Length}");
            if (mu != null && mu.Length != width * height)
                throw new ArgumentException($"expected {width * height} smooth values, got {mu.Length}");
            progress?.Reset();
            // Zoom picks the tier, not orbit presence (spec/deep-zoom.md).
            bool t1 = FractalEngine.IsPerturbationTier(viewport);
            if (t1 && orbitRe == null)
            {
                // Deep zoom with no orbit handed in: make one. spec/deep-zoom.md
                // sanctions BigInteger fixed point for exactly this, and until it
                // existed the only reachable T1 render was a replay of a vector.
                (orbitRe, orbitIm) = ReferenceOrbit.Compute(
                    ReferenceOrbit.Kind.Mandelbrot, viewport.OrbitCenterRe, viewport.OrbitCenterIm, viewport.ZoomLog10, MaxIter,
                    0.0, 0.0, progress, cancellationToken, whole: true);
            }
            double ps = FractalEngine.PixelScale(width, viewport);
            // Off-center reference: every T1 delta is fl(d + offset), d = round64(center -
            // reference), exact from the strings (FractalEngine.DeltaRe/DeltaIm).
            bool offCenter = t1 && viewport.HasReference;
            double dRe = offCenter ? viewport.ReferenceOffsetRe : 0.0;
            double dIm = offCenter ? viewport.ReferenceOffsetIm : 0.0;
            double centerRe = t1 ? 0.0 : viewport.CenterReDouble;
            double centerIm = t1 ? 0.0 : viewport.CenterImDouble;
            double r2 = EscapeRadius * EscapeRadius;
            double logR = Math.Log(EscapeRadius);
            void Row(int y)
            {
                double oy = offCenter ? FractalEngine.DeltaIm(y, height, ps, dIm) : FractalEngine.OffsetIm(y, height, ps);
                for (int x = 0; x < width; x++)
                {
                    double ox = offCenter ? FractalEngine.DeltaRe(x, width, ps, dRe) : FractalEngine.OffsetRe(x, width, ps);
                    int count;
                    double fr, fi;
                    if (t1)
                        count = Perturbation.PerturbZ2(
                            orbitRe!, orbitIm!, 0.0, 0.0, ox, oy, MaxIter, EscapeRadius, out fr, out fi);
                    else
                        count = FractalEngine.EscapeZ2(
                            0.0, 0.0, ox + centerRe, oy + centerIm, MaxIter, r2, out fr, out fi);
                    counts[y * width + x] = count;
                    if (mu != null)
                        mu[y * width + x] = FractalEngine.SmoothMu(count, fr, fi, logR);
                }
            }

            FractalEngine.ForRows(height, Workers, Row, progress, cancellationToken);
        }
    }
}
