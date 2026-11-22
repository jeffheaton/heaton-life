using System;
using System.Collections.Generic;
using System.Text;

namespace HeatonLife
{
    /// <summary>
    /// A text that is no rule file (spec/rule-files.md "Why a text is no rule file"): the reason
    /// the page gives for the first problem found, and the line (counted from 1) where it is, or
    /// null where the whole file is at fault. The Python reference's RuleFileError.
    /// </summary>
    public sealed class RuleFileException : FormatException
    {
        public RuleFileException(string reason, int? line)
            : base($"invalid rule file: {(line == null ? "" : $"line {line}: ")}{reason} (spec/rule-files.md)")
        {
            Reason = reason;
            Line = line;
        }

        /// <summary>The reason, as spec/rule-files.md words it.</summary>
        public string Reason { get; }

        /// <summary>The line the problem is on, counted from 1, or null for the whole file.</summary>
        public int? Line { get; }
    }

    /// <summary>Where a rule file's function came from.</summary>
    public enum RuleSource
    {
        /// <summary>An <c>@TABLE</c> section, compiled to a tree.</summary>
        Table,

        /// <summary>An <c>@TREE</c> section.</summary>
        Tree,
    }

    /// <summary>
    /// A <c>@COLORS</c> entry (spec/rule-files.md "@COLORS"): a state's color, or a gradient
    /// over states 1 to S − 1 from <see cref="Start"/> to <see cref="End"/>.
    /// </summary>
    public sealed class RuleColor
    {
        internal RuleColor(int state, (byte R, byte G, byte B) start, (byte R, byte G, byte B)? end)
        {
            State = state;
            Start = start;
            End = end;
        }

        /// <summary>Whether this entry is a gradient.</summary>
        public bool IsGradient => End != null;

        /// <summary>The state a state color is for; −1 for a gradient.</summary>
        public int State { get; }

        /// <summary>A state color's color, or a gradient's first color.</summary>
        public (byte R, byte G, byte B) Start { get; }

        /// <summary>A gradient's last color; null for a state color.</summary>
        public (byte R, byte G, byte B)? End { get; }
    }

    /// <summary>A <c>@NAMES</c> entry: a state and its name.</summary>
    public sealed class RuleStateName
    {
        internal RuleStateName(int state, string name)
        {
            State = state;
            Name = name;
        }

        public int State { get; }

        public string Name { get; }
    }

    /// <summary>
    /// One XPM set of <c>@ICONS</c> (spec/rule-files.md "@ICONS"): the icons' width (7, 15 or
    /// 31), the colors (each a key and <c>#RRGGBB</c> in uppercase, or null for no color) and
    /// the rows as written. Icon k (rows k·width to k·width + width − 1) is for state k + 1.
    /// </summary>
    public sealed class RuleIconSet
    {
        internal RuleIconSet(int width, IReadOnlyList<(string Key, string? Color)> colors, IReadOnlyList<string> rows)
        {
            Width = width;
            Colors = colors;
            Rows = rows;
        }

        public int Width { get; }

        public IReadOnlyList<(string Key, string? Color)> Colors { get; }

        public IReadOnlyList<string> Rows { get; }

        /// <summary>How many icons the set holds.</summary>
        public int Count => Rows.Count / Width;
    }

    /// <summary>A file's <c>@ICONS</c>: a style (<c>circles</c>, <c>diamonds</c>,
    /// <c>hexagons</c> or <c>triangles</c>), or the XPM sets kept, in file order.</summary>
    public sealed class RuleIcons
    {
        internal RuleIcons(string? style, IReadOnlyList<RuleIconSet> sets)
        {
            Style = style;
            Sets = sets;
        }

        public string? Style { get; }

        public IReadOnlyList<RuleIconSet> Sets { get; }
    }

    /// <summary>
    /// A rule file's rule (spec/rule-files.md): its name, states, neighborhood, its function as
    /// a canonical tree, and the file's colors, names and icons as read. A
    /// <see cref="StateRule"/>: <see cref="MultiStateHashLife"/> runs it, and the rule-table
    /// family (<see cref="RuleTableCA"/>, spec/ruletable.md) runs it on a grid. Made by
    /// <see cref="Parse"/>. The Python reference's heaton_life.ca.rulefile.RuleTable.
    /// </summary>
    public sealed class RuleTable : StateRule
    {
        /// <summary>The most states a rule may have: a state is one byte.</summary>
        public const int MaxStates = 256;

        private readonly int[] _levels;
        private readonly int[] _children; // node i's child v at [i * States + v]
        private readonly int _root;
        private readonly int _states;
        private readonly string _name;

        private RuleTable(
            string name, int states, int neighbors, List<(int Level, int[] Children)> nodes, string? neighborhood,
            string? symmetries, RuleSource source, string description, IReadOnlyList<RuleColor> colors,
            IReadOnlyList<RuleStateName> names, RuleIcons? icons, string text)
        {
            _name = name;
            _states = states;
            Neighbors = neighbors;
            Neighborhood = neighborhood;
            Symmetries = symmetries;
            Source = source;
            Description = description;
            Colors = colors;
            Names = names;
            Icons = icons;
            Text = text;
            _levels = new int[nodes.Count];
            _children = new int[nodes.Count * states];
            for (int i = 0; i < nodes.Count; i++)
            {
                _levels[i] = nodes[i].Level;
                Array.Copy(nodes[i].Children, 0, _children, i * states, states);
            }
            _root = nodes.Count - 1;
        }

        /// <summary>The rule's name, as the file writes it: its canonical name.</summary>
        public string Name => _name;

        /// <inheritdoc />
        public override string Canonical => _name;

        /// <inheritdoc />
        public override int States => _states;

        /// <summary>4 (the von Neumann cells) or 8 (the Moore block): the tree's neighbors.</summary>
        public int Neighbors { get; }

        /// <summary>A table's neighborhood (<c>vonNeumann</c>, <c>Moore</c>, <c>hexagonal</c> or
        /// <c>oneDimensional</c>), or null for a tree.</summary>
        public string? Neighborhood { get; }

        /// <summary>A table's symmetries in their canonical spelling, or null for a tree.</summary>
        public string? Symmetries { get; }

        /// <summary>The section that gave the function.</summary>
        public RuleSource Source { get; }

        /// <summary>The <c>@RULE</c> section's description.</summary>
        public string Description { get; }

        /// <summary>The <c>@COLORS</c> entries kept, in file order.</summary>
        public IReadOnlyList<RuleColor> Colors { get; }

        /// <summary>The <c>@NAMES</c> entries kept, in file order.</summary>
        public IReadOnlyList<RuleStateName> Names { get; }

        /// <summary>The <c>@ICONS</c> section, or null without one.</summary>
        public RuleIcons? Icons { get; }

        /// <summary>The file's text as given.</summary>
        public string Text { get; }

        /// <summary>How many nodes the canonical tree has.</summary>
        public int NodeCount => _levels.Length;

        internal int[] Children => _children;

        internal int Root => _root;

        /// <summary>
        /// The rule a rule file defines (spec/rule-files.md). Throws
        /// <see cref="RuleFileException"/> with the reason the page gives for the first problem
        /// found.
        /// </summary>
        public static RuleTable Parse(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            return RuleFileParser.Parse(text);
        }

        /// <summary><see cref="Parse"/> without throwing for a text that is no rule file: false
        /// with the error (its <see cref="RuleFileException.Reason"/> and
        /// <see cref="RuleFileException.Line"/>).</summary>
        public static bool TryParse(string text, out RuleTable? rule, out RuleFileException? error)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            try
            {
                rule = RuleFileParser.Parse(text);
                error = null;
                return true;
            }
            catch (RuleFileException e)
            {
                rule = null;
                error = e;
                return false;
            }
        }

        internal static RuleTable Make(
            string name, int states, int neighbors, List<(int Level, int[] Children)> nodes, string? neighborhood,
            string? symmetries, RuleSource source, string description, IReadOnlyList<RuleColor> colors,
            IReadOnlyList<RuleStateName> names, RuleIcons? icons, string text)
            => new RuleTable(
                name, states, neighbors, nodes, neighborhood, symmetries, source, description, colors, names, icons, text);

        /// <summary>The canonical tree as <c>@TREE</c> text (spec/rule-files.md "Compiling a table
        /// to a tree").</summary>
        public string TreeText()
        {
            var text = new StringBuilder();
            text.Append("num_states=").Append(_states).Append('\n');
            text.Append("num_neighbors=").Append(Neighbors).Append('\n');
            text.Append("num_nodes=").Append(_levels.Length).Append('\n');
            for (int i = 0; i < _levels.Length; i++)
            {
                text.Append(_levels[i]);
                for (int v = 0; v < _states; v++)
                    text.Append(' ').Append(_children[i * _states + v]);
                text.Append('\n');
            }
            return text.ToString();
        }

        /// <inheritdoc />
        public override byte NextState(byte nw, byte n, byte ne, byte w, byte c, byte e, byte sw, byte s, byte se)
        {
            int[] k = _children;
            int states = _states;
            int i;
            if (Neighbors == 8)
            {
                i = k[_root * states + nw];
                i = k[i * states + ne];
                i = k[i * states + sw];
                i = k[i * states + se];
                i = k[i * states + n];
            }
            else
            {
                i = k[_root * states + n];
            }
            i = k[i * states + w];
            i = k[i * states + e];
            i = k[i * states + s];
            return (byte)k[i * states + c];
        }

        public override string ToString() => $"RuleTable({_name}, states={_states}, neighbors={Neighbors})";
    }

    /// <summary>Reading a rule file and compiling its table (spec/rule-files.md); the Python
    /// reference's heaton_life.ca.rulefile, function for function.</summary>
    internal static class RuleFileParser
    {
        internal static readonly string[] NeighborhoodNames = { "vonNeumann", "Moore", "hexagonal", "oneDimensional" };

        // Each neighborhood's symmetries: (spelling, canonical), in the order a reason lists them.
        private static readonly (string, string)[] VonNeumannSymmetries =
        {
            ("none", "none"), ("rotate4", "rotate4"), ("rotate4reflect", "rotate4reflect"),
            ("reflect_horizontal", "reflect_horizontal"), ("reflect", "reflect_horizontal"), ("permute", "permute"),
        };

        private static readonly (string, string)[] MooreSymmetries =
        {
            ("none", "none"), ("rotate4", "rotate4"), ("rotate8", "rotate8"), ("rotate4reflect", "rotate4reflect"),
            ("rotate8reflect", "rotate8reflect"), ("reflect_horizontal", "reflect_horizontal"),
            ("reflect", "reflect_horizontal"), ("permute", "permute"),
        };

        private static readonly (string, string)[] HexagonalSymmetries =
        {
            ("none", "none"), ("rotate2", "rotate2"), ("rotate3", "rotate3"), ("rotate6", "rotate6"),
            ("rotate6reflect", "rotate6reflect"), ("permute", "permute"),
        };

        private static readonly (string, string)[] OneDimensionalSymmetries =
        {
            ("none", "none"), ("reflect", "reflect"), ("reflect_horizontal", "reflect"), ("permute", "permute"),
        };

        // The block's cells, numbered as StateRule.NextState takes them.
        internal const int NW = 0, N = 1, NE = 2, W = 3, C = 4, E = 5, SW = 6, S = 7, SE = 8;

        /// <summary>The cells a tree walks, root first.</summary>
        internal static readonly int[] TreeOrder8 = { NW, NE, SW, SE, N, W, E, S, C };

        internal static readonly int[] TreeOrder4 = { N, W, E, S, C };

        private static readonly string[] IconStyles = { "circles", "diamonds", "hexagons", "triangles" };

        internal static int[] Ring(string neighborhood) => neighborhood switch
        {
            "vonNeumann" => new[] { N, E, S, W },
            "Moore" => new[] { N, NE, E, SE, S, SW, W, NW },
            "hexagonal" => new[] { N, E, SE, S, W, NW },
            _ => new[] { W, E },
        };

        internal static int TreeNeighbors(string neighborhood)
            => neighborhood == "Moore" || neighborhood == "hexagonal" ? 8 : 4;

        private static (string, string)[] SymmetriesOf(string neighborhood) => neighborhood switch
        {
            "vonNeumann" => VonNeumannSymmetries,
            "Moore" => MooreSymmetries,
            "hexagonal" => HexagonalSymmetries,
            _ => OneDimensionalSymmetries,
        };

        // -- lines ----------------------------------------------------------------------------

        internal static string Trim(string text)
        {
            int start = 0, end = text.Length;
            while (start < end && RuleString.IsSpace(text[start]))
                start++;
            while (end > start && RuleString.IsSpace(text[end - 1]))
                end--;
            return text.Substring(start, end - start);
        }

        internal static List<string> Words(string text)
        {
            var words = new List<string>();
            int start = -1;
            for (int i = 0; i < text.Length; i++)
            {
                if (RuleString.IsSpace(text[i]))
                {
                    if (start >= 0)
                    {
                        words.Add(text.Substring(start, i - start));
                        start = -1;
                    }
                }
                else if (start < 0)
                {
                    start = i;
                }
            }
            if (start >= 0)
                words.Add(text.Substring(start));
            return words;
        }

        private static string Lower(string text)
        {
            var chars = text.ToCharArray();
            for (int i = 0; i < chars.Length; i++)
            {
                if (chars[i] >= 'A' && chars[i] <= 'Z')
                    chars[i] = (char)(chars[i] + ('a' - 'A'));
            }
            return new string(chars);
        }

        private static bool IsDigits(string text)
        {
            if (text.Length == 0)
                return false;
            foreach (char c in text)
            {
                if (c < '0' || c > '9')
                    return false;
            }
            return true;
        }

        /// <summary>Decimal digits as a number when it is at most <paramref name="limit"/>, else
        /// −1.</summary>
        private static int Number(string text, int limit)
        {
            if (!IsDigits(text))
                return -1;
            int start = 0;
            while (start < text.Length && text[start] == '0')
                start++;
            int digits = text.Length - start;
            if (digits > limit.ToString(System.Globalization.CultureInfo.InvariantCulture).Length)
                return -1;
            long value = 0;
            for (int i = start; i < text.Length; i++)
                value = value * 10 + (text[i] - '0');
            return value <= limit ? (int)value : -1;
        }

        private static bool IsPrintableName(string name, string forbidden)
        {
            foreach (char c in name)
            {
                if (c < '!' || c > '~' || forbidden.IndexOf(c) >= 0)
                    return false;
            }
            return true;
        }

        /// <summary>A section line's name and argument, or false for any other line.</summary>
        private static bool TrySection(string trimmed, out string name, out string argument)
        {
            name = argument = "";
            if (trimmed.Length == 0 || trimmed[0] != '@')
                return false;
            int end = 1;
            while (end < trimmed.Length && trimmed[end] >= 'A' && trimmed[end] <= 'Z')
                end++;
            if (end == 1 || (end < trimmed.Length && !RuleString.IsSpace(trimmed[end])))
                return false;
            name = trimmed.Substring(1, end - 1);
            argument = Trim(trimmed.Substring(end));
            return true;
        }

        private static string Uncomment(string line)
        {
            int hash = line.IndexOf('#');
            return Trim(hash < 0 ? line : line.Substring(0, hash));
        }

        private sealed class Section
        {
            internal Section(string name, string argument, int line)
            {
                Name = name;
                Argument = argument;
                Line = line;
            }

            internal string Name { get; }
            internal string Argument { get; }
            internal int Line { get; }
            internal List<(int Line, string Text)> Lines { get; } = new List<(int, string)>();
        }

        private static List<Section> SplitSections(string text)
        {
            if (text.Length > 0 && text[0] == '﻿')
                text = text.Substring(1);
            string[] lines = text.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');
            int first = -1;
            for (int k = 0; k < lines.Length; k++)
            {
                if (Trim(lines[k]).Length > 0)
                {
                    first = k;
                    break;
                }
            }
            const string startReason = "a rule file starts with '@RULE' and the rule's name";
            if (first < 0)
                throw new RuleFileException(startReason, null);
            if (!TrySection(Trim(lines[first]), out string head, out _) || head != "RULE")
                throw new RuleFileException(startReason, first + 1);
            var sections = new List<Section>();
            for (int k = first; k < lines.Length; k++)
            {
                if (TrySection(Trim(lines[k]), out string name, out string argument))
                    sections.Add(new Section(name, argument, k + 1));
                else
                    sections[sections.Count - 1].Lines.Add((k + 1, lines[k]));
            }
            return sections;
        }

        // -- @RULE ----------------------------------------------------------------------------

        private static string RuleName(Section section)
        {
            string name = section.Argument;
            if (name.Length == 0)
                throw new RuleFileException("'@RULE' has no name", section.Line);
            foreach (char c in name)
            {
                if (RuleString.IsSpace(c))
                    throw new RuleFileException("a rule's name has no spaces", section.Line);
            }
            if (!IsPrintableName(name, ",:"))
                throw new RuleFileException("a rule's name is printable ASCII without ',' or ':'", section.Line);
            return name;
        }

        private static string Description(Section section)
        {
            int start = 0, end = section.Lines.Count;
            while (start < end && Trim(section.Lines[start].Text).Length == 0)
                start++;
            while (end > start && Trim(section.Lines[end - 1].Text).Length == 0)
                end--;
            var text = new StringBuilder();
            for (int i = start; i < end; i++)
            {
                if (i > start)
                    text.Append('\n');
                text.Append(section.Lines[i].Text);
            }
            return text.ToString();
        }

        // -- @TABLE ---------------------------------------------------------------------------

        // A transition's field: a state (Var null) or a variable's name.
        private readonly struct Field
        {
            internal Field(int state)
            {
                State = state;
                Var = null;
            }

            internal Field(string var)
            {
                State = -1;
                Var = var;
            }

            internal int State { get; }
            internal string? Var { get; }
        }

        private sealed class Transition
        {
            internal Transition(Field[] inputs, Field output)
            {
                Inputs = inputs;
                Output = output;
            }

            internal Field[] Inputs { get; } // C, then the ring in the neighborhood's order
            internal Field Output { get; }
        }

        private sealed class Table
        {
            internal int States;
            internal string Neighborhood = "";
            internal string Symmetries = "";
            internal readonly Dictionary<string, int[]> Variables = new Dictionary<string, int[]>(StringComparer.Ordinal);
            internal readonly List<Transition> Transitions = new List<Transition>();
        }

        private static Table ParseTable(Section section)
        {
            var table = new Table();
            var settings = new Dictionary<string, (string Value, int Line)>(StringComparer.Ordinal);
            bool settled = false;

            void Settle(int? line)
            {
                foreach (string key in new[] { "n_states", "neighborhood", "symmetries" })
                {
                    if (!settings.ContainsKey(key))
                        throw new RuleFileException($"'{key}' is missing", line);
                }
                (string value, int valueLine) = settings["symmetries"];
                (string, string)[] allowed = SymmetriesOf(table.Neighborhood);
                foreach ((string spelling, string canonical) in allowed)
                {
                    if (Lower(value) == Lower(spelling))
                    {
                        table.Symmetries = canonical;
                        return;
                    }
                }
                var listed = new StringBuilder();
                for (int i = 0; i < allowed.Length; i++)
                {
                    if (i > 0)
                        listed.Append(", ");
                    listed.Append(allowed[i].Item1);
                }
                throw new RuleFileException(
                    $"the {table.Neighborhood} neighborhood has no '{value}' symmetries: expected {listed}", valueLine);
            }

            foreach ((int lineNo, string raw) in section.Lines)
            {
                string text = Uncomment(raw);
                if (text.Length == 0)
                    continue;
                List<string> words = Words(text);
                if (words[0] == "var")
                {
                    if (!settled)
                    {
                        Settle(lineNo);
                        settled = true;
                    }
                    ParseVariable(text, lineNo, table);
                }
                else if (text.IndexOf(':') >= 0)
                {
                    int colon = text.IndexOf(':');
                    string keyText = Trim(text.Substring(0, colon)), value = Trim(text.Substring(colon + 1));
                    string key = Lower(keyText);
                    if (key != "n_states" && key != "neighborhood" && key != "symmetries")
                        throw new RuleFileException($"unknown setting '{keyText}'", lineNo);
                    if (settled)
                        throw new RuleFileException($"'{key}' comes before the variables and transitions", lineNo);
                    if (settings.ContainsKey(key))
                        throw new RuleFileException($"'{key}' is set twice", lineNo);
                    if (key == "n_states")
                    {
                        int number = Number(value, RuleTable.MaxStates);
                        if (number < 2)
                            throw new RuleFileException("n_states is a whole number from 2 to 256", lineNo);
                        table.States = number;
                    }
                    else if (key == "neighborhood")
                    {
                        string? found = null;
                        foreach (string name in NeighborhoodNames)
                        {
                            if (Lower(name) == Lower(value))
                                found = name;
                        }
                        table.Neighborhood = found ?? throw new RuleFileException(
                            $"unknown neighborhood '{value}': expected vonNeumann, Moore, hexagonal or oneDimensional",
                            lineNo);
                    }
                    settings[key] = (value, lineNo);
                }
                else
                {
                    if (!settled)
                    {
                        Settle(lineNo);
                        settled = true;
                    }
                    table.Transitions.Add(ParseTransition(text, lineNo, table));
                }
            }
            if (!settled)
                Settle(null);
            return table;
        }

        private static Field StateOrVariable(string text, int line, Table table)
        {
            if (IsDigits(text))
            {
                int value = Number(text, table.States - 1);
                if (value < 0)
                    throw new RuleFileException($"state {text} is not below n_states {table.States}", line);
                return new Field(value);
            }
            if (!table.Variables.ContainsKey(text))
                throw new RuleFileException($"unknown variable '{text}'", line);
            return new Field(text);
        }

        private static void ParseVariable(string text, int line, Table table)
        {
            var syntax = new RuleFileException("expected 'var name = {states}'", line);
            string rest = Trim(text.Substring(3));
            int end = 0;
            while (end < rest.Length && !RuleString.IsSpace(rest[end]) && rest[end] != '=')
                end++;
            string name = rest.Substring(0, end);
            rest = Trim(rest.Substring(end));
            if (name.Length == 0 || rest.Length == 0 || rest[0] != '=')
                throw syntax;
            rest = Trim(rest.Substring(1));
            if (rest.Length < 2 || rest[0] != '{' || rest[rest.Length - 1] != '}')
                throw syntax;
            string inner = rest.Substring(1, rest.Length - 2);
            if (inner.IndexOf('{') >= 0 || inner.IndexOf('}') >= 0)
                throw syntax;
            if (IsDigits(name))
                throw new RuleFileException("a variable's name can't be a number", line);
            if (!IsPrintableName(name, ",{}=:"))
                throw new RuleFileException("a variable's name is printable ASCII without ',', '{', '}', '=' or ':'", line);
            if (table.Variables.ContainsKey(name))
                throw new RuleFileException($"variable '{name}' is defined twice", line);
            if (Trim(inner).Length == 0)
                throw new RuleFileException($"variable '{name}' has no states", line);
            var members = new SortedSet<int>();
            foreach (string part in inner.Split(','))
            {
                string member = Trim(part);
                if (member.Length == 0)
                    throw syntax;
                Field field = StateOrVariable(member, line, table);
                if (field.Var == null)
                    members.Add(field.State);
                else
                    members.UnionWith(table.Variables[field.Var]);
            }
            var states = new int[members.Count];
            members.CopyTo(states);
            table.Variables[name] = states;
        }

        private static Transition ParseTransition(string text, int line, Table table)
        {
            var fields = new List<string>();
            foreach (string part in text.Split(','))
            {
                string piece = Trim(part);
                if (piece.Length == 0)
                    throw new RuleFileException("a transition has an empty field", line);
                fields.AddRange(Words(piece));
            }
            int count = Ring(table.Neighborhood).Length + 2;
            if (fields.Count != count)
            {
                if (fields.Count == 1 && table.States <= 10 && IsDigits(fields[0]) && fields[0].Length == count)
                {
                    string digits = fields[0];
                    fields.Clear();
                    foreach (char c in digits)
                        fields.Add(c.ToString());
                }
                else
                {
                    throw new RuleFileException(
                        $"a {table.Neighborhood} transition has {count} fields, not {fields.Count}", line);
                }
            }
            var parsed = new Field[count];
            for (int i = 0; i < count; i++)
                parsed[i] = StateOrVariable(fields[i], line, table);
            var inputs = new Field[count - 1];
            Array.Copy(parsed, inputs, count - 1);
            Field output = parsed[count - 1];
            if (output.Var != null && table.Variables[output.Var].Length != 1)
            {
                bool bound = false;
                foreach (Field input in inputs)
                {
                    if (input.Var == output.Var)
                        bound = true;
                }
                if (!bound)
                    throw new RuleFileException(
                        $"the output '{output.Var}' has several states and no input binds it", line);
            }
            return new Transition(inputs, output);
        }

        // -- symmetries -----------------------------------------------------------------------

        private static readonly Dictionary<string, int[][]> VariantCache = new Dictionary<string, int[][]>();

        /// <summary>
        /// The variants of a transition under <paramref name="symmetries"/>, in the order they are
        /// tried (spec/rule-files.md "Symmetries"): each an order p saying that the variant's ring
        /// position i takes the transition's neighbor at position p[i].
        /// </summary>
        internal static int[][] VariantOrders(string neighborhood, string symmetries)
        {
            string key = neighborhood + "/" + symmetries;
            lock (VariantCache)
            {
                if (VariantCache.TryGetValue(key, out int[][]? cached))
                    return cached;
            }
            int k = Ring(neighborhood).Length;
            var orders = new List<int[]>();
            if (symmetries == "permute")
            {
                var order = new int[k];
                for (int i = 0; i < k; i++)
                    order[i] = i;
                do
                {
                    orders.Add((int[])order.Clone());
                }
                while (NextPermutation(order));
            }
            else
            {
                int[] steps = symmetries switch
                {
                    "rotate2" => new[] { 0, 3 },
                    "rotate3" => new[] { 0, 2, 4 },
                    "rotate4" or "rotate4reflect" => k == 4 ? new[] { 0, 1, 2, 3 } : new[] { 0, 2, 4, 6 },
                    "rotate6" or "rotate6reflect" => new[] { 0, 1, 2, 3, 4, 5 },
                    "rotate8" or "rotate8reflect" => new[] { 0, 1, 2, 3, 4, 5, 6, 7 },
                    _ => new[] { 0 },
                };
                foreach (int r in steps)
                {
                    var rotation = new int[k];
                    for (int i = 0; i < k; i++)
                        rotation[i] = (i + r) % k;
                    orders.Add(rotation);
                }
                bool reflecting = symmetries == "rotate4reflect" || symmetries == "rotate6reflect"
                    || symmetries == "rotate8reflect" || symmetries == "reflect_horizontal" || symmetries == "reflect";
                if (reflecting)
                {
                    int rotations = orders.Count;
                    for (int j = 0; j < rotations; j++)
                    {
                        int[] rotation = orders[j];
                        var reflected = new int[k];
                        if (neighborhood == "oneDimensional")
                        {
                            reflected[0] = rotation[1];
                            reflected[1] = rotation[0];
                        }
                        else
                        {
                            for (int i = 0; i < k; i++)
                                reflected[i] = rotation[(k - i) % k];
                        }
                        orders.Add(reflected);
                    }
                }
            }
            int[][] result = orders.ToArray();
            lock (VariantCache)
                VariantCache[key] = result;
            return result;
        }

        /// <summary>The next permutation in lexicographic order, in place; false after the last.</summary>
        private static bool NextPermutation(int[] order)
        {
            int i = order.Length - 2;
            while (i >= 0 && order[i] >= order[i + 1])
                i--;
            if (i < 0)
                return false;
            int j = order.Length - 1;
            while (order[j] <= order[i])
                j--;
            (order[i], order[j]) = (order[j], order[i]);
            Array.Reverse(order, i + 1, order.Length - i - 1);
            return true;
        }

        // -- compiling a table ----------------------------------------------------------------

        // A pattern's field at one tree level: Kind -1 any state, 0 a state (Value), 1 an unbound
        // set (Mask), 2 a bound variable (Value = its slot, Mask its states).
        private readonly struct Spec : IEquatable<Spec>
        {
            internal Spec(int kind, int value, ulong[] mask)
            {
                Kind = kind;
                Value = value;
                Mask = mask;
            }

            internal int Kind { get; }
            internal int Value { get; }
            internal ulong[] Mask { get; }

            internal bool Holds(int state) => (Mask[state >> 6] >> (state & 63) & 1) != 0;

            public bool Equals(Spec other)
            {
                if (Kind != other.Kind || Value != other.Value)
                    return false;
                if (Kind == 0 || Kind == -1)
                    return true;
                for (int i = 0; i < Mask.Length; i++)
                {
                    if (Mask[i] != other.Mask[i])
                        return false;
                }
                return true;
            }

            public override bool Equals(object? obj) => obj is Spec other && Equals(other);

            public override int GetHashCode()
            {
                int hash = Kind * 31 + Value;
                if (Kind == 1 || Kind == 2)
                {
                    foreach (ulong word in Mask)
                        hash = hash * 31 + word.GetHashCode();
                }
                return hash;
            }
        }

        private sealed class Pattern
        {
            internal Pattern(Spec[] specs, int outputKind, int output, int slots)
            {
                Specs = specs;
                OutputKind = outputKind;
                Output = output;
                Slots = slots;
            }

            internal Spec[] Specs { get; } // one per tree level, root first
            internal int OutputKind { get; } // 0 a state, 2 a slot
            internal int Output { get; }
            internal int Slots { get; }
        }

        private static readonly ulong[] NoMask = Array.Empty<ulong>();

        private static List<Pattern> Patterns(Table table, int[] order)
        {
            int[][] orders = VariantOrders(table.Neighborhood, table.Symmetries);
            int[] ring = Ring(table.Neighborhood);
            var patterns = new List<Pattern>();
            foreach (Transition transition in table.Transitions)
            {
                var uses = new Dictionary<string, int>(StringComparer.Ordinal);
                foreach (Field field in transition.Inputs)
                {
                    if (field.Var != null)
                        uses[field.Var] = uses.TryGetValue(field.Var, out int u) ? u + 1 : 1;
                }
                var slots = new Dictionary<string, int>(StringComparer.Ordinal);

                Spec SpecOf(Field field)
                {
                    if (field.Var == null)
                        return new Spec(0, field.State, NoMask);
                    var mask = new ulong[(table.States + 63) / 64];
                    foreach (int v in table.Variables[field.Var])
                        mask[v >> 6] |= 1UL << (v & 63);
                    if (uses[field.Var] > 1 || field.Var == transition.Output.Var)
                    {
                        if (!slots.TryGetValue(field.Var, out int slot))
                        {
                            slot = slots.Count;
                            slots[field.Var] = slot;
                        }
                        return new Spec(2, slot, mask);
                    }
                    return new Spec(1, 0, mask);
                }

                Spec center = SpecOf(transition.Inputs[0]);
                var neighbors = new Spec[ring.Length];
                for (int i = 0; i < ring.Length; i++)
                    neighbors[i] = SpecOf(transition.Inputs[i + 1]);
                int outputKind, output;
                Field result = transition.Output;
                if (result.Var == null)
                {
                    outputKind = 0;
                    output = result.State;
                }
                else if (slots.TryGetValue(result.Var, out int slot))
                {
                    outputKind = 2;
                    output = slot;
                }
                else
                {
                    outputKind = 0;
                    output = table.Variables[result.Var][0]; // a variable of one state
                }
                var seen = new HashSet<string>(StringComparer.Ordinal);
                foreach (int[] permutation in orders)
                {
                    var variant = new Spec[ring.Length];
                    for (int i = 0; i < ring.Length; i++)
                        variant[i] = neighbors[permutation[i]];
                    if (!seen.Add(VariantKey(variant)))
                        continue;
                    var cells = new Spec[9];
                    for (int i = 0; i < 9; i++)
                        cells[i] = new Spec(-1, 0, NoMask);
                    for (int i = 0; i < ring.Length; i++)
                        cells[ring[i]] = variant[i];
                    cells[C] = center;
                    var specs = new Spec[order.Length];
                    for (int level = 0; level < order.Length; level++)
                        specs[level] = cells[order[level]];
                    patterns.Add(new Pattern(specs, outputKind, output, slots.Count));
                }
            }
            return patterns;
        }

        private static string VariantKey(Spec[] variant)
        {
            var key = new StringBuilder();
            foreach (Spec spec in variant)
            {
                key.Append(spec.Kind).Append(':').Append(spec.Value);
                if (spec.Kind == 1 || spec.Kind == 2)
                {
                    foreach (ulong word in spec.Mask)
                        key.Append(':').Append(word);
                }
                key.Append(';');
            }
            return key.ToString();
        }

        /// <summary>Nodes made once each: a level and its children (states at level 1, node
        /// indices above), numbered as they are made.</summary>
        private sealed class TreeBuilder
        {
            internal readonly List<(int Level, int[] Children)> Nodes = new List<(int, int[])>();
            private readonly Dictionary<int[], int> _index = new Dictionary<int[], int>(IntArrayComparer.Instance);

            internal int Node(int level, int[] children)
            {
                var key = new int[children.Length + 1];
                key[0] = level;
                Array.Copy(children, 0, key, 1, children.Length);
                if (!_index.TryGetValue(key, out int found))
                {
                    found = Nodes.Count;
                    _index[key] = found;
                    Nodes.Add((level, children));
                }
                return found;
            }
        }

        private sealed class IntArrayComparer : IEqualityComparer<int[]>
        {
            internal static readonly IntArrayComparer Instance = new IntArrayComparer();

            public bool Equals(int[]? x, int[]? y)
            {
                if (x == null || y == null || x.Length != y.Length)
                    return x == y;
                for (int i = 0; i < x.Length; i++)
                {
                    if (x[i] != y[i])
                        return false;
                }
                return true;
            }

            public int GetHashCode(int[] obj)
            {
                unchecked
                {
                    int hash = 17;
                    foreach (int v in obj)
                        hash = hash * 31 + v;
                    return hash;
                }
            }
        }

        private static (int Neighbors, List<(int Level, int[] Children)> Nodes, int Root) Compile(Table table)
        {
            int neighbors = TreeNeighbors(table.Neighborhood);
            int[] order = neighbors == 8 ? TreeOrder8 : TreeOrder4;
            List<Pattern> patterns = Patterns(table, order);
            int states = table.States, levels = order.Length;
            var builder = new TreeBuilder();
            var memo = new Dictionary<int[], int>(IntArrayComparer.Instance);

            // An active pattern: its index and its slots' states (−1 unbound), flattened.
            int[] Advance(int[] active, int depth, int value)
            {
                var kept = new List<int>();
                int i = 0;
                while (i < active.Length)
                {
                    int index = active[i];
                    Pattern pattern = patterns[index];
                    int width = 1 + pattern.Slots;
                    Spec spec = pattern.Specs[depth];
                    bool keep;
                    int bindSlot = -1;
                    switch (spec.Kind)
                    {
                        case -1:
                            keep = true;
                            break;
                        case 0:
                            keep = value == spec.Value;
                            break;
                        case 1:
                            keep = spec.Holds(value);
                            break;
                        default:
                            int bound = active[i + 1 + spec.Value];
                            if (bound >= 0)
                            {
                                keep = bound == value;
                            }
                            else
                            {
                                keep = spec.Holds(value);
                                bindSlot = spec.Value;
                            }
                            break;
                    }
                    if (keep)
                    {
                        for (int j = 0; j < width; j++)
                            kept.Add(bindSlot >= 0 && j == 1 + bindSlot ? value : active[i + j]);
                    }
                    i += width;
                }
                return kept.ToArray();
            }

            int Build(int[] active, int depth)
            {
                var key = new int[active.Length + 1];
                key[0] = depth;
                Array.Copy(active, 0, key, 1, active.Length);
                if (memo.TryGetValue(key, out int found))
                    return found;
                int level = levels - depth;
                var children = new int[states];
                for (int value = 0; value < states; value++)
                {
                    int[] matched = Advance(active, depth, value);
                    if (depth == levels - 1)
                    {
                        if (matched.Length > 0)
                        {
                            Pattern pattern = patterns[matched[0]];
                            children[value] = pattern.OutputKind == 0 ? pattern.Output : matched[1 + pattern.Output];
                        }
                        else
                        {
                            children[value] = value; // nothing matches: the center keeps its state
                        }
                    }
                    else
                    {
                        children[value] = Build(matched, depth + 1);
                    }
                }
                int node = builder.Node(level, children);
                memo[key] = node;
                return node;
            }

            var start = new List<int>();
            for (int index = 0; index < patterns.Count; index++)
            {
                start.Add(index);
                for (int slot = 0; slot < patterns[index].Slots; slot++)
                    start.Add(-1);
            }
            int root = Build(start.ToArray(), 0);
            return (neighbors, builder.Nodes, root);
        }

        /// <summary>A tree in its canonical form: alike nodes merged, unreachable ones gone,
        /// numbered in post-order from the root.</summary>
        internal static List<(int Level, int[] Children)> CanonicalTree(List<(int Level, int[] Children)> nodes, int root)
        {
            var builder = new TreeBuilder();
            var renamed = new Dictionary<int, int>();

            int Visit(int index)
            {
                if (renamed.TryGetValue(index, out int done))
                    return done;
                (int level, int[] children) = nodes[index];
                int[] next;
                if (level == 1)
                {
                    next = (int[])children.Clone();
                }
                else
                {
                    next = new int[children.Length];
                    for (int v = 0; v < children.Length; v++)
                        next[v] = Visit(children[v]);
                }
                int made = builder.Node(level, next);
                renamed[index] = made;
                return made;
            }

            Visit(root);
            return builder.Nodes;
        }

        // -- @TREE ----------------------------------------------------------------------------

        private static (int States, int Neighbors, List<(int Level, int[] Children)> Nodes) ParseTree(Section section)
        {
            var settings = new Dictionary<string, int>(StringComparer.Ordinal);
            var nodes = new List<(int Level, int[] Children)>();
            string[] keys = { "num_states", "num_neighbors", "num_nodes" };
            bool settled = false;

            void Settle(int? line)
            {
                foreach (string key in keys)
                {
                    if (!settings.ContainsKey(key))
                        throw new RuleFileException($"'{key}' is missing", line);
                }
            }

            foreach ((int lineNo, string raw) in section.Lines)
            {
                string text = Uncomment(raw);
                if (text.Length == 0)
                    continue;
                int equals = text.IndexOf('=');
                if (equals >= 0)
                {
                    string key = Lower(Trim(text.Substring(0, equals)));
                    string value = Trim(text.Substring(equals + 1));
                    if (Array.IndexOf(keys, key) < 0)
                        throw new RuleFileException("expected 'num_states', 'num_neighbors' or 'num_nodes' and '='", lineNo);
                    if (settings.ContainsKey(key))
                        throw new RuleFileException($"'{key}' is set twice", lineNo);
                    int number;
                    if (key == "num_states")
                    {
                        number = Number(value, RuleTable.MaxStates);
                        if (number < 2)
                            throw new RuleFileException("num_states is a whole number from 2 to 256", lineNo);
                    }
                    else if (key == "num_neighbors")
                    {
                        number = Number(value, 8);
                        if (number != 4 && number != 8)
                            throw new RuleFileException("num_neighbors is 4 or 8", lineNo);
                    }
                    else
                    {
                        number = Number(value, 1 << 30);
                        if (number < 1)
                            throw new RuleFileException("num_nodes is a positive whole number", lineNo);
                    }
                    settings[key] = number;
                    continue;
                }
                if (!settled)
                {
                    Settle(lineNo);
                    settled = true;
                }
                int states = settings["num_states"], top = settings["num_neighbors"] + 1;
                if (nodes.Count == settings["num_nodes"])
                    throw new RuleFileException("the tree has more than num_nodes nodes", lineNo);
                List<string> words = Words(text);
                bool numbers = words.Count == states + 1;
                foreach (string word in words)
                {
                    if (!IsDigits(word))
                        numbers = false;
                }
                if (!numbers)
                    throw new RuleFileException($"a node is its level and {states} children, all whole numbers", lineNo);
                int level = Number(words[0], top);
                if (level < 1)
                    throw new RuleFileException($"a node's level is 1 to {top}", lineNo);
                var children = new int[states];
                for (int v = 0; v < states; v++)
                {
                    string word = words[v + 1];
                    if (level == 1)
                    {
                        int child = Number(word, states - 1);
                        if (child < 0)
                            throw new RuleFileException($"a level-1 node's children are states below {states}", lineNo);
                        children[v] = child;
                    }
                    else
                    {
                        int child = nodes.Count > 0 ? Number(word, nodes.Count - 1) : -1;
                        if (child < 0 || nodes[child].Level != level - 1)
                            throw new RuleFileException(
                                $"a level-{level} node's children are earlier nodes of level {level - 1}", lineNo);
                        children[v] = child;
                    }
                }
                nodes.Add((level, children));
            }
            if (!settled)
                Settle(null);
            if (nodes.Count != settings["num_nodes"])
                throw new RuleFileException($"the tree has {nodes.Count} nodes, not num_nodes {settings["num_nodes"]}", null);
            int root = settings["num_neighbors"] + 1;
            if (nodes[nodes.Count - 1].Level != root)
                throw new RuleFileException($"the root, the last node, is at level {root}", null);
            return (settings["num_states"], settings["num_neighbors"], nodes);
        }

        // -- @COLORS, @NAMES, @ICONS ----------------------------------------------------------

        private static List<RuleColor> ParseColors(Section section)
        {
            var entries = new List<RuleColor>();
            foreach ((int lineNo, string raw) in section.Lines)
            {
                string text = Trim(raw);
                if (text.Length == 0 || text[0] == '#')
                    continue;
                var numbers = new List<string>();
                foreach (string word in Words(text))
                {
                    if (!IsDigits(word))
                        break;
                    numbers.Add(word);
                }
                if (numbers.Count < 4)
                    throw new RuleFileException("a '@COLORS' line is 'state r g b' or 'r1 g1 b1 r2 g2 b2'", lineNo);
                bool gradient = numbers.Count >= 6;
                int first = gradient ? 0 : 1, count = gradient ? 6 : 3;
                var rgb = new byte[count];
                for (int i = 0; i < count; i++)
                {
                    int value = Number(numbers[first + i], 255);
                    if (value < 0)
                        throw new RuleFileException("a color component is 0 to 255", lineNo);
                    rgb[i] = (byte)value;
                }
                if (gradient)
                {
                    entries.Add(new RuleColor(-1, (rgb[0], rgb[1], rgb[2]), (rgb[3], rgb[4], rgb[5])));
                }
                else
                {
                    int state = Number(numbers[0], RuleTable.MaxStates - 1);
                    entries.Add(new RuleColor(state < 0 ? RuleTable.MaxStates : state, (rgb[0], rgb[1], rgb[2]), null));
                }
            }
            return entries;
        }

        private static List<RuleStateName> ParseNames(Section section)
        {
            var entries = new List<RuleStateName>();
            foreach ((int lineNo, string raw) in section.Lines)
            {
                string text = Trim(raw);
                if (text.Length == 0 || text[0] == '#')
                    continue;
                int end = 0;
                while (end < text.Length && text[end] >= '0' && text[end] <= '9')
                    end++;
                string name = Trim(text.Substring(end));
                if (end == 0 || end == text.Length || !RuleString.IsSpace(text[end]) || name.Length == 0)
                    throw new RuleFileException("a '@NAMES' line is a state and its name", lineNo);
                int state = Number(text.Substring(0, end), RuleTable.MaxStates - 1);
                entries.Add(new RuleStateName(state < 0 ? RuleTable.MaxStates : state, name));
            }
            return entries;
        }

        private static string Quoted(string text, int line)
        {
            int close = text.IndexOf('"', 1);
            if (close < 0)
                throw new RuleFileException("a quoted string has no closing '\"'", line);
            return text.Substring(1, close - 1);
        }

        private static RuleIcons ParseIcons(Section section)
        {
            const string both = "'@ICONS' holds one style or XPM sets, not both";
            const string lineReason =
                "an '@ICONS' line is 'XPM', a quoted string, or circles, diamonds, hexagons or triangles";
            string? style = null;
            var sets = new List<RuleIconSet>();
            int currentLine = -1;
            List<(int Line, string Text)>? current = null;

            void Finish()
            {
                if (current != null)
                {
                    RuleIconSet? kept = XpmSet(currentLine, current);
                    if (kept != null)
                        sets.Add(kept);
                }
                current = null;
            }

            foreach ((int lineNo, string raw) in section.Lines)
            {
                string text = Trim(raw);
                if (text.Length == 0 || text[0] == '#' || text[0] == '/')
                    continue;
                if (text[0] == '"')
                {
                    if (current == null)
                        throw new RuleFileException(lineReason, lineNo);
                    current.Add((lineNo, Quoted(text, lineNo)));
                }
                else if (text == "XPM")
                {
                    if (style != null)
                        throw new RuleFileException(both, lineNo);
                    Finish();
                    currentLine = lineNo;
                    current = new List<(int, string)>();
                }
                else if (Array.IndexOf(IconStyles, Lower(text)) >= 0)
                {
                    if (style != null || sets.Count > 0 || current != null)
                        throw new RuleFileException(both, lineNo);
                    style = Lower(text);
                }
                else
                {
                    throw new RuleFileException(lineReason, lineNo);
                }
            }
            Finish();
            return new RuleIcons(style, sets);
        }

        private static bool IsHex(char c) => (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');

        private static RuleIconSet? XpmSet(int line, List<(int Line, string Text)> strings)
        {
            const string headerReason = "an XPM set's first string is its width, height, colors and characters per pixel";
            if (strings.Count == 0)
                throw new RuleFileException(headerReason, line);
            (int headerLine, string header) = strings[0];
            List<string> words = Words(header);
            var numbers = new int[4];
            bool good = words.Count == 4;
            for (int i = 0; good && i < 4; i++)
            {
                numbers[i] = Number(words[i], 1 << 20);
                good = numbers[i] >= 0;
            }
            if (!good)
                throw new RuleFileException(headerReason, headerLine);
            int width = numbers[0], height = numbers[1], colors = numbers[2], perPixel = numbers[3];
            if (width < 1 || height < width || height % width != 0 || colors < 1 || (perPixel != 1 && perPixel != 2))
                throw new RuleFileException(headerReason, headerLine);
            int needed = 1 + colors + height;
            var palette = new List<(string Key, string? Color)>();
            var keys = new HashSet<string>(StringComparer.Ordinal);
            const string colorReason = "an XPM color is a key, 'c' and #RRGGBB or None";
            for (int i = 1; i < Math.Min(1 + colors, strings.Count); i++)
            {
                (int stringLine, string text) = strings[i];
                string key = text.Length >= perPixel ? text.Substring(0, perPixel) : text;
                string rest = text.Length >= perPixel ? text.Substring(perPixel) : "";
                List<string> parts = Words(rest);
                if (key.Length != perPixel || keys.Contains(key) || rest.Length == 0 || !RuleString.IsSpace(rest[0])
                    || parts.Count != 2 || parts[0] != "c")
                    throw new RuleFileException(colorReason, stringLine);
                string color = parts[1];
                string? value;
                if (Lower(color) == "none")
                {
                    value = null;
                }
                else if (color.Length == 7 && color[0] == '#' && IsHex(color[1]) && IsHex(color[2]) && IsHex(color[3])
                    && IsHex(color[4]) && IsHex(color[5]) && IsHex(color[6]))
                {
                    value = color.ToUpperInvariant();
                }
                else
                {
                    throw new RuleFileException(colorReason, stringLine);
                }
                keys.Add(key);
                palette.Add((key, value));
            }
            var rows = new List<string>();
            for (int i = 1 + colors; i < Math.Min(needed, strings.Count); i++)
            {
                (int stringLine, string text) = strings[i];
                bool row = text.Length == width * perPixel;
                for (int p = 0; row && p < text.Length; p += perPixel)
                    row = keys.Contains(text.Substring(p, perPixel));
                if (!row)
                    throw new RuleFileException(
                        $"an XPM row is {width * perPixel} characters, a color's key for each of its {width} pixels",
                        stringLine);
                rows.Add(text);
            }
            if (strings.Count < needed)
                throw new RuleFileException($"the XPM set has {strings.Count} strings, not {needed}", line);
            if (width != 7 && width != 15 && width != 31)
                return null;
            return new RuleIconSet(width, palette, rows);
        }

        // -- the rule -------------------------------------------------------------------------

        internal static RuleTable Parse(string text)
        {
            List<Section> sections = SplitSections(text);
            string name = "", description = "";
            RuleSource? source = null;
            Table? table = null;
            (int States, int Neighbors, List<(int Level, int[] Children)> Nodes)? tree = null;
            List<RuleColor>? colors = null;
            List<RuleStateName>? names = null;
            RuleIcons? icons = null;
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (Section section in sections)
            {
                string kind = section.Name;
                string slot = kind == "TABLE" || kind == "TREE" ? "FUNCTION" : kind;
                bool known = kind == "RULE" || kind == "TABLE" || kind == "TREE" || kind == "COLORS" || kind == "NAMES"
                    || kind == "ICONS";
                if (!known || !seen.Add(slot))
                    continue;
                switch (kind)
                {
                    case "RULE":
                        name = RuleName(section);
                        description = Description(section);
                        break;
                    case "TABLE":
                        source = RuleSource.Table;
                        table = ParseTable(section);
                        break;
                    case "TREE":
                        source = RuleSource.Tree;
                        tree = ParseTree(section);
                        break;
                    case "COLORS":
                        colors = ParseColors(section);
                        break;
                    case "NAMES":
                        names = ParseNames(section);
                        break;
                    default:
                        icons = ParseIcons(section);
                        break;
                }
            }
            int states, neighbors;
            List<(int Level, int[] Children)> nodes;
            string? neighborhood = null, symmetries = null;
            if (table != null)
            {
                (int n, List<(int, int[])> built, int root) = Compile(table);
                neighbors = n;
                nodes = CanonicalTree(built, root);
                states = table.States;
                neighborhood = table.Neighborhood;
                symmetries = table.Symmetries;
            }
            else if (tree != null)
            {
                var read = tree.Value;
                states = read.States;
                neighbors = read.Neighbors;
                nodes = CanonicalTree(read.Nodes, read.Nodes.Count - 1);
            }
            else
            {
                throw new RuleFileException("no '@TABLE' or '@TREE' section", null);
            }
            var keptColors = new List<RuleColor>();
            foreach (RuleColor color in colors ?? new List<RuleColor>())
            {
                if (color.IsGradient || color.State < states)
                    keptColors.Add(color);
            }
            var keptNames = new List<RuleStateName>();
            foreach (RuleStateName entry in names ?? new List<RuleStateName>())
            {
                if (entry.State < states)
                    keptNames.Add(entry);
            }
            return RuleTable.Make(
                name, states, neighbors, nodes, neighborhood, symmetries, source!.Value, description, keptColors,
                keptNames, icons, text);
        }
    }
}
