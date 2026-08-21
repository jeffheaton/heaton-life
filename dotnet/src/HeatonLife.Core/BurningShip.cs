using System;

namespace HeatonLife
{
    /// <summary>
    /// Burning Ship: z &lt;- (|Re z| + i |Im z|)^2 + c, c = pixel, z0 = 0 (spec/fractals.md).
    /// Bit-exact tier.
    /// </summary>
    public sealed class BurningShip
    {
        public int MaxIter { get; }

        /// <summary>Row-parallel worker count; output is identical for any value.</summary>
        public int Workers { get; }
        public double EscapeRadius { get; }

        public BurningShip(int maxIter = 500, double escapeRadius = 1000.0, int workers = 1)
        {
            if (workers < 1)
                throw new ArgumentException("workers must be positive");
            Workers = workers;
            if (maxIter < 1)
                throw new ArgumentException("max_iter must be positive");
            MaxIter = maxIter;
            EscapeRadius = escapeRadius;
        }

        /// <summary>T0 (direct float64) escape counts into <paramref name="counts"/>. Zoom &lt;= 1e12.</summary>
        public void Iterations(int width, int height, Viewport viewport, int[] counts)
            => Compute(width, height, viewport, null, null, counts, null);

        /// <summary>T0 escape counts, row-major (height, width). Zoom &lt;= 1e12.</summary>
        public int[] Iterations(int width, int height, Viewport viewport)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, counts);
            return counts;
        }

        /// <summary>
        /// T1 (perturbation + rebasing, diffabs) escape counts against a precomputed
        /// reference orbit for the viewport center. Zoom &lt;= 1e290.
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
            RenderProgress? progress = null)
        {
            if (counts.Length != width * height)
                throw new ArgumentException($"expected {width * height} counts, got {counts.Length}");
            // Zoom picks the tier, not orbit presence (spec/deep-zoom.md).
            bool t1 = FractalEngine.IsPerturbationTier(viewport);
            if (t1 && orbitRe == null)
            {
                // Deep zoom with no orbit handed in: make one. spec/deep-zoom.md
                // sanctions BigInteger fixed point for exactly this, and until it
                // existed the only reachable T1 render was a replay of a vector.
                (orbitRe, orbitIm) = ReferenceOrbit.BurningShip(viewport.CenterRe, viewport.CenterIm, viewport.ZoomLog10, MaxIter);
            }
            double ps = FractalEngine.PixelScale(width, viewport);
            double centerRe = t1 ? 0.0 : viewport.CenterReDouble;
            double centerIm = t1 ? 0.0 : viewport.CenterImDouble;
            double r2 = EscapeRadius * EscapeRadius;
            double logR = Math.Log(EscapeRadius);
            void Row(int y)
            {
                double oy = FractalEngine.OffsetIm(y, height, ps);
                for (int x = 0; x < width; x++)
                {
                    double ox = FractalEngine.OffsetRe(x, width, ps);
                    int count;
                    double fr, fi;
                    if (t1)
                        count = Perturbation.PerturbBurningShip(
                            orbitRe!, orbitIm!, ox, oy, MaxIter, EscapeRadius, out fr, out fi);
                    else
                        count = FractalEngine.EscapeShip(
                            0.0, 0.0, ox + centerRe, oy + centerIm, MaxIter, r2, out fr, out fi);
                    counts[y * width + x] = count;
                    if (mu != null)
                        mu[y * width + x] = FractalEngine.SmoothMu(count, fr, fi, logR);
                }
            }

            FractalEngine.ForRows(height, Workers, Row, progress);
        }
    }
}
