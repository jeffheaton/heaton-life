using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Numerics;
using System.Text;
using System.Threading;

namespace HeatonLife
{
    /// <summary>What a <see cref="MultiStateHashLife"/> frame's pixels hold
    /// (spec/hashlife-multistate.md "View and render").</summary>
    public enum MultiStateRenderMode
    {
        /// <summary>The cell's state; zoomed out, the block's shown state: of its non-zero states,
        /// the first in the universe's <see cref="MultiStateHashLife.ZoomOrder"/>, or 0.</summary>
        State = 0,

        /// <summary>⌈255 · p / 4^s⌉ for a block of p non-zero cells (255 or 0 zoomed in).</summary>
        Density = 1,
    }

    /// <summary>
    /// An unbounded universe of a state rule, run by HashLife (spec/hashlife-multistate.md): the
    /// two-state <see cref="HashLife"/>'s algorithm on a quadtree whose leaves are 2 × 2 squares of
    /// states, its base case computed from the rule's cell function (<see cref="StateRule"/>) and
    /// memoized. Wireworld runs today; every family whose rule is a function of the 3 × 3 block
    /// plugs in through a <see cref="StateRule"/>. Coordinates, generations and populations are
    /// <see cref="BigInteger"/>s at this edge; cells sit where Macrocell files put them (cell
    /// (x, y) is tree position (x, y − 1)).
    ///
    /// Everything it shares with <see cref="HashLife"/> behaves as there: the editing box,
    /// snapshots (<see cref="HashLifeSnapshot"/>, refused across the two kinds), the memory budget,
    /// cancellation, and <see cref="LifeView"/> navigation. <see cref="Step"/> allocates nothing on
    /// the managed heap once warm, and <see cref="WriteFrame"/> renders into a caller's buffer. Not
    /// thread-safe: one thread drives a universe, and another may only cancel its step through the
    /// token. The Python reference's heaton_life.ca.hashlife.MultiStateHashLife.
    /// </summary>
    public sealed class MultiStateHashLife
    {
        /// <summary>Editing reaches cells with |x| ≤ EditLimit and |y| ≤ EditLimit.</summary>
        public const long EditLimit = HashLife.EditLimit;

        public const int DefaultMaxMemoryMb = HashLife.DefaultMaxMemoryMb;

        /// <summary>The smallest allowed budget, in MiB.</summary>
        public const int MinMemoryMb = HashLife.MinMemoryMb;

        /// <summary>The deepest tree (spec/hashlife.md "Depth").</summary>
        public const int MaxLevel = HashLife.MaxLevel;

        private static readonly BigInteger StepLimit = BigInteger.One << (MaxLevel - 2);

        private const int MinLevel = 2;     // the root is always an internal node
        private const int MinStepLevel = 4; // sub-steps check containment on great-grandchildren
        private const int WindowLevel = 31; // the four level-31 nodes around the origin hold the editing box
        private const int Phase2Bits = 30;  // render walks switch to long offsets below 2^30 blocks
        private const int SplitAfterCollections = 4;

        private readonly MultiStateStore _store;
        private StateRule _rule;
        private int _maxMemoryMb;
        private ulong _genLow;
        private BigInteger _genHigh; // multiples of 2^64
        private BigInteger? _genCache;
        private int _version;        // bumps whenever the root changes
        private int _popVersion = -1;
        private BigInteger _popCache;
        private int _boxVersion = -1;
        private CellBox? _boxCache;
        private byte[] _stepBits = new byte[16];
        private int _snapshotPrune = 64;
        private byte[] _zoomOrder = Array.Empty<byte>();
        private readonly Dictionary<int, long> _edgeMemo = new Dictionary<int, long>();
        private readonly Dictionary<int, BigInteger> _edgeMemoBig = new Dictionary<int, BigInteger>();

        // The edit window: the root (level ≤ 32) or the four level-31 nodes around the origin.
        private int _windowCount;
        private int _windowLevel;
        private readonly int[] _windowNode = new int[4];
        private readonly long[] _windowX = new long[4];
        private readonly long[] _windowY = new long[4];

        // An edit's rectangle in tree coordinates, and a paste's source.
        private long _rx0, _ry0, _rx1, _ry1;
        private Dictionary<long, int>? _blocks;
        private HashSet<long>?[]? _tiers;
        private HashLifePasteMode _mode;
        private byte[]? _extract;

        // A frame in progress (see WriteFrame).
        private byte[] _frame = Array.Empty<byte>();
        private int _frameWidth, _frameHeight;
        private int _fs, _fp;
        private long _fox, _foy, _ftw, _fth;
        private bool _fDensity;
        private HashLife.Coord _cx, _cy;
        private byte[] _coordBytesX = new byte[16], _coordBytesY = new byte[16];

        // Which cells of a leaf (bit i: cell i, NW NE SW SE) as a mask of their state bytes.
        private static readonly int[] ByteMasks = BuildByteMasks();

        /// <summary>A universe of the rule <paramref name="rule"/> names (spec/hashlife-multistate.md
        /// "Names"); an unknown name throws <see cref="ArgumentException"/>.</summary>
        public MultiStateHashLife(string rule = "WireWorld", int maxMemoryMb = DefaultMaxMemoryMb)
            : this(StateRules.Compile(rule), maxMemoryMb)
        {
        }

        /// <summary>A universe of a rule given as an object, checked by <see cref="StateRules.Check"/>.</summary>
        public MultiStateHashLife(StateRule rule, int maxMemoryMb = DefaultMaxMemoryMb)
        {
            _rule = StateRules.Check(rule);
            _store = new MultiStateStore(_rule, MaxNodesFor(maxMemoryMb), MinLevel);
            _maxMemoryMb = maxMemoryMb;
        }

        // -- configuration ----------------------------------------------------------------------

        /// <summary>The rule's canonical name. Setting a name keeps the cells and drops cached
        /// results, as <see cref="StateRule"/>'s setter does.</summary>
        public string Rule
        {
            get => _rule.Canonical;
            set => StateRule = StateRules.Compile(value);
        }

        /// <summary>
        /// The rule itself. Setting it keeps the cells and drops cached results; a rule with fewer
        /// states than the largest state present throws <see cref="ArgumentException"/> and changes
        /// nothing (spec/hashlife-multistate.md "Changing the rule").
        /// </summary>
        public StateRule StateRule
        {
            get => _rule;
            set
            {
                StateRule rule = StateRules.Check(value);
                if (ReferenceEquals(rule, _rule))
                    return;
                if (rule.States < _rule.States)
                {
                    int top = MaxState(_store.Root, _store.Level, new Dictionary<int, int>());
                    if (top >= rule.States)
                        throw new ArgumentException(
                            $"{rule.Canonical} has {rule.States} states and the universe holds state {top}", nameof(value));
                }
                _rule = rule;
                _store.UseRule(rule);
            }
        }

        /// <summary>The rule's number of states, S.</summary>
        public int States => _rule.States;

        /// <summary>The node store's budget in MiB: default 500, minimum 10. It changes speed,
        /// never results.</summary>
        public int MaxMemoryMb
        {
            get => _maxMemoryMb;
            set
            {
                _store.MaxNodes = MaxNodesFor(value);
                _maxMemoryMb = value;
            }
        }

        /// <summary>The store's estimated size in bytes (the budget's measure, not the process's).</summary>
        public long MemoryUsed => (long)_store.Live * MultiStateStore.BytesPerNode;

        public long NodeCount => _store.Live;

        /// <summary>Garbage collections run so far.</summary>
        public int Collections => _store.Collections;

        /// <summary>
        /// How a zoomed-out pixel chooses among the states it covers (spec/hashlife-multistate.md
        /// "View and render"): these states first, in this order, then every other non-zero state
        /// in increasing order. Distinct states from 1 to 255; default empty. The getter returns a
        /// copy, and setting copies.
        /// </summary>
        public byte[] ZoomOrder
        {
            get => (byte[])_zoomOrder.Clone();
            set
            {
                if (value == null)
                    throw new ArgumentNullException(nameof(value));
                var seen = new bool[256];
                foreach (byte state in value)
                {
                    if (state == 0 || seen[state])
                        throw new ArgumentException("a zoom order lists distinct states from 1 to 255", nameof(value));
                    seen[state] = true;
                }
                if (value.AsSpan().SequenceEqual(_zoomOrder))
                    return;
                _zoomOrder = (byte[])value.Clone();
                _store.SetOrder(_zoomOrder);
            }
        }

        private static int MaxNodesFor(int maxMemoryMb)
        {
            if (maxMemoryMb < MinMemoryMb)
                throw new ArgumentOutOfRangeException(
                    nameof(maxMemoryMb), maxMemoryMb, $"MaxMemoryMb must be at least {MinMemoryMb}");
            long nodes = ((long)maxMemoryMb << 20) / MultiStateStore.BytesPerNode;
            return (int)Math.Min(nodes, MultiStateStore.MaxCapacity);
        }

        // -- observables ------------------------------------------------------------------------

        public BigInteger Generation
        {
            get
            {
                if (_genCache == null)
                    _genCache = (_genHigh << 64) + _genLow;
                return _genCache.Value;
            }
        }

        /// <summary>The number of cells whose state is not 0.</summary>
        public BigInteger Population
        {
            get
            {
                if (_popVersion != _version)
                {
                    _popCache = _store.PopBig(_store.Root, _store.Level);
                    _popVersion = _version;
                }
                return _popCache;
            }
        }

        /// <summary>The inclusive extremes of the non-zero cells, or null for an empty universe.</summary>
        public CellBox? BoundingBox
        {
            get
            {
                if (_boxVersion != _version)
                {
                    _boxCache = ComputeBox();
                    _boxVersion = _version;
                }
                return _boxCache;
            }
        }

        /// <summary>Non-zero cells in the inclusive rectangle; any coordinates.</summary>
        public BigInteger PopulationIn(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            if (x1 < x0 || y1 < y0)
                return BigInteger.Zero;
            int k = _store.Level;
            BigInteger origin = -(BigInteger.One << (k - 1));
            return CountBig(_store.Root, k, origin, origin, x0, y0 - 1, x1, y1 - 1);
        }

        /// <summary>The inclusive extremes of the non-zero cells inside the inclusive rectangle, or
        /// null when it holds none; any coordinates.</summary>
        public CellBox? BoundingBoxIn(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            if (x1 < x0 || y1 < y0)
                return null;
            var s = _store;
            int k = s.Level;
            BigInteger origin = -(BigInteger.One << (k - 1));
            var found = new BigInteger[4];
            try
            {
                for (int edge = 0; edge < 4; edge++)
                {
                    _edgeMemo.Clear();
                    _edgeMemoBig.Clear();
                    BigInteger? extreme = ExtremeBig(s.Root, k, origin, origin, x0, y0 - 1, x1, y1 - 1, edge);
                    if (extreme == null)
                        return null;
                    found[edge] = extreme.Value;
                }
            }
            finally
            {
                _edgeMemo.Clear();
                _edgeMemoBig.Clear();
            }
            return new CellBox(found[0], found[2] + 1, found[1], found[3] + 1);
        }

        /// <summary>The state of cell (x, y), in the editing box.</summary>
        public byte GetCell(long x, long y)
        {
            HashLife.CheckBox(x, y, x, y);
            long ty = y - 1;
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
            {
                long size = 1L << _windowLevel;
                long rx = x - _windowX[w], ry = ty - _windowY[w];
                if (rx < 0 || rx >= size || ry < 0 || ry >= size)
                    continue;
                int n = _windowNode[w];
                int k = _windowLevel;
                while (k > 1)
                {
                    k--;
                    long half = 1L << k;
                    int q = 0;
                    if (rx >= half)
                    {
                        rx -= half;
                        q = 1;
                    }
                    if (ry >= half)
                    {
                        ry -= half;
                        q += 2;
                    }
                    n = _store.Kid(n, q);
                }
                return (byte)(_store.States(n) >> (8 * (int)(ry * 2 + rx)));
            }
            return 0;
        }

        /// <summary>The inclusive rectangle's states, (y1 − y0 + 1) × (x1 − x0 + 1) bytes, row-major.</summary>
        public byte[] GetRect(long x0, long y0, long x1, long y1)
        {
            HashLife.CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
            long width = x1 - x0 + 1, height = y1 - y0 + 1;
            if (width * height > int.MaxValue)
                throw new ArgumentOutOfRangeException(
                    null, $"({x0}, {y0})..({x1}, {y1}) holds more cells than one array can");
            var cells = new byte[width * height];
            SetBounds(x0, y0 - 1, x1, y1 - 1);
            _extract = cells;
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                ExtractIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            _extract = null;
            return cells;
        }

        // -- evolution --------------------------------------------------------------------------

        /// <summary>
        /// Advance exactly <paramref name="n"/> generations, 0 ≤ n &lt; 2^510, as
        /// <see cref="HashLife.Step"/> does: a larger n throws
        /// <see cref="ArgumentOutOfRangeException"/> before anything runs, a pattern spread too far
        /// throws <see cref="InvalidOperationException"/> at a sub-step boundary, a canceled token
        /// stops at a completed sub-step with <see cref="OperationCanceledException"/>, and a
        /// generation that cannot fit the budget throws <see cref="HashLifeMemoryException"/>.
        /// </summary>
        public void Step(BigInteger n, CancellationToken cancellationToken = default)
        {
            if (n.Sign < 0)
                throw new ArgumentOutOfRangeException(nameof(n), n, "cannot step backward");
            if (n.CompareTo(StepLimit) >= 0)
                throw new ArgumentOutOfRangeException(
                    nameof(n), n, $"a step of 2^{MaxLevel - 2} generations or more needs a tree deeper than level {MaxLevel}");
            if (n.IsZero)
                return;
            _store.Cancel = cancellationToken;
            try
            {
                if (n.CompareTo(ulong.MaxValue) <= 0)
                {
                    ulong bits = (ulong)n;
                    for (int j = 0; bits != 0; j++, bits >>= 1)
                    {
                        if ((bits & 1) != 0)
                            Advance(j, cancellationToken);
                    }
                }
                else
                {
                    int count = n.GetByteCount(isUnsigned: true);
                    if (_stepBits.Length < count)
                        _stepBits = new byte[count];
                    n.TryWriteBytes(_stepBits, out int written, isUnsigned: true);
                    for (int j = 0; j < written * 8; j++)
                    {
                        if (((_stepBits[j >> 3] >> (j & 7)) & 1) != 0)
                            Advance(j, cancellationToken);
                    }
                }
            }
            finally
            {
                _store.Cancel = default;
            }
        }

        /// <summary>Advance 2^j generations, collecting when three-quarters full and splitting a
        /// sub-step that cannot finish, as the two-state universe does.</summary>
        private void Advance(int j, CancellationToken cancellationToken)
        {
            if (cancellationToken.IsCancellationRequested)
                throw Canceled(cancellationToken);
            var s = _store;
            for (int attempt = 0; attempt < (j == 0 ? 2 : 1); attempt++)
            {
                if (s.Live > (long)s.MaxNodes * 3 / 4 || attempt > 0)
                    s.Collect(inFlight: false);
                try
                {
                    SubStep(j);
                    return;
                }
                catch (HashLifeStore.AbortException abort)
                {
                    if (abort.Canceled)
                        throw Canceled(cancellationToken);
                }
            }
            if (j == 0)
                throw new HashLifeMemoryException(
                    $"one generation does not fit in MaxMemoryMb = {_maxMemoryMb} (the pattern alone "
                    + $"needs about {MemoryUsed >> 20} MB); raise the budget");
            Advance(j - 1, cancellationToken);
            Advance(j - 1, cancellationToken);
        }

        private OperationCanceledException Canceled(CancellationToken cancellationToken)
            => new OperationCanceledException(
                $"canceled; the universe is at generation {Generation}", cancellationToken);

        private void SubStep(int j)
        {
            var s = _store;
            int need = Math.Max(j + 3, MinStepLevel);
            if (need > MaxLevel)
                throw new ArgumentOutOfRangeException(
                    nameof(j), $"a sub-step of 2^{j} generations is past the deepest supported tree");
            s.BeginGuard(j == 0 ? int.MaxValue : SplitAfterCollections);
            int root;
            try
            {
                while (s.Level < need || !Centered())
                {
                    if (s.Level >= MaxLevel)
                        throw new InvalidOperationException(
                            $"the pattern has spread too far to step 2^{j} generations within a level-{MaxLevel} "
                            + $"tree (spec/hashlife.md \"Depth\"); the universe is at generation {Generation}");
                    Expand();
                }
                root = s.Stepped(s.Root, s.Level, j);
            }
            finally
            {
                s.EndGuard();
            }
            s.Root = root;
            s.Level--;
            _version++;
            AddGeneration(j);
        }

        private void AddGeneration(int j)
        {
            if (j < 64)
            {
                ulong sum = _genLow + (1UL << j);
                if (sum < _genLow)
                    _genHigh += BigInteger.One;
                _genLow = sum;
            }
            else
            {
                _genHigh += BigInteger.One << (j - 64);
            }
            _genCache = null;
        }

        /// <summary>Set the generation counter to any integer ≥ 0; no cell changes.</summary>
        public void SetGeneration(BigInteger generation)
        {
            if (generation.Sign < 0)
                throw new ArgumentOutOfRangeException(nameof(generation), generation, "a generation is never negative");
            _genLow = (ulong)(generation & ulong.MaxValue);
            _genHigh = generation >> 64;
            _genCache = generation;
        }

        /// <summary>Every non-zero cell lies in the centered square of side 2^(k−2).</summary>
        private bool Centered()
        {
            var s = _store;
            int k = s.Level;
            int e2 = s.Empty(k - 2), e3 = s.Empty(k - 3);
            for (int q = 0; q < 4; q++)
            {
                int child = s.Kid(s.Root, q);
                int inward = 3 - q;
                for (int i = 0; i < 4; i++)
                {
                    if (i != inward && s.Kid(child, i) != e2)
                        return false;
                }
                int grand = s.Kid(child, inward);
                for (int i = 0; i < 4; i++)
                {
                    if (i != inward && s.Kid(grand, i) != e3)
                        return false;
                }
            }
            return true;
        }

        /// <summary>Wrap the root in a node twice its size, centered, with empty margins.</summary>
        private void Expand()
        {
            var s = _store;
            s.Root = ExpandNode(s.Root, s.Level);
            s.Level++;
            _version++;
        }

        /// <summary>Centered level-k node (k ≥ 1) inside a centered node twice its size; its
        /// intermediates ride the saved stack, so a guarded expansion may collect.</summary>
        private int ExpandNode(int root, int k)
        {
            var s = _store;
            int depth = s.StackDepth;
            int expanded;
            if (k == 1)
            {
                int states = s.States(root);
                int nw = s.Push(s.Leaf((states & 0xFF) << 24));
                int ne = s.Push(s.Leaf(((states >> 8) & 0xFF) << 16));
                int sw = s.Push(s.Leaf(((states >> 16) & 0xFF) << 8));
                int se = s.Push(s.Leaf((int)((uint)states >> 24)));
                expanded = s.Join(nw, ne, sw, se);
            }
            else
            {
                int e = s.Empty(k - 1);
                int a = s.Kid(root, 0), b = s.Kid(root, 1), c = s.Kid(root, 2), d = s.Kid(root, 3);
                int nw = s.Push(s.Join(e, e, e, a));
                int ne = s.Push(s.Join(e, e, b, e));
                int sw = s.Push(s.Join(e, c, e, e));
                int se = s.Push(s.Join(d, e, e, e));
                expanded = s.Join(nw, ne, sw, se);
            }
            s.StackDepth = depth;
            return expanded;
        }

        /// <summary>Free every node unreachable from the current state and the live snapshots.</summary>
        public void CollectGarbage() => _store.Collect(inFlight: false);

        // -- editing ----------------------------------------------------------------------------

        private void CheckState(int state, string name)
        {
            if (state < 0 || state >= _rule.States)
                throw new ArgumentOutOfRangeException(
                    name, state, $"state {state} is outside the rule's states 0..{_rule.States - 1}");
        }

        /// <summary>Set cell (x, y) to <paramref name="state"/>, 0 ≤ state &lt; S.</summary>
        public void SetCell(long x, long y, byte state)
        {
            CheckState(state, nameof(state));
            HashLife.CheckBox(x, y, x, y);
            Contain(x, y - 1, x, y - 1);
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
            {
                long size = 1L << _windowLevel;
                long rx = x - _windowX[w], ry = y - 1 - _windowY[w];
                if (rx >= 0 && rx < size && ry >= 0 && ry < size)
                    _windowNode[w] = SetIn(_windowNode[w], _windowLevel, rx, ry, state);
            }
            CloseWindow();
        }

        /// <summary>
        /// Land <paramref name="cells"/> (<paramref name="height"/> rows of <paramref name="width"/>
        /// states, each below S) with its top-left cell at (x, y). <see cref="HashLifePasteMode.Copy"/>
        /// writes every cell, <see cref="HashLifePasteMode.Or"/> the non-zero ones;
        /// <see cref="HashLifePasteMode.Xor"/> and <see cref="HashLifePasteMode.And"/> need every
        /// cell of <paramref name="cells"/>, and of the rectangle it lands on, to be 0 or 1.
        /// </summary>
        public void SetRect(
            long x, long y, ReadOnlySpan<byte> cells, int width, int height,
            HashLifePasteMode mode = HashLifePasteMode.Copy)
        {
            if (mode != HashLifePasteMode.Copy && mode != HashLifePasteMode.Or && mode != HashLifePasteMode.Xor
                && mode != HashLifePasteMode.And)
                throw new ArgumentOutOfRangeException(nameof(mode), mode, "unknown paste mode");
            if (width < 1 || height < 1)
                throw new ArgumentException($"cells must be a non-empty rectangle, got {width} x {height}");
            if (cells.Length != (long)width * height)
                throw new ArgumentException($"expected {(long)width * height} cells, got {cells.Length}");
            int top = 0;
            foreach (byte cell in cells)
                top = Math.Max(top, cell);
            CheckState(top, nameof(cells));
            HashLife.CheckBox(x, y, x + width - 1, y + height - 1);
            long tx = x, ty = y - 1;
            if (mode == HashLifePasteMode.Xor || mode == HashLifePasteMode.And)
            {
                if (top > 1)
                    throw new ArgumentException($"paste mode {mode} needs cells of states 0 and 1", nameof(cells));
                SetBounds(tx, ty, x + width - 1, ty + height - 1);
                Contain(_rx0, _ry0, _rx1, _ry1);
                OpenWindow();
                var memo = new Dictionary<int, int>();
                for (int w = 0; w < _windowCount; w++)
                {
                    if (MaxStateIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w], memo) > 1)
                        throw new ArgumentException(
                            $"paste mode {mode} needs the rectangle it lands on to hold states 0 and 1 only", nameof(cells));
                }
            }
            // The rectangle's leaves, densely, then the non-empty ones.
            long bx0 = tx >> 1, by0 = ty >> 1;
            int ox = (int)(tx - (bx0 << 1)), oy = (int)(ty - (by0 << 1));
            int columns = (ox + width + 1) >> 1, rows = (oy + height + 1) >> 1;
            var dense = new int[(long)columns * rows];
            for (int row = 0; row < height; row++)
            {
                int gy = oy + row;
                long line = (long)(gy >> 1) * columns;
                int shift = (gy & 1) * 16;
                for (int col = 0; col < width; col++)
                {
                    byte state = cells[row * width + col];
                    if (state != 0)
                    {
                        int gx = ox + col;
                        dense[line + (gx >> 1)] |= state << (shift + (gx & 1) * 8);
                    }
                }
            }
            var blocks = new Dictionary<long, int>();
            for (int r = 0; r < rows; r++)
            {
                for (int c = 0; c < columns; c++)
                {
                    int states = dense[(long)r * columns + c];
                    if (states != 0)
                        blocks[HashLife.BlockKey(bx0 + c, by0 + r)] = states;
                }
            }
            PasteBlocks(blocks, tx, ty, x + width - 1, ty + height - 1, mode);
        }

        /// <summary>Every cell of the inclusive rectangle becomes 0.</summary>
        public void ClearRect(long x0, long y0, long x1, long y1)
        {
            HashLife.CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                return;
            SetBounds(x0, y0 - 1, x1, y1 - 1);
            Contain(_rx0, _ry0, _rx1, _ry1);
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                _windowNode[w] = ClearIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            CloseWindow();
        }

        /// <summary>Every cell outside the inclusive rectangle becomes 0, wherever it lies. An empty
        /// rectangle is an error (<see cref="Clear"/> empties everything).</summary>
        public void ClearOutside(long x0, long y0, long x1, long y1)
        {
            CheckEditRect(x0, y0, x1, y1);
            SetBounds(x0, y0 - 1, x1, y1 - 1);
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                _windowNode[w] = KeepIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            var s = _store;
            if (_windowCount == 1)
            {
                s.Root = _windowNode[0];
            }
            else
            {
                // Everything outside the four windows lies outside the box, and so becomes 0.
                s.Root = s.Join(_windowNode[0], _windowNode[1], _windowNode[2], _windowNode[3]);
                s.Level = WindowLevel + 1;
            }
            _version++;
        }

        /// <summary>Turn the inclusive rectangle and its cells a quarter about its center, in place,
        /// and return the rectangle they land on (spec/hashlife.md "Rectangle transforms").</summary>
        public CellBox RotateRect(long x0, long y0, long x1, long y1, bool clockwise = true)
        {
            CheckEditRect(x0, y0, x1, y1);
            CellBox turned = Patterns.TurnedRect(x0, y0, x1, y1, clockwise);
            (BigInteger s, BigInteger d) = Patterns.TurnCenter(x0, y0, x1, y1);
            long sum = (long)s, diff = (long)d;
            long nx0 = (long)turned.X0, ny0 = (long)turned.Y0, nx1 = (long)turned.X1, ny1 = (long)turned.Y1;
            long dx = clockwise ? sum : 1 - diff;
            long dy = clockwise ? diff - 1 : sum;
            HashLife.CheckBox(nx0, ny0, nx1, ny1);
            MoveRect(x0, y0, x1, y1, nx0, ny0, nx1, ny1, clockwise ? TurnClockwise : TurnCounterClockwise, dx, dy);
            return turned;
        }

        /// <summary>Mirror the inclusive rectangle's cells in place: left-right or, with
        /// <paramref name="horizontal"/> false, top-bottom.</summary>
        public void FlipRect(long x0, long y0, long x1, long y1, bool horizontal = true)
        {
            CheckEditRect(x0, y0, x1, y1);
            if (horizontal)
                MoveRect(x0, y0, x1, y1, x0, y0, x1, y1, MirrorLeftRight, x0 + x1 + 1, 0);
            else
                MoveRect(x0, y0, x1, y1, x0, y0, x1, y1, MirrorTopBottom, 0, y0 + y1 - 1);
        }

        /// <summary>Evolve the inclusive rectangle <paramref name="n"/> generations as an isolated
        /// plane and clip the result to it; the outside and the generation are untouched. It throws
        /// what <see cref="Step"/> throws, and then leaves the universe exactly as it was.</summary>
        public void AdvanceSelection(
            long x0, long y0, long x1, long y1, BigInteger n, CancellationToken cancellationToken = default)
            => AdvanceRegion(x0, y0, x1, y1, n, outside: false, cancellationToken);

        /// <summary>Evolve everything outside the inclusive rectangle <paramref name="n"/>
        /// generations as if the rectangle held only 0 cells; the rectangle keeps its cells.</summary>
        public void AdvanceOutside(
            long x0, long y0, long x1, long y1, BigInteger n, CancellationToken cancellationToken = default)
            => AdvanceRegion(x0, y0, x1, y1, n, outside: true, cancellationToken);

        /// <summary>Every cell becomes 0; the generation stays.</summary>
        public void Clear()
        {
            _store.Root = _store.Empty(MinLevel);
            _store.Level = MinLevel;
            _version++;
        }

        // -- snapshots --------------------------------------------------------------------------

        /// <summary>The cells and generation now, in O(1); the nodes stay alive while it does.</summary>
        public HashLifeSnapshot Snapshot() => SnapshotAt(_store.Root, _store.Level, Generation, _rule.States);

        /// <summary>A snapshot of any tree in this universe's store whose states are all below
        /// <paramref name="states"/>, kept alive like any other.</summary>
        internal HashLifeSnapshot SnapshotAt(int root, int level, BigInteger generation, int states)
        {
            var snapshot = new HashLifeSnapshot(this, root, level, generation, states);
            List<WeakReference<HashLifeSnapshot>> live = _store.Snapshots;
            if (live.Count >= _snapshotPrune)
            {
                live.RemoveAll(weak => !weak.TryGetTarget(out HashLifeSnapshot? held) || held.Released);
                _snapshotPrune = Math.Max(64, 2 * live.Count);
            }
            live.Add(new WeakReference<HashLifeSnapshot>(snapshot));
            return snapshot;
        }

        /// <summary>Put the universe back at a snapshot of it. A snapshot of another universe, a
        /// released one, or one holding a state the rule lacks throws <see cref="ArgumentException"/>.</summary>
        public void Restore(HashLifeSnapshot snapshot)
        {
            CheckOwn(snapshot, nameof(snapshot));
            if (snapshot.Released)
                throw new ArgumentException("the snapshot was released and holds no cells", nameof(snapshot));
            CheckStates(snapshot, nameof(snapshot));
            _store.Root = snapshot.RootNode;
            _store.Level = snapshot.Level;
            SetGeneration(snapshot.Generation);
            _version++;
        }

        private void CheckOwn(HashLifeSnapshot snapshot, string name)
        {
            if (snapshot == null)
                throw new ArgumentNullException(name);
            if (!ReferenceEquals(snapshot.Owner, this))
                throw new ArgumentException("the snapshot belongs to another universe", name);
        }

        /// <summary>Throw when one of this universe's snapshots holds a state its rule lacks: only
        /// possible after a change to a rule of fewer states, so only then is the tree looked at.</summary>
        internal void CheckStates(HashLifeSnapshot snapshot, string name)
        {
            if (snapshot.States <= _rule.States)
                return;
            int top = MaxState(snapshot.RootNode, snapshot.Level, new Dictionary<int, int>());
            if (top >= _rule.States)
                throw new ArgumentException(
                    $"the snapshot holds state {top}, which {_rule.Canonical} doesn't have ({_rule.States} states)", name);
        }

        /// <summary>
        /// What <paramref name="snapshots"/> hold beyond the current state, in nodes
        /// (spec/hashlife-multistate.md "Snapshots"): the current state's own nodes, each
        /// snapshot's addition to the state's and the earlier snapshots' nodes, and their sum. A
        /// state's nodes are the node lines of its canonical Macrocell text, leaves included.
        /// </summary>
        public SnapshotFootprint MeasureSnapshots(IEnumerable<HashLifeSnapshot> snapshots)
        {
            if (snapshots == null)
                throw new ArgumentNullException(nameof(snapshots));
            var listed = new List<HashLifeSnapshot>(snapshots);
            foreach (HashLifeSnapshot snapshot in listed)
                CheckOwn(snapshot, nameof(snapshots));
            var seen = new HashSet<int>();
            var (root, level) = Minimal();
            long universeNodes = CountNew(root, level, seen);
            var added = new long[listed.Count];
            long nodes = 0;
            for (int i = 0; i < listed.Count; i++)
            {
                HashLifeSnapshot snapshot = listed[i];
                if (snapshot.Released)
                    continue;
                var (n, k) = Minimal(snapshot.RootNode, snapshot.Level);
                added[i] = CountNew(n, k, seen);
                nodes += added[i];
            }
            return new SnapshotFootprint(universeNodes, added, nodes, nodes * MultiStateStore.BytesPerNode);
        }

        private long CountNew(int root, int level, HashSet<int> seen)
        {
            var s = _store;
            long count = 0;
            var stack = new Stack<(int Node, int Level)>();
            stack.Push((root, level));
            while (stack.Count > 0)
            {
                var (n, k) = stack.Pop();
                if (n == s.Empty(k) || !seen.Add(n))
                    continue;
                count++;
                if (k > 1)
                {
                    for (int q = 0; q < 4; q++)
                        stack.Push((s.Kid(n, q), k - 1));
                }
            }
            return count;
        }

        // -- files ------------------------------------------------------------------------------

        /// <summary>RLE of either dialect; <c>#CXRLE Pos=x,y Gen=n</c> places it and sets the
        /// generation. <paramref name="rule"/> is the rule when the header names none (default
        /// WireWorld), and the rule its name matches.</summary>
        public static MultiStateHashLife FromRle(string text, StateRule? rule = null, int maxMemoryMb = DefaultMaxMemoryMb)
            => MultiStateFiles.ReadRle(text, rule, maxMemoryMb);

        /// <summary>Macrocell text, placed by tree coordinates (spec/macrocell.md "Multi-state files").</summary>
        public static MultiStateHashLife FromMacrocell(string text, StateRule? rule = null, int maxMemoryMb = DefaultMaxMemoryMb)
            => MultiStateMacrocell.Read(text, rule, maxMemoryMb);

        /// <summary>Macrocell bytes, gzip-compressed or not.</summary>
        public static MultiStateHashLife FromMacrocell(byte[] data, StateRule? rule = null, int maxMemoryMb = DefaultMaxMemoryMb)
            => MultiStateMacrocell.Read(data, rule, maxMemoryMb);

        /// <summary>A Macrocell or RLE file's bytes, gzip-compressed or not, recognized by content;
        /// <see cref="MultiStateFiles.ReadUniverse(byte[], StateRule, int)"/> gives its metadata too.</summary>
        public static MultiStateHashLife Load(byte[] data, StateRule? rule = null, int maxMemoryMb = DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return MultiStateFiles.ReadUniverse(data, rule, maxMemoryMb).Universe;
        }

        /// <summary>A Macrocell or RLE file read into this universe's own store as a snapshot, with
        /// its format, rule, metadata and a timeline's frames; a file that names no rule takes this
        /// universe's. The universe's state, rule and earlier snapshots stay as they were.</summary>
        public PatternSnapshot ReadSnapshot(byte[] data) => MultiStateFiles.ReadSnapshot(this, data);

        /// <summary>A Macrocell or RLE file's text read into this universe's store as a snapshot.</summary>
        public PatternSnapshot ReadSnapshot(string text) => MultiStateFiles.ReadSnapshot(this, text);

        /// <summary>RLE of the bounding box behind a <c>#CXRLE</c> line; inside the editing box, and
        /// states up to 24, only.</summary>
        public string ToRle() => MultiStateFiles.WriteRle(this, null);

        /// <summary>RLE with <paramref name="metadata"/>'s lines after the <c>#CXRLE</c> line.</summary>
        public string ToRle(PatternMetadata? metadata) => MultiStateFiles.WriteRle(this, metadata);

        /// <summary>The canonical Macrocell text: the whole state, any size, in one string.</summary>
        public string ToMacrocell() => MultiStateMacrocell.Write(this);

        /// <summary>The canonical Macrocell text with <paramref name="metadata"/>'s lines.</summary>
        public string ToMacrocell(PatternMetadata? metadata) => MultiStateMacrocell.Write(this, metadata);

        /// <summary>The bytes of a pattern file named <paramref name="fileName"/>, by its extension:
        /// <c>.rle</c>, <c>.mc</c>, or <c>.mc.gz</c>.</summary>
        public byte[] EncodeFile(string fileName) => EncodeFile(fileName, null);

        /// <summary>The bytes of a pattern file named <paramref name="fileName"/> with
        /// <paramref name="metadata"/>'s lines, as UTF-8 (ASCII unless the metadata isn't).</summary>
        public byte[] EncodeFile(string fileName, PatternMetadata? metadata)
        {
            if (fileName == null)
                throw new ArgumentNullException(nameof(fileName));
            var utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            string name = fileName.ToLowerInvariant();
            if (name.EndsWith(".mc.gz", StringComparison.Ordinal))
            {
                byte[] text = utf8.GetBytes(ToMacrocell(metadata));
                using var output = new MemoryStream();
                using (var gzip = new GZipStream(output, CompressionLevel.Optimal, leaveOpen: true))
                    gzip.Write(text, 0, text.Length);
                return output.ToArray();
            }
            if (name.EndsWith(".mc", StringComparison.Ordinal))
                return utf8.GetBytes(ToMacrocell(metadata));
            if (name.EndsWith(".rle", StringComparison.Ordinal))
                return utf8.GetBytes(ToRle(metadata));
            throw new ArgumentException($"unknown pattern extension for '{fileName}' (.rle, .mc, .mc.gz)", nameof(fileName));
        }

        // -- internals for the readers and writers ----------------------------------------------

        internal MultiStateStore Store => _store;

        internal void Adopt(int root, int level, BigInteger generation)
        {
            _store.Root = root;
            _store.Level = level;
            SetGeneration(generation);
            _version++;
        }

        /// <summary>A node line as a root of level ≥ 2, placed by tree coordinates: a lone leaf is
        /// the center of a level-2 root.</summary>
        internal (int Root, int Level) Place(int node, int level)
            => level == 1 ? (ExpandNode(node, 1), 2) : (node, level);

        /// <summary>Run <paramref name="fill"/> on an empty tree in this universe's store and give
        /// the tree it built, leaving the universe's own root, level and generation as they were.</summary>
        internal (int Root, int Level) Build(Action fill)
        {
            var s = _store;
            int root = s.Root, level = s.Level;
            BigInteger generation = Generation;
            s.Root = s.Empty(MinLevel);
            s.Level = MinLevel;
            _version++;
            try
            {
                fill();
                return (s.Root, s.Level);
            }
            finally
            {
                s.Root = root;
                s.Level = level;
                SetGeneration(generation);
                _version++;
            }
        }

        /// <summary>The smallest centered root (level ≥ 1) that holds every non-zero cell.</summary>
        internal (int Node, int Level) Minimal() => Minimal(_store.Root, _store.Level);

        /// <summary>The smallest centered root (level ≥ 1) holding every non-zero cell of (n, k).</summary>
        internal (int Node, int Level) Minimal(int n, int k)
        {
            var s = _store;
            while (k > 1)
            {
                int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
                if (k == 2)
                {
                    int la = s.States(a), lb = s.States(b), lc = s.States(c), ld = s.States(d);
                    // Each quarter may keep only its cell at the center: a's SE, b's SW, c's NE, d's NW.
                    if ((la & 0x00FFFFFF) != 0 || (lb & unchecked((int)0xFF00FFFF)) != 0
                        || (lc & unchecked((int)0xFFFF00FF)) != 0 || (ld & unchecked((int)0xFFFFFF00)) != 0)
                        break;
                }
                else
                {
                    int e = s.Empty(k - 2);
                    bool held = true;
                    for (int q = 0; q < 4 && held; q++)
                    {
                        int child = s.Kid(n, q);
                        for (int i = 0; i < 4; i++)
                        {
                            if (i != 3 - q && s.Kid(child, i) != e)
                                held = false;
                        }
                    }
                    if (!held)
                        break;
                }
                n = s.CenterOf(a, b, c, d, k);
                k--;
            }
            return (n, k);
        }

        /// <summary>Every non-empty leaf as (tree x, tree y, packed states); the non-zero cells must
        /// lie in the editing box.</summary>
        internal void CollectLeaves(List<(long X, long Y, int States)> leaves)
        {
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                CollectLeavesIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w], leaves);
        }

        private void CollectLeavesIn(int n, int k, long nx, long ny, List<(long X, long Y, int States)> leaves)
        {
            var s = _store;
            if (n == s.Empty(k))
                return;
            if (k == 1)
            {
                leaves.Add((nx, ny, s.States(n)));
                return;
            }
            long half = 1L << (k - 1);
            CollectLeavesIn(s.Kid(n, 0), k - 1, nx, ny, leaves);
            CollectLeavesIn(s.Kid(n, 1), k - 1, nx + half, ny, leaves);
            CollectLeavesIn(s.Kid(n, 2), k - 1, nx, ny + half, leaves);
            CollectLeavesIn(s.Kid(n, 3), k - 1, nx + half, ny + half, leaves);
        }

        /// <summary>Land leaves keyed by <see cref="HashLife.BlockKey"/> (2 × 2 blocks) over the
        /// inclusive tree rectangle (x0, y0)..(x1, y1), which lies in the editing box.</summary>
        internal void PasteBlocks(Dictionary<long, int> blocks, long x0, long y0, long x1, long y1, HashLifePasteMode mode)
        {
            Contain(x0, y0, x1, y1);
            OpenWindow();
            // Which aligned nodes hold source cells, per level below the window's top.
            var tiers = new HashSet<long>?[_windowLevel];
            for (int level = 2; level < _windowLevel; level++)
            {
                var tier = new HashSet<long>();
                int shift = level - 1;
                foreach (long key in blocks.Keys)
                {
                    long bx = key >> 32, by = (int)(uint)key;
                    tier.Add(HashLife.BlockKey(bx >> shift, by >> shift));
                }
                tiers[level] = tier;
            }
            SetBounds(x0, y0, x1, y1);
            _blocks = blocks;
            _tiers = tiers;
            _mode = mode;
            for (int w = 0; w < _windowCount; w++)
                _windowNode[w] = PasteIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            _blocks = null;
            _tiers = null;
            CloseWindow();
        }

        /// <summary>The largest state of level-k node n.</summary>
        internal int MaxState(int n, int k, Dictionary<int, int> memo)
        {
            var s = _store;
            if (k == 1)
            {
                int states = s.States(n);
                return Math.Max(Math.Max(states & 0xFF, (states >> 8) & 0xFF), Math.Max((states >> 16) & 0xFF, (int)((uint)states >> 24)));
            }
            if (n == s.Empty(k))
                return 0;
            if (memo.TryGetValue(n, out int hit))
                return hit;
            int top = 0;
            for (int q = 0; q < 4; q++)
                top = Math.Max(top, MaxState(s.Kid(n, q), k - 1, memo));
            memo[n] = top;
            return top;
        }

        // -- tree walks (tree coordinates: y one less than the cell's) --------------------------

        private static int[] BuildByteMasks()
        {
            var masks = new int[16];
            for (int cells = 0; cells < 16; cells++)
            {
                int mask = 0;
                for (int i = 0; i < 4; i++)
                {
                    if ((cells & (1 << i)) != 0)
                        mask |= 0xFF << (8 * i);
                }
                masks[cells] = mask;
            }
            return masks;
        }

        /// <summary>Which of a leaf's four cells at tree (nx, ny) lie in the bounds: bit i for cell
        /// i (NW, NE, SW, SE).</summary>
        private int LeafCells(long nx, long ny)
        {
            int cells = 0;
            for (int i = 0; i < 4; i++)
            {
                long x = nx + (i & 1), y = ny + (i >> 1);
                if (x >= _rx0 && x <= _rx1 && y >= _ry0 && y <= _ry1)
                    cells |= 1 << i;
            }
            return cells;
        }

        /// <summary>Expand the root until it holds the tree rectangle (or covers the whole box).</summary>
        private void Contain(long x0, long y0, long x1, long y1)
        {
            while (_store.Level <= WindowLevel)
            {
                long half = 1L << (_store.Level - 1);
                if (-half <= x0 && x1 < half && -half <= y0 && y1 < half)
                    return;
                Expand();
            }
        }

        private void OpenWindow()
        {
            var s = _store;
            int k = s.Level;
            if (k <= WindowLevel + 1)
            {
                _windowCount = 1;
                _windowLevel = k;
                _windowNode[0] = s.Root;
                _windowX[0] = _windowY[0] = -(1L << (k - 1));
                return;
            }
            _windowCount = 4;
            _windowLevel = WindowLevel;
            int steps = k - 1 - WindowLevel;
            for (int q = 0; q < 4; q++)
            {
                int n = s.Kid(s.Root, q);
                for (int i = 0; i < steps; i++)
                    n = s.Kid(n, 3 - q);
                _windowNode[q] = n;
                _windowX[q] = (q & 1) == 0 ? -(1L << WindowLevel) : 0;
                _windowY[q] = (q & 2) == 0 ? -(1L << WindowLevel) : 0;
            }
        }

        private void CloseWindow()
        {
            var s = _store;
            if (_windowCount == 1)
            {
                s.Root = _windowNode[0];
            }
            else
            {
                int k = s.Level;
                int a = Replace(s.Kid(s.Root, 0), k - 1, 3, _windowNode[0]);
                int b = Replace(s.Kid(s.Root, 1), k - 1, 2, _windowNode[1]);
                int c = Replace(s.Kid(s.Root, 2), k - 1, 1, _windowNode[2]);
                int d = Replace(s.Kid(s.Root, 3), k - 1, 0, _windowNode[3]);
                s.Root = s.Join(a, b, c, d);
            }
            _version++;
        }

        /// <summary>Node n (level k) with its descendant at level 31 down quadrant q replaced.</summary>
        private int Replace(int n, int k, int q, int inner)
        {
            if (k == WindowLevel)
                return inner;
            var s = _store;
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            switch (q)
            {
                case 0:
                    a = Replace(a, k - 1, q, inner);
                    break;
                case 1:
                    b = Replace(b, k - 1, q, inner);
                    break;
                case 2:
                    c = Replace(c, k - 1, q, inner);
                    break;
                default:
                    d = Replace(d, k - 1, q, inner);
                    break;
            }
            return s.Join(a, b, c, d);
        }

        private bool Disjoint(long nx, long ny, long size)
            => nx > _rx1 || nx + size <= _rx0 || ny > _ry1 || ny + size <= _ry0;

        private bool Covers(long nx, long ny, long size)
            => _rx0 <= nx && nx + size - 1 <= _rx1 && _ry0 <= ny && ny + size - 1 <= _ry1;

        private int SetIn(int n, int k, long x, long y, byte state)
        {
            var s = _store;
            if (k == 1)
            {
                int shift = 8 * (int)(y * 2 + x);
                return s.Leaf((s.States(n) & ~(0xFF << shift)) | (state << shift));
            }
            long half = 1L << (k - 1);
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            if (y < half)
            {
                if (x < half)
                    a = SetIn(a, k - 1, x, y, state);
                else
                    b = SetIn(b, k - 1, x - half, y, state);
            }
            else if (x < half)
            {
                c = SetIn(c, k - 1, x, y - half, state);
            }
            else
            {
                d = SetIn(d, k - 1, x - half, y - half, state);
            }
            return s.Join(a, b, c, d);
        }

        private int ClearIn(int n, int k, long nx, long ny)
        {
            var s = _store;
            long size = 1L << k;
            int e = s.Empty(k);
            if (n == e || Disjoint(nx, ny, size))
                return n;
            if (Covers(nx, ny, size))
                return e;
            if (k == 1)
                return s.Leaf(s.States(n) & ~ByteMasks[LeafCells(nx, ny)]);
            long half = size >> 1;
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            return s.Join(
                ClearIn(a, k - 1, nx, ny),
                ClearIn(b, k - 1, nx + half, ny),
                ClearIn(c, k - 1, nx, ny + half),
                ClearIn(d, k - 1, nx + half, ny + half));
        }

        private int PasteIn(int n, int k, long nx, long ny)
        {
            long size = 1L << k;
            if (Disjoint(nx, ny, size))
                return n;
            var s = _store;
            if (k == 1)
            {
                int old = s.States(n);
                _blocks!.TryGetValue(HashLife.BlockKey(nx >> 1, ny >> 1), out int src);
                int mask = ByteMasks[LeafCells(nx, ny)];
                int states;
                switch (_mode)
                {
                    case HashLifePasteMode.Copy:
                        states = (old & ~mask) | src;
                        break;
                    case HashLifePasteMode.Or:
                        states = old;
                        for (int i = 0; i < 4; i++)
                        {
                            int bytes = 0xFF << (8 * i);
                            if ((src & bytes) != 0)
                                states = (states & ~bytes) | (src & bytes);
                        }
                        break;
                    case HashLifePasteMode.Xor:
                        states = old ^ src;
                        break;
                    default: // And: in the rectangle only the source's cells stay (every cell 0 or 1)
                        states = old & (src | ~mask);
                        break;
                }
                return s.Leaf(states);
            }
            HashSet<long>? tier = k < _tiers!.Length ? _tiers[k] : null;
            if (tier != null && !tier.Contains(HashLife.BlockKey(nx >> k, ny >> k)))
            {
                // No source cells below: copy and and clear the rectangle here, or and xor keep it.
                return _mode == HashLifePasteMode.Copy || _mode == HashLifePasteMode.And ? ClearIn(n, k, nx, ny) : n;
            }
            long half = size >> 1;
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            return s.Join(
                PasteIn(a, k - 1, nx, ny),
                PasteIn(b, k - 1, nx + half, ny),
                PasteIn(c, k - 1, nx, ny + half),
                PasteIn(d, k - 1, nx + half, ny + half));
        }

        /// <summary>The largest state of node n's cells inside the bounds (0 when none).</summary>
        private int MaxStateIn(int n, int k, long nx, long ny, Dictionary<int, int> memo)
        {
            var s = _store;
            long size = 1L << k;
            if (n == s.Empty(k) || Disjoint(nx, ny, size))
                return 0;
            if (Covers(nx, ny, size))
                return MaxState(n, k, memo);
            if (k == 1)
            {
                int states = s.States(n) & ByteMasks[LeafCells(nx, ny)];
                return Math.Max(Math.Max(states & 0xFF, (states >> 8) & 0xFF), Math.Max((states >> 16) & 0xFF, (int)((uint)states >> 24)));
            }
            long half = size >> 1;
            int top = 0;
            for (int q = 0; q < 4; q++)
                top = Math.Max(top, MaxStateIn(s.Kid(n, q), k - 1, nx + ((q & 1) != 0 ? half : 0), ny + ((q & 2) != 0 ? half : 0), memo));
            return top;
        }

        /// <summary>The inclusive rectangle's states anywhere on the plane, for readers that
        /// measured it first.</summary>
        internal byte[] CellsAnywhere(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            BigInteger w = x1 - x0 + 1, h = y1 - y0 + 1;
            if (w.Sign <= 0 || h.Sign <= 0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
            if (w * h > int.MaxValue)
                throw new ArgumentOutOfRangeException(null, $"({x0}, {y0})..({x1}, {y1}) holds more cells than one array can");
            var cells = new byte[(int)(w * h)];
            int k = _store.Level;
            BigInteger origin = -(BigInteger.One << (k - 1));
            ExtractBig(_store.Root, k, origin - x0, origin - (y0 - 1), (long)w, (long)h, cells);
            return cells;
        }

        private void ExtractBig(int n, int k, BigInteger rx, BigInteger ry, long w, long h, byte[] cells)
        {
            var s = _store;
            if (n == s.Empty(k))
                return;
            BigInteger size = BigInteger.One << k;
            if (rx >= w || rx + size <= 0 || ry >= h || ry + size <= 0)
                return;
            if (k <= 31)
            {
                ExtractSmall(n, k, (long)rx, (long)ry, w, h, cells);
                return;
            }
            BigInteger half = size >> 1;
            ExtractBig(s.Kid(n, 0), k - 1, rx, ry, w, h, cells);
            ExtractBig(s.Kid(n, 1), k - 1, rx + half, ry, w, h, cells);
            ExtractBig(s.Kid(n, 2), k - 1, rx, ry + half, w, h, cells);
            ExtractBig(s.Kid(n, 3), k - 1, rx + half, ry + half, w, h, cells);
        }

        private void ExtractSmall(int n, int k, long rx, long ry, long w, long h, byte[] cells)
        {
            var s = _store;
            long size = 1L << k;
            if (n == s.Empty(k) || rx >= w || rx + size <= 0 || ry >= h || ry + size <= 0)
                return;
            if (k == 1)
            {
                int states = s.States(n);
                for (int i = 0; i < 4; i++)
                {
                    long x = rx + (i & 1), y = ry + (i >> 1);
                    if (x >= 0 && x < w && y >= 0 && y < h)
                        cells[y * w + x] = (byte)(states >> (8 * i));
                }
                return;
            }
            long half = size >> 1;
            ExtractSmall(s.Kid(n, 0), k - 1, rx, ry, w, h, cells);
            ExtractSmall(s.Kid(n, 1), k - 1, rx + half, ry, w, h, cells);
            ExtractSmall(s.Kid(n, 2), k - 1, rx, ry + half, w, h, cells);
            ExtractSmall(s.Kid(n, 3), k - 1, rx + half, ry + half, w, h, cells);
        }

        private void ExtractIn(int n, int k, long nx, long ny)
        {
            var s = _store;
            long size = 1L << k;
            if (n == s.Empty(k) || Disjoint(nx, ny, size))
                return;
            if (k == 1)
            {
                int states = s.States(n);
                long width = _rx1 - _rx0 + 1;
                byte[] cells = _extract!;
                for (int i = 0; i < 4; i++)
                {
                    long x = nx + (i & 1), y = ny + (i >> 1);
                    if (x >= _rx0 && x <= _rx1 && y >= _ry0 && y <= _ry1)
                        cells[(y - _ry0) * width + (x - _rx0)] = (byte)(states >> (8 * i));
                }
                return;
            }
            long half = size >> 1;
            ExtractIn(s.Kid(n, 0), k - 1, nx, ny);
            ExtractIn(s.Kid(n, 1), k - 1, nx + half, ny);
            ExtractIn(s.Kid(n, 2), k - 1, nx, ny + half);
            ExtractIn(s.Kid(n, 3), k - 1, nx + half, ny + half);
        }

        private BigInteger CountBig(
            int n, int k, BigInteger nx, BigInteger ny, BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            var s = _store;
            if (n == s.Empty(k))
                return BigInteger.Zero;
            BigInteger size = BigInteger.One << k;
            if (nx > x1 || nx + size <= x0 || ny > y1 || ny + size <= y0)
                return BigInteger.Zero;
            if (x0 <= nx && nx + size - 1 <= x1 && y0 <= ny && ny + size - 1 <= y1)
                return s.PopBig(n, k);
            if (k <= 31)
            {
                long rx0 = (long)BigInteger.Max(x0 - nx, BigInteger.Zero);
                long ry0 = (long)BigInteger.Max(y0 - ny, BigInteger.Zero);
                long rx1 = (long)BigInteger.Min(x1 - nx, size - 1);
                long ry1 = (long)BigInteger.Min(y1 - ny, size - 1);
                return CountLong(n, k, rx0, ry0, rx1, ry1);
            }
            BigInteger half = size >> 1;
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            return CountBig(a, k - 1, nx, ny, x0, y0, x1, y1)
                + CountBig(b, k - 1, nx + half, ny, x0, y0, x1, y1)
                + CountBig(c, k - 1, nx, ny + half, x0, y0, x1, y1)
                + CountBig(d, k - 1, nx + half, ny + half, x0, y0, x1, y1);
        }

        /// <summary>Non-zero cells of level-k node n (k ≤ 31) in the inclusive rectangle relative
        /// to its origin, which lies inside it.</summary>
        private long CountLong(int n, int k, long x0, long y0, long x1, long y1)
        {
            var s = _store;
            if (n == s.Empty(k))
                return 0;
            long size = 1L << k;
            if (x0 == 0 && y0 == 0 && x1 == size - 1 && y1 == size - 1)
                return s.PopLong(n, k);
            if (k == 1)
            {
                int states = s.States(n);
                int count = 0;
                for (int i = 0; i < 4; i++)
                {
                    long x = i & 1, y = i >> 1;
                    if (x >= x0 && x <= x1 && y >= y0 && y <= y1 && ((states >> (8 * i)) & 0xFF) != 0)
                        count++;
                }
                return count;
            }
            long half = size >> 1;
            long total = 0;
            for (int q = 0; q < 4; q++)
            {
                long qx = (q & 1) * half, qy = (q >> 1) * half;
                long cx0 = Math.Max(x0, qx) - qx, cx1 = Math.Min(x1, qx + half - 1) - qx;
                long cy0 = Math.Max(y0, qy) - qy, cy1 = Math.Min(y1, qy + half - 1) - qy;
                if (cx0 <= cx1 && cy0 <= cy1)
                    total += CountLong(s.Kid(n, q), k - 1, cx0, cy0, cx1, cy1);
            }
            return total;
        }

        // -- rectangle tools (spec/hashlife.md "Rectangle transforms", "Advancing part of the universe")

        private const int TurnClockwise = 0, TurnCounterClockwise = 1, MirrorLeftRight = 2, MirrorTopBottom = 3;

        // Which old child lands in each new quadrant (NW, NE, SW, SE) of a node turned or mirrored
        // about its own center, by the kinds above; a leaf's four states move the same way.
        private static readonly int[][] TransformOrder =
        {
            new[] { 2, 0, 3, 1 },
            new[] { 1, 3, 0, 2 },
            new[] { 1, 0, 3, 2 },
            new[] { 2, 3, 0, 1 },
        };

        private static void CheckEditRect(long x0, long y0, long x1, long y1)
        {
            HashLife.CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
        }

        private void SetBounds(long x0, long y0, long x1, long y1)
        {
            _rx0 = x0;
            _ry0 = y0;
            _rx1 = x1;
            _ry1 = y1;
        }

        private void MoveRect(
            long x0, long y0, long x1, long y1, long nx0, long ny0, long nx1, long ny1, int kind, long dx, long dy)
        {
            const int k = WindowLevel + 1;
            const long origin = -(1L << (k - 1));
            int box = OpenBox();
            SetBounds(x0, y0 - 1, x1, y1 - 1);
            int lifted = KeepIn(box, k, origin, origin);
            int rest = ClearIn(box, k, origin, origin);
            int moved = Shifted(Transform(lifted, k, kind, new Dictionary<int, int>()), k, dx, dy);
            SetBounds(nx0, ny0 - 1, nx1, ny1 - 1);
            CloseBox(SpliceIn(moved, rest, k, origin, origin));
        }

        private int OpenBox()
        {
            while (_store.Level < WindowLevel + 2)
                Expand();
            OpenWindow();
            return _store.Join(_windowNode[0], _windowNode[1], _windowNode[2], _windowNode[3]);
        }

        private void CloseBox(int box)
        {
            for (int q = 0; q < 4; q++)
                _windowNode[q] = _store.Kid(box, q);
            CloseWindow();
        }

        private void WindowsOf(int root, int level, int[] windows)
        {
            var s = _store;
            int steps = level - 1 - WindowLevel;
            for (int q = 0; q < 4; q++)
            {
                int n = s.Kid(root, q);
                for (int i = 0; i < steps; i++)
                    n = s.Kid(n, 3 - q);
                windows[q] = n;
            }
        }

        private void AdvanceRegion(
            long x0, long y0, long x1, long y1, BigInteger n, bool outside, CancellationToken cancellationToken)
        {
            CheckEditRect(x0, y0, x1, y1);
            if (n.Sign < 0)
                throw new ArgumentOutOfRangeException(nameof(n), n, "cannot advance backward");
            if (n.CompareTo(StepLimit) >= 0)
                throw new ArgumentOutOfRangeException(
                    nameof(n), n, $"a step of 2^{MaxLevel - 2} generations or more needs a tree deeper than level {MaxLevel}");
            HashLifeSnapshot saved = Snapshot();
            var s = _store;
            int grown, grownLevel;
            try
            {
                if (outside)
                    ClearRect(x0, y0, x1, y1);
                else
                    ClearOutside(x0, y0, x1, y1);
                try
                {
                    Step(n, cancellationToken);
                }
                catch
                {
                    Restore(saved);
                    throw;
                }
                grown = s.Root;
                grownLevel = s.Level;
                Restore(saved);
            }
            finally
            {
                saved.Release();
            }
            int level = Math.Max(Math.Max(grownLevel, s.Level), WindowLevel + 2);
            while (s.Level < level)
                Expand();
            while (grownLevel < level)
                grown = ExpandNode(grown, grownLevel++);
            var inside = new int[4];
            if (outside)
            {
                WindowsOf(s.Root, level, inside);
                s.Root = grown;
            }
            else
            {
                WindowsOf(grown, level, inside);
            }
            OpenWindow();
            SetBounds(x0, y0 - 1, x1, y1 - 1);
            for (int w = 0; w < 4; w++)
                _windowNode[w] = SpliceIn(inside[w], _windowNode[w], WindowLevel, _windowX[w], _windowY[w]);
            CloseWindow();
        }

        private int KeepIn(int n, int k, long nx, long ny)
        {
            var s = _store;
            long size = 1L << k;
            int e = s.Empty(k);
            if (n == e || Disjoint(nx, ny, size))
                return e;
            if (Covers(nx, ny, size))
                return n;
            if (k == 1)
                return s.Leaf(s.States(n) & ByteMasks[LeafCells(nx, ny)]);
            long half = size >> 1;
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            return s.Join(
                KeepIn(a, k - 1, nx, ny),
                KeepIn(b, k - 1, nx + half, ny),
                KeepIn(c, k - 1, nx, ny + half),
                KeepIn(d, k - 1, nx + half, ny + half));
        }

        private int SpliceIn(int inside, int outside, int k, long nx, long ny)
        {
            if (inside == outside)
                return inside;
            long size = 1L << k;
            if (Disjoint(nx, ny, size))
                return outside;
            if (Covers(nx, ny, size))
                return inside;
            var s = _store;
            if (k == 1)
            {
                int mask = ByteMasks[LeafCells(nx, ny)];
                return s.Leaf((s.States(inside) & mask) | (s.States(outside) & ~mask));
            }
            long half = size >> 1;
            int ia = s.Kid(inside, 0), ib = s.Kid(inside, 1), ic = s.Kid(inside, 2), id = s.Kid(inside, 3);
            int oa = s.Kid(outside, 0), ob = s.Kid(outside, 1), oc = s.Kid(outside, 2), od = s.Kid(outside, 3);
            return s.Join(
                SpliceIn(ia, oa, k - 1, nx, ny),
                SpliceIn(ib, ob, k - 1, nx + half, ny),
                SpliceIn(ic, oc, k - 1, nx, ny + half),
                SpliceIn(id, od, k - 1, nx + half, ny + half));
        }

        private int Transform(int n, int k, int kind, Dictionary<int, int> memo)
        {
            if (memo.TryGetValue(n, out int hit))
                return hit;
            var s = _store;
            int[] order = TransformOrder[kind];
            int r;
            if (k == 1)
            {
                int states = s.States(n);
                int turned = 0;
                for (int i = 0; i < 4; i++)
                    turned |= ((states >> (8 * order[i])) & 0xFF) << (8 * i);
                r = s.Leaf(turned);
            }
            else if (n == s.Empty(k))
            {
                r = n;
            }
            else
            {
                int nw = Transform(s.Kid(n, order[0]), k - 1, kind, memo);
                int ne = Transform(s.Kid(n, order[1]), k - 1, kind, memo);
                int sw = Transform(s.Kid(n, order[2]), k - 1, kind, memo);
                int se = Transform(s.Kid(n, order[3]), k - 1, kind, memo);
                r = s.Join(nw, ne, sw, se);
            }
            memo[n] = r;
            return r;
        }

        private int Shifted(int n, int k, long dx, long dy)
        {
            var s = _store;
            int big = ExpandNode(n, k);
            long half = 1L << (k - 1);
            return Crop(
                k, s.Kid(big, 0), s.Kid(big, 1), s.Kid(big, 2), s.Kid(big, 3), half - dx, half - dy,
                new Dictionary<(int, int, int, int, int, long, long), int>());
        }

        /// <summary>The level-k node at offset (ox, oy), 0 ≤ ox, oy ≤ 2^k, in the square of the four
        /// aligned level-k nodes a b over c d.</summary>
        private int Crop(
            int k, int a, int b, int c, int d, long ox, long oy, Dictionary<(int, int, int, int, int, long, long), int> memo)
        {
            long size = 1L << k;
            if ((ox == 0 || ox == size) && (oy == 0 || oy == size))
                return ox == 0 ? (oy == 0 ? a : c) : (oy == 0 ? b : d);
            var s = _store;
            int e = s.Empty(k);
            if (a == e && b == e && c == e && d == e)
                return e;
            var key = (k, a, b, c, d, ox, oy);
            if (memo.TryGetValue(key, out int hit))
                return hit;
            int r;
            if (k == 1)
            {
                // The 4 × 4 square of states, row by row, and the 2 × 2 at (ox, oy) in it.
                int sa = s.States(a), sb = s.States(b), sc = s.States(c), sd = s.States(d);
                Span<int> square = stackalloc int[16];
                for (int i = 0; i < 4; i++)
                {
                    int x = i & 1, y = i >> 1;
                    square[y * 4 + x] = (sa >> (8 * i)) & 0xFF;
                    square[y * 4 + x + 2] = (sb >> (8 * i)) & 0xFF;
                    square[(y + 2) * 4 + x] = (sc >> (8 * i)) & 0xFF;
                    square[(y + 2) * 4 + x + 2] = (sd >> (8 * i)) & 0xFF;
                }
                int cx = (int)ox, cy = (int)oy;
                r = s.Leaf(square[cy * 4 + cx] | square[cy * 4 + cx + 1] << 8
                    | square[(cy + 1) * 4 + cx] << 16 | square[(cy + 1) * 4 + cx + 1] << 24);
            }
            else
            {
                Span<int> g = stackalloc int[16];
                for (int q = 0; q < 4; q++)
                {
                    int row = 2 * (q >> 1), column = 2 * (q & 1);
                    int parent = q == 0 ? a : q == 1 ? b : q == 2 ? c : d;
                    g[row * 4 + column] = s.Kid(parent, 0);
                    g[row * 4 + column + 1] = s.Kid(parent, 1);
                    g[(row + 1) * 4 + column] = s.Kid(parent, 2);
                    g[(row + 1) * 4 + column + 1] = s.Kid(parent, 3);
                }
                long half = size >> 1;
                Span<int> kids = stackalloc int[4];
                for (int j = 0; j < 2; j++)
                {
                    long py = oy + j * half;
                    int gy = (int)(py / half);
                    long ry = py - gy * half;
                    if (gy == 3)
                    {
                        gy = 2;
                        ry = half;
                    }
                    for (int i = 0; i < 2; i++)
                    {
                        long px = ox + i * half;
                        int gx = (int)(px / half);
                        long rx = px - gx * half;
                        if (gx == 3)
                        {
                            gx = 2;
                            rx = half;
                        }
                        kids[2 * j + i] = Crop(
                            k - 1, g[gy * 4 + gx], g[gy * 4 + gx + 1], g[(gy + 1) * 4 + gx], g[(gy + 1) * 4 + gx + 1],
                            rx, ry, memo);
                    }
                }
                r = s.Join(kids[0], kids[1], kids[2], kids[3]);
            }
            memo[key] = r;
            return r;
        }

        // -- extremes and the bounding box ------------------------------------------------------

        // Per edge (min x, max x, min y, max y): the near children, then the far ones half a node
        // further along the axis.
        private static readonly int[][] EdgeNear = { new[] { 0, 2 }, new[] { 1, 3 }, new[] { 0, 1 }, new[] { 2, 3 } };
        private static readonly int[][] EdgeFar = { new[] { 1, 3 }, new[] { 0, 2 }, new[] { 2, 3 }, new[] { 0, 1 } };

        /// <summary>One extreme of a leaf's non-zero cells (packed states), as a column or row 0..1,
        /// or −1 when it has none: edge 0 is the least x, 1 the greatest x, 2 the least y, 3 the
        /// greatest y.</summary>
        private static int LeafEdge(int states, int edge)
        {
            bool lowest = edge == 0 || edge == 2;
            int best = -1;
            for (int i = 0; i < 4; i++)
            {
                if (((states >> (8 * i)) & 0xFF) == 0)
                    continue;
                int v = edge < 2 ? i & 1 : i >> 1;
                if (best < 0 || (lowest ? v < best : v > best))
                    best = v;
            }
            return best;
        }

        private BigInteger? ExtremeBig(
            int n, int k, BigInteger nx, BigInteger ny, BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1, int edge)
        {
            var s = _store;
            if (n == s.Empty(k))
                return null;
            BigInteger size = BigInteger.One << k;
            if (nx > x1 || nx + size <= x0 || ny > y1 || ny + size <= y0)
                return null;
            BigInteger origin = edge < 2 ? nx : ny;
            if (x0 <= nx && nx + size - 1 <= x1 && y0 <= ny && ny + size - 1 <= y1)
                return origin + EdgeBig(n, k, edge);
            if (k <= 62)
            {
                long rx0 = (long)BigInteger.Max(x0 - nx, BigInteger.Zero);
                long ry0 = (long)BigInteger.Max(y0 - ny, BigInteger.Zero);
                long rx1 = (long)BigInteger.Min(x1 - nx, size - 1);
                long ry1 = (long)BigInteger.Min(y1 - ny, size - 1);
                long offset = ExtremeLong(n, k, rx0, ry0, rx1, ry1, edge);
                return offset < 0 ? (BigInteger?)null : origin + offset;
            }
            bool lowest = edge == 0 || edge == 2;
            BigInteger half = size >> 1;
            for (int pass = 0; pass < 2; pass++)
            {
                BigInteger? best = null;
                foreach (int i in pass == 0 ? EdgeNear[edge] : EdgeFar[edge])
                {
                    BigInteger cx = (i & 1) != 0 ? nx + half : nx;
                    BigInteger cy = (i & 2) != 0 ? ny + half : ny;
                    BigInteger? got = ExtremeBig(s.Kid(n, i), k - 1, cx, cy, x0, y0, x1, y1, edge);
                    if (got.HasValue && (!best.HasValue || (lowest ? got.Value < best.Value : got.Value > best.Value)))
                        best = got;
                }
                if (best.HasValue)
                    return best;
            }
            return null;
        }

        private long ExtremeLong(int n, int k, long x0, long y0, long x1, long y1, int edge)
        {
            var s = _store;
            if (n == s.Empty(k))
                return -1;
            long size = 1L << k;
            if (x0 == 0 && y0 == 0 && x1 == size - 1 && y1 == size - 1)
                return EdgeLong(n, k, edge);
            if (k == 1)
            {
                int states = s.States(n), kept = 0;
                for (int i = 0; i < 4; i++)
                {
                    long x = i & 1, y = i >> 1;
                    if (x >= x0 && x <= x1 && y >= y0 && y <= y1)
                        kept |= states & (0xFF << (8 * i));
                }
                return LeafEdge(kept, edge);
            }
            bool lowest = edge == 0 || edge == 2;
            long half = size >> 1;
            for (int pass = 0; pass < 2; pass++)
            {
                long best = -1;
                foreach (int i in pass == 0 ? EdgeNear[edge] : EdgeFar[edge])
                {
                    long qx = (i & 1) * half, qy = (i >> 1) * half;
                    long cx0 = Math.Max(x0, qx) - qx, cx1 = Math.Min(x1, qx + half - 1) - qx;
                    long cy0 = Math.Max(y0, qy) - qy, cy1 = Math.Min(y1, qy + half - 1) - qy;
                    if (cx0 > cx1 || cy0 > cy1)
                        continue;
                    long got = ExtremeLong(s.Kid(n, i), k - 1, cx0, cy0, cx1, cy1, edge);
                    if (got < 0)
                        continue;
                    got += edge < 2 ? qx : qy;
                    if (best < 0 || (lowest ? got < best : got > best))
                        best = got;
                }
                if (best >= 0)
                    return best;
            }
            return -1;
        }

        private CellBox? ComputeBox()
        {
            var s = _store;
            int k = s.Level;
            if (s.Root == s.Empty(k))
                return null;
            if (k <= 62)
            {
                long origin = -(1L << (k - 1));
                long[] e = new long[4];
                for (int edge = 0; edge < 4; edge++)
                {
                    _edgeMemo.Clear();
                    e[edge] = EdgeLong(s.Root, k, edge);
                }
                _edgeMemo.Clear();
                return new CellBox(origin + e[0], origin + e[2] + 1, origin + e[1], origin + e[3] + 1);
            }
            BigInteger bigOrigin = -(BigInteger.One << (k - 1));
            var big = new BigInteger[4];
            for (int edge = 0; edge < 4; edge++)
            {
                _edgeMemo.Clear();
                _edgeMemoBig.Clear();
                big[edge] = EdgeBig(s.Root, k, edge);
            }
            _edgeMemo.Clear();
            _edgeMemoBig.Clear();
            return new CellBox(bigOrigin + big[0], bigOrigin + big[2] + 1, bigOrigin + big[1], bigOrigin + big[3] + 1);
        }

        /// <summary>One extreme of the non-zero cells of non-empty level-k node n (k ≤ 62), as an
        /// offset from its origin.</summary>
        private long EdgeLong(int n, int k, int edge)
        {
            if (_edgeMemo.TryGetValue(n, out long hit))
                return hit;
            var s = _store;
            bool lowest = edge == 0 || edge == 2;
            long r;
            if (k == 1)
            {
                r = LeafEdge(s.States(n), edge);
            }
            else
            {
                int e = s.Empty(k - 1);
                long half = 1L << (k - 1);
                bool any = false;
                long best = 0;
                foreach (int i in EdgeNear[edge])
                {
                    int kid = s.Kid(n, i);
                    if (kid == e)
                        continue;
                    long v = EdgeLong(kid, k - 1, edge);
                    best = !any ? v : lowest ? Math.Min(best, v) : Math.Max(best, v);
                    any = true;
                }
                if (any)
                {
                    r = best + (lowest ? 0 : half);
                }
                else
                {
                    foreach (int i in EdgeFar[edge])
                    {
                        int kid = s.Kid(n, i);
                        if (kid == e)
                            continue;
                        long v = EdgeLong(kid, k - 1, edge);
                        best = !any ? v : lowest ? Math.Min(best, v) : Math.Max(best, v);
                        any = true;
                    }
                    r = best + (lowest ? half : 0);
                }
            }
            _edgeMemo[n] = r;
            return r;
        }

        private BigInteger EdgeBig(int n, int k, int edge)
        {
            if (k <= 62)
                return EdgeLong(n, k, edge);
            if (_edgeMemoBig.TryGetValue(n, out BigInteger hit))
                return hit;
            var s = _store;
            bool lowest = edge == 0 || edge == 2;
            int e = s.Empty(k - 1);
            BigInteger half = BigInteger.One << (k - 1);
            bool any = false;
            BigInteger best = BigInteger.Zero;
            foreach (int i in EdgeNear[edge])
            {
                int kid = s.Kid(n, i);
                if (kid == e)
                    continue;
                BigInteger v = EdgeBig(kid, k - 1, edge);
                best = !any ? v : lowest ? BigInteger.Min(best, v) : BigInteger.Max(best, v);
                any = true;
            }
            BigInteger r;
            if (any)
            {
                r = lowest ? best : best + half;
            }
            else
            {
                foreach (int i in EdgeFar[edge])
                {
                    int kid = s.Kid(n, i);
                    if (kid == e)
                        continue;
                    BigInteger v = EdgeBig(kid, k - 1, edge);
                    best = !any ? v : lowest ? BigInteger.Min(best, v) : BigInteger.Max(best, v);
                    any = true;
                }
                r = lowest ? best + half : best;
            }
            _edgeMemoBig[n] = r;
            return r;
        }

        // -- frames -----------------------------------------------------------------------------

        /// <summary>
        /// Render <paramref name="view"/> into <paramref name="frame"/> (height × width bytes,
        /// row-major) without allocating (spec/hashlife-multistate.md "View and render"): at
        /// <c>Mag ≥ 0</c> each cell's state over its 2^Mag-pixel square (255 for a non-zero cell
        /// in <see cref="MultiStateRenderMode.Density"/>); zoomed out, one aligned block of 2^−Mag
        /// cells per pixel, its shown state under <see cref="ZoomOrder"/> or its density. The walk
        /// visits only the blocks in view, so a frame costs the same at any scale and distance.
        /// </summary>
        public void WriteFrame(
            byte[] frame, int width, int height, LifeView view, MultiStateRenderMode mode = MultiStateRenderMode.State)
        {
            if (frame == null)
                throw new ArgumentNullException(nameof(frame));
            if (width < 1 || height < 1 || width > 1 << Phase2Bits || height > 1 << Phase2Bits)
                throw new ArgumentOutOfRangeException(nameof(width), $"frame size must be positive, got {width} x {height}");
            if (frame.Length < (long)width * height)
                throw new ArgumentException($"frame holds {frame.Length} bytes, needs {(long)width * height}", nameof(frame));
            if (mode != MultiStateRenderMode.State && mode != MultiStateRenderMode.Density)
                throw new ArgumentOutOfRangeException(nameof(mode), mode, "unknown render mode");
            Array.Clear(frame, 0, width * height);
            _frame = frame;
            _frameWidth = width;
            _frameHeight = height;
            _fDensity = mode == MultiStateRenderMode.Density;
            if (view.Mag < 0)
            {
                _fs = -view.Mag;
                _fp = 0;
                _fox = _foy = 0;
                _cx.Set(view.X, 0, ref _coordBytesX);
                _cy.Set(view.Y, 0, ref _coordBytesY);
                _ftw = width;
                _fth = height;
            }
            else
            {
                _fs = 0;
                _fp = view.Mag;
                _cx.Set(view.X, _fp, ref _coordBytesX);
                _cy.Set(view.Y, _fp, ref _coordBytesY);
                _fox = _cx.DroppedBits;
                _foy = _cy.DroppedBits;
                _ftw = ((_fox + width - 1) >> _fp) + 1;
                _fth = ((_foy + height - 1) >> _fp) + 1;
            }
            try
            {
                RenderFrame();
            }
            finally
            {
                _frame = Array.Empty<byte>(); // hold no reference to the caller's buffer
            }
        }

        /// <summary>A newly allocated frame of <paramref name="view"/>; see <see cref="WriteFrame"/>.</summary>
        public byte[] Frame(int width, int height, LifeView view, MultiStateRenderMode mode = MultiStateRenderMode.State)
        {
            if (width < 1 || height < 1)
                throw new ArgumentOutOfRangeException(nameof(width), $"frame size must be positive, got {width} x {height}");
            var frame = new byte[(long)width * height];
            WriteFrame(frame, width, height, view, mode);
            return frame;
        }

        private void RenderFrame()
        {
            var s = _store;
            int root = s.Root, k = s.Level;
            while (k - 1 < _fs)
            {
                root = ExpandNode(root, k);
                k++;
            }
            int m = k - 1; // the root's children: aligned blocks −1 and 0 along each axis
            int d = m - _fs;
            if (d > Phase2Bits)
            {
                if (!_cx.TopQuotient(d, out int qx) || !_cy.TopQuotient(d, out int qy))
                    return; // the frame lies outside the root
                for (int q = 0; q < 4; q++)
                {
                    int rx = (q & 1) - 1 - qx, ry = (q >> 1) - 1 - qy;
                    if (InTop(ref _cx, rx, d, _ftw) && InTop(ref _cy, ry, d, _fth))
                        VisitTop(s.Kid(root, q), m, rx, ry);
                }
                return;
            }
            const long Far = 1L << 61;
            if (!_cx.Small || !_cy.Small
                || _cx.Value <= -Far || _cx.Value >= Far || _cy.Value <= -Far || _cy.Value >= Far)
                return;
            long size = 1L << d;
            for (int q = 0; q < 4; q++)
            {
                long ox = ((q & 1) - 1) * size - _cx.Value, oy = ((q >> 1) - 1) * size - _cy.Value;
                if (ox < _ftw && ox + size > 0 && oy < _fth && oy + size > 0)
                    VisitNear(s.Kid(root, q), m, ox, oy);
            }
        }

        private static bool InTop(ref HashLife.Coord c, int rel, int d, long count)
            => rel == 0 || (rel == 1 && c.Crosses(d, count));

        private void VisitTop(int n, int m, int relX, int relY)
        {
            var s = _store;
            if (n == s.Empty(m))
                return;
            int d = m - _fs;
            int dc = d - 1;
            int bitX = _cx.Bit(dc), bitY = _cy.Bit(dc);
            for (int q = 0; q < 4; q++)
            {
                int rx = 2 * relX + (q & 1) - bitX, ry = 2 * relY + (q >> 1) - bitY;
                int kid = s.Kid(n, q);
                if (dc > Phase2Bits)
                {
                    if (InTop(ref _cx, rx, dc, _ftw) && InTop(ref _cy, ry, dc, _fth))
                        VisitTop(kid, m - 1, rx, ry);
                }
                else
                {
                    long size = 1L << dc;
                    long ox = rx * size - _cx.Low(dc), oy = ry * size - _cy.Low(dc);
                    if (ox < _ftw && ox + size > 0 && oy < _fth && oy + size > 0)
                        VisitNear(kid, m - 1, ox, oy);
                }
            }
        }

        private void VisitNear(int n, int m, long ox, long oy)
        {
            var s = _store;
            if (n == s.Empty(m))
                return;
            if (m == _fs)
            {
                // s ≥ 1: this node is one pixel.
                _frame[oy * _frameWidth + ox] = _fDensity ? s.Density(n, m) : (byte)s.Shown(n, m);
                return;
            }
            if (m == 1)
            {
                LeafPixels(s.States(n), ox, oy);
                return;
            }
            long half = 1L << (m - _fs - 1);
            for (int q = 0; q < 4; q++)
            {
                long cx = ox + ((q & 1) != 0 ? half : 0), cy = oy + ((q & 2) != 0 ? half : 0);
                if (cx < _ftw && cx + half > 0 && cy < _fth && cy + half > 0)
                    VisitNear(s.Kid(n, q), m - 1, cx, cy);
            }
        }

        /// <summary>A leaf's cells zoomed in: each non-zero one a square of its state (or 255).</summary>
        private void LeafPixels(int states, long ox, long oy)
        {
            byte[] frame = _frame;
            int width = _frameWidth;
            int p = _fp;
            long side = 1L << p;
            for (int i = 0; i < 4; i++)
            {
                int state = (states >> (8 * i)) & 0xFF;
                if (state == 0)
                    continue;
                long cx = ox + (i & 1), cy = oy + (i >> 1);
                if (cx < 0 || cx >= _ftw || cy < 0 || cy >= _fth)
                    continue;
                byte value = _fDensity ? (byte)255 : (byte)state;
                long px0 = Math.Max((cx << p) - _fox, 0), px1 = Math.Min((cx << p) - _fox + side, width);
                long py0 = Math.Max((cy << p) - _foy, 0), py1 = Math.Min((cy << p) - _foy + side, _frameHeight);
                for (long py = py0; py < py1; py++)
                    for (long px = px0; px < px1; px++)
                        frame[py * width + px] = value;
            }
        }
    }
}
