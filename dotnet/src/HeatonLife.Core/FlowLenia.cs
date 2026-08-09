using System;

namespace HeatonLife
{
    /// <summary>
    /// Flow Lenia (Plantec et al. 2022, simplified single-channel form): mass-conserving.
    /// Matter flows along the growth gradient, switching to diffusion (down its own
    /// concentration gradient) where it crowds: F = (1-alpha)*grad(G) - alpha*grad(A),
    /// alpha = clip((A/theta)^2, 0, 1). Mass then advects by bilinear reintegration —
    /// each cell's mass is distributed over the 4 cells around its displaced position.
    /// Total mass is conserved by construction; patterns emerge purely from transport.
    /// </summary>
    public sealed class FlowLenia : LeniaBase
    {
        /// <summary>Max displacement in cells per step; keeps the bilinear scatter local.</summary>
        public const double MaxDisplacement = 0.9;

        private readonly int[] _y0;
        private readonly int[] _x0;
        private readonly double[] _fy;
        private readonly double[] _fx;
        private double[] _scratch;

        public double Theta { get; }

        public FlowLenia(
            int width,
            int height,
            int radius = 13,
            double mu = 0.3,
            double sigma = 0.08,
            double dt = 2.0,
            double theta = 2.0)
            : base(width, height, radius, mu, sigma, dt)
        {
            Theta = theta;
            _y0 = new int[width * height];
            _x0 = new int[width * height];
            _fy = new double[width * height];
            _fx = new double[width * height];
            _scratch = new double[width * height];
            SeedSoup(0.5, 0); // the Python constructor's default init
        }

        private protected override void StepOnce()
        {
            int w = Width, h = Height;
            double[] growth = Potential();
            for (int i = 0; i < growth.Length; i++)
                growth[i] = Growth(growth[i]);

            // Displaced position per cell: (y, x) + clip(dt * F, ±MaxDisplacement),
            // F = (1-alpha)*grad(G) - alpha*grad(A), central differences on the torus.
            for (int y = 0; y < h; y++)
            {
                int up = (y - 1 + h) % h, down = (y + 1) % h;
                for (int x = 0; x < w; x++)
                {
                    int left = (x - 1 + w) % w, right = (x + 1) % w;
                    int i = y * w + x;
                    double gyG = (growth[down * w + x] - growth[up * w + x]) * 0.5;
                    double gxG = (growth[y * w + right] - growth[y * w + left]) * 0.5;
                    double gyA = (_state[down * w + x] - _state[up * w + x]) * 0.5;
                    double gxA = (_state[y * w + right] - _state[y * w + left]) * 0.5;
                    double ratio = _state[i] / Theta;
                    double alpha = Math.Clamp(ratio * ratio, 0.0, 1.0);
                    double dy = Math.Clamp(
                        Dt * ((1.0 - alpha) * gyG - alpha * gyA), -MaxDisplacement, MaxDisplacement);
                    double dx = Math.Clamp(
                        Dt * ((1.0 - alpha) * gxG - alpha * gxA), -MaxDisplacement, MaxDisplacement);
                    double ty = y + dy;
                    double tx = x + dx;
                    int y0 = (int)Math.Floor(ty);
                    int x0 = (int)Math.Floor(tx);
                    _y0[i] = y0;
                    _x0[i] = x0;
                    _fy[i] = ty - y0;
                    _fx[i] = tx - x0;
                }
            }

            // Bilinear scatter in four passes over all cells (row-major), matching the
            // reference's np.add.at accumulation order corner by corner.
            Array.Clear(_scratch, 0, _scratch.Length);
            for (int corner = 0; corner < 4; corner++)
            {
                int oy = corner >> 1, ox = corner & 1;
                for (int i = 0; i < _state.Length; i++)
                {
                    double wy = oy == 0 ? 1.0 - _fy[i] : _fy[i];
                    double wx = ox == 0 ? 1.0 - _fx[i] : _fx[i];
                    int iy = (_y0[i] + oy + h) % h;
                    int ix = (_x0[i] + ox + w) % w;
                    _scratch[iy * w + ix] += _state[i] * (wy * wx);
                }
            }
            (_state, _scratch) = (_scratch, _state);
        }
    }
}
