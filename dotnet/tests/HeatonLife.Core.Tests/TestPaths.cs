using System;
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
    }
}
