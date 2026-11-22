using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Snapshots (spec/hashlife.md "Snapshots", "What snapshots hold"), a file read into a
    /// universe that exists (spec/formats.md "Reading into a universe that exists"), and a
    /// timeline's frames from the reader by content. The vectors pin the counts; these tests pin
    /// the properties that make them useful. The Python reference's test_hashlife_snapshots.py.
    /// </summary>
    public class HashLifeSnapshotTests
    {
        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        private const string Gun =
            "#CXRLE Pos=-18,-4\nx = 36, y = 9, rule = B3/S23\n"
            + "24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$2o8bo3bob2o4bobo$"
            + "10bo5bo7bo$11bo3bo$12b2o!\n";

        private static int NodeLines(string macrocell)
            => macrocell.Split('\n').Skip(1).Count(line => line.Length > 0 && line[0] != '#');

        private static (string, BigInteger, string) StateOf(HashLife u) => (u.ToMacrocell(), u.Generation, u.Rule);

        [Fact]
        public void AStatesNodesAreItsCanonicalMacrocellLines()
        {
            HashLife u = HashLife.FromRle(Gun);
            for (int i = 0; i < 6; i++)
            {
                Assert.Equal(NodeLines(u.ToMacrocell()), u.MeasureSnapshots(Array.Empty<HashLifeSnapshot>()).UniverseNodes);
                u.Step(37);
            }
            Assert.Equal(0, new HashLife().MeasureSnapshots(Array.Empty<HashLifeSnapshot>()).UniverseNodes); // its `$` is no node
        }

        [Fact]
        public void TheLastSnapshotsCountsAddUpToWhatLettingThemGoFrees()
        {
            HashLife u = HashLife.FromRle(Gun);
            var history = new List<HashLifeSnapshot>();
            for (int i = 0; i < 7; i++)
            {
                history.Add(u.Snapshot());
                u.Step(17);
                u.SetCell(40, 3 * history.Count, true); // every point a little different
            }
            history.Reverse(); // newest first
            SnapshotFootprint whole = u.MeasureSnapshots(history);
            Assert.Equal(whole.Added.Sum(), whole.Nodes);
            Assert.Equal(whole.Nodes * 40, whole.EstimatedBytes);
            for (int k = 0; k <= history.Count; k++)
            {
                long freed = whole.Nodes - u.MeasureSnapshots(history.Take(history.Count - k)).Nodes;
                Assert.Equal(whole.Added.Skip(history.Count - k).Sum(), freed);
            }
        }

        [Fact]
        public void ASnapshotOfTheCurrentStateOrListedTwiceAddsNothing()
        {
            HashLife u = HashLife.FromRle(Gun);
            HashLifeSnapshot old = u.Snapshot();
            u.Step(90);
            HashLifeSnapshot now = u.Snapshot();
            SnapshotFootprint footprint = u.MeasureSnapshots(new[] { now, old, old });
            Assert.Equal(0, footprint.Added[0]);
            Assert.True(footprint.Added[1] > 0);
            Assert.Equal(0, footprint.Added[2]);
        }

        [Fact]
        public void AReleasedSnapshotLetsACollectionFreeItsNodes()
        {
            HashLife u = HashLife.FromRle(Gun);
            HashLifeSnapshot old = u.Snapshot();
            u.Step(1000);
            u.CollectGarbage();
            long holding = u.NodeCount;
            Assert.False(old.Released);
            old.Release();
            old.Release(); // again does nothing
            Assert.True(old.Released);
            Assert.Equal(BigInteger.Zero, old.Generation); // still readable
            u.CollectGarbage(); // the object is still alive here: only the release lets go
            Assert.True(u.NodeCount < holding, $"{u.NodeCount} nodes after the release, {holding} before");
            Assert.Equal(new long[] { 0 }, u.MeasureSnapshots(new[] { old }).Added.ToArray());
            Assert.Contains("released", Assert.Throws<ArgumentException>(() => u.Restore(old)).Message);
            Assert.Contains("released", Assert.Throws<ArgumentException>(() => Macrocell.WriteTimeline(u, new[] { old })).Message);
            GC.KeepAlive(old);
        }

        [Fact]
        public async Task AnotherThreadMayReleaseASnapshot()
        {
            HashLife u = HashLife.FromRle(Gun);
            HashLifeSnapshot old = u.Snapshot();
            u.Step(500);
            u.CollectGarbage();
            long holding = u.NodeCount;
            await Task.Run(old.Release);
            u.CollectGarbage();
            Assert.True(u.NodeCount < holding);
            GC.KeepAlive(old);
        }

        [Fact]
        public void MeasuringAnotherUniversesSnapshotThrows()
        {
            var a = new HashLife();
            var b = new HashLife();
            Assert.Throws<ArgumentException>(() => a.MeasureSnapshots(new[] { b.Snapshot() }));
            Assert.Throws<ArgumentNullException>(() => a.MeasureSnapshots(null!));
        }

        [Fact]
        public void AdvancingPartOfTheUniverseHoldsNoSnapshotAfter()
        {
            HashLife u = HashLife.FromRle(Gun);
            u.AdvanceSelection(-18, -4, 0, 4, 30);
            u.AdvanceOutside(-18, -4, 0, 4, 30);
            u.CollectGarbage(); // drops released entries from the store's list
            Assert.Empty(u.Store.Snapshots);
        }

        [Fact]
        public void ReadSnapshotKeepsTheUniverseAndItsHistory()
        {
            var u = new HashLife("B36/S23");
            u.SetRect(0, 0, Glider, 3, 3);
            HashLifeSnapshot first = u.Snapshot();
            u.Step(40);
            var before = StateOf(u);
            PatternSnapshot found = u.ReadSnapshot(Encoding.ASCII.GetBytes(Gun));
            Assert.Equal(before, StateOf(u));
            Assert.Equal((PatternFormat.Rle, "B3/S23"), (found.Format, found.Rule));
            Assert.Empty(found.Frames);
            Assert.Null(found.Step);
            u.Rule = found.Rule;
            u.Restore(found.Snapshot);
            Assert.Equal(HashLife.FromRle(Gun).ToMacrocell(), u.ToMacrocell());
            u.Restore(first); // the history from before the read still restores
            Assert.Equal((BigInteger.Zero, new BigInteger(5)), (u.Generation, u.Population));
            Assert.Equal(u.ReadSnapshot(Gun).Snapshot.Generation, found.Snapshot.Generation); // and from text
        }

        [Fact]
        public void ARefusedFileLeavesTheUniverseAndItsSnapshots()
        {
            var u = new HashLife();
            u.SetRect(-3, 2, Glider, 3, 3);
            HashLifeSnapshot kept = u.Snapshot();
            u.Step(9);
            var before = StateOf(u);
            string[] bad =
            {
                "#Life 1.05\n#R 23/3/4\n#P 0 0\n**\n", // not a Life-like rule
                "#Life 1.06\n1000000001 0\n",         // outside the editing box
                "x = 2, y = 1, rule = WireWorld\nAC!\n", // extended
                "[M2]\n#FRAMES 2 0 1\n*$\n#FRAME 0 1\n", // a frame missing
                "[M2]\n#R life\n*$\n",               // a preset
            };
            foreach (string text in bad)
            {
                Exception e = Assert.ThrowsAny<Exception>(() => u.ReadSnapshot(Encoding.ASCII.GetBytes(text)));
                Assert.True(e is FormatException || e is ArgumentException, e.ToString());
                Assert.Equal(before, StateOf(u));
            }
            u.Restore(kept);
            Assert.Equal(BigInteger.Zero, u.Generation);
        }

        [Fact]
        public void AFileSharesTheNodesTheStoreAlreadyHolds()
        {
            HashLife u = HashLife.FromRle(Gun);
            u.Step(120);
            PatternSnapshot same = u.ReadSnapshot(u.ToMacrocell());
            Assert.Equal(new long[] { 0 }, u.MeasureSnapshots(new[] { same.Snapshot }).Added.ToArray());
            PatternSnapshot shifted = u.ReadSnapshot(Gun.Replace("Pos=-18,-4", "Pos=-17,-4"));
            Assert.True(u.MeasureSnapshots(new[] { shifted.Snapshot }).Added[0] > 0);
        }

        [Fact]
        public void ATimelineGivesItsFramesToBothReaders()
        {
            HashLife recorded = HashLife.FromRle(Gun);
            var frames = new List<HashLifeSnapshot>();
            foreach (int generation in new[] { 0, 30, 60, 90 })
            {
                recorded.Step(generation - recorded.Generation);
                frames.Add(recorded.Snapshot());
            }
            string text = Macrocell.WriteTimeline(recorded, frames, new PatternMetadata("Gun", null, Array.Empty<string>()));
            MacrocellTimeline timeline = Macrocell.ReadTimeline(text);
            var expected = new List<string>();
            foreach (HashLifeSnapshot frame in timeline.Frames)
            {
                timeline.Universe.Restore(frame);
                expected.Add(timeline.Universe.ToMacrocell());
            }
            byte[] gzipped;
            using (var output = new MemoryStream())
            {
                using (var gzip = new GZipStream(output, CompressionLevel.Optimal, leaveOpen: true))
                {
                    byte[] raw = Encoding.ASCII.GetBytes(text);
                    gzip.Write(raw, 0, raw.Length);
                }
                gzipped = output.ToArray();
            }
            foreach (byte[] source in new[] { Encoding.ASCII.GetBytes(text), gzipped })
            {
                PatternUniverse found = PatternFiles.ReadUniverse(source);
                Assert.Equal(new BigInteger(30), found.Step);
                Assert.Equal("Gun", found.Metadata.Name);
                Assert.Equal(new BigInteger(90), found.Universe.Generation); // the file's own root and #G
                var got = new List<string>();
                foreach (HashLifeSnapshot frame in found.Frames)
                {
                    found.Universe.Restore(frame);
                    got.Add(found.Universe.ToMacrocell());
                }
                Assert.Equal(expected, got);

                var host = new HashLife("B36/S23");
                host.SetRect(5, 5, Glider, 3, 3);
                PatternSnapshot snapshot = host.ReadSnapshot(source);
                Assert.Equal((new BigInteger(30), "B3/S23", BigInteger.Zero), (snapshot.Step!.Value, snapshot.Rule, host.Generation));
                host.Rule = snapshot.Rule;
                got.Clear();
                foreach (HashLifeSnapshot frame in snapshot.Frames)
                {
                    host.Restore(frame);
                    got.Add(host.ToMacrocell());
                }
                Assert.Equal(expected, got);
            }
        }

        [Fact]
        public void FrameLinesWithoutAFramesLineAreNoTimeline()
        {
            PatternUniverse found = PatternFiles.ReadUniverse("[M2]\n*$\n#FRAME 0 1\n");
            Assert.Empty(found.Frames);
            Assert.Null(found.Step);
            // The plain Macrocell reader skips a broken timeline; the reader by content refuses it.
            const string broken = "[M2]\n#FRAMES 2 0 1\n*$\n#FRAME 1 1\n";
            Assert.Equal(BigInteger.One, HashLife.FromMacrocell(broken).Population);
            Assert.Contains("frame 0", Assert.Throws<FormatException>(() => PatternFiles.ReadUniverse(broken)).Message);
        }
    }
}
