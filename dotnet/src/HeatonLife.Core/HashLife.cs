using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Numerics;
using System.Text;
using System.Threading;

namespace HeatonLife
{
    /// <summary>How <see cref="HashLife.SetRect"/> lands its cells (spec/hashlife.md "Editing").</summary>
    public enum HashLifePasteMode
    {
        /// <summary>Every cell of the rectangle takes the source's value.</summary>
        Copy,

        /// <summary>The source's live cells are added.</summary>
        Or,

        /// <summary>Each cell toggles where the source is alive.</summary>
        Xor,

        /// <summary>A cell of the rectangle stays alive only where the source is alive too.</summary>
        And,
    }

    /// <summary>What a zoomed-out pixel shows (spec/hashlife.md "View and render").</summary>
    public enum HashLifeRenderMode
    {
        /// <summary>255 when the pixel's block holds a live cell, else 0.</summary>
        Any,

        /// <summary>⌈255 · population / 4^s⌉ for a block of 2^s × 2^s cells.</summary>
        Density,
    }

    /// <summary>An inclusive rectangle of cells, (X0, Y0) top-left to (X1, Y1) bottom-right.</summary>
    public readonly struct CellBox : IEquatable<CellBox>
    {
        public CellBox(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            X0 = x0;
            Y0 = y0;
            X1 = x1;
            Y1 = y1;
        }

        public BigInteger X0 { get; }
        public BigInteger Y0 { get; }
        public BigInteger X1 { get; }
        public BigInteger Y1 { get; }

        public bool Equals(CellBox other)
            => X0 == other.X0 && Y0 == other.Y0 && X1 == other.X1 && Y1 == other.Y1;

        public override bool Equals(object? obj) => obj is CellBox other && Equals(other);

        public override int GetHashCode()
            => X0.GetHashCode() ^ (Y0.GetHashCode() * 31) ^ (X1.GetHashCode() * 961) ^ (Y1.GetHashCode() * 29791);

        public override string ToString() => $"({X0}, {Y0})..({X1}, {Y1})";

        public static bool operator ==(CellBox a, CellBox b) => a.Equals(b);

        public static bool operator !=(CellBox a, CellBox b) => !a.Equals(b);
    }

    /// <summary>A universe's cells and generation at one moment (spec/hashlife.md "Snapshots").
    /// Both kinds of universe, <see cref="HashLife"/> and <see cref="MultiStateHashLife"/>, make
    /// them, and each refuses the other's (spec/hashlife-multistate.md "Snapshots").</summary>
    public sealed class HashLifeSnapshot
    {
        private volatile bool _released;

        internal HashLifeSnapshot(object owner, int root, int level, BigInteger generation, int states = 2)
        {
            Owner = owner;
            RootNode = root;
            Level = level;
            Generation = generation;
            States = states;
        }

        /// <summary>The universe that made it, compared by reference.</summary>
        internal object Owner { get; }

        /// <summary>The most states its cells can need: every state is below it (2 for a
        /// two-state universe).</summary>
        internal int States { get; }

        internal int RootNode { get; }

        internal int Level { get; }

        public BigInteger Generation { get; }

        /// <summary>True once <see cref="Release"/> has let go of the snapshot's nodes.</summary>
        public bool Released => _released;

        /// <summary>
        /// Let go of this snapshot's nodes now (spec/hashlife.md "Snapshots"): the universe's next
        /// collection may free whatever nothing else holds, without waiting for the managed
        /// collector to find this object unreachable. A released snapshot holds no cells, so
        /// restoring it, or writing it into a timeline, throws; its <see cref="Generation"/> can
        /// still be read, and releasing it again does nothing. Any thread may call it: the store
        /// reads the flag at its next collection.
        /// </summary>
        public void Release() => _released = true;
    }

    /// <summary>
    /// What a list of snapshots holds in a universe's store beyond its current state
    /// (spec/hashlife.md "What snapshots hold"). The counts are nodes, exact and the same in
    /// every port; <see cref="EstimatedBytes"/> is this port's estimate of <see cref="Nodes"/>
    /// in memory. The Python reference's heaton_life.ca.hashlife.SnapshotFootprint.
    /// </summary>
    public sealed class SnapshotFootprint
    {
        internal SnapshotFootprint(long universeNodes, long[] added, long nodes, long estimatedBytes)
        {
            UniverseNodes = universeNodes;
            Added = added;
            Nodes = nodes;
            EstimatedBytes = estimatedBytes;
        }

        /// <summary>The nodes of the universe's current state: its canonical Macrocell node lines
        /// (none for the empty universe).</summary>
        public long UniverseNodes { get; }

        /// <summary>For each snapshot in order, the nodes it holds that neither the current state
        /// nor an earlier snapshot in the list holds (0 for a released snapshot, and for one listed
        /// a second time). The last k counts add up to what releasing those k snapshots frees.</summary>
        public IReadOnlyList<long> Added { get; }

        /// <summary>The sum of <see cref="Added"/>: the nodes the list holds beyond the current state.</summary>
        public long Nodes { get; }

        /// <summary><see cref="Nodes"/> at the store's size of a node (40 bytes), the measure
        /// <see cref="HashLife.MemoryUsed"/> and the memory budget are kept in.</summary>
        public long EstimatedBytes { get; }
    }

    /// <summary>A step could not fit even one generation into <see cref="HashLife.MaxMemoryMb"/>.</summary>
    public sealed class HashLifeMemoryException : Exception
    {
        public HashLifeMemoryException(string message)
            : base(message)
        {
        }
    }

    /// <summary>
    /// An unbounded Life-like universe run by HashLife (spec/hashlife.md): a hash-consed quadtree
    /// whose nodes memoize their own future, so regular patterns of trillions of cells fit in
    /// memory and a step can be any number of generations. Coordinates, generations, and
    /// populations are <see cref="BigInteger"/>s at this edge; x grows right and y grows down, and
    /// cells sit where Macrocell files put them (cell (x, y) is tree position (x, y − 1)).
    /// Every Life-like rule runs, B0 included: its universe holds the cells that differ from the
    /// background (<see cref="BackgroundAlive"/>; spec/hashlife.md "Rules with B0").
    ///
    /// Editing reaches |x|, |y| ≤ <see cref="EditLimit"/>; queries and rendering
    /// reach everywhere. <see cref="Step"/> allocates nothing on the managed heap once warm, and
    /// <see cref="WriteFrame"/> renders into a caller's buffer. Not thread-safe: one thread drives
    /// a universe, and another may only cancel its step through the token.
    /// The Python reference's heaton_life.ca.hashlife.HashLife.
    /// </summary>
    public sealed class HashLife
    {
        /// <summary>Editing reaches cells with |x| ≤ EditLimit and |y| ≤ EditLimit.</summary>
        public const long EditLimit = 1_000_000_000;

        public const int DefaultMaxMemoryMb = 500;

        /// <summary>The smallest allowed budget, in MiB.</summary>
        public const int MinMemoryMb = 10;

        /// <summary>The deepest tree (spec/hashlife.md "Depth"): every live cell lies within ±2^511,
        /// and the store's walks recurse at most once per level, which a small thread stack holds.</summary>
        public const int MaxLevel = 512;

        /// <summary>2^(MaxLevel − 2): sub-step j needs a level-(j + 3) root, so steps stay below it.</summary>
        private static readonly BigInteger StepLimit = BigInteger.One << (MaxLevel - 2);

        private const int MinLevel = 4;     // the root is always an internal node
        private const int MinStepLevel = 6; // sub-steps check containment on great-grandchildren
        private const int WindowLevel = 31; // the four level-31 nodes around the origin hold the editing box
        private const int Phase2Bits = 30;  // render walks switch to long offsets below 2^30 blocks

        private readonly HashLifeStore _store;
        private string _rule;
        private LifeRule _lifeRule;
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
        private Dictionary<long, ulong>? _blocks;
        private HashSet<long>?[]? _tiers;
        private HashLifePasteMode _mode;
        private byte[]? _extract;

        // A frame in progress (see WriteFrame).
        private byte[] _frame = Array.Empty<byte>();
        private int _frameWidth, _frameHeight;
        private int _fs, _fp;
        private long _fox, _foy, _ftw, _fth;
        private bool _fDensity;
        private Coord _cx, _cy;
        private byte[] _coordBytesX = new byte[16], _coordBytesY = new byte[16];

        public HashLife(string rule = "B3/S23", int maxMemoryMb = DefaultMaxMemoryMb)
        {
            _rule = CheckedRule(rule);
            _lifeRule = RuleString.Compile(_rule);
            _store = new HashLifeStore(HashLifeLeaves.RuleTables(_rule), MaxNodesFor(maxMemoryMb));
            _maxMemoryMb = maxMemoryMb;
        }

        // -- configuration ----------------------------------------------------------------------

        /// <summary>The canonical rule (spec/rules.md): any Life-like rule, B0 included (spec/hashlife.md
        /// "Rules with B0"). Setting it keeps the cells and drops cached results; under a rule with
        /// B0 the cells then stand for the plane the new rule's background says.</summary>
        public string Rule
        {
            get => _rule;
            set
            {
                string canonical = CheckedRule(value);
                if (canonical != _rule)
                {
                    _rule = canonical;
                    _lifeRule = RuleString.Compile(canonical);
                    _store.UseRule(HashLifeLeaves.RuleTables(canonical));
                }
            }
        }

        /// <summary>The node store's budget in MiB: default 500, minimum 10. It changes speed,
        /// never results (spec/hashlife.md "Memory").</summary>
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
        public long MemoryUsed => (long)_store.Live * HashLifeStore.BytesPerNode;

        public long NodeCount => _store.Live;

        /// <summary>Garbage collections run so far.</summary>
        public int Collections => _store.Collections;

        /// <summary>The canonical form of a rule a universe can run: any Life-like rule of two
        /// states (spec/rules.md), B0 included (spec/hashlife.md "Rules with B0"). A rule with a
        /// variant (History) is refused, since it has more states than the universe holds, and so
        /// is a Generations rule (spec/generations.md), each saying that
        /// <see cref="MultiStateHashLife"/> runs it; a Larger than Life rule is refused as one
        /// (spec/ltl.md "Topologies"); anything else throws <see cref="ArgumentException"/> too.</summary>
        internal static string CheckedRule(string rule)
        {
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            string? ltl = LtlRule.Refusal(rule);
            if (ltl != null)
                throw new ArgumentException(ltl, nameof(rule));
            if (!RuleString.TryCompile(rule, true, out LifeRule? compiled, out _))
            {
                if (GenerationsRule.TryCompile(rule, out GenerationsRule? generations, out _))
                {
                    throw new ArgumentException(
                        $"{generations.Canonical} is a Generations rule of {generations.States} states, not a "
                        + "Life-like rule: MultiStateHashLife runs it (spec/hashlife.md, spec/generations.md)",
                        nameof(rule));
                }
                compiled = RuleString.Compile(rule, variants: true); // throws, its message carrying the reason
            }
            if (compiled.Variant != RuleVariant.None)
                throw new ArgumentException(
                    $"{compiled.Canonical} is a {compiled.Variant} rule of {compiled.States} states, and this "
                    + "universe holds two: MultiStateHashLife runs it (spec/hashlife.md, spec/hashlife-multistate.md)",
                    nameof(rule));
            return compiled.Canonical;
        }

        private static int MaxNodesFor(int maxMemoryMb)
        {
            if (maxMemoryMb < MinMemoryMb)
                throw new ArgumentOutOfRangeException(
                    nameof(maxMemoryMb), maxMemoryMb, $"MaxMemoryMb must be at least {MinMemoryMb}");
            long nodes = ((long)maxMemoryMb << 20) / HashLifeStore.BytesPerNode;
            return (int)Math.Min(nodes, HashLifeStore.MaxCapacity);
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

        /// <summary>
        /// True where the plane outside the universe's cells is alive at the current generation
        /// (spec/hashlife.md "Rules with B0"): never for a rule without B0, always for B0 with
        /// Smax, at odd generations for B0 without Smax. The plane's cell (x, y) is
        /// <c>GetCell(x, y) ^ BackgroundAlive</c>. The Python reference's <c>background</c>.
        /// </summary>
        public bool BackgroundAlive => _lifeRule.HasB0 && (_lifeRule.HasSmax || (_genLow & 1) != 0);

        /// <summary>The number of the universe's live cells: under a rule with B0, the cells that
        /// differ from the background, the plane's dead cells where it is alive.</summary>
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

        /// <summary>The inclusive extremes of the live cells, or null for an empty universe.</summary>
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

        /// <summary>Live cells in the inclusive rectangle; any coordinates.</summary>
        public BigInteger PopulationIn(BigInteger x0, BigInteger y0, BigInteger x1, BigInteger y1)
        {
            if (x1 < x0 || y1 < y0)
                return BigInteger.Zero;
            int k = _store.Level;
            BigInteger origin = -(BigInteger.One << (k - 1));
            return CountBig(_store.Root, k, origin, origin, x0, y0 - 1, x1, y1 - 1);
        }

        /// <summary>
        /// The inclusive extremes of the live cells inside the inclusive rectangle, or null when it
        /// holds none (an empty rectangle holds none): where Shrink Selection moves a selection
        /// (spec/hashlife.md "Observables"). Any coordinates.
        /// </summary>
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

        public bool GetCell(long x, long y)
        {
            CheckBox(x, y, x, y);
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
                while (k > 3)
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
                return ((_store.Bits(n) >> (int)(ry * 8 + rx)) & 1) != 0;
            }
            return false;
        }

        /// <summary>The inclusive rectangle as (y1 − y0 + 1) × (x1 − x0 + 1) bytes of 0/1, row-major.</summary>
        public byte[] GetRect(long x0, long y0, long x1, long y1)
        {
            CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
            long width = x1 - x0 + 1, height = y1 - y0 + 1;
            if (width * height > int.MaxValue)
                throw new ArgumentOutOfRangeException(
                    null, $"({x0}, {y0})..({x1}, {y1}) holds more cells than one array can");
            var cells = new byte[width * height];
            _rx0 = x0;
            _ry0 = y0 - 1;
            _rx1 = x1;
            _ry1 = y1 - 1;
            _extract = cells;
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                ExtractIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            _extract = null;
            return cells;
        }

        // -- evolution --------------------------------------------------------------------------

        /// <summary>
        /// Advance exactly <paramref name="n"/> generations, 0 ≤ n &lt; 2^510 (spec/hashlife.md
        /// "Evolution", "Depth"): a larger n throws <see cref="ArgumentOutOfRangeException"/> before
        /// anything runs, and a pattern spread too far for a level-<see cref="MaxLevel"/> root throws
        /// <see cref="InvalidOperationException"/> at a sub-step boundary. A canceled token stops the step at the boundary of a completed sub-step
        /// with <see cref="OperationCanceledException"/>; a step that cannot fit one generation
        /// into the budget throws <see cref="HashLifeMemoryException"/>. Either way the universe
        /// holds the state at the last completed sub-step, and <see cref="Generation"/> says which.
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
                // When a rule with B0 alternates its phases (spec/hashlife.md "Rules with B0"),
                // every sub-step of two or more generations starts at an even generation: one
                // generation first from an odd generation, then the set bits j ≥ 1 of what
                // remains, then the last single generation, if one remains.
                bool alternates = _store.Alternates;
                bool last = false;
                if (n.CompareTo(ulong.MaxValue) <= 0)
                {
                    ulong bits = (ulong)n;
                    if (alternates)
                    {
                        if ((_genLow & 1) != 0)
                        {
                            Advance(0, cancellationToken);
                            bits--;
                        }
                        last = (bits & 1) != 0;
                        bits &= ~1UL;
                    }
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
                    if (alternates)
                    {
                        if ((_genLow & 1) != 0)
                        {
                            Advance(0, cancellationToken);
                            // n − 1 in place, borrowing upward (n ≥ 2^64, so it never reaches 0).
                            for (int i = 0; i < written && _stepBits[i]-- == 0; i++)
                            {
                            }
                        }
                        last = (_stepBits[0] & 1) != 0;
                        _stepBits[0] &= 0xFE;
                    }
                    for (int j = 0; j < written * 8; j++)
                    {
                        if (((_stepBits[j >> 3] >> (j & 7)) & 1) != 0)
                            Advance(j, cancellationToken);
                    }
                }
                if (last)
                    Advance(0, cancellationToken);
            }
            finally
            {
                _store.Cancel = default;
            }
        }

        /// <summary>In-flight collections a sub-step of more than one generation may run before it
        /// is split instead (a single generation collects for as long as collecting makes room).
        /// Measured at the 10 MiB floor on soups of 1024² to 2400² cells and jumps of 2^8 to 2^20:
        /// 4 was fastest or near it everywhere, and without a limit a 2^12 jump never finished.</summary>
        private const int SplitAfterCollections = 4;

        /// <summary>
        /// Advance 2^j generations (spec/hashlife.md "Memory"): collect when three-quarters full,
        /// then step, collecting in flight when the budget fills. A sub-step that cannot finish
        /// is split into two halves at once — collecting in flight already did what a retry after
        /// collection would — except a single generation, which is retried once after a full
        /// collection before the step gives up.
        /// </summary>
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
            if (need > HashLifeStore.MaxLevel)
                throw new ArgumentOutOfRangeException(
                    nameof(j), $"a sub-step of 2^{j} generations is past the deepest supported tree");
            // Guarded from the first expansion on, so a store at its budget collects instead of
            // growing; ExpandNode keeps its intermediates on the saved stack.
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
                // A single generation of alternating phases runs the table of its own parity.
                s.Parity = s.Alternates && j == 0 ? (int)(_genLow & 1) : 0;
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

        /// <summary>Set the generation counter to any integer ≥ 0; no cell changes
        /// (spec/hashlife.md "Editing"). When a rule with B0 alternates its phases, the other
        /// parity swaps live and dead across the plane the cells stand for ("Rules with B0").</summary>
        public void SetGeneration(BigInteger generation)
        {
            if (generation.Sign < 0)
                throw new ArgumentOutOfRangeException(nameof(generation), generation, "a generation is never negative");
            _genLow = (ulong)(generation & ulong.MaxValue);
            _genHigh = generation >> 64;
            _genCache = generation;
        }

        /// <summary>Every live cell lies in the centered square of side 2^(k−2).</summary>
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

        private int ExpandNode(int root, int k)
        {
            var s = _store;
            int e = s.Empty(k - 1);
            int a = s.Kid(root, 0), b = s.Kid(root, 1), c = s.Kid(root, 2), d = s.Kid(root, 3);
            int depth = s.StackDepth;
            int nw = s.Push(s.Join(e, e, e, a));
            int ne = s.Push(s.Join(e, e, b, e));
            int sw = s.Push(s.Join(e, c, e, e));
            int se = s.Push(s.Join(d, e, e, e));
            int expanded = s.Join(nw, ne, sw, se);
            s.StackDepth = depth;
            return expanded;
        }

        /// <summary>Free every node unreachable from the current state and the live snapshots.</summary>
        public void CollectGarbage() => _store.Collect(inFlight: false);

        // -- editing ----------------------------------------------------------------------------

        /// <summary>Throw unless every corner lies in the editing box (spec/hashlife.md "Editing").</summary>
        internal static void CheckBox(long x0, long y0, long x1, long y1)
        {
            if (x0 < -EditLimit || x0 > EditLimit || y0 < -EditLimit || y0 > EditLimit
                || x1 < -EditLimit || x1 > EditLimit || y1 < -EditLimit || y1 > EditLimit)
                throw new ArgumentOutOfRangeException(
                    null,
                    $"({x0}, {y0})..({x1}, {y1}) reaches outside the editing box |x|, |y| <= "
                    + "1,000,000,000 (spec/hashlife.md \"Editing\")");
        }

        public void SetCell(long x, long y, bool alive)
        {
            CheckBox(x, y, x, y);
            Contain(x, y - 1, x, y - 1);
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
            {
                long size = 1L << _windowLevel;
                long rx = x - _windowX[w], ry = y - 1 - _windowY[w];
                if (rx >= 0 && rx < size && ry >= 0 && ry < size)
                    _windowNode[w] = SetIn(_windowNode[w], _windowLevel, rx, ry, alive);
            }
            CloseWindow();
        }

        /// <summary>
        /// Land <paramref name="cells"/> (<paramref name="height"/> rows of
        /// <paramref name="width"/>, nonzero = alive) with its top-left cell at (x, y).
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
            CheckBox(x, y, x + width - 1, y + height - 1);
            long tx = x, ty = y - 1;
            // The rectangle's leaves, densely (it is a dense rectangle), then the non-empty ones.
            long bx0 = tx >> 3, by0 = ty >> 3;
            int ox = (int)(tx - (bx0 << 3)), oy = (int)(ty - (by0 << 3));
            int columns = (ox + width + 7) >> 3, rows = (oy + height + 7) >> 3;
            var dense = new ulong[(long)columns * rows];
            for (int row = 0; row < height; row++)
            {
                int gy = oy + row;
                long line = (long)(gy >> 3) * columns;
                int shift = (gy & 7) * 8;
                for (int col = 0; col < width; col++)
                {
                    if (cells[row * width + col] != 0)
                    {
                        int gx = ox + col;
                        dense[line + (gx >> 3)] |= 1UL << (shift + (gx & 7));
                    }
                }
            }
            var blocks = new Dictionary<long, ulong>();
            for (int r = 0; r < rows; r++)
            {
                for (int c = 0; c < columns; c++)
                {
                    ulong bits = dense[(long)r * columns + c];
                    if (bits != 0)
                        blocks[BlockKey(bx0 + c, by0 + r)] = bits;
                }
            }
            PasteBlocks(blocks, tx, ty, x + width - 1, ty + height - 1, mode);
        }

        /// <summary>Every cell of the inclusive rectangle dies.</summary>
        public void ClearRect(long x0, long y0, long x1, long y1)
        {
            CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                return;
            _rx0 = x0;
            _ry0 = y0 - 1;
            _rx1 = x1;
            _ry1 = y1 - 1;
            Contain(_rx0, _ry0, _rx1, _ry1);
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                _windowNode[w] = ClearIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            CloseWindow();
        }

        /// <summary>Replace the inclusive rectangle with lifelike's PCG32 soup of the same size:
        /// seq 0, one draw per cell in row-major order, alive iff draw &lt; ⌊density · 2^32⌋.</summary>
        public void FillRandom(long x0, long y0, long x1, long y1, double density, ulong seed)
        {
            CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
            long width = x1 - x0 + 1, height = y1 - y0 + 1;
            if (width * height > int.MaxValue)
                throw new ArgumentOutOfRangeException(
                    null, $"({x0}, {y0})..({x1}, {y1}) holds more cells than one soup can");
            ulong threshold = Seeding.Threshold(density);
            var rng = new Pcg32(seed);
            var cells = new byte[width * height];
            for (int i = 0; i < cells.Length; i++)
                cells[i] = (byte)(rng.NextU32() < threshold ? 1 : 0);
            SetRect(x0, y0, cells, (int)width, (int)height, HashLifePasteMode.Copy);
        }

        /// <summary>Every cell outside the inclusive rectangle dies, wherever it lies. An empty
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
                // Everything outside the four windows lies outside the box, and so dies.
                s.Root = s.Join(_windowNode[0], _windowNode[1], _windowNode[2], _windowNode[3]);
                s.Level = WindowLevel + 1;
            }
            _version++;
        }

        /// <summary>
        /// Turn the inclusive rectangle and its cells a quarter about its center, in place, and
        /// return the rectangle they land on (spec/hashlife.md "Rectangle transforms"): the new
        /// rectangle takes the turned cells, live or dead, and the rest of the old one dies. Both
        /// rectangles must lie in the editing box. The turn works on the tree, so no dense copy is
        /// made, whatever the rectangle's area or population. The new rectangle is
        /// <see cref="Patterns.TurnedRect(BigInteger, BigInteger, BigInteger, BigInteger, bool)"/>'s,
        /// which a grid turns a region onto.
        /// </summary>
        public CellBox RotateRect(long x0, long y0, long x1, long y1, bool clockwise = true)
        {
            CheckEditRect(x0, y0, x1, y1);
            CellBox turned = Patterns.TurnedRect(x0, y0, x1, y1, clockwise);
            (BigInteger s, BigInteger d) = Patterns.TurnCenter(x0, y0, x1, y1);
            long sum = (long)s, diff = (long)d; // the editing box keeps both well inside a long
            long nx0 = (long)turned.X0, ny0 = (long)turned.Y0, nx1 = (long)turned.X1, ny1 = (long)turned.Y1;
            // The shift in tree coordinates, after turning about the box node's center.
            long dx = clockwise ? sum : 1 - diff;
            long dy = clockwise ? diff - 1 : sum;
            CheckBox(nx0, ny0, nx1, ny1);
            MoveRect(x0, y0, x1, y1, nx0, ny0, nx1, ny1, clockwise ? TurnClockwise : TurnCounterClockwise, dx, dy);
            return turned;
        }

        /// <summary>Mirror the inclusive rectangle's cells in place: left-right (x → x0 + x1 − x)
        /// or, with <paramref name="horizontal"/> false, top-bottom (y → y0 + y1 − y). No dense
        /// copy is made.</summary>
        public void FlipRect(long x0, long y0, long x1, long y1, bool horizontal = true)
        {
            CheckEditRect(x0, y0, x1, y1);
            if (horizontal)
                MoveRect(x0, y0, x1, y1, x0, y0, x1, y1, MirrorLeftRight, x0 + x1 + 1, 0);
            else
                MoveRect(x0, y0, x1, y1, x0, y0, x1, y1, MirrorTopBottom, 0, y0 + y1 - 1);
        }

        /// <summary>
        /// Evolve the inclusive rectangle <paramref name="n"/> generations as an isolated plane —
        /// every cell outside it dead at the start — and clip the result to it; the outside and
        /// the generation are untouched (spec/hashlife.md "Advancing part of the universe"). It
        /// throws what <see cref="Step"/> throws, and then leaves the universe exactly as it was.
        /// Under a rule with B0 the cells evolved and put back are the universe's, as
        /// <see cref="Step"/> gives them ("Rules with B0").
        /// </summary>
        public void AdvanceSelection(
            long x0, long y0, long x1, long y1, BigInteger n, CancellationToken cancellationToken = default)
            => AdvanceRegion(x0, y0, x1, y1, n, outside: false, cancellationToken);

        /// <summary>
        /// Evolve everything outside the inclusive rectangle <paramref name="n"/> generations as if
        /// the rectangle were empty; the rectangle keeps its cells and the generation stays. It
        /// throws what <see cref="Step"/> throws, and then leaves the universe exactly as it was.
        /// </summary>
        public void AdvanceOutside(
            long x0, long y0, long x1, long y1, BigInteger n, CancellationToken cancellationToken = default)
            => AdvanceRegion(x0, y0, x1, y1, n, outside: true, cancellationToken);

        /// <summary>Every cell dies; the generation stays.</summary>
        public void Clear()
        {
            _store.Root = _store.Empty(MinLevel);
            _store.Level = MinLevel;
            _version++;
        }

        // -- snapshots --------------------------------------------------------------------------

        /// <summary>The cells and generation now, in O(1); the nodes stay alive while it does.</summary>
        public HashLifeSnapshot Snapshot() => SnapshotAt(_store.Root, _store.Level, Generation);

        /// <summary>A snapshot of any tree in this universe's store, kept alive like any other.</summary>
        internal HashLifeSnapshot SnapshotAt(int root, int level, BigInteger generation)
        {
            var snapshot = new HashLifeSnapshot(this, root, level, generation);
            List<WeakReference<HashLifeSnapshot>> live = _store.Snapshots;
            if (live.Count >= _snapshotPrune)
            {
                // Forget snapshots nobody holds any more, or that were released, so a host taking
                // one per frame keeps a short list even when nothing collects.
                live.RemoveAll(weak => !weak.TryGetTarget(out HashLifeSnapshot? held) || held.Released);
                _snapshotPrune = Math.Max(64, 2 * live.Count);
            }
            live.Add(new WeakReference<HashLifeSnapshot>(snapshot));
            return snapshot;
        }

        /// <summary>Put the universe back at a snapshot of it: its cells and generation. A snapshot
        /// of another universe, or a released one, throws <see cref="ArgumentException"/>.</summary>
        public void Restore(HashLifeSnapshot snapshot)
        {
            CheckOwn(snapshot, nameof(snapshot));
            if (snapshot.Released)
                throw new ArgumentException("the snapshot was released and holds no cells", nameof(snapshot));
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

        /// <summary>
        /// What <paramref name="snapshots"/> hold beyond the current state, in nodes
        /// (spec/hashlife.md "What snapshots hold"): the current state's own nodes, each
        /// snapshot's addition to the state's and the earlier snapshots' nodes, and their sum. A
        /// state's nodes are the distinct non-empty nodes of its minimal tree, the ones its
        /// canonical Macrocell text writes. The last k snapshots' counts add up to what releasing
        /// them frees, so a history listed newest first says what letting go of its oldest points
        /// would free. A snapshot of another universe throws <see cref="ArgumentException"/>.
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
            return new SnapshotFootprint(universeNodes, added, nodes, nodes * HashLifeStore.BytesPerNode);
        }

        /// <summary>The non-empty nodes of tree (root, level) that <paramref name="seen"/> lacks,
        /// added to it.</summary>
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
                if (k > 3)
                {
                    for (int q = 0; q < 4; q++)
                        stack.Push((s.Kid(n, q), k - 1));
                }
            }
            return count;
        }

        // -- files ------------------------------------------------------------------------------

        /// <summary>Two-state RLE; <c>#CXRLE Pos=x,y Gen=n</c> places it and sets the generation
        /// (spec/patterns.md "RLE in the unbounded universe").</summary>
        public static HashLife FromRle(string text, int maxMemoryMb = DefaultMaxMemoryMb)
            => Patterns.RleToHashLife(text, maxMemoryMb);

        /// <summary>Macrocell text, placed by tree coordinates (spec/macrocell.md).</summary>
        public static HashLife FromMacrocell(string text, int maxMemoryMb = DefaultMaxMemoryMb)
            => Macrocell.Read(text, maxMemoryMb);

        /// <summary>Macrocell bytes, gzip-compressed or not.</summary>
        public static HashLife FromMacrocell(byte[] data, int maxMemoryMb = DefaultMaxMemoryMb)
            => Macrocell.Read(data, maxMemoryMb);

        /// <summary>A pattern file's bytes in any two-state format, gzip-compressed or not,
        /// recognized by content (spec/formats.md); <see cref="PatternFiles.ReadUniverse(byte[], int)"/>
        /// gives its metadata too.</summary>
        public static HashLife Load(byte[] data, int maxMemoryMb = DefaultMaxMemoryMb)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            return PatternFiles.ReadUniverse(data, maxMemoryMb).Universe;
        }

        /// <summary>
        /// Read a pattern file's bytes, in any two-state format and gzip-compressed or not, into
        /// this universe's own store (spec/formats.md "Reading into a universe that exists"): a
        /// snapshot of its cells and generation, with its format, rule, metadata and a timeline's
        /// frames. The file is read as <see cref="PatternFiles.ReadUniverse(byte[], int)"/> reads it
        /// and refused as it refuses it, but this universe's cells, generation, rule and earlier
        /// snapshots stay as they were: restoring the file's snapshot, and taking its rule, is the
        /// caller's to do. Its nodes are shared with any equal ones the store already holds.
        /// </summary>
        public PatternSnapshot ReadSnapshot(byte[] data) => PatternFiles.ReadSnapshot(this, data);

        /// <summary>A pattern file's text read into this universe's store as a snapshot.</summary>
        public PatternSnapshot ReadSnapshot(string text) => PatternFiles.ReadSnapshot(this, text);

        /// <summary>RLE of the bounding box behind a <c>#CXRLE</c> line; inside the editing box only.</summary>
        public string ToRle() => Patterns.HashLifeToRle(this);

        /// <summary>RLE with <paramref name="metadata"/>'s lines after the <c>#CXRLE</c> line.</summary>
        public string ToRle(PatternMetadata? metadata) => Patterns.HashLifeToRle(this, metadata);

        /// <summary>The canonical Macrocell text: the whole state, any size, in one string.</summary>
        public string ToMacrocell() => Macrocell.Write(this);

        /// <summary>The canonical Macrocell text with <paramref name="metadata"/>'s lines.</summary>
        public string ToMacrocell(PatternMetadata? metadata) => Macrocell.Write(this, metadata);

        /// <summary>The bytes of a pattern file named <paramref name="fileName"/>, by its extension:
        /// <c>.rle</c>, <c>.mc</c>, or <c>.mc.gz</c> (gzip of the canonical text).</summary>
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

        internal static string Latin1(byte[] data, int start, int length)
        {
            var chars = new char[length];
            for (int i = 0; i < length; i++)
                chars[i] = (char)data[start + i];
            return new string(chars);
        }

        // -- internals for the readers and writers ----------------------------------------------

        internal HashLifeStore Store => _store;

        internal void Adopt(int root, int level, BigInteger generation)
        {
            _store.Root = root;
            _store.Level = level;
            SetGeneration(generation);
            _version++;
        }

        /// <summary>
        /// Run <paramref name="fill"/> on an empty tree in this universe's store and give the tree
        /// it built, leaving the universe's own root, level and generation as they were: how a file
        /// is read into the store without becoming the state. Nothing collects outside a step, so
        /// the universe's own tree survives the building.
        /// </summary>
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

        /// <summary>The smallest centered root (level ≥ 3) that holds every live cell.</summary>
        internal (int Node, int Level) Minimal() => Minimal(_store.Root, _store.Level);

        /// <summary>The smallest centered root (level ≥ 3) holding every live cell of tree (n, k).</summary>
        internal (int Node, int Level) Minimal(int n, int k)
        {
            var s = _store;
            while (k > 3)
            {
                int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
                int middle;
                if (k == 4)
                {
                    ulong na = s.Bits(a), nb = s.Bits(b), nc = s.Bits(c), nd = s.Bits(d);
                    ulong sq = HashLifeLeaves.Square4;
                    if ((na & ~(sq << 36)) != 0 || (nb & ~(sq << 32)) != 0 || (nc & ~(sq << 4)) != 0 || (nd & ~sq) != 0)
                        break;
                    middle = s.Leaf(HashLifeLeaves.Inner(na, nb, nc, nd));
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
                    middle = s.Join(s.Kid(a, 3), s.Kid(b, 2), s.Kid(c, 1), s.Kid(d, 0));
                }
                n = middle;
                k--;
            }
            return (n, k);
        }

        /// <summary>Every non-empty leaf as (tree x, tree y, bitmap); the live cells must lie in
        /// the editing box.</summary>
        internal void CollectLeaves(List<(long X, long Y, ulong Bits)> leaves)
        {
            OpenWindow();
            for (int w = 0; w < _windowCount; w++)
                CollectLeavesIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w], leaves);
        }

        private void CollectLeavesIn(int n, int k, long nx, long ny, List<(long X, long Y, ulong Bits)> leaves)
        {
            var s = _store;
            if (n == s.Empty(k))
                return;
            if (k == 3)
            {
                leaves.Add((nx, ny, s.Bits(n)));
                return;
            }
            long half = 1L << (k - 1);
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            CollectLeavesIn(a, k - 1, nx, ny, leaves);
            CollectLeavesIn(b, k - 1, nx + half, ny, leaves);
            CollectLeavesIn(c, k - 1, nx, ny + half, leaves);
            CollectLeavesIn(d, k - 1, nx + half, ny + half, leaves);
        }

        internal static long BlockKey(long bx, long by) => (bx << 32) ^ (uint)by;

        /// <summary>Land leaf bitmaps keyed by <see cref="BlockKey"/> over the inclusive tree
        /// rectangle (x0, y0)..(x1, y1), which lies in the editing box.</summary>
        internal void PasteBlocks(Dictionary<long, ulong> blocks, long x0, long y0, long x1, long y1, HashLifePasteMode mode)
        {
            Contain(x0, y0, x1, y1);
            OpenWindow();
            // Which aligned nodes hold source cells, per level below the window's top.
            var tiers = new HashSet<long>?[_windowLevel];
            for (int level = 4; level < _windowLevel; level++)
            {
                var tier = new HashSet<long>();
                int shift = level - 3;
                foreach (long key in blocks.Keys)
                {
                    long bx = key >> 32, by = (int)(uint)key;
                    tier.Add(BlockKey(bx >> shift, by >> shift));
                }
                tiers[level] = tier;
            }
            _rx0 = x0;
            _ry0 = y0;
            _rx1 = x1;
            _ry1 = y1;
            _blocks = blocks;
            _tiers = tiers;
            _mode = mode;
            for (int w = 0; w < _windowCount; w++)
                _windowNode[w] = PasteIn(_windowNode[w], _windowLevel, _windowX[w], _windowY[w]);
            _blocks = null;
            _tiers = null;
            CloseWindow();
        }

        // -- tree walks (tree coordinates: y one less than the cell's) --------------------------

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

        private ulong LeafMask(long nx, long ny)
            => HashLifeLeaves.RectMask(
                (int)Math.Max(_rx0 - nx, 0), (int)Math.Min(_rx1 - nx, 7),
                (int)Math.Max(_ry0 - ny, 0), (int)Math.Min(_ry1 - ny, 7));

        private int SetIn(int n, int k, long x, long y, bool alive)
        {
            var s = _store;
            if (k == 3)
            {
                ulong bits = s.Bits(n);
                ulong mask = 1UL << (int)(y * 8 + x);
                return s.Leaf(alive ? bits | mask : bits & ~mask);
            }
            long half = 1L << (k - 1);
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            if (y < half)
            {
                if (x < half)
                    a = SetIn(a, k - 1, x, y, alive);
                else
                    b = SetIn(b, k - 1, x - half, y, alive);
            }
            else if (x < half)
            {
                c = SetIn(c, k - 1, x, y - half, alive);
            }
            else
            {
                d = SetIn(d, k - 1, x - half, y - half, alive);
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
            if (k == 3)
                return s.Leaf(s.Bits(n) & ~LeafMask(nx, ny));
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
            if (k == 3)
            {
                ulong old = s.Bits(n);
                _blocks!.TryGetValue(BlockKey(nx >> 3, ny >> 3), out ulong src);
                ulong bits = _mode == HashLifePasteMode.Copy ? (old & ~LeafMask(nx, ny)) | src
                    : _mode == HashLifePasteMode.Or ? old | src
                    : _mode == HashLifePasteMode.Xor ? old ^ src
                    : old & (src | ~LeafMask(nx, ny)); // And: in the rectangle only the source's cells stay
                return s.Leaf(bits);
            }
            HashSet<long>? tier = k < _tiers!.Length ? _tiers[k] : null;
            if (tier != null && !tier.Contains(BlockKey(nx >> k, ny >> k)))
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

        /// <summary>
        /// The inclusive rectangle's cells as <see cref="GetRect"/> gives them, anywhere on the plane,
        /// for readers that measured it first (spec/formats.md "Reading into a grid").
        /// </summary>
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

        /// <summary>Level-k node n, its origin at (rx, ry) from the rectangle's top-left tree
        /// position, into the w × h rectangle; long arithmetic once the node is small.</summary>
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
            if (k == 3)
            {
                ulong bits = s.Bits(n);
                for (int r = 0; r < 8; r++)
                {
                    long y = ry + r;
                    if (y < 0 || y >= h)
                        continue;
                    for (int c = 0; c < 8; c++)
                    {
                        long x = rx + c;
                        if (x >= 0 && x < w && ((bits >> (r * 8 + c)) & 1) != 0)
                            cells[y * w + x] = 1;
                    }
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
            if (k == 3)
            {
                ulong bits = s.Bits(n);
                long ix0 = Math.Max(nx, _rx0), iy0 = Math.Max(ny, _ry0);
                long ix1 = Math.Min(nx + 7, _rx1), iy1 = Math.Min(ny + 7, _ry1);
                long width = _rx1 - _rx0 + 1;
                byte[] cells = _extract!;
                for (long iy = iy0; iy <= iy1; iy++)
                {
                    int row = (int)(iy - ny) * 8;
                    long rowStart = (iy - _ry0) * width - _rx0;
                    for (long ix = ix0; ix <= ix1; ix++)
                        cells[rowStart + ix] = (byte)((bits >> (row + (int)(ix - nx))) & 1);
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

        /// <summary>Live cells of level-k node n (k ≤ 31) in the inclusive rectangle relative to
        /// its origin, which lies inside it.</summary>
        private long CountLong(int n, int k, long x0, long y0, long x1, long y1)
        {
            var s = _store;
            if (n == s.Empty(k))
                return 0;
            long size = 1L << k;
            if (x0 == 0 && y0 == 0 && x1 == size - 1 && y1 == size - 1)
                return s.PopLong(n, k);
            if (k == 3)
                return HashLifeLeaves.PopCount(s.Bits(n) & HashLifeLeaves.RectMask((int)x0, (int)x1, (int)y0, (int)y1));
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
        // about its own center, by the kinds above.
        private static readonly int[][] TransformOrder =
        {
            new[] { 2, 0, 3, 1 },
            new[] { 1, 3, 0, 2 },
            new[] { 1, 0, 3, 2 },
            new[] { 2, 3, 0, 1 },
        };

        /// <summary>Throw unless the inclusive rectangle lies in the editing box and is not empty.</summary>
        private static void CheckEditRect(long x0, long y0, long x1, long y1)
        {
            CheckBox(x0, y0, x1, y1);
            if (x1 < x0 || y1 < y0)
                throw new ArgumentException($"empty rectangle ({x0}, {y0})..({x1}, {y1})");
        }

        /// <summary>The inclusive tree rectangle the walks below test nodes against.</summary>
        private void SetBounds(long x0, long y0, long x1, long y1)
        {
            _rx0 = x0;
            _ry0 = y0;
            _rx1 = x1;
            _ry1 = y1;
        }

        /// <summary>
        /// Lift the cells of the old rectangle (cell coordinates), turn or mirror them about the
        /// box node's center, move them by (dx, dy) in tree coordinates onto the new rectangle, and
        /// paste them there by copy; the rest of the old rectangle dies.
        /// </summary>
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

        /// <summary>The centered level-32 node that holds the editing box, joined from the four
        /// windows; the root first grows to level 33 if it is smaller.</summary>
        private int OpenBox()
        {
            while (_store.Level < WindowLevel + 2)
                Expand();
            OpenWindow();
            return _store.Join(_windowNode[0], _windowNode[1], _windowNode[2], _windowNode[3]);
        }

        /// <summary>Put an edited box node from <see cref="OpenBox"/> back into the tree.</summary>
        private void CloseBox(int box)
        {
            for (int q = 0; q < 4; q++)
                _windowNode[q] = _store.Kid(box, q);
            CloseWindow();
        }

        /// <summary>The four level-31 windows of a centered root of level ≥ 33, as
        /// <see cref="OpenWindow"/> finds them.</summary>
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
            HashLifeSnapshot saved = Snapshot(); // a collection inside the step keeps the original's nodes
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
                saved.Release(); // the universe holds its nodes again, so it pins nothing past here
            }
            int level = Math.Max(Math.Max(grownLevel, s.Level), WindowLevel + 2);
            while (s.Level < level)
                Expand();
            while (grownLevel < level)
                grown = ExpandNode(grown, grownLevel++);
            // The tree outside the windows comes from the outside's source; the rectangle, which
            // lies in the windows, from the inside's.
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

        /// <summary>Node n with every cell outside the bounds cleared.</summary>
        private int KeepIn(int n, int k, long nx, long ny)
        {
            var s = _store;
            long size = 1L << k;
            int e = s.Empty(k);
            if (n == e || Disjoint(nx, ny, size))
                return e;
            if (Covers(nx, ny, size))
                return n;
            if (k == 3)
                return s.Leaf(s.Bits(n) & LeafMask(nx, ny));
            long half = size >> 1;
            int a = s.Kid(n, 0), b = s.Kid(n, 1), c = s.Kid(n, 2), d = s.Kid(n, 3);
            return s.Join(
                KeepIn(a, k - 1, nx, ny),
                KeepIn(b, k - 1, nx + half, ny),
                KeepIn(c, k - 1, nx, ny + half),
                KeepIn(d, k - 1, nx + half, ny + half));
        }

        /// <summary>Two aligned level-k nodes made one: the inside's cells within the bounds, the
        /// outside's everywhere else.</summary>
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
            if (k == 3)
            {
                ulong mask = LeafMask(nx, ny);
                return s.Leaf((s.Bits(inside) & mask) | (s.Bits(outside) & ~mask));
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

        /// <summary>Level-k node n turned or mirrored about its own center.</summary>
        private int Transform(int n, int k, int kind, Dictionary<int, int> memo)
        {
            if (memo.TryGetValue(n, out int hit))
                return hit;
            var s = _store;
            int r;
            if (k == 3)
            {
                ulong b = s.Bits(n);
                r = s.Leaf(kind == TurnClockwise ? HashLifeLeaves.TurnCw(b)
                    : kind == TurnCounterClockwise ? HashLifeLeaves.TurnCcw(b)
                    : kind == MirrorLeftRight ? HashLifeLeaves.MirrorColumns(b)
                    : HashLifeLeaves.MirrorRows(b));
            }
            else if (n == s.Empty(k))
            {
                r = n;
            }
            else
            {
                int[] order = TransformOrder[kind];
                int nw = Transform(s.Kid(n, order[0]), k - 1, kind, memo);
                int ne = Transform(s.Kid(n, order[1]), k - 1, kind, memo);
                int sw = Transform(s.Kid(n, order[2]), k - 1, kind, memo);
                int se = Transform(s.Kid(n, order[3]), k - 1, kind, memo);
                r = s.Join(nw, ne, sw, se);
            }
            memo[n] = r;
            return r;
        }

        /// <summary>Centered level-k node n with every cell moved by (dx, dy),
        /// |dx|, |dy| ≤ 2^(k−1). A cell moved past the node's edge is lost; callers leave room.</summary>
        private int Shifted(int n, int k, long dx, long dy)
        {
            var s = _store;
            int big = ExpandNode(n, k);
            long half = 1L << (k - 1);
            return Crop(
                k, s.Kid(big, 0), s.Kid(big, 1), s.Kid(big, 2), s.Kid(big, 3), half - dx, half - dy,
                new Dictionary<CropKey, int>());
        }

        /// <summary>The level-k node at offset (ox, oy), 0 ≤ ox, oy ≤ 2^k, in the square of the four
        /// aligned level-k nodes a b over c d.</summary>
        private int Crop(int k, int a, int b, int c, int d, long ox, long oy, Dictionary<CropKey, int> memo)
        {
            long size = 1L << k;
            if ((ox == 0 || ox == size) && (oy == 0 || oy == size))
                return ox == 0 ? (oy == 0 ? a : c) : (oy == 0 ? b : d);
            var s = _store;
            int e = s.Empty(k);
            if (a == e && b == e && c == e && d == e)
                return e;
            var key = new CropKey(k, a, b, c, d, ox, oy);
            if (memo.TryGetValue(key, out int hit))
                return hit;
            int r;
            if (k == 3)
            {
                r = s.Leaf(HashLifeLeaves.Crop(s.Bits(a), s.Bits(b), s.Bits(c), s.Bits(d), (int)ox, (int)oy));
            }
            else
            {
                // The sixteen grandchildren, four rows of four.
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

        /// <summary>A <see cref="Crop"/> call's arguments, as its memo's key.</summary>
        private readonly struct CropKey : IEquatable<CropKey>
        {
            private readonly int _k, _a, _b, _c, _d;
            private readonly long _ox, _oy;

            internal CropKey(int k, int a, int b, int c, int d, long ox, long oy)
            {
                _k = k;
                _a = a;
                _b = b;
                _c = c;
                _d = d;
                _ox = ox;
                _oy = oy;
            }

            public bool Equals(CropKey other)
                => _a == other._a && _b == other._b && _c == other._c && _d == other._d
                    && _k == other._k && _ox == other._ox && _oy == other._oy;

            public override bool Equals(object? obj) => obj is CropKey other && Equals(other);

            public override int GetHashCode() => HashCode.Combine(_k, _a, _b, _c, _d, _ox, _oy);
        }

        /// <summary>One extreme of node n's live cells inside the inclusive tree rectangle
        /// (x0, y0)..(x1, y1), as a tree coordinate, or null when it holds none. The near half is
        /// searched first: anything found there beats everything in the far half.</summary>
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

        /// <summary>One extreme of the live cells of level-k node n (k ≤ 62) inside the inclusive
        /// rectangle (x0, y0)..(x1, y1), relative to its origin and lying inside it, as an offset
        /// from that origin, or −1 when it holds none.</summary>
        private long ExtremeLong(int n, int k, long x0, long y0, long x1, long y1, int edge)
        {
            var s = _store;
            if (n == s.Empty(k))
                return -1;
            long size = 1L << k;
            if (x0 == 0 && y0 == 0 && x1 == size - 1 && y1 == size - 1)
                return EdgeLong(n, k, edge);
            if (k == 3)
            {
                ulong bits = s.Bits(n) & HashLifeLeaves.RectMask((int)x0, (int)x1, (int)y0, (int)y1);
                return bits == 0 ? -1 : HashLifeLeaves.Edge(bits, edge);
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

        // -- the bounding box -------------------------------------------------------------------

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

        // Per edge (min x, max x, min y, max y): the near children, then the far ones half a node
        // further along the axis (Python's _EDGES).
        private static readonly int[][] EdgeNear = { new[] { 0, 2 }, new[] { 1, 3 }, new[] { 0, 1 }, new[] { 2, 3 } };
        private static readonly int[][] EdgeFar = { new[] { 1, 3 }, new[] { 0, 2 }, new[] { 2, 3 }, new[] { 0, 1 } };

        /// <summary>One extreme of the live cells of non-empty level-k node n (k ≤ 62), as an
        /// offset from its origin.</summary>
        private long EdgeLong(int n, int k, int edge)
        {
            if (_edgeMemo.TryGetValue(n, out long hit))
                return hit;
            var s = _store;
            bool lowest = edge == 0 || edge == 2;
            long r;
            if (k == 3)
            {
                r = HashLifeLeaves.Edge(s.Bits(n), edge);
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
        /// row-major) without allocating (spec/hashlife.md "View and render"): at
        /// <c>Mag ≥ 0</c> 255 for a live cell over its 2^Mag-pixel square, else 0; zoomed out, one
        /// aligned block of 2^−Mag cells per pixel, 255 when it holds a live cell
        /// (<see cref="HashLifeRenderMode.Any"/>) or ⌈255 · population / 4^−Mag⌉
        /// (<see cref="HashLifeRenderMode.Density"/>). The walk visits only the blocks in view,
        /// so a frame costs the same at any scale and any distance from the origin.
        /// </summary>
        public void WriteFrame(
            byte[] frame, int width, int height, LifeView view, HashLifeRenderMode mode = HashLifeRenderMode.Any)
        {
            if (frame == null)
                throw new ArgumentNullException(nameof(frame));
            if (width < 1 || height < 1 || width > 1 << Phase2Bits || height > 1 << Phase2Bits)
                throw new ArgumentOutOfRangeException(nameof(width), $"frame size must be positive, got {width} x {height}");
            if (frame.Length < (long)width * height)
                throw new ArgumentException($"frame holds {frame.Length} bytes, needs {(long)width * height}", nameof(frame));
            if (mode != HashLifeRenderMode.Any && mode != HashLifeRenderMode.Density)
                throw new ArgumentOutOfRangeException(nameof(mode), mode, "unknown render mode");
            Array.Clear(frame, 0, width * height);
            _frame = frame;
            _frameWidth = width;
            _frameHeight = height;
            _fDensity = mode == HashLifeRenderMode.Density;
            if (view.Mag < 0)
            {
                // Blocks of 2^s × 2^s cells, one per pixel.
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
                // Cells, each a 2^p-pixel square: the target is the cells the frame touches.
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
            // The root spans at most 2^31 blocks around the origin; a frame starting past 2^61
            // cannot reach it.
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

        /// <summary>A newly allocated frame of <paramref name="view"/>; see <see cref="WriteFrame"/>.</summary>
        public byte[] Frame(int width, int height, LifeView view, HashLifeRenderMode mode = HashLifeRenderMode.Any)
        {
            if (width < 1 || height < 1)
                throw new ArgumentOutOfRangeException(nameof(width), $"frame size must be positive, got {width} x {height}");
            var frame = new byte[(long)width * height];
            WriteFrame(frame, width, height, view, mode);
            return frame;
        }

        /// <summary>Along one axis, whether the node at relative index rel (0 or 1 matter) with
        /// 2^d blocks overlaps the target's first <paramref name="count"/> blocks, d > 30.</summary>
        private static bool InTop(ref Coord c, int rel, int d, long count)
            => rel == 0 || (rel == 1 && c.Crosses(d, count));

        /// <summary>The walk while nodes span more than 2^30 blocks: per axis the node's index
        /// relative to the target's start is 0 or 1, and a child's follows from one bit of the
        /// target (rel' = 2·rel + c − bit(d − 1)), so no coordinate is ever formed.</summary>
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

        /// <summary>The walk once nodes span at most 2^30 blocks: (ox, oy) is the node's first
        /// block relative to the target's.</summary>
        private void VisitNear(int n, int m, long ox, long oy)
        {
            var s = _store;
            if (n == s.Empty(m))
                return;
            if (m == _fs)
            {
                // s ≥ 3: this node is one pixel.
                _frame[oy * _frameWidth + ox] = _fDensity ? s.Density(n, m) : (byte)255;
                return;
            }
            if (m == 3)
            {
                LeafPixels(s.Bits(n), ox, oy);
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

        private static readonly ulong[][] BlockMasks = BuildBlockMasks();

        private static ulong[][] BuildBlockMasks()
        {
            var masks = new ulong[3][];
            for (int s = 1; s <= 2; s++)
            {
                int per = 8 >> s, side = 1 << s;
                masks[s] = new ulong[per * per];
                for (int by = 0; by < per; by++)
                    for (int bx = 0; bx < per; bx++)
                        masks[s][by * per + bx] = HashLifeLeaves.RectMask(
                            bx * side, bx * side + side - 1, by * side, by * side + side - 1);
            }
            return masks;
        }

        /// <summary>A leaf's pixels: its live cells as squares (zoomed in), or its 2^s blocks
        /// (s = 1, 2) as pixels.</summary>
        private void LeafPixels(ulong bits, long ox, long oy)
        {
            byte[] frame = _frame;
            int width = _frameWidth;
            if (_fs == 0)
            {
                int p = _fp;
                long side = 1L << p;
                while (bits != 0)
                {
                    int i = TrailingZeros(bits);
                    bits &= bits - 1;
                    long cx = ox + (i & 7), cy = oy + (i >> 3);
                    if (cx < 0 || cx >= _ftw || cy < 0 || cy >= _fth)
                        continue;
                    long px0 = Math.Max((cx << p) - _fox, 0), px1 = Math.Min((cx << p) - _fox + side, width);
                    long py0 = Math.Max((cy << p) - _foy, 0), py1 = Math.Min((cy << p) - _foy + side, _frameHeight);
                    for (long py = py0; py < py1; py++)
                        for (long px = px0; px < px1; px++)
                            frame[py * width + px] = 255;
                }
                return;
            }
            int s = _fs;
            int per = 8 >> s;
            ulong[] masks = BlockMasks[s];
            int area = 2 * s;
            for (int by = 0; by < per; by++)
            {
                long py = oy + by;
                if (py < 0 || py >= _fth)
                    continue;
                for (int bx = 0; bx < per; bx++)
                {
                    long px = ox + bx;
                    if (px < 0 || px >= _ftw)
                        continue;
                    int pop = HashLifeLeaves.PopCount(bits & masks[by * per + bx]);
                    if (pop == 0)
                        continue;
                    frame[py * width + px] = _fDensity ? (byte)((255 * pop + (1 << area) - 1) >> area) : (byte)255;
                }
            }
        }

        private static readonly int[] DeBruijn = BuildDeBruijn();

        private static int[] BuildDeBruijn()
        {
            var table = new int[64];
            for (int i = 0; i < 64; i++)
                table[(int)(((1UL << i) * 0x03F79D71B4CB0A89UL) >> 58)] = i;
            return table;
        }

        private static int TrailingZeros(ulong v) => DeBruijn[(int)(((v & (ulong)-(long)v) * 0x03F79D71B4CB0A89UL) >> 58)];

        /// <summary>
        /// One frame coordinate (a block or cell index) as two's-complement bits, read without
        /// forming the number: a long when it fits, else bytes written into a reused buffer.
        /// </summary>
        internal struct Coord
        {
            internal bool Small;
            internal long Value;      // the coordinate, when Small
            private byte[]? _bytes;   // the unshifted source, when not
            private int _length;
            private int _offset;      // source bits dropped (the zoom shift)
            private bool _negative;
            private int _low30;       // bits 0..29
            private int _significant; // bits from here up all equal the sign
            private int _zeroFrom30;  // the lowest clear bit at or above 30 (int.MaxValue: none)
            internal long DroppedBits; // the source's low bits under the shift

            internal void Set(BigInteger source, int shift, ref byte[] buffer)
            {
                if (source >= long.MinValue && source <= long.MaxValue)
                {
                    long v = (long)source;
                    Small = true;
                    Value = v >> shift;
                    DroppedBits = v & ((1L << shift) - 1);
                    _negative = Value < 0;
                    _bytes = null;
                    long magnitude = Value ^ (Value >> 63);
                    int bits = 0;
                    while (magnitude != 0)
                    {
                        magnitude >>= 1;
                        bits++;
                    }
                    _significant = bits;
                }
                else
                {
                    int count = source.GetByteCount();
                    if (buffer.Length < count)
                        buffer = new byte[Math.Max(count, buffer.Length * 2)];
                    source.TryWriteBytes(buffer, out _length);
                    Small = false;
                    Value = 0;
                    _bytes = buffer;
                    _offset = shift;
                    _negative = source.Sign < 0;
                    long dropped = 0;
                    for (int i = 0; i < shift; i++)
                        dropped |= (long)RawBit(i) << i;
                    DroppedBits = dropped;
                    _significant = 0;
                    int sign = _negative ? 1 : 0;
                    for (int i = _length * 8 - shift - 1; i >= 0; i--)
                    {
                        if (Bit(i) != sign)
                        {
                            _significant = i + 1;
                            break;
                        }
                    }
                }
                int low = 0;
                for (int i = 0; i < 30; i++)
                    low |= Bit(i) << i;
                _low30 = low;
                int z = 30;
                while (true)
                {
                    if (z >= _significant)
                    {
                        _zeroFrom30 = _negative ? int.MaxValue : z;
                        break;
                    }
                    if (Bit(z) == 0)
                    {
                        _zeroFrom30 = z;
                        break;
                    }
                    z++;
                }
            }

            private int RawBit(int i)
            {
                int index = i >> 3;
                return index < _length ? (_bytes![index] >> (i & 7)) & 1 : _negative ? 1 : 0;
            }

            /// <summary>Bit i of the coordinate (sign-extended).</summary>
            internal int Bit(int i)
            {
                if (Small)
                    return i >= 63 ? (_negative ? 1 : 0) : (int)((Value >> i) & 1);
                return RawBit(i + _offset);
            }

            /// <summary>The coordinate mod 2^d, d ≤ 30.</summary>
            internal long Low(int d) => _low30 & ((1L << d) - 1);

            /// <summary>The coordinate >> d when that lies in [−2, 1].</summary>
            internal bool TopQuotient(int d, out int quotient)
            {
                if (d + 1 < _significant)
                {
                    quotient = 0;
                    return false;
                }
                quotient = (_negative ? -2 : 0) + Bit(d);
                return true;
            }

            /// <summary>Whether a run of <paramref name="count"/> blocks starting here crosses the
            /// next multiple of 2^d (d > 30, count ≤ 2^30): 2^d − (coordinate mod 2^d) &lt; count.</summary>
            internal bool Crosses(int d, long count)
                => _zeroFrom30 >= d && _low30 > (1L << 30) - count;
        }
    }
}
