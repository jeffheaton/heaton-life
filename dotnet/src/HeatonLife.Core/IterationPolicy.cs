using System;

namespace HeatonLife
{
    /// <summary>
    /// Iteration policy (spec/fractals.md "Iteration policy", policy version 1): how many
    /// iterations a frame deserves. A host's choice, versioned apart from the counts —
    /// changing it changes which max_iter a host asks for, never what a given max_iter
    /// renders. Integer and pinned float arithmetic only, so every port suggests the same
    /// budget. The Python reference's heaton_life.fractal.policy.
    /// </summary>
    public static class IterationPolicy
    {
        /// <summary>
        /// The depth ramp: 400 + round(200 · max(0, zoom)), rounding half to even, capped at
        /// int.MaxValue (reached near zoom 1.07e7).
        /// </summary>
        public static int AutoMaxIter(double zoomLog10)
        {
            if (double.IsNaN(zoomLog10) || double.IsInfinity(zoomLog10))
                throw new ArgumentException($"zoom must be finite, got {zoomLog10}", nameof(zoomLog10));
            double scaled = 200.0 * Math.Max(0.0, zoomLog10);
            if (scaled >= 2147483648.0)                           // past the cap
                return int.MaxValue;
            long ramp = 400 + (long)Math.Round(scaled, MidpointRounding.ToEven);
            return (int)Math.Min(ramp, int.MaxValue);
        }

        /// <summary>
        /// The iteration by which 99.9% of a frame's escaped pixels escaped: the nearest-rank
        /// 99.9th percentile of the positive counts, rank ceil(0.999 n) computed in integers;
        /// 0 when nothing escaped.
        /// </summary>
        public static int NeedFromCounts(int[] counts)
        {
            if (counts == null)
                throw new ArgumentNullException(nameof(counts));
            int n = 0;
            foreach (int count in counts)
                if (count > 0)
                    n++;
            if (n == 0)
                return 0;
            var escaped = new int[n];
            int k = 0;
            foreach (int count in counts)
                if (count > 0)
                    escaped[k++] = count;
            Array.Sort(escaped);
            long rank = (999L * n + 999) / 1000;               // ceil(999 n / 1000), 1-based
            return escaped[rank - 1];
        }

        /// <summary>max(the depth ramp, twice what the frame's own escapes needed).</summary>
        public static int SuggestMaxIter(double zoomLog10, int[] counts)
        {
            long twice = 2L * NeedFromCounts(counts);
            return (int)Math.Min(Math.Max(AutoMaxIter(zoomLog10), twice), int.MaxValue);
        }

        /// <summary>
        /// A movie frame's budget without a user limit (spec/zoom.md "Iteration budget"): the
        /// depth ramp.
        /// </summary>
        public static int MovieMaxIter(double zoomLog10, double targetZoomLog10) =>
            AutoMaxIter(zoomLog10);

        /// <summary>
        /// A movie frame's budget with a user limit U (1 ≤ U): the depth ramp scaled to
        /// reach exactly U at the target, min(U, max(a, (U · a) / a_T)) with a =
        /// AutoMaxIter(zoom) and a_T = AutoMaxIter(target), the product in 64 bits (it
        /// reaches 2^62) and the quotient floored.
        /// </summary>
        public static int MovieMaxIter(double zoomLog10, double targetZoomLog10, int userLimit)
        {
            if (userLimit < 1)
                throw new ArgumentOutOfRangeException(nameof(userLimit), $"an iteration limit must lie in [1, 2^31 - 1], got {userLimit}");
            int ramp = AutoMaxIter(zoomLog10);
            long scaled = (long)userLimit * ramp / AutoMaxIter(targetZoomLog10);
            return (int)Math.Min(userLimit, Math.Max(ramp, scaled));
        }

        /// <summary>
        /// The measured need at a depth from a survey's knots (zoom, need), ascending in zoom:
        /// the larger of the two knots around it; the nearer knot's past either end; at a knot,
        /// the largest of it and its two neighbors. No knots: 0.
        /// </summary>
        public static int NeedAt(double zoomLog10, (double Zoom, int Need)[] knots)
        {
            if (double.IsNaN(zoomLog10) || double.IsInfinity(zoomLog10))
                throw new ArgumentException($"zoom must be finite, got {zoomLog10}", nameof(zoomLog10));
            if (knots == null)
                throw new ArgumentNullException(nameof(knots));
            int n = knots.Length;
            if (n == 0)
                return 0;
            for (int k = 0; k < n; k++)
            {
                if (knots[k].Zoom == zoomLog10)
                {
                    int need = knots[k].Need;
                    if (k > 0)
                        need = Math.Max(need, knots[k - 1].Need);
                    if (k + 1 < n)
                        need = Math.Max(need, knots[k + 1].Need);
                    return need;
                }
            }
            if (!(zoomLog10 > knots[0].Zoom))
                return knots[0].Need;
            if (!(zoomLog10 < knots[n - 1].Zoom))
                return knots[n - 1].Need;
            int deeper = 1;
            while (!(knots[deeper].Zoom > zoomLog10))
                deeper++;
            return Math.Max(knots[deeper - 1].Need, knots[deeper].Need);
        }

        /// <summary>
        /// A movie frame's budget from a survey (Heaton Fractal's measured mode):
        /// min(max(AutoMaxIter(zoom), 2 · NeedAt(zoom, knots)), 2^31 − 1).
        /// </summary>
        public static int MeasuredMaxIter(double zoomLog10, (double Zoom, int Need)[] knots)
        {
            long twice = 2L * NeedAt(zoomLog10, knots);
            return (int)Math.Min(Math.Max(AutoMaxIter(zoomLog10), twice), int.MaxValue);
        }
    }
}
