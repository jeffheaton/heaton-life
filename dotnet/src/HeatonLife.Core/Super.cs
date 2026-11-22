using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>
    /// Super rules (spec/super.md): any Life-like rule with 26 states. States 0–6 are a History
    /// rule's (spec/history.md) and behave as they do there; states 7–25 add on cells that leave no
    /// trail (7 and the odd states 13–25), two more trails with envelopes of their own (9 and 10,
    /// 11 and 12), and labels, the even states 14–24, that vanish, wait to be cleared, cycle, or
    /// appear when something touches them. The on cells (the odd states) run the base rule's table
    /// exactly as a two-state world's live cells do, away from boundary cells (6), and a newborn
    /// takes its state from its parents, the on cells among its neighbors. This class holds the one
    /// cell function that the Life-like grid (<see cref="LifeLike"/>) and the multi-state universe
    /// (<see cref="SuperRule"/>) both run. The Python reference's <c>heaton_life.ca.super_rules</c>.
    /// </summary>
    public static class Super
    {
        /// <summary>A Super rule's states (spec/super.md "States").</summary>
        public const int States = LifeRule.SuperStates;

        /// <summary>State 3: marked on, as History's.</summary>
        public const byte MarkedOn = 3;

        /// <summary>State 4: marked off, as History's; a birth there gives 3.</summary>
        public const byte MarkedOff = 4;

        /// <summary>State 6: boundary; it never changes, counts as off, and keeps every cell beside
        /// it off.</summary>
        public const byte Boundary = 6;

        /// <summary>State 7: marked on, leaving no trail; it dies into 8.</summary>
        public const byte NoTrailMarkedOn = 7;

        /// <summary>State 8: marked off, no trail; a birth there gives 7.</summary>
        public const byte NoTrailMarkedOff = 8;

        /// <summary>State 9: the second trail's on cell; it dies into 10.</summary>
        public const byte SecondTrail = 9;

        /// <summary>State 11: the third trail's on cell; it dies into 12.</summary>
        public const byte ThirdTrail = 11;

        /// <summary>State 13, the first of the no-trail states 13, 15, …, 25, which die into 0; a
        /// newborn of mixed no-trail parents takes it.</summary>
        public const byte NoTrail = 13;

        /// <summary>State 14: the vanishing label, 0 a generation later.</summary>
        public const byte Vanishing = 14;

        /// <summary>State 16: the clearable label; it turns vanishing when a neighbor is on or
        /// vanishing.</summary>
        public const byte Clearable = 16;

        /// <summary>State 18: cycling label 1; it turns into cycling label 3 beside one.</summary>
        public const byte Cycling1 = 18;

        /// <summary>State 20: cycling label 2; it turns into cycling label 1 beside one.</summary>
        public const byte Cycling2 = 20;

        /// <summary>State 22: cycling label 3; it turns into cycling label 2 beside one.</summary>
        public const byte Cycling3 = 22;

        /// <summary>State 24: the hidden label; it turns into cycling label 1 when a neighbor is
        /// on, vanishing or cycling label 1.</summary>
        public const byte Hidden = 24;

        // An on cell's state when it turns off (1 → 2, 3 and 5 → 4, 7 → 8, 9 → 10, 11 → 12, a
        // no-trail state → 0); an off state maps to itself.
        private static readonly byte[] Death =
            { 0, 2, 2, 4, 4, 4, 6, 8, 8, 10, 10, 12, 12, 0, 14, 0, 16, 0, 18, 0, 20, 0, 22, 0, 24, 0 };

        // A cell's next state beside a boundary cell: 7, 8, the no-trail states and the labels
        // → 0, the others as on turning off or staying off.
        private static readonly byte[] Walled =
            { 0, 2, 2, 4, 4, 4, 6, 0, 0, 10, 10, 12, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };

        // The eight neighbors' bits in the neighborhood index, in block order NW N NE W E SW S SE.
        private static readonly int[] Bits = { 256, 128, 64, 32, 8, 4, 2, 1 };

        /// <summary>
        /// A newborn's state from its parents' states, the on cells among its neighbors (spec/super.md
        /// "The newborn's state"): the first of these that applies — one no-trail state s with any 3s
        /// gives s; one trail state t with any 7s gives t; 7s and no-trail states give 13; anything
        /// else, a birth with no parents included, gives 1. Every parent must be an on state.
        /// </summary>
        public static byte Newborn(ReadOnlySpan<byte> parents)
        {
            var tally = default(Parents);
            foreach (byte parent in parents)
            {
                if (parent >= States || (parent & 1) == 0)
                    throw new ArgumentOutOfRangeException(nameof(parents), parent, "a parent is an on state: odd, 1 to 25");
                tally.Add(parent);
            }
            return tally.Newborn();
        }

        /// <summary>
        /// A cell's next state from its 3 × 3 block (spec/super.md "Evolution"): the base rule's
        /// <paramref name="table"/> read at the index of the block's on cells, and
        /// <paramref name="near"/> the neighbors the rule counts as bits of that index
        /// (<see cref="History.NeighborBits"/>). Allocates nothing.
        /// </summary>
        internal static byte Next(
            byte[] table, int near, int nw, int n, int ne, int w, int c, int e, int sw, int s, int se)
        {
            if (c == Boundary)
                return Boundary;
            if ((Mask(Boundary, nw, n, ne, w, e, sw, s, se) & near) != 0)
                return Walled[c];
            int index = ((nw & 1) << 8) | ((n & 1) << 7) | ((ne & 1) << 6) | ((w & 1) << 5) | ((c & 1) << 4)
                | ((e & 1) << 3) | ((sw & 1) << 2) | ((s & 1) << 1) | (se & 1);
            bool on = table[index] != 0;
            if ((c & 1) != 0)
                return on ? (byte)c : Death[c];
            if (on)
            {
                if (c == MarkedOff)
                    return MarkedOn;
                if (c == NoTrailMarkedOff)
                    return NoTrailMarkedOn;
                var tally = default(Parents);
                for (int j = 0; j < 8; j++)
                {
                    if ((near & Bits[j]) == 0)
                        continue;
                    int parent = j switch { 0 => nw, 1 => n, 2 => ne, 3 => w, 4 => e, 5 => sw, 6 => s, _ => se };
                    if ((parent & 1) != 0)
                        tally.Add(parent);
                }
                return tally.Newborn();
            }
            int touched = index & 0x1EF & near; // the neighbors that are on
            switch (c)
            {
                case Vanishing:
                    return 0;
                case Clearable:
                    return ((touched | Mask(Vanishing, nw, n, ne, w, e, sw, s, se)) & near) != 0 ? Vanishing : Clearable;
                case Cycling1:
                    return (Mask(Cycling3, nw, n, ne, w, e, sw, s, se) & near) != 0 ? Cycling3 : Cycling1;
                case Cycling2:
                    return (Mask(Cycling1, nw, n, ne, w, e, sw, s, se) & near) != 0 ? Cycling1 : Cycling2;
                case Cycling3:
                    return (Mask(Cycling2, nw, n, ne, w, e, sw, s, se) & near) != 0 ? Cycling2 : Cycling3;
                case Hidden:
                    int hit = touched | Mask(Vanishing, nw, n, ne, w, e, sw, s, se) | Mask(Cycling1, nw, n, ne, w, e, sw, s, se);
                    return (hit & near) != 0 ? Cycling1 : Hidden;
                default:
                    return (byte)c;
            }
        }

        /// <summary>The neighbors whose state is <paramref name="value"/>, as bits of the
        /// neighborhood index.</summary>
        private static int Mask(int value, int nw, int n, int ne, int w, int e, int sw, int s, int se)
            => (nw == value ? 256 : 0) | (n == value ? 128 : 0) | (ne == value ? 64 : 0) | (w == value ? 32 : 0)
                | (e == value ? 8 : 0) | (sw == value ? 4 : 0) | (s == value ? 2 : 0) | (se == value ? 1 : 0);

        /// <summary>A newborn's parents, tallied one by one for the rules of spec/super.md "The
        /// newborn's state". A struct, so a birth allocates nothing.</summary>
        private struct Parents
        {
            private int _count;
            private int _noTrail; // the one no-trail state seen, or 0
            private int _trail; // the one trail state seen, or 0
            private bool _notFirst; // a parent other than _noTrail and 3
            private bool _notSecond; // a parent other than _trail and 7
            private bool _notThird; // a parent other than 7 and the no-trail states

            public void Add(int parent)
            {
                _count++;
                bool quiet = parent >= NoTrail;
                if (parent != MarkedOn)
                {
                    if (quiet && (_noTrail == 0 || _noTrail == parent))
                        _noTrail = parent;
                    else
                        _notFirst = true;
                }
                if (parent != NoTrailMarkedOn)
                {
                    if ((parent == SecondTrail || parent == ThirdTrail) && (_trail == 0 || _trail == parent))
                        _trail = parent;
                    else
                        _notSecond = true;
                    if (!quiet)
                        _notThird = true;
                }
            }

            public byte Newborn()
            {
                if (_count == 0)
                    return 1;
                if (!_notFirst && _noTrail != 0)
                    return (byte)_noTrail;
                if (!_notSecond && _trail != 0)
                    return (byte)_trail;
                if (!_notThird)
                    return NoTrail;
                return 1;
            }
        }
    }

    /// <summary>
    /// A Super rule as the multi-state universe runs it (spec/hashlife-multistate.md "State rules"):
    /// 26 states, the rule's canonical name, and spec/super.md's evolution as the cell function. A
    /// base rule with B0 is refused: the plane's background would change. Every spelling of a rule
    /// gives the same object (<see cref="For"/>). The Python reference's <c>SuperRule</c>.
    /// </summary>
    public sealed class SuperRule : StateRule
    {
        private static readonly Dictionary<string, SuperRule> Cache = new Dictionary<string, SuperRule>();

        private readonly byte[] _table;
        private readonly int _near;

        private SuperRule(LifeRule rule)
        {
            Rule = rule;
            _table = rule._TableArray();
            _near = History.NeighborBits(rule.Neighborhood);
        }

        /// <summary>The compiled Super rule (its <see cref="LifeRule.Base"/> is the two-state rule).</summary>
        public LifeRule Rule { get; }

        /// <inheritdoc />
        public override string Canonical => Rule.Canonical;

        /// <inheritdoc />
        public override int States => Super.States;

        /// <summary>The state rule of a compiled Super rule. Throws <see cref="ArgumentException"/>
        /// for a rule without the Super variant, or one whose base has B0 (its first generation
        /// would turn the whole plane on).</summary>
        public static SuperRule For(LifeRule rule)
        {
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            if (rule.Variant != RuleVariant.Super)
                throw new ArgumentException($"{rule.Canonical} is not a Super rule (spec/super.md)", nameof(rule));
            if (rule.HasB0)
                throw new ArgumentException(
                    $"{rule.Canonical} has B0: its first generation would turn the whole plane on, and the "
                    + "unbounded universe's background must stay 0 (spec/super.md \"On the unbounded plane\"); "
                    + "a grid runs it",
                    nameof(rule));
            lock (Cache)
            {
                if (!Cache.TryGetValue(rule.Canonical, out SuperRule? found))
                {
                    if (Cache.Count >= 32)
                        Cache.Clear();
                    found = new SuperRule(rule);
                    Cache[rule.Canonical] = found;
                }
                return found;
            }
        }

        /// <summary>The state rule a Super rule's text names (<c>B3/S23Super</c>, <c>LifeSuper</c>,
        /// any notation of spec/rules.md), or null for text that is no Super rule. Throws for a Super
        /// rule the universe can't run (a base with B0).</summary>
        internal static SuperRule? FromText(string text)
        {
            if (!RuleString.TryCompile(text, true, out LifeRule? rule, out _) || rule.Variant != RuleVariant.Super)
                return null;
            return For(rule);
        }

        /// <inheritdoc />
        public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
            => Super.Next(_table, _near, nw, n, ne, w, c, e, sw, s, se);
    }
}
