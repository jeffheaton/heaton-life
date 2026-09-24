using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;

namespace HeatonLife
{
    /// <summary>
    /// The bivariate linear approximation table of one reference orbit (spec/deep-zoom.md
    /// "BLA"): over a span of l steps from reference index m a pixel near the reference
    /// follows dz_{m+l} ≈ A·dz_m + B·dc while |dz| &lt; r. Level 0 folds S = 8 single steps
    /// (A = 2Z, B = 1, r = eps·|Z|) left to right; each level above merges pairs. A pure
    /// function of the float64 orbit samples, the escape radius and the frame's dc bound,
    /// computed with plain doubles only (the coefficients in double-double, each entry
    /// storing the hi) — the Python reference's heaton_life.fractal.bla, expression for
    /// expression.
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

        /// <summary>Whether any entry can ever be taken (a parent is dead when its left child is).</summary>
        internal bool Live
        {
            get
            {
                if (R.Length == 0)
                    return false;
                foreach (double r in R[0])
                    if (r > 0.0)
                        return true;
                return false;
            }
        }

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

        /// <summary>
        /// The frame's bound on |dc|: Mag(max |dc.re| over columns, max |dc.im| over rows),
        /// rounded up to a power of two — conservative (a larger bound only shrinks radii),
        /// and one table then serves every frame within an octave of zoom.
        /// </summary>
        internal static double DcBound(double maxAbsRe, double maxAbsIm) => CeilPowerOfTwo(Mag(maxAbsRe, maxAbsIm));

        /// <summary><see cref="DcBound"/> over a frame's own pixel deltas (an off-center reference's offset included).</summary>
        internal static double FrameDcBound(int width, int height, Viewport viewport)
        {
            double ps = FractalEngine.PixelScale(width, viewport);
            bool offCenter = viewport.HasReference;
            double dRe = offCenter ? viewport.ReferenceOffsetRe : 0.0;
            double dIm = offCenter ? viewport.ReferenceOffsetIm : 0.0;
            double maxRe = 0.0, maxIm = 0.0;
            for (int x = 0; x < width; x++)
            {
                double v = Math.Abs(offCenter ? FractalEngine.DeltaRe(x, width, ps, dRe) : FractalEngine.OffsetRe(x, width, ps));
                if (v > maxRe)
                    maxRe = v;
            }
            for (int y = 0; y < height; y++)
            {
                double v = Math.Abs(offCenter ? FractalEngine.DeltaIm(y, height, ps, dIm) : FractalEngine.OffsetIm(y, height, ps));
                if (v > maxIm)
                    maxIm = v;
            }
            return DcBound(maxRe, maxIm);
        }

        /// <summary>The least power of two &gt;= x (x itself when it is one); 0, +∞ and NaN unchanged.</summary>
        internal static double CeilPowerOfTwo(double x)
        {
            if (!(x > 0.0) || double.IsInfinity(x))
                return x;
            long bits = BitConverter.DoubleToInt64Bits(x);
            int exponent = (int)((bits >> 52) & 0x7FF);
            long mantissa = bits & 0xFFFFFFFFFFFFFL;
            if (exponent == 0)
            {
                // Subnormal: x = mantissa * 2^-1074; the least 2^k >= mantissa, scaled back.
                int k = 0;
                while ((1L << k) < mantissa)
                    k++;
                return k >= 52 ? PowerOfTwo(k - 1074) : BitConverter.Int64BitsToDouble(1L << k);
            }
            if (mantissa == 0)
                return x;
            return exponent + 1 >= 0x7FF ? double.PositiveInfinity : BitConverter.Int64BitsToDouble((long)(exponent + 1) << 52);
        }

        // Tables built for an orbit, keyed by what they depend on beyond it: a render re-uses
        // the cached orbit's arrays, so a frame within an octave of the last builds nothing.
        private static readonly ConditionalWeakTable<double[], List<(double[] Im, int Samples, double R, double Dc, BlaTable Table)>> Tables =
            new ConditionalWeakTable<double[], List<(double[] Im, int Samples, double R, double Dc, BlaTable Table)>>();

        /// <summary><see cref="Build"/>, re-using a table already built for these same arrays and inputs.</summary>
        internal static BlaTable Get(double[] orbitRe, double[] orbitIm, int samples, double escapeRadius, double dcBound)
        {
            var list = Tables.GetValue(orbitRe, _ => new List<(double[], int, double, double, BlaTable)>());
            lock (list)
            {
                foreach (var entry in list)
                {
                    if (ReferenceEquals(entry.Im, orbitIm) && entry.Samples == samples
                        && entry.R.Equals(escapeRadius) && entry.Dc.Equals(dcBound))
                        return entry.Table;
                }
            }
            var table = Build(orbitRe, orbitIm, samples, escapeRadius, dcBound);
            lock (list)
            {
                if (list.Count >= 4)
                    list.RemoveAt(0);
                list.Add((orbitIm, samples, escapeRadius, dcBound, table));
            }
            return table;
        }

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

        /// <summary>
        /// Build the table (spec/deep-zoom.md "BLA") over the first <paramref name="samples"/>
        /// samples of the orbit — max_iter + 1 at most, so a cached orbit longer than the
        /// frame needs builds the same table the reference does, at the frame's cost.
        /// </summary>
        internal static BlaTable Build(double[] orbitRe, double[] orbitIm, int samples, double escapeRadius, double dcBound)
        {
            if (samples < 1 || samples > orbitRe.Length || samples > orbitIm.Length)
                throw new ArgumentOutOfRangeException(nameof(samples));
            double r2 = escapeRadius * escapeRadius;
            int extent = samples - 1;
            for (int k = 1; k < samples; k++)
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
            // The coefficients' lo parts, level by level: a merge reads its children's pairs.
            var arLo = new double[levels][];
            var aiLo = new double[levels][];
            var brLo = new double[levels][];
            var biLo = new double[levels][];
            ar[0] = new double[n0];
            ai[0] = new double[n0];
            br[0] = new double[n0];
            bi[0] = new double[n0];
            arLo[0] = new double[n0];
            aiLo[0] = new double[n0];
            brLo[0] = new double[n0];
            biLo[0] = new double[n0];
            r[0] = new double[n0];
            for (int block = 0; block < n0; block++)
            {
                Dd.FoldStart(out Dd xar, out Dd xai, out Dd xbr, out Dd xbi);
                double radius = double.PositiveInfinity;
                for (int j = 0; j < Stride; j++)
                {
                    double zr = orbitRe[block * Stride + j], zi = orbitIm[block * Stride + j];
                    radius = Merge(radius, Epsilon * Mag(zr, zi), xar.Hi, xai.Hi, xbr.Hi, xbi.Hi, dcBound);
                    Dd.FoldStep(ref xar, ref xai, ref xbr, ref xbi, zr, zi);
                }
                Dd.Store(xar, ar[0], arLo[0], block);
                Dd.Store(xai, ai[0], aiLo[0], block);
                Dd.Store(xbr, br[0], brLo[0], block);
                Dd.Store(xbi, bi[0], biLo[0], block);
                r[0][block] = Alive(radius, xar.Hi, xai.Hi, xbr.Hi, xbi.Hi);
            }
            for (int level = 1; level < levels; level++)
            {
                int count = r[level - 1].Length / 2;
                ar[level] = new double[count];
                ai[level] = new double[count];
                br[level] = new double[count];
                bi[level] = new double[count];
                arLo[level] = new double[count];
                aiLo[level] = new double[count];
                brLo[level] = new double[count];
                biLo[level] = new double[count];
                r[level] = new double[count];
                int below = level - 1;
                for (int k = 0; k < count; k++)
                {
                    int x = 2 * k, y = 2 * k + 1;
                    Dd.Merge(
                        Dd.Load(ar[below], arLo[below], x), Dd.Load(ai[below], aiLo[below], x),
                        Dd.Load(br[below], brLo[below], x), Dd.Load(bi[below], biLo[below], x),
                        Dd.Load(ar[below], arLo[below], y), Dd.Load(ai[below], aiLo[below], y),
                        Dd.Load(br[below], brLo[below], y), Dd.Load(bi[below], biLo[below], y),
                        out Dd nar, out Dd nai, out Dd nbr, out Dd nbi);
                    double radius = Merge(
                        r[below][x], r[below][y], ar[below][x], ai[below][x], br[below][x], bi[below][x], dcBound);
                    Dd.Store(nar, ar[level], arLo[level], k);
                    Dd.Store(nai, ai[level], aiLo[level], k);
                    Dd.Store(nbr, br[level], brLo[level], k);
                    Dd.Store(nbi, bi[level], biLo[level], k);
                    r[level][k] = Alive(radius, nar.Hi, nai.Hi, nbr.Hi, nbi.Hi);
                }
            }
            return new BlaTable(ar, ai, br, bi, r, extent);
        }

        // --- T2 (spec/deep-zoom.md "BLA at T2") ---------------------------------------------

        private static readonly ConditionalWeakTable<double[], List<(double[] Im, int Samples, double R, long? Dc, BlaTableX Table)>> TablesX =
            new ConditionalWeakTable<double[], List<(double[] Im, int Samples, double R, long? Dc, BlaTableX Table)>>();

        /// <summary><see cref="BuildX"/>, re-using a table already built for these same arrays and inputs.</summary>
        internal static BlaTableX GetX(double[] orbitRe, double[] orbitIm, bool[] small, int samples, double escapeRadius, long? dcExponent)
        {
            var list = TablesX.GetValue(orbitRe, _ => new List<(double[], int, double, long?, BlaTableX)>());
            lock (list)
            {
                foreach (var entry in list)
                {
                    if (ReferenceEquals(entry.Im, orbitIm) && entry.Samples == samples
                        && entry.R.Equals(escapeRadius) && entry.Dc == dcExponent)
                        return entry.Table;
                }
            }
            var table = BuildX(orbitRe, orbitIm, small, samples, escapeRadius, dcExponent);
            lock (list)
            {
                if (list.Count >= 4)
                    list.RemoveAt(0);
                list.Add((orbitIm, samples, escapeRadius, dcExponent, table));
            }
            return table;
        }

        /// <summary><see cref="FrameDcBoundExponent(FloatExp, FloatExp)"/> over a T2 frame's own floatexp pixel deltas (an off-center offset included).</summary>
        internal static long? FrameDcBoundExponent(int width, int height, Viewport viewport)
        {
            FloatExp ps = FractalEngine.PixelScaleX(width, viewport.ZoomLog10);
            bool offCenter = viewport.HasReference;
            FloatExp dRe = offCenter ? DecimalText.DifferenceX(viewport.CenterRe, viewport.ReferenceRe!) : FloatExp.Zero;
            FloatExp dIm = offCenter ? DecimalText.DifferenceX(viewport.CenterIm, viewport.ReferenceIm!) : FloatExp.Zero;
            FloatExp maxRe = FloatExp.Zero, maxIm = FloatExp.Zero;
            for (int x = 0; x < width; x++)
            {
                FloatExp v = FractalEngine.OffsetReX(x, width, ps);
                if (offCenter)
                    v = FloatExp.Add(dRe, v);
                if (v.M < 0.0)
                    v = v.Neg();
                if (FloatExp.Compare(v, maxRe) > 0)
                    maxRe = v;
            }
            for (int y = 0; y < height; y++)
            {
                FloatExp v = FractalEngine.OffsetImX(y, height, ps);
                if (offCenter)
                    v = FloatExp.Add(dIm, v);
                if (v.M < 0.0)
                    v = v.Neg();
                if (FloatExp.Compare(v, maxIm) > 0)
                    maxIm = v;
            }
            return FrameDcBoundExponent(maxRe, maxIm);
        }

        /// <summary>
        /// The T2 frame's bound on |dc| as 2^k: Mag(max |dc.re|, max |dc.im|) over the frame's
        /// floatexp pixel deltas, rounded up to a power of two; null when every delta is zero.
        /// The magnitude is <see cref="Mag"/> of the pair scaled by 2^-E (E the larger exponent
        /// of the nonzero maxima), times 2^E.
        /// </summary>
        internal static long? FrameDcBoundExponent(FloatExp maxAbsRe, FloatExp maxAbsIm)
        {
            if (maxAbsRe.IsZero && maxAbsIm.IsZero)
                return null;
            long exponent = maxAbsIm.IsZero ? maxAbsRe.E : maxAbsRe.IsZero ? maxAbsIm.E : Math.Max(maxAbsRe.E, maxAbsIm.E);
            double m = Mag(maxAbsRe.Scaled(exponent), maxAbsIm.Scaled(exponent));   // in [1, 2√2]
            int binade = FloatExp.Binade(m);
            return exponent + (m == FloatExp.Pow2(binade) ? binade : binade + 1);
        }

        /// <summary>
        /// T1's merge in floatexp: num = r2 − |B_x|·2^k; num &gt; 0 ? min(r1, num / |A_x|) : 0,
        /// |A_x| = 0 keeping r1 (and its +∞); a magnitude that is not finite gives 0 (such an
        /// entry is dead anyway: its own coefficients cannot be finite).
        /// </summary>
        private static FloatExp MergeX(
            FloatExp r1, bool r1Infinite, FloatExp r2, double ar, double ai, double br, double bi, long? dcExponent,
            out bool infinite)
        {
            infinite = false;
            double magA = Mag(ar, ai), magB = Mag(br, bi);
            if (double.IsNaN(magA) || double.IsInfinity(magA) || double.IsNaN(magB) || double.IsInfinity(magB))
                return FloatExp.Zero;
            FloatExp term = dcExponent.HasValue ? FloatExp.Normalize(magB, dcExponent.Value) : FloatExp.Zero;
            FloatExp num = FloatExp.Sub(r2, term);
            if (!(num.M > 0.0))
                return FloatExp.Zero;
            if (magA == 0.0)
            {
                infinite = r1Infinite;
                return r1;
            }
            FloatExp q = FloatExp.Div(num, FloatExp.FromDouble(magA));
            return r1Infinite || FloatExp.Compare(q, r1) < 0 ? q : r1;
        }

        /// <summary>The dead rule at T2: live only if the radius is positive and finite and |A|, |B| &lt; 2^960.</summary>
        private static FloatExp AliveX(FloatExp r, bool infinite, double ar, double ai, double br, double bi)
            => r.M > 0.0 && !infinite && Mag(ar, ai) < Cap && Mag(br, bi) < Cap ? r : FloatExp.Zero;

        /// <summary>
        /// The T2 table (spec/deep-zoom.md "BLA at T2"): <see cref="Build"/>'s coefficients (the
        /// same double-double fold, each entry storing the hi of each component) with its radii
        /// in floatexp, the dc bound 2^dcExponent (null: zero), from those stored values. A step at a small index (<paramref name="small"/>, the
        /// orbit's small table) has radius 0, so no span containing one is ever taken: its
        /// float64 sample may have lost bits.
        /// </summary>
        internal static BlaTableX BuildX(
            double[] orbitRe, double[] orbitIm, bool[] small, int samples, double escapeRadius, long? dcExponent)
        {
            if (samples < 1 || samples > orbitRe.Length || samples > orbitIm.Length || samples > small.Length)
                throw new ArgumentOutOfRangeException(nameof(samples));
            double r2 = escapeRadius * escapeRadius;
            int extent = samples - 1;
            for (int k = 1; k < samples; k++)
            {
                if (orbitRe[k] * orbitRe[k] + orbitIm[k] * orbitIm[k] > r2)
                {
                    extent = k;
                    break;
                }
            }
            int n0 = Math.Max(extent, 0) / Stride;
            if (n0 == 0)
                return new BlaTableX(new double[0][], new double[0][], new double[0][], new double[0][], new FloatExp[0][], extent);
            int levels = 1;
            for (int count = n0; levels < LevelCap && count >= 2; count /= 2)
                levels++;
            var ar = new double[levels][];
            var ai = new double[levels][];
            var br = new double[levels][];
            var bi = new double[levels][];
            var r = new FloatExp[levels][];
            // The lo parts, level by level: a merge reads its children's pairs.
            var arLo = new double[levels][];
            var aiLo = new double[levels][];
            var brLo = new double[levels][];
            var biLo = new double[levels][];
            ar[0] = new double[n0];
            ai[0] = new double[n0];
            br[0] = new double[n0];
            bi[0] = new double[n0];
            arLo[0] = new double[n0];
            aiLo[0] = new double[n0];
            brLo[0] = new double[n0];
            biLo[0] = new double[n0];
            r[0] = new FloatExp[n0];
            for (int block = 0; block < n0; block++)
            {
                Dd.FoldStart(out Dd xar, out Dd xai, out Dd xbr, out Dd xbi);
                FloatExp radius = FloatExp.Zero;
                bool infinite = true;
                for (int j = 0; j < Stride; j++)
                {
                    int index = block * Stride + j;
                    double zr = orbitRe[index], zi = orbitIm[index];
                    // eps·|Z|, exact; 0 at a small index
                    FloatExp step = small[index] ? FloatExp.Zero : FloatExp.Normalize(Mag(zr, zi), -53);
                    radius = MergeX(radius, infinite, step, xar.Hi, xai.Hi, xbr.Hi, xbi.Hi, dcExponent, out infinite);
                    Dd.FoldStep(ref xar, ref xai, ref xbr, ref xbi, zr, zi);
                }
                Dd.Store(xar, ar[0], arLo[0], block);
                Dd.Store(xai, ai[0], aiLo[0], block);
                Dd.Store(xbr, br[0], brLo[0], block);
                Dd.Store(xbi, bi[0], biLo[0], block);
                r[0][block] = AliveX(radius, infinite, xar.Hi, xai.Hi, xbr.Hi, xbi.Hi);
            }
            for (int level = 1; level < levels; level++)
            {
                int count = r[level - 1].Length / 2;
                ar[level] = new double[count];
                ai[level] = new double[count];
                br[level] = new double[count];
                bi[level] = new double[count];
                arLo[level] = new double[count];
                aiLo[level] = new double[count];
                brLo[level] = new double[count];
                biLo[level] = new double[count];
                r[level] = new FloatExp[count];
                int below = level - 1;
                for (int k = 0; k < count; k++)
                {
                    int x = 2 * k, y = 2 * k + 1;
                    Dd.Merge(
                        Dd.Load(ar[below], arLo[below], x), Dd.Load(ai[below], aiLo[below], x),
                        Dd.Load(br[below], brLo[below], x), Dd.Load(bi[below], biLo[below], x),
                        Dd.Load(ar[below], arLo[below], y), Dd.Load(ai[below], aiLo[below], y),
                        Dd.Load(br[below], brLo[below], y), Dd.Load(bi[below], biLo[below], y),
                        out Dd nar, out Dd nai, out Dd nbr, out Dd nbi);
                    FloatExp radius = MergeX(
                        r[below][x], false, r[below][y], ar[below][x], ai[below][x], br[below][x], bi[below][x],
                        dcExponent, out bool infinite);
                    Dd.Store(nar, ar[level], arLo[level], k);
                    Dd.Store(nai, ai[level], aiLo[level], k);
                    Dd.Store(nbr, br[level], brLo[level], k);
                    Dd.Store(nbi, bi[level], biLo[level], k);
                    r[level][k] = AliveX(radius, infinite, nar.Hi, nai.Hi, nbr.Hi, nbi.Hi);
                }
            }
            return new BlaTableX(ar, ai, br, bi, r, extent);
        }

        /// <summary>
        /// Double-double (spec/deep-zoom.md "BLA", "Arithmetic"): a value is Hi + Lo, two
        /// doubles; every operation is plain IEEE float64 with no fused multiply-add, in the
        /// Python reference's order, so both ports agree bit for bit.
        /// </summary>
        private readonly struct Dd
        {
            private const double Splitter = 134217729.0;   // 2^27 + 1, Dekker's

            internal readonly double Hi;
            internal readonly double Lo;

            internal Dd(double hi, double lo)
            {
                Hi = hi;
                Lo = lo;
            }

            private static Dd TwoSum(double a, double b)
            {
                double s = a + b;
                double bb = s - a;
                return new Dd(s, (a - (s - bb)) + (b - bb));
            }

            private static Dd QuickTwoSum(double a, double b)
            {
                double s = a + b;
                return new Dd(s, b - (s - a));
            }

            private static void Split(double a, out double hi, out double lo)
            {
                double t = Splitter * a;
                hi = t - (t - a);
                lo = a - hi;
            }

            private static Dd TwoProd(double a, double b)
            {
                double p = a * b;
                Split(a, out double ah, out double al);
                Split(b, out double bh, out double bl);
                return new Dd(p, (((ah * bh - p) + ah * bl) + al * bh) + al * bl);
            }

            internal static Dd Mul(Dd x, Dd y)
            {
                Dd p = TwoProd(x.Hi, y.Hi);
                return QuickTwoSum(p.Hi, p.Lo + (x.Hi * y.Lo + x.Lo * y.Hi));
            }

            internal static Dd Add(Dd x, Dd y)
            {
                Dd s = TwoSum(x.Hi, y.Hi);
                return QuickTwoSum(s.Hi, s.Lo + (x.Lo + y.Lo));
            }

            private Dd Neg() => new Dd(-Hi, -Lo);

            /// <summary>(x.re y.re − x.im y.im, x.re y.im + x.im y.re).</summary>
            internal static void CMul(Dd xr, Dd xi, Dd yr, Dd yi, out Dd pr, out Dd pi)
            {
                pr = Add(Mul(xr, yr), Mul(xi, yi).Neg());
                pi = Add(Mul(xr, yi), Mul(xi, yr));
            }

            /// <summary>A level-0 fold's start: A = 1, B = 0.</summary>
            internal static void FoldStart(out Dd ar, out Dd ai, out Dd br, out Dd bi)
            {
                ar = new Dd(1.0, 0.0);
                ai = new Dd(0.0, 0.0);
                br = new Dd(0.0, 0.0);
                bi = new Dd(0.0, 0.0);
            }

            /// <summary>One step of a level-0 fold, a = 2Z exact: B ← (a·B).re + 1, (a·B).im; A ← a·A.</summary>
            internal static void FoldStep(ref Dd ar, ref Dd ai, ref Dd br, ref Dd bi, double zr, double zi)
            {
                var sr = new Dd(2.0 * zr, 0.0);
                var si = new Dd(2.0 * zi, 0.0);
                CMul(sr, si, br, bi, out Dd abr, out Dd abi);
                CMul(sr, si, ar, ai, out ar, out ai);
                br = Add(abr, new Dd(1.0, 0.0));
                bi = abi;
            }

            /// <summary>x followed by y: A = A_y·A_x, B = A_y·B_x + B_y, on the children's pairs.</summary>
            internal static void Merge(
                Dd xar, Dd xai, Dd xbr, Dd xbi, Dd yar, Dd yai, Dd ybr, Dd ybi,
                out Dd ar, out Dd ai, out Dd br, out Dd bi)
            {
                CMul(yar, yai, xar, xai, out ar, out ai);
                CMul(yar, yai, xbr, xbi, out Dd pr, out Dd pi);
                br = Add(pr, ybr);
                bi = Add(pi, ybi);
            }

            internal static Dd Load(double[] hi, double[] lo, int index) => new Dd(hi[index], lo[index]);

            internal static void Store(Dd value, double[] hi, double[] lo, int index)
            {
                hi[index] = value.Hi;
                lo[index] = value.Lo;
            }
        }
    }

    /// <summary>
    /// A T2 BLA table (spec/deep-zoom.md "BLA at T2"): <see cref="BlaTable"/>'s coefficients
    /// with each radius in floatexp (zero = dead).
    /// </summary>
    internal sealed class BlaTableX
    {
        internal BlaTableX(double[][] ar, double[][] ai, double[][] br, double[][] bi, FloatExp[][] r, int extent)
        {
            Ar = ar;
            Ai = ai;
            Br = br;
            Bi = bi;
            R = r;
            Extent = extent;
        }

        internal double[][] Ar { get; }
        internal double[][] Ai { get; }
        internal double[][] Br { get; }
        internal double[][] Bi { get; }
        internal FloatExp[][] R { get; }

        /// <summary>k*: the steps tabulated are 0 .. Extent - 1.</summary>
        internal int Extent { get; }

        internal int Levels => R.Length;

        /// <summary>Whether any entry can ever be taken (a parent is dead when its left child is).</summary>
        internal bool Live
        {
            get
            {
                if (R.Length == 0)
                    return false;
                foreach (FloatExp r in R[0])
                    if (r.M > 0.0)
                        return true;
                return false;
            }
        }
    }
}
