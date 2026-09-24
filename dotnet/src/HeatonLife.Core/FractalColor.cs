using System;

namespace HeatonLife
{
    /// <summary>
    /// The 1st and 99th percentiles of a frame's escaped smooth values — the bounds the
    /// per-frame stretch maps onto [0, 1] (spec/fractal-color.md "Stretch"). Kept and
    /// reused across frames of one view, a frozen stretch.
    /// </summary>
    public readonly struct Stretch
    {
        public Stretch(double lo, double hi)
        {
            Lo = lo;
            Hi = hi;
        }

        public double Lo { get; }
        public double Hi { get; }
    }

    /// <summary>
    /// Depth-phase parameters (spec/fractal-color.md "Depth phase"):
    /// t = (PhaseOffset + CyclesPerOctave * u) + CyclesPerIteration * (mu - Anchor),
    /// u = zoom * log2(10). CyclesPerOctave 0 (the default) gives a point the same color
    /// at every zoom; Heaton Fractal's video flow uses 0.25.
    /// </summary>
    public sealed class PhaseParams
    {
        public PhaseParams(
            double cyclesPerIteration = 0.01, double cyclesPerOctave = 0.0, double phaseOffset = 0.0, double anchor = 0.0)
        {
            if (!IsFinite(cyclesPerIteration) || !IsFinite(cyclesPerOctave) || !IsFinite(phaseOffset) || !IsFinite(anchor))
                throw new ArgumentException("phase parameters must be finite");
            CyclesPerIteration = cyclesPerIteration;
            CyclesPerOctave = cyclesPerOctave;
            PhaseOffset = phaseOffset;
            Anchor = anchor;
        }

        public double CyclesPerIteration { get; }
        public double CyclesPerOctave { get; }
        public double PhaseOffset { get; }
        public double Anchor { get; }

        private static bool IsFinite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
    }

    /// <summary>A fitted cycles-per-iteration and the anchor (an escape count) it pivots on.</summary>
    public readonly struct Frequency
    {
        public Frequency(double cyclesPerIteration, double anchor)
        {
            CyclesPerIteration = cyclesPerIteration;
            Anchor = anchor;
        }

        public double CyclesPerIteration { get; }
        public double Anchor { get; }
    }

    /// <summary>
    /// Distance-shading parameters (spec/fractal-color.md "Distance shading"; Heaton
    /// Fractal's defaults): the stroke width in pixels at 1080p, how dark the boundary
    /// gets, and how much dense regions are released.
    /// </summary>
    public sealed class ShadeParams
    {
        public ShadeParams(double width = 1.6, double strength = 0.85, double denseRelease = 1.0)
        {
            if (!(width > 0.0) || double.IsInfinity(width))
                throw new ArgumentException("width must be finite and positive", nameof(width));
            if (!(strength >= 0.0 && strength <= 1.0))
                throw new ArgumentException("strength must be in [0, 1]", nameof(strength));
            if (!(denseRelease >= 0.0 && denseRelease <= 1.0))
                throw new ArgumentException("denseRelease must be in [0, 1]", nameof(denseRelease));
            Width = width;
            Strength = strength;
            DenseRelease = denseRelease;
        }

        public double Width { get; }
        public double Strength { get; }
        public double DenseRelease { get; }
    }

    /// <summary>
    /// Fractal color (spec/fractal-color.md): how an escape-time frame's smooth values and
    /// distance estimates become colors that hold still while a view moves — stretch,
    /// depth phase, frequency and distance shading. Presentation only. Every function is
    /// bit-exact given its inputs (plain IEEE operations in the spec's order, no libm
    /// beyond Math.Sqrt), byte-identical with the Python reference's
    /// heaton_life.fractal.coloring.
    /// </summary>
    public static class FractalColor
    {
        /// <summary>The double nearest log2(10), 0x400A934F0979A371.</summary>
        public const double Log2Of10 = 3.321928094887362;

        /// <summary>
        /// sqrt(W^2 + H^2) / sqrt(1920^2 + 1080^2): pixel-sized parameters are given at 1080p
        /// and scaled to the frame. Integer squares, correctly rounded square roots.
        /// </summary>
        public static double ColorScale(int width, int height)
        {
            if (width < 1 || height < 1)
                throw new ArgumentException("frame dimensions must be positive");
            long squares = (long)width * width + (long)height * height;
            return Math.Sqrt(squares) / Math.Sqrt(1920L * 1920L + 1080L * 1080L);
        }

        /// <summary>(t*t)*(3 - 2t) with t = clip((x - e0) / (e1 - e0), 0, 1).</summary>
        public static double Smoothstep(double e0, double e1, double x)
        {
            double t = (x - e0) / (e1 - e0);
            t = t < 0.0 ? 0.0 : (t > 1.0 ? 1.0 : t);
            return (t * t) * (3.0 - 2.0 * t);
        }

        /// <summary>
        /// The frame's own stretch: NumPy's linear percentiles 1 and 99 of the escaped
        /// (mu &gt; 0) values; false when nothing escaped. <paramref name="scratch"/> (at
        /// least as long as <paramref name="mu"/>) receives the sorted escaped values.
        /// </summary>
        public static bool TryMeasureStretch(ReadOnlySpan<double> mu, double[] scratch, out Stretch stretch)
        {
            if (scratch == null || scratch.Length < mu.Length)
                throw new ArgumentException($"expected a scratch buffer of at least {mu.Length} values", nameof(scratch));
            int escaped = 0;
            foreach (double value in mu)
                if (value > 0.0)
                    scratch[escaped++] = value;
            if (escaped == 0)
            {
                stretch = default;
                return false;
            }
            Array.Sort(scratch, 0, escaped);
            stretch = new Stretch(
                FractalEngine.Percentile(scratch, escaped, 1.0), FractalEngine.Percentile(scratch, escaped, 99.0));
            return true;
        }

        /// <summary>
        /// Escaped pixels: 0.6 if hi &lt;= lo (a featureless frame), else
        /// clip((mu - lo) / (hi - lo), 0.02, 1); the rest 0; then sqrt.
        /// <paramref name="render"/> may be <paramref name="mu"/>'s own memory.
        /// </summary>
        public static void ApplyStretch(ReadOnlySpan<double> mu, Stretch stretch, Span<double> render)
        {
            if (render.Length != mu.Length)
                throw new ArgumentException($"expected a render buffer of {mu.Length} values", nameof(render));
            double lo = stretch.Lo, hi = stretch.Hi;
            for (int i = 0; i < mu.Length; i++)
            {
                double value = 0.0;
                if (mu[i] > 0.0)
                {
                    value = hi <= lo
                        ? 0.6 // featureless frame: one mid tone
                        : Math.Clamp((mu[i] - lo) / (hi - lo), 0.02, 1.0);
                }
                render[i] = Math.Sqrt(value);
            }
        }

        /// <summary>
        /// The unwrapped palette phase t, in cycles, for every escaped (mu &gt; 0) pixel; NaN
        /// elsewhere (spec/fractal-color.md "Depth phase"). The phase lookup wraps it
        /// (<see cref="Colormaps.ApplyPhase"/>).
        /// </summary>
        public static void DepthPhase(ReadOnlySpan<double> mu, double zoomLog10, PhaseParams parameters, Span<double> t)
        {
            if (parameters == null)
                throw new ArgumentNullException(nameof(parameters));
            if (double.IsNaN(zoomLog10) || double.IsInfinity(zoomLog10))
                throw new ArgumentException("zoom must be finite", nameof(zoomLog10));
            if (t.Length != mu.Length)
                throw new ArgumentException($"expected {mu.Length} phase values, got {t.Length}", nameof(t));
            double baseline = parameters.PhaseOffset + parameters.CyclesPerOctave * (zoomLog10 * Log2Of10);
            double c = parameters.CyclesPerIteration, anchor = parameters.Anchor;
            for (int i = 0; i < mu.Length; i++)
                t[i] = mu[i] > 0.0 ? baseline + c * (mu[i] - anchor) : double.NaN;
        }

        /// <summary>
        /// Fit the phase frequency to one frame (spec/fractal-color.md "Frequency"): the
        /// upper median of neighbor steps |mu - mu_left| and |mu - mu_up| where both
        /// escaped with a finite mu, c = min(max, (target / ColorScale) / max(step, 1)), anchor = the upper
        /// median of the positive counts; false with fewer than 64 steps.
        /// <paramref name="scratch"/> must hold at least twice as many values as the frame.
        /// </summary>
        public static bool TryMeasureFrequency(
            ReadOnlySpan<int> counts, ReadOnlySpan<double> mu, int width, double targetCyclesPerStep,
            double maxCyclesPerIteration, double[] scratch, out Frequency frequency)
        {
            if (!(targetCyclesPerStep > 0.0) || double.IsInfinity(targetCyclesPerStep))
                throw new ArgumentException("targetCyclesPerStep must be finite and positive", nameof(targetCyclesPerStep));
            if (!(maxCyclesPerIteration > 0.0) || double.IsInfinity(maxCyclesPerIteration))
                throw new ArgumentException("maxCyclesPerIteration must be finite and positive", nameof(maxCyclesPerIteration));
            if (width < 1 || mu.Length % width != 0 || counts.Length != mu.Length || mu.Length == 0)
                throw new ArgumentException("counts and mu must be one (height, width) frame each");
            if (scratch == null || scratch.Length < 2 * mu.Length)
                throw new ArgumentException($"expected a scratch buffer of at least {2 * mu.Length} values", nameof(scratch));
            int height = mu.Length / width;
            int steps = 0;
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    int i = y * width + x;
                    if (!FiniteEscaped(mu[i]))
                        continue;
                    if (x > 0 && FiniteEscaped(mu[i - 1]))
                        scratch[steps++] = Math.Abs(mu[i] - mu[i - 1]);
                    if (y > 0 && FiniteEscaped(mu[i - width]))
                        scratch[steps++] = Math.Abs(mu[i] - mu[i - width]);
                }
            }
            int positive = 0;
            foreach (int count in counts)
                if (count > 0)
                    positive++;
            if (steps < 64 || positive == 0)
            {
                frequency = default;
                return false;
            }
            Array.Sort(scratch, 0, steps);
            double step = scratch[steps / 2];
            int k = 0;
            foreach (int count in counts)
                if (count > 0)
                    scratch[k++] = count;
            Array.Sort(scratch, 0, positive);
            double anchor = scratch[positive / 2];
            double scaled = (targetCyclesPerStep / ColorScale(width, height)) / Math.Max(step, 1.0);
            frequency = new Frequency(Math.Min(maxCyclesPerIteration, scaled), anchor);
            return true;
        }

        /// <summary>An escaped pixel with a finite mu: an infinite pair would step by NaN.</summary>
        private static bool FiniteEscaped(double mu) => mu > 0.0 && mu < double.PositiveInfinity;

        /// <summary>
        /// <paramref name="parameters"/> with the new frequency and anchor, and the phase offset
        /// moved so t at mu = <paramref name="pivot"/> is unchanged (up to rounding):
        /// phi' = (phi + c (pivot - A)) - c' (pivot - A').
        /// </summary>
        public static PhaseParams Retune(PhaseParams parameters, Frequency frequency, double pivot)
        {
            if (parameters == null)
                throw new ArgumentNullException(nameof(parameters));
            double offset = (parameters.PhaseOffset + parameters.CyclesPerIteration * (pivot - parameters.Anchor))
                - frequency.CyclesPerIteration * (pivot - frequency.Anchor);
            return new PhaseParams(frequency.CyclesPerIteration, parameters.CyclesPerOctave, offset, frequency.Anchor);
        }

        /// <summary>
        /// Darken each escaped pixel of an RGB frame, in place, by its distance estimate
        /// (spec/fractal-color.md "Distance shading"): a factor f in light, applied to the
        /// encoded bytes as sqrt(f). Pixels whose distance is NaN (did not escape) are left
        /// as they are. <paramref name="scratch"/> must hold at least twice as many values
        /// as the frame.
        /// </summary>
        public static void ShadeRgb(
            Span<byte> rgb, ReadOnlySpan<double> distance, int width, ShadeParams parameters, double[] scratch)
            => Shade(rgb, 3, distance, width, parameters, scratch);

        /// <summary><see cref="ShadeRgb"/> for an RGBA32 frame; alpha is untouched.</summary>
        public static void ShadeRgba(
            Span<byte> rgba, ReadOnlySpan<double> distance, int width, ShadeParams parameters, double[] scratch)
            => Shade(rgba, 4, distance, width, parameters, scratch);

        private static void Shade(
            Span<byte> pixels, int stride, ReadOnlySpan<double> distance, int width, ShadeParams parameters, double[] scratch)
        {
            if (parameters == null)
                throw new ArgumentNullException(nameof(parameters));
            int n = distance.Length;
            if (width < 1 || n == 0 || n % width != 0)
                throw new ArgumentException("distance must be one (height, width) frame");
            if (pixels.Length != n * stride)
                throw new ArgumentException($"expected {n * stride} bytes, got {pixels.Length}");
            if (scratch == null || scratch.Length < 2 * n)
                throw new ArgumentException($"expected a scratch buffer of at least {2 * n} values", nameof(scratch));
            int height = n / width;
            double w = Math.Max(parameters.Width * ColorScale(width, height), 1e-4);
            if (double.IsInfinity(w))
                throw new ArgumentException("width * ColorScale(width, height) must be finite", nameof(parameters));
            int r = (int)Math.Min(Math.Ceiling(w) + 1.0, Math.Max(width, height));
            // The window maximum, rows then columns: scratch[0, n) rows, scratch[n, 2n) the result.
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    double best = 0.0;
                    for (int xx = Math.Max(0, x - r); xx <= Math.Min(width - 1, x + r); xx++)
                    {
                        double v = distance[y * width + xx];
                        if (v > best)
                            best = v;                   // NaN counts as 0, +inf as +inf
                    }
                    scratch[y * width + x] = best;
                }
            }
            for (int y = 0; y < height; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    double best = 0.0;
                    for (int yy = Math.Max(0, y - r); yy <= Math.Min(height - 1, y + r); yy++)
                    {
                        double v = scratch[yy * width + x];
                        if (v > best)
                            best = v;
                    }
                    scratch[n + y * width + x] = best;
                }
            }
            for (int i = 0; i < n; i++)
            {
                double de = distance[i];
                if (double.IsNaN(de))
                    continue;
                double shade = Smoothstep(0.0, w, de);
                double open = Smoothstep(0.25 * w, w, scratch[n + i]);
                double s = parameters.Strength * (1.0 + (open - 1.0) * parameters.DenseRelease);
                double g = Math.Sqrt(1.0 + (shade - 1.0) * s);
                for (int c = 0; c < 3; c++)
                {
                    double v = Math.Round(pixels[i * stride + c] * g);   // half-even
                    pixels[i * stride + c] = (byte)(v < 0.0 ? 0.0 : (v > 255.0 ? 255.0 : v));
                }
            }
        }
    }
}
