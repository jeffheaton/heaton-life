using System;

namespace HeatonLife
{
    /// <summary>
    /// A rule over cell states: everything <see cref="MultiStateHashLife"/> knows of a rule
    /// (spec/hashlife-multistate.md "State rules"). A rule has <see cref="States"/> states, from 2
    /// to 256, a <see cref="Canonical"/> name that files give it, and a cell function,
    /// <see cref="NextState"/>, from the 3 × 3 block of states around a cell to its next state.
    /// The engine computes nothing else from a rule, so a family plugs in by deriving from this
    /// class: Wireworld today (<see cref="WireworldRule"/>), and the Generations, History and
    /// Super, and rule-table families as their pages add them. The cell function must map an
    /// all-0 block to 0, or the infinite background would change.
    /// The Python reference's heaton_life.ca.state_rules.StateRule.
    /// </summary>
    public abstract class StateRule
    {
        /// <summary>The rule's canonical name: printable ASCII, with no whitespace and no comma.</summary>
        public abstract string Canonical { get; }

        /// <summary>S: every state is from 0 to S − 1, and S is from 2 to 256.</summary>
        public abstract int States { get; }

        /// <summary>The next state of the center cell <paramref name="c"/> from its 3 × 3 block,
        /// laid out as spec/rules.md lays it out: NW N NE / W C E / SW S SE. Every argument and
        /// the result are states below <see cref="States"/>.</summary>
        public abstract byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se);

        public override string ToString() => $"{GetType().Name}({Canonical}, states={States})";
    }

    /// <summary>
    /// Rule names for <see cref="MultiStateHashLife"/> (spec/hashlife-multistate.md "Names"): a
    /// name may carry the whitespace of spec/rules.md at its two ends and is matched ignoring
    /// ASCII case. The Python reference's state_rule, check_state_rule and names_rule.
    /// </summary>
    public static class StateRules
    {
        /// <summary>The most states a rule may have: a state is one byte.</summary>
        public const int MaxStates = 256;

        /// <summary>Wireworld (spec/wireworld.md), named <c>WireWorld</c>.</summary>
        public static StateRule Wireworld => WireworldRule.Instance;

        /// <summary>The rule a name gives; any text that names no rule throws
        /// <see cref="ArgumentException"/>.</summary>
        public static StateRule Compile(string name)
        {
            if (name == null)
                throw new ArgumentNullException(nameof(name));
            if (Names(name, WireworldRule.Instance))
                return WireworldRule.Instance;
            // History rules, a family named by any Life-like rule's text (spec/history.md).
            HistoryRule? history = HistoryRule.FromText(name);
            if (history != null)
                return history;
            throw new ArgumentException(
                $"'{name}' is not a state rule (known: {WireworldRule.Instance.Canonical}, and History rules "
                + "such as B3/S23History)",
                nameof(name));
        }

        /// <summary>Whether <paramref name="text"/> names <paramref name="rule"/>: its canonical
        /// name, ignoring whitespace at the two ends and ASCII case.</summary>
        public static bool Names(string text, StateRule rule)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            int start = 0, end = text.Length;
            while (start < end && RuleString.IsSpace(text[start]))
                start++;
            while (end > start && RuleString.IsSpace(text[end - 1]))
                end--;
            string canonical = rule.Canonical;
            if (end - start != canonical.Length)
                return false;
            for (int i = 0; i < canonical.Length; i++)
            {
                if (AsciiLower(text[start + i]) != AsciiLower(canonical[i]))
                    return false;
            }
            return true;
        }

        /// <summary>
        /// <paramref name="rule"/> itself, once it is known to be one the engine can run: 2 to 256
        /// states, a canonical name a file can carry, and a background that stays 0. Anything else
        /// throws <see cref="ArgumentException"/>.
        /// </summary>
        public static StateRule Check(StateRule rule)
        {
            if (rule == null)
                throw new ArgumentNullException(nameof(rule));
            int states = rule.States;
            if (states < 2 || states > MaxStates)
                throw new ArgumentException($"a state rule has 2 to {MaxStates} states, not {states}", nameof(rule));
            string? name = rule.Canonical;
            bool good = !string.IsNullOrEmpty(name);
            if (good)
            {
                foreach (char c in name!)
                {
                    if (c <= ' ' || c > '~' || c == ',')
                        good = false;
                }
            }
            if (!good)
                throw new ArgumentException(
                    $"a state rule's canonical name is printable ASCII without spaces or commas, not '{name}'", nameof(rule));
            if (rule.NextState(0, 0, 0, 0, 0, 0, 0, 0, 0) != 0)
                throw new ArgumentException(
                    $"{name} turns an all-0 block into another state: the infinite background would change "
                    + "(spec/hashlife-multistate.md \"State rules\")", nameof(rule));
            return rule;
        }

        private static char AsciiLower(char c) => c >= 'A' && c <= 'Z' ? (char)(c + ('a' - 'A')) : c;
    }

    /// <summary>
    /// Wireworld's cell function (spec/wireworld.md), the rule <see cref="MultiStateHashLife"/>
    /// runs as <c>WireWorld</c>: a head becomes a tail, a tail a conductor, and a conductor a head
    /// when one or two of its eight neighbors are heads. The grid family
    /// (<see cref="HeatonLife.Wireworld"/>) computes the same generation; the vectors pin that
    /// the two agree. The Python reference's heaton_life.ca.wireworld.WireworldRule.
    /// </summary>
    public sealed class WireworldRule : StateRule
    {
        /// <summary>The one instance.</summary>
        public static readonly WireworldRule Instance = new WireworldRule();

        private WireworldRule()
        {
        }

        public override string Canonical => "WireWorld";

        public override int States => 4;

        public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
        {
            switch (c)
            {
                case HeatonLife.Wireworld.Head:
                    return HeatonLife.Wireworld.Tail;
                case HeatonLife.Wireworld.Tail:
                    return HeatonLife.Wireworld.Conductor;
                case HeatonLife.Wireworld.Conductor:
                    int heads = (nw == 1 ? 1 : 0) + (n == 1 ? 1 : 0) + (ne == 1 ? 1 : 0) + (w == 1 ? 1 : 0)
                        + (e == 1 ? 1 : 0) + (sw == 1 ? 1 : 0) + (s == 1 ? 1 : 0) + (se == 1 ? 1 : 0);
                    return heads == 1 || heads == 2 ? HeatonLife.Wireworld.Head : HeatonLife.Wireworld.Conductor;
                default:
                    return HeatonLife.Wireworld.Empty;
            }
        }
    }
}
