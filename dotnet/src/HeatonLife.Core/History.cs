using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>
    /// History rules (spec/history.md): any Life-like rule with seven states. The on cells (odd
    /// states) run the base rule's table exactly as a two-state world's live cells do; the other
    /// states record the envelope (cells once on) and marks, and boundary cells (6) never change
    /// and keep every cell beside them off. This class holds the one table of state changes that
    /// the Life-like grid (<see cref="LifeLike"/>) and the multi-state universe
    /// (<see cref="HistoryRule"/>) both run. The Python reference's <c>heaton_life.ca.history</c>.
    /// Variants with more states (Super, 26) plug in the same way: a state count, a table of state
    /// changes, and a cell function.
    /// </summary>
    public static class History
    {
        /// <summary>A History rule's states (spec/history.md "States").</summary>
        public const int States = LifeRule.HistoryStates;

        /// <summary>State 0: off.</summary>
        public const byte Off = 0;

        /// <summary>State 1: on.</summary>
        public const byte On = 1;

        /// <summary>State 2: the envelope, off and once on.</summary>
        public const byte Envelope = 2;

        /// <summary>State 3: marked on.</summary>
        public const byte MarkedOn = 3;

        /// <summary>State 4: marked off.</summary>
        public const byte MarkedOff = 4;

        /// <summary>State 5: start on; once dead it is marked off, and never start-on again.</summary>
        public const byte StartOn = 5;

        /// <summary>State 6: boundary; it never changes, counts as off, and keeps every cell
        /// beside it off.</summary>
        public const byte Boundary = 6;

        /// <summary>Each state's letter in the extended dialect of RLE (spec/patterns.md), state n
        /// at index n.</summary>
        public const string Letters = ".ABCDEF";

        /// <summary><c>Next[2 * state + on]</c>: a cell's next state from its state and whether it
        /// is on next (spec/history.md "Evolution").</summary>
        private static readonly byte[] Next = { 0, 1, 2, 1, 2, 1, 4, 3, 4, 3, 4, 5, 6, 6 };

        /// <summary>A cell's next state from its state (0–6) and whether it is on next, as
        /// spec/history.md's table gives it.</summary>
        public static byte NextState(byte state, bool on)
        {
            if (state >= States)
                throw new ArgumentOutOfRangeException(nameof(state), state, "a History state is 0 to 6");
            return Next[2 * state + (on ? 1 : 0)];
        }

        /// <summary>The table itself, for the grid's loop.</summary>
        internal static byte[] Table => Next;

        /// <summary>The neighbors whose boundary cells keep a cell off, as bits of the
        /// neighborhood index (NW 256, N 128, NE 64, W 32, E 8, SW 4, S 2, SE 1): the rule's own
        /// neighborhood (spec/rules.md "Neighborhoods").</summary>
        internal static int NeighborBits(RuleNeighborhood neighborhood)
            => neighborhood == RuleNeighborhood.Hexagonal ? 0x1AB
                : neighborhood == RuleNeighborhood.VonNeumann ? 0xAA
                : 0x1EF;
    }

    /// <summary>
    /// A History rule as the multi-state universe runs it (spec/hashlife-multistate.md "State
    /// rules"): seven states, the rule's canonical name, and spec/history.md's evolution as the
    /// cell function. A base rule with B0 is refused: the plane's background would change. Every
    /// spelling of a rule gives the same object (<see cref="For"/>). The Python reference's
    /// <c>HistoryRule</c>.
    /// </summary>
    public sealed class HistoryRule : StateRule
    {
        private static readonly Dictionary<string, HistoryRule> Cache = new Dictionary<string, HistoryRule>();

        private readonly byte[] _table;
        private readonly int _near;

        private HistoryRule(LifeRule rule)
        {
            Rule = rule;
            _table = rule._TableArray();
            _near = History.NeighborBits(rule.Neighborhood);
        }

        /// <summary>The compiled History rule (its <see cref="LifeRule.Base"/> is the two-state rule).</summary>
        public LifeRule Rule { get; }

        /// <inheritdoc />
        public override string Canonical => Rule.Canonical;

        /// <inheritdoc />
        public override int States => History.States;

        /// <summary>The state rule of a compiled History rule. Throws
        /// <see cref="ArgumentException"/> for a rule without the History variant, or one whose
        /// base has B0 (its first generation would turn the whole plane on).</summary>
        public static HistoryRule For(LifeRule rule)
        {
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            if (rule.Variant != RuleVariant.History)
                throw new ArgumentException($"{rule.Canonical} is not a History rule (spec/history.md)", nameof(rule));
            if (rule.HasB0)
                throw new ArgumentException(
                    $"{rule.Canonical} has B0: its first generation would turn the whole plane on, and the "
                    + "unbounded universe's background must stay 0 (spec/history.md \"On the unbounded plane\"); "
                    + "a grid runs it",
                    nameof(rule));
            lock (Cache)
            {
                if (!Cache.TryGetValue(rule.Canonical, out HistoryRule? found))
                {
                    if (Cache.Count >= 32)
                        Cache.Clear();
                    found = new HistoryRule(rule);
                    Cache[rule.Canonical] = found;
                }
                return found;
            }
        }

        /// <summary>The state rule a History rule's text names (<c>B3/S23History</c>,
        /// <c>LifeHistory</c>, any notation of spec/rules.md), or null for text that is no History
        /// rule. Throws for a History rule the universe can't run (a base with B0).</summary>
        internal static HistoryRule? FromText(string text)
        {
            if (!RuleString.TryCompile(text, true, out LifeRule? rule, out _) || rule.Variant != RuleVariant.History)
                return null;
            return For(rule);
        }

        /// <inheritdoc />
        public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
        {
            if (c == History.Boundary)
                return History.Boundary;
            int index = ((nw & 1) << 8) | ((n & 1) << 7) | ((ne & 1) << 6) | ((w & 1) << 5) | ((c & 1) << 4)
                | ((e & 1) << 3) | ((sw & 1) << 2) | ((s & 1) << 1) | (se & 1);
            int boundary = (nw == History.Boundary ? 256 : 0) | (n == History.Boundary ? 128 : 0)
                | (ne == History.Boundary ? 64 : 0) | (w == History.Boundary ? 32 : 0)
                | (e == History.Boundary ? 8 : 0) | (sw == History.Boundary ? 4 : 0)
                | (s == History.Boundary ? 2 : 0) | (se == History.Boundary ? 1 : 0);
            int on = (boundary & _near) == 0 ? _table[index] : 0;
            return History.Table[2 * c + on];
        }
    }
}
