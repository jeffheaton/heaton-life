using System;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// T2 perturbation past zoom 1e290 (spec/deep-zoom.md "T2"): each pixel carries its
    /// delta as a float64 pair w and an integer exponent E, delta = w·2^E, renormalized by
    /// exact powers of two when max(|w|) leaves [2^-64, 2^64]. A step at a normal reference
    /// index (|Z| ≥ 2^-400) is T1's shape on w in plain real float64 operations; at a small
    /// index (Z = 0 or |Z| &lt; 2^-400, from the orbit's floatexp small table) the step, and
    /// the escape and rebase tests that land there, run in <see cref="FloatExp"/> per
    /// component. No fused multiply-add anywhere. The Python reference's
    /// heaton_life.fractal.perturbation_t2, pixel for pixel and bit for bit.
    /// </summary>
    internal static class PerturbationT2
    {
        internal const int Band = 64;
        internal const int DcGap = 960;
        private static readonly double Low = FloatExp.Pow2(-Band);
        private static readonly double High = FloatExp.Pow2(Band);

        /// <summary>One orbit as T2 reads it: the double samples, a small flag per index, and the small table.</summary>
        internal sealed class Orbit
        {
            internal Orbit(double[] re, double[] im, ReferenceOrbit.SmallSamples small)
            {
                Re = re;
                Im = im;
                Small = new bool[re.Length];
                Table = small;
                foreach (int index in small.Index)
                {
                    if (index < re.Length)
                        Small[index] = true;
                }
            }

            internal double[] Re { get; }
            internal double[] Im { get; }
            internal bool[] Small { get; }
            internal ReferenceOrbit.SmallSamples Table { get; }

            /// <summary>Z[m] in floatexp: the small table where small, else the double sample exactly.</summary>
            internal void Z(int m, out FloatExp zr, out FloatExp zi)
            {
                if (Small[m])
                {
                    int row = Array.BinarySearch(Table.Index, m);
                    zr = Table.Re[row];
                    zi = Table.Im[row];
                }
                else
                {
                    zr = FloatExp.FromDouble(Re[m]);
                    zi = FloatExp.FromDouble(Im[m]);
                }
            }
        }

        /// <summary>
        /// T2 escape count for one pixel of a z^2 + c map (Mandelbrot: delta0 = 0; Julia:
        /// deltaC = 0 and <paramref name="rebase"/> the critical orbit). With
        /// <paramref name="track"/> it also carries the distance derivative d, starting at
        /// (d0r, d0i) and adding <paramref name="add"/> each step (Mandelbrot: 0 and ps;
        /// Julia: ps and none), and returns it as (dr, di)·2^dExponent.
        /// </summary>
        internal static int Perturb(
            Orbit orbit, Orbit rebase, FloatExp delta0r, FloatExp delta0i, FloatExp dcr, FloatExp dci,
            int maxIter, double escapeRadius,
            bool track, FloatExp d0r, FloatExp d0i, FloatExp add, bool hasAdd,
            out double finalRe, out double finalIm, out double dr, out double di, out long dExponent,
            CancellationToken cancellationToken = default)
        {
            Orbit cur = orbit;
            int m = 0;
            int last = orbit.Re.Length - 1;
            double r2 = escapeRadius * escapeRadius;
            FloatExp r2x = FloatExp.FromDouble(r2);
            bool hasDc = !dcr.IsZero || !dci.IsZero;

            double wr, wi;
            long e;
            if (delta0r.IsZero && delta0i.IsZero)
            {
                // E = the larger exponent of deltaC's nonzero parts (0 if both are zero); no
                // output depends on it, since index 0 is small and the first step is slow.
                SplitPair(dcr, dci, 0, out _, out _, out e);
                wr = 0.0;
                wi = 0.0;
            }
            else
            {
                SplitPair(delta0r, delta0i, 0, out wr, out wi, out e);
            }
            DcScaled(dcr, dci, hasDc, e, out double dcsR, out double dcsI, out bool dcBad);

            double dwr = 0.0, dwi = 0.0, adds = 0.0;
            long dE = 0;
            bool addBad = false;
            bool zSmall = false;
            double zdr = 0.0, zdi = 0.0;
            FloatExp zxr = FloatExp.Zero, zxi = FloatExp.Zero;
            if (track)
            {
                SplitPair(d0r, d0i, hasAdd ? add.E : 0, out dwr, out dwi, out dE);
                Landing(cur, m, wr, wi, e, out zSmall, out zdr, out zdi, out zxr, out zxi);
                AddScaled(add, hasAdd, dE, out adds, out addBad);
            }

            for (long it = 1; it <= maxIter; it++)
            {
                // A T2 pixel can run for millions of iterations: poll here, not only per row.
                if ((it & ((1 << 16) - 1)) == 0)
                    cancellationToken.ThrowIfCancellationRequested();
                if (track)
                {
                    // d' = 2 z d + add, from the pre-step z (fractals.md "Distance estimate").
                    if (zSmall || addBad)
                    {
                        FloatExp dxr = FloatExp.Normalize(dwr, dE), dxi = FloatExp.Normalize(dwi, dE);
                        FloatExp zr = zSmall ? zxr : FloatExp.FromDouble(zdr);
                        FloatExp zi = zSmall ? zxi : FloatExp.FromDouble(zdi);
                        CMul(zr, zi, dxr, dxi, out FloatExp pr, out FloatExp pi);
                        pr = pr.Twice();
                        pi = pi.Twice();
                        if (hasAdd)
                            pr = FloatExp.Add(pr, add);
                        SplitPair(pr, pi, dE, out dwr, out dwi, out dE);
                    }
                    else
                    {
                        double tr = 2.0 * (zdr * dwr - zdi * dwi) + adds;
                        double ti = 2.0 * (zdr * dwi + zdi * dwr);
                        dwr = tr;
                        dwi = ti;
                    }
                    Renormalize(ref dwr, ref dwi, ref dE);
                    AddScaled(add, hasAdd, dE, out adds, out addBad);
                }

                // --- the step ---------------------------------------------------------
                if (cur.Small[m] || dcBad)
                {
                    cur.Z(m, out FloatExp zr, out FloatExp zi);
                    FloatExp xr = FloatExp.Normalize(wr, e), xi = FloatExp.Normalize(wi, e);
                    FloatExp tr = FloatExp.Add(zr.Twice(), xr), ti = FloatExp.Add(zi.Twice(), xi);
                    CMul(tr, ti, xr, xi, out FloatExp pr, out FloatExp pi);
                    SplitPair(FloatExp.Add(pr, dcr), FloatExp.Add(pi, dci), e, out wr, out wi, out e);
                }
                else
                {
                    DeltaDouble(wr, wi, e, out double ddr, out double ddi);
                    double tr = 2.0 * cur.Re[m] + ddr;
                    double ti = 2.0 * cur.Im[m] + ddi;
                    double nwr = (tr * wr - ti * wi) + dcsR;
                    double nwi = (tr * wi + ti * wr) + dcsI;
                    wr = nwr;
                    wi = nwi;
                }
                m = Math.Min(m + 1, last);
                Renormalize(ref wr, ref wi, ref e);
                DcScaled(dcr, dci, hasDc, e, out dcsR, out dcsI, out dcBad);

                // --- landing: escape, then rebase ---------------------------------------
                Landing(cur, m, wr, wi, e, out zSmall, out zdr, out zdi, out zxr, out zxi);
                bool escaped, rebased;
                if (zSmall)
                {
                    FloatExp za = Abs2(zxr, zxi);
                    FloatExp da = Abs2(FloatExp.Normalize(wr, e), FloatExp.Normalize(wi, e));
                    escaped = FloatExp.Compare(za, r2x) > 0;
                    rebased = FloatExp.Compare(za, da) < 0;
                }
                else
                {
                    DeltaDouble(wr, wi, e, out double ddr, out double ddi);
                    double zabs2 = zdr * zdr + zdi * zdi;
                    escaped = zabs2 > r2;
                    rebased = zabs2 < ddr * ddr + ddi * ddi;
                }
                if (escaped)
                {
                    finalRe = zdr;
                    finalIm = zdi;
                    dr = dwr;
                    di = dwi;
                    dExponent = dE;
                    return (int)it;
                }
                if (rebased)
                {
                    FloatExp nr = zSmall ? zxr : FloatExp.FromDouble(zdr);
                    FloatExp ni = zSmall ? zxi : FloatExp.FromDouble(zdi);
                    SplitPair(nr, ni, e, out wr, out wi, out e);
                    cur = rebase;
                    m = 0;
                    last = cur.Re.Length - 1;
                    DcScaled(dcr, dci, hasDc, e, out dcsR, out dcsI, out dcBad);
                }
            }
            finalRe = 0.0;
            finalIm = 0.0;
            dr = 0.0;
            di = 0.0;
            dExponent = 0;
            return -1;
        }

        /// <summary>
        /// z = Z[m] + delta: at a normal index as doubles (Z + delta_d); at a small index in
        /// floatexp, with its double (ToDouble's rounding) for the final z.
        /// </summary>
        private static void Landing(
            Orbit cur, int m, double wr, double wi, long e,
            out bool small, out double zdr, out double zdi, out FloatExp zxr, out FloatExp zxi)
        {
            small = cur.Small[m];
            if (small)
            {
                cur.Z(m, out FloatExp zr, out FloatExp zi);
                zxr = FloatExp.Add(zr, FloatExp.Normalize(wr, e));
                zxi = FloatExp.Add(zi, FloatExp.Normalize(wi, e));
                zdr = zxr.ToDouble();
                zdi = zxi.ToDouble();
            }
            else
            {
                DeltaDouble(wr, wi, e, out double ddr, out double ddi);
                zdr = cur.Re[m] + ddr;
                zdi = cur.Im[m] + ddi;
                zxr = FloatExp.Zero;
                zxi = FloatExp.Zero;
            }
        }

        /// <summary>delta as a double pair: w·2^E for E ≥ −1022 (one multiply by an exact normal power of two), else 0.</summary>
        private static void DeltaDouble(double wr, double wi, long e, out double ddr, out double ddi)
        {
            if (e < FloatExp.MinNormalExp)
            {
                ddr = 0.0;
                ddi = 0.0;
                return;
            }
            double p = FloatExp.Pow2((int)Math.Min(e, FloatExp.MaxExp));
            ddr = wr * p;
            ddi = wi * p;
        }

        /// <summary>
        /// (w, E) from a complex floatexp: E = the larger exponent of the nonzero parts
        /// (<paramref name="keep"/> when both are zero), w = each part / 2^E.
        /// </summary>
        private static void SplitPair(FloatExp xr, FloatExp xi, long keep, out double wr, out double wi, out long e)
        {
            if (xr.IsZero && xi.IsZero)
                e = keep;
            else if (xr.IsZero)
                e = xi.E;
            else if (xi.IsZero)
                e = xr.E;
            else
                e = Math.Max(xr.E, xi.E);
            wr = xr.IsZero ? 0.0 : xr.Scaled(e);
            wi = xi.IsZero ? 0.0 : xi.Scaled(e);
        }

        /// <summary>
        /// When max(|w|) (nonzero) leaves [2^-64, 2^64], scale it into [1, 2) by an exact power
        /// of two (two multiplies, the second by 1 unless the max was subnormal) and move E.
        /// </summary>
        private static void Renormalize(ref double wr, ref double wi, ref long e)
        {
            double big = Math.Max(Math.Abs(wr), Math.Abs(wi));
            if (big == 0.0 || (big >= Low && big <= High))
                return;
            int k = FloatExp.Binade(big);
            int first = Math.Max(FloatExp.MinNormalExp, Math.Min(FloatExp.MaxExp, -k));
            int rest = -k - first;
            double p1 = FloatExp.Pow2(first), p2 = FloatExp.Pow2(rest);
            wr = (wr * p1) * p2;
            wi = (wi * p1) * p2;
            e += k;
            if (e < FloatExp.ExpFloor)
            {
                // Past 2^-(2^31) the value is zero (FloatExp.ExpFloor), so exponents never overflow.
                wr = 0.0;
                wi = 0.0;
            }
        }

        /// <summary>delta_c / 2^E per component (ToDouble's rounding), and whether a nonzero component sits more than DcGap binades above 2^E.</summary>
        private static void DcScaled(FloatExp dcr, FloatExp dci, bool hasDc, long e, out double sr, out double si, out bool bad)
        {
            if (!hasDc)
            {
                sr = 0.0;
                si = 0.0;
                bad = false;
                return;
            }
            sr = dcr.IsZero ? 0.0 : dcr.Scaled(e);
            si = dci.IsZero ? 0.0 : dci.Scaled(e);
            bad = (!dcr.IsZero && dcr.E - e > DcGap) || (!dci.IsZero && dci.E - e > DcGap);
        }

        private static void AddScaled(FloatExp add, bool hasAdd, long dE, out double s, out bool bad)
        {
            if (!hasAdd || add.IsZero)
            {
                s = 0.0;
                bad = false;
                return;
            }
            s = add.Scaled(dE);
            bad = add.E - dE > DcGap;
        }

        /// <summary>(a.r b.r − a.i b.i, a.r b.i + a.i b.r) in floatexp.</summary>
        private static void CMul(FloatExp ar, FloatExp ai, FloatExp br, FloatExp bi, out FloatExp pr, out FloatExp pi)
        {
            FloatExp rr = FloatExp.Mul(ar, br);
            FloatExp ii = FloatExp.Mul(ai, bi);
            FloatExp ri = FloatExp.Mul(ar, bi);
            FloatExp ir = FloatExp.Mul(ai, br);
            pr = FloatExp.Add(rr, ii.Neg());
            pi = FloatExp.Add(ri, ir);
        }

        private static FloatExp Abs2(FloatExp r, FloatExp i) => FloatExp.Add(FloatExp.Mul(r, r), FloatExp.Mul(i, i));

        /// <summary>
        /// The distance estimate for a T2 derivative d = (dr, di)·2^dExponent: the T1 formula
        /// on (dr, di), then that value / 2^dExponent rounded once — +∞, 0 and NaN as
        /// <see cref="FractalEngine.DistanceEstimate"/> gives them.
        /// </summary>
        internal static double DistanceEstimate(int count, double fr, double fi, double dr, double di, long dExponent)
        {
            double de = FractalEngine.DistanceEstimate(count, fr, fi, dr, di);
            if (double.IsNaN(de) || double.IsInfinity(de) || de == 0.0)
                return de;
            return FloatExp.Normalize(de, -dExponent).ToDouble();
        }
    }
}
