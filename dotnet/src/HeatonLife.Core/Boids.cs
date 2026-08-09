using System;

namespace HeatonLife
{
    public enum BoidsBoundary
    {
        Wrap,
        Bounce,
    }

    /// <summary>
    /// Reynolds boids (spec/boids.md). State is a point cloud, not a grid: flat
    /// float64 rows of [x, y, vx, vy], Count*4 values, in world units. Neighbors are
    /// O(N^2) with minimum-image wrapped distances. Weighted separation/alignment/
    /// cohesion steering with force and speed clamps, expression-for-expression with
    /// the NumPy reference. ε tier (1e-6).
    /// </summary>
    public sealed class Boids : IFloatFrameSource
    {
        // Rasterization kernel (spec/render.md): center bright, cross and diagonals
        // dimmer; entries are (dy, dx, weight) and their order is the accumulation order.
        private static readonly (int Dy, int Dx, double Weight)[] Dot =
        {
            (0, 0, 1.0), (-1, 0, 0.55), (1, 0, 0.55), (0, -1, 0.55), (0, 1, 0.55),
            (-1, -1, 0.3), (-1, 1, 0.3), (1, -1, 0.3), (1, 1, 0.3),
        };
        private double[] _state;
        private double[] _scratch;

        public int Count { get; }
        public int Width { get; }
        public int Height { get; }
        public double Perception { get; }
        public double SeparationRadius { get; }
        public double WSeparation { get; }
        public double WAlignment { get; }
        public double WCohesion { get; }
        public double MaxSpeed { get; }
        public double MinSpeed { get; }
        public double MaxForce { get; }
        public BoidsBoundary Boundary { get; }
        public int Generation { get; private set; }

        /// <summary>Flat (Count, 4) rows: [x, y, vx, vy] per boid.</summary>
        public ReadOnlySpan<double> State => _state;

        public Boids(
            int count,
            int width,
            int height,
            double perception = 12.0,
            double separationRadius = 6.0,
            double wSeparation = 1.5,
            double wAlignment = 1.0,
            double wCohesion = 1.0,
            double maxSpeed = 3.0,
            double minSpeed = 1.0,
            double maxForce = 0.08,
            BoidsBoundary boundary = BoidsBoundary.Wrap)
        {
            if (count < 1)
                throw new ArgumentOutOfRangeException(nameof(count));
            Count = count;
            Width = width;
            Height = height;
            Perception = perception;
            SeparationRadius = separationRadius;
            WSeparation = wSeparation;
            WAlignment = wAlignment;
            WCohesion = wCohesion;
            MaxSpeed = maxSpeed;
            MinSpeed = minSpeed;
            MaxForce = maxForce;
            Boundary = boundary;
            _state = new double[count * 4];
            _scratch = new double[count * 4];
            SeedRandom(0);
        }

        /// <summary>
        /// Random init per spec: 3 PCG32 draws per boid — x (fraction of Width),
        /// y (fraction of Height), heading angle — launch speed = (min + max) / 2.
        /// </summary>
        public void SeedRandom(uint seed)
        {
            var rng = new Pcg32(seed);
            double launch = (MinSpeed + MaxSpeed) / 2.0;
            for (int i = 0; i < Count; i++)
            {
                _state[i * 4 + 0] = rng.NextU32() / 4294967296.0 * Width;
                _state[i * 4 + 1] = rng.NextU32() / 4294967296.0 * Height;
                double angle = rng.NextU32() / 4294967296.0 * 2.0 * Math.PI;
                _state[i * 4 + 2] = Math.Cos(angle) * launch;
                _state[i * 4 + 3] = Math.Sin(angle) * launch;
            }
            Generation = 0;
        }

        /// <summary>Load an explicit (Count, 4) state, rows of [x, y, vx, vy].</summary>
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

        /// <summary>Overwrite one boid's [x, y, vx, vy] in place; does not reset the generation.</summary>
        public void SetBoid(int index, double x, double y, double vx, double vy)
        {
            if (index < 0 || index >= Count)
                throw new ArgumentOutOfRangeException(nameof(index));
            _state[index * 4 + 0] = x;
            _state[index * 4 + 1] = y;
            _state[index * 4 + 2] = vx;
            _state[index * 4 + 3] = vy;
        }

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>
        /// Frame per spec/render.md: rasterize to (Height, Width) soft dots — kernel
        /// pass by pass, boids in index order within each pass, then clip to [0, 1].
        /// Pixel = truncate(position) with floored wrap, matching the reference.
        /// </summary>
        public void WriteFrame(double[] frame)
        {
            int cells = Width * Height;
            if (frame.Length != cells)
                throw new ArgumentException($"expected {cells} values, got {frame.Length}");
            Array.Clear(frame, 0, cells);
            foreach (var (dy, dx, weight) in Dot)
            {
                for (int i = 0; i < Count; i++)
                {
                    long px = FloorModInt((long)_state[i * 4 + 0], Width);
                    long py = FloorModInt((long)_state[i * 4 + 1], Height);
                    long y = FloorModInt(py + dy, Height);
                    long x = FloorModInt(px + dx, Width);
                    frame[y * Width + x] += weight;
                }
            }
            for (int i = 0; i < cells; i++)
                frame[i] = Math.Clamp(frame[i], 0.0, 1.0);
        }

        /// <summary>Allocating convenience for <see cref="WriteFrame"/>.</summary>
        public double[] Frame()
        {
            var frame = new double[Width * Height];
            WriteFrame(frame);
            return frame;
        }

        private static long FloorModInt(long value, long modulus)
        {
            long r = value % modulus;
            return r < 0 ? r + modulus : r;
        }

        private void StepOnce()
        {
            int n = Count;
            double w = Width, h = Height;
            bool wrap = Boundary == BoidsBoundary.Wrap;
            double perception2 = Perception * Perception;
            double separation2 = SeparationRadius * SeparationRadius;

            for (int i = 0; i < n; i++)
            {
                double xi = _state[i * 4 + 0], yi = _state[i * 4 + 1];
                double vxi = _state[i * 4 + 2], vyi = _state[i * 4 + 3];

                int neighbors = 0;
                double sumOffX = 0.0, sumOffY = 0.0;
                double sumVelX = 0.0, sumVelY = 0.0;
                double sepX = 0.0, sepY = 0.0;
                for (int j = 0; j < n; j++)
                {
                    // delta = pos_j - pos_i, minimum image on the torus when wrapping
                    double dx = _state[j * 4 + 0] - xi;
                    double dy = _state[j * 4 + 1] - yi;
                    if (wrap)
                    {
                        dx -= w * Math.Round(dx / w); // banker's rounding, matching np.round
                        dy -= h * Math.Round(dy / h);
                    }
                    double d2 = dx * dx + dy * dy;
                    if (d2 > 0.0 && d2 <= perception2)
                    {
                        neighbors++;
                        sumOffX += dx;
                        sumOffY += dy;
                        sumVelX += _state[j * 4 + 2];
                        sumVelY += _state[j * 4 + 3];
                    }
                    if (d2 > 0.0 && d2 <= separation2)
                    {
                        double denom = Math.Max(d2, 1e-12);
                        sepX += -dx / denom;
                        sepY += -dy / denom;
                    }
                }
                double count = Math.Max(neighbors, 1);
                double meanOffX = sumOffX / count, meanOffY = sumOffY / count;
                double meanVelX = sumVelX / count, meanVelY = sumVelY / count;

                var (s1x, s1y) = Steer(sepX, sepY, vxi, vyi);
                var (s2x, s2y) = Steer(meanVelX, meanVelY, vxi, vyi);
                var (s3x, s3y) = Steer(meanOffX, meanOffY, vxi, vyi);
                double accX = WSeparation * s1x + WAlignment * s2x + WCohesion * s3x;
                double accY = WSeparation * s1y + WAlignment * s2y + WCohesion * s3y;

                double nvx = vxi + accX;
                double nvy = vyi + accY;
                double speed = Math.Sqrt(nvx * nvx + nvy * nvy);
                if (speed > MaxSpeed)
                {
                    nvx = nvx / speed * MaxSpeed;
                    nvy = nvy / speed * MaxSpeed;
                }
                if (speed > 0.0 && speed < MinSpeed) // original speed, like the reference
                {
                    nvx = nvx / speed * MinSpeed;
                    nvy = nvy / speed * MinSpeed;
                }

                double nx = xi + nvx;
                double ny = yi + nvy;
                if (wrap)
                {
                    nx = Mod(nx, w);
                    ny = Mod(ny, h);
                }
                else
                {
                    // bounce: reflect position and flip velocity at the walls
                    if (nx < 0.0) { nx = -nx; nvx = -nvx; }
                    if (nx > w) { nx = 2.0 * w - nx; nvx = -nvx; }
                    if (ny < 0.0) { ny = -ny; nvy = -nvy; }
                    if (ny > h) { ny = 2.0 * h - ny; nvy = -nvy; }
                    nx = Math.Clamp(nx, 0.0, w - 1e-9);
                    ny = Math.Clamp(ny, 0.0, h - 1e-9);
                }

                _scratch[i * 4 + 0] = nx;
                _scratch[i * 4 + 1] = ny;
                _scratch[i * 4 + 2] = nvx;
                _scratch[i * 4 + 3] = nvy;
            }
            (_state, _scratch) = (_scratch, _state);
        }

        /// <summary>Reynolds steering: desired = normalize(direction)*max_speed; clip force to max_force.</summary>
        private (double X, double Y) Steer(double dirX, double dirY, double velX, double velY)
        {
            double norm = Math.Sqrt(dirX * dirX + dirY * dirY);
            if (norm <= 0.0)
                return (0.0, 0.0);
            double desX = dirX / norm * MaxSpeed;
            double desY = dirY / norm * MaxSpeed;
            double steerX = desX - velX;
            double steerY = desY - velY;
            double force = Math.Sqrt(steerX * steerX + steerY * steerY);
            if (force > MaxForce)
            {
                steerX = steerX / force * MaxForce;
                steerY = steerY / force * MaxForce;
            }
            return (steerX, steerY);
        }

        /// <summary>Floored modulo (result in [0, m) for m &gt; 0), matching np.mod.</summary>
        private static double Mod(double x, double m)
        {
            double r = x % m;
            return r < 0.0 ? r + m : r;
        }
    }
}
