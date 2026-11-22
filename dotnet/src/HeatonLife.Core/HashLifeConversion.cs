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
            var memo = new Dictionary<int, int>();
            int root = FromTwoState(src, dst, src.Root, src.Level, memo);
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
            var memo = new Dictionary<int, int>();
            output.Adopt(ToTwoState(src, dst, root, level, memo), level, generation);
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
            var memo = new Dictionary<int, int>();
            output.Adopt(Mapped(src, dst, src.Root, src.Level, table, memo), src.Level, universe.Generation);
            return output;
        }

        private static int FromTwoState(HashLifeStore src, MultiStateStore dst, int n, int k, Dictionary<int, int> memo)
        {
            if (n == src.Empty(k))
                return dst.Empty(k);
            if (memo.TryGetValue(n, out int hit))
                return hit;
            int r = k == 3
                ? MultiStateMacrocell.BitsNode(dst, src.Bits(n))
                : dst.Join(
                    FromTwoState(src, dst, src.Kid(n, 0), k - 1, memo), FromTwoState(src, dst, src.Kid(n, 1), k - 1, memo),
                    FromTwoState(src, dst, src.Kid(n, 2), k - 1, memo), FromTwoState(src, dst, src.Kid(n, 3), k - 1, memo));
            memo[n] = r;
            return r;
        }

        private static int ToTwoState(MultiStateStore src, HashLifeStore dst, int n, int k, Dictionary<int, int> memo)
        {
            if (n == src.Empty(k))
                return dst.Empty(k);
            if (memo.TryGetValue(n, out int hit))
                return hit;
            int r = k == 3
                ? dst.Leaf(OddBits(src, n))
                : dst.Join(
                    ToTwoState(src, dst, src.Kid(n, 0), k - 1, memo), ToTwoState(src, dst, src.Kid(n, 1), k - 1, memo),
                    ToTwoState(src, dst, src.Kid(n, 2), k - 1, memo), ToTwoState(src, dst, src.Kid(n, 3), k - 1, memo));
            memo[n] = r;
            return r;
        }

        private static int Mapped(
            MultiStateStore src, MultiStateStore dst, int n, int k, byte[] table, Dictionary<int, int> memo)
        {
            if (n == src.Empty(k))
                return dst.Empty(k);
            if (memo.TryGetValue(n, out int hit))
                return hit;
            int r;
            if (k == 1)
            {
                int states = src.States(n);
                r = dst.Leaf(table[states & 0xFF] | table[(states >> 8) & 0xFF] << 8
                    | table[(states >> 16) & 0xFF] << 16 | table[(states >> 24) & 0xFF] << 24);
            }
            else
            {
                r = dst.Join(
                    Mapped(src, dst, src.Kid(n, 0), k - 1, table, memo), Mapped(src, dst, src.Kid(n, 1), k - 1, table, memo),
                    Mapped(src, dst, src.Kid(n, 2), k - 1, table, memo), Mapped(src, dst, src.Kid(n, 3), k - 1, table, memo));
            }
            memo[n] = r;
            return r;
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
