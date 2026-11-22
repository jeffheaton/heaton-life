using System;
using System.Diagnostics.CodeAnalysis;

namespace HeatonLife
{
    /// <summary>
    /// A rule over cell states: everything <see cref="MultiStateHashLife"/> knows of a rule
    /// (spec/hashlife-multistate.md "State rules"). A rule has <see cref="States"/> states, from 2
    /// to 256, a <see cref="Canonical"/> name that files give it, and a cell function,
    /// <see cref="NextState"/>, from the 3 × 3 block of states around a cell to its next state.
    /// The engine computes nothing else from a rule, so a family plugs in by deriving from this
    /// class: Wireworld (<see cref="WireworldRule"/>), the Generations, History and Super
    /// families, and rule tables. The cell function must map an all-0 block to 0, or the
    /// infinite background would change.
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

        /// <summary>The rule a name gives: <c>WireWorld</c> or a rule of the rule-table starter set
        /// (spec/ruletable.md), a History rule (spec/history.md), a Super rule (spec/super.md), or a
        /// Generations rule in either spelling (spec/generations.md "Rules"). Every rule it gives is
        /// one the engine runs (<see cref="Check"/> passes it). Any other text throws
        /// <see cref="ArgumentException"/>, its message the reason <see cref="TryCompile"/> gives and
        /// the page that says why (spec/hashlife-multistate.md "Names").</summary>
        public static StateRule Compile(string name)
        {
            if (name == null)
                throw new ArgumentNullException(nameof(name));
            StateRule? rule = Resolve(name, out string reason, out string page);
            if (rule == null)
                throw new ArgumentException($"{reason} ({page})", nameof(name));
            return rule;
        }

        /// <summary>
        /// Like <see cref="Compile"/>, but answers false instead of throwing, with the reason
        /// (spec/hashlife-multistate.md "Names", "Reasons"): the phrase for why the text names no
        /// rule the universe runs, such as "B03/S23/C3 has B0: its first generation would turn the
        /// whole plane on, …", with no page in parentheses and no note of a parameter. The reason is
        /// null when the text names a rule. Null text reads as empty text.
        /// </summary>
        public static bool TryCompile(
            string? name, [NotNullWhen(true)] out StateRule? rule, [NotNullWhen(false)] out string? reason)
        {
            rule = Resolve(name ?? "", out string why, out _);
            reason = rule == null ? why : null;
            return rule != null;
        }

        /// <summary>The reason a History, Super or Generations rule with B0 names no rule the
        /// universe runs (spec/hashlife-multistate.md "Names", reason 1).</summary>
        internal static string B0Reason(string canonical)
            => $"{canonical} has B0: its first generation would turn the whole plane on, and the "
                + "unbounded universe's background must stay 0; a grid runs it";

        /// <summary>The page that says why a History rule with B0 can't run on the plane.</summary>
        internal const string HistoryB0Page = "spec/history.md \"On the unbounded plane\"";

        /// <summary>The page that says why a Super rule with B0 can't run on the plane.</summary>
        internal const string SuperB0Page = "spec/super.md \"On the unbounded plane\"";

        /// <summary>
        /// The rule <paramref name="name"/> gives, or null with the reason and the page that says
        /// why (spec/hashlife-multistate.md "Names"): the fixed names, then History and Super
        /// rules, Generations rules and the rule-table starter set, then Larger than Life's
        /// refusal. <paramref name="reason"/> and <paramref name="page"/> are empty when a rule is
        /// found.
        /// </summary>
        private static StateRule? Resolve(string name, out string reason, out string page)
        {
            reason = "";
            page = "";
            if (Names(name, WireworldRule.Instance))
                return WireworldRule.Instance;
            // History and Super rules, families named by any Life-like rule's text with its
            // variant (spec/history.md, spec/super.md); a base with B0 is refused (reason 1).
            if (RuleString.TryCompile(name, true, out LifeRule? life, out _) && life.Variant != RuleVariant.None)
            {
                bool history = life.Variant == RuleVariant.History;
                if (life.HasB0)
                {
                    reason = B0Reason(life.Canonical);
                    page = history ? HistoryB0Page : SuperB0Page;
                    return null;
                }
                return history ? (StateRule)HistoryRule.For(life) : SuperRule.For(life);
            }
            // Generations rules, in either spelling (spec/generations.md); B0 is refused (reason 1).
            if (GenerationsRule.TryCompile(name, out GenerationsRule? generations, out _))
            {
                if (generations.HasB0)
                {
                    reason = B0Reason(generations.Canonical);
                    page = "spec/generations.md \"The unbounded plane\"";
                    return null;
                }
                return generations;
            }
            // The rule-table starter set (spec/ruletable.md "The starter set"), read when named.
            RuleTable? starter = RuleTables.StarterOrNull(Trimmed(name));
            if (starter != null)
                return starter;
            string? ltl = LtlRule.PlaneReason(name); // Larger than Life: grids only (reason 2)
            if (ltl != null)
            {
                reason = ltl;
                page = "spec/ltl.md";
                return null;
            }
            reason = $"'{name}' is not a state rule (known: {WireworldRule.Instance.Canonical}, "
                + $"{string.Join(", ", RuleTables.StarterNames)}, History rules such as B3/S23History, "
                + "Super rules such as B3/S23Super, and Generations rules such as B2/S345/C4)";
            page = "spec/hashlife-multistate.md \"Names\"";
            return null;
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

        /// <summary><paramref name="text"/> without spec/rules.md's whitespace at its two ends.</summary>
        private static string Trimmed(string text)
        {
            int start = 0, end = text.Length;
            while (start < end && RuleString.IsSpace(text[start]))
                start++;
            while (end > start && RuleString.IsSpace(text[end - 1]))
                end--;
            return text.Substring(start, end - start);
        }
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
