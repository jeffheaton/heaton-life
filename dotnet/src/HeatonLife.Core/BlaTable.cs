using System;

namespace HeatonLife
{
    /// <summary>
    /// The bivariate linear approximation table of one reference orbit (spec/deep-zoom.md
    /// "BLA"): over a span of l steps from reference index m a pixel near the reference
    /// follows dz_{m+l} ≈ A·dz_m + B·dc while |dz| &lt; r. Level 0 folds S = 8 single steps
    /// (A = 2Z, B = 1, r = eps·|Z|) left to right; each level above merges pairs. A pure
    /// function of the float64 orbit samples, the escape radius and the frame's dc bound,
    /// computed with plain doubles only — the Python reference's heaton_life.fractal.bla,
    /// expression for expression.
    /// </summary>
    internal sealed class BlaTable
    {
        /// <summary>Steps folded into one level-0 entry.</summary>
        internal const int Stride = 8;

        /// <summary>At most this many levels.</summary>
        internal const int LevelCap = 32;

        /// <summary>float64's unit roundoff, 2^-53: the dropped dz² stays below rounding.</summary>
        internal static readonly double Epsilon = PowerOfTwo(-53);

        private static readonly double Cap = PowerOfTwo(960);
        private static readonly double TwoTo400 = PowerOfTwo(400);
        private static readonly double TwoToMinus400 = PowerOfTwo(-400);
        private static readonly double TwoTo600 = PowerOfTwo(600);
        private static readonly double TwoToMinus600 = PowerOfTwo(-600);

        private BlaTable(double[][] ar, double[][] ai, double[][] br, double[][] bi, double[][] r, int extent)
        {
            Ar = ar;
            Ai = ai;
            Br = br;
            Bi = bi;
            R = r;
            Extent = extent;
        }

        /// <summary>Per level: the coefficients and validity radius (0 = dead) of each entry.</summary>
        internal double[][] Ar { get; }
        internal double[][] Ai { get; }
        internal double[][] Br { get; }
        internal double[][] Bi { get; }
        internal double[][] R { get; }

        /// <summary>k*: the steps tabulated are 0 .. Extent - 1.</summary>
        internal int Extent { get; }

        internal int Levels => R.Length;

        private static double PowerOfTwo(int exponent) => BitConverter.Int64BitsToDouble((long)(1023 + exponent) << 52);

        /// <summary>
        /// |x + iy| with an exact power-of-two scale, so neither square leaves the normal
        /// range: a = max(|x|, |y|); s = 2^600 below 2^-400, 2^-600 above 2^400, else 1;
        /// sqrt((xs)² + (ys)²)/s. 0, +∞ and NaN come out as themselves.
        /// </summary>
        internal static double Mag(double x, double y)
        {
            double a = Math.Max(Math.Abs(x), Math.Abs(y));
            double s = 1.0, t = 1.0;
            if (a < TwoToMinus400)
            {
                s = TwoTo600;
                t = TwoToMinus600;
            }
            else if (a > TwoTo400)
            {
                s = TwoToMinus600;
                t = TwoTo600;
            }
            double xs = x * s, ys = y * s;
            return Math.Sqrt(xs * xs + ys * ys) * t;
        }

        /// <summary>The frame's bound on |dc|: Mag(max |dc.re| over columns, max |dc.im| over rows).</summary>
        internal static double DcBound(double maxAbsRe, double maxAbsIm) => Mag(maxAbsRe, maxAbsIm);

        /// <summary>
        /// The radius of x followed by y: num &gt; 0 ? min(r1, num / |A_x|) : 0 with
        /// num = r2 - |B_x|·dcBound, NaN-free as spelled.
        /// </summary>
        private static double Merge(double r1, double r2, double ar, double ai, double br, double bi, double dcBound)
        {
            double num = r2 - Mag(br, bi) * dcBound;
            double cand = num / Mag(ar, ai);
            return num > 0.0 ? (cand < r1 ? cand : r1) : 0.0;
        }

        /// <summary>The dead rule: live only if r &gt; 0 and |A|, |B| &lt; 2^960.</summary>
        private static double Alive(double r, double ar, double ai, double br, double bi)
            => r > 0.0 && Mag(ar, ai) < Cap && Mag(br, bi) < Cap ? r : 0.0;

        /// <summary>Build the table (spec/deep-zoom.md "BLA").</summary>
        internal static BlaTable Build(double[] orbitRe, double[] orbitIm, double escapeRadius, double dcBound)
        {
            double r2 = escapeRadius * escapeRadius;
            int extent = orbitRe.Length - 1;
            for (int k = 1; k < orbitRe.Length; k++)
            {
                if (orbitRe[k] * orbitRe[k] + orbitIm[k] * orbitIm[k] > r2)
                {
                    extent = k;
                    break;
                }
            }
            int n0 = Math.Max(extent, 0) / Stride;
            if (n0 == 0)
                return new BlaTable(new double[0][], new double[0][], new double[0][], new double[0][], new double[0][], extent);
            int levels = 1;
            for (int count = n0; levels < LevelCap && count >= 2; count /= 2)
                levels++;
            var ar = new double[levels][];
            var ai = new double[levels][];
            var br = new double[levels][];
            var bi = new double[levels][];
            var r = new double[levels][];
            ar[0] = new double[n0];
            ai[0] = new double[n0];
            br[0] = new double[n0];
            bi[0] = new double[n0];
            r[0] = new double[n0];
            for (int block = 0; block < n0; block++)
            {
                double xar = 1.0, xai = 0.0, xbr = 0.0, xbi = 0.0, radius = double.PositiveInfinity;
                for (int j = 0; j < Stride; j++)
                {
                    double zr = orbitRe[block * Stride + j], zi = orbitIm[block * Stride + j];
                    double sr = 2.0 * zr, si = 2.0 * zi;
                    radius = Merge(radius, Epsilon * Mag(zr, zi), xar, xai, xbr, xbi, dcBound);
                    double nbr = (sr * xbr - si * xbi) + 1.0;
                    double nbi = sr * xbi + si * xbr;
                    double nar = sr * xar - si * xai;
                    double nai = sr * xai + si * xar;
                    xar = nar;
                    xai = nai;
                    xbr = nbr;
                    xbi = nbi;
                }
                ar[0][block] = xar;
                ai[0][block] = xai;
                br[0][block] = xbr;
                bi[0][block] = xbi;
                r[0][block] = Alive(radius, xar, xai, xbr, xbi);
            }
            for (int level = 1; level < levels; level++)
            {
                int count = r[level - 1].Length / 2;
                ar[level] = new double[count];
                ai[level] = new double[count];
                br[level] = new double[count];
                bi[level] = new double[count];
                r[level] = new double[count];
                for (int k = 0; k < count; k++)
                {
                    int x = 2 * k, y = 2 * k + 1;
                    double xar = ar[level - 1][x], xai = ai[level - 1][x], xbr = br[level - 1][x], xbi = bi[level - 1][x];
                    double yar = ar[level - 1][y], yai = ai[level - 1][y], ybr = br[level - 1][y], ybi = bi[level - 1][y];
                    double nar = yar * xar - yai * xai;
                    double nai = yar * xai + yai * xar;
                    double nbr = (yar * xbr - yai * xbi) + ybr;
                    double nbi = (yar * xbi + yai * xbr) + ybi;
                    double radius = Merge(r[level - 1][x], r[level - 1][y], xar, xai, xbr, xbi, dcBound);
                    ar[level][k] = nar;
                    ai[level][k] = nai;
                    br[level][k] = nbr;
                    bi[level][k] = nbi;
                    r[level][k] = Alive(radius, nar, nai, nbr, nbi);
                }
            }
            return new BlaTable(ar, ai, br, bi, r, extent);
        }
    }
}
