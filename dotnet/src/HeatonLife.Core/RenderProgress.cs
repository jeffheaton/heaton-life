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
    /// </summary>
    public sealed class RenderProgress
    {
        private int _completed;
        private int _total;

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

        /// <summary>True once a render has begun reporting into this object.</summary>
        public bool Started => Total > 0;

        internal void Begin(int total)
        {
            Volatile.Write(ref _completed, 0);
            Volatile.Write(ref _total, total);
        }

        internal void Step() => Interlocked.Increment(ref _completed);
    }
}
