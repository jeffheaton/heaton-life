using System;
using System.Collections.Generic;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// Wireworld, Silverman (spec/wireworld.md). States: 0 empty, 1 electron head,
    /// 2 electron tail, 3 conductor. head -> tail; tail -> conductor; conductor -> head
    /// iff exactly 1 or 2 Moore neighbors are heads; empty stays empty. State is a flat
    /// row-major byte grid; default boundary is dead (circuits rarely want a torus), and every
    /// topology of spec/topology.md is allowed, read through the grid's halo. Bit-exact tier.
    /// </summary>
    public sealed class Wireworld : IIndexedFrameSource, IRegionWorld
    {
        public const byte Empty = 0;
        public const byte Head = 1;
        public const byte Tail = 2;
        public const byte Conductor = 3;

        private readonly Halo _halo; // the cells past the edges (spec/topology.md "The halo")
        private readonly byte[] _padded; // the halo each generation reads
        private byte[] _cells;
        private byte[] _scratch;

        public int Width { get; }
        public int Height { get; }

        /// <summary>The topology's boundary: <see cref="Topology"/>.Boundary.</summary>
        public Boundary Boundary => Topology.Boundary;

        /// <summary>How the grid's edges join (spec/topology.md).</summary>
        public Topology Topology { get; }

        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        public Wireworld(int width, int height, Boundary boundary = Boundary.Dead)
            : this(width, height, new Topology(boundary))
        {
        }

        /// <summary>A world on any topology (spec/topology.md), seeded with the clock; throws
        /// <see cref="TopologyException"/> for a topology the size can't have.</summary>
        public Wireworld(int width, int height, Topology topology)
        {
            _halo = new Halo(topology, width, height);
            _padded = new byte[_halo.Length];
            Width = width;
            Height = height;
            Topology = topology;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            // The Python constructor's default init; throws (like Python) if the grid
            // is too small for a clock — build small circuits with the cells overload.
            SeedClock();
        }

        /// <summary>Construct directly from an explicit grid, mirroring Python's init=array.</summary>
        public Wireworld(int width, int height, ReadOnlySpan<byte> cells, Boundary boundary = Boundary.Dead)
            : this(width, height, cells, new Topology(boundary))
        {
        }

        /// <summary>A world on any topology from an explicit grid, mirroring Python's init=array.</summary>
        public Wireworld(int width, int height, ReadOnlySpan<byte> cells, Topology topology)
        {
            _halo = new Halo(topology, width, height);
            _padded = new byte[_halo.Length];
            Width = width;
            Height = height;
            Topology = topology;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            SetState(cells);
        }

        /// <summary>
        /// A rectangular conductor loop with one circulating electron (period = perimeter),
        /// same construction as the Python clock_loop.
        /// </summary>
        public void SeedClock(int margin = 2)
        {
            int w = Width, h = Height;
            if (w < 2 * margin + 4 || h < 2 * margin + 4)
                throw new ArgumentException($"grid {w}x{h} too small for a clock loop");
            Array.Clear(_cells, 0, _cells.Length);
            int top = margin, bottom = h - 1 - margin;
            int left = margin, right = w - 1 - margin;
            for (int x = left; x <= right; x++)
            {
                _cells[top * w + x] = Conductor;
                _cells[bottom * w + x] = Conductor;
            }
            for (int y = top; y <= bottom; y++)
            {
                _cells[y * w + left] = Conductor;
                _cells[y * w + right] = Conductor;
            }
            _cells[top * w + left + 1] = Tail;
            _cells[top * w + left + 2] = Head;
            Generation = 0;
            Remember(_seed, _ => { SeedClock(margin); });
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

        /// <summary>Load an explicit grid (row-major, Height*Width entries, values 0..3). A grid of
        /// the wrong size, or a value above 3, throws and changes nothing.</summary>
        public void SetState(ReadOnlySpan<byte> cells)
        {
            CheckCells(cells);
            cells.CopyTo(_cells);
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
        /// Load a grid at a given generation (spec/README.md "A world's state and its start").
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
            CheckCells(cells);
            cells.CopyTo(_cells);
            Generation = generation;
        }

        private void CheckCells(ReadOnlySpan<byte> cells)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            for (int i = 0; i < cells.Length; i++)
            {
                if (cells[i] > Conductor)
                    throw new ArgumentException($"wireworld cell value {cells[i]} > 3");
            }
        }

        /// <summary>
        /// Parse ASCII art: '.' empty, 'H' head, 'T' tail, '#' conductor, space empty;
        /// blank lines are skipped and short lines are right-padded with empty.
        /// </summary>
        public static (int Width, int Height, byte[] Cells) ParseText(string text)
        {
            var lines = new List<string>();
            foreach (string line in text.Split('\n'))
            {
                string trimmedEnd = line.TrimEnd('\r');
                if (trimmedEnd.Trim().Length > 0)
                    lines.Add(trimmedEnd);
            }
            if (lines.Count == 0)
                throw new ArgumentException("empty wireworld pattern");
            int width = 0;
            foreach (string line in lines)
                width = Math.Max(width, line.Length);
            var cells = new byte[lines.Count * width];
            for (int y = 0; y < lines.Count; y++)
            {
                for (int x = 0; x < lines[y].Length; x++)
                {
                    byte value = lines[y][x] switch
                    {
                        '.' => Empty,
                        ' ' => Empty,
                        'H' => Head,
                        'T' => Tail,
                        '#' => Conductor,
                        _ => throw new ArgumentException(
                            $"unknown wireworld character '{lines[y][x]}' at row {y}"),
                    };
                    cells[y * width + x] = value;
                }
            }
            return (width, lines.Count, cells);
        }

        /// <summary>Paint one cell in place (0..3); does not reset the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            if (value > Conductor)
                throw new ArgumentException($"wireworld cell value {value} > 3");
            _cells[y * Width + x] = value;
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family blank, Empty (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    SetCell(x, y, Empty);
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

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>
        /// Frame per spec/render.md: palette index = state * 85 — 0/85/170/255 hit the
        /// 'wireworld' colormap's anchors exactly.
        /// </summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} bytes, got {frame.Length}");
            for (int i = 0; i < _cells.Length; i++)
                frame[i] = (byte)(_cells[i] * 85);
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
            _halo.Fill(_cells, p, Empty);
            for (int y = 0; y < h; y++)
            {
                // Polled each row, so even a big grid stops within a generation (spec/patterns.md
                // "Canceling"); Step's default token is never canceled.
                if (cancellationToken.IsCancellationRequested)
                    throw GridRegion.Canceled(cancellationToken, Generation);
                int mid = (y + 1) * stride + 1; // the halo index of (0, y)
                for (int x = 0; x < w; x++)
                {
                    byte current = _cells[y * w + x];
                    byte next = current;
                    if (current == Head)
                    {
                        next = Tail;
                    }
                    else if (current == Tail)
                    {
                        next = Conductor;
                    }
                    else if (current == Conductor)
                    {
                        int heads = 0;
                        for (int dy = -1; dy <= 1; dy++)
                            for (int dx = -1; dx <= 1; dx++)
                            {
                                if ((dy != 0 || dx != 0) && p[mid + x + dy * stride + dx] == Head)
                                    heads++;
                            }
                        if (heads == 1 || heads == 2)
                            next = Head;
                    }
                    _scratch[y * w + x] = next;
                }
            }
            (_cells, _scratch) = (_scratch, _cells);
        }
    }
}
