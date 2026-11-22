using System;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// Larger than Life (spec/ltl.md): Life over a box, a diamond or a circle of range r, birth
    /// and survival as ranges of counts, and beyond two states dying states that decay as
    /// Generations rules do. State is a flat row-major byte grid of states 0 to S − 1. Bounded
    /// grids only, on any topology (spec/topology.md), every count read through the grid's halo
    /// of radius r: a summed-area table for the box, row prefix sums for the diamond and the
    /// circle, exact integers. <see cref="Step"/>, <see cref="WriteFrame"/> and a keep-start
    /// <c>SetState</c> allocate nothing. Bit-exact tier. The Python reference's
    /// heaton_life.ca.ltl.LargerThanLife.
    /// </summary>
    public sealed class LargerThanLife : IIndexedFrameSource, IRegionWorld
    {
        private readonly LtlRule _rule;
        private readonly Halo _halo; // the cells past the edges, r deep (spec/topology.md "The halo")
        private readonly byte[] _padded; // the halo each generation reads
        private readonly int[] _sums; // the box's summed-area table, or every halo row's prefix sums
        private readonly int[] _halfWidths; // w(dy), dy from −r to r
        private byte[] _cells;
        private byte[] _scratch;

        public int Width { get; }
        public int Height { get; }

        /// <summary>The rule, its canonical text in <see cref="LtlRule.Canonical"/>.</summary>
        public LtlRule Rule => _rule;

        /// <summary>The topology's boundary: <see cref="Topology"/>.Boundary.</summary>
        public Boundary Boundary => Topology.Boundary;

        /// <summary>How the grid's edges join (spec/topology.md).</summary>
        public Topology Topology { get; }

        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        /// <summary>
        /// A world of <paramref name="rule"/> (either form of spec/ltl.md's rule text) on
        /// <paramref name="topology"/> (the torus by default), seeded with a soup of density 0.5.
        /// Throws <see cref="ArgumentException"/> for text that is no rule and for a world
        /// narrower or shorter than 2r + 1 cells, and <see cref="TopologyException"/> for a
        /// topology the size can't have.
        /// </summary>
        public LargerThanLife(string rule, int width, int height, Topology topology = default)
            : this(LtlRule.Parse(rule), width, height, topology)
        {
        }

        public LargerThanLife(LtlRule rule, int width, int height, Topology topology = default)
        {
            _rule = rule ?? throw new ArgumentNullException(nameof(rule));
            int side = 2 * rule.Range + 1;
            if (width < side || height < side)
                throw new ArgumentException(
                    $"a Larger than Life world of range {rule.Range} is at least {side} cells wide and high (spec/ltl.md)");
            _halo = new Halo(topology, width, height, rule.Range);
            _padded = new byte[_halo.Length];
            long sums = rule.Neighborhood == LtlNeighborhood.Moore
                ? (long)(_halo.Rows + 1) * (_halo.Columns + 1)
                : (long)_halo.Rows * (_halo.Columns + 1);
            if (sums > int.MaxValue)
                throw new ArgumentOutOfRangeException(nameof(width), "the world and its halo hold more cells than one array can");
            _sums = new int[sums];
            _halfWidths = rule.HalfWidthSpan.ToArray();
            Width = width;
            Height = height;
            Topology = topology;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            SeedSoup(0.5, 0); // the Python constructor's default init
        }

        /// <summary>Soup init per spec/lifelike.md: PCG32 seq 0, row-major draws, alive (state 1)
        /// iff draw &lt; floor(density * 2^32).</summary>
        public void SeedSoup(double density, uint seed)
        {
            Seeding.Soup(_cells, density, seed);
            Generation = 0;
            Remember(seed, s => { Seeding.Soup(_cells, density, s); Generation = 0; });
        }

        /// <summary>Blob init per spec/lifelike.md: the soup restricted to a centered disk.</summary>
        public void SeedBlob(double density, uint seed, double radius = 0.25)
        {
            Seeding.Blob(_cells, Width, Height, density, radius, seed);
            Generation = 0;
            Remember(seed, s => { Seeding.Blob(_cells, Width, Height, density, radius, s); Generation = 0; });
        }

        /// <summary>Single init per spec/lifelike.md: one alive cell at the grid's middle.</summary>
        public void SeedSingle()
        {
            Seeding.Single(_cells, Width, Height);
            Generation = 0;
            Remember(_seed, _ => { Seeding.Single(_cells, Width, Height); Generation = 0; });
        }

        // How this world was last seeded, so Reset can replay it (as LifeLike does).
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

        /// <summary>Load an explicit grid (row-major, states 0 to S − 1). A grid of the wrong size,
        /// or a state past the rule's, throws and changes nothing.</summary>
        public void SetState(ReadOnlySpan<byte> cells) => SetState(cells, 0);

        /// <summary>Restore a saved state at a given generation (catalog loads).</summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation) => SetState(cells, generation, keepStart: false);

        /// <summary>
        /// Load a grid at a given generation (spec/README.md "A world's state and its start").
        /// Without <paramref name="keepStart"/> the grid also becomes the start <see cref="Reset"/>
        /// returns to; with it the start stays as it was and nothing is copied for it.
        /// </summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation, bool keepStart)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
            {
                if (cells[i] >= _rule.States)
                    throw new ArgumentException($"state {cells[i]} is past this rule's {_rule.States} states");
            }
            cells.CopyTo(_cells);
            Generation = generation;
            if (!keepStart)
                RememberGrid();
        }

        /// <summary>The loaded grid becomes the start <see cref="Reset"/> returns to (the reference's
        /// <c>array</c> init). Its own method, so that a keep-start load builds no closure.</summary>
        private void RememberGrid()
        {
            var snapshot = (byte[])_cells.Clone();
            Remember(_seed, _ =>
            {
                Array.Copy(snapshot, _cells, _cells.Length);
                Generation = 0;
            });
        }

        /// <summary>Paint one cell in place (0 to S − 1); does not reset the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            if (value >= _rule.States)
                throw new ArgumentException($"state {value} is past this rule's {_rule.States} states");
            _cells[y * Width + x] = value;
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family blank, 0 (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    SetCell(x, y, 0);
        }

        /// <summary>
        /// Random fill (spec/patterns.md "Editing a region"): the inclusive region becomes the soup
        /// of a world its size, alive cells state 1 — the cells a Life-like grid's random fill gives.
        /// <see cref="Generation"/> is untouched.
        /// </summary>
        public void FillRandom(int x0, int y0, int x1, int y1, double density, ulong seed)
            => Patterns.FillRandom(_cells, Width, Height, x0, y0, x1, y1, density, seed);

        /// <summary>
        /// Advance Selection (spec/patterns.md "Editing a region"): the inclusive region evolves
        /// <paramref name="n"/> generations as if nothing else existed, and is copied back. A
        /// canceled <paramref name="cancellationToken"/> stops it promptly with
        /// <see cref="OperationCanceledException"/> and leaves the world exactly as it was.
        /// </summary>
        public void AdvanceSelection(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: false, cancellationToken);

        /// <summary>Advance Outside: Advance Selection's mirror image, canceled the same way.</summary>
        public void AdvanceOutside(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: true, cancellationToken);

        byte[] IRegionWorld.Cells => _cells;

        void IRegionWorld.StepOnce(CancellationToken cancellationToken) => StepOnce(cancellationToken);

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>Frame per spec/ltl.md "Frames": state × 255 for two states, and the state
        /// itself for more (a color per state from the host's palette).</summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} bytes, got {frame.Length}");
            int scale = _rule.States == 2 ? 255 : 1;
            for (int i = 0; i < _cells.Length; i++)
                frame[i] = (byte)(_cells[i] * scale);
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
            byte[] padded = _padded, cells = _cells, next = _scratch;
            int[] sums = _sums, halfWidths = _halfWidths;
            _halo.Fill(cells, padded, 0);
            int r = _rule.Range, columns = _halo.Columns, rows = _halo.Rows, stride = columns + 1;
            bool box = _rule.Neighborhood == LtlNeighborhood.Moore;
            // The box: sums[(j + 1)·stride + i + 1] holds the alive cells of halo rows ≤ j and
            // columns ≤ i, row 0 and column 0 zero. The others: sums[j·stride + i] holds those of
            // halo row j and columns < i.
            for (int j = 0; j < rows; j++)
            {
                int here = (box ? j + 1 : j) * stride, above = j * stride, run = 0;
                sums[here] = 0;
                for (int i = 0; i < columns; i++)
                {
                    run += padded[j * columns + i] == 1 ? 1 : 0;
                    sums[here + i + 1] = box ? sums[above + i + 1] + run : run;
                }
            }
            int w = Width, h = Height, k = 2 * r + 1, states = _rule.States;
            int sMin = _rule.SurvivalMin, sMax = _rule.SurvivalMax, bMin = _rule.BirthMin, bMax = _rule.BirthMax;
            bool middle = _rule.Middle;
            for (int y = 0; y < h; y++)
            {
                // Polled each row, so even a big grid stops within a generation (spec/patterns.md
                // "Canceling"); Step's default token is never canceled.
                if (cancellationToken.IsCancellationRequested)
                    throw GridRegion.Canceled(cancellationToken, Generation);
                for (int x = 0; x < w; x++)
                {
                    int count;
                    if (box)
                    {
                        count = sums[(y + k) * stride + x + k] - sums[y * stride + x + k]
                            - sums[(y + k) * stride + x] + sums[y * stride + x];
                    }
                    else
                    {
                        count = 0;
                        for (int dy = -r; dy <= r; dy++)
                        {
                            int half = halfWidths[dy + r], row = (y + r + dy) * stride + x + r;
                            count += sums[row + half + 1] - sums[row - half];
                        }
                    }
                    byte state = cells[y * w + x];
                    if (!middle && state == 1)
                        count--;
                    int after;
                    if (state == 0)
                        after = count >= bMin && count <= bMax ? 1 : 0;
                    else if (state == 1)
                        after = count >= sMin && count <= sMax ? 1 : states > 2 ? 2 : 0;
                    else
                        after = state + 1 < states ? state + 1 : 0;
                    next[y * w + x] = (byte)after;
                }
            }
            _cells = next;
            _scratch = cells;
        }
    }
}
