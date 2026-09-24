using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>
    /// A zoom movie's survey (spec/zoom.md, "Survey"): the depths it probes, the patience
    /// rule that measures at each how late the location's points escape, and the budget
    /// every frame gets from it — Heaton Fractal's measured mode, or with a user limit
    /// <see cref="IterationPolicy.MovieMaxIter(double, double, int)"/>. The host renders
    /// the probes: a <see cref="ProbeWidth"/> × <see cref="ProbeHeight"/> frame of the
    /// movie's own field at the station's zoom and the movie's center, its counts and
    /// statuses. Bit-exact with the Python reference (heaton_life.fractal.movie).
    /// </summary>
    public static class ZoomSurvey
    {
        /// <summary>The double nearest log10(2): 0x3FD34413509F79FF.</summary>
        public const double Log10Of2 = 0.3010299956639812;

        /// <summary>A probe's width in pixels (Heaton Fractal's palette pre-pass probe).</summary>
        public const int ProbeWidth = 192;

        /// <summary>A probe's height in pixels.</summary>
        public const int ProbeHeight = 108;

        /// <summary>The default cap is this many times the depth ramp at the deepest zoom.</summary>
        public const int CapFactor = 64;

        private static readonly int[] ApproachOctaves = { 32, 24, 16, 12, 8, 7, 6, 5, 4, 3, 2, 1 };

        /// <summary>
        /// The depths (log10) a survey probes, ascending: the shallow end; every
        /// <paramref name="spacingOctaves"/> below it while at least 33 octaves short of the
        /// deep end; the approach, 32, 24, 16, 12, 8, 7, …, 1 octaves short of the deep end,
        /// where more than an octave past the shallow end; and the deep end. The regular and
        /// approach stations keep an octave apart; both ends are always probed.
        /// </summary>
        public static double[] Stations(ZoomPlan plan, int spacingOctaves = 64)
        {
            if (plan == null)
                throw new ArgumentNullException(nameof(plan));
            if (spacingOctaves < 1)
                throw new ArgumentOutOfRangeException(nameof(spacingOctaves), $"spacingOctaves must be >= 1, got {spacingOctaves}");
            double low = plan.ShallowestZoom, high = plan.DeepestZoom;
            double step = spacingOctaves * Log10Of2;
            double regularLimit = high - 33.0 * Log10Of2;
            double approachFloor = low + Log10Of2;
            var stations = new List<double> { low };
            for (int index = 1; ; index++)
            {
                double zoom = low + index * step;
                if (!(zoom < regularLimit))
                    break;
                stations.Add(zoom);
            }
            foreach (int octaves in ApproachOctaves)
            {
                double zoom = high - octaves * Log10Of2;
                if (zoom > approachFloor)
                    stations.Add(zoom);
            }
            if (high > low)
                stations.Add(high);
            return stations.ToArray();
        }

        /// <summary>The default probe cap: min(64 · AutoMaxIter(deepest zoom), 2^31 − 1).</summary>
        public static int DefaultCap(ZoomPlan plan)
        {
            if (plan == null)
                throw new ArgumentNullException(nameof(plan));
            return (int)Math.Min((long)CapFactor * IterationPolicy.AutoMaxIter(plan.DeepestZoom), int.MaxValue);
        }

        /// <summary>
        /// Probes every station of <paramref name="plan"/>: <paramref name="probe"/>(zoom,
        /// budget) returns the counts and statuses of a <see cref="ProbeWidth"/> ×
        /// <see cref="ProbeHeight"/> frame of the movie's field at that zoom. Without a user
        /// limit each station is patient (<see cref="ProbeStation"/>) up to
        /// <paramref name="cap"/> (null: <see cref="DefaultCap"/>); with one, each is probed
        /// once at MovieMaxIter's budget (for a host's color fit).
        /// </summary>
        public static SurveyStation[] Survey(
            ZoomPlan plan, Func<double, int, (int[] Counts, byte[] Status)> probe,
            int? userLimit = null, int spacingOctaves = 64, int? cap = null)
        {
            if (plan == null)
                throw new ArgumentNullException(nameof(plan));
            if (probe == null)
                throw new ArgumentNullException(nameof(probe));
            if (userLimit.HasValue)
                IterationPolicy.MovieMaxIter(plan.DeepestZoom, plan.DeepestZoom, userLimit.Value);  // validates
            int limit = cap ?? DefaultCap(plan);
            double[] zooms = Stations(plan, spacingOctaves);
            var stations = new SurveyStation[zooms.Length];
            for (int i = 0; i < zooms.Length; i++)
            {
                double zoom = zooms[i];
                (int[] Counts, byte[] Status) At(int budget) => probe(zoom, budget);
                stations[i] = userLimit.HasValue
                    ? ProbeStation(At, zoom, int.MaxValue, false,
                        IterationPolicy.MovieMaxIter(zoom, plan.DeepestZoom, userLimit.Value))
                    : ProbeStation(At, zoom, limit);
            }
            return stations;
        }

        /// <summary>The survey's knots (zoom, need): its stations that saw an escape, in order.</summary>
        public static (double Zoom, int Need)[] Knots(SurveyStation[] stations)
        {
            if (stations == null)
                throw new ArgumentNullException(nameof(stations));
            var knots = new List<(double Zoom, int Need)>();
            foreach (var station in stations)
                if (station.Need.HasValue)
                    knots.Add((station.ZoomLog10, station.Need.Value));
            return knots.ToArray();
        }

        /// <summary>
        /// A frame's budget: with <paramref name="userLimit"/>, MovieMaxIter's ramp to it
        /// (the survey is not read); without, MeasuredMaxIter from the survey's knots.
        /// </summary>
        public static int MaxIter(double zoomLog10, ZoomPlan plan, SurveyStation[] stations, int? userLimit)
        {
            if (plan == null)
                throw new ArgumentNullException(nameof(plan));
            return userLimit.HasValue
                ? IterationPolicy.MovieMaxIter(zoomLog10, plan.DeepestZoom, userLimit.Value)
                : IterationPolicy.MeasuredMaxIter(zoomLog10, Knots(stations));
        }

        /// <summary>
        /// Probes one station: from <paramref name="budget"/> (null: the depth ramp) doubling
        /// up to <paramref name="cap"/>, until no point is left unresolved
        /// (<see cref="PixelStatus.Exhausted"/>), or something escaped and the budget is at
        /// least twice the latest escape, or the cap is reached; <paramref name="patient"/>
        /// false probes once. <paramref name="probe"/> returns the station frame's counts and
        /// statuses at a budget.
        /// </summary>
        public static SurveyStation ProbeStation(
            Func<int, (int[] Counts, byte[] Status)> probe, double zoomLog10, int cap,
            bool patient = true, int? budget = null)
        {
            if (probe == null)
                throw new ArgumentNullException(nameof(probe));
            if (cap < 1)
                throw new ArgumentOutOfRangeException(nameof(cap), $"cap must be >= 1, got {cap}");
            int current = Math.Min(budget ?? IterationPolicy.AutoMaxIter(zoomLog10), cap);
            if (current < 1)
                throw new ArgumentOutOfRangeException(nameof(budget), $"budget must be >= 1, got {current}");
            while (true)
            {
                var (counts, status) = probe(current);
                if (counts == null || status == null || counts.Length != status.Length)
                    throw new InvalidOperationException("a probe returns counts and statuses of one length");
                int escaped = 0, unresolved = 0, latest = 0;
                for (int i = 0; i < counts.Length; i++)
                {
                    if (counts[i] > 0)
                    {
                        escaped++;
                        latest = Math.Max(latest, counts[i]);
                    }
                    if (status[i] == (byte)PixelStatus.Exhausted)
                        unresolved++;
                }
                bool done = unresolved == 0 || (escaped > 0 && current >= 2L * latest) || current >= cap;
                if (done || !patient)
                {
                    int? need = escaped > 0 ? IterationPolicy.NeedFromCounts(counts) : (int?)null;
                    return new SurveyStation(zoomLog10, current, need, escaped, unresolved, counts.Length);
                }
                current = (int)Math.Min(2L * current, cap);
            }
        }
    }

    /// <summary>One probed depth of a <see cref="ZoomSurvey"/>.</summary>
    public sealed class SurveyStation
    {
        /// <summary>The station's depth (log10).</summary>
        public double ZoomLog10 { get; }

        /// <summary>The budget the probe stopped at.</summary>
        public int Budget { get; }

        /// <summary>The knot: the count by which 99.9% of the escapes escaped; null when none did.</summary>
        public int? Need { get; }

        /// <summary>Points that escaped.</summary>
        public int Escaped { get; }

        /// <summary>Points still running at the last budget (status Exhausted).</summary>
        public int Unresolved { get; }

        /// <summary>Points probed.</summary>
        public int Samples { get; }

        internal SurveyStation(double zoomLog10, int budget, int? need, int escaped, int unresolved, int samples)
        {
            ZoomLog10 = zoomLog10;
            Budget = budget;
            Need = need;
            Escaped = escaped;
            Unresolved = unresolved;
            Samples = samples;
        }
    }
}
