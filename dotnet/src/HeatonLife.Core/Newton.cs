using System;

namespace HeatonLife
{
    /// <summary>
    /// Newton fractal: basins of z^d - 1 under Newton's method (spec/fractals.md).
    /// Float64 only (no deep tier). Outputs: root index at convergence and 1-based
    /// iteration of first convergence, -1 where unconverged. Convergence:
    /// |z^d - 1| &lt; 1e-9. Complex division uses the reference's exact Smith branch
    /// (|re| >= |im|), so int32 outputs are bit-exact. Bit-exact tier.
    /// </summary>
    public sealed class Newton
    {
        public const double Tolerance = 1e-9;

        private readonly double[] _rootRe;
        private readonly double[] _rootIm;

        public int Degree { get; }
        public int MaxIter { get; }

        /// <summary>Row-parallel worker count; output is identical for any value.</summary>
        public int Workers { get; }

        public Newton(int degree = 3, int maxIter = 60, int workers = 1)
        {
            if (degree < 2)
                throw new ArgumentException("degree must be >= 2");
            if (workers < 1)
                throw new ArgumentException("workers must be positive");
            Workers = workers;
            Degree = degree;
            MaxIter = maxIter;
            _rootRe = new double[degree];
            _rootIm = new double[degree];
            for (int k = 0; k < degree; k++)
            {
                double angle = 2.0 * Math.PI * k / degree;
                _rootRe[k] = Math.Cos(angle);
                _rootIm[k] = Math.Sin(angle);
            }
        }

        /// <summary>Root/iteration grids into caller buffers, row-major (height, width), -1 where unconverged.</summary>
        public void Basins(int width, int height, Viewport viewport, int[] roots, int[] iterations)
        {
            if (roots.Length != width * height || iterations.Length != width * height)
                throw new ArgumentException($"expected {width * height} cells in each output buffer");
            FractalEngine.RequireT0(viewport);
            double ps = FractalEngine.PixelScale(width, viewport);
            double centerRe = viewport.CenterReDouble;
            double centerIm = viewport.CenterImDouble;
            const double tol2 = Tolerance * Tolerance;
            void Row(int y)
            {
                double z0i = FractalEngine.OffsetIm(y, height, ps) + centerIm;
                for (int x = 0; x < width; x++)
                {
                    double z0r = FractalEngine.OffsetRe(x, width, ps) + centerRe;
                    (roots[y * width + x], iterations[y * width + x]) = Pixel(z0r, z0i, tol2);
                }
            }

            FractalEngine.ForRows(height, Workers, Row);
        }

        /// <summary>(root_index, iterations), each row-major (height, width), -1 where unconverged.</summary>
        public (int[] Roots, int[] Iterations) Basins(int width, int height, Viewport viewport)
        {
            var roots = new int[width * height];
            var iters = new int[width * height];
            Basins(width, height, viewport, roots, iters);
            return (roots, iters);
        }

        public int[] Iterations(int width, int height, Viewport viewport) =>
            Basins(width, height, viewport).Iterations;

        /// <summary>
        /// Hue by basin, shaded by convergence speed; unconverged pixels are 0
        /// (spec/render.md): value = (root + 1 - 0.7 * iters / max_iter) / degree, clipped.
        /// </summary>
        public double[] Render(int width, int height, Viewport viewport)
        {
            var (roots, iters) = Basins(width, height, viewport);
            var value = new double[roots.Length];
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i] >= 0)
                {
                    double shade = 1.0 - 0.7 * (iters[i] / (double)MaxIter);
                    value[i] = Math.Clamp((roots[i] + shade) / Degree, 0.0, 1.0);
                }
            }
            return value;
        }

        private (int Root, int Iterations) Pixel(double zr, double zi, double tol2)
        {
            int d = Degree;
            for (int it = 1; it <= MaxIter; it++)
            {
                // zd1 = z^(d-1); deriv = d * zd1
                var (pr, pi) = PowInt(zr, zi, d - 1);
                double derivRe = d * pr;
                double derivIm = d * pi;
                if (derivRe != 0.0 || derivIm != 0.0)
                {
                    // z -= (zd1 * z - 1) / deriv  (dead pixels with zero derivative never
                    // converge). zd1 * z runs through the reference's multiply ufunc, so
                    // it carries the fma-contracted form; the z^n helper does not.
                    var (mr, mi) = FractalEngine.ComplexMul(pr, pi, zr, zi);
                    double numRe = mr - 1.0;
                    double numIm = mi;
                    var (qr, qi) = Divide(numRe, numIm, derivRe, derivIm);
                    zr -= qr;
                    zi -= qi;
                }
                var (rr, ri) = PowInt(zr, zi, d);
                double resRe = rr - 1.0;
                double resIm = ri;
                if (resRe * resRe + resIm * resIm < tol2)
                    return (NearestRoot(zr, zi), it);
            }
            return (-1, -1);
        }

        /// <summary>First root of minimal |z - root|, matching np.argmin's first-minimum rule.</summary>
        private int NearestRoot(double zr, double zi)
        {
            int best = 0;
            double bestDist = double.PositiveInfinity;
            for (int k = 0; k < Degree; k++)
            {
                double dr = zr - _rootRe[k];
                double di = zi - _rootIm[k];
                double dist = Math.Sqrt(dr * dr + di * di);
                if (dist < bestDist)
                {
                    bestDist = dist;
                    best = k;
                }
            }
            return best;
        }

        /// <summary>Integer power by binary exponentiation (numpy's nc_pow integer path).</summary>
        private static (double Re, double Im) PowInt(double zr, double zi, int n)
        {
            if (n == 1)
                return (zr, zi);
            if (n == 2)
                return (zr * zr - zi * zi, zr * zi + zi * zr);
            double rr = 1.0, ri = 0.0;
            double br = zr, bi = zi;
            int k = n;
            while (k > 0)
            {
                if ((k & 1) != 0)
                {
                    double tr = rr * br - ri * bi;
                    double ti = rr * bi + ri * br;
                    rr = tr;
                    ri = ti;
                }
                k >>= 1;
                if (k > 0)
                {
                    double sr = br * br - bi * bi;
                    double si = br * bi + bi * br;
                    br = sr;
                    bi = si;
                }
            }
            return (rr, ri);
        }

        /// <summary>Smith's algorithm with numpy's exact branch: |re| >= |im| of the divisor.</summary>
        private static (double Re, double Im) Divide(double ar, double ai, double br, double bi)
        {
            if (Math.Abs(br) >= Math.Abs(bi))
            {
                double rat = bi / br;
                double scl = 1.0 / (br + bi * rat);
                return ((ar + ai * rat) * scl, (ai - ar * rat) * scl);
            }
            else
            {
                double rat = br / bi;
                double scl = 1.0 / (bi + br * rat);
                return ((ar * rat + ai) * scl, (ai * rat - ar) * scl);
            }
        }
    }
}
