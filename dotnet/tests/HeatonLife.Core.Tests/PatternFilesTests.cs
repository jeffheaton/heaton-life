using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Numerics;
using System.Text;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Pattern files beyond the vectors (spec/formats.md): round trips of cells and metadata
    /// through every writer, what the writers refuse, text decoding, numbers of any size, and
    /// the timeline writer's rules. The Python twin is python/tests/test_formats.py.
    /// </summary>
    public class PatternFilesTests
    {
        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        private static byte[] Utf8(string text) => new UTF8Encoding(false).GetBytes(text);

        private static byte[] Gzip(byte[] data)
        {
            using var output = new MemoryStream();
            using (var gzip = new GZipStream(output, CompressionLevel.Optimal, leaveOpen: true))
                gzip.Write(data, 0, data.Length);
            return output.ToArray();
        }

        private static PatternMetadata RandomMetadata(Random random)
        {
            string[] words = { "glider", "Café", "x = 3", "#N", "!Name:", "  ", "", "ą Å —", "$!bo" };
            string Text() => string.Join(" ", Enumerable.Range(0, random.Next(4)).Select(_ => words[random.Next(words.Length)]));
            string? name = random.NextDouble() < 0.7 ? Text() : null;
            string? author = random.NextDouble() < 0.7 ? Text() : null;
            var comments = Enumerable.Range(0, random.Next(5)).Select(_ => Text()).ToList();
            return new PatternMetadata(name, author, comments);
        }

        /// <summary>What a reader gives back for metadata a writer was handed.</summary>
        private static PatternMetadata Stripped(PatternMetadata m)
        {
            string? Value(string? v) => string.IsNullOrEmpty(v?.Trim()) ? null : v!.Trim();
            return new PatternMetadata(Value(m.Name), Value(m.Author), m.Comments.Select(c => c.Trim()));
        }

        // -- metadata ---------------------------------------------------------------------------

        [Fact]
        public void RleRoundTripsCellsAndMetadata()
        {
            var random = new Random(10);
            for (int trial = 0; trial < 200; trial++)
            {
                int width = random.Next(1, 12), height = random.Next(1, 12);
                int top = new[] { 1, 2, 24 }[random.Next(3)];
                var cells = new byte[width * height];
                for (int i = 0; i < cells.Length; i++)
                    cells[i] = (byte)random.Next(top + 1);
                PatternMetadata notes = RandomMetadata(random);
                string text = Patterns.RleEncode(cells, width, height, top == 1 ? "B3/S23" : "WireWorld", notes);
                RlePattern decoded = Patterns.RleDecode(text);
                Assert.Equal(cells, decoded.Cells);
                Assert.Equal(Stripped(notes), Patterns.RleMetadata(text));
                Assert.Equal(Stripped(notes), PatternFiles.Read(text).Metadata);
            }
        }

        [Fact]
        public void UniverseWritersRoundTripMetadata()
        {
            var random = new Random(11);
            for (int trial = 0; trial < 40; trial++)
            {
                var u = new HashLife("B36/S23");
                u.FillRandom(-9, -5, 8, 6, 0.4, (ulong)random.Next());
                u.Step(random.Next(50));
                PatternMetadata notes = RandomMetadata(random);
                foreach (string text in new[] { u.ToRle(notes), u.ToMacrocell(notes) })
                {
                    PatternUniverse found = PatternFiles.ReadUniverse(text);
                    Assert.Equal(Stripped(notes), found.Metadata);
                    Assert.Equal(u.ToMacrocell(), found.Universe.ToMacrocell());
                }
            }
        }

        [Fact]
        public void NoMetadataWritesExactlyWhatItDid()
        {
            var u = new HashLife();
            u.SetRect(3, -2, Glider, 3, 3);
            foreach (PatternMetadata? notes in new[] { null, PatternMetadata.Empty, new PatternMetadata("", "  ") })
            {
                Assert.Equal(Patterns.RleEncode(Glider, 3, 3), Patterns.RleEncode(Glider, 3, 3, "B3/S23", notes));
                Assert.Equal(u.ToRle(), u.ToRle(notes));
                Assert.Equal(u.ToMacrocell(), u.ToMacrocell(notes));
            }
        }

        [Fact]
        public void MetadataLinesAreCanonical()
        {
            var notes = new PatternMetadata("Glider", "R. K. Guy", new[] { "one", "", "  three  " });
            string text = Patterns.RleEncode(Glider, 3, 3, "B3/S23", notes);
            Assert.StartsWith("#N Glider\n#O R. K. Guy\n#C one\n#C\n#C three\nx = 3, y = 3", text);
            var u = new HashLife();
            u.SetRect(0, 0, Glider, 3, 3);
            Assert.StartsWith("#CXRLE Pos=0,0\n#N Glider\n", u.ToRle(notes));
            Assert.StartsWith("[M2] (heaton-life)\n#R B3/S23\n#N Glider\n", u.ToMacrocell(notes));
        }

        [Theory]
        [InlineData('\n')]
        [InlineData('\r')]
        [InlineData('\x0b')]
        [InlineData('\x0c')]
        [InlineData('\x1c')]
        [InlineData('\x1d')]
        [InlineData('\x1e')]
        [InlineData('\x85')]
        [InlineData('\u2028')]
        [InlineData('\u2029')]
        public void AMetadataValueWithALineEndIsRefused(char end)
        {
            var u = new HashLife();
            foreach (PatternMetadata notes in new[]
            {
                new PatternMetadata(name: $"a{end}b"),
                new PatternMetadata(author: $"a{end}"),
                new PatternMetadata(comments: new[] { "fine", $"{end}x" }),
            })
            {
                Assert.Throws<ArgumentException>(() => Patterns.RleEncode(Glider, 3, 3, "B3/S23", notes));
                Assert.Throws<ArgumentException>(() => u.ToMacrocell(notes));
                Assert.Throws<ArgumentException>(() => u.ToRle(notes));
            }
        }

        [Fact]
        public void TheFirstNameAndAuthorCount()
        {
            const string text = "#O first author\n#N first\n#N second\n#O second author\nx = 1, y = 1\no!\n";
            Assert.Equal(new PatternMetadata("first", "first author"), Patterns.RleMetadata(text));
            Assert.Null(Patterns.RleMetadata("#N\n#N named later\no!\n").Name);
            Assert.Equal(new[] { "XRLE Pos=3,4" }, Patterns.RleMetadata("\n#CXRLE Pos=1,2\n#CXRLE Pos=3,4\no!\n").Comments);
        }

        // -- bytes and text ---------------------------------------------------------------------

        [Fact]
        public void TextIsUtf8WhenItCanBeAndLatin1Otherwise()
        {
            Assert.Equal("Café", PatternText.Decode(Utf8("Café")));
            Assert.Equal("x", PatternText.Decode(new byte[] { 0xEF, 0xBB, 0xBF, (byte)'x' }));
            Assert.Equal("\uFEFFx", PatternText.Decode(new byte[] { 0xEF, 0xBB, 0xBF, 0xEF, 0xBB, 0xBF, (byte)'x' }));
            Assert.Equal("Café", PatternText.Decode(new byte[] { (byte)'C', (byte)'a', (byte)'f', 0xE9 }));
            Assert.Equal("\U0001F600", PatternText.Decode(new byte[] { 0xF0, 0x9F, 0x98, 0x80 }));
            byte[][] bad =
            {
                new byte[] { 0xC0, 0xAF }, new byte[] { 0xED, 0xA0, 0x80 }, new byte[] { 0xF4, 0x90, 0x80, 0x80 },
                new byte[] { 0xE2, 0x82 }, new byte[] { 0x80 }, new byte[] { 0xE0, 0x9F, 0xBF }, new byte[] { 0xF5, 0x80, 0x80, 0x80 },
            };
            foreach (byte[] b in bad)
                Assert.Equal(HashLife.Latin1(b, 0, b.Length), PatternText.Decode(b));
        }

        [Fact]
        public void A0x85ByteInsideAUtf8CharacterDoesNotEndALine()
        {
            byte[] data = Utf8("#C Å\nx = 1, y = 1\no!\n");
            Assert.Contains((byte)0x85, data);
            Assert.Equal(new[] { "Å" }, PatternFiles.Read(data).Metadata.Comments);
            Assert.Equal(BigInteger.One, PatternFiles.ReadUniverse(data).Universe.Population);
        }

        [Fact]
        public void RleDecodingSplitsLinesAsTheReferenceDoes()
        {
            // A file with CR line ends only: one line per CR, not one line in all.
            RlePattern decoded = Patterns.RleDecode("x = 3, y = 3, rule = B3/S23\rbo$2bo$\r3o!\r");
            Assert.Equal(Glider, decoded.Cells);
            Assert.Equal(Glider, Patterns.RleDecode("x = 3, y = 3\nbo$2bo$\u001f3o!").Cells); // U+001F is whitespace
        }

        [Fact]
        public void DetectionOfTextSkipsGzipAndImages()
        {
            Assert.Equal(PatternFormat.Rle, PatternFiles.Detect("bo$2bo$3o!"));
            Assert.Equal(PatternFormat.Rle, PatternFiles.Detect("\u0089PNG\r\n\u001a\n"));
            Assert.Equal(PatternFormat.Life106, PatternFiles.Detect(Gzip(Utf8("#Life 1.06\n0 0\n"))));
            Assert.Throws<FormatException>(() => PatternFiles.Detect("\n \t\n"));
        }

        [Theory]
        [InlineData(1)]
        [InlineData(4)]
        [InlineData(8)]
        [InlineData(20)]
        [InlineData(30)]
        public void AGzipStreamCutShortIsRefused(int cut)
        {
            byte[] packed = Gzip(Utf8(string.Concat(Enumerable.Repeat("x = 3, y = 3\nbo$2bo$3o!\n", 20))));
            Assert.Throws<FormatException>(() => PatternFiles.Read(packed[..^cut]));
        }

        [Fact]
        public void GzipInsideEveryReader()
        {
            byte[] data = Gzip(Utf8("!Name: g\n.O\n..O\nOOO\n"));
            Assert.Equal(Glider, PatternFiles.Read(data).Cells);
            Assert.Equal(new BigInteger(5), PatternFiles.ReadUniverse(data).Universe.Population);
        }

        // -- numbers of any size ----------------------------------------------------------------

        [Fact]
        public void Life106CoordinatesOfAnySize()
        {
            BigInteger big = BigInteger.Pow(10, 5000);
            PatternFile found = PatternFiles.Read($"#Life 1.06\n{big} -{big}\n{big + 1} -{big}\n");
            Assert.Equal(big, found.X);
            Assert.Equal(-big, found.Y);
            Assert.Equal(new byte[] { 1, 1 }, found.Cells);
        }

        [Fact]
        public void MacrocellGenerationsOfAnySize()
        {
            BigInteger big = BigInteger.Pow(10, 5000) + 7;
            var u = new HashLife();
            u.SetRect(0, 0, Glider, 3, 3);
            string text = u.ToMacrocell().Replace("#R B3/S23\n", $"#R B3/S23\n#G {big}\n");
            HashLife again = Macrocell.Read(text);
            Assert.Equal(big, again.Generation);
            Assert.Equal(text, again.ToMacrocell());
            Assert.Equal(big, PatternFiles.ReadUniverse(again.ToRle()).Universe.Generation);
        }

        // -- formats ----------------------------------------------------------------------------

        [Theory]
        [InlineData("#R 23/3", "B3/S23")]
        [InlineData("#R 3223/663", "B36/S23")]
        [InlineData("#R /3", "B3/S")]
        [InlineData("#R 23/", "B/S23")]
        [InlineData("#R 239/3", "239/3")]
        [InlineData("#R B3/S23", "B3/S23")]
        [InlineData("#R", null)]
        [InlineData("#N", "B3/S23")]
        public void Life105Rules(string line, string? rule)
            => Assert.Equal(rule, PatternFiles.Read($"#Life 1.05\n{line}\n*\n").Rule);

        [Fact]
        public void TheLastLife105RuleCounts()
            => Assert.Equal("B36/S23", PatternFiles.Read("#Life 1.05\n#R 23/3\n#R 23/36\n*\n").Rule);

        [Fact]
        public void PlaintextTrailingBlankLinesAreNotRows()
        {
            PatternFile found = PatternFiles.Read("O\n\n.O\n\n\n  \n");
            Assert.Equal(2, found.Width);
            Assert.Equal(3, found.Height);
            Assert.Equal(new byte[] { 1, 0, 0, 0, 0, 1 }, found.Cells);
        }

        [Fact]
        public void BoundingBoxFormatsRefuseAnEmptyPattern()
        {
            foreach (string text in new[] { "#Life 1.06\n", "#Life 1.05\n#P 0 0\n...\n", "[M2]\n$\n" })
                Assert.Throws<FormatException>(() => PatternFiles.Read(text));
        }

        [Fact]
        public void LoadReadsEveryFormat()
        {
            var files = new[]
            {
                Utf8(".O\n..O\nOOO\n"),
                Utf8("#Life 1.06\n1 0\n2 1\n0 2\n1 2\n2 2\n"),
                Gzip(Utf8("x = 3, y = 3\nbo$2bo$3o!\n")),
                PngGrid.EncodeRgb(Enumerable.Range(0, 9).SelectMany(i => Glider[i] != 0 ? new byte[] { 0, 0, 0 } : new byte[] { 255, 255, 255 }).ToArray(), 3, 3),
            };
            foreach (byte[] data in files)
            {
                HashLife u = HashLife.Load(data);
                Assert.Equal(new BigInteger(5), u.Population);
                Assert.Equal(new CellBox(0, 0, 2, 2), u.BoundingBox);
            }
        }

        [Fact]
        public void EncodeFileWritesMetadata()
        {
            var u = new HashLife();
            u.SetRect(0, 0, Glider, 3, 3);
            var notes = new PatternMetadata("Glider", "Ångström", new[] { "a comment" });
            foreach (string name in new[] { "g.rle", "g.mc", "g.mc.gz" })
            {
                PatternUniverse found = PatternFiles.ReadUniverse(u.EncodeFile(name, notes));
                Assert.Equal(notes, found.Metadata);
                Assert.Equal(new BigInteger(5), found.Universe.Population);
            }
        }

        [Fact]
        public void AnImagePastTheLimitIsRefusedBeforeDecoding()
        {
            // A header that claims 50,000 × 50,000 pixels over a few bytes of data.
            byte[] png = PngGrid.EncodeRgb(new byte[] { 0, 0, 0 }, 1, 1);
            png[16] = 0;
            png[17] = 0;
            png[18] = 0xC3;
            png[19] = 0x50;
            png[20] = 0;
            png[21] = 0;
            png[22] = 0xC3;
            png[23] = 0x50;
            Assert.Throws<ArgumentException>(() => PatternFiles.Read(png));
        }

        // -- timelines --------------------------------------------------------------------------

        [Fact]
        public void PowerIsTheSmallestBase()
        {
            var cases = new Dictionary<BigInteger, (BigInteger, int)>
            {
                [1] = (2, 0),
                [2] = (2, 1),
                [8] = (2, 3),
                [9] = (3, 2),
                [12] = (12, 1),
                [36] = (6, 2),
                [64] = (2, 6),
                [1000] = (10, 3),
                [BigInteger.Pow(3, 100)] = (3, 100),
                [BigInteger.Pow(6, 50)] = (6, 50),
                [BigInteger.Pow(2, 4095)] = (2, 4095),
                [BigInteger.Pow((BigInteger.One << 61) - 1, 3)] = ((BigInteger.One << 61) - 1, 3),
            };
            foreach (var (step, form) in cases)
                Assert.Equal(form, Macrocell.Power(step));
        }

        [Fact]
        public void WriteTimelineRefusesWhatAFileCannotHold()
        {
            var u = new HashLife();
            u.SetRect(0, 0, Glider, 3, 3);
            HashLifeSnapshot a = u.Snapshot();
            u.Step(2);
            HashLifeSnapshot b = u.Snapshot();
            u.Step(3);
            HashLifeSnapshot c = u.Snapshot();
            HashLifeSnapshot other = new HashLife().Snapshot();
            Assert.Throws<ArgumentException>(() => Macrocell.WriteTimeline(u, Array.Empty<HashLifeSnapshot>()));
            Assert.Throws<ArgumentException>(() => Macrocell.WriteTimeline(u, new[] { a, other }));
            Assert.Throws<ArgumentException>(() => Macrocell.WriteTimeline(u, new[] { a, b, c }));
            Assert.Throws<ArgumentException>(() => Macrocell.WriteTimeline(u, new[] { b, a }));
            Assert.Throws<ArgumentException>(() => Macrocell.WriteTimeline(u, new[] { a, a }));
        }

        [Fact]
        public void ATimelineFileLoadsItsLastFrameWithoutTimelines()
        {
            var u = new HashLife();
            u.SetRect(-1, 0, new byte[] { 1, 1, 1 }, 3, 1);
            var frames = new List<HashLifeSnapshot>();
            for (int i = 0; i < 3; i++)
            {
                frames.Add(u.Snapshot());
                u.Step(1);
            }
            string text = Macrocell.WriteTimeline(u, frames);
            HashLife plain = Macrocell.Read(text);
            u.Restore(frames[frames.Count - 1]);
            Assert.Equal(u.ToMacrocell(), plain.ToMacrocell());
            Assert.Equal(new BigInteger(2), HashLife.Load(Utf8(text)).Generation);
        }

        [Fact]
        public void TimelineFramesSurviveGarbageCollection()
        {
            MacrocellTimeline timeline = Macrocell.ReadTimeline(
                "[M2]\n#FRAMES 2 0 2^1\n.**$**$.*$\n$$$$$$$***$\n#FRAME 0 1\n#FRAME 1 2\n");
            HashLife u = timeline.Universe;
            u.Restore(timeline.Frames[0]);
            u.Step(1000);
            u.CollectGarbage();
            u.Restore(timeline.Frames[0]);
            Assert.Equal(new BigInteger(5), u.Population);
            u.Restore(timeline.Frames[1]);
            Assert.Equal(new BigInteger(3), u.Population);
        }

        [Fact]
        public void ReadTimelineNeedsFrames()
            => Assert.Throws<FormatException>(() => Macrocell.ReadTimeline("[M2]\n**$**$\n"));


        // ---- measuring (spec/formats.md "Measuring") ------------------------------------------

        public static IEnumerable<object[]> ReadInputs()
        {
            string formats = Path.Combine(TestPaths.VectorRoot(), "formats");
            foreach (string dir in Directory.GetDirectories(formats, "read-*").OrderBy(d => d, StringComparer.Ordinal))
            {
                foreach (string file in Directory.GetFiles(dir, "input.*"))
                    yield return new object[] { Path.GetFileName(dir), Path.GetFileName(file) };
            }
        }

        private static bool Refuses(Action action)
        {
            try
            {
                action();
                return false;
            }
            catch (Exception e) when (e is FormatException || e is ArgumentException)
            {
                return true;
            }
        }

        /// <summary>Every read case's input measures as an untrimmed read without a limit gives it;
        /// one that reading refuses is refused by measuring too, unless it is empty (0 x 0) or a
        /// picture whose pixels are what is wrong.</summary>
        [Theory]
        [MemberData(nameof(ReadInputs))]
        public void MeasuringAgreesWithReading(string caseName, string input)
        {
            byte[] data = File.ReadAllBytes(Path.Combine(TestPaths.VectorRoot(), "formats", caseName, input));
            PatternFile? found = null;
            if (Refuses(() => found = PatternFiles.Read(data, null)))
            {
                PatternExtent? measured = null;
                if (Refuses(() => measured = PatternFiles.Measure(data)))
                    return;
                Assert.True(
                    measured!.Width * measured.Height == 0 || measured.Format == PatternFormat.Png
                        || measured.Format == PatternFormat.Bmp,
                    caseName);
                return;
            }
            PatternExtent extent = PatternFiles.Measure(data);
            Assert.Equal(found!.Format, extent.Format);
            Assert.Equal((found.X, found.Y), (extent.X, extent.Y));
            Assert.Equal((found.Rule, found.Generation), (extent.Rule, extent.Generation));
            Assert.Equal(found.Metadata, extent.Metadata);
            Assert.Equal(new BigInteger(found.Width), extent.Width);
            Assert.Equal(new BigInteger(found.Height), extent.Height);
            bool extended = found.Format == PatternFormat.Rle
                && Patterns.RleMeasure(PatternText.Decode(PatternText.Inflate(data))).Extended;
            Assert.Equal(!extended, extent.TwoState);
        }

        [Fact]
        public void AMacrocellFileMeasuresAsItsUniverse()
        {
            // Measuring from the tree gives the bounding box, rule and generation the universe has,
            // for patterns near the origin and far out, written by the canonical writer.
            var rng = new Pcg32(1121); // test input only
            for (int trial = 0; trial < 40; trial++)
            {
                var u = new HashLife(trial % 2 == 1 ? "B36/S23" : "B3/S23");
                long far = (long)(rng.NextU32() % 999_999_000u) * (trial % 3 != 0 ? -1 : 1);
                int pieces = 1 + (int)(rng.NextU32() % 3);
                for (int k = 0; k < pieces; k++)
                {
                    int w = 1 + (int)(rng.NextU32() % 8), h = 1 + (int)(rng.NextU32() % 8);
                    var cells = new byte[w * h];
                    for (int i = 0; i < cells.Length; i++)
                        cells[i] = rng.NextU32() % 5 < 2 ? (byte)1 : (byte)0;
                    long x = (long)(rng.NextU32() % 80) - 40, y = (long)(rng.NextU32() % 80) - 40;
                    u.SetRect(x + (trial % 4 == 0 ? far : 0), y, cells, w, h, HashLifePasteMode.Or);
                }
                u.Step(rng.NextU32() % 5);
                PatternExtent extent = PatternFiles.Measure(u.ToMacrocell(new PatternMetadata("trial")));
                CellBox? found = u.BoundingBox;
                if (found == null)
                {
                    Assert.Equal((BigInteger.Zero, BigInteger.Zero), (extent.Width, extent.Height));
                    Assert.Equal((BigInteger.Zero, BigInteger.Zero), (extent.X, extent.Y));
                }
                else
                {
                    CellBox box = found.Value;
                    Assert.Equal((box.X0, box.Y0), (extent.X, extent.Y));
                    Assert.Equal((box.X1 - box.X0 + 1, box.Y1 - box.Y0 + 1), (extent.Width, extent.Height));
                }
                Assert.Equal((u.Rule, u.Generation), (extent.Rule, extent.Generation));
                Assert.Equal("trial", extent.Metadata.Name);
                Assert.True(extent.TwoState);
            }
        }

        [Fact]
        public void MeasuringMakesNoGrid()
        {
            // Sizes no memory holds measure exactly: an RLE run of 2^200 cells, Life 1.06 cells
            // 10^40 apart.
            BigInteger run = BigInteger.One << 200;
            string rle = "x = 1, y = 1\no" + run.ToString(System.Globalization.CultureInfo.InvariantCulture) + "bo!\n";
            PatternExtent extent = PatternFiles.Measure(rle);
            Assert.Equal((run + 2, BigInteger.One), (extent.Width, extent.Height));
            BigInteger apart = BigInteger.Pow(10, 40);
            string far = apart.ToString(System.Globalization.CultureInfo.InvariantCulture);
            PatternExtent cells = PatternFiles.Measure("#Life 1.06\n0 0\n" + far + " -" + far + "\n");
            Assert.Equal((apart + 1, apart + 1, -apart), (cells.Width, cells.Height, cells.Y));
            Assert.True(Refuses(() => PatternFiles.Read(rle, null)));
        }
    }
}
