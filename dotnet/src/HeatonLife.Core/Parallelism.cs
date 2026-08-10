using System;
using System.Threading.Tasks;

namespace HeatonLife
{
    /// <summary>
    /// The one parallel primitive the library uses (spec/fractals.md "Parallel
    /// rendering", spec/evolve.md "Parallel evaluation"): an indexed loop whose
    /// iterations are independent and write disjoint slots, so the output is
    /// bit-identical for any worker count or schedule. workers &lt;= 1 runs the
    /// plain serial loop.
    /// </summary>
    public static class Parallelism
    {
        public static void For(int count, int workers, Action<int> body)
        {
            if (workers <= 1 || count <= 1)
            {
                for (int i = 0; i < count; i++)
                    body(i);
                return;
            }
            var options = new ParallelOptions
            {
                MaxDegreeOfParallelism = Math.Min(workers, count),
            };
            Parallel.For(0, count, options, body);
        }
    }
}
