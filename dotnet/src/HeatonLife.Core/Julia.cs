using System;
using System.Threading;

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
            if (double.IsNaN(escapeRadius * escapeRadius) || double.IsInfinity(escapeRadius * escapeRadius))
                throw new ArgumentException($"escape_radius squared must be finite, got {escapeRadius}");   // |z|² > R² could never fire
            CRe = cRe;
            CIm = cIm;
            MaxIter = maxIter;
            EscapeRadius = escapeRadius;
            Workers = workers;
        }

        /// <summary>
        /// Escape counts into <paramref name="counts"/>, tiered by zoom: T0 (direct float64)
        /// through 1e12, T1 (perturbation against a reference orbit this call computes)
        /// through 1e290, then T2 (floatexp perturbation) through
        /// <see cref="MaxZoomLog10"/>, 1e9000.
        /// </summary>
        public void Iterations(int width, int height, Viewport viewport, int[] counts)
            => Compute(width, height, viewport, null, null, null, null, counts, null);

        /// <summary>Escape counts, row-major (height, width), tiered by zoom through <see cref="MaxZoomLog10"/> (1e9000).</summary>
        public int[] Iterations(int width, int height, Viewport viewport)
        {
            var counts = new int[width * height];
            Iterations(width, height, viewport, counts);
            return counts;
        }

        /// <summary>
        /// T1 (perturbation + rebasing) escape counts against a precomputed reference orbit
        /// for the viewport's reference point (Julia orbit: same c, z0 = <see cref="Viewport.OrbitCenterRe"/>,
        /// the center unless the viewport names another), computed at twice the viewport's
        /// zoom (spec/deep-zoom.md "Reference orbit": a Julia orbit's precision is that of
        /// <c>2 · ZoomLog10</c>). The critical orbit rebased pixels restart on is computed
        /// here (<see cref="ReferenceOrbit.JuliaCritical"/>). Zoom &lt;= 1e290.
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
        /// replay path for a stored vector, needing no bignum at all. Both orbits run at
        /// twice the viewport's zoom. The critical orbit (z0 = 0, same c) is where rebased
        /// pixels restart (spec/deep-zoom.md "Rebasing"); it must begin at 0. Zoom &lt;= 1e290.
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
            => Compute(width, height, viewport, null, null, null, null, counts, smooth, progress, cancellationToken);

        /// <summary>
        /// <see cref="RenderAndCounts(int,int,Viewport,RenderProgress)"/> that a host can
        /// cancel (OperationCanceledException); a superseded frame stops within a row.
        /// </summary>
        public (double[] Render, int[] Counts) RenderAndCounts(
            int width, int height, Viewport viewport, RenderProgress? progress, CancellationToken cancellationToken)
        {
            var counts = new int[width * height];
            var mu = new double[width * height];
            Compute(width, height, viewport, null, null, null, null, counts, mu, progress, cancellationToken);
            return (FractalEngine.NormalizeRender(mu), counts);
        }

        /// <summary>
        /// Escape counts and how each was decided (spec/fractals.md "Status") into caller
        /// buffers: <see cref="PixelStatus"/> as bytes — Escaped, Exhausted (max_iter reached,
        /// more might escape), CardioidOrBulb and Cycle (proved interior, T0). Counts and
        /// <paramref name="smooth"/> (may be null) are exactly what the other overloads give.
        /// </summary>
        public void CountsAndStatus(
            int width, int height, Viewport viewport, int[] counts, byte[] status, double[]? smooth = null,
            RenderProgress? progress = null, CancellationToken cancellationToken = default)
        {
            if (status == null)
                throw new ArgumentNullException(nameof(status));
            Compute(width, height, viewport, null, null, null, null, counts, smooth, progress, cancellationToken, status);
        }

        /// <summary><see cref="CountsAndStatus(int,int,Viewport,int[],byte[],double[],RenderProgress,CancellationToken)"/>, allocating.</summary>
        public (int[] Counts, byte[] Status) CountsAndStatus(int width, int height, Viewport viewport)
        {
            var counts = new int[width * height];
            var status = new byte[width * height];
            CountsAndStatus(width, height, viewport, counts, status);
            return (counts, status);
        }

        /// <summary>
        /// One computation, every output a host asks for, into caller buffers
        /// (spec/fractals.md): counts, and — each may be null — raw smooth values (mu, 0 where
        /// interior), statuses (<see cref="PixelStatus"/> as bytes), and the distance estimate
        /// ("Distance estimate": pixels of this frame, NaN where a pixel did not escape).
        /// Counts, smooth values and statuses are exactly what the other overloads give; the
        /// distance estimate runs a separate loop that also carries the derivative, and needs
        /// 2 &lt;= <see cref="EscapeRadius"/> &lt;= 1e64. Progress and cancellation as in
        /// <see cref="Iterations(int,int,Viewport,int[],double[],RenderProgress,CancellationToken)"/>.
        /// </summary>
        public void Fields(
            int width, int height, Viewport viewport, int[] counts, double[]? smooth = null, byte[]? status = null,
            double[]? distance = null, RenderProgress? progress = null, CancellationToken cancellationToken = default)
        {
            if (distance != null)
                FractalEngine.RequireDistanceRadius(EscapeRadius);
            Compute(width, height, viewport, null, null, null, null, counts, smooth, progress, cancellationToken, status, distance);
        }

        /// <summary>
        /// <see cref="Fields(int,int,Viewport,int[],double[],byte[],double[],RenderProgress,CancellationToken)"/>
        /// against stored reference and critical orbits — the conformance runners' replay path.
        /// </summary>
        internal void Fields(
            int width, int height, Viewport viewport, double[] orbitRe, double[] orbitIm,
            double[] criticalRe, double[] criticalIm, int[] counts, byte[]? status, double[]? distance)
        {
            if (distance != null)
                FractalEngine.RequireDistanceRadius(EscapeRadius);
            Compute(width, height, viewport, orbitRe, orbitIm, criticalRe, criticalIm, counts, null, null, default, status, distance);
        }

        /// <summary>Whether this family has a distance estimate: yes (spec/fractals.md "Distance estimate").</summary>
        public bool SupportsDistance => true;

        /// <summary>The deepest zoom this family renders: the T2 ceiling (spec/fractals.md "Tiering").</summary>
        public double MaxZoomLog10 => FractalEngine.T2MaxZoom;

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
            RenderProgress? progress = null,
            CancellationToken cancellationToken = default,
            byte[]? status = null,
            double[]? distance = null)
        {
            if (status != null && status.Length != width * height)
                throw new ArgumentException($"expected {width * height} statuses, got {status.Length}");
            if (distance != null && distance.Length != width * height)
                throw new ArgumentException($"expected {width * height} distances, got {distance.Length}");
            if (counts.Length != width * height)
                throw new ArgumentException($"expected {width * height} counts, got {counts.Length}");
            if (mu != null && mu.Length != width * height)
                throw new ArgumentException($"expected {width * height} smooth values, got {mu.Length}");
            progress?.Reset();
            // Zoom picks the tier, not orbit presence (spec/deep-zoom.md).
            FractalTier tier = FractalEngine.TierFor(viewport, MaxZoomLog10, "Julia");
            if (tier == FractalTier.T2)
            {
                if (orbitRe != null || criticalRe != null)
                    throw new ArgumentException("a T2 frame computes its own orbits and small samples; no replay");
                ComputeT2(width, height, viewport, counts, mu, progress, cancellationToken, status, distance, null);
                return;
            }
            bool t1 = tier == FractalTier.T1;
            if (t1 && orbitRe == null)
            {
                // Deep zoom with no orbit handed in: make one. spec/deep-zoom.md
                // sanctions BigInteger fixed point for exactly this, and until it
                // existed the only reachable T1 render was a replay of a vector.
                // Twice the frame's precision (FractalEngine.OrbitZoom).
                (orbitRe, orbitIm) = ReferenceOrbit.Compute(
                    ReferenceOrbit.Kind.Julia, viewport.OrbitCenterRe, viewport.OrbitCenterIm,
                    FractalEngine.OrbitZoom(true, viewport.ZoomLog10), MaxIter,
                    CRe, CIm, progress, cancellationToken, whole: true);
            }
            if (t1 && criticalRe == null)
            {
                // The reference starts at the center, so rebasing (which restarts a
                // pixel at index 0 of an orbit that must begin at 0) needs the
                // critical orbit under the same c (spec/deep-zoom.md "Rebasing").
                (criticalRe, criticalIm) = ReferenceOrbit.Compute(
                    ReferenceOrbit.Kind.Julia, "0", "0", FractalEngine.OrbitZoom(true, viewport.ZoomLog10), MaxIter,
                    CRe, CIm, progress, cancellationToken, whole: true);
            }
            if (t1 && (orbitRe!.Length == 0 || orbitIm!.Length != orbitRe.Length))
                throw new ArgumentException("the reference orbit must be two equal-length, non-empty arrays");
            if (t1 && (criticalRe!.Length == 0 || criticalIm!.Length != criticalRe.Length
                       || criticalRe[0] != 0.0 || criticalIm[0] != 0.0))
                throw new ArgumentException("the critical orbit must be two equal-length, non-empty arrays beginning at 0");
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
                    double fr, fi, fdr = 0.0, fdi = 0.0;
                    PixelStatus pixel;
                    if (t1)
                    {
                        count = distance == null
                            ? Perturbation.PerturbZ2(
                                orbitRe!, orbitIm!, criticalRe!, criticalIm!, ox, oy, 0.0, 0.0,
                                MaxIter, EscapeRadius, out fr, out fi)
                            : Perturbation.PerturbZ2De(
                                orbitRe!, orbitIm!, criticalRe!, criticalIm!, ox, oy, 0.0, 0.0,
                                MaxIter, EscapeRadius, ps, 0.0, false, ps, out fr, out fi, out fdr, out fdi);
                        pixel = count > 0 ? PixelStatus.Escaped : PixelStatus.Exhausted;
                    }
                    else if (distance == null)
                    {
                        count = FractalEngine.EscapeZ2(
                            ox + centerRe, oy + centerIm, CRe, CIm, MaxIter, r2, out fr, out fi, out pixel);
                    }
                    else
                    {
                        count = FractalEngine.EscapeZ2De(
                            ox + centerRe, oy + centerIm, CRe, CIm, MaxIter, r2, ps, 0.0, false, ps,
                            out fr, out fi, out fdr, out fdi, out pixel);
                    }
                    counts[y * width + x] = count;
                    if (status != null)
                        status[y * width + x] = (byte)pixel;
                    if (mu != null)
                        mu[y * width + x] = FractalEngine.SmoothMu(count, fr, fi, logR);
                    if (distance != null)
                        distance[y * width + x] = FractalEngine.DistanceEstimate(count, fr, fi, fdr, fdi);
                }
            }

            FractalEngine.ForRows(height, Workers, Row, progress, cancellationToken);
        }

        /// <summary>
        /// The T2 path (spec/deep-zoom.md "T2"): the orbit and its small samples, floatexp
        /// pixel deltas, and <see cref="PerturbationT2"/> per pixel. BLA does not run at T2
        /// yet; statuses are Escaped or Exhausted.
        /// </summary>
        private void ComputeT2(
            int width, int height, Viewport viewport, int[] counts, double[]? mu, RenderProgress? progress,
            CancellationToken cancellationToken, byte[]? status, double[]? distance, int[]? blaApplications)
        {
            PerturbationT2.Orbit orbit, rebase;
            double zoom = FractalEngine.OrbitZoom(true, viewport.ZoomLog10);   // twice the frame's precision
            var (re, im, small) = ReferenceOrbit.ComputeX(
                ReferenceOrbit.Kind.Julia, viewport.OrbitCenterRe, viewport.OrbitCenterIm, zoom, MaxIter,
                CRe, CIm, progress, cancellationToken);
            orbit = new PerturbationT2.Orbit(re, im, small);
            var (wre, wim, wsmall) = ReferenceOrbit.ComputeX(
                ReferenceOrbit.Kind.Julia, "0", "0", zoom, MaxIter, CRe, CIm, progress, cancellationToken);
            rebase = new PerturbationT2.Orbit(wre, wim, wsmall);
            FloatExp ps = FractalEngine.PixelScaleX(width, viewport.ZoomLog10);
            bool offCenter = viewport.HasReference;
            FloatExp dRe = offCenter ? DecimalText.DifferenceX(viewport.CenterRe, viewport.ReferenceRe!) : FloatExp.Zero;
            FloatExp dIm = offCenter ? DecimalText.DifferenceX(viewport.CenterIm, viewport.ReferenceIm!) : FloatExp.Zero;
            double logR = Math.Log(EscapeRadius);
            bool track = distance != null;
            void Row(int y)
            {
                FloatExp oy = FractalEngine.OffsetImX(y, height, ps);
                if (offCenter)
                    oy = FloatExp.Add(dIm, oy);
                for (int x = 0; x < width; x++)
                {
                    FloatExp ox = FractalEngine.OffsetReX(x, width, ps);
                    if (offCenter)
                        ox = FloatExp.Add(dRe, ox);
                    int count = PerturbationT2.Perturb(
                        orbit, rebase, ox, oy, FloatExp.Zero, FloatExp.Zero, MaxIter, EscapeRadius,
                        track, ps, FloatExp.Zero, FloatExp.Zero, false,
                        out double fr, out double fi, out double dr, out double di, out long dE,
                        cancellationToken);
                    counts[y * width + x] = count;
                    if (status != null)
                        status[y * width + x] = (byte)(count > 0 ? PixelStatus.Escaped : PixelStatus.Exhausted);
                    if (mu != null)
                        mu[y * width + x] = FractalEngine.SmoothMu(count, fr, fi, logR);
                    if (distance != null)
                        distance[y * width + x] = PerturbationT2.DistanceEstimate(count, fr, fi, dr, di, dE);
                    if (blaApplications != null)
                        blaApplications[y * width + x] = 0;
                }
            }

            FractalEngine.ForRows(height, Workers, Row, progress, cancellationToken);
        }
    }
}
