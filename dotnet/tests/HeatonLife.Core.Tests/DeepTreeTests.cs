using System;
using System.Collections.Generic;
using System.Numerics;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// The walks a tree's depth decides fit a thread of 1 MB, Windows' default: frames far out,
    /// whose blocks reach past the root to the frame's scale (a density frame at mag −5000 overflowed
    /// a 1 MB stack in <c>PopBig</c> under <c>Density</c>, test host crash on windows-latest), and
    /// every walk over a tree of the deepest level, 512 (populations, boxes, counts in a rectangle,
    /// frames near its cells, files, conversion). Each runs on a thread of exactly 1 MB, so the test
    /// means the same on every platform; a walk that overflows takes the test host down.
    /// </summary>
    public class DeepTreeTests
    {
        private const int OneMegabyte = 1 << 20;

        private static T OnStack<T>(int size, Func<T> work)
        {
            T result = default!;
            Exception? failure = null;
            var thread = new Thread(() =>
            {
                try
                {
                    result = work();
                }
                catch (Exception e)
                {
                    failure = e;
                }
            }, size);
            thread.Start();
            thread.Join();
            if (failure != null)
                throw new InvalidOperationException("the walk failed on its thread", failure);
            return result;
        }

        private static string DeepText()
        {
            var lines = new List<string> { "[M2]", "#R B3/S23History", "1 0 3 0 1" };
            for (int k = 2; k <= 512; k++)
                lines.Add($"{k} {k - 1} 0 0 {(k == 512 ? k - 1 : 0)}");
            return string.Join("\n", lines);
        }

        private static List<byte[]> FarFrames()
        {
            var two = new HashLife();
            two.SetRect(-1, -1, new byte[] { 0, 1, 0, 0, 0, 1, 1, 1, 1 }, 3, 3);
            var multi = new MultiStateHashLife("B3/S23History");
            multi.SetRect(-1, -1, new byte[] { 0, 1, 0, 0, 0, 1, 1, 1, 3 }, 3, 3);
            var frames = new List<byte[]>();
            foreach (int mag in new[] { -600, -5000, -100000 })
            {
                var view = new LifeView(-2, -2, mag);
                frames.Add(two.Frame(4, 4, view, HashLifeRenderMode.Density));
                frames.Add(two.Frame(4, 4, view, HashLifeRenderMode.Any));
                frames.Add(multi.Frame(4, 4, view, MultiStateRenderMode.Density));
                frames.Add(multi.Frame(4, 4, view, MultiStateRenderMode.State));
            }
            return frames;
        }

        [Fact]
        public void FramesFarPastTheRootFitAOneMegabyteStack()
        {
            List<byte[]> small = OnStack(OneMegabyte, FarFrames);
            List<byte[]> large = OnStack(64 * OneMegabyte, FarFrames);
            Assert.Equal(large, small);
            Assert.Contains(small, frame => Array.Exists(frame, value => value != 0)); // the pattern shows
        }

        [Fact]
        public void EveryWalkOverTheDeepestTreeFitsAOneMegabyteStack()
        {
            string text = DeepText();
            string report = OnStack(OneMegabyte, () =>
            {
                MultiStateHashLife multi = MultiStateMacrocell.Read(text);
                CellBox box = multi.BoundingBox!.Value;
                BigInteger x0 = box.X0 + 1, y0 = box.Y0, x1 = box.X1, y1 = box.Y1;
                var near = new LifeView(box.X0, box.Y0, 2);
                HashLife two = multi.ToTwoState("B3/S23");
                CellBox twoBox = two.BoundingBox!.Value;
                MultiStateHashLife super = two.ToMultiState("B3/S23Super");
                MultiStateHashLife history = super.ToMultiState("B3/S23History");
                var parts = new List<string>
                {
                    $"{multi.Population} {multi.LivePopulation} {multi.PopulationIn(x0, y0, x1, y1)}",
                    $"{multi.LivePopulationIn(x0, y0, x1, y1)} {multi.BoundingBoxIn(x0, y0, x1, y1)}",
                    $"{two.Population} {two.PopulationIn(x0, y0, x1, y1)} {two.BoundingBoxIn(x0, y0, x1, y1)}",
                    $"{twoBox} {history.Population} {multi.ToMacrocell().Length} {two.ToMacrocell().Length}",
                    Convert.ToBase64String(multi.Frame(8, 8, near, MultiStateRenderMode.State)),
                    Convert.ToBase64String(multi.Frame(8, 8, near, MultiStateRenderMode.Density)),
                    Convert.ToBase64String(two.Frame(8, 8, new LifeView(twoBox.X0, twoBox.Y0, 2), HashLifeRenderMode.Density)),
                };
                multi.MeasureSnapshots(new[] { multi.Snapshot() });
                multi.StateRule = StateRules.Compile("B3/S23/C4"); // a rule change looks for the largest state
                return string.Join("|", parts);
            });
            Assert.StartsWith("4 4 ", report, StringComparison.Ordinal);
        }
    }
}
