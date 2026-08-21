using System;

namespace HeatonLife
{
    /// <summary>
    /// Lenia kernel construction (spec/lenia.md): the standard exponential ring core,
    /// built directly in wrapped (torus) coordinates with the center at [0, 0],
    /// normalized to sum 1.
    /// </summary>
    public static class RingKernel
    {
        /// <summary>Steepness of the exponential core.</summary>
        public const double Alpha = 4.0;

        /// <summary>
        /// Normalized single-ring kernel on a torus, row-major, origin at [0, 0].
        /// Core: K(r) = exp(Alpha - Alpha / (4 r (1 - r))) for 0 &lt; r &lt; 1, else 0,
        /// where r = distance / radius.
        /// </summary>
        public static double[] Build(int width, int height, int radius)
        {
            if (radius < 1 || 2 * radius + 1 > Math.Min(width, height))
                throw new ArgumentException($"radius {radius} does not fit a {width}x{height} torus");
            var kernel = new double[width * height];
            double total = 0.0;
            for (int y = 0; y < height; y++)
            {
                double dy = Math.Min(y, height - y);
                for (int x = 0; x < width; x++)
                {
                    double dx = Math.Min(x, width - x);
                    double r = Math.Sqrt(dx * dx + dy * dy) / radius;
                    double value = r > 0.0 && r < 1.0
                        ? Math.Exp(Alpha - Alpha / (4.0 * r * (1.0 - r)))
                        : 0.0;
                    kernel[y * width + x] = value;
                    total += value;
                }
            }
            if (total <= 0.0)
                throw new ArgumentException($"degenerate kernel for radius {radius}");
            for (int i = 0; i < kernel.Length; i++)
                kernel[i] /= total;
            return kernel;
        }
    }

    /// <summary>
    /// Common Lenia machinery (spec/lenia.md): state, seeding, and the
    /// kernel/potential/growth pipeline. State is flat row-major float64 in [0, 1].
    /// Subclasses implement one update rule each. ε tier (1e-6).
    /// </summary>
    public abstract class LeniaBase : IFloatFrameSource
    {
        private readonly Fft2Plan _plan;
        private readonly double[] _kernelRe;
        private readonly double[] _kernelIm;
        private readonly double[] _potential; // convolution result buffer
        private readonly double[] _potentialIm; // convolution scratch

        private protected double[] _state;

        public int Width { get; }
        public int Height { get; }
        public int Radius { get; }
        public double Mu { get; }
        public double Sigma { get; }
        public double Dt { get; }
        public int Generation { get; private set; }

        public ReadOnlySpan<double> State => _state;

        private protected LeniaBase(int width, int height, int radius, double mu, double sigma, double dt)
        {
            Width = width;
            Height = height;
            Radius = radius;
            Mu = mu;
            Sigma = sigma;
            Dt = dt;
            _plan = new Fft2Plan(width, height);
            (_kernelRe, _kernelIm) = FftConv.KernelFft(_plan, RingKernel.Build(width, height, radius));
            _state = new double[width * height];
            _potential = new double[width * height];
            _potentialIm = new double[width * height];
        }

        /// <summary>
        /// Uniform random fill: one PCG32 draw per cell in row-major order,
        /// value = draw / 2^32 * density.
        /// </summary>
        public void SeedSoup(double density, uint seed)
        {
            var rng = new Pcg32(seed);
            for (int i = 0; i < _state.Length; i++)
                _state[i] = rng.NextU32() / 4294967296.0 * density;
            Generation = 0;
            Remember(seed, s => SeedSoup(density, s));
        }

        /// <summary>
        /// Seeded gaussian bumps with wrapped distances; 3 draws per blob in order
        /// cx (% Width), cy (% Height), amplitude (0.5 + 0.5 * draw / 2^32); the
        /// accumulated field is clipped to [0, 1].
        /// </summary>
        public void SeedBlobs(int blobs, uint seed)
        {
            var rng = new Pcg32(seed);
            var cx = new int[blobs];
            var cy = new int[blobs];
            var amp = new double[blobs];
            for (int b = 0; b < blobs; b++)
            {
                cx[b] = (int)(rng.NextU32() % (uint)Width);
                cy[b] = (int)(rng.NextU32() % (uint)Height);
                amp[b] = 0.5 + 0.5 * (rng.NextU32() / 4294967296.0);
            }
            Array.Clear(_state, 0, _state.Length);
            double rb = Math.Max(Radius / 2.0, 1.0);
            for (int b = 0; b < blobs; b++) // blob-major, matching the reference's accumulation order
            {
                for (int y = 0; y < Height; y++)
                {
                    double ady = Math.Abs((double)y - cy[b]);
                    double dy = Math.Min(ady, Height - ady);
                    for (int x = 0; x < Width; x++)
                    {
                        double adx = Math.Abs((double)x - cx[b]);
                        double dx = Math.Min(adx, Width - adx);
                        _state[y * Width + x] += amp[b] * Math.Exp(-(dx * dx + dy * dy) / (2.0 * rb * rb));
                    }
                }
            }
            for (int i = 0; i < _state.Length; i++)
                _state[i] = Math.Clamp(_state[i], 0.0, 1.0);
            Generation = 0;
            Remember(seed, s => SeedBlobs(blobs, s));
        }

        // --- reset ---------------------------------------------------------------
        // How this world was last seeded, so Reset can replay it. The Python
        // reference keeps init/density/seed on its params object and re-dispatches
        // in reset(); a captured delegate is the same idea without a params type.
        private Action<uint> _replayInit = _ => { };
        private uint _seed;

        private void Remember(uint seed, Action<uint> replay)
        {
            _seed = seed;
            _replayInit = replay;
        }

        /// <inheritdoc />
        public void Reset(uint? seed = null)
        {
            if (seed.HasValue)
                _seed = seed.Value;
            _replayInit(_seed);
        }

        /// <summary>Load an explicit (Height, Width) row-major state.</summary>
        public void SetState(ReadOnlySpan<double> state)
        {
            if (state.Length != _state.Length)
                throw new ArgumentException($"expected {_state.Length} values, got {state.Length}");
            state.CopyTo(_state);
            Generation = 0;
            var snapshot = _state.Clone() as double[];
            Remember(_seed, _ =>
            {
                Array.Copy(snapshot!, _state, _state.Length);
                Generation = 0;
            });
        }

        /// <summary>Restore a saved state at a given generation (catalog loads).</summary>
        public void SetState(ReadOnlySpan<double> state, int generation)
        {
            SetState(state);
            Generation = generation;
        }

        /// <summary>Paint one cell in place (caller keeps values in [0, 1]); does not reset the generation.</summary>
        public void SetCell(int x, int y, double value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            _state[y * Width + x] = value;
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family blank, 0.0 (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    SetCell(x, y, 0.0);
        }

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>Frame per spec/render.md: the state itself (already floats in [0, 1]).</summary>
        public void WriteFrame(double[] frame)
        {
            if (frame.Length != _state.Length)
                throw new ArgumentException($"expected {_state.Length} values, got {frame.Length}");
            Array.Copy(_state, frame, _state.Length);
        }

        /// <summary>Allocating convenience for <see cref="WriteFrame"/>.</summary>
        public double[] Frame()
        {
            var frame = new double[_state.Length];
            WriteFrame(frame);
            return frame;
        }

        private protected abstract void StepOnce();

        /// <summary>Potential U = K ⊛ A; returns an internal buffer valid until the next call.</summary>
        private protected double[] Potential()
        {
            FftConv.Convolve(_plan, _state, _kernelRe, _kernelIm, _potential, _potentialIm);
            return _potential;
        }

        /// <summary>Exponential growth in [-1, 1]: 2*exp(-(u-mu)^2 / (2 sigma^2)) - 1.</summary>
        private protected double Growth(double u)
        {
            double diff = u - Mu;
            return 2.0 * Math.Exp(-(diff * diff) / (2.0 * Sigma * Sigma)) - 1.0;
        }
    }
}
