using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace HeatonLife.Tests
{
    internal static class TestPaths
    {
        /// <summary>Ascend from the test binary to the repo's shared vectors/ directory.</summary>
        internal static string VectorRoot()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null)
            {
                string candidate = Path.Combine(dir.FullName, "vectors");
                if (Directory.Exists(candidate))
                    return candidate;
                dir = dir.Parent;
            }
            throw new DirectoryNotFoundException("could not locate the repo vectors/ directory");
        }

        /// <summary>The Name column of a spec page's "## States" table (spec/history.md,
        /// spec/super.md), state n at index n.</summary>
        internal static List<string> SpecStateNames(string page)
        {
            string root = Path.GetDirectoryName(VectorRoot())!;
            string text = File.ReadAllText(Path.Combine(root, "spec", page)).Replace("\r\n", "\n");
            int at = text.IndexOf("\n## States\n", StringComparison.Ordinal);
            if (at < 0)
                throw new InvalidDataException($"spec/{page} has no States section");
            var names = new List<string>();
            bool inTable = false;
            foreach (string line in text.Substring(at + 1).Split('\n'))
            {
                if (!line.StartsWith("|", StringComparison.Ordinal))
                {
                    if (inTable)
                        break;
                    continue;
                }
                inTable = true;
                string[] cells = line.Split('|');
                if (!int.TryParse(cells[1].Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out int state))
                    continue; // the header and the rule under it
                if (state != names.Count)
                    throw new InvalidDataException($"spec/{page}: state {state} out of order");
                names.Add(cells[2].Trim());
            }
            return names;
        }
    }
}
