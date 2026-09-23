using System;

namespace HeatonLife
{
    /// <summary>Julia set: z &lt;- z^2 + c, c fixed, z0 = pixel (spec/fractals.md). Bit-exact tier.</summary>
    public sealed class Julia
    {
        public double CRe { get; }
        public double CIm { get; }
        public int MaxIter { get; }

        /// <summary>Row-parallel worker count; output is identical for any value.</summary>
        public int Workers { get; }
        public double EscapeRadius { get; }

        public Julia(
            double cRe = -0.7269, double cIm = 0.1889, int maxIter = 500,
            double escapeRadius = 1000.0, int workers = 1)
        {
            if (maxIter < 1)
                throw new ArgumentException("max_iter must be positive");
            if (workers < 1)
                throw new ArgumentException("workers must be positive");
            CRe = cRe;
            CIm = cIm;
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
            => Compute(width, height, viewport, null, null, null, null, counts, null);

        /// <summary>Escape counts, row-major (height, width), tiered by zoom through 1e290.</summary>
        public int[] Iterations(int width, int height, Viewport viewport)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, counts);
            return counts;
        }

        /// <summary>
        /// T1 (perturbation + rebasing) escape counts against a precomputed reference orbit
        /// for the viewport center (Julia orbit: same c, z0 = center). The critical orbit
        /// rebased pixels restart on is computed here (<see cref="ReferenceOrbit.JuliaCritical"/>).
        /// Zoom &lt;= 1e290.
        /// </summary>
        public void Iterations(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm, int[] counts)
            => Compute(width, height, viewport, orbitRe, orbitIm, null, null, counts, null);

        /// <summary>T1 escape counts, allocating. Zoom &lt;= 1e290.</summary>
        public int[] Iterations(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, orbitRe, orbitIm, counts);
            return counts;
        }

        /// <summary>
        /// T1 escape counts against precomputed reference AND critical orbits — the
        /// replay path for a stored vector, needing no bignum at all. The critical orbit
        /// (z0 = 0, same c, precision from the zoom) is where rebased pixels restart
        /// (spec/deep-zoom.md "Rebasing"); it must begin at 0. Zoom &lt;= 1e290.
        /// </summary>
        public void Iterations(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm,
            double[] criticalRe, double[] criticalIm, int[] counts)
        {
            if (criticalRe == null)
                throw new ArgumentNullException(nameof(criticalRe));
            if (criticalIm == null)
                throw new ArgumentNullException(nameof(criticalIm));
            Compute(width, height, viewport, orbitRe, orbitIm, criticalRe, criticalIm, counts, null);
        }

        /// <summary>T1 escape counts against both orbits, allocating. Zoom &lt;= 1e290.</summary>
        public int[] Iterations(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm,
            double[] criticalRe, double[] criticalIm)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, orbitRe, orbitIm, criticalRe, criticalIm, counts);
            return counts;
        }

        /// <summary>One computation, both consumers: the smooth render in [0,1] and the raw counts.</summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, RenderProgress? progress = null)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, null, null, null, null, counts, mu, progress);
            return (FractalEngine.NormalizeRender(mu), counts);
        }

        /// <summary>T1 variant of <see cref="RenderAndCounts(int,int,Viewport,RenderProgress)"/>.</summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm,
            RenderProgress? progress = null)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, orbitRe, orbitIm, null, null, counts, mu, progress);
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
            double[]? criticalRe,
            double[]? criticalIm,
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
                (orbitRe, orbitIm) = ReferenceOrbit.Julia(viewport.CenterRe, viewport.CenterIm, viewport.ZoomLog10, MaxIter, CRe, CIm);
            }
            if (t1 && criticalRe == null)
            {
                // The reference starts at the center, so rebasing (which restarts a
                // pixel at index 0 of an orbit that must begin at 0) needs the
                // critical orbit under the same c (spec/deep-zoom.md "Rebasing").
                (criticalRe, criticalIm) = ReferenceOrbit.JuliaCritical(CRe, CIm, viewport.ZoomLog10, MaxIter);
            }
            if (t1 && (orbitRe!.Length == 0 || orbitIm!.Length != orbitRe.Length))
                throw new ArgumentException("the reference orbit must be two equal-length, non-empty arrays");
            if (t1 && (criticalRe!.Length == 0 || criticalIm!.Length != criticalRe.Length
                       || criticalRe[0] != 0.0 || criticalIm[0] != 0.0))
                throw new ArgumentException("the critical orbit must be two equal-length, non-empty arrays beginning at 0");
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
                        count = Perturbation.PerturbZ2(
                            orbitRe!, orbitIm!, criticalRe!, criticalIm!, ox, oy, 0.0, 0.0,
                            MaxIter, EscapeRadius, out fr, out fi);
                    else
                        count = FractalEngine.EscapeZ2(
                            ox + centerRe, oy + centerIm, CRe, CIm, MaxIter, r2, out fr, out fi);
                    counts[y * width + x] = count;
                    if (mu != null)
                        mu[y * width + x] = FractalEngine.SmoothMu(count, fr, fi, logR);
                }
            }

            FractalEngine.ForRows(height, Workers, Row, progress);
        }
    }
}
