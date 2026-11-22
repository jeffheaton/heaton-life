using System;
using System.Collections.Generic;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// A Life-like world converted between the two engines (spec/hashlife-multistate.md
    /// "Converting between the engines"). The cells never become a grid: each distinct node of the
    /// old tree is converted once, into the new universe's store, and the tree keeps its root, its
    /// level and its place. A two-state universe's live cells become state 1 of a History or Super
    /// rule; a History or Super universe's on cells, its odd states, become a two-state universe's
    /// live cells; and a History or Super universe under another of those rules keeps each state
    /// the rule has and turns any other into its parity. The Python reference's
    /// heaton_life.ca.hashlife.multistate.convert; the public calls are
    /// <see cref="HashLife.ToMultiState(StateRule, int?)"/>,
    /// <see cref="MultiStateHashLife.ToTwoState(string, int?)"/> and
    /// <see cref="MultiStateHashLife.ToMultiState(StateRule, int?)"/>.
    /// </summary>
    internal static class HashLifeConversion
    {
        private const string Page = "spec/hashlife-multistate.md \"Converting between the engines\"";

        private static void RequireLifeLike(StateRule rule, string whose)
        {
            if (!(rule is HistoryRule || rule is SuperRule))
                throw new ArgumentException(
                    $"{whose}{rule.Canonical} is no History or Super rule: a world converts between Life-like rules "
                    + $"only, two states, History and Super ({Page})");
        }

        internal static MultiStateHashLife ToMultiState(HashLife universe, StateRule rule, int? maxMemoryMb)
        {
            StateRule target = StateRules.Check(rule);
            RequireLifeLike(target, "");
            if (universe.BackgroundAlive)
                throw new ArgumentException(
                    $"the universe's background is alive at generation {universe.Generation} (its rule {universe.Rule} "
                    + $"has B0): a universe of many states has a background of 0 ({Page})");
            var output = new MultiStateHashLife(target, maxMemoryMb ?? universe.MaxMemoryMb);
            HashLifeStore src = universe.Store;
            MultiStateStore dst = output.Store;
            int root = Walk(
                src.Root, src.Level, 3, (n, k) => n == src.Empty(k), dst.Empty,
                n => MultiStateMacrocell.BitsNode(dst, src.Bits(n)), src.Kid, dst.Join);
            output.Adopt(root, src.Level, universe.Generation);
            return output;
        }

        internal static HashLife ToTwoState(MultiStateHashLife universe, string rule, int? maxMemoryMb)
        {
            RequireLifeLike(universe.StateRule, "the universe's rule ");
            var output = new HashLife(rule, maxMemoryMb ?? universe.MaxMemoryMb);
            BigInteger generation = universe.Generation;
            if (RuleString.Compile(output.Rule).BackgroundAlive(generation))
                throw new ArgumentException(
                    $"{output.Rule} has B0 and its background is alive at generation {generation}: the world's cells, "
                    + $"on a background of 0, can't be its cells ({Page}; spec/hashlife.md \"Rules with B0\")");
            MultiStateStore src = universe.Store;
            HashLifeStore dst = output.Store;
            int root = src.Root, level = src.Level;
            while (level < 4) // the two-state tree's leaves are 8 × 8, its root at least level 4
            {
                root = universe.Expand(root, level);
                level++;
            }
            int converted = Walk(
                root, level, 3, (n, k) => n == src.Empty(k), dst.Empty, n => dst.Leaf(OddBits(src, n)), src.Kid,
                dst.Join);
            output.Adopt(converted, level, generation);
            return output;
        }

        internal static MultiStateHashLife ToMultiState(MultiStateHashLife universe, StateRule rule, int? maxMemoryMb)
        {
            RequireLifeLike(universe.StateRule, "the universe's rule ");
            StateRule target = StateRules.Check(rule);
            RequireLifeLike(target, "");
            var output = new MultiStateHashLife(target, maxMemoryMb ?? universe.MaxMemoryMb);
            var table = new byte[256];
            for (int state = 0; state < 256; state++)
                table[state] = (byte)(state < target.States ? state : state & 1);
            MultiStateStore src = universe.Store;
            MultiStateStore dst = output.Store;
            int mapped = Walk(
                src.Root, src.Level, 1, (n, k) => n == src.Empty(k), dst.Empty,
                n =>
                {
                    int states = src.States(n);
                    return dst.Leaf(table[states & 0xFF] | table[(states >> 8) & 0xFF] << 8
                        | table[(states >> 16) & 0xFF] << 16 | table[(states >> 24) & 0xFF] << 24);
                },
                src.Kid, dst.Join);
            output.Adopt(mapped, src.Level, universe.Generation);
            return output;
        }

        /// <summary>
        /// The old tree from (<paramref name="root"/>, <paramref name="level"/>) rebuilt in the new
        /// store, each distinct node once: an empty node as the new store's empty node of its level,
        /// a node of <paramref name="baseLevel"/> by <paramref name="convertBase"/>, and any other as
        /// the join of its converted children. The nodes wait on the walk's own stack, not the
        /// thread's, so a tree of any level converts on any thread.
        /// </summary>
        private static int Walk(
            int root, int level, int baseLevel, Func<int, int, bool> emptyIn, Func<int, int> emptyOut,
            Func<int, int> convertBase, Func<int, int, int> kid, Func<int, int, int, int, int> join)
        {
            var memo = new Dictionary<int, int>();
            var pending = new Stack<(int Node, int Level)>();
            pending.Push((root, level));
            while (pending.Count > 0)
            {
                (int n, int k) = pending.Peek();
                if (memo.ContainsKey(n))
                {
                    pending.Pop();
                    continue;
                }
                if (emptyIn(n, k))
                {
                    memo[n] = emptyOut(k);
                    pending.Pop();
                    continue;
                }
                if (k == baseLevel)
                {
                    memo[n] = convertBase(n);
                    pending.Pop();
                    continue;
                }
                bool ready = true;
                for (int q = 0; q < 4; q++)
                {
                    int child = kid(n, q);
                    if (!memo.ContainsKey(child))
                    {
                        pending.Push((child, k - 1));
                        ready = false;
                    }
                }
                if (!ready)
                    continue;
                memo[n] = join(memo[kid(n, 0)], memo[kid(n, 1)], memo[kid(n, 2)], memo[kid(n, 3)]);
                pending.Pop();
            }
            return memo[root];
        }

        /// <summary>A level-3 node of states as a two-state 8 × 8 leaf (bit 8r + c is row r, column
        /// c): its odd cells live.</summary>
        private static ulong OddBits(MultiStateStore store, int n)
        {
            ulong bits = 0;
            for (int q = 0; q < 4; q++)
            {
                int quarter = store.Kid(n, q);
                int qx = 4 * (q & 1), qy = 4 * (q >> 1);
                for (int l = 0; l < 4; l++)
                {
                    int states = store.States(store.Kid(quarter, l));
                    int x = qx + 2 * (l & 1), y = qy + 2 * (l >> 1);
                    bits |= (ulong)(states & 1) << (8 * y + x)
                        | (ulong)((states >> 8) & 1) << (8 * y + x + 1)
                        | (ulong)((states >> 16) & 1) << (8 * y + x + 8)
                        | (ulong)((states >> 24) & 1) << (8 * y + x + 9);
                }
            }
            return bits;
        }
    }
}
