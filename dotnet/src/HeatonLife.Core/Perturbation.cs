using System;

namespace HeatonLife
{
    /// <summary>
    /// Perturbation + rebasing deep-zoom engine (spec/deep-zoom.md). One high-precision
    /// reference orbit — precomputed elsewhere (the Python side, or a stored vector) —
    /// and every pixel iterates its small deviation delta in plain float64. Rebasing
    /// (Zhuoran 2021): whenever the full value |Z[m] + delta| drops below |delta|,
    /// restart against the beginning of the reference. One reference serves the whole
    /// frame; no glitch detection passes.
    /// </summary>
    public static class Perturbation
    {
        /// <summary>
        /// Perturbation for z^2 + c maps (Mandelbrot: delta0 = 0; Julia: deltaC = 0).
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
        {
            double dzr = dz0Re, dzi = dz0Im;
            int m = 0;
            int last = orbitRe.Length - 1;
            double r2 = escapeRadius * escapeRadius;
            for (int it = 1; it <= maxIter; it++)
            {
                // dz = (2*Z[m] + dz) * dz + dc, with the reference's fma-contracted multiply
                double tr = 2.0 * orbitRe[m] + dzr;
                double ti = 2.0 * orbitIm[m] + dzi;
                var (mr, mi) = FractalEngine.ComplexMul(tr, ti, dzr, dzi);
                dzr = mr + dcRe;
                dzi = mi + dcIm;
                m = Math.Min(m + 1, last);
                double zr = orbitRe[m] + dzr;
                double zi = orbitIm[m] + dzi;
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
                    m = 0;
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
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
