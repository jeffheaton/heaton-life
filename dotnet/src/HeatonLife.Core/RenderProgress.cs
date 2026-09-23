using System;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// A live row counter for an in-flight render, so a host can show real progress
    /// on a long frame instead of an indeterminate spinner.
    ///
    /// This is a HOST-SIDE observation knob, in the same category as the `workers`
    /// argument that spec/fractals.md "Parallel rendering" already sanctions: it
    /// observes the work without changing it, so **output stays bit-identical
    /// whether or not a progress object is passed**, for any worker count or
    /// schedule. Like `workers`, the Python reference has no equivalent — it renders
    /// whole-array through NumPy, where there are no rows to count.
    ///
    /// The counter is written from worker threads and read from the host's main
    /// thread, so it is interlocked. Rows complete out of order under parallelism,
    /// so <see cref="Fraction"/> is a completion count, not a scanline position —
    /// do not use it to decide which rows are ready to display.
    ///
    /// A deep (T1) render first computes its reference orbit, serially, and that can
    /// be most of the frame's time; <see cref="Phase"/> says which stage is running
    /// and <see cref="OrbitCompleted"/>/<see cref="OrbitTotal"/> count the orbit's
    /// iterations (reported every 4,096). A render whose orbit comes from the cache
    /// goes straight to <see cref="RenderPhase.Pixels"/>. A Julia frame computes two
    /// orbits in turn — its center's, then the critical orbit — each its own phase, so
    /// the orbit counters restart once. Every render resets the object first, so one
    /// object can be reused frame after frame.
    /// </summary>
    public sealed class RenderProgress
    {
        private int _completed;
        private int _total;
        private int _phase;
        private int _orbitCompleted;
        private int _orbitTotal;

        /// <summary>The stage the render is in.</summary>
        public RenderPhase Phase => (RenderPhase)Volatile.Read(ref _phase);

        /// <summary>Reference-orbit iterations run so far in the current orbit phase.</summary>
        public int OrbitCompleted => Volatile.Read(ref _orbitCompleted);

        /// <summary>
        /// Iterations the current orbit phase will run at most; the orbit stops early if
        /// the reference escapes. 0 before an orbit phase.
        /// </summary>
        public int OrbitTotal => Volatile.Read(ref _orbitTotal);

        /// <summary>OrbitCompleted / OrbitTotal, clamped to [0, 1]; 0 before an orbit phase.</summary>
        public double OrbitFraction
        {
            get
            {
                int total = OrbitTotal;
                return total <= 0 ? 0.0 : Math.Min(1.0, (double)OrbitCompleted / total);
            }
        }

        /// <summary>Rows in the frame being rendered; 0 before one starts.</summary>
        public int Total => Volatile.Read(ref _total);

        /// <summary>Rows finished so far.</summary>
        public int Completed => Volatile.Read(ref _completed);

        /// <summary>Completed / Total, clamped to [0, 1]; 0 before a render starts.</summary>
        public double Fraction
        {
            get
            {
                int total = Total;
                return total <= 0 ? 0.0 : Math.Min(1.0, (double)Completed / total);
            }
        }

        /// <summary>True once a render has begun reporting into this object (either phase).</summary>
        public bool Started => Phase != RenderPhase.NotStarted;

        /// <summary>A new render: back to <see cref="RenderPhase.NotStarted"/> with every counter at 0.</summary>
        internal void Reset()
        {
            Volatile.Write(ref _phase, (int)RenderPhase.NotStarted);
            Volatile.Write(ref _completed, 0);
            Volatile.Write(ref _total, 0);
            Volatile.Write(ref _orbitCompleted, 0);
            Volatile.Write(ref _orbitTotal, 0);
        }

        internal void Begin(int total)
        {
            Volatile.Write(ref _completed, 0);
            Volatile.Write(ref _total, total);
            Volatile.Write(ref _phase, (int)RenderPhase.Pixels);
        }

        internal void Step() => Interlocked.Increment(ref _completed);

        internal void BeginOrbit(int total)
        {
            Volatile.Write(ref _orbitCompleted, 0);
            Volatile.Write(ref _orbitTotal, total);
            Volatile.Write(ref _phase, (int)RenderPhase.ReferenceOrbit);
        }

        internal void OrbitAt(int completed) => Volatile.Write(ref _orbitCompleted, completed);
    }

    /// <summary>The stage of a render reporting into a <see cref="RenderProgress"/>.</summary>
    public enum RenderPhase
    {
        /// <summary>Nothing has reported yet.</summary>
        NotStarted = 0,

        /// <summary>Computing a T1 reference orbit (serial, arbitrary precision).</summary>
        ReferenceOrbit = 1,

        /// <summary>Iterating pixels; <see cref="RenderProgress.Fraction"/> counts rows.</summary>
        Pixels = 2,
    }
}
