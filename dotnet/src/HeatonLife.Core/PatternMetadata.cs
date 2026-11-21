using System;
using System.Collections.Generic;

namespace HeatonLife
{
    /// <summary>
    /// What a pattern file says besides its cells (spec/formats.md "Metadata"): the pattern's
    /// name, its author, and its comment lines in file order. RLE and Macrocell spell them
    /// <c>#N</c>, <c>#O</c> and <c>#C</c>; plaintext <c>!Name:</c>, <c>!Author:</c> and <c>!</c>;
    /// Life 1.05 and 1.06 <c>#D</c>. The Python reference's heaton_life.init.PatternMetadata.
    /// </summary>
    public sealed class PatternMetadata : IEquatable<PatternMetadata>
    {
        /// <summary>No name, no author, no comments.</summary>
        public static readonly PatternMetadata Empty = new PatternMetadata();

        public PatternMetadata(string? name = null, string? author = null, IEnumerable<string>? comments = null)
        {
            Name = name;
            Author = author;
            var lines = new List<string>();
            if (comments != null)
            {
                foreach (string comment in comments)
                    lines.Add(comment ?? throw new ArgumentNullException(nameof(comments), "a comment is null"));
            }
            Comments = lines.AsReadOnly();
        }

        /// <summary>What the pattern is called, or null.</summary>
        public string? Name { get; }

        /// <summary>Who found or made it (free text), or null.</summary>
        public string? Author { get; }

        /// <summary>The comment lines in file order, empty ones included.</summary>
        public IReadOnlyList<string> Comments { get; }

        /// <summary>True when there is no name, no author, and no comment.</summary>
        public bool IsEmpty => Name == null && Author == null && Comments.Count == 0;

        public bool Equals(PatternMetadata? other)
        {
            if (other is null || other.Name != Name || other.Author != Author || other.Comments.Count != Comments.Count)
                return false;
            for (int i = 0; i < Comments.Count; i++)
            {
                if (other.Comments[i] != Comments[i])
                    return false;
            }
            return true;
        }

        public override bool Equals(object? obj) => Equals(obj as PatternMetadata);

        public override int GetHashCode()
        {
            int hash = (Name?.GetHashCode() ?? 0) * 31 + (Author?.GetHashCode() ?? 0);
            foreach (string comment in Comments)
                hash = hash * 31 + comment.GetHashCode();
            return hash;
        }

        public override string ToString()
            => $"PatternMetadata(name: {Name ?? "null"}, author: {Author ?? "null"}, comments: [{string.Join(" | ", Comments)}])";

        // ---- writing (spec/formats.md "Metadata", "Writing") ------------------------------

        /// <summary>The <c>#N</c>, <c>#O</c> and <c>#C</c> lines RLE and Macrocell write: values
        /// stripped, a value with a line end refused.</summary>
        internal static List<string> Lines(PatternMetadata? metadata)
        {
            var lines = new List<string>();
            if (metadata == null)
                return lines;
            if (metadata.Name != null)
            {
                string name = Value(metadata.Name, "name");
                if (name.Length > 0)
                    lines.Add("#N " + name);
            }
            if (metadata.Author != null)
            {
                string author = Value(metadata.Author, "author");
                if (author.Length > 0)
                    lines.Add("#O " + author);
            }
            foreach (string comment in metadata.Comments)
            {
                string text = Value(comment, "comment");
                lines.Add(text.Length > 0 ? "#C " + text : "#C");
            }
            return lines;
        }

        private static string Value(string value, string what)
        {
            foreach (char c in value)
            {
                if (TextLines.IsBreak(c))
                    throw new ArgumentException($"the metadata's {what} holds a line end: '{value}'");
            }
            return TextLines.Strip(value);
        }
    }

    /// <summary>Collects metadata from a file's lines: the first name and author count, and
    /// the comments keep their order (spec/formats.md "Metadata").</summary>
    internal sealed class MetadataReader
    {
        private readonly List<string> _comments = new List<string>();
        private string? _name;
        private string? _author;
        private bool _named;
        private bool _authored;

        internal void Name(string value)
        {
            if (_named)
                return;
            _named = true;
            string name = TextLines.Strip(value);
            _name = name.Length > 0 ? name : null;
        }

        internal void Author(string value)
        {
            if (_authored)
                return;
            _authored = true;
            string author = TextLines.Strip(value);
            _author = author.Length > 0 ? author : null;
        }

        internal void Comment(string value) => _comments.Add(TextLines.Strip(value));

        /// <summary>An RLE or Macrocell <c>#</c> line, stripped: <c>#N</c> names, <c>#O</c>
        /// credits, <c>#C</c> and <c>#c</c> comment; any other tag is not metadata.</summary>
        internal void HashLine(string line)
        {
            if (line.Length < 2)
                return;
            char tag = line[1];
            if (tag == 'N')
                Name(line.Substring(2));
            else if (tag == 'O')
                Author(line.Substring(2));
            else if (tag == 'C' || tag == 'c')
                Comment(line.Substring(2));
        }

        internal PatternMetadata Result() => new PatternMetadata(_name, _author, _comments);
    }
}
