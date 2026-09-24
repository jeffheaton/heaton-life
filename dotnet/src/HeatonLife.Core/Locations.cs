using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// A location as a file gave it (spec/locations.md "The location record"): a center,
    /// and the portable scale every other deep-zoom program frames by — the half-height,
    /// center to top edge in plane units.
    /// </summary>
    public sealed class Location
    {
        internal Location(
            string centerRe, string centerIm, double? halfHeightLog10, string format,
            long? maxIter, string? referenceRe, string? referenceIm, IReadOnlyList<string> warnings)
        {
            CenterRe = centerRe;
            CenterIm = centerIm;
            HalfHeightLog10 = halfHeightLog10;
            Format = format;
            MaxIter = maxIter;
            ReferenceRe = referenceRe;
            ReferenceIm = referenceIm;
            Warnings = warnings;
        }

        /// <summary>The center's real part, positional (same value and places, no exponent).</summary>
        public string CenterRe { get; }

        /// <summary>The center's imaginary part, positional.</summary>
        public string CenterIm { get; }

        /// <summary>log10 of the half-height, or null when the file gives no scale.</summary>
        public double? HalfHeightLog10 { get; }

        /// <summary>kfr, f3, hf-preset, hf-result, hf-journal, or nucleus (<see cref="Nucleus.ToLocation"/>).</summary>
        public string Format { get; }

        /// <summary>The file's iteration budget, or null.</summary>
        public long? MaxIter { get; }

        /// <summary>Fraktaler-3's perturbation reference (real part), or null. Reported, not attached.</summary>
        public string? ReferenceRe { get; }

        /// <summary>Fraktaler-3's perturbation reference (imaginary part), or null.</summary>
        public string? ReferenceIm { get; }

        /// <summary>
        /// What the file asks that heaton-life does not do, as stable codes in a fixed order:
        /// rotation-ignored, stretch-ignored, reflect-ignored, exponential-map-ignored,
        /// old-style-skew, no-scale.
        /// </summary>
        public IReadOnlyList<string> Warnings { get; }

        /// <summary>
        /// The heaton-life viewport of a width × height frame whose vertical extent matches
        /// the source's: zoom = log10(fl(2H/W)) − log10 h. Not bit-exact (log10); run once,
        /// when a location enters, and keep the viewport.
        /// </summary>
        public Viewport ToViewport(int width, int height)
        {
            if (HalfHeightLog10 == null)
                throw new InvalidOperationException($"this {Format} location gives no scale");
            if (width < 1 || height < 1)
                throw new ArgumentOutOfRangeException(nameof(width), $"frame must be at least 1x1, got {width}x{height}");
            double zoom = Math.Log10(2.0 * height / width) - HalfHeightLog10.Value;
            return new Viewport(CenterRe, CenterIm, zoom);
        }
    }

    /// <summary>
    /// Location import and framing conversions (spec/locations.md): Kalles Fraktaler
    /// .kfr, Fraktaler-3 .f3.toml, and Heaton Fractal's hunt result .txt as text; Heaton
    /// Fractal's preset JSON and journal.jsonl as parsed fields, because Core reads no
    /// JSON. The Python reference's heaton_life.fractal.locations.
    /// </summary>
    public static class Locations
    {
        private static readonly string[] WarningOrder =
        {
            "rotation-ignored", "stretch-ignored", "reflect-ignored", "exponential-map-ignored", "old-style-skew", "no-scale",
        };

        /// <summary>Fraktaler-3 omits a key that holds its default; this is its iteration budget's.</summary>
        private const long F3DefaultIterations = 1024;

        private static readonly double Log10Of2 = Math.Log10(2.0);

        /// <summary>
        /// log10 of a positive decimal of any size: log10 of its first 15 significant digits
        /// (exact in a double) plus the power of ten they stand for.
        /// </summary>
        public static double DecimalLog10(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            DecimalText.Scan(text, out bool negative, out BigInteger digits, out int netExponent);
            if (negative || digits.IsZero)
                throw new ArgumentException($"must be positive: '{text}'", nameof(text));
            string spelled = digits.ToString(CultureInfo.InvariantCulture);
            string kept = spelled.Length > 15 ? spelled.Substring(0, 15) : spelled;
            return Math.Log10(long.Parse(kept, NumberStyles.None, CultureInfo.InvariantCulture))
                + (netExponent + spelled.Length - kept.Length);
        }

        /// <summary>A Kalles Fraktaler .kfr (spec/locations.md "File formats").</summary>
        public static Location ParseKfr(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            var values = new Dictionary<string, string>();
            foreach (string line in Lines(text))
            {
                string s = line.Trim(' ', '\t');
                if (s.Length == 0 || s[0] == ';' || s[0] == '#')
                    continue;
                int colon = s.IndexOf(':'), equals = s.IndexOf('=');
                int cut = colon < 0 ? equals : equals < 0 ? colon : Math.Min(colon, equals);
                if (cut <= 0)
                    continue;
                values[s.Substring(0, cut).Trim(' ', '\t').ToLowerInvariant()] = s.Substring(cut + 1).Trim(' ', '\t');
            }
            foreach (string key in new[] { "re", "im" })
                if (!values.ContainsKey(key))
                    throw new ArgumentException($"a .kfr needs {char.ToUpperInvariant(key[0])}{key.Substring(1)}");
            var warnings = new HashSet<string>();
            if (NonZero(Get(values, "rotateangle")))
                warnings.Add("rotation-ignored");
            if (NonZero(Get(values, "stretchamount")))
                warnings.Add("stretch-ignored");
            if (!NonZero(Get(values, "imagpointsup")))            // KF's default axis points down
                warnings.Add("reflect-ignored");
            if (NonZero(Get(values, "rotate")) || (values.TryGetValue("ratio", out string? ratio) && !EqualsInteger(ratio, 360)))
                warnings.Add("old-style-skew");
            string? zoom = Get(values, "zoom");
            if (zoom == null)
                warnings.Add("no-scale");
            string? iterations = Get(values, "iterations");
            return new Location(
                Positional(values["re"]),
                Positional(values["im"]),
                zoom == null ? (double?)null : Log10Of2 - DecimalLog10(zoom),
                "kfr",
                iterations == null ? (long?)null : Whole(iterations, "Iterations"),
                null,
                null,
                Ordered(warnings));
        }

        /// <summary>
        /// A Fraktaler-3 .f3.toml, in the TOML subset F3 writes. F3 leaves out every key that
        /// holds its default, so a missing one means the default: center 0, zoom 1, 1024
        /// iterations, and a reference part equal to the location's.
        /// </summary>
        public static Location ParseFraktaler3(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            var values = TomlSubset(text);
            bool isF3 = values.TryGetValue("program", out var program) && program.Kind == TomlKind.String && program.Source == "fraktaler-3";
            if (!isF3)
            {
                foreach (string key in values.Keys)
                    isF3 |= key.StartsWith("location.", StringComparison.Ordinal);
            }
            if (!isF3)
                throw new ArgumentException("not a Fraktaler-3 location: no location keys and no program line");
            var warnings = new HashSet<string>();
            if (NonZero(Scalar(values, "transform.rotate")))
                warnings.Add("rotation-ignored");
            if (NonZero(Scalar(values, "transform.stretch_amount")))
                warnings.Add("stretch-ignored");
            if (IsTrue(values, "transform.reflect"))
                warnings.Add("reflect-ignored");
            if (IsTrue(values, "transform.exponential_map"))
                warnings.Add("exponential-map-ignored");
            string real = TextOr(values, "location.real", "0");
            string imag = TextOr(values, "location.imag", "0");
            string? referenceRe = null, referenceIm = null;
            if (values.ContainsKey("reference.real") || values.ContainsKey("reference.imag"))
            {
                referenceRe = Positional(TextOr(values, "reference.real", real));
                referenceIm = Positional(TextOr(values, "reference.imag", imag));
            }
            return new Location(
                Positional(real),
                Positional(imag),
                Log10Of2 - DecimalLog10(TextOr(values, "location.zoom", "1")),
                "f3",
                values.TryGetValue("bailout.iterations", out var iterations)
                    ? Whole(iterations.Text(), "bailout.iterations")
                    : F3DefaultIterations,
                referenceRe,
                referenceIm,
                Ordered(warnings));
        }

        /// <summary>
        /// A Heaton Fractal preset from its parsed fields (settings.location.centerReal,
        /// centerImag, baseHalfHeight — required, as HF's own decoder requires it;
        /// settings.zoom.targetDepthLog10; settings.quality.maxIterationsOverride):
        /// h = h0 × 10^−d, or no scale when the file states no depth (pass null; HF itself
        /// would render at its app default).
        /// </summary>
        public static Location HeatonFractalPreset(
            string centerReal, string centerImag, string baseHalfHeight, double? targetDepthLog10, long? maxIterations)
        {
            if (baseHalfHeight == null)
                throw new ArgumentNullException(nameof(baseHalfHeight), "a Heaton Fractal preset needs baseHalfHeight");
            double h0Log10 = DecimalLog10(baseHalfHeight);
            if (targetDepthLog10 != null)
                RequireFinite(targetDepthLog10.Value, "targetDepthLog10");
            if (maxIterations != null && maxIterations < 1)
                throw new ArgumentException($"maxIterationsOverride must be a positive integer, got {maxIterations}");
            return new Location(
                Positional(centerReal),
                Positional(centerImag),
                targetDepthLog10 == null ? (double?)null : h0Log10 - targetDepthLog10.Value,
                "hf-preset",
                maxIterations,
                null,
                null,
                targetDepthLog10 == null ? new[] { "no-scale" } : Array.Empty<string>());
        }

        /// <summary>
        /// A Heaton Fractal hunt result .txt: "re = …" / "im = …" lines, and a
        /// "# … depth 1e&lt;d&gt;" comment for the scale (hunts frame with h0 = 1, so the depth
        /// is −log10 h: the nucleus fills the half-height).
        /// </summary>
        public static Location ParseHeatonFractalResult(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            var values = new Dictionary<string, string>();
            double? depth = null;
            foreach (string line in Lines(text))
            {
                string s = line.Trim(' ', '\t');
                if (s.StartsWith("#", StringComparison.Ordinal))
                {
                    int at = s.IndexOf("depth 1e", StringComparison.Ordinal);
                    if (at >= 0 && depth == null)
                        depth = DecimalText.ToDouble(Word(s.Substring(at + "depth 1e".Length)).TrimEnd(',', ';'));
                    continue;
                }
                int cut = s.IndexOf('=');
                if (cut > 0)
                    values[s.Substring(0, cut).Trim(' ', '\t').ToLowerInvariant()] = s.Substring(cut + 1).Trim(' ', '\t');
            }
            foreach (string key in new[] { "re", "im" })
                if (!values.ContainsKey(key))
                    throw new ArgumentException($"a Heaton Fractal result needs {key}");
            return Seed(values["re"], values["im"], depth, "hf-result");
        }

        /// <summary>
        /// The deepest of a hunt journal's (real, imaginary, depthLog10) seeds, the latest
        /// among equals — where the hunt got to. The host parses journal.jsonl, skipping
        /// lines that do not parse (a torn last write).
        /// </summary>
        public static Location HeatonFractalJournal(IEnumerable<(string Real, string Imaginary, double DepthLog10)> seeds)
        {
            if (seeds == null)
                throw new ArgumentNullException(nameof(seeds));
            bool any = false;
            (string Real, string Imaginary, double DepthLog10) best = default;
            foreach (var seed in seeds)
            {
                if (seed.Real == null || seed.Imaginary == null)
                    throw new ArgumentException("a journal seed needs real and imaginary parts");
                if (!any || seed.DepthLog10 >= best.DepthLog10)
                    best = seed;
                any = true;
            }
            if (!any)
                throw new ArgumentException("no seed in the journal");
            return Seed(best.Real!, best.Imaginary!, best.DepthLog10, "hf-journal");
        }

        private static Location Seed(string real, string imaginary, double? depth, string format)
        {
            if (depth != null)
                RequireFinite(depth.Value, "depth");
            return new Location(
                Positional(real),
                Positional(imaginary),
                depth == null ? (double?)null : -depth.Value,
                format,
                null,
                null,
                null,
                depth == null ? new[] { "no-scale" } : Array.Empty<string>());
        }

        // ---- helpers ---------------------------------------------------------------

        private static string[] Lines(string text)
        {
            if (text.Length > 0 && text[0] == '﻿')
                text = text.Substring(1);
            return text.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');
        }

        /// <summary>Text up to the first space or tab.</summary>
        private static string Word(string s)
        {
            int cut = s.IndexOfAny(new[] { ' ', '\t' });
            return cut < 0 ? s : s.Substring(0, cut);
        }

        private static string Positional(string text) => DecimalText.Positional(text);

        private static string? Get(Dictionary<string, string> values, string key) =>
            values.TryGetValue(key, out string? value) ? value : null;

        private static bool NonZero(string? text)
        {
            if (text == null)
                return false;
            DecimalText.Scan(text, out _, out BigInteger digits, out _);
            return !digits.IsZero;
        }

        private static bool EqualsInteger(string text, int value)
        {
            DecimalText.Scan(text, out bool negative, out BigInteger digits, out int netExponent);
            if (negative)
                return false;
            BigInteger scale = BigInteger.Pow(10, Math.Abs(netExponent));
            return netExponent >= 0 ? digits * scale == value : digits == value * scale;
        }

        private static long Whole(string text, string name)
        {
            DecimalText.Scan(text, out bool negative, out BigInteger digits, out int netExponent);
            BigInteger scale = BigInteger.Pow(10, Math.Abs(netExponent));
            BigInteger value;
            if (netExponent >= 0)
            {
                value = digits * scale;
            }
            else
            {
                value = BigInteger.DivRem(digits, scale, out BigInteger remainder);
                if (!remainder.IsZero)
                    throw new ArgumentException($"{name} must be a whole number: '{text}'");
            }
            if (negative || value < 1)
                throw new ArgumentException($"{name} must be positive: '{text}'");
            if (value > long.MaxValue)
                throw new ArgumentException($"{name} is too large: '{text}'");
            return (long)value;
        }

        private static IReadOnlyList<string> Ordered(HashSet<string> warnings)
        {
            var ordered = new List<string>();
            foreach (string code in WarningOrder)
                if (warnings.Contains(code))
                    ordered.Add(code);
            return ordered;
        }

        private static void RequireFinite(double value, string name)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
                throw new ArgumentException($"{name} must be finite, got {value}");
        }

        // ---- the TOML subset Fraktaler-3 writes ---------------------------------------

        private enum TomlKind
        {
            String,
            Number,
            Boolean,
        }

        private readonly struct TomlValue
        {
            internal TomlValue(TomlKind kind, string text, bool boolean)
            {
                Kind = kind;
                Source = text;
                Boolean = boolean;
            }

            internal TomlKind Kind { get; }

            /// <summary>A string's value, or a number's source text.</summary>
            internal string Source { get; }

            internal bool Boolean { get; }

            internal string Text() => Kind == TomlKind.Boolean
                ? throw new ArgumentException($"expected a string or a number, got {Boolean}")
                : Source;
        }

        private static bool IsTrue(Dictionary<string, TomlValue> values, string key) =>
            values.TryGetValue(key, out var value) && value.Kind == TomlKind.Boolean && value.Boolean;

        private static string TextOr(Dictionary<string, TomlValue> values, string key, string fallback) =>
            values.TryGetValue(key, out var value) ? value.Text() : fallback;

        private static string? Scalar(Dictionary<string, TomlValue> values, string key) =>
            values.TryGetValue(key, out var value) && value.Kind != TomlKind.Boolean ? value.Source : null;

        /// <summary>
        /// [section] headers, key = value with dotted keys, # comments, basic and literal
        /// strings — single-line, and the multi-line forms F3 writes for long coordinates (a
        /// triple quote, then chunks ending in a line-ending backslash) — numbers (_ separators
        /// dropped), booleans. Anything else — arrays, inline tables, dates, the keys of
        /// [[array tables]] — is skipped. Keys are case-insensitive; a later duplicate wins.
        /// </summary>
        private static Dictionary<string, TomlValue> TomlSubset(string text)
        {
            var values = new Dictionary<string, TomlValue>();
            string? section = "";
            string[] lines = Lines(text);
            int i = 0;
            while (i < lines.Length)
            {
                string s = lines[i].Trim(' ', '\t');
                i++;
                if (s.Length == 0 || s[0] == '#')
                    continue;
                if (s[0] == '[')
                {
                    if (s.StartsWith("[[", StringComparison.Ordinal))
                    {
                        section = null;                      // an array of tables: not a location's
                        continue;
                    }
                    int close = s.IndexOf(']');
                    section = close > 0 ? s.Substring(1, close - 1).Trim(' ', '\t').ToLowerInvariant() : null;
                    continue;
                }
                int cut = s.IndexOf('=');
                if (cut <= 0)
                    continue;
                string key = s.Substring(0, cut).Trim(' ', '\t').ToLowerInvariant();
                string rest = s.Substring(cut + 1).Trim(' ', '\t');
                bool parsed;
                TomlValue value;
                if (rest.StartsWith("\"\"\"", StringComparison.Ordinal) || rest.StartsWith("'''", StringComparison.Ordinal))
                    parsed = TryTomlMultiline(rest, lines, ref i, out value);
                else
                    parsed = TryTomlValue(rest, out value);
                if (parsed && section != null)
                    values[section.Length > 0 ? section + "." + key : key] = value;
            }
            return values;
        }

        /// <summary>
        /// A multi-line string opened on this line, advancing past its lines. The closer is
        /// the first unescaped triple delimiter (a basic string's backslash escapes are
        /// stepped over), and up to two more delimiter characters right before it belong to
        /// the value. The newline right after the opener is dropped; in a basic string a
        /// backslash at the end of a line removes itself, the newline and the whitespace
        /// that follows.
        /// </summary>
        private static bool TryTomlMultiline(string rest, string[] lines, ref int i, out TomlValue value)
        {
            value = default;
            string delimiter = rest.Substring(0, 3);
            string all = rest.Substring(3);
            int close = Closer(all, delimiter);
            while (close < 0 && i < lines.Length)
            {
                all += "\n" + lines[i];
                i++;
                close = Closer(all, delimiter);
            }
            if (close < 0 || !OnlyComment(all.Substring(close + 3)))
                return false;
            string raw = all.Substring(0, close);
            if (raw.StartsWith("\n", StringComparison.Ordinal))
                raw = raw.Substring(1);
            if (delimiter == "'''")
            {
                value = new TomlValue(TomlKind.String, raw, false);
                return true;
            }
            var chars = new System.Text.StringBuilder();
            int j = 0;
            while (j < raw.Length)
            {
                char c = raw[j];
                if (c == '\\')
                {
                    int k = j + 1;
                    while (k < raw.Length && (raw[k] == ' ' || raw[k] == '\t'))
                        k++;
                    if (k < raw.Length && raw[k] == '\n')             // a line-ending backslash
                    {
                        while (k < raw.Length && (raw[k] == ' ' || raw[k] == '\t' || raw[k] == '\n'))
                            k++;
                        j = k;
                        continue;
                    }
                    if (j + 1 < raw.Length)
                    {
                        char escaped = raw[j + 1];
                        chars.Append(escaped == 'n' ? '\n' : escaped == 't' ? '\t' : escaped);
                        j += 2;
                        continue;
                    }
                }
                chars.Append(c);
                j++;
            }
            value = new TomlValue(TomlKind.String, chars.ToString(), false);
            return true;
        }

        /// <summary>
        /// Where the closing delimiter starts in content, or -1: the first run of three to
        /// five delimiter characters not escaped by a backslash (basic strings only), whose
        /// last three close the string.
        /// </summary>
        private static int Closer(string content, string delimiter)
        {
            char quote = delimiter[0];
            int j = 0;
            while (j < content.Length)
            {
                char c = content[j];
                if (c == '\\' && quote == '"')
                {
                    j += 2;
                    continue;
                }
                if (string.CompareOrdinal(content, j, delimiter, 0, 3) == 0)
                {
                    int run = 3;
                    while (j + run < content.Length && content[j + run] == quote && run < 5)
                        run++;
                    return j + run - 3;
                }
                j++;
            }
            return -1;
        }

        private static bool TryTomlValue(string s, out TomlValue value)
        {
            value = default;
            if (s.StartsWith("\"", StringComparison.Ordinal))
            {
                var chars = new System.Text.StringBuilder();
                for (int i = 1; i < s.Length; i++)
                {
                    char c = s[i];
                    if (c == '\\' && i + 1 < s.Length)
                    {
                        char escaped = s[i + 1];
                        chars.Append(escaped == 'n' ? '\n' : escaped == 't' ? '\t' : escaped);
                        i++;
                        continue;
                    }
                    if (c == '"')
                    {
                        if (!OnlyComment(s.Substring(i + 1)))
                            return false;
                        value = new TomlValue(TomlKind.String, chars.ToString(), false);
                        return true;
                    }
                    chars.Append(c);
                }
                return false;
            }
            if (s.StartsWith("'", StringComparison.Ordinal))
            {
                int close = s.IndexOf('\'', 1);
                if (close <= 0 || !OnlyComment(s.Substring(close + 1)))
                    return false;
                value = new TomlValue(TomlKind.String, s.Substring(1, close - 1), false);
                return true;
            }
            int hash = s.IndexOf('#');
            string token = (hash < 0 ? s : s.Substring(0, hash)).Trim(' ', '\t');
            if (token == "true" || token == "false")
            {
                value = new TomlValue(TomlKind.Boolean, token, token == "true");
                return true;
            }
            token = token.Replace("_", "");
            try
            {
                DecimalText.NetExponent(token);
            }
            catch (ArgumentException)
            {
                return false;                                // arrays, inline tables, dates, inf/nan
            }
            value = new TomlValue(TomlKind.Number, token, false);
            return true;
        }

        private static bool OnlyComment(string rest)
        {
            rest = rest.Trim(' ', '\t');
            return rest.Length == 0 || rest[0] == '#';
        }
    }
}
