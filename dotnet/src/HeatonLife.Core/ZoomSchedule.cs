using System;

namespace HeatonLife
{
    /// <summary>
    /// A zoom movie's speed profile (spec/zoom.md, "Schedule"): seconds of hold, smoothstep
    /// ease in, ease out and hold, with a full-speed cruise filling the rest (Heaton
    /// Fractal's defaults 3, 5, 5, 5). <see cref="Uniform"/> is all zero, a constant speed
    /// from the first frame to the last. Fit it to a duration with <see cref="Resolved"/>.
    /// </summary>
    public sealed class ZoomSchedule
    {
        /// <summary>No holds or ramps: the descent runs at one speed throughout.</summary>
        public static readonly ZoomSchedule Uniform = new ZoomSchedule(0.0, 0.0, 0.0, 0.0);

        /// <summary>Seconds held at the start depth.</summary>
        public double HoldStart { get; }

        /// <summary>Seconds of smoothstep speed-up.</summary>
        public double EaseIn { get; }

        /// <summary>Seconds of smoothstep slow-down.</summary>
        public double EaseOut { get; }

        /// <summary>Seconds held at the end depth.</summary>
        public double HoldEnd { get; }

        /// <summary>A schedule; a segment that is not finite or not positive counts as 0.</summary>
        public ZoomSchedule(double holdStart = 3.0, double easeIn = 5.0, double easeOut = 5.0, double holdEnd = 5.0)
        {
            HoldStart = holdStart;
            EaseIn = easeIn;
            EaseOut = easeOut;
            HoldEnd = holdEnd;
        }

        /// <summary>
        /// Fitted to <paramref name="duration"/> seconds: a segment that is not finite or not
        /// positive is 0, and segments longer together than 90% of the duration are scaled
        /// down together (a tenth of the run keeps cruising, up to rounding).
        /// </summary>
        public ResolvedZoomSchedule Resolved(double duration)
        {
            double span = IsPositiveFinite(duration) ? duration : 0.0;
            double h0 = Clean(HoldStart), e0 = Clean(EaseIn), e1 = Clean(EaseOut), h1 = Clean(HoldEnd);
            double budget = span * 0.9;
            double shaped = ((h0 + e0) + e1) + h1;
            if (shaped > budget && shaped > 0.0)
            {
                double scale = budget / shaped;
                h0 *= scale;
                e0 *= scale;
                e1 *= scale;
                h1 *= scale;
            }
            return new ResolvedZoomSchedule(span, h0, e0, e1, h1);
        }

        private static bool IsPositiveFinite(double value) =>
            !double.IsNaN(value) && !double.IsInfinity(value) && value > 0.0;

        private static double Clean(double value) => IsPositiveFinite(value) ? value : 0.0;
    }

    /// <summary>
    /// A <see cref="ZoomSchedule"/> fitted to a duration (spec/zoom.md, "Schedule"): every
    /// query is a straight float64 evaluation in the spec's order, bit-exact with the Python
    /// reference (heaton_life.fractal.movie.ResolvedSchedule).
    /// </summary>
    public sealed class ResolvedZoomSchedule
    {
        /// <summary>The run's length in seconds (0 when the duration was not positive).</summary>
        public double Duration { get; }

        /// <summary>Seconds held at the start depth.</summary>
        public double HoldStart { get; }

        /// <summary>Seconds of smoothstep speed-up.</summary>
        public double EaseIn { get; }

        /// <summary>Seconds of smoothstep slow-down.</summary>
        public double EaseOut { get; }

        /// <summary>Seconds held at the end depth.</summary>
        public double HoldEnd { get; }

        /// <summary>Seconds at full speed between the ramps.</summary>
        public double Cruise { get; }

        /// <summary>The cruise plus half of each ramp: smoothstep integrates to one half.</summary>
        public double EffectiveSeconds { get; }

        internal ResolvedZoomSchedule(double duration, double holdStart, double easeIn, double easeOut, double holdEnd)
        {
            Duration = duration;
            HoldStart = holdStart;
            EaseIn = easeIn;
            EaseOut = easeOut;
            HoldEnd = holdEnd;
            Cruise = Math.Max(0.0, (((duration - holdStart) - easeIn) - easeOut) - holdEnd);
            EffectiveSeconds = Cruise + 0.5 * (easeIn + easeOut);
        }

        /// <summary>Peak speed as a multiple of the average (1 when nothing descends).</summary>
        public double PeakOverAverage =>
            EffectiveSeconds > 0.0 && Duration > 0.0 ? Duration / EffectiveSeconds : 1.0;

        /// <summary>
        /// The fraction of the descent done by <paramref name="t"/> seconds, in [0, 1]: 0
        /// through the first hold, e0 (x³ − x⁴/2) over the ease in, linear through the
        /// cruise, e1 (x − x³ + x⁴/2) over the ease out, and exactly 1 from the end of the
        /// ease out on (at and past the duration too): Heaton Fractal's closed form with its
        /// end pinned.
        /// </summary>
        public double Progress(double t)
        {
            if (!(Duration > 0.0))
                return 0.0;
            double eff = EffectiveSeconds;
            if (!(eff > 0.0))
                return t >= Duration ? 1.0 : 0.0;
            if (t >= Duration)
                return 1.0;
            double time = Max0(t);
            if (time <= HoldStart)
                return 0.0;
            double covered = 0.0;
            double remaining = time - HoldStart;
            if (EaseIn > 0.0)
            {
                if (remaining < EaseIn)
                {
                    double x = remaining / EaseIn;
                    return Math.Min(1.0, (EaseIn * (((x * x) * x) - ((((0.5 * x) * x) * x) * x))) / eff);
                }
                covered += 0.5 * EaseIn;
                remaining -= EaseIn;
            }
            if (Cruise > 0.0)
            {
                if (remaining < Cruise)
                    return Math.Min(1.0, (covered + remaining) / eff);
                covered += Cruise;
                remaining -= Cruise;
            }
            if (EaseOut > 0.0 && remaining < EaseOut)
            {
                double x = remaining / EaseOut;
                return Math.Min(1.0, (covered + EaseOut * ((x - ((x * x) * x)) + ((((0.5 * x) * x) * x) * x))) / eff);
            }
            return 1.0;
        }

        /// <summary>
        /// The speed at <paramref name="t"/> seconds as a fraction of the peak: smoothstep
        /// up, 1, smoothstep down, 0 through the holds; at and past the duration, the value
        /// arriving there (1 when the run ends in its cruise, else 0).
        /// </summary>
        public double SpeedFraction(double t)
        {
            if (!(Duration > 0.0 && EffectiveSeconds > 0.0))
                return 0.0;
            if (t >= Duration)
                return EaseOut == 0.0 && HoldEnd == 0.0 && Cruise > 0.0 ? 1.0 : 0.0;
            double time = Max0(t);
            if (time < HoldStart)
                return 0.0;
            double remaining = time - HoldStart;
            if (EaseIn > 0.0)
            {
                if (remaining < EaseIn)
                {
                    double x = remaining / EaseIn;
                    return (x * x) * (3.0 - 2.0 * x);
                }
                remaining -= EaseIn;
            }
            if (remaining < Cruise)
                return 1.0;
            remaining -= Cruise;
            if (EaseOut > 0.0 && remaining < EaseOut)
            {
                double x = remaining / EaseOut;
                return 1.0 - (x * x) * (3.0 - 2.0 * x);
            }
            return 0.0;
        }

        // max(t, 0) as Python's max(t, 0.0) reads it: t unless 0 is greater (a NaN stays NaN).
        private static double Max0(double t) => 0.0 > t ? 0.0 : t;
    }
}
