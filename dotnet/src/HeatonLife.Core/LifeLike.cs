using System;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// Life-like cellular automaton (spec/lifelike.md). State is a flat row-major
    /// byte grid (0/1), index = y * Width + x — the same memory layout as the
    /// Python implementation and the conformance vectors. Bit-exact tier. The rule is any
    /// Life-like rule (spec/rules.md), run through its 512-entry table, on any topology
    /// (spec/topology.md), read through the grid's halo.
    /// </summary>
    public sealed class LifeLike : IIndexedFrameSource, IRegionWorld
    {
        private readonly byte[] _table; // next state by 3×3 neighborhood index (spec/rules.md)
        private readonly Halo _halo; // the cells past the edges (spec/topology.md "The halo")
        private readonly byte[] _padded; // the halo each generation reads
        private byte[] _cells;
        private byte[] _scratch;

        public int Width { get; }
        public int Height { get; }
        public string Rule { get; }

        /// <summary>The topology's boundary: <see cref="Topology"/>.Boundary.</summary>
        public Boundary Boundary => Topology.Boundary;

        /// <summary>How the grid's edges join (spec/topology.md).</summary>
        public Topology Topology { get; }

        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        public LifeLike(
            string rule,
            int width,
            int height,
            Boundary boundary = Boundary.Torus)
            : this(rule, width, height, new Topology(boundary))
        {
        }

        /// <summary>A world on any topology (spec/topology.md); throws
        /// <see cref="TopologyException"/> for one the size can't have.</summary>
        public LifeLike(string rule, int width, int height, Topology topology)
        {
            LifeRule compiled = RuleString.Compile(rule);
            Rule = compiled.Canonical;
            _table = compiled.Table.ToArray();
            _halo = new Halo(topology, width, height);
            _padded = new byte[_halo.Length];
            Width = width;
            Height = height;
            Topology = topology;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            SeedSoup(0.35, 0); // the Python constructor's default init
        }

        /// <summary>Soup init per spec: PCG32 seq 0, row-major draws, alive iff draw &lt; floor(density * 2^32).</summary>
        public void SeedSoup(double density, uint seed)
        {
            Seeding.Soup(_cells, density, seed);
            Generation = 0;
            Remember(seed, s => { Seeding.Soup(_cells, density, s); Generation = 0; });
        }

        /// <summary>Blob init per spec: soup restricted to a centered disk (radius as a fraction of min dimension).</summary>
        public void SeedBlob(double density, uint seed, double radius = 0.25)
        {
            Seeding.Blob(_cells, Width, Height, density, radius, seed);
            Generation = 0;
            Remember(
                seed,
                s => { Seeding.Blob(_cells, Width, Height, density, radius, s); Generation = 0; });
        }

        /// <summary>
        /// Single init per spec/lifelike.md: one live cell at the grid's middle,
        /// consuming no RNG draws. The third of the family's four `init` strategies
        /// (soup / blob / single / array) — Python has had it since the reference
        /// implementation; it was missing here because no vector exercised it.
        /// </summary>
        public void SeedSingle()
        {
            Seeding.Single(_cells, Width, Height);
            Generation = 0;
            Remember(_seed, _ => { Seeding.Single(_cells, Width, Height); Generation = 0; });
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

        /// <summary>Load an explicit 0/1 grid (row-major, Height*Width entries).</summary>
        public void SetState(ReadOnlySpan<byte> cells)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
                _cells[i] = (byte)(cells[i] > 0 ? 1 : 0);
            Generation = 0;
            var snapshot = _cells.Clone() as byte[];
            Remember(_seed, _ =>
            {
                Array.Copy(snapshot!, _cells, _cells.Length);
                Generation = 0;
            });
        }

        /// <summary>Restore a saved state at a given generation (catalog loads).</summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation)
        {
            SetState(cells);
            Generation = generation;
        }

        /// <summary>
        /// Load a 0/1 grid at a given generation (spec/README.md "A world's state and its start").
        /// Without <paramref name="keepStart"/> it is <see cref="SetState(ReadOnlySpan{byte}, int)"/>:
        /// the grid also becomes the start <see cref="Reset"/> returns to. With it the start stays
        /// as it was and nothing is copied for it, so showing a saved frame or putting back an undo
        /// point allocates nothing.
        /// </summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation, bool keepStart)
        {
            if (!keepStart)
            {
                SetState(cells, generation);
                return;
            }
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
                _cells[i] = (byte)(cells[i] > 0 ? 1 : 0);
            Generation = generation;
        }

        /// <summary>Paint one cell in place (0/1); does not reset the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            _cells[y * Width + x] = (byte)(value > 0 ? 1 : 0);
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family blank, 0 (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    SetCell(x, y, 0);
        }

        /// <summary>
        /// Advance Selection (spec/patterns.md "Editing a region"): the inclusive region evolves
        /// <paramref name="n"/> generations as if nothing else existed — a copy of the world blank
        /// outside it runs under the world's rule and boundary (a torus wraps), and its region is
        /// copied back. Cells outside the region and <see cref="Generation"/> are untouched. A
        /// canceled <paramref name="cancellationToken"/> stops it promptly with
        /// <see cref="OperationCanceledException"/> and leaves the world exactly as it was.
        /// </summary>
        public void AdvanceSelection(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: false, cancellationToken);

        /// <summary>
        /// Advance Outside: Advance Selection's mirror image. The world with the region blank runs
        /// <paramref name="n"/> generations and everything outside the region is copied back; the
        /// region keeps its cells, and <see cref="Generation"/> stays. A canceled
        /// <paramref name="cancellationToken"/> stops it as it does Advance Selection.
        /// </summary>
        public void AdvanceOutside(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: true, cancellationToken);

        byte[] IRegionWorld.Cells => _cells;

        void IRegionWorld.StepOnce(CancellationToken cancellationToken) => StepOnce(cancellationToken);

        /// <summary>
        /// Random fill (spec/patterns.md "Editing a region"): the inclusive region becomes the soup
        /// of a world its size — PCG32 stream 0, one draw per cell in row-major order, alive iff
        /// draw &lt; ⌊density · 2^32⌋ — the same cells <see cref="HashLife.FillRandom"/> gives a
        /// rectangle of that size and seed. <see cref="Generation"/> is untouched.
        /// </summary>
        public void FillRandom(int x0, int y0, int x1, int y1, double density, ulong seed)
            => Patterns.FillRandom(_cells, Width, Height, x0, y0, x1, y1, density, seed);

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>Frame per spec/render.md: palette index = state * 255.</summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} bytes, got {frame.Length}");
            for (int i = 0; i < _cells.Length; i++)
                frame[i] = (byte)(_cells[i] * 255);
        }

        /// <summary>Allocating convenience for <see cref="WriteFrame"/>.</summary>
        public byte[] Frame()
        {
            var frame = new byte[_cells.Length];
            WriteFrame(frame);
            return frame;
        }

        private void StepOnce(CancellationToken cancellationToken = default)
        {
            int w = Width, h = Height, stride = _halo.Columns;
            byte[] p = _padded;
            _halo.Fill(_cells, p, 0);
            for (int y = 0; y < h; y++)
            {
                // Polled each row, so even a big grid stops within a generation (spec/patterns.md
                // "Canceling"); Step's default token is never canceled.
                if (cancellationToken.IsCancellationRequested)
                    throw GridRegion.Canceled(cancellationToken, Generation);
                // Halo indices of (0, y - 1), (0, y) and (0, y + 1): row y + 1 of the halo is the
                // grid's row y, and its column x + 1 the grid's column x.
                int up = y * stride + 1, mid = up + stride, down = mid + stride, row = y * w;
                for (int x = 0; x < w; x++)
                {
                    // The neighborhood index (spec/rules.md): NW 256, N 128, NE 64, W 32,
                    // the cell 16, E 8, SW 4, S 2, SE 1.
                    int index = (p[up + x - 1] << 8) | (p[up + x] << 7) | (p[up + x + 1] << 6)
                        | (p[mid + x - 1] << 5) | (p[mid + x] << 4) | (p[mid + x + 1] << 3)
                        | (p[down + x - 1] << 2) | (p[down + x] << 1) | p[down + x + 1];
                    _scratch[row + x] = _table[index];
                }
            }
            (_cells, _scratch) = (_scratch, _cells);
        }
    }
}
