using System;
using System.Collections.Generic;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// The multi-state node store (spec/hashlife-multistate.md "Quadtree", "Evolution";
    /// spec/hashlife.md "Memory"): hash-consed quadtree nodes whose leaves hold states, in one int
    /// arena, their memoized futures, and a collector that can run in the middle of a step. It is
    /// the two-state <see cref="HashLifeStore"/>'s design with other leaves:
    ///
    /// <list type="bullet">
    /// <item>A node is an 8-int record at <c>id * 8</c> in <see cref="Nodes"/>: four children (a
    /// leaf, a level-1 node, keeps its four states packed in the first, NW in bits 0–7 up to SE in
    /// bits 24–31, and <see cref="LeafTag"/> in the fourth), a population, the full-speed result,
    /// the fixed-step result, and an info word: the level (bits 0–9), the j the fixed-step result
    /// belongs to plus one (bits 10–18), the shown state of the zoomed-out frames plus one (bits
    /// 19–27, under <see cref="Ranks"/>), and the collector's mark bit (bit 31).</item>
    /// <item>The rule enters in one place: a level-2 node's center one generation on, from four
    /// calls of the cell function, cached as the node's full-speed result.</item>
    /// <item>Hash-consing, growth up to the budget, collection in flight with a saved-node
    /// stack, and cancellation are the two-state store's, line for line.</item>
    /// </list>
    ///
    /// Nothing here is observable: the spec pins cells, never layout.
    /// </summary>
    internal sealed class MultiStateStore
    {
        internal const int Stride = 8;
        internal const int Nw = 0, Ne = 1, Sw = 2, Se = 3; // children; a leaf: its states, 0, -1, LeafTag
        private const int Pop = 4;  // population if it fits an int, -1 unknown, -2 in _longPop; a free record: the next free id
        private const int Res = 5;  // the full-speed result, -1 none
        private const int Slow = 6; // the fixed-step result for the j in Info's tag, -1 none
        private const int Info = 7; // level (bits 0-9), tag j + 1 (bits 10-18), shown + 1 (bits 19-27), mark (bit 31)
        internal const int LeafTag = -1;
        private const int FreeTag = -2;
        private const int LevelMask = 0x3FF;
        private const int TagShift = 10;
        private const int TagMask = 0x1FF << TagShift;
        private const int ShownShift = 19;
        private const int ShownMask = 0x1FF << ShownShift;
        private const int MarkBit = int.MinValue;
        private const int CheckEvery = 4096; // allocations between cancellation checks

        /// <summary>The store's accounting: a 32-byte record plus 8 bytes of hash table.</summary>
        internal const int BytesPerNode = 40;

        /// <summary>The largest arena: its record array stays under 2^31 ints.</summary>
        internal const int MaxCapacity = (1 << 28) - 16;

        private const int InitialCapacity = 1 << 12;

        internal int[] Nodes;
        private int[] _table;
        private int _tableMask;
        private int _tableVersion;
        private int _capacity;
        private int _used; // records ever handed out (the high-water mark)
        private int _free = -1;
        private int _live;
        private int _tick = CheckEvery;
        private int[] _empty = new int[64];
        private int _emptyCount;
        private int[] _stack = new int[1024];
        private int _sp;
        private int[] _markStack = new int[1024];
        private readonly Dictionary<int, long> _longPop = new Dictionary<int, long>();
        private readonly Dictionary<int, BigInteger> _bigPop = new Dictionary<int, BigInteger>();
        private readonly Dictionary<int, byte> _bigDensity = new Dictionary<int, byte>();
        // Odd cells of nodes of level 4 and up, asked for only under History and Super rules
        // (spec/hashlife-multistate.md "Observables"); levels 1 to 3 are counted when asked.
        private readonly Dictionary<int, long> _oddPop = new Dictionary<int, long>();
        private readonly Dictionary<int, BigInteger> _bigOddPop = new Dictionary<int, BigInteger>();

        /// <summary>The rule whose cell function the base case runs.</summary>
        internal StateRule Rule;

        /// <summary>Each state's place in the zoom order, lower first; state 0 is 256, after all
        /// (spec/hashlife-multistate.md "View and render").</summary>
        internal readonly int[] Ranks = new int[256];

        /// <summary>Live nodes a step may hold before it collects (the memory budget).</summary>
        internal int MaxNodes;

        /// <summary>The universe's root and its level, the collector's first root.</summary>
        internal int Root;
        internal int Level;

        /// <summary>Snapshots pin their roots for as long as they live and aren't released.</summary>
        internal readonly List<WeakReference<HashLifeSnapshot>> Snapshots = new List<WeakReference<HashLifeSnapshot>>();

        /// <summary>True while a step computes: allocation may collect in flight or abort.</summary>
        internal bool Guard;

        /// <summary>In-flight collections the current sub-step may run before it is abandoned.</summary>
        internal int ThrashLimit = int.MaxValue;

        private int _attemptCollections;

        internal CancellationToken Cancel;

        internal int Collections;

        /// <summary>Collections run in the middle of a step, and steps abandoned for lack of room
        /// (both for tests: neither is observable).</summary>
        internal int InFlightCollections;
        internal int Aborts;

        internal MultiStateStore(StateRule rule, int maxNodes, int minLevel)
        {
            Rule = rule;
            MaxNodes = maxNodes;
            _capacity = InitialCapacity;
            Nodes = new int[_capacity * Stride];
            _table = new int[TableSizeFor(_capacity)];
            _tableMask = _table.Length - 1;
            Array.Fill(_table, -1);
            _empty[0] = -1;
            _empty[1] = Leaf(0);
            _emptyCount = 2;
            Root = Empty(minLevel);
            Level = minLevel;
            SetOrder(Array.Empty<byte>());
        }

        internal int Live => _live;

        // -- nodes ------------------------------------------------------------------------------

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal int Kid(int n, int quadrant) => Nodes[n * Stride + quadrant];

        /// <summary>A leaf's four states, packed: NW in bits 0–7, NE 8–15, SW 16–23, SE 24–31.</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal int States(int leaf) => Nodes[leaf * Stride];

        internal int Empty(int k)
        {
            while (_emptyCount <= k)
            {
                if (_emptyCount == _empty.Length)
                    Array.Resize(ref _empty, _empty.Length * 2);
                int z = _empty[_emptyCount - 1];
                _empty[_emptyCount] = Join(z, z, z, z);
                _emptyCount++;
            }
            return _empty[k];
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static uint Mix(ulong h)
        {
            h ^= h >> 31;
            h *= 0x7FB5D329728EA185UL;
            h ^= h >> 27;
            return (uint)(h >> 32);
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static uint HashKids(int nw, int ne, int sw, int se)
            => Mix((ulong)(uint)nw * 0x9E3779B97F4A7C15UL
                + (ulong)(uint)ne * 0xC2B2AE3D27D4EB4FUL
                + (ulong)(uint)sw * 0x165667B19E3779F9UL
                + (ulong)(uint)se * 0xD6E8FEB86659FD93UL);

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static uint HashLeaf(int states) => Mix((ulong)(uint)states * 0xA0761D6478BD642FUL + 1);

        /// <summary>A table entry is an id (below 2^28) with three bits of its hash above it, so a
        /// probe skips most mismatches without reading a record.</summary>
        private const int IdMask = (1 << 28) - 1;

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static int Fingerprint(uint h) => (int)(h >> 29) << 28;

        /// <summary>The leaf with these packed states.</summary>
        internal int Leaf(int states)
        {
            uint h = HashLeaf(states);
            int[] nodes = Nodes, table = _table;
            int mask = _tableMask;
            int i = (int)(h & (uint)mask);
            int fingerprint = Fingerprint(h);
            while (true)
            {
                int entry = table[i];
                if (entry < 0)
                    break;
                if ((entry & ~IdMask) == fingerprint)
                {
                    int o = (entry & IdMask) * Stride;
                    if (nodes[o + Se] == LeafTag && nodes[o] == states)
                        return entry & IdMask;
                }
                i = (i + 1) & mask;
            }
            int version = _tableVersion;
            int m = Alloc();
            nodes = Nodes;
            int mo = m * Stride;
            nodes[mo] = states;
            nodes[mo + Ne] = 0;
            nodes[mo + Sw] = -1;
            nodes[mo + Se] = LeafTag;
            nodes[mo + Pop] = -1;
            nodes[mo + Res] = -1;
            nodes[mo + Slow] = -1;
            nodes[mo + Info] = 1;
            if (version != _tableVersion)
                i = OpenSlot(h);
            _table[i] = m | fingerprint;
            return m;
        }

        /// <summary>The node with these children (all one level, at least 1).</summary>
        internal int Join(int nw, int ne, int sw, int se)
        {
            uint h = HashKids(nw, ne, sw, se);
            int[] nodes = Nodes, table = _table;
            int mask = _tableMask;
            int i = (int)(h & (uint)mask);
            int fingerprint = Fingerprint(h);
            while (true)
            {
                int entry = table[i];
                if (entry < 0)
                    break;
                if ((entry & ~IdMask) == fingerprint)
                {
                    int o = (entry & IdMask) * Stride;
                    if (nodes[o + Se] == se && nodes[o] == nw && nodes[o + Ne] == ne && nodes[o + Sw] == sw)
                        return entry & IdMask;
                }
                i = (i + 1) & mask;
            }
            int version = _tableVersion;
            int m = Alloc();
            nodes = Nodes;
            int mo = m * Stride;
            nodes[mo] = nw;
            nodes[mo + Ne] = ne;
            nodes[mo + Sw] = sw;
            nodes[mo + Se] = se;
            nodes[mo + Pop] = -1;
            nodes[mo + Res] = -1;
            nodes[mo + Slow] = -1;
            nodes[mo + Info] = (nodes[nw * Stride + Info] & LevelMask) + 1;
            if (version != _tableVersion)
                i = OpenSlot(h);
            _table[i] = m | fingerprint;
            return m;
        }

        private int OpenSlot(uint h)
        {
            int[] table = _table;
            int mask = _tableMask;
            int i = (int)(h & (uint)mask);
            while (table[i] >= 0)
                i = (i + 1) & mask;
            return i;
        }

        private int Alloc()
        {
            if (--_tick <= 0)
            {
                _tick = CheckEvery;
                if (Guard && Cancel.IsCancellationRequested)
                    throw new HashLifeStore.AbortException(canceled: true);
            }
            if ((_free < 0 && _used == _capacity) || (Guard && _live >= MaxNodes))
                MakeRoom();
            int n;
            if (_free >= 0)
            {
                n = _free;
                _free = Nodes[n * Stride + Pop];
            }
            else
            {
                n = _used++;
            }
            _live++;
            return n;
        }

        /// <summary>
        /// Grow the arena, or — inside a step at the budget — collect in flight, as the two-state
        /// store does: the step is abandoned when a collection leaves less than an eighth of the
        /// budget free, or when a sub-step that could still be split keeps collecting.
        /// </summary>
        private void MakeRoom()
        {
            if (Guard && (_live >= MaxNodes || _capacity >= MaxNodes))
            {
                Collect(inFlight: true);
                InFlightCollections++;
                _attemptCollections++;
                if (_live > MaxNodes - (MaxNodes >> 3) || _attemptCollections > ThrashLimit)
                {
                    Aborts++;
                    throw new HashLifeStore.AbortException(canceled: false);
                }
                if (_free >= 0 || _used < _capacity)
                    return;
            }
            if (_capacity >= MaxCapacity)
                throw new OutOfMemoryException(
                    $"the multi-state HashLife store is at its largest size ({MaxCapacity} nodes)");
            long grown = (long)_capacity * 2;
            if (Guard)
                grown = Math.Min(grown, Math.Max(MaxNodes, _capacity + 1));
            Grow((int)Math.Min(grown, MaxCapacity));
        }

        private void Grow(int capacity)
        {
            var nodes = new int[(long)capacity * Stride];
            Array.Copy(Nodes, nodes, (long)_used * Stride);
            Nodes = nodes;
            _capacity = capacity;
            int size = TableSizeFor(capacity);
            if (size != _table.Length)
            {
                _table = new int[size];
                _tableMask = size - 1;
                Rehash();
            }
        }

        private static int TableSizeFor(int capacity)
        {
            int size = 1;
            while (size < capacity * 2L)
                size <<= 1;
            return size;
        }

        private void Rehash()
        {
            int[] nodes = Nodes, table = _table;
            int mask = _tableMask;
            Array.Fill(table, -1);
            for (int n = 0; n < _used; n++)
            {
                int o = n * Stride;
                int se = nodes[o + Se];
                if (se == FreeTag)
                    continue;
                uint h = se == LeafTag ? HashLeaf(nodes[o]) : HashKids(nodes[o], nodes[o + Ne], nodes[o + Sw], se);
                int i = (int)(h & (uint)mask);
                while (table[i] >= 0)
                    i = (i + 1) & mask;
                table[i] = n | Fingerprint(h);
            }
            _tableVersion++;
        }

        // -- results ----------------------------------------------------------------------------

        /// <summary>Switch rules: cells survive, every cached result goes.</summary>
        internal void UseRule(StateRule rule)
        {
            Rule = rule;
            int[] nodes = Nodes;
            for (int n = 0; n < _used; n++)
            {
                int o = n * Stride;
                int se = nodes[o + Se];
                if (se == FreeTag || se == LeafTag)
                    continue;
                nodes[o + Res] = -1;
                nodes[o + Slow] = -1;
                nodes[o + Info] &= ~TagMask;
            }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal int Push(int n)
        {
            if (_sp == _stack.Length)
                Array.Resize(ref _stack, _stack.Length * 2);
            _stack[_sp++] = n;
            return n;
        }

        /// <summary>The saved stack's depth, to pop back to after pushing intermediates.</summary>
        internal int StackDepth
        {
            get => _sp;
            set => _sp = value;
        }

        /// <summary>Start a guarded computation (a sub-step): allocation may now collect in flight
        /// or abort. <paramref name="thrashLimit"/> bounds its in-flight collections.</summary>
        internal void BeginGuard(int thrashLimit)
        {
            Guard = true;
            ThrashLimit = thrashLimit;
            _attemptCollections = 0;
        }

        /// <summary>End a guarded computation: drop the saved stack.</summary>
        internal void EndGuard()
        {
            Guard = false;
            _sp = 0;
        }

        /// <summary>
        /// Level-k node n (k ≥ 2) → the level-(k−1) node at its center, 2^(k−2) generations on
        /// (spec/hashlife.md "Full speed"). At level 2 this is the base case
        /// (spec/hashlife-multistate.md "Evolution"): the four center cells, each the cell
        /// function of its 3 × 3 block. n must be held (reachable from a root or on the saved
        /// stack); the result comes back pushed on the saved stack.
        /// </summary>
        internal int Full(int n, int k)
        {
            int o = n * Stride;
            int[] nodes = Nodes;
            int r = nodes[o + Res];
            if (r >= 0)
                return Push(r);
            if (k == 2)
            {
                int la = nodes[nodes[o] * Stride], lb = nodes[nodes[o + Ne] * Stride];
                int lc = nodes[nodes[o + Sw] * Stride], ld = nodes[nodes[o + Se] * Stride];
                if ((la | lb | lc | ld) == 0)
                {
                    r = _empty[1]; // f(0, …, 0) = 0
                }
                else
                {
                    // The 4 × 4 square, row by row: a0 a1 b0 b1 / a2 a3 b2 b3 / c0 c1 d0 d1 / c2 c3 d2 d3.
                    byte a0 = (byte)la, a1 = (byte)(la >> 8), a2 = (byte)(la >> 16), a3 = (byte)(la >> 24);
                    byte b0 = (byte)lb, b1 = (byte)(lb >> 8), b2 = (byte)(lb >> 16), b3 = (byte)(lb >> 24);
                    byte c0 = (byte)lc, c1 = (byte)(lc >> 8), c2 = (byte)(lc >> 16), c3 = (byte)(lc >> 24);
                    byte d0 = (byte)ld, d1 = (byte)(ld >> 8), d2 = (byte)(ld >> 16), d3 = (byte)(ld >> 24);
                    StateRule f = Rule;
                    int nw = f.NextState(a0, a1, b0, a2, a3, b2, c0, c1, d0);
                    int ne = f.NextState(a1, b0, b1, a3, b2, b3, c1, d0, d1);
                    int sw = f.NextState(a2, a3, b2, c0, c1, d0, c2, c3, d2);
                    int se = f.NextState(a3, b2, b3, c1, d0, d1, c3, d2, d3);
                    r = Leaf(nw | ne << 8 | sw << 16 | se << 24);
                }
                Nodes[o + Res] = r;
                return Push(r);
            }
            int sp = _sp;
            int na0 = nodes[o], nb0 = nodes[o + Ne], nc0 = nodes[o + Sw], nd0 = nodes[o + Se];
            int ao = na0 * Stride, bo = nb0 * Stride, co = nc0 * Stride, dob = nd0 * Stride;
            int a2x = nodes[ao + Ne], a3x = nodes[ao + Sw], a4 = nodes[ao + Se];
            int b1x = nodes[bo], b3x = nodes[bo + Sw], b4 = nodes[bo + Se];
            int c1x = nodes[co], c2x = nodes[co + Ne], c4 = nodes[co + Se];
            int d1x = nodes[dob], d2x = nodes[dob + Ne], d3x = nodes[dob + Sw];
            int k1 = k - 1;
            int r00 = Full(na0, k1);
            int r01 = Full(Push(Join(a2x, b1x, a4, b3x)), k1);
            int r02 = Full(nb0, k1);
            int r10 = Full(Push(Join(a3x, a4, c1x, c2x)), k1);
            int r11 = Full(Push(Join(a4, b3x, c2x, d1x)), k1);
            int r12 = Full(Push(Join(b3x, b4, d1x, d2x)), k1);
            int r20 = Full(nc0, k1);
            int r21 = Full(Push(Join(c2x, d1x, c4, d3x)), k1);
            int r22 = Full(nd0, k1);
            r = Join(
                Full(Push(Join(r00, r01, r10, r11)), k1),
                Full(Push(Join(r01, r02, r11, r12)), k1),
                Full(Push(Join(r10, r11, r20, r21)), k1),
                Full(Push(Join(r11, r12, r21, r22)), k1));
            Nodes[o + Res] = r;
            _sp = sp;
            return Push(r);
        }

        /// <summary>
        /// Level-k node n (k ≥ 3, j ≤ k − 3) → the level-(k−1) node at its center, 2^j generations
        /// on (spec/hashlife.md "Fixed step"): the nine squares' centers with no time advance, then
        /// <c>result_j</c> of the four overlaps. Same contract as <see cref="Full"/>.
        /// </summary>
        internal int Stepped(int n, int k, int j)
        {
            int o = n * Stride;
            int[] nodes = Nodes;
            int tag = (j + 1) << TagShift;
            if ((nodes[o + Info] & TagMask) == tag)
            {
                int cached = nodes[o + Slow];
                if (cached >= 0)
                    return Push(cached);
            }
            int sp = _sp;
            int a = nodes[o], b = nodes[o + Ne], c = nodes[o + Sw], d = nodes[o + Se];
            int ao = a * Stride, bo = b * Stride, co = c * Stride, dob = d * Stride;
            int a1 = nodes[ao], a2 = nodes[ao + Ne], a3 = nodes[ao + Sw], a4 = nodes[ao + Se];
            int b1 = nodes[bo], b2 = nodes[bo + Ne], b3 = nodes[bo + Sw], b4 = nodes[bo + Se];
            int c1 = nodes[co], c2 = nodes[co + Ne], c3 = nodes[co + Sw], c4 = nodes[co + Se];
            int d1 = nodes[dob], d2 = nodes[dob + Ne], d3 = nodes[dob + Sw], d4 = nodes[dob + Se];
            int k1 = k - 1;
            // The nine overlapping level-(k−1) squares, by their quarters; each one's center.
            int s00 = Push(CenterOf(a1, a2, a3, a4, k1));
            int s01 = Push(CenterOf(a2, b1, a4, b3, k1));
            int s02 = Push(CenterOf(b1, b2, b3, b4, k1));
            int s10 = Push(CenterOf(a3, a4, c1, c2, k1));
            int s11 = Push(CenterOf(a4, b3, c2, d1, k1));
            int s12 = Push(CenterOf(b3, b4, d1, d2, k1));
            int s20 = Push(CenterOf(c1, c2, c3, c4, k1));
            int s21 = Push(CenterOf(c2, d1, c4, d3, k1));
            int s22 = Push(CenterOf(d1, d2, d3, d4, k1));
            int q00 = Push(Join(s00, s01, s10, s11));
            int q01 = Push(Join(s01, s02, s11, s12));
            int q10 = Push(Join(s10, s11, s20, s21));
            int q11 = Push(Join(s11, s12, s21, s22));
            int r;
            if (k1 == j + 2)
                r = Join(Full(q00, k1), Full(q01, k1), Full(q10, k1), Full(q11, k1));
            else
                r = Join(Stepped(q00, k1, j), Stepped(q01, k1, j), Stepped(q10, k1, j), Stepped(q11, k1, j));
            _sp = sp;
            nodes = Nodes;
            nodes[o + Slow] = r;
            nodes[o + Info] = (nodes[o + Info] & ~TagMask) | tag;
            return Push(r);
        }

        /// <summary>The center (level k − 1) of the level-k square with these quarters.</summary>
        internal int CenterOf(int p, int q, int s, int u, int k)
        {
            int[] nodes = Nodes;
            if (k == 2)
            {
                int sp = nodes[p * Stride], sq = nodes[q * Stride], ss = nodes[s * Stride], su = nodes[u * Stride];
                return Leaf((int)((uint)sp >> 24)
                    | ((sq >> 16) & 0xFF) << 8
                    | ((ss >> 8) & 0xFF) << 16
                    | (su & 0xFF) << 24);
            }
            return Join(nodes[p * Stride + Se], nodes[q * Stride + Sw], nodes[s * Stride + Ne], nodes[u * Stride + Nw]);
        }

        // -- populations ------------------------------------------------------------------------

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static int LeafPopulation(int states)
            => ((states & 0xFF) != 0 ? 1 : 0) + ((states & 0xFF00) != 0 ? 1 : 0)
                + ((states & 0xFF0000) != 0 ? 1 : 0) + ((states & unchecked((int)0xFF000000)) != 0 ? 1 : 0);

        /// <summary>The non-zero cells of level-k node n, k ≤ 31 (it fits a long).</summary>
        internal long PopLong(int n, int k)
        {
            int[] nodes = Nodes;
            int o = n * Stride;
            if (k == 1)
                return LeafPopulation(nodes[o]);
            int p = nodes[o + Pop];
            if (p >= 0)
                return p;
            if (p == -2 && _longPop.TryGetValue(n, out long big))
                return big;
            int k1 = k - 1;
            long sum = PopLong(nodes[o], k1) + PopLong(nodes[o + Ne], k1)
                + PopLong(nodes[o + Sw], k1) + PopLong(nodes[o + Se], k1);
            if (sum <= int.MaxValue)
            {
                nodes[o + Pop] = (int)sum;
            }
            else
            {
                nodes[o + Pop] = -2;
                _longPop[n] = sum;
            }
            return sum;
        }

        /// <summary>The non-zero cells of level-k node n, any k.</summary>
        internal BigInteger PopBig(int n, int k)
        {
            if (k <= 31)
                return PopLong(n, k);
            if (n == Empty(k))
                return BigInteger.Zero;
            if (_bigPop.TryGetValue(n, out BigInteger cached))
                return cached;
            int o = n * Stride;
            int[] nodes = Nodes;
            int k1 = k - 1;
            BigInteger sum = PopBig(nodes[o], k1) + PopBig(nodes[o + Ne], k1)
                + PopBig(nodes[o + Sw], k1) + PopBig(nodes[o + Se], k1);
            _bigPop[n] = sum;
            return sum;
        }

        /// <summary>A leaf's odd states: a History or Super rule's on cells.</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static int LeafOdd(int states)
            => (states & 1) + ((states >> 8) & 1) + ((states >> 16) & 1) + ((states >> 24) & 1);

        /// <summary>The cells of level-k node n whose state is odd, k ≤ 31 (it fits a long).</summary>
        internal long OddLong(int n, int k)
        {
            if (k == 1)
                return LeafOdd(Nodes[n * Stride]);
            if (n == Empty(k))
                return 0;
            if (k >= 4 && _oddPop.TryGetValue(n, out long known))
                return known;
            int o = n * Stride;
            int[] nodes = Nodes;
            int k1 = k - 1;
            long sum = OddLong(nodes[o], k1) + OddLong(nodes[o + Ne], k1)
                + OddLong(nodes[o + Sw], k1) + OddLong(nodes[o + Se], k1);
            if (k >= 4)
                _oddPop[n] = sum;
            return sum;
        }

        /// <summary>The cells of level-k node n whose state is odd, any k.</summary>
        internal BigInteger OddBig(int n, int k)
        {
            if (k <= 31)
                return OddLong(n, k);
            if (n == Empty(k))
                return BigInteger.Zero;
            if (_bigOddPop.TryGetValue(n, out BigInteger cached))
                return cached;
            int o = n * Stride;
            int[] nodes = Nodes;
            int k1 = k - 1;
            BigInteger sum = OddBig(nodes[o], k1) + OddBig(nodes[o + Ne], k1)
                + OddBig(nodes[o + Sw], k1) + OddBig(nodes[o + Se], k1);
            _bigOddPop[n] = sum;
            return sum;
        }

        /// <summary>⌈255 · population / 4^s⌉ for a level-s node, s ≥ 1, exactly.</summary>
        internal byte Density(int n, int s)
        {
            if (s <= 31)
                return HashLifeStore.DensityOf(PopLong(n, s), s);
            if (_bigDensity.TryGetValue(n, out byte value))
                return value;
            BigInteger area = BigInteger.One << (2 * s);
            value = (byte)((255 * PopBig(n, s) + area - 1) >> (2 * s));
            _bigDensity[n] = value;
            return value;
        }

        // -- the zoomed-out state ---------------------------------------------------------------

        /// <summary>Set the zoom order (distinct states from 1 to 255, checked by the caller): the
        /// listed states first, then the rest in increasing order. Cached shown states go.</summary>
        internal void SetOrder(byte[] order)
        {
            var listed = new bool[256];
            for (int place = 0; place < order.Length; place++)
            {
                Ranks[order[place]] = place;
                listed[order[place]] = true;
            }
            int next = order.Length;
            for (int state = 1; state < 256; state++)
            {
                if (!listed[state])
                    Ranks[state] = next++;
            }
            Ranks[0] = 256;
            int[] nodes = Nodes;
            for (int n = 0; n < _used; n++)
                nodes[n * Stride + Info] &= ~ShownMask;
        }

        /// <summary>The state level-k node n shows zoomed out: of its non-zero states, the first in
        /// the zoom order, or 0 when it has none. Cached in the node's info word.</summary>
        internal int Shown(int n, int k)
        {
            int[] nodes = Nodes;
            int o = n * Stride;
            int[] ranks = Ranks;
            if (k == 1)
            {
                int states = nodes[o];
                int best = 0;
                for (int i = 0; i < 4; i++)
                {
                    int state = (states >> (8 * i)) & 0xFF;
                    if (ranks[state] < ranks[best])
                        best = state;
                }
                return best;
            }
            int cached = (nodes[o + Info] & ShownMask) >> ShownShift;
            if (cached != 0)
                return cached - 1;
            int shown = 0;
            if (n != Empty(k))
            {
                for (int q = 0; q < 4; q++)
                {
                    int state = Shown(nodes[o + q], k - 1);
                    if (ranks[state] < ranks[shown])
                        shown = state;
                }
            }
            nodes[o + Info] = (nodes[o + Info] & ~ShownMask) | ((shown + 1) << ShownShift);
            return shown;
        }

        // -- collection -------------------------------------------------------------------------

        /// <summary>
        /// Mark from the root, the live snapshots (not the released ones), the empty nodes, and
        /// — in flight — the saved stack; free the rest. Results survive only when both ends do.
        /// </summary>
        internal void Collect(bool inFlight)
        {
            MarkFrom(Root);
            for (int k = 1; k < _emptyCount; k++)
                MarkFrom(_empty[k]);
            for (int i = Snapshots.Count - 1; i >= 0; i--)
            {
                if (Snapshots[i].TryGetTarget(out HashLifeSnapshot? snapshot) && !snapshot.Released)
                    MarkFrom(snapshot.RootNode);
                else
                    Snapshots.RemoveAt(i);
            }
            if (inFlight)
            {
                for (int i = 0; i < _sp; i++)
                    MarkFrom(_stack[i]);
            }

            int[] nodes = Nodes;
            for (int n = 0; n < _used; n++)
            {
                int o = n * Stride;
                if (nodes[o + Se] == FreeTag)
                    continue;
                int info = nodes[o + Info];
                if (info < 0)
                {
                    nodes[o + Info] = info & ~MarkBit;
                    continue;
                }
                nodes[o + Se] = FreeTag;
                nodes[o + Pop] = _free;
                _free = n;
                _live--;
            }

            int[] table = _table;
            int mask = _tableMask;
            Array.Fill(table, -1);
            for (int n = 0; n < _used; n++)
            {
                int o = n * Stride;
                int se = nodes[o + Se];
                if (se == FreeTag)
                    continue;
                uint h;
                if (se == LeafTag)
                {
                    h = HashLeaf(nodes[o]);
                }
                else
                {
                    int r = nodes[o + Res];
                    if (r >= 0 && nodes[r * Stride + Se] == FreeTag)
                        nodes[o + Res] = -1;
                    r = nodes[o + Slow];
                    if (r >= 0 && nodes[r * Stride + Se] == FreeTag)
                    {
                        nodes[o + Slow] = -1;
                        nodes[o + Info] &= ~TagMask;
                    }
                    if (nodes[o + Pop] == -2)
                        nodes[o + Pop] = -1;
                    h = HashKids(nodes[o], nodes[o + Ne], nodes[o + Sw], se);
                }
                int i = (int)(h & (uint)mask);
                while (table[i] >= 0)
                    i = (i + 1) & mask;
                table[i] = n | Fingerprint(h);
            }
            _tableVersion++;
            _longPop.Clear();
            _bigPop.Clear();
            _bigDensity.Clear();
            _oddPop.Clear();
            _bigOddPop.Clear();
            Collections++;
        }

        private void MarkFrom(int start)
        {
            int[] nodes = Nodes;
            int sp = 0;
            _markStack[sp++] = start;
            while (sp > 0)
            {
                int n = _markStack[--sp];
                int o = n * Stride;
                int info = nodes[o + Info];
                if (info < 0)
                    continue;
                nodes[o + Info] = info | MarkBit;
                if (nodes[o + Se] < 0)
                    continue; // a leaf
                if (sp + 4 > _markStack.Length)
                    Array.Resize(ref _markStack, _markStack.Length * 2);
                for (int q = 0; q < 4; q++)
                {
                    int kid = nodes[o + q];
                    if (nodes[kid * Stride + Info] >= 0)
                        _markStack[sp++] = kid;
                }
            }
        }
    }
}
