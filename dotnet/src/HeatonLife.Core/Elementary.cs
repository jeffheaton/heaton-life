using System;

namespace HeatonLife
{
    /// <summary>
    /// Elementary (Wolfram) cellular automaton (spec/elementary.md). State is the 1-D
    /// 0/1 tape, Width bytes; the diagram is the scrolling space-time record (Height
    /// rows, row-major 0/1) — the canonical way to *look* at these. Bit-exact tier.
    /// </summary>
    public sealed class Elementary : IIndexedFrameSource
    {
        private readonly byte[] _table; // indexed by (left<<2 | center<<1 | right)
        private byte[] _tape;
        private byte[] _scratch;
        private readonly byte[] _diagram;

        public int Rule { get; }
        public int Width { get; }
        public int Height { get; }
        public Boundary Boundary { get; }
        public int Generation { get; private set; }

        /// <summary>The current tape (Width bytes, 0/1).</summary>
        public ReadOnlySpan<byte> State => _tape;

        /// <summary>The space-time diagram (Height*Width bytes, row-major 0/1).</summary>
        public ReadOnlySpan<byte> Diagram => _diagram;

        public Elementary(int rule, int width, int height, Boundary boundary = Boundary.Torus)
        {
            if (rule < 0 || rule > 255)
                throw new ArgumentOutOfRangeException(nameof(rule), $"rule must be 0..255, got {rule}");
            Rule = rule;
            Width = width;
            Height = height;
            Boundary = boundary;
            _table = new byte[8];
            for (int i = 0; i < 8; i++)
                _table[i] = (byte)((rule >> i) & 1);
            _tape = new byte[width];
            _scratch = new byte[width];
            _diagram = new byte[width * height];
            SeedSingle();
        }

        /// <summary>Single live cell at Width / 2. Consumes no RNG draws.</summary>
        public void SeedSingle()
        {
            Array.Clear(_tape, 0, _tape.Length);
            _tape[Width / 2] = 1;
            ResetDiagram();
            Remember(_seed, _ =>
            {
                Array.Clear(_tape, 0, _tape.Length);
                _tape[Width / 2] = 1;
                ResetDiagram();
            });
        }

        /// <summary>Soup init per spec: one PCG32 draw per cell, alive iff draw &lt; floor(density * 2^32).</summary>
        public void SeedSoup(double density, uint seed)
        {
            Seeding.Soup(_tape, density, seed);
            ResetDiagram();
            Remember(seed, s => { Seeding.Soup(_tape, density, s); ResetDiagram(); });
        }

        // --- reset ---------------------------------------------------------------
        // How this world was last seeded, so Reset can replay it. The Python
        // reference keeps init/density/seed on its params object and re-dispatches
        // in reset(); a captured delegate is the same idea without a params type.
        // Every replay ends in ResetDiagram(), so the space-time record restarts
        // from the fresh tape exactly as it does after a first seeding.
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

        /// <summary>Load an explicit 0/1 tape (Width entries).</summary>
        public void SetState(ReadOnlySpan<byte> tape)
        {
            if (tape.Length != Width)
                throw new ArgumentException($"expected {Width} cells, got {tape.Length}");
            for (int i = 0; i < tape.Length; i++)
                _tape[i] = (byte)(tape[i] > 0 ? 1 : 0);
            ResetDiagram();
            var snapshot = _tape.Clone() as byte[];
            Remember(_seed, _ =>
            {
                Array.Copy(snapshot!, _tape, _tape.Length);
                ResetDiagram();
            });
        }

        /// <summary>
        /// Restore a saved tape at a given generation. The diagram restarts from the
        /// tape, placed in the row a world that had stepped to that generation would
        /// hold it in (so stepping on continues the picture downward rather than
        /// leaving a gap); the rows above it are gone. A host that saved the diagram
        /// should use the overload that takes it.
        /// </summary>
        public void SetState(ReadOnlySpan<byte> tape, int generation)
        {
            SetState(tape);
            int row = TapeRow(generation);
            if (row != 0)
            {
                Array.Clear(_diagram, 0, Width);
                Array.Copy(_tape, 0, _diagram, row * Width, Width);
            }
            Generation = generation;
        }

        /// <summary>
        /// Restore a saved tape together with its space-time diagram (Height*Width
        /// bytes, row-major 0/1) at a given generation. This is what a host that
        /// persists a world needs: the diagram is the record of the steps already
        /// taken and cannot be rebuilt from the tape (spec/elementary.md "State"), so
        /// a world restored from its tape alone reopens blank. Reset replays the tape
        /// from a fresh diagram, exactly as after the tape-only overload.
        /// </summary>
        public void SetState(ReadOnlySpan<byte> tape, ReadOnlySpan<byte> diagram, int generation)
        {
            if (diagram.Length != _diagram.Length)
                throw new ArgumentException(
                    $"expected {_diagram.Length} diagram cells, got {diagram.Length}");
            SetState(tape);
            for (int i = 0; i < diagram.Length; i++)
                _diagram[i] = (byte)(diagram[i] > 0 ? 1 : 0);
            Generation = generation;
        }

        /// <summary>The diagram row that holds the tape at a given generation.</summary>
        private int TapeRow(int generation) => Math.Min(Math.Max(generation, 0), Height - 1);

        private void ResetDiagram()
        {
            Array.Clear(_diagram, 0, _diagram.Length);
            Array.Copy(_tape, 0, _diagram, 0, Width);
            Generation = 0;
        }

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
        }

        /// <summary>Frame per spec/render.md: the space-time diagram, palette index = cell * 255.</summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame.Length != _diagram.Length)
                throw new ArgumentException($"expected {_diagram.Length} bytes, got {frame.Length}");
            for (int i = 0; i < _diagram.Length; i++)
                frame[i] = (byte)(_diagram[i] * 255);
        }

        /// <summary>Allocating convenience for <see cref="WriteFrame"/>.</summary>
        public byte[] Frame()
        {
            var frame = new byte[_diagram.Length];
            WriteFrame(frame);
            return frame;
        }

        private void StepOnce()
        {
            int w = Width;
            bool torus = Boundary == Boundary.Torus;
            for (int x = 0; x < w; x++)
            {
                int left = torus ? _tape[(x - 1 + w) % w] : (x > 0 ? _tape[x - 1] : 0);
                int right = torus ? _tape[(x + 1) % w] : (x < w - 1 ? _tape[x + 1] : 0);
                _scratch[x] = _table[(left << 2) | (_tape[x] << 1) | right];
            }
            (_tape, _scratch) = (_scratch, _tape);
            Generation++;
            int row = Generation;
            if (row < Height)
            {
                Array.Copy(_tape, 0, _diagram, row * w, w);
            }
            else // scroll up
            {
                Array.Copy(_diagram, w, _diagram, 0, (Height - 1) * w);
                Array.Copy(_tape, 0, _diagram, (Height - 1) * w, w);
            }
        }
    }
}
