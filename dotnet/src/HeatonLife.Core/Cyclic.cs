using System;
using System.Collections.Generic;

namespace HeatonLife
{
    public enum Neighborhood
    {
        Moore,
        VonNeumann,
    }

    /// <summary>
    /// Cyclic cellular automaton, Griffeath (spec/cyclic.md). Each cell advances to the
    /// successor state (mod States) when at least Threshold neighbors within Reach
    /// already hold that successor. State is a flat row-major byte grid in [0, States),
    /// toroidal by definition. Bit-exact tier.
    /// </summary>
    public sealed class Cyclic : IIndexedFrameSource
    {
        private readonly (int Dy, int Dx)[] _offsets;
        private byte[] _cells;
        private byte[] _scratch;

        public int States { get; }
        public int Threshold { get; }
        public int Reach { get; }
        public Neighborhood Neighborhood { get; }
        public int Width { get; }
        public int Height { get; }
        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        public Cyclic(
            int states,
            int width,
            int height,
            int threshold = 1,
            int reach = 1,
            Neighborhood neighborhood = Neighborhood.Moore)
        {
            if (states < 2)
                throw new ArgumentOutOfRangeException(nameof(states), $"states must be >= 2, got {states}");
            if (reach < 1)
                throw new ArgumentOutOfRangeException(nameof(reach), $"reach must be >= 1, got {reach}");
            States = states;
            Threshold = threshold;
            Reach = reach;
            Neighborhood = neighborhood;
            Width = width;
            Height = height;
            _offsets = BuildOffsets(reach, neighborhood);
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            SeedSoup(0); // the Python constructor's default init
        }

        private static (int, int)[] BuildOffsets(int reach, Neighborhood neighborhood)
        {
            var offsets = new List<(int, int)>();
            for (int dy = -reach; dy <= reach; dy++)
                for (int dx = -reach; dx <= reach; dx++)
                {
                    if (dy == 0 && dx == 0)
                        continue;
                    if (neighborhood == Neighborhood.VonNeumann && Math.Abs(dy) + Math.Abs(dx) > reach)
                        continue;
                    offsets.Add((dy, dx));
                }
            return offsets.ToArray();
        }

        /// <summary>Soup init per spec: one PCG32 draw per cell in row-major order, state = draw % States.</summary>
        public void SeedSoup(uint seed)
        {
            var rng = new Pcg32(seed);
            for (int i = 0; i < _cells.Length; i++)
                _cells[i] = (byte)(rng.NextU32() % (uint)States);
            Generation = 0;
            Remember(seed, s => SeedSoup(s));
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

        /// <summary>Load an explicit grid (row-major, Height*Width entries, values in [0, States)).</summary>
        public void SetState(ReadOnlySpan<byte> cells)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
            {
                if (cells[i] >= States)
                    throw new ArgumentException($"cell value {cells[i]} >= states ({States})");
                _cells[i] = cells[i];
            }
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

        /// <summary>Paint one cell in place (value in [0, States)); does not reset the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            if (value >= States)
                throw new ArgumentException($"cell value {value} >= states ({States})");
            _cells[y * Width + x] = value;
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family blank, 0 (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    SetCell(x, y, 0);
        }

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>Frame per spec/render.md: palette index = state * 255 / max(States - 1, 1).</summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} bytes, got {frame.Length}");
            int span = Math.Max(States - 1, 1);
            for (int i = 0; i < _cells.Length; i++)
                frame[i] = (byte)(_cells[i] * 255 / span);
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
            for (int y = 0; y < h; y++)
            {
                for (int x = 0; x < w; x++)
                {
                    byte current = _cells[y * w + x];
                    byte succ = (byte)((current + 1) % States);
                    int count = 0;
                    foreach (var (dy, dx) in _offsets)
                    {
                        int ny = (y + dy + h) % h;
                        int nx = (x + dx + w) % w;
                        if (_cells[ny * w + nx] == succ)
                            count++;
                    }
                    _scratch[y * w + x] = count >= Threshold ? succ : current;
                }
            }
            (_cells, _scratch) = (_scratch, _cells);
        }
    }
}
