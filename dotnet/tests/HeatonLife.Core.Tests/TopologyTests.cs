using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Grid topologies (spec/topology.md), checked independently of the vectors the conformance
    /// runner replays: the flat topologies run as their unfolded plane, a glider crosses shifted
    /// and twisted edges as the spec's oracles say, the cross-surface's and sphere's corners land
    /// a point the same whichever edge it crosses first, and bounded RLE round-trips. The Python
    /// suite's python/tests/test_topology.py checks the same.
    /// </summary>
    public class TopologyTests
    {
        private static readonly Topology[] Flat =
        {
            new Topology(Boundary.Torus),
            new Topology(Boundary.Torus, 3),
            new Topology(Boundary.Torus, -5),
            new Topology(Boundary.Torus, 2, TopologyAxis.Y),
            new Topology(Boundary.Klein),
            new Topology(Boundary.Klein, 0, TopologyAxis.Y),
            new Topology(Boundary.Klein, 1),
            new Topology(Boundary.Klein, -3, TopologyAxis.Y),
        };

        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        public static IEnumerable<object[]> FlatCases() => Flat.Select(t => new object[] { t.Name, t.Shift, t.AxisName });

        private static byte[] Soup(int width, int height, double density, uint seed)
        {
            var life = new LifeLike("B3/S23", width, height, Boundary.Dead);
            life.SeedSoup(density, seed);
            return life.State.ToArray();
        }

        /// <summary>The plane around a flat topology's grid, every point holding the cell it stands
        /// for, out to <paramref name="copies"/> grids in every direction.</summary>
        private static byte[] Unfolded(Topology topology, byte[] cells, int width, int height, int copies)
        {
            int bigW = width * (2 * copies + 1), bigH = height * (2 * copies + 1);
            var plane = new byte[bigW * bigH];
            for (int y = 0; y < bigH; y++)
            {
                for (int x = 0; x < bigW; x++)
                {
                    Assert.True(topology.Locate(x - copies * width, y - copies * height, width, height, out int cx, out int cy));
                    plane[y * bigW + x] = cells[cy * width + cx];
                }
            }
            return plane;
        }

        private static byte[] Middle(ReadOnlySpan<byte> plane, int width, int height, int copies)
        {
            int bigW = width * (2 * copies + 1);
            var middle = new byte[width * height];
            for (int y = 0; y < height; y++)
                plane.Slice((copies * height + y) * bigW + copies * width, width).CopyTo(middle.AsSpan(y * width, width));
            return middle;
        }

        [Theory]
        [MemberData(nameof(FlatCases))]
        public void AFlatTopologyRunsAsItsUnfoldedPlane(string boundary, int shift, string axis)
        {
            Topology topology = Topology.Parse(boundary, shift, axis);
            foreach (var (width, height) in new[] { (12, 10), (10, 12) })
            {
                byte[] start = Soup(width, height, 0.4, (uint)(width * 7 + height));
                var world = new LifeLike("B3/S23", width, height, topology);
                world.SetState(start);
                byte[] plane = Unfolded(topology, start, width, height, 2);
                var flat = new LifeLike("B3/S23", width * 5, height * 5, Boundary.Dead);
                flat.SetState(plane);
                for (int g = 0; g < Math.Min(width, height); g++)
                {
                    world.Step();
                    flat.Step();
                    Assert.Equal(world.State.ToArray(), Middle(flat.State, width, height, 2));
                }
            }
        }

        [Theory]
        [MemberData(nameof(FlatCases))]
        public void WireworldRunsAsItsUnfoldedPlaneToo(string boundary, int shift, string axis)
        {
            Topology topology = Topology.Parse(boundary, shift, axis);
            const int width = 12, height = 10;
            byte[] a = Soup(width, height, 0.5, 1), b = Soup(width, height, 0.5, 2);
            byte[] start = a.Zip(b, (x, y) => (byte)(x + 2 * y)).ToArray();
            var world = new Wireworld(width, height, start, topology);
            byte[] plane = Unfolded(topology, start, width, height, 2);
            var flat = new Wireworld(width * 5, height * 5, plane, Boundary.Dead);
            for (int g = 0; g < height; g++)
            {
                world.Step();
                flat.Step();
                Assert.Equal(world.State.ToArray(), Middle(flat.State, width, height, 2));
            }
        }

        private static byte[] Place(int width, int height, byte[] pattern, int pw, int x0, int y0)
        {
            var grid = new byte[width * height];
            for (int i = 0; i < pattern.Length; i++)
                grid[(y0 + i / pw) * width + x0 + i % pw] = pattern[i];
            return grid;
        }

        [Fact]
        public void AGliderCrossingAShiftedEdgeComesBackShifted()
        {
            byte[] start = Place(20, 16, Glider, 3, 4, 10);
            var plain = new LifeLike("B3/S23", 20, 16, Boundary.Torus);
            plain.SetState(start);
            var shifted = new LifeLike("B3/S23", 20, 16, new Topology(Boundary.Torus, 5));
            shifted.SetState(start);
            plain.Step(24);
            shifted.Step(24);
            var rolled = new byte[20 * 16];
            for (int y = 0; y < 16; y++)
                for (int x = 0; x < 20; x++)
                    rolled[y * 20 + (x + 5) % 20] = plain.State[y * 20 + x];
            Assert.Equal(rolled, shifted.State.ToArray());
        }

        [Fact]
        public void AGliderCrossingATwistedEdgeComesBackMirrored()
        {
            var klein = new LifeLike("B3/S23", 20, 16, new Topology(Boundary.Klein));
            klein.SetState(Place(20, 16, Glider, 3, 4, 10));
            klein.Step(24);
            var unfolded = new LifeLike("B3/S23", 20, 32, Boundary.Dead);
            unfolded.SetState(Place(20, 32, Glider, 3, 4, 10));
            unfolded.Step(24);
            var expected = new byte[20 * 16];
            for (int y = 0; y < 16; y++)
                for (int x = 0; x < 20; x++)
                    expected[y * 20 + x] = unfolded.State[(16 + y) * 20 + 19 - x];
            Assert.Equal(expected, klein.State.ToArray());
        }

        [Fact]
        public void TheSphereFoldsTheTopOntoTheLeft()
        {
            var halo = new Halo(new Topology(Boundary.Sphere), 3, 3);
            var filled = new byte[halo.Length];
            halo.Fill(Encoding.ASCII.GetBytes("ABCDEFGHI"), filled, 0);
            string rows = Encoding.ASCII.GetString(filled);
            Assert.Equal("AADGCAABCGBDEFHCGHIIGCFII", rows);
        }

        [Fact]
        public void TheCrossSurfaceAndKleinBottleMirrorTheirTwistedEdges()
        {
            string Rows(Topology topology)
            {
                var halo = new Halo(topology, 4, 3);
                var filled = new byte[halo.Length];
                halo.Fill(Encoding.ASCII.GetBytes("ABCDEFGHIJKL"), filled, 0);
                return Encoding.ASCII.GetString(filled);
            }
            Assert.Equal("ALKJID" + "LABCDI" + "HEFGHE" + "DIJKLA" + "IDCBAL", Rows(new Topology(Boundary.Cross)));
            Assert.Equal("ILKJIL" + "DABCDA" + "HEFGHE" + "LIJKLI" + "ADCBAD", Rows(new Topology(Boundary.Klein)));
            Assert.Equal("KLIJKL" + "DABCDA" + "HEFGHE" + "LIJKLI" + "ABCDAB", Rows(new Topology(Boundary.Torus, 1)));
        }

        /// <summary>One edge crossed, the first axis's when the point lies beyond one of those: the
        /// cross-surface's and the sphere's single crossings as spec/topology.md words them.</summary>
        private static (long, long) CrossOneEdge(Boundary boundary, long x, long y, int w, int h, bool xFirst)
        {
            bool beyondX = x < 0 || x >= w, beyondY = y < 0 || y >= h;
            bool acrossX = beyondX && (xFirst || !beyondY);
            if (boundary == Boundary.Cross)
                return acrossX ? (x < 0 ? x + w : x - w, h - 1 - y) : (w - 1 - x, y < 0 ? y + h : y - h);
            long n = w; // a sphere
            if (acrossX)
                return x < 0 ? (y, -1 - x) : (y, 2 * n - 1 - x);
            return y < 0 ? (-1 - y, x) : (2 * n - 1 - y, x);
        }

        [Theory]
        [InlineData(Boundary.Cross)]
        [InlineData(Boundary.Sphere)]
        public void PastACornerEitherEdgeMayBeCrossedFirst(Boundary boundary)
        {
            var topology = new Topology(boundary);
            foreach (var (w, h) in new[] { (1, 1), (2, 3), (5, 4), (6, 6), (7, 7) })
            {
                if (boundary == Boundary.Sphere && w != h)
                    continue;
                int reach = Math.Min(w, h);
                for (long x = -reach; x < w + reach; x++)
                {
                    for (long y = -reach; y < h + reach; y++)
                    {
                        if (x >= 0 && x < w && y >= 0 && y < h)
                            continue;
                        Assert.True(topology.Locate(x, y, w, h, out int lx, out int ly));
                        foreach (bool xFirst in new[] { true, false })
                        {
                            (long px, long py) = (x, y);
                            for (int i = 0; i < 4 && !(px >= 0 && px < w && py >= 0 && py < h); i++)
                                (px, py) = CrossOneEdge(boundary, px, py, w, h, xFirst);
                            Assert.Equal((lx, ly), ((int)px, (int)py));
                        }
                    }
                }
            }
        }

        [Fact]
        public void LocateIsExactFarAway()
        {
            // The flat topologies' formulas in exact integers, against the port's long arithmetic.
            static BigInteger Floor(BigInteger a, BigInteger b) => BigInteger.Divide(a - ((a % b) + b) % b, b);
            static BigInteger Mod(BigInteger a, BigInteger b) => ((a % b) + b) % b;
            long[] far = { -4_000_000_000_000L, -2_000_000_001L, -31, 7, 1_999_999_999L, 9_000_000_000_000_000L };
            foreach (Topology t in Flat)
            {
                foreach (long x in far)
                {
                    foreach (long y in far)
                    {
                        const int w = 30, h = 20;
                        Assert.True(t.Locate(x, y, w, h, out int cx, out int cy));
                        BigInteger ex, ey;
                        if (t.Boundary == Boundary.Torus && t.Axis == TopologyAxis.X)
                            (ex, ey) = (Mod(x + Floor(y, h) * t.Shift, w), Mod(y, h));
                        else if (t.Boundary == Boundary.Torus)
                            (ex, ey) = (Mod(x, w), Mod(y + Floor(x, w) * t.Shift, h));
                        else if (t.Axis == TopologyAxis.X)
                            (ex, ey) = (Floor(y, h).IsEven ? Mod(x, w) : Mod(w - 1 + t.Shift - (BigInteger)x, w), Mod(y, h));
                        else
                            (ex, ey) = (Mod(x, w), Floor(x, w).IsEven ? Mod(y, h) : Mod(h - 1 + t.Shift - (BigInteger)y, h));
                        Assert.Equal((ex, ey), ((BigInteger)cx, (BigInteger)cy));
                    }
                }
            }
        }

        [Fact]
        public void AnAxisThatMeansNothingReadsBackAsX()
        {
            Assert.Equal(TopologyAxis.X, new Topology(Boundary.Torus, 0, TopologyAxis.Y).Axis);
            Assert.Equal(TopologyAxis.X, new Topology(Boundary.Sphere, 0, TopologyAxis.Y).Axis);
            Assert.Equal(TopologyAxis.Y, new Topology(Boundary.Klein, 0, TopologyAxis.Y).Axis);
            Assert.Equal(new Topology(Boundary.Torus), default);
            var life = new LifeLike("B3/S23", 8, 8, new Topology(Boundary.Torus, 0, TopologyAxis.Y));
            Assert.Equal(Boundary.Torus, life.Boundary);
            Assert.Equal(new Topology(Boundary.Torus), life.Topology);
        }

        [Theory]
        [InlineData("sphere", 0, "x", 8, 9, "a sphere is square")]
        [InlineData("klein", 1, "x", 9, 8, "a Klein bottle shifts only a side of even length")]
        [InlineData("klein", 1, "y", 8, 9, "a Klein bottle shifts only a side of even length")]
        [InlineData("torus", 0, "x", 0, 8, "a grid has at least one row and one column")]
        public void AWorldTheSizeCantHaveIsRefused(string boundary, int shift, string axis, int w, int h, string reason)
        {
            Topology topology = Topology.Parse(boundary, shift, axis);
            Assert.Equal(reason, Assert.Throws<TopologyException>(() => topology.Check(w, h)).Reason);
            Assert.Equal(reason, Assert.Throws<TopologyException>(() => new LifeLike("B3/S23", w, h, topology)).Reason);
            Assert.Equal(reason, Assert.Throws<TopologyException>(() => new Wireworld(w, h, new byte[Math.Max(w * h, 0)], topology)).Reason);
        }

        [Theory]
        [InlineData("moebius", 0, "x", "unknown boundary 'moebius': expected dead, torus, klein, cross or sphere")]
        [InlineData("torus", 0, "z", "unknown axis 'z': expected x or y")]
        [InlineData("dead", 1, "x", "the plane has no shift")]
        [InlineData("cross", 2, "x", "the cross-surface has no shift")]
        [InlineData("sphere", -1, "y", "the sphere has no shift")]
        public void ATopologyThatIsNoneSaysWhy(string boundary, int shift, string axis, string reason)
        {
            TopologyException e = Assert.Throws<TopologyException>(() => Topology.Parse(boundary, shift, axis));
            Assert.Equal(reason, e.Reason);
            Assert.Equal($"invalid topology: {reason} (spec/topology.md)", e.Message);
        }

        [Fact]
        public void ElementaryKeepsItsTwoEnds()
        {
            Assert.Throws<ArgumentException>(() => new Elementary(30, 16, 8, Boundary.Klein));
            Assert.Throws<ArgumentException>(() => new Elementary(30, 16, 8, Boundary.Sphere));
        }

        [Fact]
        public void SteppingOnAnyTopologyAllocatesNothing()
        {
            var life = new LifeLike("B3/S23", 64, 48, new Topology(Boundary.Klein, 1));
            var wire = new Wireworld(48, 48, new byte[48 * 48], new Topology(Boundary.Sphere));
            life.Step(2); // warm up
            wire.Step(2);
            Assert.Equal(0, Allocations.Least(() =>
            {
                life.Step(20);
                wire.Step(20);
            }));
        }

        // ---- RLE --------------------------------------------------------------------------------

        private const string GliderBo = "x = 3, y = 3, rule = B3/S23:T30,20\nBOB$2BO$3O!\n";

        [Fact]
        public void ASuffixLeavesTheDialectToTheRule()
        {
            RlePattern decoded = Patterns.RleDecode(GliderBo);
            Assert.Equal("B3/S23", decoded.Rule);
            Assert.Equal(Glider, decoded.Cells);
            Assert.Equal(BoundedGrid.Parse(":T30,20"), decoded.BoundedGrid);
            RleExtent extent = Patterns.RleMeasure(GliderBo);
            Assert.False(extent.Extended);
            Assert.Equal(BoundedGrid.Parse(":T30,20"), extent.BoundedGrid);
            RlePattern wire = Patterns.RleDecode("x = 3, y = 1, rule = WireWorld:P10,4\nCBA!\n");
            Assert.Equal("WireWorld", wire.Rule);
            Assert.Equal(new byte[] { 3, 2, 1 }, wire.Cells);
        }

        [Fact]
        public void AWorldWritesItsSuffixAndReadsBackAsItself()
        {
            Topology[] every = Flat.Concat(new[]
            {
                new Topology(Boundary.Dead), new Topology(Boundary.Cross), new Topology(Boundary.Sphere),
            }).ToArray();
            foreach (Topology topology in every)
            {
                int w = 12, h = topology.Boundary == Boundary.Sphere ? 12 : 10;
                byte[] world = Soup(w, h, 0.3, 3);
                string text = Patterns.RleEncode(world, w, h, "b3/s32", null, topology);
                var expected = new BoundedGrid(w, h, topology);
                Assert.StartsWith($"x = {w}, y = {h}, rule = B3/S23{expected.Suffix}\n", text);
                PatternFile found = PatternFiles.Read(text);
                Assert.Equal(expected, found.BoundedGrid);
                Assert.Equal((new BigInteger(-(w / 2)), new BigInteger(-(h / 2))), (found.X, found.Y));
                Assert.Equal("B3/S23", found.Rule);
                Assert.Equal(world, found.Cells);
                PatternExtent extent = PatternFiles.Measure(text);
                Assert.Equal((new BigInteger(w), new BigInteger(h), found.X, found.Y), (extent.Width, extent.Height, extent.X, extent.Y));
                Assert.Equal(expected, extent.BoundedGrid);
            }
        }

        [Fact]
        public void ABoundedPatternIsCenteredInItsWorldWithoutAPosition()
        {
            PatternFile found = PatternFiles.Read(GliderBo);
            Assert.Equal((30, 20), (found.Width, found.Height));
            Assert.Equal((new BigInteger(-15), new BigInteger(-10)), (found.X, found.Y));
            for (int i = 0; i < 9; i++)
                Assert.Equal(Glider[i], found.Cells[(9 + i / 3) * 30 + 14 + i % 3]);
            Assert.Equal(5, found.Cells.Count(c => c != 0));
            PatternFile trimmed = PatternFiles.Read(GliderBo, Patterns.DefaultMaxCells, trim: true);
            Assert.Equal((new BigInteger(-1), new BigInteger(-1), 3, 3), (trimmed.X, trimmed.Y, trimmed.Width, trimmed.Height));
            Assert.Equal(found.BoundedGrid, trimmed.BoundedGrid);
        }

        [Fact]
        public void ABoundedPatternGoesWhereItsPositionSays()
        {
            PatternFile found = PatternFiles.Read("#CXRLE Pos=-15,7\n" + GliderBo);
            for (int i = 0; i < 9; i++)
                Assert.Equal(Glider[i], found.Cells[(17 + i / 3) * 30 + i % 3]);
            Assert.Equal(5, found.Cells.Count(c => c != 0));
            Assert.Throws<ArgumentException>(() => PatternFiles.Read("#CXRLE Pos=-15,8\n" + GliderBo));
            Assert.Throws<ArgumentException>(() => PatternFiles.Measure("#CXRLE Pos=-16,0\n" + GliderBo));
            Assert.Throws<ArgumentException>(
                () => PatternFiles.Read("#CXRLE Pos=-16,0\n" + GliderBo, Patterns.DefaultMaxCells, trim: true));
        }

        [Fact]
        public void ADeadMarginMayReachPastTheWorld()
        {
            PatternFile found = PatternFiles.Read("x = 40, y = 3, rule = B3/S23:P30,20\n19b3o!\n");
            Assert.Equal((30, 20), (found.Width, found.Height));
            Assert.Equal(new byte[] { 1, 1, 1 }, found.Cells.Skip(9 * 30 + 14).Take(3).ToArray());
        }

        [Fact]
        public void ARunCountOfAnyLengthPlacesInItsWorld()
        {
            // A dead run 5,001 digits long: centered, it widens the pattern past any world; placed
            // by its position, the live cell after it lands where it says.
            string body = "x = 3, y = 3, rule = B3/S23:T30,20\n1" + new string('0', 5000) + "b$bo!\n";
            Assert.Throws<ArgumentException>(() => PatternFiles.Read(body));
            PatternFile found = PatternFiles.Read("#CXRLE Pos=-15,-10\n" + body);
            Assert.Equal((new BigInteger(-15), new BigInteger(-10), 30, 20), (found.X, found.Y, found.Width, found.Height));
            Assert.Equal(1, found.Cells[1 * 30 + 1]);
            Assert.Equal(1, found.Cells.Count(c => c != 0));
        }

        [Fact]
        public void TheUniverseHasNoBoundedGrid()
        {
            Assert.Contains("no bounded grid", Assert.Throws<FormatException>(() => PatternFiles.ReadUniverse(GliderBo)).Message);
            Assert.Throws<FormatException>(() => Patterns.RleToHashLife(GliderBo));
            Assert.Throws<FormatException>(() => new HashLife().ReadSnapshot(GliderBo));
        }

        [Fact]
        public void ABadSuffixIsAnErrorOfTheDecode()
        {
            Assert.Throws<TopologyException>(() => Patterns.RleDecode("x = 3, y = 3, rule = B3/S23:T0,20\nbo$2bo$3o!\n"));
            Assert.Throws<TopologyException>(() => PatternFiles.Read("x = 3, y = 3, rule = B3/S23:Q\nbo$2bo$3o!\n"));
        }
    }
}
