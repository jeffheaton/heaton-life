using System;

namespace HeatonLife
{
    /// <summary>
    /// A zoom movie's frames (spec/zoom.md, "Plan"): frames 0..Frames−1 at Fps, from
    /// StartZoom to EndZoom (log10 magnification, either way), paced by a
    /// <see cref="ZoomSchedule"/>. Frame f is at t = f / fps seconds of a run of
    /// (frames − 1) / fps, so the first frame is StartZoom and the last EndZoom. Bit-exact
    /// with the Python reference (heaton_life.fractal.movie.ZoomPlan).
    /// </summary>
    public sealed class ZoomPlan
    {
        /// <summary>The bound on |zoom|: the pinned 10^x's domain (spec/pow10.md).</summary>
        public const double MaxZoom = 10000.0;

        /// <summary>The first frame's zoom.</summary>
        public double StartZoom { get; }

        /// <summary>The last frame's zoom.</summary>
        public double EndZoom { get; }

        /// <summary>How many frames, at least 2.</summary>
        public int Frames { get; }

        /// <summary>Frames per second, at least 1.</summary>
        public int Fps { get; }

        /// <summary>The pacing.</summary>
        public ZoomSchedule Schedule { get; }

        /// <summary>The schedule fitted to <see cref="Duration"/>.</summary>
        public ResolvedZoomSchedule Resolved { get; }

        /// <summary>A plan; <paramref name="schedule"/> null is <see cref="ZoomSchedule.Uniform"/>.</summary>
        public ZoomPlan(double startZoom, double endZoom, int frames, int fps = 30, ZoomSchedule? schedule = null)
        {
            CheckZoom(startZoom, nameof(startZoom));
            CheckZoom(endZoom, nameof(endZoom));
            if (frames < 2)
                throw new ArgumentOutOfRangeException(nameof(frames), $"frames must be >= 2, got {frames}");
            if (fps < 1)
                throw new ArgumentOutOfRangeException(nameof(fps), $"fps must be >= 1, got {fps}");
            StartZoom = startZoom + 0.0;                          // a negative zero becomes +0
            EndZoom = endZoom + 0.0;
            Frames = frames;
            Fps = fps;
            Schedule = schedule ?? ZoomSchedule.Uniform;
            Resolved = Schedule.Resolved(Duration);
        }

        /// <summary>(frames − 1) / fps seconds: the last frame's time.</summary>
        public double Duration => (double)(Frames - 1) / Fps;

        /// <summary>min(start, end).</summary>
        public double ShallowestZoom => EndZoom < StartZoom ? EndZoom : StartZoom;

        /// <summary>max(start, end).</summary>
        public double DeepestZoom => EndZoom > StartZoom ? EndZoom : StartZoom;

        /// <summary>f / fps seconds.</summary>
        public double Time(int frame)
        {
            CheckFrame(frame);
            return (double)frame / Fps;
        }

        /// <summary>The schedule's progress at the frame's time.</summary>
        public double Progress(int frame) => Resolved.Progress(Time(frame));

        /// <summary>
        /// The frame's zoom: start if p == 0, end if p == 1, else start + (end − start) · p
        /// held to the plan's range.
        /// </summary>
        public double Zoom(int frame)
        {
            double p = Progress(frame);
            if (p == 0.0)
                return StartZoom;
            if (p == 1.0)
                return EndZoom;
            double lerp = StartZoom + (EndZoom - StartZoom) * p;
            if (lerp < ShallowestZoom)
                return ShallowestZoom;
            return lerp > DeepestZoom ? DeepestZoom : lerp;
        }

        /// <summary>Every frame's zoom, in order.</summary>
        public double[] Zooms()
        {
            var zooms = new double[Frames];
            for (int f = 0; f < Frames; f++)
                zooms[f] = Zoom(f);
            return zooms;
        }

        /// <summary>
        /// Decades per frame at the frame (negative zooming out):
        /// (((end − start) / eff) / fps) · speed_fraction(t). For motion blur and a UI.
        /// </summary>
        public double Speed(int frame)
        {
            double eff = Resolved.EffectiveSeconds;
            if (!(eff > 0.0))
                return 0.0;
            double rate = ((EndZoom - StartZoom) / eff) / Fps;
            return rate * Resolved.SpeedFraction(Time(frame));
        }

        private void CheckFrame(int frame)
        {
            if (frame < 0 || frame >= Frames)
                throw new ArgumentOutOfRangeException(nameof(frame), $"frame must lie in [0, {Frames}), got {frame}");
        }

        private static void CheckZoom(double zoom, string name)
        {
            if (double.IsNaN(zoom) || double.IsInfinity(zoom) || Math.Abs(zoom) > MaxZoom)
                throw new ArgumentOutOfRangeException(name, $"{name} must be finite with |zoom| <= 10000, got {zoom}");
        }
    }
}
