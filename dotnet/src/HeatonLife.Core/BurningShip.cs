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
        public double EscapeRadius { get; }

        public BurningShip(int maxIter = 500, double escapeRadius = 1000.0)
        {
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
        public (double[] Render, int[] Counts) RenderAndCounts(int width, int height, Viewport viewport)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, null, null, counts, mu);
            return (FractalEngine.NormalizeRender(mu), counts);
        }

        /// <summary>T1 variant of <see cref="RenderAndCounts(int,int,Viewport)"/>.</summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, orbitRe, orbitIm, counts, mu);
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
            double[]? mu)
        {
            if (counts.Length != width * height)
                throw new ArgumentException($"expected {width * height} counts, got {counts.Length}");
            bool t1 = orbitRe != null;
            if (t1)
                FractalEngine.RequireT1(viewport);
            else
                FractalEngine.RequireT0(viewport);
            double ps = FractalEngine.PixelScale(width, viewport);
            double centerRe = t1 ? 0.0 : viewport.CenterReDouble;
            double centerIm = t1 ? 0.0 : viewport.CenterImDouble;
            double r2 = EscapeRadius * EscapeRadius;
            double logR = Math.Log(EscapeRadius);
            for (int y = 0; y < height; y++)
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
        }
    }
}
