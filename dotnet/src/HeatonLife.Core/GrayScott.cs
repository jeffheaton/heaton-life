using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>
    /// Gray-Scott reaction-diffusion (spec/grayscott.md). Two species U (substrate)
    /// and V (activator) on a torus:
    ///
    ///     dU/dt = du * lap(U) - U*V^2 + feed * (1 - U)
    ///     dV/dt = dv * lap(V) + U*V^2 - (feed + kill) * V
    ///
    /// Explicit Euler, 5-point Laplacian with the spec'd operation order
    /// ((N + S) + W) + E - 4*C, so doubles match the NumPy reference bit-for-bit
    /// (the ε=1e-9 tier is margin, not license). State is flat float64, shape
    /// (2, Height, Width): channel 0 = U, channel 1 = V, row-major.
    /// </summary>
    public sealed class GrayScott : IFloatFrameSource
    {
        /// <summary>Well-known (feed, kill) coordinates in the phase diagram.</summary>
        public static readonly IReadOnlyDictionary<string, (double Feed, double Kill)> Presets =
            new Dictionary<string, (double, double)>
            {
                ["Mitosis"] = (0.0367, 0.0649),
                ["Coral"] = (0.0545, 0.062),
                ["Worms"] = (0.046, 0.063),
                ["Maze"] = (0.029, 0.057),
                ["Solitons"] = (0.03, 0.062),
                ["Chaos"] = (0.026, 0.051),
                ["U-Skate"] = (0.062, 0.0609),
            };

        private readonly double[] _state; // U then V, each Height*Width
        private readonly double[] _lapU;
        private readonly double[] _lapV;

        public double Du { get; }
        public double Dv { get; }
        public double Feed { get; }
        public double Kill { get; }
        public double Dt { get; }
        public int Width { get; }
        public int Height { get; }
        public int Generation { get; private set; }

        /// <summary>Flat (2, Height, Width) float64 state: U at [0, H*W), V at [H*W, 2*H*W).</summary>
        public ReadOnlySpan<double> State => _state;

        public GrayScott(
            int width,
            int height,
            double du = 0.16,
            double dv = 0.08,
            double feed = 0.0545,
            double kill = 0.062,
            double dt = 1.0)
        {
            Width = width;
            Height = height;
            Du = du;
            Dv = dv;
            Feed = feed;
            Kill = kill;
            Dt = dt;
            _state = new double[2 * width * height];
            _lapU = new double[width * height];
            _lapV = new double[width * height];
            SeedSpots(20, 0); // the Python constructor's default init (spots, not center)
        }

        /// <summary>U=1, V=0 everywhere, then one spec'd seed box at the grid center.</summary>
        public void SeedCenter()
        {
            FillHomogeneous();
            SeedBox(Width / 2, Height / 2);
            Generation = 0;
        }

        /// <summary>
        /// U=1, V=0, then <paramref name="spots"/> seed boxes at PCG32 positions:
        /// cx = draw % Width then cy = draw % Height per spot (draw order is the spec).
        /// </summary>
        public void SeedSpots(int spots, uint seed)
        {
            FillHomogeneous();
            var rng = new Pcg32(seed);
            for (int i = 0; i < spots; i++)
            {
                int cx = (int)(rng.NextU32() % (uint)Width);
                int cy = (int)(rng.NextU32() % (uint)Height);
                SeedBox(cx, cy);
            }
            Generation = 0;
        }

        /// <summary>Load an explicit (2, Height, Width) state, row-major, U then V.</summary>
        public void SetState(ReadOnlySpan<double> state)
        {
            if (state.Length != _state.Length)
                throw new ArgumentException($"expected {_state.Length} values, got {state.Length}");
            state.CopyTo(_state);
            Generation = 0;
        }

        /// <summary>Restore a saved state at a given generation (catalog loads).</summary>
        public void SetState(ReadOnlySpan<double> state, int generation)
        {
            SetState(state);
            Generation = generation;
        }

        private void FillHomogeneous()
        {
            int cells = Width * Height;
            for (int i = 0; i < cells; i++)
            {
                _state[i] = 1.0; // U
                _state[cells + i] = 0.0; // V
            }
        }

        /// <summary>Spec'd seed: a clipped (2*half+1)^2 box with U=0.5, V=0.25.</summary>
        private void SeedBox(int cx, int cy, int half = 3)
        {
            int cells = Width * Height;
            int y0 = Math.Max(0, cy - half), y1 = Math.Min(Height, cy + half + 1);
            int x0 = Math.Max(0, cx - half), x1 = Math.Min(Width, cx + half + 1);
            for (int y = y0; y < y1; y++)
                for (int x = x0; x < x1; x++)
                {
                    _state[y * Width + x] = 0.5;
                    _state[cells + y * Width + x] = 0.25;
                }
        }

        /// <summary>Paint one cell's (U, V) in place; does not reset the generation.</summary>
        public void SetCell(int x, int y, double u, double v)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            int cells = Width * Height;
            _state[y * Width + x] = u;
            _state[cells + y * Width + x] = v;
        }

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>
        /// Frame per spec/render.md: clip(V * 2.5, 0, 1) — V is where the patterns
        /// live, and ~0.4 is its practical ceiling.
        /// </summary>
        public void WriteFrame(double[] frame)
        {
            int cells = Width * Height;
            if (frame.Length != cells)
                throw new ArgumentException($"expected {cells} values, got {frame.Length}");
            for (int i = 0; i < cells; i++)
                frame[i] = Math.Clamp(_state[cells + i] * 2.5, 0.0, 1.0);
        }

        /// <summary>Allocating convenience for <see cref="WriteFrame"/>.</summary>
        public double[] Frame()
        {
            var frame = new double[Width * Height];
            WriteFrame(frame);
            return frame;
        }

        private void StepOnce()
        {
            int w = Width, h = Height, cells = w * h;
            Laplacian5(_state, 0, _lapU);
            Laplacian5(_state, cells, _lapV);
            for (int i = 0; i < cells; i++)
            {
                double u = _state[i];
                double v = _state[cells + i];
                double uvv = u * v * v;
                // Expression shapes mirror the NumPy reference exactly.
                double newU = u + Dt * (Du * _lapU[i] - uvv + Feed * (1.0 - u));
                double newV = v + Dt * (Dv * _lapV[i] + uvv - (Feed + Kill) * v);
                _state[i] = newU;
                _state[cells + i] = newV;
            }
        }

        /// <summary>5-point Laplacian on a torus, spec'd order: ((N + S) + W) + E, minus 4*C.</summary>
        private void Laplacian5(double[] state, int offset, double[] result)
        {
            int w = Width, h = Height;
            for (int y = 0; y < h; y++)
            {
                int up = (y - 1 + h) % h, down = (y + 1) % h;
                for (int x = 0; x < w; x++)
                {
                    int left = (x - 1 + w) % w, right = (x + 1) % w;
                    double acc = state[offset + up * w + x] + state[offset + down * w + x];
                    acc += state[offset + y * w + left];
                    acc += state[offset + y * w + right];
                    acc -= 4.0 * state[offset + y * w + x];
                    result[y * w + x] = acc;
                }
            }
        }
    }
}
