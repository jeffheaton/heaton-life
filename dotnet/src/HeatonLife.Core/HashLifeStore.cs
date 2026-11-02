using System;
using System.Collections.Generic;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// Leaf-level bit machinery for HashLife (spec/hashlife.md "Quadtree"). A leaf is an 8×8
    /// bitmap in one ulong: cell (x, y) of the leaf is bit <c>y * 8 + x</c> (row-major, origin
    /// top-left, y down). Smaller squares keep the same 8-wide row stride ("spread" form): a 4×4
    /// square occupies bits <c>y * 8 + x</c> for x, y &lt; 4, so four of them compose into a leaf
    /// with three shifts. The rule enters only through the 65,536-entry base case, a 4×4 square to
    /// its center 2×2 one generation later. The Python reference's ca/hashlife/leaves.py.
    /// </summary>
    internal static class HashLifeLeaves
    {
        internal const ulong Left4 = 0x0F0F0F0F0F0F0F0FUL;   // columns 0-3 of every row
        internal const ulong Right4 = 0xF0F0F0F0F0F0F0F0UL;  // columns 4-7 of every row
        internal const ulong Square4 = 0x0F0F0F0FUL;         // a 4×4 square in spread form
        private const ulong RepeatRows = 0x0101010101010101UL;

        private static readonly Dictionary<string, ushort[]> Tables = new Dictionary<string, ushort[]>();

        /// <summary>The base case for a canonical rule: a 4×4 square indexed compactly (bit
        /// <c>y * 4 + x</c>) to its center 2×2 one generation later, in spread form (bits 0, 1, 8,
        /// 9). Built once per rule and shared.</summary>
        internal static ushort[] RuleTable(string canonicalRule)
        {
            lock (Tables)
            {
                if (Tables.TryGetValue(canonicalRule, out ushort[]? table))
                    return table;
                var (birth, survive) = RuleString.Parse(canonicalRule);
                table = new ushort[1 << 16];
                for (int index = 0; index < 1 << 16; index++)
                {
                    int result = 0;
                    for (int cell = 0; cell < 4; cell++)
                    {
                        int cx = 1 + (cell & 1), cy = 1 + (cell >> 1);
                        int count = 0;
                        for (int dy = -1; dy <= 1; dy++)
                            for (int dx = -1; dx <= 1; dx++)
                                if (dx != 0 || dy != 0)
                                    count += (index >> ((cy + dy) * 4 + cx + dx)) & 1;
                        bool alive = ((index >> (cy * 4 + cx)) & 1) != 0;
                        if (alive ? survive[count] : birth[count])
                            result |= 1 << ((cell & 1) + 8 * (cell >> 1));
                    }
                    table[index] = (ushort)result;
                }
                if (Tables.Count >= 16)
                    Tables.Clear();
                Tables[canonicalRule] = table;
                return table;
            }
        }

        /// <summary>The 4×4 square at bit 0 of a spread bitmap, as a compact 16-bit table index.</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static int Window(ulong b)
            => (int)((b & 0xF) | ((b >> 4) & 0xF0) | ((b >> 8) & 0xF00) | ((b >> 12) & 0xF000));

        /// <summary>A leaf's center 4×4 one generation on (spread form).</summary>
        internal static ulong One(ulong b, ushort[] t)
            => t[Window(b >> 9)]
                | (ulong)t[Window(b >> 11)] << 2
                | (ulong)t[Window(b >> 25)] << 16
                | (ulong)t[Window(b >> 27)] << 18;

        /// <summary>A leaf's center 4×4 two generations on (spread form). Nine windows at even
        /// offsets give the 6×6 at cells 1..6 after one generation (each window's 2×2 lands at
        /// its own offset + 9); four windows of that give the center.</summary>
        internal static ulong Two(ulong b, ushort[] t)
        {
            ulong g = (ulong)t[Window(b)] << 9
                | (ulong)t[Window(b >> 2)] << 11
                | (ulong)t[Window(b >> 4)] << 13
                | (ulong)t[Window(b >> 16)] << 25
                | (ulong)t[Window(b >> 18)] << 27
                | (ulong)t[Window(b >> 20)] << 29
                | (ulong)t[Window(b >> 32)] << 41
                | (ulong)t[Window(b >> 34)] << 43
                | (ulong)t[Window(b >> 36)] << 45;
            return t[Window(g >> 9)]
                | (ulong)t[Window(g >> 11)] << 2
                | (ulong)t[Window(g >> 25)] << 16
                | (ulong)t[Window(g >> 27)] << 18;
        }

        /// <summary>
        /// A level-4 node's center 8×8, 2^j generations on (j is 0 or 1), from its four leaves:
        /// the nine overlapping squares' centers with no time advance, then one or two
        /// generations of the four overlaps (spec/hashlife.md "Fixed step", at its base).
        /// </summary>
        internal static ulong StepCenter(ulong na, ulong nb, ulong nc, ulong nd, int j, ushort[] t)
        {
            ulong n01 = Beside(na, nb);
            ulong n21 = Beside(nc, nd);
            ulong n10 = Above(na, nc);
            ulong n12 = Above(nb, nd);
            ulong n11 = Above(n01, n21);
            ulong c00 = Center(na), c01 = Center(n01), c02 = Center(nb);
            ulong c10 = Center(n10), c11 = Center(n11), c12 = Center(n12);
            ulong c20 = Center(nc), c21 = Center(n21), c22 = Center(nd);
            ulong q00 = Compose(c00, c01, c10, c11);
            ulong q01 = Compose(c01, c02, c11, c12);
            ulong q10 = Compose(c10, c11, c20, c21);
            ulong q11 = Compose(c11, c12, c21, c22);
            return j == 1
                ? Compose(Two(q00, t), Two(q01, t), Two(q10, t), Two(q11, t))
                : Compose(One(q00, t), One(q01, t), One(q10, t), One(q11, t));
        }

        /// <summary>A leaf's center 4×4 with no time advance (spread form).</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static ulong Center(ulong b) => (b >> 18) & Square4;

        /// <summary>Four 4×4 squares (spread form) into one leaf.</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static ulong Compose(ulong nw, ulong ne, ulong sw, ulong se)
            => nw | ne << 4 | sw << 32 | se << 36;

        /// <summary>The leaf straddling two side-by-side leaves: w's right half, then e's left half.</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static ulong Beside(ulong w, ulong e) => ((w >> 4) & Left4) | ((e << 4) & Right4);

        /// <summary>The leaf straddling two stacked leaves: n's bottom half over s's top half.</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static ulong Above(ulong n, ulong s) => (n >> 32) | (s << 32);

        /// <summary>The leaf at the center of four leaves (a level-4 node's center, no time).</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal static ulong Inner(ulong nw, ulong ne, ulong sw, ulong se)
            => Compose((nw >> 36) & Square4, (ne >> 32) & Square4, (sw >> 4) & Square4, se & Square4);

        /// <summary>Columns c0..c1 and rows r0..r1 of a leaf, inclusive, all within 0..7.</summary>
        internal static ulong RectMask(int c0, int c1, int r0, int r1)
        {
            ulong row = ((1UL << (c1 - c0 + 1)) - 1) << c0;
            int rows = r1 - r0 + 1;
            ulong band = rows == 8 ? ulong.MaxValue : ((1UL << (rows * 8)) - 1) << (8 * r0);
            return (row * RepeatRows) & band;
        }

        /// <summary>The 8-bit OR of a leaf's rows: bit x is set when column x holds a live cell.</summary>
        internal static int Columns(ulong b)
        {
            b |= b >> 32;
            b |= b >> 16;
            b |= b >> 8;
            return (int)(b & 0xFF);
        }

        internal static int PopCount(ulong v)
        {
            v -= (v >> 1) & 0x5555555555555555UL;
            v = (v & 0x3333333333333333UL) + ((v >> 2) & 0x3333333333333333UL);
            v = (v + (v >> 4)) & 0x0F0F0F0F0F0F0F0FUL;
            return (int)((v * 0x0101010101010101UL) >> 56);
        }

        /// <summary>The index of the lowest set bit of a non-zero value.</summary>
        internal static int LowestBit(ulong v)
        {
            int i = 0;
            while ((v & 1) == 0)
            {
                v >>= 1;
                i++;
            }
            return i;
        }

        /// <summary>The index of the highest set bit of a non-zero value.</summary>
        internal static int HighestBit(ulong v)
        {
            int i = 63;
            while ((v & (1UL << i)) == 0)
                i--;
            return i;
        }
    }

    /// <summary>
    /// The HashLife node store (spec/hashlife.md "Quadtree", "Evolution", "Memory"): hash-consed
    /// quadtree nodes in one int arena, their memoized futures, and a collector that can run in
    /// the middle of a step. Nothing here is observable — the spec pins cells, never layout — so
    /// this is the C# port's own design rather than a copy of the Python store:
    ///
    /// <list type="bullet">
    /// <item>A node is an 8-int record at <c>id * 8</c> in <see cref="Nodes"/>: four children (a
    /// leaf keeps its bitmap's halves, its two-generation center, and <see cref="LeafTag"/>
    /// there), a population, the full-speed result, the fixed-step result, and an info word
    /// (level, the j the fixed-step result belongs to, and the collector's mark bit).</item>
    /// <item>Hash-consing is open addressing with linear probing over a table of ids at most
    /// half full. Freed records chain into a free list; the table is rebuilt by every
    /// collection, so it never holds tombstones.</item>
    /// <item>Growth doubles the arrays up to the memory budget. Past it, a step collects in
    /// flight: every id the recursion holds is pushed on a saved-node stack, and
    /// marking starts from the root, the live snapshots, the empty nodes, and that stack.
    /// Cached results are not roots: a result whose node is collected is dropped.</item>
    /// <item>After warm-up nothing here allocates on the managed heap while stepping: the
    /// arrays, the saved stack, and the mark stack only grow.</item>
    /// </list>
    /// </summary>
    internal sealed class HashLifeStore
    {
        internal const int Stride = 8;
        internal const int Nw = 0, Ne = 1, Sw = 2, Se = 3; // children; a leaf: Lo, Hi, its 2-gen center, LeafTag
        private const int Pop = 4;  // population if it fits an int, -1 unknown, -2 in _longPop; a free record: the next free id
        private const int Res = 5;  // the full-speed result, -1 none
        private const int Slow = 6; // the fixed-step result for the j in Info's tag, -1 none
        private const int Info = 7; // level (bits 0-15), fixed-step tag j + 1 (bits 16-30), mark (bit 31)
        internal const int LeafTag = -1;
        private const int FreeTag = -2;
        private const int LevelMask = 0xFFFF;
        private const int TagShift = 16;
        private const int TagMask = 0x7FFF << TagShift;
        private const int MarkBit = int.MinValue;
        private const int CheckEvery = 4096; // allocations between cancellation checks

        /// <summary>The deepest root (spec/hashlife.md "Depth"); the fixed-step tag would hold j + 1
        /// in 15 bits, far past it.</summary>
        internal const int MaxLevel = HashLife.MaxLevel;

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

        /// <summary>The rule's base case (see <see cref="HashLifeLeaves.RuleTable"/>).</summary>
        internal ushort[] Rule;

        /// <summary>Live nodes a step may hold before it collects (the memory budget).</summary>
        internal int MaxNodes;

        /// <summary>The universe's root and its level, the collector's first root.</summary>
        internal int Root;
        internal int Level;

        /// <summary>Snapshots pin their roots for as long as they live.</summary>
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

        internal HashLifeStore(ushort[] rule, int maxNodes)
        {
            Rule = rule;
            MaxNodes = maxNodes;
            _capacity = InitialCapacity;
            Nodes = new int[_capacity * Stride];
            _table = new int[TableSizeFor(_capacity)];
            _tableMask = _table.Length - 1;
            Array.Fill(_table, -1);
            for (int k = 0; k < 3; k++)
                _empty[k] = -1;
            _empty[3] = Leaf(0);
            _emptyCount = 4;
            Root = Empty(4);
            Level = 4;
        }

        internal int Live => _live;

        // -- nodes ------------------------------------------------------------------------------

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal int Kid(int n, int quadrant) => Nodes[n * Stride + quadrant];

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        internal ulong Bits(int leaf)
        {
            int o = leaf * Stride;
            return (ulong)(uint)Nodes[o + Ne] << 32 | (uint)Nodes[o];
        }

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
        private static uint HashLeaf(int lo, int hi)
            => Mix((ulong)(uint)lo * 0xA0761D6478BD642FUL + (ulong)(uint)hi * 0xE7037ED1A0B428DBUL + 1);

        /// <summary>A table entry is an id (below 2^28) with three bits of its hash above it, so a
        /// probe skips most mismatches without reading a record. The table index uses the low
        /// hash bits (the table never passes 2^29 entries); the fingerprint the top three.</summary>
        private const int IdMask = (1 << 28) - 1;

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static int Fingerprint(uint h) => (int)(h >> 29) << 28;

        /// <summary>The leaf with this bitmap.</summary>
        internal int Leaf(ulong bits)
        {
            int lo = (int)(uint)bits, hi = (int)(uint)(bits >> 32);
            uint h = HashLeaf(lo, hi);
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
                    if (nodes[o + Se] == LeafTag && nodes[o] == lo && nodes[o + Ne] == hi)
                        return entry & IdMask;
                }
                i = (i + 1) & mask;
            }
            int version = _tableVersion;
            int m = Alloc();
            nodes = Nodes;
            int mo = m * Stride;
            nodes[mo] = lo;
            nodes[mo + Ne] = hi;
            nodes[mo + Sw] = -1;
            nodes[mo + Se] = LeafTag;
            nodes[mo + Pop] = -1;
            nodes[mo + Res] = -1;
            nodes[mo + Slow] = -1;
            nodes[mo + Info] = 3;
            if (version != _tableVersion)
                i = OpenSlot(h);
            _table[i] = m | fingerprint;
            return m;
        }

        /// <summary>The node with these children (all one level, at least 3).</summary>
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
                    throw new AbortException(canceled: true);
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
        /// Grow the arena, or — inside a step at the budget — collect in flight. The step is
        /// abandoned when a collection leaves less than an eighth of the budget free, or when a
        /// sub-step that could still be split (<see cref="ThrashLimit"/>) keeps collecting: its
        /// working set outgrows the budget, every collection drops results it will compute again,
        /// and two half sub-steps need less room.
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
                    throw new AbortException(canceled: false);
                }
                if (_free >= 0 || _used < _capacity)
                    return;
            }
            if (_capacity >= MaxCapacity)
                throw new OutOfMemoryException(
                    $"the HashLife store is at its largest size ({MaxCapacity} nodes)");
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
                uint h = se == LeafTag
                    ? HashLeaf(nodes[o], nodes[o + Ne])
                    : HashKids(nodes[o], nodes[o + Ne], nodes[o + Sw], se);
                int i = (int)(h & (uint)mask);
                while (table[i] >= 0)
                    i = (i + 1) & mask;
                table[i] = n | Fingerprint(h);
            }
            _tableVersion++;
        }

        // -- results ----------------------------------------------------------------------------

        /// <summary>Switch rules: cells survive, every cached result goes.</summary>
        internal void UseRule(ushort[] rule)
        {
            Rule = rule;
            int[] nodes = Nodes;
            for (int n = 0; n < _used; n++)
            {
                int o = n * Stride;
                int se = nodes[o + Se];
                if (se == FreeTag)
                    continue;
                if (se == LeafTag)
                {
                    nodes[o + Sw] = -1;
                }
                else
                {
                    nodes[o + Res] = -1;
                    nodes[o + Slow] = -1;
                    nodes[o + Info] &= ~TagMask;
                }
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

        /// <summary>A leaf's center 4×4 two generations on, cached in the leaf's record.</summary>
        private ulong LeafTwo(int leaf)
        {
            int o = leaf * Stride;
            int r = Nodes[o + Sw];
            if (r < 0)
            {
                r = (int)HashLifeLeaves.Two(Bits(leaf), Rule);
                Nodes[o + Sw] = r;
            }
            return (ulong)r;
        }

        /// <summary>
        /// Level-k node n (k ≥ 4) → the level-(k−1) node at its center, 2^(k−2) generations on
        /// (spec/hashlife.md "Full speed"). n must be held (reachable from a root or on the saved
        /// stack); the result comes back pushed on the saved stack.
        /// </summary>
        internal int Full(int n, int k)
        {
            int o = n * Stride;
            int[] nodes = Nodes;
            int r = nodes[o + Res];
            if (r >= 0)
                return Push(r);
            if (k == 4)
            {
                // Children are leaves: the nine overlapping squares are bit shuffles, and every
                // two-generation center comes from the rule table (the children's from their records).
                int a = nodes[o], b = nodes[o + Ne], c = nodes[o + Sw], d = nodes[o + Se];
                ulong na = Bits(a), nb = Bits(b), nc = Bits(c), nd = Bits(d);
                ulong n01 = HashLifeLeaves.Beside(na, nb);
                ulong n21 = HashLifeLeaves.Beside(nc, nd);
                ulong n10 = HashLifeLeaves.Above(na, nc);
                ulong n12 = HashLifeLeaves.Above(nb, nd);
                ulong n11 = HashLifeLeaves.Above(n01, n21);
                ushort[] t = Rule;
                ulong r00 = LeafTwo(a), r01 = HashLifeLeaves.Two(n01, t), r02 = LeafTwo(b);
                ulong r10 = HashLifeLeaves.Two(n10, t), r11 = HashLifeLeaves.Two(n11, t), r12 = HashLifeLeaves.Two(n12, t);
                ulong r20 = LeafTwo(c), r21 = HashLifeLeaves.Two(n21, t), r22 = LeafTwo(d);
                r = Leaf(HashLifeLeaves.Compose(
                    HashLifeLeaves.Two(HashLifeLeaves.Compose(r00, r01, r10, r11), t),
                    HashLifeLeaves.Two(HashLifeLeaves.Compose(r01, r02, r11, r12), t),
                    HashLifeLeaves.Two(HashLifeLeaves.Compose(r10, r11, r20, r21), t),
                    HashLifeLeaves.Two(HashLifeLeaves.Compose(r11, r12, r21, r22), t)));
                Nodes[o + Res] = r;
                return Push(r);
            }
            int sp = _sp;
            int na0 = nodes[o], nb0 = nodes[o + Ne], nc0 = nodes[o + Sw], nd0 = nodes[o + Se];
            int ao = na0 * Stride, bo = nb0 * Stride, co = nc0 * Stride, dob = nd0 * Stride;
            int a2 = nodes[ao + Ne], a3 = nodes[ao + Sw], a4 = nodes[ao + Se];
            int b1 = nodes[bo], b3 = nodes[bo + Sw], b4 = nodes[bo + Se];
            int c1 = nodes[co], c2 = nodes[co + Ne], c4 = nodes[co + Se];
            int d1 = nodes[dob], d2 = nodes[dob + Ne], d3 = nodes[dob + Sw];
            int k1 = k - 1;
            int r00x = Full(na0, k1);
            int r01x = Full(Push(Join(a2, b1, a4, b3)), k1);
            int r02x = Full(nb0, k1);
            int r10x = Full(Push(Join(a3, a4, c1, c2)), k1);
            int r11x = Full(Push(Join(a4, b3, c2, d1)), k1);
            int r12x = Full(Push(Join(b3, b4, d1, d2)), k1);
            int r20x = Full(nc0, k1);
            int r21x = Full(Push(Join(c2, d1, c4, d3)), k1);
            int r22x = Full(nd0, k1);
            r = Join(
                Full(Push(Join(r00x, r01x, r10x, r11x)), k1),
                Full(Push(Join(r01x, r02x, r11x, r12x)), k1),
                Full(Push(Join(r10x, r11x, r20x, r21x)), k1),
                Full(Push(Join(r11x, r12x, r21x, r22x)), k1));
            Nodes[o + Res] = r;
            _sp = sp;
            return Push(r);
        }

        /// <summary>
        /// Level-k node n (k ≥ 4, j ≤ k − 3) → the level-(k−1) node at its center, 2^j generations
        /// on (spec/hashlife.md "Fixed step"): the nine squares' centers with no time advance,
        /// then <c>result_j</c> of the four overlaps. Same contract as <see cref="Full"/>.
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
            int r;
            if (k == 4)
            {
                // j is 0 or 1 and the children are leaves.
                r = Leaf(HashLifeLeaves.StepCenter(
                    Bits(nodes[o]), Bits(nodes[o + Ne]), Bits(nodes[o + Sw]), Bits(nodes[o + Se]), j, Rule));
            }
            else if (k == 5 && j <= 1)
            {
                // The nine level-4 overlaps are never stored: each quarter of the result comes
                // straight from the grandchildren's bitmaps, so a chaotic region costs five
                // lookups here instead of eighteen.
                int sp = _sp;
                int a = nodes[o], b = nodes[o + Ne], c = nodes[o + Sw], d = nodes[o + Se];
                ulong a1 = Bits(Kid(a, Nw)), a2 = Bits(Kid(a, Ne)), a3 = Bits(Kid(a, Sw)), a4 = Bits(Kid(a, Se));
                ulong b1 = Bits(Kid(b, Nw)), b2 = Bits(Kid(b, Ne)), b3 = Bits(Kid(b, Sw)), b4 = Bits(Kid(b, Se));
                ulong c1 = Bits(Kid(c, Nw)), c2 = Bits(Kid(c, Ne)), c3 = Bits(Kid(c, Sw)), c4 = Bits(Kid(c, Se));
                ulong d1 = Bits(Kid(d, Nw)), d2 = Bits(Kid(d, Ne)), d3 = Bits(Kid(d, Sw)), d4 = Bits(Kid(d, Se));
                ulong s00 = HashLifeLeaves.Inner(a1, a2, a3, a4), s01 = HashLifeLeaves.Inner(a2, b1, a4, b3);
                ulong s02 = HashLifeLeaves.Inner(b1, b2, b3, b4), s10 = HashLifeLeaves.Inner(a3, a4, c1, c2);
                ulong s11 = HashLifeLeaves.Inner(a4, b3, c2, d1), s12 = HashLifeLeaves.Inner(b3, b4, d1, d2);
                ulong s20 = HashLifeLeaves.Inner(c1, c2, c3, c4), s21 = HashLifeLeaves.Inner(c2, d1, c4, d3);
                ulong s22 = HashLifeLeaves.Inner(d1, d2, d3, d4);
                ushort[] t = Rule;
                int r00 = Push(Leaf(HashLifeLeaves.StepCenter(s00, s01, s10, s11, j, t)));
                int r01 = Push(Leaf(HashLifeLeaves.StepCenter(s01, s02, s11, s12, j, t)));
                int r10 = Push(Leaf(HashLifeLeaves.StepCenter(s10, s11, s20, s21, j, t)));
                int r11 = Push(Leaf(HashLifeLeaves.StepCenter(s11, s12, s21, s22, j, t)));
                r = Join(r00, r01, r10, r11);
                _sp = sp;
            }
            else
            {
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
                if (k1 == j + 2)
                    r = Join(Full(q00, k1), Full(q01, k1), Full(q10, k1), Full(q11, k1));
                else
                    r = Join(Stepped(q00, k1, j), Stepped(q01, k1, j), Stepped(q10, k1, j), Stepped(q11, k1, j));
                _sp = sp;
            }
            nodes = Nodes;
            nodes[o + Slow] = r;
            nodes[o + Info] = (nodes[o + Info] & ~TagMask) | tag;
            return Push(r);
        }

        /// <summary>The center (level k − 1) of the level-k square with these quarters.</summary>
        private int CenterOf(int p, int q, int s, int u, int k)
        {
            if (k == 4)
                return Leaf(HashLifeLeaves.Inner(Bits(p), Bits(q), Bits(s), Bits(u)));
            int[] nodes = Nodes;
            return Join(nodes[p * Stride + Se], nodes[q * Stride + Sw], nodes[s * Stride + Ne], nodes[u * Stride + Nw]);
        }

        // -- populations ------------------------------------------------------------------------

        /// <summary>The population of level-k node n, k ≤ 31 (it fits a long).</summary>
        internal long PopLong(int n, int k)
        {
            int[] nodes = Nodes;
            int o = n * Stride;
            if (k == 3)
                return HashLifeLeaves.PopCount((ulong)(uint)nodes[o + Ne] << 32 | (uint)nodes[o]);
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

        /// <summary>The population of level-k node n, any k.</summary>
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

        /// <summary>⌈255 · population / 4^s⌉ for a level-s node, s ≥ 3, exactly.</summary>
        internal byte Density(int n, int s)
        {
            if (s <= 31)
                return DensityOf(PopLong(n, s), s);
            if (_bigDensity.TryGetValue(n, out byte value))
                return value;
            BigInteger area = BigInteger.One << (2 * s);
            value = (byte)((255 * PopBig(n, s) + area - 1) >> (2 * s));
            _bigDensity[n] = value;
            return value;
        }

        /// <summary>⌈255 · pop / 4^s⌉ for 0 ≤ pop ≤ 4^s, s ≤ 31, in long arithmetic.</summary>
        internal static byte DensityOf(long pop, int s)
        {
            int shift = 2 * s;
            if (s <= 27)
                return (byte)((255L * pop + (1L << shift) - 1) >> shift);
            // 255·pop overflows a long here: split pop at bit 2s − 8 so every product fits.
            int low = shift - 8;
            long a = pop >> low;
            long c = 255L * (pop & ((1L << low) - 1));
            long whole = 255L * a + (c >> low);
            bool rest = (c & ((1L << low) - 1)) != 0;
            return (byte)((whole + (rest ? 1 : 0) + 255) >> 8);
        }

        // -- collection -------------------------------------------------------------------------

        /// <summary>
        /// Mark from the root, the live snapshots, the empty nodes, and — in flight — the saved
        /// stack; free the rest. Results survive only when both ends do.
        /// </summary>
        internal void Collect(bool inFlight)
        {
            MarkFrom(Root);
            for (int k = 3; k < _emptyCount; k++)
                MarkFrom(_empty[k]);
            for (int i = Snapshots.Count - 1; i >= 0; i--)
            {
                if (Snapshots[i].TryGetTarget(out HashLifeSnapshot? snapshot))
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
                    h = HashLeaf(nodes[o], nodes[o + Ne]);
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

        /// <summary>Thrown inside a step to unwind it: the budget filled or a cancel arrived.</summary>
        internal sealed class AbortException : Exception
        {
            internal AbortException(bool canceled)
                : base(canceled ? "canceled" : "memory budget exhausted")
            {
                Canceled = canceled;
            }

            internal bool Canceled { get; }
        }
    }
}
