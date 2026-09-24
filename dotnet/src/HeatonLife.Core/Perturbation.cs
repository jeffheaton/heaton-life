using System;

namespace HeatonLife
{
    /// <summary>
    /// Perturbation + rebasing deep-zoom engine (spec/deep-zoom.md). One high-precision
    /// reference orbit (<see cref="ReferenceOrbit"/>, or a stored vector) and every
    /// pixel iterates its small deviation delta in plain float64. Rebasing (Zhuoran
    /// 2021): whenever the full value |Z[m] + delta| drops below |delta|, restart
    /// against the beginning of an orbit whose first sample is 0 — the reference
    /// itself for Mandelbrot and Burning Ship, the critical orbit for Julia (whose
    /// reference starts at the viewport center). One reference serves the whole
    /// frame; no glitch detection passes.
    /// </summary>
    public static class Perturbation
    {
        /// <summary>
        /// Perturbation for z^2 + c maps whose reference starts at 0 (Mandelbrot:
        /// delta0 = 0), so a rebased pixel restarts on the reference itself.
        /// Returns the 1-based escape iteration for one pixel, or -1.
        /// </summary>
        public static int PerturbZ2(
            double[] orbitRe,
            double[] orbitIm,
            double dz0Re,
            double dz0Im,
            double dcRe,
            double dcIm,
            int maxIter,
            double escapeRadius,
            out double finalRe,
            out double finalIm)
            => PerturbZ2(
                orbitRe, orbitIm, orbitRe, orbitIm, dz0Re, dz0Im, dcRe, dcIm,
                maxIter, escapeRadius, out finalRe, out finalIm);

        /// <summary>
        /// Perturbation for z^2 + c maps with a separate rebase orbit, which must
        /// start at 0 (Julia: deltaC = 0, the reference starts at the viewport
        /// center, and <paramref name="rebaseRe"/>/<paramref name="rebaseIm"/> is the
        /// critical orbit under the same c). A pixel follows the reference until its
        /// first rebase and the rebase orbit from then on (spec/deep-zoom.md
        /// "Rebasing"). Returns the 1-based escape iteration for one pixel, or -1.
        /// </summary>
        public static int PerturbZ2(
            double[] orbitRe,
            double[] orbitIm,
            double[] rebaseRe,
            double[] rebaseIm,
            double dz0Re,
            double dz0Im,
            double dcRe,
            double dcIm,
            int maxIter,
            double escapeRadius,
            out double finalRe,
            out double finalIm)
        {
            double dzr = dz0Re, dzi = dz0Im;
            double[] refRe = orbitRe, refIm = orbitIm;
            int m = 0;
            int last = refRe.Length - 1;
            double r2 = escapeRadius * escapeRadius;
            for (int it = 1; it <= maxIter; it++)
            {
                // dz = (2*Z[m] + dz) * dz + dc, with the reference's fma-contracted multiply
                double tr = 2.0 * refRe[m] + dzr;
                double ti = 2.0 * refIm[m] + dzi;
                var (mr, mi) = FractalEngine.ComplexMul(tr, ti, dzr, dzi);
                dzr = mr + dcRe;
                dzi = mi + dcIm;
                m = Math.Min(m + 1, last);
                double zr = refRe[m] + dzr;
                double zi = refIm[m] + dzi;
                double zabs2 = zr * zr + zi * zi;
                if (zabs2 > r2)
                {
                    finalRe = zr;
                    finalIm = zi;
                    return it;
                }
                if (zabs2 < dzr * dzr + dzi * dzi)
                {
                    dzr = zr;
                    dzi = zi;
                    refRe = rebaseRe;
                    refIm = rebaseIm;
                    last = refRe.Length - 1;
                    m = 0;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
            return -1;
        }

        /// <summary>
        /// <see cref="PerturbZ2(double[],double[],double[],double[],double,double,double,double,int,double,out double,out double)"/>
        /// that also carries the derivative of the full z for a distance estimate
        /// (spec/fractals.md "Distance estimate"): updated from the z the previous iteration
        /// reconstructed — fl(Z_0 + delta_0) before the first — and left alone by a rebase,
        /// which changes delta, m and the orbit followed but not z. Mandelbrot: d0 = (0, 0),
        /// <paramref name="addScale"/>; Julia: d0 = (ps, 0), no addition. Counts and the final
        /// z are exactly PerturbZ2's.
        /// </summary>
        internal static int PerturbZ2De(
            double[] orbitRe,
            double[] orbitIm,
            double[] rebaseRe,
            double[] rebaseIm,
            double dz0Re,
            double dz0Im,
            double dcRe,
            double dcIm,
            int maxIter,
            double escapeRadius,
            double d0Re,
            double d0Im,
            bool addScale,
            double ps,
            out double finalRe,
            out double finalIm,
            out double finalDr,
            out double finalDi)
        {
            double dzr = dz0Re, dzi = dz0Im;
            double[] refRe = orbitRe, refIm = orbitIm;
            int m = 0;
            int last = refRe.Length - 1;
            double r2 = escapeRadius * escapeRadius;
            double dr = d0Re, di = d0Im;
            double zr = refRe[0] + dzr;                   // the pre-square z of iteration 1
            double zi = refIm[0] + dzi;
            for (int it = 1; it <= maxIter; it++)
            {
                double tdr = 2.0 * (zr * dr - zi * di);
                if (addScale)
                    tdr = tdr + ps;
                double tdi = 2.0 * (zr * di + zi * dr);
                dr = tdr;
                di = tdi;
                double tr = 2.0 * refRe[m] + dzr;
                double ti = 2.0 * refIm[m] + dzi;
                var (mr, mi) = FractalEngine.ComplexMul(tr, ti, dzr, dzi);
                dzr = mr + dcRe;
                dzi = mi + dcIm;
                m = Math.Min(m + 1, last);
                zr = refRe[m] + dzr;
                zi = refIm[m] + dzi;
                double zabs2 = zr * zr + zi * zi;
                if (zabs2 > r2)
                {
                    finalRe = zr;
                    finalIm = zi;
                    finalDr = dr;
                    finalDi = di;
                    return it;
                }
                if (zabs2 < dzr * dzr + dzi * dzi)
                {
                    // z, and so the derivative, are unchanged: only delta, m and the orbit move
                    dzr = zr;
                    dzi = zi;
                    refRe = rebaseRe;
                    refIm = rebaseIm;
                    last = refRe.Length - 1;
                    m = 0;
                }
            }
            finalRe = finalIm = finalDr = finalDi = 0.0;
            return -1;
        }

        /// <summary>
        /// Mandelbrot perturbation with BLA skips (spec/deep-zoom.md "BLA"): each pass, a
        /// pixel at a stride-aligned reference index takes the longest live span of
        /// <paramref name="table"/> whose radius exceeds |dz| and that fits in maxIter, else
        /// one plain step exactly as <see cref="PerturbZ2(double[],double[],double,double,double,double,int,double,out double,out double)"/>
        /// takes it. A skip is plain doubles: dz' = A·dz + B·dc, and with
        /// <paramref name="distance"/> the derivative d' = A·d + B·ps. Returns the count
        /// (-1 if none) and how many skips the pixel took.
        /// </summary>
        internal static int PerturbZ2Bla(
            double[] orbitRe,
            double[] orbitIm,
            BlaTable table,
            double dcRe,
            double dcIm,
            int maxIter,
            double escapeRadius,
            bool distance,
            double ps,
            out double finalRe,
            out double finalIm,
            out double finalDr,
            out double finalDi,
            out int applications)
        {
            const int stride = BlaTable.Stride;
            double dzr = 0.0, dzi = 0.0;
            int m = 0;
            long n = 0;
            int last = orbitRe.Length - 1;
            double r2 = escapeRadius * escapeRadius;
            double dr = 0.0, di = 0.0;
            double zr = orbitRe[0] + dzr;                  // the pre-square z of the first pass
            double zi = orbitIm[0] + dzi;
            int levels = table.Levels;
            int blocks = levels > 0 ? table.R[0].Length : 0;
            applications = 0;
            while (n < maxIter)
            {
                int chosen = -1;
                if (levels > 0 && m % stride == 0 && m / stride < blocks)
                {
                    double dm = BlaTable.Mag(dzr, dzi);
                    for (int level = 0; level < levels; level++)
                    {
                        long span = (long)stride << level;
                        if (m % span != 0 || m / span >= table.R[level].Length || n + span > maxIter
                            || !(dm < table.R[level][m / span]))
                            break;
                        chosen = level;
                    }
                }
                if (chosen >= 0)
                {
                    int span = stride << chosen;
                    int e = m / span;
                    double ar = table.Ar[chosen][e], ai = table.Ai[chosen][e];
                    double br = table.Br[chosen][e], bi = table.Bi[chosen][e];
                    if (distance)
                    {
                        double tdr = (ar * dr - ai * di) + br * ps;
                        double tdi = (ar * di + ai * dr) + bi * ps;
                        dr = tdr;
                        di = tdi;
                    }
                    double nr = (ar * dzr - ai * dzi) + (br * dcRe - bi * dcIm);
                    double ni = (ar * dzi + ai * dzr) + (br * dcIm + bi * dcRe);
                    dzr = nr;
                    dzi = ni;
                    m += span;
                    n += span;
                    applications++;
                }
                else
                {
                    if (distance)
                    {
                        double tdr = 2.0 * (zr * dr - zi * di) + ps;
                        double tdi = 2.0 * (zr * di + zi * dr);
                        dr = tdr;
                        di = tdi;
                    }
                    double tr = 2.0 * orbitRe[m] + dzr;
                    double ti = 2.0 * orbitIm[m] + dzi;
                    var (mr, mi) = FractalEngine.ComplexMul(tr, ti, dzr, dzi);
                    dzr = mr + dcRe;
                    dzi = mi + dcIm;
                    m = Math.Min(m + 1, last);
                    n++;
                }
                zr = orbitRe[m] + dzr;
                zi = orbitIm[m] + dzi;
                double zabs2 = zr * zr + zi * zi;
                if (zabs2 > r2)
                {
                    finalRe = zr;
                    finalIm = zi;
                    finalDr = dr;
                    finalDi = di;
                    return (int)n;
                }
                if (zabs2 < dzr * dzr + dzi * dzi)
                {
                    dzr = zr;                               // z and the derivative are unchanged
                    dzi = zi;
                    m = 0;
                }
            }
            finalRe = finalIm = finalDr = finalDi = 0.0;
            return -1;
        }

        /// <summary>Component-form perturbation for the Burning Ship, using stable diffabs.</summary>
        public static int PerturbBurningShip(
            double[] orbitRe,
            double[] orbitIm,
            double dcRe,
            double dcIm,
            int maxIter,
            double escapeRadius,
            out double finalRe,
            out double finalIm)
        {
            double dx = 0.0, dy = 0.0;
            int m = 0;
            int last = orbitRe.Length - 1;
            double r2 = escapeRadius * escapeRadius;
            for (int it = 1; it <= maxIter; it++)
            {
                double xRef = orbitRe[m];
                double yRef = orbitIm[m];
                double a = DiffAbs(xRef, dx);
                double b = DiffAbs(yRef, dy);
                double newDx = (2.0 * xRef + dx) * dx - (2.0 * yRef + dy) * dy + dcRe;
                double newDy = 2.0 * (Math.Abs(xRef) * b + Math.Abs(yRef) * a + a * b) + dcIm;
                dx = newDx;
                dy = newDy;
                m = Math.Min(m + 1, last);
                double zx = orbitRe[m] + dx;
                double zy = orbitIm[m] + dy;
                double zabs2 = zx * zx + zy * zy;
                if (zabs2 > r2)
                {
                    finalRe = zx;
                    finalIm = zy;
                    return it;
                }
                if (zabs2 < dx * dx + dy * dy)
                {
                    dx = zx;
                    dy = zy;
                    m = 0;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
            return -1;
        }

        /// <summary>|ref + delta| - |ref|, computed without cancellation (case analysis).</summary>
        private static double DiffAbs(double reference, double delta)
        {
            double total = reference + delta;
            if (reference >= 0.0)
                return total >= 0.0 ? delta : -(2.0 * reference + delta);
            return total <= 0.0 ? -delta : 2.0 * reference + delta;
        }
    }
}
