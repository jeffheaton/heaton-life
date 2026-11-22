using System;
using System.Diagnostics;
using System.Linq;
using System.Numerics;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Editing primitives (spec/patterns.md "Extract and stamp", "Editing a region";
    /// spec/hashlife.md "Editing"): paste modes, the counter-clockwise turn, random fill,
    /// Advance Selection and Advance Outside on grids and in HashLife, and HashLife's rectangle
    /// tools. The C# counterpart of python/tests/test_editing.py.
    /// </summary>
    public class EditingTests
    {
        private const long Limit = HashLife.EditLimit;

        private static readonly byte[] Glider = { 0, 1, 0, 0, 0, 1, 1, 1, 1 };

        private static (byte[] Cells, int Width, int Height) Builtin(string name)
        {
            RlePattern p = BuiltinPatterns.All.First(b => b.Name == name).Decode();
            return (p.Cells, p.Width, p.Height);
        }

        /// <summary>Incompressible 0/1 test input from an integer hash (simulation randomness stays PCG32).</summary>
        private static byte[] Noise(int height, int width, uint seed)
        {
            var cells = new byte[height * width];
            for (int i = 0; i < cells.Length; i++)
            {
                uint v = unchecked((uint)i * 0x9E3779B1u + seed);
                v ^= v >> 15;
                v = unchecked(v * 0x85EBCA6Bu);
                v ^= v >> 13;
                v = unchecked(v * 0xC2B2AE35u);
                v ^= v >> 16;
                cells[i] = (byte)(v >> 31);
            }
            return cells;
        }

        private static ulong LeafOf(Func<int, int, bool> alive)
        {
            ulong b = 0;
            for (int y = 0; y < 8; y++)
                for (int x = 0; x < 8; x++)
                    if (alive(x, y))
                        b |= 1UL << (y * 8 + x);
            return b;
        }

        private static bool At(ulong b, int x, int y) => ((b >> (y * 8 + x)) & 1) != 0;

        // -- leaves -----------------------------------------------------------------------------

        [Fact]
        public void LeafTransformsMoveEveryCell()
        {
            ulong seed = 0x9E3779B97F4A7C15UL;
            for (int trial = 0; trial < 300; trial++)
            {
                seed = seed * 6364136223846793005UL + 1442695040888963407UL;
                ulong b = seed;
                Assert.Equal(LeafOf((x, y) => At(b, y, x)), HashLifeLeaves.Transpose(b));
                Assert.Equal(LeafOf((x, y) => At(b, y, 7 - x)), HashLifeLeaves.TurnCw(b));
                Assert.Equal(LeafOf((x, y) => At(b, 7 - y, x)), HashLifeLeaves.TurnCcw(b));
                Assert.Equal(LeafOf((x, y) => At(b, 7 - x, y)), HashLifeLeaves.MirrorColumns(b));
                Assert.Equal(LeafOf((x, y) => At(b, x, 7 - y)), HashLifeLeaves.MirrorRows(b));
                ulong ne = b * 3 + 7, sw = ~b, se = b ^ (b >> 13);
                ulong[] quads = { b, ne, sw, se };
                for (int ox = 0; ox <= 8; ox += 1 + trial % 3)
                {
                    for (int oy = 0; oy <= 8; oy += 1 + trial % 2)
                    {
                        int cx = ox, cy = oy;
                        ulong want = LeafOf((x, y) =>
                        {
                            int gx = x + cx, gy = y + cy;
                            return At(quads[(gy >= 8 ? 2 : 0) + (gx >= 8 ? 1 : 0)], gx & 7, gy & 7);
                        });
                        Assert.Equal(want, HashLifeLeaves.Crop(b, ne, sw, se, ox, oy));
                    }
                }
            }
        }

        // -- grids: transforms and stamping -----------------------------------------------------

        [Fact]
        public void Rotate90CcwUndoesRotate90()
        {
            byte[] p = { 1, 2, 3, 4, 5, 6 }; // 3 wide, 2 tall
            Assert.Equal(new byte[] { 3, 6, 2, 5, 1, 4 }, Patterns.Rotate90Ccw(p, 3, 2));
            Assert.Equal(p, Patterns.Rotate90Ccw(Patterns.Rotate90(p, 3, 2), 2, 3));
            Assert.Equal(p, Patterns.Rotate90(Patterns.Rotate90Ccw(p, 3, 2), 2, 3));
            byte[] thrice = Patterns.Rotate90(Patterns.Rotate90(Patterns.Rotate90(p, 3, 2), 2, 3), 3, 2);
            Assert.Equal(thrice, Patterns.Rotate90Ccw(p, 3, 2));
            byte[] rgb = Enumerable.Range(0, 18).Select(i => (byte)i).ToArray(); // 3 × 2 × 3 channels
            Assert.Equal(rgb, Patterns.Rotate90(Patterns.Rotate90Ccw(rgb, 3, 2, 3), 2, 3, 3));
            double[] planes = Enumerable.Range(0, 12).Select(i => i * 0.5).ToArray(); // 3 × 2, two planes
            Assert.Equal(planes, Patterns.Rotate90Planes(Patterns.Rotate90CcwPlanes(planes, 3, 2, 2), 2, 3, 2));
        }

        [Fact]
        public void StampModesCombineTwoStateCells()
        {
            byte[] target = Noise(9, 11, 1);
            byte[] piece = Noise(5, 7, 2);
            foreach (StampMode mode in new[] { StampMode.Copy, StampMode.Or, StampMode.Xor, StampMode.And })
            {
                byte[] got = (byte[])target.Clone();
                Patterns.Stamp(got, 11, 9, 1, piece, 7, 5, 3, 2, torus: false, mode);
                byte[] want = (byte[])target.Clone();
                for (int r = 0; r < 5; r++)
                {
                    for (int c = 0; c < 7; c++)
                    {
                        int i = (r + 2) * 11 + c + 3;
                        byte p = piece[r * 7 + c];
                        want[i] = mode == StampMode.Copy ? p
                            : mode == StampMode.Or ? (byte)(want[i] | p)
                            : mode == StampMode.Xor ? (byte)(want[i] ^ p)
                            : (byte)(want[i] & p);
                    }
                }
                Assert.Equal(want, got);
            }
            // Wrapping: every pattern cell lands somewhere, and xor toggles accumulate.
            var wrapped = new byte[9];
            byte[] ones = Enumerable.Repeat((byte)1, 16).ToArray();
            Patterns.Stamp(wrapped, 3, 3, 1, ones, 4, 4, 0, 0, torus: true, StampMode.Xor);
            // Rows and columns 0 take two pattern rows or columns each, the others one.
            Assert.Equal(new byte[] { 0, 0, 0, 0, 1, 1, 0, 1, 1 }, wrapped);
            // The older flag is mode or.
            byte[] a = Enumerable.Repeat((byte)2, 16).ToArray(), b = (byte[])a.Clone();
            byte[] ghost = Glider.Select(v => (byte)(3 * v)).ToArray();
            Patterns.Stamp(a, 4, 4, 1, ghost, 3, 3, 1, 1, torus: true, transparent: true);
            Patterns.Stamp(b, 4, 4, 1, ghost, 3, 3, 1, 1, torus: true, StampMode.Or);
            Assert.Equal(a, b);
            Assert.Equal(2, a[5]);
            Assert.Equal(3, a[6]);
        }

        [Theory]
        [InlineData(StampMode.Xor)]
        [InlineData(StampMode.And)]
        public void TwoStateModesRefuseOtherValuesUnchanged(StampMode mode)
        {
            var grid = new byte[16];
            grid[15] = 2; // under the glider only when it wraps from (2, 2)
            byte[] before = (byte[])grid.Clone();
            Patterns.Stamp(grid, 4, 4, 1, Glider, 3, 3, 0, 0, torus: false, mode);
            grid = (byte[])before.Clone();
            Assert.Throws<ArgumentException>(() => Patterns.Stamp(grid, 4, 4, 1, Glider, 3, 3, 2, 2, torus: true, mode));
            Assert.Equal(before, grid);
            byte[] doubled = Glider.Select(v => (byte)(2 * v)).ToArray();
            Assert.Throws<ArgumentException>(() => Patterns.Stamp(grid, 4, 4, 1, doubled, 3, 3, 0, 0, torus: false, mode));
            Assert.Equal(before, grid);
            Assert.Throws<ArgumentException>(
                () => Patterns.Stamp(new byte[48], 4, 4, 3, new byte[12], 2, 2, 0, 0, torus: true, mode));
        }

        // -- grids: random fill -----------------------------------------------------------------

        [Fact]
        public void FillRandomIsTheSoupOfTheRegion()
        {
            var life = new LifeLike("B3/S23", 30, 20);
            life.SeedSoup(0.6, 4);
            byte[] seeded = life.State.ToArray();
            life.Step(3);
            byte[] stepped = life.State.ToArray();
            life.FillRandom(5, 3, 16, 14, 0.35, 99);
            var soup = new byte[12 * 12];
            Seeding.Soup(soup, 0.35, 99);
            byte[] want = (byte[])stepped.Clone();
            for (int y = 0; y < 12; y++)
                Array.Copy(soup, y * 12, want, (y + 3) * 30 + 5, 12);
            Assert.Equal(want, life.State.ToArray());
            Assert.Equal(3, life.Generation);
            // The draws depend on the region's size alone: HashLife fills alike anywhere.
            var u = new HashLife();
            u.FillRandom(-1000, 77, -989, 88, 0.35, 99);
            Assert.Equal(soup, u.GetRect(-1000, 77, -989, 88));
            // A fill of the whole grid with the grid's own seed is its soup.
            var whole = new LifeLike("B3/S23", 30, 20);
            whole.SeedSoup(0.6, 4);
            whole.Step(1);
            whole.FillRandom(0, 0, 29, 19, 0.6, 4);
            Assert.Equal(seeded, whole.State.ToArray());
        }

        [Theory]
        [InlineData(-1, 0, 3, 3)]
        [InlineData(0, 0, 30, 3)]
        [InlineData(5, 5, 4, 5)]
        [InlineData(0, 3, 3, 2)]
        [InlineData(0, 0, 0, 20)]
        public void RegionsLieInsideTheGrid(int x0, int y0, int x1, int y1)
        {
            var life = new LifeLike("B3/S23", 30, 20);
            byte[] before = life.State.ToArray();
            Assert.Throws<ArgumentOutOfRangeException>(() => life.FillRandom(x0, y0, x1, y1, 0.5, 1));
            Assert.Throws<ArgumentOutOfRangeException>(() => life.AdvanceSelection(x0, y0, x1, y1, 2));
            Assert.Throws<ArgumentOutOfRangeException>(() => life.AdvanceOutside(x0, y0, x1, y1, 2));
            Assert.Equal(before, life.State.ToArray());
            Assert.Equal(0, life.Generation);
            Assert.Throws<ArgumentOutOfRangeException>(() => life.FillRandom(0, 0, 3, 3, 1.5, 1));
            Assert.Throws<ArgumentOutOfRangeException>(() => life.AdvanceOutside(0, 0, 3, 3, -1));
            Assert.Equal(before, life.State.ToArray());
        }

        // -- grids: Advance Selection and Advance Outside ---------------------------------------

        private interface IWorld
        {
            byte[] Cells { get; }

            int Generation { get; }

            void Step(int n);

            void Advance(int x0, int y0, int x1, int y1, int n, bool outside);
        }

        private sealed class Life : IWorld
        {
            private readonly LifeLike _w;

            public Life(string rule, int width, int height, Boundary boundary, byte[] cells)
            {
                _w = new LifeLike(rule, width, height, boundary);
                _w.SetState(cells);
            }

            public byte[] Cells => _w.State.ToArray();

            public int Generation => _w.Generation;

            public void Step(int n) => _w.Step(n);

            public void Advance(int x0, int y0, int x1, int y1, int n, bool outside)
            {
                if (outside)
                    _w.AdvanceOutside(x0, y0, x1, y1, n);
                else
                    _w.AdvanceSelection(x0, y0, x1, y1, n);
            }
        }

        private sealed class Wire : IWorld
        {
            private readonly Wireworld _w;

            public Wire(int width, int height, Boundary boundary, byte[] cells)
                => _w = new Wireworld(width, height, cells, boundary);

            public byte[] Cells => _w.State.ToArray();

            public int Generation => _w.Generation;

            public void Step(int n) => _w.Step(n);

            public void Advance(int x0, int y0, int x1, int y1, int n, bool outside)
            {
                if (outside)
                    _w.AdvanceOutside(x0, y0, x1, y1, n);
                else
                    _w.AdvanceSelection(x0, y0, x1, y1, n);
            }
        }

        private sealed class Cycle : IWorld
        {
            private readonly Cyclic _w;

            public Cycle(int states, int width, int height, byte[] cells)
            {
                _w = new Cyclic(states, width, height, threshold: 2, reach: 2, Neighborhood.VonNeumann);
                _w.SetState(cells);
            }

            public byte[] Cells => _w.State.ToArray();

            public int Generation => _w.Generation;

            public void Step(int n) => _w.Step(n);

            public void Advance(int x0, int y0, int x1, int y1, int n, bool outside)
            {
                if (outside)
                    _w.AdvanceOutside(x0, y0, x1, y1, n);
                else
                    _w.AdvanceSelection(x0, y0, x1, y1, n);
            }
        }

        private sealed class Gen : IWorld
        {
            private readonly Generations _w;

            public Gen(int width, int height, byte[] cells)
            {
                _w = new Generations("B2/S345/C4", width, height, new Topology(Boundary.Klein));
                _w.SetState(cells);
            }

            public byte[] Cells => _w.State.ToArray();

            public int Generation => _w.Generation;

            public void Step(int n) => _w.Step(n);

            public void Advance(int x0, int y0, int x1, int y1, int n, bool outside)
            {
                if (outside)
                    _w.AdvanceOutside(x0, y0, x1, y1, n);
                else
                    _w.AdvanceSelection(x0, y0, x1, y1, n);
            }
        }

        private static byte[] ClockLoop(int width, int height)
        {
            var cells = new byte[width * height];
            for (int x = 1; x < width - 1; x++)
                cells[width + x] = cells[(height - 2) * width + x] = Wireworld.Conductor;
            for (int y = 1; y < height - 1; y++)
                cells[y * width + 1] = cells[y * width + width - 2] = Wireworld.Conductor;
            cells[width + 2] = Wireworld.Tail;
            cells[width + 3] = Wireworld.Head;
            return cells;
        }

        public static TheoryData<string> WorldNames() => new TheoryData<string>
        {
            "life-torus", "life-dead", "life-b0", "wireworld", "cyclic", "generations",
        };

        private static (Func<byte[], IWorld> Make, byte[] Cells, int Width, int Height) MakeWorld(string name)
        {
            switch (name)
            {
                case "life-torus":
                    return (c => new Life("B36/S23", 24, 18, Boundary.Torus, c), Noise(18, 24, 5), 24, 18);
                case "life-dead":
                    return (c => new Life("B3/S23", 24, 18, Boundary.Dead, c), Noise(18, 24, 6), 24, 18);
                case "life-b0":
                    return (c => new Life("B0123478/S01234678", 20, 16, Boundary.Torus, c), Noise(16, 20, 7), 20, 16);
                case "wireworld":
                    return (c => new Wire(20, 20, Boundary.Dead, c), ClockLoop(20, 20), 20, 20);
                case "generations":
                    {
                        byte[] a = Noise(16, 20, 10), b = Noise(16, 20, 11);
                        byte[] cells = a.Select((v, i) => (byte)(v + 2 * b[i])).ToArray();
                        return (c => new Gen(20, 16, c), cells, 20, 16);
                    }
                default:
                    {
                        byte[] a = Noise(16, 20, 8), b = Noise(16, 20, 9);
                        byte[] cells = a.Select((v, i) => (byte)(v + 2 * b[i])).ToArray();
                        return (c => new Cycle(4, 20, 16, c), cells, 20, 16);
                    }
            }
        }

        [Theory]
        [MemberData(nameof(WorldNames))]
        public void AdvanceIsABlankedCopyMergedBack(string name)
        {
            var (make, cells, width, height) = MakeWorld(name);
            foreach (bool outside in new[] { false, true })
            {
                foreach (var (x0, y0, x1, y1, n) in new[] { (3, 2, 12, 9, 7), (0, 0, 5, 15, 4), (8, 1, 8, 1, 1), (2, 3, 9, 7, 0) })
                {
                    IWorld world = make(cells);
                    world.Step(2);
                    byte[] stepped = world.Cells;
                    world.Advance(x0, y0, x1, y1, n, outside);
                    // The spec's definition, spelled out: a blanked copy run n generations, merged.
                    var copy = new byte[stepped.Length];
                    for (int i = 0; i < copy.Length; i++)
                    {
                        int x = i % width, y = i / width;
                        bool inside = x >= x0 && x <= x1 && y >= y0 && y <= y1;
                        copy[i] = inside != outside ? stepped[i] : (byte)0;
                    }
                    IWorld alone = make(copy);
                    alone.Step(n);
                    byte[] grown = alone.Cells;
                    var want = new byte[stepped.Length];
                    for (int i = 0; i < want.Length; i++)
                    {
                        int x = i % width, y = i / width;
                        bool inside = x >= x0 && x <= x1 && y >= y0 && y <= y1;
                        want[i] = inside != outside ? grown[i] : stepped[i];
                    }
                    Assert.Equal(want, world.Cells);
                    Assert.Equal(2, world.Generation);
                }
            }
        }

        [Fact]
        public void AdvanceOnATorusWrapsBackIntoTheRegion()
        {
            var grid = new byte[64];
            for (int y = 0; y < 3; y++)
                Array.Copy(Glider, y * 3, grid, y * 8, 3);
            var life = new LifeLike("B3/S23", 8, 8, Boundary.Torus);
            life.SetState(grid);
            var plain = new LifeLike("B3/S23", 8, 8, Boundary.Torus);
            plain.SetState(grid);
            // 32 generations carry a glider once round the torus, out of the region and back in.
            life.AdvanceSelection(0, 0, 3, 3, 32);
            plain.Step(32);
            Assert.Equal(plain.State.ToArray(), life.State.ToArray());
            Assert.Equal(0, life.Generation);
            // The whole grid: n plain generations, the counter untouched; its outside is empty.
            life.AdvanceSelection(0, 0, 7, 7, 5);
            plain.Step(5);
            Assert.Equal(plain.State.ToArray(), life.State.ToArray());
            byte[] before = life.State.ToArray();
            life.AdvanceOutside(0, 0, 7, 7, 9);
            Assert.Equal(before, life.State.ToArray());
            Assert.Equal(0, life.Generation);
        }

        // -- HashLife: paste and, generation, queries -------------------------------------------

        [Fact]
        public void PasteAndMatchesTheCells()
        {
            var u = new HashLife();
            u.SetRect(-37, -21, Noise(60, 80, 3), 80, 60);
            byte[] mirror = u.GetRect(-37, -21, 42, 38);
            for (int i = 0; i < 6; i++)
            {
                int h = 13 + 3 * i, w = 29 - 2 * i, px = 4 * i + 1, py = 5 * i + 2;
                byte[] piece = Noise(h, w, (uint)(20 + i));
                u.SetRect(-37 + px, -21 + py, piece, w, h, HashLifePasteMode.And);
                for (int r = 0; r < h; r++)
                    for (int c = 0; c < w; c++)
                        mirror[(py + r) * 80 + px + c] &= piece[r * w + c];
                Assert.Equal(mirror, u.GetRect(-37, -21, 42, 38));
            }
            Assert.Equal(mirror.Count(v => v != 0), (int)u.Population);
        }

        [Fact]
        public void SetGenerationMovesOnlyTheCounter()
        {
            var u = new HashLife();
            u.SetRect(0, 0, Glider, 3, 3);
            string text = u.ToMacrocell();
            BigInteger big = BigInteger.Pow(3, 300);
            u.SetGeneration(big);
            Assert.Equal(big, u.Generation);
            Assert.Equal(text, u.ToMacrocell().Replace($"#G {big}\n", ""));
            u.SetGeneration(0);
            Assert.Equal(text, u.ToMacrocell());
            Assert.Throws<ArgumentOutOfRangeException>(() => u.SetGeneration(-1));
        }

        [Fact]
        public void BoundingBoxInMatchesTheCells()
        {
            var u = new HashLife();
            byte[] a = Noise(70, 90, 4);
            u.SetRect(-45, -35, a, 90, 70);
            foreach (var (x0, y0, x1, y1) in new[]
            {
                (-45, -35, 44, 34), (-30, -10, 3, 7), (0, 0, 0, 0), (10, -35, 12, 34), (-100, -100, -46, 100),
                (44, -35, 200, 34),
            })
            {
                int bx0 = int.MaxValue, by0 = int.MaxValue, bx1 = int.MinValue, by1 = int.MinValue;
                for (int y = Math.Max(y0, -35); y <= Math.Min(y1, 34); y++)
                {
                    for (int x = Math.Max(x0, -45); x <= Math.Min(x1, 44); x++)
                    {
                        if (a[(y + 35) * 90 + x + 45] == 0)
                            continue;
                        bx0 = Math.Min(bx0, x);
                        by0 = Math.Min(by0, y);
                        bx1 = Math.Max(bx1, x);
                        by1 = Math.Max(by1, y);
                    }
                }
                CellBox? want = bx0 == int.MaxValue ? (CellBox?)null : new CellBox(bx0, by0, bx1, by1);
                Assert.Equal(want, u.BoundingBoxIn(x0, y0, x1, y1));
            }
            Assert.Null(u.BoundingBoxIn(5, 5, 4, 5));
            BigInteger far = BigInteger.Pow(10, 40);
            Assert.Equal(u.BoundingBox, u.BoundingBoxIn(-far, -far, far, far));
            // Past 64 bits: a glider 2^100 cells out.
            var g = new HashLife();
            g.SetRect(0, 0, Glider, 3, 3);
            BigInteger m = BigInteger.One << 100;
            g.Step(4 * m);
            Assert.Equal(new CellBox(m + 1, m, m + 1, m), g.BoundingBoxIn(m - 5, m - 5, m + 1, m + 1));
            Assert.Equal(new CellBox(m + 2, m + 1, m + 2, m + 2), g.BoundingBoxIn(m + 2, m, m + 2, m + 2));
            Assert.Equal(new CellBox(m, m + 1, m + 2, m + 2), g.BoundingBoxIn(m, m + 1, m + 2, m + 2));
            Assert.Null(g.BoundingBoxIn(0, 0, m - 1, m + 9));
        }

        // -- HashLife: clear outside, turns, and flips ------------------------------------------

        [Fact]
        public void ClearOutsideKeepsOnlyTheRectangle()
        {
            var u = new HashLife();
            byte[] a = Noise(50, 60, 5);
            u.SetRect(-30, -25, a, 60, 50);
            u.SetCell(Limit, Limit, true);
            u.ClearOutside(-10, -5, 12, 9);
            byte[] kept = new byte[15 * 23];
            for (int y = 0; y < 15; y++)
                Array.Copy(a, (y + 20) * 60 + 20, kept, y * 23, 23);
            Assert.Equal(kept, u.GetRect(-10, -5, 12, 9));
            Assert.Equal(kept.Count(v => v != 0), (int)u.Population);
            Assert.Throws<ArgumentException>(() => u.ClearOutside(3, 3, 2, 3));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.ClearOutside(0, 0, Limit + 1, 0));
        }

        /// <summary>The spec's maps applied cell by cell to a dense picture of [−frame, frame]².</summary>
        private static byte[] TurnedByHand(byte[] cells, int frame, long x0, long y0, long x1, long y1, string kind)
        {
            int side = 2 * frame + 1;
            byte[] result = (byte[])cells.Clone();
            for (long y = y0; y <= y1; y++)
                for (long x = x0; x <= x1; x++)
                    result[(y + frame) * side + x + frame] = 0;
            var (bigS, bigD) = Patterns.TurnCenter(x0, y0, x1, y1);
            long s = (long)bigS, d = (long)bigD;
            for (long y = y0; y <= y1; y++)
            {
                for (long x = x0; x <= x1; x++)
                {
                    (long tx, long ty) = kind switch
                    {
                        "cw" => (s - y, x + d),
                        "ccw" => (y - d, s - x),
                        "h" => (x0 + x1 - x, y),
                        _ => (x, y0 + y1 - y),
                    };
                    result[(ty + frame) * side + tx + frame] = cells[(y + frame) * side + x + frame];
                }
            }
            return result;
        }

        [Theory]
        [InlineData("cw")]
        [InlineData("ccw")]
        [InlineData("h")]
        [InlineData("v")]
        public void TurnsAndFlipsMatchTheMaps(string kind)
        {
            const int frame = 70;
            var sizes = new[] { (7, 4), (4, 7), (6, 6), (5, 8), (9, 2), (1, 1), (1, 6) };
            for (int i = 0; i < sizes.Length; i++)
            {
                var (w, h) = sizes[i];
                var u = new HashLife();
                u.SetRect(-40, -38, Noise(76, 80, (uint)(30 + i)), 80, 76);
                long x0 = (-9 + 5 * i) * (i % 2 == 1 ? 1 : -1), y0 = 3 - 4 * i;
                long x1 = x0 + w - 1, y1 = y0 + h - 1;
                byte[] before = u.GetRect(-frame, -frame, frame, frame);
                if (kind == "cw" || kind == "ccw")
                {
                    CellBox moved = u.RotateRect(x0, y0, x1, y1, kind == "cw");
                    Assert.Equal(h, (int)(moved.X1 - moved.X0 + 1));
                    Assert.Equal(w, (int)(moved.Y1 - moved.Y0 + 1));
                }
                else
                {
                    u.FlipRect(x0, y0, x1, y1, kind == "h");
                }
                Assert.Equal(TurnedByHand(before, frame, x0, y0, x1, y1, kind), u.GetRect(-frame, -frame, frame, frame));
            }
        }

        [Theory]
        [InlineData(0, 0, 1, 0, 0, 0, 0, 1, 0, -1, 0, 0)]
        [InlineData(1, 0, 2, 0, 2, -1, 2, 0, 2, 0, 2, 1)]
        [InlineData(0, 0, 2, 0, 1, -1, 1, 1, 1, -1, 1, 1)]
        [InlineData(0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1)]
        [InlineData(-3, -2, -2, 0, -4, -1, -2, 0, -4, -2, -2, -1)]
        [InlineData(-2, -3, 0, -2, -2, -4, -1, -2, -1, -4, 0, -2)]
        public void TurnedRectangles(
            long x0, long y0, long x1, long y1, long cx0, long cy0, long cx1, long cy1, long ax0, long ay0, long ax1, long ay1)
        {
            Assert.Equal(new CellBox(cx0, cy0, cx1, cy1), new HashLife().RotateRect(x0, y0, x1, y1));
            Assert.Equal(new CellBox(ax0, ay0, ax1, ay1), new HashLife().RotateRect(x0, y0, x1, y1, clockwise: false));
        }

        [Fact]
        public void TurnsUndoEachOtherAndNeverDrift()
        {
            var sizes = new[] { (3, 2), (2, 3), (5, 2), (4, 4), (1, 4), (6, 3) };
            for (int i = 0; i < sizes.Length; i++)
            {
                var (w, h) = sizes[i];
                foreach (var (x0, y0) in new[] { (0L, 0L), (1L, 0L), (0L, 1L), (-3L, 7L), (11L, -4L) })
                {
                    var u = new HashLife();
                    u.SetRect(x0 - 3, y0 - 3, Noise(h + 6, w + 6, (uint)(50 + i)), w + 6, h + 6);
                    long x1 = x0 + w - 1, y1 = y0 + h - 1;
                    byte[] cells = u.GetRect(x0, y0, x1, y1);
                    CellBox turned = u.RotateRect(x0, y0, x1, y1);
                    CellBox back = u.RotateRect((long)turned.X0, (long)turned.Y0, (long)turned.X1, (long)turned.Y1, false);
                    Assert.Equal(new CellBox(x0, y0, x1, y1), back);
                    CellBox r = back;
                    for (int t = 0; t < 4; t++)
                        r = u.RotateRect((long)r.X0, (long)r.Y0, (long)r.X1, (long)r.Y1);
                    Assert.Equal(back, r);
                    u.FlipRect(x0, y0, x1, y1);
                    u.FlipRect(x0, y0, x1, y1);
                    u.FlipRect(x0, y0, x1, y1, horizontal: false);
                    u.FlipRect(x0, y0, x1, y1, horizontal: false);
                    Assert.Equal(cells, u.GetRect(x0, y0, x1, y1));
                }
            }
        }

        [Fact]
        public void TransformsReachAnySizeAndStopAtTheBox()
        {
            var (gun, gw, gh) = Builtin("Gosper glider gun"); // 36 × 9
            var u = new HashLife();
            foreach (var (x, y) in new[] { (-999_999_000L, -999_999_000L), (999_990_000L, 3L), (5L, 999_999_000L), (-7L, -7L) })
                u.SetRect(x, y, gun, gw, gh);
            BigInteger population = u.Population;
            var clock = Stopwatch.StartNew();
            // X = 0, Y = −1: s = 0, d = 0, so a clockwise turn sends (x, y) to (−y, x).
            Assert.Equal(new CellBox(-Limit + 1, -Limit, Limit, Limit), u.RotateRect(-Limit, -Limit, Limit, Limit - 1));
            u.FlipRect(-Limit, -Limit, Limit, Limit, horizontal: false);
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(10)); // the tree, never a dense copy
            Assert.Equal(population, u.Population);
            // The gun at (−7, −7) went to (−x, −y) of where it was: turned, then mirrored.
            var turned = new HashLife();
            turned.SetRect(-1, -28, Patterns.FlipV(Patterns.Rotate90(gun, gw, gh), gh, gw), gh, gw);
            Assert.Equal(turned.GetRect(-50, -50, 50, 50), u.GetRect(-50, -50, 50, 50));
            string text = u.ToMacrocell();
            Assert.Throws<ArgumentOutOfRangeException>(() => u.RotateRect(Limit - 9, 0, Limit, 100));
            Assert.Throws<ArgumentException>(() => u.FlipRect(4, 4, 3, 4));
            Assert.Equal(text, u.ToMacrocell());
            var mirror = new HashLife();
            mirror.SetRect(-1, -1, gun, gw, gh);
            mirror.FlipRect(-1, -1, 34, 7);
            Assert.Equal(Patterns.FlipH(gun, gw, gh), mirror.GetRect(-1, -1, 34, 7));
        }

        // -- HashLife: Advance Selection and Advance Outside ------------------------------------

        [Theory]
        [InlineData("B3/S23")]
        [InlineData("B36/S23")]
        [InlineData("B2/S")]
        public void AdvanceSelectionIsAnIsolatedPlane(string rule)
        {
            const int frame = 80, side = 2 * frame + 1;
            var u = new HashLife(rule);
            u.SetRect(-20, -20, Noise(41, 41, (uint)(60 + rule.Length)), 41, 41);
            byte[] before = u.GetRect(-frame, -frame, frame, frame);
            const long x0 = -14, y0 = -18, x1 = 9, y1 = 5;
            u.SetGeneration(5);
            u.AdvanceSelection(x0, y0, x1, y1, 13);
            Assert.Equal(5, (int)u.Generation);
            // The plane, as a dead-edged grid the pattern never reaches.
            var isolated = new byte[side * side];
            for (long y = y0; y <= y1; y++)
                for (long x = x0; x <= x1; x++)
                    isolated[(y + frame) * side + x + frame] = before[(y + frame) * side + x + frame];
            var grid = new LifeLike(rule, side, side, Boundary.Dead);
            grid.SetState(isolated);
            grid.Step(13);
            byte[] want = (byte[])before.Clone();
            ReadOnlySpan<byte> grown = grid.State;
            for (long y = y0; y <= y1; y++)
                for (long x = x0; x <= x1; x++)
                    want[(y + frame) * side + x + frame] = grown[(int)((y + frame) * side + x + frame)];
            Assert.Equal(want, u.GetRect(-frame, -frame, frame, frame));
        }

        [Fact]
        public void AdvanceJumpsLikeStep()
        {
            var (gun, gw, gh) = Builtin("Gosper glider gun");
            var u = new HashLife();
            u.SetRect(0, 0, gun, gw, gh);
            u.SetRect(500, 500, new byte[] { 1, 1, 1, 1 }, 2, 2);
            var alone = new HashLife();
            alone.SetRect(0, 0, gun, gw, gh);
            alone.Step(BigInteger.One << 40);
            u.AdvanceSelection(-5, -5, 40, 15, BigInteger.One << 40);
            Assert.Equal(alone.GetRect(-5, -5, 40, 15), u.GetRect(-5, -5, 40, 15));
            Assert.Equal(4, (int)u.PopulationIn(490, 490, 510, 510));
            Assert.Equal(0, (int)u.Generation);
            // Outside: the gun fires on as if the frozen rectangle were empty.
            var v = new HashLife();
            v.SetRect(0, 0, gun, gw, gh);
            v.SetRect(100, 100, new byte[] { 1, 1, 1, 1 }, 2, 2);
            v.SetCell(103, 100, true); // a lone cell that would die if advanced
            v.AdvanceOutside(99, 99, 104, 102, 1000);
            Assert.Equal(5, (int)v.PopulationIn(99, 99, 104, 102));
            Assert.True(v.GetCell(103, 100));
            var fired = new HashLife();
            fired.SetRect(0, 0, gun, gw, gh);
            fired.Step(1000);
            Assert.Equal(fired.GetRect(-10, -10, 90, 90), v.GetRect(-10, -10, 90, 90));
        }

        [Fact]
        public void AdvanceRefusalsChangeNothing()
        {
            var (gun, gw, gh) = Builtin("Gosper glider gun");
            var u = new HashLife();
            u.SetRect(0, 0, gun, gw, gh);
            u.Step(77);
            string before = u.ToMacrocell();
            Assert.Throws<ArgumentOutOfRangeException>(() => u.AdvanceSelection(0, 0, 10, 10, BigInteger.One << 510));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.AdvanceOutside(0, 0, 10, 10, -1));
            Assert.Throws<ArgumentOutOfRangeException>(() => u.AdvanceSelection(0, 0, Limit + 1, 10, 1));
            Assert.Throws<ArgumentException>(() => u.AdvanceOutside(5, 5, 4, 5, 1));
            Assert.Equal(before, u.ToMacrocell());
            Assert.Equal(77, (int)u.Generation);
        }

        [Fact]
        public void AdvanceOutOfMemoryLeavesTheUniverse()
        {
            var u = new HashLife(maxMemoryMb: 10);
            u.FillRandom(0, 0, 2999, 2999, 0.5, 9); // most of the floor budget
            string before = u.ToMacrocell();
            Assert.Throws<HashLifeMemoryException>(() => u.AdvanceOutside(10, 10, 20, 20, 1));
            Assert.Equal(before, u.ToMacrocell());
            Assert.Equal(0, (int)u.Generation);
        }

        [Fact]
        public void AdvanceCanceledLeavesTheUniverse()
        {
            var u = new HashLife();
            u.SetRect(0, 0, Noise(256, 256, 2), 256, 256);
            string before = u.ToMacrocell();
            using var cts = new CancellationTokenSource();
            long nodes = u.NodeCount;
            var watcher = new Thread(() =>
            {
                while (!cts.IsCancellationRequested)
                {
                    if (u.NodeCount > nodes + 400_000)
                        cts.Cancel();
                    else
                        Thread.Sleep(1);
                }
            });
            watcher.Start();
            try
            {
                Assert.Throws<OperationCanceledException>(
                    () => u.AdvanceOutside(100, 100, 120, 120, (1 << 20) + 1, cts.Token));
            }
            finally
            {
                cts.Cancel();
                watcher.Join();
            }
            Assert.Equal(before, u.ToMacrocell()); // not a sub-step boundary: as it was
            Assert.Equal(0, (int)u.Generation);
        }


        [Fact]
        public void TurnedRectIsWhereRotateRectsCellsLand()
        {
            // spec/patterns.md "Editing a region": a rectangle's four corner cells, moved by the
            // tree's own shift (not by TurnedRect), land on the corners of TurnedRect's rectangle.
            for (long x0 = -3; x0 < 3; x0++)
            {
                for (long y0 = -3; y0 < 3; y0++)
                {
                    for (int w = 1; w <= 5; w++)
                    {
                        for (int h = 1; h <= 5; h++)
                        {
                            long x1 = x0 + w - 1, y1 = y0 + h - 1;
                            foreach (bool clockwise in new[] { true, false })
                            {
                                var u = new HashLife();
                                foreach (long x in new[] { x0, x1 })
                                {
                                    foreach (long y in new[] { y0, y1 })
                                        u.SetCell(x, y, true);
                                }
                                u.RotateRect(x0, y0, x1, y1, clockwise);
                                Assert.Equal((CellBox?)Patterns.TurnedRect(x0, y0, x1, y1, clockwise), u.BoundingBox);
                            }
                        }
                    }
                }
            }
        }

        [Fact]
        public void AGridTurnsARegionOntoRotateRectsCells()
        {
            // Extract, Rotate90 (or Rotate90Ccw), clear, then stamp at TurnedRect's top-left: a
            // life-like grid's turn of a region gives the cells HashLife.RotateRect gives.
            const int size = 24;
            var rng = new Pcg32(2611); // test input only
            int turns = 0;
            for (int trial = 0; trial < 80; trial++)
            {
                byte[] grid = Noise(size, size, (uint)(100 + trial));
                int w = 1 + (int)(rng.NextU32() % 9), h = 1 + (int)(rng.NextU32() % 9);
                int x0 = (int)(rng.NextU32() % (uint)(size - w + 1)), y0 = (int)(rng.NextU32() % (uint)(size - h + 1));
                int x1 = x0 + w - 1, y1 = y0 + h - 1;
                bool clockwise = trial % 2 == 0;
                CellBox target = Patterns.TurnedRect(x0, y0, x1, y1, clockwise);
                if (target.X0 < 0 || target.Y0 < 0 || target.X1 >= size || target.Y1 >= size)
                    continue; // past an edge: the caller's to refuse
                byte[] turned = (byte[])grid.Clone();
                byte[] region = Patterns.Extract(turned, size, size, 1, x0, y0, w, h, torus: false);
                for (int y = y0; y <= y1; y++)
                {
                    for (int x = x0; x <= x1; x++)
                        turned[y * size + x] = 0;
                }
                byte[] rotated = clockwise ? Patterns.Rotate90(region, w, h) : Patterns.Rotate90Ccw(region, w, h);
                Patterns.Stamp(turned, size, size, 1, rotated, h, w, (int)target.X0, (int)target.Y0, false, StampMode.Copy);
                var u = new HashLife();
                u.SetRect(0, 0, grid, size, size, HashLifePasteMode.Copy);
                Assert.Equal(target, u.RotateRect(x0, y0, x1, y1, clockwise));
                Assert.Equal(turned, u.GetRect(0, 0, size - 1, size - 1));
                turns++;
            }
            Assert.True(turns > 50, $"only {turns} turns stayed in the grid");
        }

        [Fact]
        public void TurnedRectNeedsARectangleAndTakesAnyIntegers()
        {
            Assert.Throws<ArgumentException>(() => Patterns.TurnedRect(0, 0, -1, 0));
            Assert.Throws<ArgumentException>(() => Patterns.TurnedRect(0, 1, 0, 0, clockwise: false));
            Assert.Equal(new CellBox(7, 7, 7, 7), Patterns.TurnedRect(7, 7, 7, 7));
            BigInteger big = BigInteger.One << 100;
            var rect = new CellBox(big, -big, big + 3, -big + 1);
            CellBox turned = Patterns.TurnedRect(rect);
            Assert.Equal(rect, Patterns.TurnedRect(turned, clockwise: false));
            CellBox spun = rect;
            for (int i = 0; i < 4; i++)
                spun = Patterns.TurnedRect(spun);
            Assert.Equal(rect, spun);
        }
    }
}
