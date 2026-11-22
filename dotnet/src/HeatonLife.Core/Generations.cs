using System;
using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Text;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// A Generations rule compiled (spec/generations.md "Rules"): its canonical text, its C
    /// states, and the Life-like rule whose table gives births and survival. It is also the cell
    /// function <see cref="MultiStateHashLife"/> runs. A rule is written <c>B…/S…/C…</c>, any
    /// Life-like rule of spec/rules.md before the count, or in survival/birth/count order
    /// (<c>345/2/4</c>); its canonical form is <c>B2/S345/C4</c>.
    /// The Python reference's heaton_life.ca.generations.GenerationsRule.
    /// </summary>
    public sealed class GenerationsRule : StateRule, IEquatable<GenerationsRule>
    {
        /// <summary>The fewest states a Generations rule has.</summary>
        public const int MinStates = 2;

        /// <summary>The most states a Generations rule has: a state is one byte.</summary>
        public const int MaxStates = 256;

        private readonly byte[] _table;
        private readonly int _states;
        private readonly string _canonical;

        private GenerationsRule(LifeRule life, int states)
        {
            Life = life;
            _states = states;
            _canonical = life.Canonical + "/C" + states.ToString(CultureInfo.InvariantCulture);
            _table = life.Table.ToArray();
        }

        public override string Canonical => _canonical;

        /// <summary>C: every cell is a state from 0 to C − 1.</summary>
        public override int States => _states;

        /// <summary>The Life-like rule whose table gives births and survival.</summary>
        public LifeRule Life { get; }

        /// <summary>True when a dead cell with no live neighbors is born.</summary>
        public bool HasB0 => Life.HasB0;

        /// <summary>The next state of <paramref name="c"/> (spec/generations.md "Respond +
        /// Integrate"): a dying cell moves one state on, C − 1 to 0; a dead or live one is
        /// born, survives or starts dying by the table over its live neighbors.</summary>
        public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
        {
            if (c >= 2)
                return (byte)(c + 1 < _states ? c + 1 : 0);
            int index = (nw == 1 ? 256 : 0) | (n == 1 ? 128 : 0) | (ne == 1 ? 64 : 0) | (w == 1 ? 32 : 0)
                | (c << 4) | (e == 1 ? 8 : 0) | (sw == 1 ? 4 : 0) | (s == 1 ? 2 : 0) | (se == 1 ? 1 : 0);
            if (_table[index] != 0)
                return 1;
            return (byte)(c == 0 || _states == 2 ? 0 : 2);
        }

        /// <summary>Compile a Generations rule; text that is none throws <see cref="ArgumentException"/>
        /// whose message carries the reason spec/generations.md "Reasons" gives.</summary>
        public static GenerationsRule Compile(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            if (!TryCompile(text, out GenerationsRule? rule, out string? reason))
                throw new ArgumentException($"invalid Generations rule '{text}': {reason} (spec/generations.md)", nameof(text));
            return rule;
        }

        /// <summary>Compile without throwing: true and the rule, or false and the reason of the
        /// first problem found (spec/generations.md "Reasons"). Null reads as empty text.</summary>
        public static bool TryCompile(
            string? text, [NotNullWhen(true)] out GenerationsRule? rule, [NotNullWhen(false)] out string? reason)
        {
            text ??= "";
            rule = null;
            int start = 0, end = text.Length;
            while (start < end && RuleString.IsSpace(text[start]))
                start++;
            while (end > start && RuleString.IsSpace(text[end - 1]))
                end--;
            string body = text.Substring(start, end - start);
            if (SurvivalBirthCount(body, out string? lifeText, out string? count))
            {
                if (!ParseCount(count!, out int states, out reason))
                    return false;
                rule = new GenerationsRule(RuleString.Compile(lifeText!), states);
                return true;
            }
            int slash = body.LastIndexOf('/');
            string tail = slash >= 0 ? body.Substring(slash + 1) : "";
            int at = 0;
            while (at < tail.Length && RuleString.IsSpace(tail[at]))
                at++;
            tail = tail.Substring(at);
            if (slash < 0 || tail.Length < 2 || (tail[0] != 'C' && tail[0] != 'c') || !AsciiDigits(tail, 1))
            {
                reason = "expected '/C' and the number of states at the end";
                return false;
            }
            if (!RuleString.TryCompile(body.Substring(0, slash), out LifeRule? life, out string? lifeReason))
            {
                reason = lifeReason!;
                return false;
            }
            if (!ParseCount(tail.Substring(1), out int count2, out reason))
                return false;
            rule = new GenerationsRule(life!, count2);
            return true;
        }

        /// <summary>Survival digits, birth digits and a count, each part as written and nothing
        /// else between: the <c>B…/S…</c> text the first two make, and the count.</summary>
        private static bool SurvivalBirthCount(string body, out string? lifeText, out string? count)
        {
            lifeText = count = null;
            int first = body.IndexOf('/');
            int second = first < 0 ? -1 : body.IndexOf('/', first + 1);
            if (second < 0 || body.IndexOf('/', second + 1) >= 0)
                return false;
            string survival = body.Substring(0, first), birth = body.Substring(first + 1, second - first - 1);
            string digits = body.Substring(second + 1);
            if (!RuleDigits(survival) || !RuleDigits(birth) || digits.Length == 0 || !AsciiDigits(digits, 0))
                return false;
            lifeText = "B" + Sorted(birth) + "/S" + Sorted(survival);
            count = digits;
            return true;
        }

        private static bool RuleDigits(string text)
        {
            foreach (char c in text)
            {
                if (c < '0' || c > '8')
                    return false;
            }
            return true;
        }

        private static bool AsciiDigits(string text, int from)
        {
            for (int i = from; i < text.Length; i++)
            {
                if (text[i] < '0' || text[i] > '9')
                    return false;
            }
            return true;
        }

        /// <summary>A side's digits sorted, repeats dropped.</summary>
        private static string Sorted(string digits)
        {
            var seen = new bool[9];
            foreach (char c in digits)
                seen[c - '0'] = true;
            var text = new StringBuilder();
            for (int d = 0; d < 9; d++)
            {
                if (seen[d])
                    text.Append((char)('0' + d));
            }
            return text.ToString();
        }

        /// <summary>The count of states from its ASCII digits, leading zeros allowed (step 4 of
        /// spec/generations.md "Reasons").</summary>
        private static bool ParseCount(string digits, out int states, [NotNullWhen(false)] out string? reason)
        {
            states = 0;
            foreach (char c in digits)
            {
                states = states * 10 + (c - '0');
                if (states > MaxStates)
                    break; // a longer number only grows
            }
            if (states < MinStates || states > MaxStates)
            {
                states = 0;
                reason = $"a Generations rule has {MinStates} to {MaxStates} states";
                return false;
            }
            reason = null;
            return true;
        }

        public bool Equals(GenerationsRule? other) => other != null && other._canonical == _canonical;

        public override bool Equals(object? obj) => obj is GenerationsRule other && Equals(other);

        public override int GetHashCode() => _canonical.GetHashCode();
    }

    /// <summary>
    /// The Generations family (spec/generations.md): a Life-like rule's births and survival with
    /// dying states. State is a flat row-major byte grid, index = y * Width + x: 0 dead, 1 alive,
    /// 2 … C − 1 dying. A dying cell counts as a dead neighbor and moves one state on each
    /// generation, C − 1 to 0; a live cell that doesn't survive starts dying. It runs on every
    /// topology (spec/topology.md) through the grid's halo, and <see cref="Step"/> and
    /// <see cref="WriteFrame"/> allocate nothing. Bit-exact tier.
    /// The Python reference's heaton_life.ca.generations.Generations.
    /// </summary>
    public sealed class Generations : IIndexedFrameSource, IRegionWorld
    {
        private readonly byte[] _table; // births and survival by 3×3 neighborhood index of live cells
        private readonly Halo _halo;
        private readonly byte[] _padded;
        private byte[] _cells;
        private byte[] _scratch;

        public int Width { get; }
        public int Height { get; }

        /// <summary>The rule's canonical form.</summary>
        public string Rule => CompiledRule.Canonical;

        /// <summary>The compiled rule: its C states and its Life-like births and survival.</summary>
        public GenerationsRule CompiledRule { get; }

        /// <summary>C: every cell is a state from 0 to C − 1.</summary>
        public int States => CompiledRule.States;

        /// <summary>The topology's boundary: <see cref="Topology"/>.Boundary.</summary>
        public Boundary Boundary => Topology.Boundary;

        /// <summary>How the grid's edges join (spec/topology.md).</summary>
        public Topology Topology { get; }

        public int Generation { get; private set; }

        public ReadOnlySpan<byte> State => _cells;

        public Generations(string rule, int width, int height, Boundary boundary = Boundary.Torus)
            : this(rule, width, height, new Topology(boundary))
        {
        }

        /// <summary>A world on any topology (spec/topology.md); throws
        /// <see cref="TopologyException"/> for one the size can't have, and
        /// <see cref="ArgumentException"/> for text that is no Generations rule.</summary>
        public Generations(string rule, int width, int height, Topology topology)
        {
            CompiledRule = GenerationsRule.Compile(rule);
            _table = CompiledRule.Life.Table.ToArray();
            _halo = new Halo(topology, width, height);
            _padded = new byte[_halo.Length];
            Width = width;
            Height = height;
            Topology = topology;
            _cells = new byte[width * height];
            _scratch = new byte[width * height];
            SeedSoup(0.35, 0); // the Python constructor's default init
        }

        /// <summary>Soup init as spec/lifelike.md's: PCG32 seq 0, row-major draws, alive (state 1)
        /// iff draw &lt; floor(density * 2^32).</summary>
        public void SeedSoup(double density, uint seed)
        {
            Seeding.Soup(_cells, density, seed);
            Generation = 0;
            Remember(seed, s => { Seeding.Soup(_cells, density, s); Generation = 0; });
        }

        /// <summary>Blob init as spec/lifelike.md's: soup restricted to a centered disk.</summary>
        public void SeedBlob(double density, uint seed, double radius = 0.25)
        {
            Seeding.Blob(_cells, Width, Height, density, radius, seed);
            Generation = 0;
            Remember(
                seed,
                s => { Seeding.Blob(_cells, Width, Height, density, radius, s); Generation = 0; });
        }

        /// <summary>Single init as spec/lifelike.md's: one live cell at the grid's middle.</summary>
        public void SeedSingle()
        {
            Seeding.Single(_cells, Width, Height);
            Generation = 0;
            Remember(_seed, _ => { Seeding.Single(_cells, Width, Height); Generation = 0; });
        }

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

        private void Check(ReadOnlySpan<byte> cells)
        {
            if (cells.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} cells, got {cells.Length}");
            foreach (byte cell in cells)
            {
                if (cell >= States)
                    throw new ArgumentException($"a Generations state is 0 to {States - 1} under {Rule}, not {cell}");
            }
        }

        /// <summary>Load an explicit grid of states 0 … C − 1 (row-major, Height*Width entries); it
        /// also becomes the start <see cref="Reset"/> returns to.</summary>
        public void SetState(ReadOnlySpan<byte> cells)
        {
            Check(cells);
            cells.CopyTo(_cells);
            Generation = 0;
            var snapshot = (byte[])_cells.Clone();
            Remember(_seed, _ =>
            {
                Array.Copy(snapshot, _cells, _cells.Length);
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
        /// Load a grid of states at a given generation (spec/README.md "A world's state and its
        /// start"). Without <paramref name="keepStart"/> it is <see cref="SetState(ReadOnlySpan{byte}, int)"/>;
        /// with it the start stays as it was and nothing is copied for it. A state of C or more
        /// throws and changes nothing.
        /// </summary>
        public void SetState(ReadOnlySpan<byte> cells, int generation, bool keepStart)
        {
            if (!keepStart)
            {
                SetState(cells, generation);
                return;
            }
            Check(cells);
            cells.CopyTo(_cells);
            Generation = generation;
        }

        /// <summary>Paint one cell in place (a state below C); does not reset the generation.</summary>
        public void SetCell(int x, int y, byte value)
        {
            if (x < 0 || x >= Width || y < 0 || y >= Height)
                throw new ArgumentOutOfRangeException($"cell ({x}, {y}) outside {Width}x{Height}");
            if (value >= States)
                throw new ArgumentOutOfRangeException(nameof(value), value, $"a Generations state is 0 to {States - 1} under {Rule}");
            _cells[y * Width + x] = value;
        }

        /// <summary>Restore a rectangle (inclusive corners) to the family blank, 0 (spec/patterns.md "Clear").</summary>
        public void ClearRect(int x0, int y0, int x1, int y1)
        {
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    SetCell(x, y, 0);
        }

        /// <summary>Advance Selection (spec/patterns.md "Editing a region"): the inclusive region
        /// evolves <paramref name="n"/> generations as if nothing else existed, and its region is
        /// copied back; the rest and <see cref="Generation"/> are untouched. A canceled
        /// <paramref name="cancellationToken"/> stops it promptly with
        /// <see cref="OperationCanceledException"/> and leaves the world exactly as it was
        /// (spec/patterns.md "Canceling").</summary>
        public void AdvanceSelection(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: false, cancellationToken);

        /// <summary>Advance Outside: the world with the region blank runs <paramref name="n"/>
        /// generations and everything outside the region is copied back. A canceled
        /// <paramref name="cancellationToken"/> stops it as it does Advance Selection.</summary>
        public void AdvanceOutside(
            int x0, int y0, int x1, int y1, int n = 1, CancellationToken cancellationToken = default)
            => GridRegion.Advance(this, Width, Height, x0, y0, x1, y1, n, outside: true, cancellationToken);

        byte[] IRegionWorld.Cells => _cells;

        void IRegionWorld.StepOnce(CancellationToken cancellationToken) => StepOnce(cancellationToken);

        /// <summary>Random fill (spec/patterns.md "Editing a region"): the region becomes the
        /// life-like soup of a world its size, each live cell state 1. <see cref="Generation"/>
        /// is untouched.</summary>
        public void FillRandom(int x0, int y0, int x1, int y1, double density, ulong seed)
            => Patterns.FillRandom(_cells, Width, Height, x0, y0, x1, y1, density, seed);

        public void Step(int n = 1)
        {
            for (int s = 0; s < n; s++)
                StepOnce();
            Generation += n;
        }

        /// <summary>Frame per spec/render.md: 0 for a dead cell, ⌊255 · (C − s) / (C − 1)⌋ for
        /// state s ≥ 1, so a live cell is 255 and the dying states fade.</summary>
        public void WriteFrame(byte[] frame)
        {
            if (frame.Length != _cells.Length)
                throw new ArgumentException($"expected {_cells.Length} bytes, got {frame.Length}");
            int c = States;
            for (int i = 0; i < _cells.Length; i++)
            {
                int s = _cells[i];
                frame[i] = s == 0 ? (byte)0 : (byte)((c - s) * 255 / (c - 1));
            }
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
            int w = Width, h = Height, stride = _halo.Columns, count = States;
            byte[] p = _padded;
            _halo.Fill(_cells, p, 0);
            for (int i = 0; i < p.Length; i++)
                p[i] = p[i] == 1 ? (byte)1 : (byte)0; // only a live cell counts; a dying one is dead
            byte dropped = (byte)(count > 2 ? 2 : 0);
            for (int y = 0; y < h; y++)
            {
                // Polled each row, so even a big grid stops within a generation (spec/patterns.md
                // "Canceling"); Step's default token is never canceled.
                if (cancellationToken.IsCancellationRequested)
                    throw GridRegion.Canceled(cancellationToken, Generation);
                int up = y * stride + 1, mid = up + stride, down = mid + stride, row = y * w;
                for (int x = 0; x < w; x++)
                {
                    int s = _cells[row + x];
                    byte next;
                    if (s >= 2)
                    {
                        next = (byte)(s + 1 < count ? s + 1 : 0);
                    }
                    else
                    {
                        // The neighborhood index of live cells (spec/rules.md): NW 256, N 128,
                        // NE 64, W 32, the cell 16, E 8, SW 4, S 2, SE 1.
                        int index = (p[up + x - 1] << 8) | (p[up + x] << 7) | (p[up + x + 1] << 6)
                            | (p[mid + x - 1] << 5) | (p[mid + x] << 4) | (p[mid + x + 1] << 3)
                            | (p[down + x - 1] << 2) | (p[down + x] << 1) | p[down + x + 1];
                        byte verdict = _table[index];
                        next = s == 0 ? verdict : verdict != 0 ? (byte)1 : dropped;
                    }
                    _scratch[row + x] = next;
                }
            }
            (_cells, _scratch) = (_scratch, _cells);
        }
    }
}
