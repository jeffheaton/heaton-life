using System;

namespace HeatonLife
{
    public enum BoidsBoundary
    {
        Wrap,
        Bounce,
    }

    /// <summary>
    /// Reynolds boids in d dimensions (spec/boids.md). State is a point cloud,
    /// not a grid: flat float64 rows of positions then velocities, Count*(2*d)
    /// values, in world units — the historical [x, y, vx, vy] for d=2,
    /// [x, y, z, vx, vy, vz] for d=3. One algorithm for every d: the step is a
    /// loop over components and never names an axis; only seeding and the frame
    /// projection are per-dimension recipes. Neighbors are O(N^2) with
    /// minimum-image wrapped distances. Weighted separation/alignment/cohesion
    /// steering with force and speed clamps, expression-for-expression with the
    /// NumPy reference. ε tier (1e-6).
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
        private readonly double[] _size; // world box per axis, Dimensions entries
        private readonly int _stride;    // 2 * Dimensions values per boid

        public int Count { get; }
        public int Dimensions { get; }
        public int Width { get; }
        public int Height { get; }
        public int Depth { get; }
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

        /// <summary>Flat (Count, 2*Dimensions) rows: positions then velocities per boid.</summary>
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
            BoidsBoundary boundary = BoidsBoundary.Wrap,
            int dimensions = 2,
            int depth = 256)
        {
            if (count < 1)
                throw new ArgumentOutOfRangeException(nameof(count));
            if (dimensions != 2 && dimensions != 3)
                throw new ArgumentOutOfRangeException(
                    nameof(dimensions), "dimensions must be 2 or 3");
            Count = count;
            Dimensions = dimensions;
            Width = width;
            Height = height;
            Depth = depth;
            Perception = perception;
            SeparationRadius = separationRadius;
            WSeparation = wSeparation;
            WAlignment = wAlignment;
            WCohesion = wCohesion;
            MaxSpeed = maxSpeed;
            MinSpeed = minSpeed;
            MaxForce = maxForce;
            Boundary = boundary;
            _stride = 2 * dimensions;
            _size = dimensions == 2
                ? new[] { (double)width, height }
                : new[] { (double)width, height, depth };
            _state = new double[count * _stride];
            _scratch = new double[count * _stride];
            SeedRandom(0);
        }

        /// <summary>
        /// Random init per spec "Initialization" — per-dimension draw recipes
        /// (an angle does not generalize by component), launch = (min+max)/2:
        /// d=2 is 3 draws per boid (x, y, heading), the historical byte stream;
        /// d=3 is 5 draws (x, y, z, azimuth, w = cos(polar)) — a uniform sphere
        /// direction in closed form, no rejection sampling.
        /// </summary>
        public void SeedRandom(uint seed)
        {
            var rng = new Pcg32(seed);
            double launch = (MinSpeed + MaxSpeed) / 2.0;
            if (Dimensions == 2)
            {
                for (int i = 0; i < Count; i++)
                {
                    _state[i * 4 + 0] = rng.NextU32() / 4294967296.0 * Width;
                    _state[i * 4 + 1] = rng.NextU32() / 4294967296.0 * Height;
                    double angle = rng.NextU32() / 4294967296.0 * 2.0 * Math.PI;
                    _state[i * 4 + 2] = Math.Cos(angle) * launch;
                    _state[i * 4 + 3] = Math.Sin(angle) * launch;
                }
            }
            else
            {
                for (int i = 0; i < Count; i++)
                {
                    _state[i * 6 + 0] = rng.NextU32() / 4294967296.0 * Width;
                    _state[i * 6 + 1] = rng.NextU32() / 4294967296.0 * Height;
                    _state[i * 6 + 2] = rng.NextU32() / 4294967296.0 * Depth;
                    double azimuth = rng.NextU32() / 4294967296.0 * 2.0 * Math.PI;
                    double w = rng.NextU32() / 4294967296.0 * 2.0 - 1.0;
                    double ring = Math.Sqrt(1.0 - w * w);
                    _state[i * 6 + 3] = ring * Math.Cos(azimuth) * launch;
                    _state[i * 6 + 4] = ring * Math.Sin(azimuth) * launch;
                    _state[i * 6 + 5] = w * launch;
                }
            }
            Generation = 0;
        }

        /// <summary>Load an explicit (Count, 2*Dimensions) state.</summary>
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

        /// <summary>Overwrite one 2D boid's [x, y, vx, vy] in place; does not reset the generation.</summary>
        public void SetBoid(int index, double x, double y, double vx, double vy)
        {
            if (Dimensions != 2)
                throw new InvalidOperationException("2D SetBoid on a 3D flock — pass z and vz");
            if (index < 0 || index >= Count)
                throw new ArgumentOutOfRangeException(nameof(index));
            _state[index * 4 + 0] = x;
            _state[index * 4 + 1] = y;
            _state[index * 4 + 2] = vx;
            _state[index * 4 + 3] = vy;
        }

        /// <summary>Overwrite one 3D boid's [x, y, z, vx, vy, vz] in place.</summary>
        public void SetBoid(int index, double x, double y, double z, double vx, double vy, double vz)
        {
            if (Dimensions != 3)
                throw new InvalidOperationException("3D SetBoid on a 2D flock");
            if (index < 0 || index >= Count)
                throw new ArgumentOutOfRangeException(nameof(index));
            _state[index * 6 + 0] = x;
            _state[index * 6 + 1] = y;
            _state[index * 6 + 2] = z;
            _state[index * 6 + 3] = vx;
            _state[index * 6 + 4] = vy;
            _state[index * 6 + 5] = vz;
        }

        /// <summary>
        /// Radial velocity impulse at (x, y) — spec/boids.md "Nudge (editing)".
        /// Positive strength pushes nearby boids away (scare), negative pulls
        /// them in (lure); offsets are minimum-image wrapped on a torus. The
        /// pointer is 2-D: the impulse acts in the x/y plane and leaves any z
        /// motion alone. Editing, not physics — the generation is unchanged.
        /// </summary>
        public void Nudge(double x, double y, double radius, double strength)
        {
            bool wrap = Boundary == BoidsBoundary.Wrap;
            for (int i = 0; i < Count; i++)
            {
                int row = i * _stride;
                double offsetX = _state[row + 0] - x;
                double offsetY = _state[row + 1] - y;
                if (wrap)
                {
                    offsetX -= Width * Math.Round(offsetX / Width);   // banker's, matching np.round
                    offsetY -= Height * Math.Round(offsetY / Height);
                }
                double dist = Math.Sqrt(offsetX * offsetX + offsetY * offsetY);
                if (dist <= 0.0 || dist >= radius)
                    continue;
                _state[row + Dimensions + 0] += offsetX / dist * strength;
                _state[row + Dimensions + 1] += offsetY / dist * strength;
            }
        }

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>
        /// Frame per spec: rasterize to (Height, Width) soft dots — kernel pass by
        /// pass, boids in index order within each pass, then clip to [0, 1]. Pixel =
        /// truncate(position) with floored wrap. d=3 projects orthographically along
        /// z, each boid's kernel scaled by the depth cue b = 0.3 + 0.7*(1 - z/Depth)
        /// (z = 0 nearest, brightest), matching the reference.
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
                    int row = i * _stride;
                    long px = FloorModInt((long)_state[row + 0], Width);
                    long py = FloorModInt((long)_state[row + 1], Height);
                    long y = FloorModInt(py + dy, Height);
                    long x = FloorModInt(px + dx, Width);
                    double cue = Dimensions == 3
                        ? 0.3 + 0.7 * (1.0 - _state[row + 2] / Depth)
                        : 1.0;
                    frame[y * Width + x] += weight * cue;
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
            int dim = Dimensions;
            int stride = _stride;
            bool wrap = Boundary == BoidsBoundary.Wrap;
            double perception2 = Perception * Perception;
            double separation2 = SeparationRadius * SeparationRadius;

            // Per-boid temporaries, one component per axis (stack: zero-alloc step).
            Span<double> delta = stackalloc double[3];
            Span<double> sumOff = stackalloc double[3];
            Span<double> sumVel = stackalloc double[3];
            Span<double> sep = stackalloc double[3];
            Span<double> veli = stackalloc double[3];
            Span<double> steer = stackalloc double[3];
            Span<double> acc = stackalloc double[3];
            Span<double> newVel = stackalloc double[3];

            for (int i = 0; i < n; i++)
            {
                int baseI = i * stride;
                for (int a = 0; a < dim; a++)
                {
                    sumOff[a] = 0.0;
                    sumVel[a] = 0.0;
                    sep[a] = 0.0;
                    veli[a] = _state[baseI + dim + a];
                }

                int neighbors = 0;
                for (int j = 0; j < n; j++)
                {
                    int baseJ = j * stride;
                    // delta = pos_j - pos_i, minimum image per axis when wrapping
                    double d2 = 0.0;
                    for (int a = 0; a < dim; a++)
                    {
                        double da = _state[baseJ + a] - _state[baseI + a];
                        if (wrap)
                            da -= _size[a] * Math.Round(da / _size[a]); // banker's, matching np.round
                        delta[a] = da;
                        d2 += da * da;
                    }
                    if (d2 > 0.0 && d2 <= perception2)
                    {
                        neighbors++;
                        for (int a = 0; a < dim; a++)
                        {
                            sumOff[a] += delta[a];
                            sumVel[a] += _state[baseJ + dim + a];
                        }
                    }
                    if (d2 > 0.0 && d2 <= separation2)
                    {
                        double denom = Math.Max(d2, 1e-12);
                        for (int a = 0; a < dim; a++)
                            sep[a] += -delta[a] / denom;
                    }
                }
                double count = Math.Max(neighbors, 1);
                for (int a = 0; a < dim; a++)
                {
                    sumOff[a] /= count; // mean_offset
                    sumVel[a] /= count; // mean_vel
                }

                // acc = w_sep*steer(separation) + w_align*steer(mean_vel) + w_coh*steer(mean_offset)
                for (int a = 0; a < dim; a++)
                    acc[a] = 0.0;
                Steer(sep, veli, dim, steer);
                for (int a = 0; a < dim; a++)
                    acc[a] += WSeparation * steer[a];
                Steer(sumVel, veli, dim, steer);
                for (int a = 0; a < dim; a++)
                    acc[a] += WAlignment * steer[a];
                Steer(sumOff, veli, dim, steer);
                for (int a = 0; a < dim; a++)
                    acc[a] += WCohesion * steer[a];

                double speed2 = 0.0;
                for (int a = 0; a < dim; a++)
                {
                    newVel[a] = veli[a] + acc[a];
                    speed2 += newVel[a] * newVel[a];
                }
                double speed = Math.Sqrt(speed2);
                if (speed > MaxSpeed)
                {
                    for (int a = 0; a < dim; a++)
                        newVel[a] = newVel[a] / speed * MaxSpeed;
                }
                if (speed > 0.0 && speed < MinSpeed) // original speed, like the reference
                {
                    for (int a = 0; a < dim; a++)
                        newVel[a] = newVel[a] / speed * MinSpeed;
                }

                for (int a = 0; a < dim; a++)
                {
                    double np = _state[baseI + a] + newVel[a];
                    if (wrap)
                    {
                        np = Mod(np, _size[a]);
                    }
                    else
                    {
                        // bounce: reflect position and flip velocity at the walls
                        if (np < 0.0) { np = -np; newVel[a] = -newVel[a]; }
                        if (np > _size[a]) { np = 2.0 * _size[a] - np; newVel[a] = -newVel[a]; }
                        np = Math.Clamp(np, 0.0, _size[a] - 1e-9);
                    }
                    _scratch[baseI + a] = np;
                    _scratch[baseI + dim + a] = newVel[a];
                }
            }
            (_state, _scratch) = (_scratch, _state);
        }

        /// <summary>Reynolds steering: desired = normalize(direction)*max_speed; clip force to max_force.</summary>
        private void Steer(
            ReadOnlySpan<double> direction, ReadOnlySpan<double> vel, int dim, Span<double> result)
        {
            double norm2 = 0.0;
            for (int a = 0; a < dim; a++)
                norm2 += direction[a] * direction[a];
            double norm = Math.Sqrt(norm2);
            if (norm <= 0.0)
            {
                for (int a = 0; a < dim; a++)
                    result[a] = 0.0;
                return;
            }
            double force2 = 0.0;
            for (int a = 0; a < dim; a++)
            {
                result[a] = direction[a] / norm * MaxSpeed - vel[a];
                force2 += result[a] * result[a];
            }
            double force = Math.Sqrt(force2);
            if (force > MaxForce)
            {
                for (int a = 0; a < dim; a++)
                    result[a] = result[a] / force * MaxForce;
            }
        }

        /// <summary>Floored modulo (result in [0, m) for m &gt; 0), matching np.mod.</summary>
        private static double Mod(double x, double m)
        {
            double r = x % m;
            return r < 0.0 ? r + m : r;
        }
    }
}
