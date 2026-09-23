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
    }
}
