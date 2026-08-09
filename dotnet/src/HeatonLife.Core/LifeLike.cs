using System;

namespace HeatonLife
{
    public enum Boundary
    {
        Torus,
        Dead,
    }

    /// <summary>
    /// Life-like cellular automaton (spec/lifelike.md). State is a flat row-major
    /// byte grid (0/1), index = y * Width + x — the same memory layout as the
    /// Python implementation and the conformance vectors. Bit-exact tier.
    /// </summary>
    public sealed class LifeLike : IIndexedFrameSource
    {
        private readonly bool[] _birth;
        private readonly bool[] _survive;
        private byte[] _cells;
        private byte[] _scratch;

        public int Width { get; }
        public int Height { get; }
        public string Rule { get; }
        public Boundary Boundary { get; }
        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        public LifeLike(
            string rule,
            int width,
            int height,
            Boundary boundary = Boundary.Torus)
        {
            Rule = RuleString.Canonical(rule);
            (_birth, _survive) = RuleString.Parse(rule);
            Width = width;
            Height = height;
            Boundary = boundary;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            SeedSoup(0.35, 0); // the Python constructor's default init
        }

        /// <summary>Soup init per spec: PCG32 seq 0, row-major draws, alive iff draw &lt; floor(density * 2^32).</summary>
        public void SeedSoup(double density, uint seed)
        {
            Seeding.Soup(_cells, density, seed);
            Generation = 0;
        }

        /// <summary>Blob init per spec: soup restricted to a centered disk (radius as a fraction of min dimension).</summary>
        public void SeedBlob(double density, uint seed, double radius = 0.25)
        {
            Seeding.Blob(_cells, Width, Height, density, radius, seed);
            Generation = 0;
        }

        /// <summary>Load an explicit 0/1 grid (row-major, Height*Width entries).</summary>
        public void SetState(ReadOnlySpan<byte> cells)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
                _cells[i] = (byte)(cells[i] > 0 ? 1 : 0);
            Generation = 0;
        }

        /// <summary>Restore a saved state at a given generation (catalog loads).</summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation)
        {
            SetState(cells);
            Generation = generation;
        }

        /// <summary>Paint one cell in place (0/1); does not reset the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            _cells[y * Width + x] = (byte)(value > 0 ? 1 : 0);
        }

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

        private void StepOnce()
        {
            int w = Width, h = Height;
            bool torus = Boundary == Boundary.Torus;
            for (int y = 0; y < h; y++)
            {
                int up = y - 1, down = y + 1;
                if (torus)
                {
                    up = (up + h) % h;
                    down = down % h;
                }
                for (int x = 0; x < w; x++)
                {
                    int left = x - 1, right = x + 1;
                    if (torus)
                    {
                        left = (left + w) % w;
                        right = right % w;
                    }
                    int count = 0;
                    count += Cell(left, up) + Cell(x, up) + Cell(right, up);
                    count += Cell(left, y) + Cell(right, y);
                    count += Cell(left, down) + Cell(x, down) + Cell(right, down);
                    byte current = _cells[y * w + x];
                    bool alive = current == 1 ? _survive[count] : _birth[count];
                    _scratch[y * w + x] = (byte)(alive ? 1 : 0);
                }
            }
            (_cells, _scratch) = (_scratch, _cells);
        }

        private int Cell(int x, int y)
        {
            if (Boundary == Boundary.Dead && (x < 0 || x >= Width || y < 0 || y >= Height))
                return 0;
            return _cells[y * Width + x];
        }
    }
}
