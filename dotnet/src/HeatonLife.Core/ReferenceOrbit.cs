using System;
using System.Collections.Generic;
using System.Numerics;
using System.Threading;

namespace HeatonLife
{
    /// <summary>
    /// High-precision reference orbits for the perturbation tier
    /// (spec/deep-zoom.md). The only bignum computation in the fractal pipeline:
    /// one orbit of the viewport center, so a T1 render needs no externally
    /// supplied data.
    ///
    /// The arithmetic is spec'd, not just the result: binary fixed point over
    /// System.Numerics.BigInteger with <see cref="WorkingBits"/> fractional bits,
    /// decimal parsing and products rounded to nearest with ties away from zero, and
    /// each sample converted to float64 by one correct rounding. The Python reference
    /// (core/bignum.py) runs the same integer operations, so the two orbits agree
    /// bit for bit at any length. Until 2026-09-23 Python iterated in binary
    /// FLOATING point instead; the two agreed only while rounding differences stayed
    /// below a double ulp, which a chaotic orbit outgrows within ~40 iterations
    /// (the deep Julia vector parted at sample 38, a 256-digit center at 67,941).
    ///
    /// <c>ReferenceOrbitTests</c> regenerates the shipped orbit vectors and requires
    /// them byte for byte.
    /// </summary>
    public static class ReferenceOrbit
    {
        /// <summary>Extra bits below the working precision (spec/deep-zoom.md).</summary>
        public const int GuardBits = 64;

        /// <summary>
        /// Stop the reference once it is unambiguously escaping. Mirrors the Python
        /// reference's <c>_ESCAPE_ABS2</c>: |Z|^2 &gt; 1e100 means every pixel that
        /// reaches this sample has already escaped at any sane radius, and it keeps
        /// the value inside float64's range. A short orbit is expected, not an
        /// error — both ports clamp the reference index to the last sample.
        /// </summary>
        public const double EscapeAbs2 = 1e100;

        /// <summary>
        /// Bits needed to resolve a frame at 10^zoom magnification, plus guard — the
        /// zoom term of <see cref="WorkingBits"/>. NOTE the truncation:
        /// <c>(int)(3.33 * zoom)</c>, matching the Python reference's <c>int(3.33 * ...)</c>
        /// (46 bits at zoom 14, not 47). The spec once said ceil; the shipped vectors
        /// were produced by the truncating form and the vectors are the contract. Do
        /// not "fix" this to Ceiling without regenerating every deep-zoom vector.
        /// </summary>
        public static int PrecisionBits(double zoomLog10) =>
            (int)(3.33 * Math.Max(zoomLog10, 0.0)) + GuardBits;

        /// <summary>
        /// Fractional bits the fixed point carries beyond the precision rule. Fixed
        /// point measures precision from the binary point, a float from the leading
        /// digit, so a value below 1 gets fewer significant bits than its nominal
        /// precision; the headroom keeps every sample a correctly rounded double
        /// (a center of ~0.13 at 110 fractional bits came out one ulp off in Z[1]).
        /// </summary>
        internal const int WorkingGuardBits = 64;

        /// <summary>
        /// Center digits past 10^-340 sit below half the smallest float64 subnormal: they
        /// cannot reach a sample, so the digit term of <see cref="WorkingBits"/> stops
        /// there and a long string cannot set the precision on its own.
        /// </summary>
        public const int MaxDigitPlaces = 340;

        /// <summary>Bit length of 10^p for p = 0..MaxDigitPlaces, so a frame never builds 10^p.</summary>
        private static readonly int[] DigitBits = BuildDigitBits();

        private static int[] BuildDigitBits()
        {
            var table = new int[MaxDigitPlaces + 1];
            BigInteger power = BigInteger.One;
            for (int p = 0; p <= MaxDigitPlaces; p++)
            {
                table[p] = DecimalText.BitLength(power);
                power *= 10;
            }
            return table;
        }

        /// <summary>
        /// Fractional bits F of the fixed-point orbit (spec/deep-zoom.md "Precision"):
        /// the frame's need (<see cref="PrecisionBits"/>) or the center's own digits (at
        /// most <see cref="MaxDigitPlaces"/> of them), whichever is finer, plus
        /// <see cref="WorkingGuardBits"/>. The digits term
        /// keeps a long or tiny center intact — without it a component of 1e-310 at
        /// zoom 280 would keep ~30 significant bits.
        /// </summary>
        public static int WorkingBits(string centerRe, string centerIm, double zoomLog10)
        {
            int places = Math.Min(Math.Max(DecimalPlaces(centerRe), DecimalPlaces(centerIm)), MaxDigitPlaces);
            return Math.Max(PrecisionBits(zoomLog10), DigitBits[places]) + WorkingGuardBits;
        }

        /// <summary>Z0..ZK for Z -&gt; Z^2 + C with Z0 = 0 and C = the center.</summary>
        public static (double[] Re, double[] Im) Mandelbrot(
            string centerRe, string centerIm, double zoomLog10, int maxIter) =>
            Compute(Kind.Mandelbrot, centerRe, centerIm, zoomLog10, maxIter, 0.0, 0.0);

        /// <summary>
        /// Z0..ZK for Z -&gt; Z^2 + c with Z0 = the center and c fixed
        /// (spec/fractals.md: Julia's reference uses the center's orbit under the
        /// same c, and its delta carries no dc term). <paramref name="zoomLog10"/> sets the
        /// precision: a Julia frame's orbits run at twice its zoom (spec/deep-zoom.md
        /// "Reference orbit"), so pass <c>2 · viewport.ZoomLog10</c> for a frame's orbit.
        /// </summary>
        public static (double[] Re, double[] Im) Julia(
            string centerRe, string centerIm, double zoomLog10, int maxIter, double cRe, double cIm) =>
            Compute(Kind.Julia, centerRe, centerIm, zoomLog10, maxIter, cRe, cIm);

        /// <summary>
        /// W0..WK for W -&gt; W^2 + c with W0 = 0: the Julia critical orbit, which a
        /// rebased Julia pixel restarts on (spec/deep-zoom.md "Rebasing"). Exactly
        /// <see cref="Julia(string,string,double,int,double,double)"/> at center "0",
        /// so it shares that method's precision (set by the zoom: twice the frame's) and cache.
        /// </summary>
        public static (double[] Re, double[] Im) JuliaCritical(
            double cRe, double cIm, double zoomLog10, int maxIter) =>
            Compute(Kind.Julia, "0", "0", zoomLog10, maxIter, cRe, cIm);

        /// <summary>Z0..ZK for the Burning Ship map, |x| and |y| taken each step.</summary>
        public static (double[] Re, double[] Im) BurningShip(
            string centerRe, string centerIm, double zoomLog10, int maxIter) =>
            Compute(Kind.BurningShip, centerRe, centerIm, zoomLog10, maxIter, 0.0, 0.0);

        internal enum Kind
        {
            Mandelbrot,
            Julia,
            BurningShip,
        }

        // The orbit depends on (kind, center, F, c) and on max_iter only through where it
        // stops, so the cache keys on the first four (spec/deep-zoom.md "Caching &
        // interactivity"). A cached orbit serves any shorter request as a prefix, and a
        // longer one by resuming from the exact fixed-point state it kept — both
        // identical to computing afresh, since the recurrence is deterministic and
        // max_iter only says when to stop. That is what makes an auto-iteration ladder
        // cheap. Least-recently-used eviction under both an entry cap (the Python
        // reference's 8) and a byte cap: a Julia render hits its critical orbit every
        // frame, and a phone cannot hold 8 long orbits.
        private const int CacheCapacity = 8;
        private static readonly object CacheLock = new object();

        // Set on this thread inside Uncached(): orbits are computed afresh and never stored,
        // so a caller that must not disturb the cache (the platform self-check) leaves a
        // host's cached orbits in place.
        [ThreadStatic]
        private static bool _uncached;

        /// <summary>
        /// Until the returned scope is disposed, every orbit this thread asks for is computed
        /// afresh and not cached: the same arithmetic, the cache neither read nor written.
        /// </summary>
        internal static UncachedScope Uncached()
        {
            bool previous = _uncached;
            _uncached = true;
            return new UncachedScope(previous);
        }

        /// <summary>Restores the thread's caching when disposed.</summary>
        internal readonly struct UncachedScope : IDisposable
        {
            private readonly bool _previous;

            internal UncachedScope(bool previous)
            {
                _previous = previous;
            }

            public void Dispose() => _uncached = _previous;
        }
        private static readonly List<Key> CacheOrder = new List<Key>();
        private static readonly Dictionary<Key, Entry> Cache = new Dictionary<Key, Entry>();
        private static long _cacheByteLimit = 64L << 20;

        /// <summary>Orbits the cache keeps whatever its byte cap: the two a Julia frame needs.</summary>
        private const int KeepRecent = 2;

        /// <summary>How often (in iterations) a running orbit polls for cancellation and reports progress, up to 1024 bits.</summary>
        internal const int PollInterval = 4096;

        /// <summary>
        /// The poll interval for an orbit at <paramref name="bits"/>: PollInterval up to 1024
        /// bits, then halved while the work between polls (iterations × bits², a step's
        /// multiplies) exceeds PollInterval steps at 1024 bits — every 4 iterations at zoom
        /// 9000's ~30,000 bits, every one at a Julia frame's ~60,000, so a cancel lands
        /// promptly at any depth.
        /// </summary>
        internal static int PollIntervalFor(int bits)
        {
            long work = (long)bits * bits;
            long budget = PollInterval * 1024L * 1024L;
            int interval = PollInterval;
            while (interval > 1 && interval * work > budget)
                interval >>= 1;
            return interval;
        }

        /// <summary>
        /// Most bytes of orbit samples the cache holds (16 per sample; default 64 MB).
        /// Least recently used orbits go first; the two most recent always stay, even over
        /// the limit (a Julia frame needs both of its orbits). 0 keeps only those two.
        /// </summary>
        public static long CacheByteLimit
        {
            get { lock (CacheLock) return _cacheByteLimit; }
            set
            {
                if (value < 0)
                    throw new ArgumentOutOfRangeException(nameof(value), "the byte limit cannot be negative");
                lock (CacheLock)
                {
                    _cacheByteLimit = value;
                    Evict();
                }
            }
        }

        /// <summary>
        /// What an orbit depends on — (kind, center, F, c) — compared by value without
        /// building a string per lookup.
        /// </summary>
        private readonly struct Key : IEquatable<Key>
        {
            internal Key(Kind kind, string re, string im, int bits, double cRe, double cIm)
            {
                KindOf = kind;
                Re = re;
                Im = im;
                Bits = bits;
                CRe = BitConverter.DoubleToInt64Bits(cRe);
                CIm = BitConverter.DoubleToInt64Bits(cIm);
            }

            private Kind KindOf { get; }
            private string Re { get; }
            private string Im { get; }
            private int Bits { get; }
            private long CRe { get; }
            private long CIm { get; }

            public bool Equals(Key other) =>
                KindOf == other.KindOf && Bits == other.Bits && CRe == other.CRe && CIm == other.CIm
                && string.Equals(Re, other.Re, StringComparison.Ordinal)
                && string.Equals(Im, other.Im, StringComparison.Ordinal);

            public override bool Equals(object? obj) => obj is Key other && Equals(other);

            public override int GetHashCode() => HashCode.Combine(KindOf, Re, Im, Bits, CRe, CIm);
        }

        /// <summary>A sample is small when binade(max(|Re|, |Im|)) is below this (or it is 0).</summary>
        internal const int SmallBinade = -400;

        /// <summary>... or above this: a huge Julia center, whose doubles T2 could overflow.</summary>
        internal const int LargeBinade = 900;

        /// <summary>
        /// An orbit's small samples in floatexp (spec/deep-zoom.md "T2"): the indices where
        /// Z = 0 or binade(max(|Re Z|, |Im Z|)) &lt; −400, and each component there rounded once
        /// from the fixed point — the values T2 steps through exactly.
        /// </summary>
        internal sealed class SmallSamples
        {
            internal static readonly SmallSamples Empty = new SmallSamples(new int[0], new FloatExp[0], new FloatExp[0]);

            internal SmallSamples(int[] index, FloatExp[] re, FloatExp[] im)
            {
                Index = index;
                Re = re;
                Im = im;
            }

            internal int[] Index { get; }
            internal FloatExp[] Re { get; }
            internal FloatExp[] Im { get; }

            /// <summary>The entries with an index below <paramref name="length"/>.</summary>
            internal SmallSamples Prefix(int length)
            {
                int keep = 0;
                while (keep < Index.Length && Index[keep] < length)
                    keep++;
                if (keep == Index.Length)
                    return this;
                var index = new int[keep];
                var re = new FloatExp[keep];
                var im = new FloatExp[keep];
                Array.Copy(Index, index, keep);
                Array.Copy(Re, re, keep);
                Array.Copy(Im, im, keep);
                return new SmallSamples(index, re, im);
            }
        }

        /// <summary>Accumulates small samples as an orbit runs.</summary>
        private sealed class SmallBuilder
        {
            private readonly List<int> _index = new List<int>();
            private readonly List<FloatExp> _re = new List<FloatExp>(), _im = new List<FloatExp>();

            internal SmallBuilder(SmallSamples? start)
            {
                if (start == null)
                    return;
                _index.AddRange(start.Index);
                _re.AddRange(start.Re);
                _im.AddRange(start.Im);
            }

            internal void Add(int index, BigInteger zr, BigInteger zi, int bits)
            {
                _index.Add(index);
                _re.Add(FloatExp.FromFixed(zr, bits));
                _im.Add(FloatExp.FromFixed(zi, bits));
            }

            internal SmallSamples Build() => new SmallSamples(_index.ToArray(), _re.ToArray(), _im.ToArray());
        }

        /// <summary>Z = 0, or binade(max(|Re|, |Im|)) &lt; −400, from the exact fixed point.</summary>
        private static bool IsSmall(BigInteger zr, BigInteger zi, int bits)
        {
            int top = Math.Max(DecimalText.BitLength(BigInteger.Abs(zr)), DecimalText.BitLength(BigInteger.Abs(zi)));
            return top == 0 || top - 1 - bits < SmallBinade || top - 1 - bits > LargeBinade;
        }

        /// <summary>A cached orbit: its samples, its small samples, and the exact state to resume from.</summary>
        private sealed class Entry
        {
            internal Entry(
                double[] re, double[] im, bool escaped, BigInteger zr, BigInteger zi, BigInteger cr, BigInteger ci,
                SmallSamples small)
            {
                Re = re;
                Im = im;
                Escaped = escaped;
                Zr = zr;
                Zi = zi;
                Cr = cr;
                Ci = ci;
                Small = small;
            }

            internal double[] Re { get; }
            internal double[] Im { get; }

            /// <summary>The small samples in floatexp (T2).</summary>
            internal SmallSamples Small { get; }

            /// <summary>The last sample tripped the stopping rule: longer requests get the same orbit.</summary>
            internal bool Escaped { get; }

            /// <summary>The fixed-point Z at the last sample, and C, to resume from.</summary>
            internal BigInteger Zr { get; }
            internal BigInteger Zi { get; }
            internal BigInteger Cr { get; }
            internal BigInteger Ci { get; }

            internal long Bytes => Re.Length * 16L + Small.Index.Length * 40L;

            /// <summary>Whether this orbit answers a request for <paramref name="maxIter"/> without iterating.</summary>
            internal bool Covers(int maxIter) => Escaped || Re.Length - 1 >= maxIter;
        }

        /// <summary>
        /// The orbit for <paramref name="maxIter"/>, from the cache when it can be. With
        /// <paramref name="whole"/>, a longer cached orbit comes back as it is, uncopied:
        /// the renderers use that, because the perturbation loop's index advances by at
        /// most one per iteration (m &lt;= it &lt;= maxIter), so samples past maxIter are
        /// never read and a longer orbit renders bit-identically. Otherwise exactly
        /// min(length, maxIter + 1) samples, copied outside the lock when they are fewer.
        /// </summary>
        internal static (double[] Re, double[] Im) Compute(
            Kind kind, string centerRe, string centerIm, double zoomLog10, int maxIter,
            double cRe, double cIm, RenderProgress? progress = null, CancellationToken cancellationToken = default,
            bool whole = false)
        {
            var entry = ComputeEntry(kind, centerRe, centerIm, zoomLog10, maxIter, cRe, cIm, progress, cancellationToken);
            return whole ? (entry.Re, entry.Im) : Prefix(entry, maxIter);
        }

        /// <summary>
        /// The orbit for T2 (spec/deep-zoom.md "T2"): its samples (the whole cached orbit, as
        /// <see cref="Compute"/> with whole: true gives them) and its small samples in floatexp.
        /// </summary>
        internal static (double[] Re, double[] Im, SmallSamples Small) ComputeX(
            Kind kind, string centerRe, string centerIm, double zoomLog10, int maxIter,
            double cRe, double cIm, RenderProgress? progress = null, CancellationToken cancellationToken = default)
        {
            var entry = ComputeEntry(kind, centerRe, centerIm, zoomLog10, maxIter, cRe, cIm, progress, cancellationToken);
            return (entry.Re, entry.Im, entry.Small);
        }

        private static Entry ComputeEntry(
            Kind kind, string centerRe, string centerIm, double zoomLog10, int maxIter,
            double cRe, double cIm, RenderProgress? progress, CancellationToken cancellationToken)
        {
            if (centerRe == null)
                throw new ArgumentNullException(nameof(centerRe));
            if (centerIm == null)
                throw new ArgumentNullException(nameof(centerIm));
            if (maxIter < 1)
                throw new ArgumentOutOfRangeException(nameof(maxIter), "max_iter must be positive");

            int bits = WorkingBits(centerRe, centerIm, zoomLog10);
            if (_uncached)
                return Fresh(kind, centerRe, centerIm, bits, maxIter, cRe, cIm, progress, cancellationToken);
            var key = new Key(kind, centerRe, centerIm, bits, cRe, cIm);
            Entry? start = null;
            lock (CacheLock)
            {
                if (Cache.TryGetValue(key, out var hit))
                {
                    Touch(key);
                    start = hit;
                }
            }
            if (start != null && start.Covers(maxIter))
                return start;

            // A canceled run throws out of here, so nothing partial is ever cached.
            Entry computed = start == null
                ? Fresh(kind, centerRe, centerIm, bits, maxIter, cRe, cIm, progress, cancellationToken)
                : Resume(kind, start, bits, maxIter, progress, cancellationToken);

            lock (CacheLock)
            {
                if (!Cache.TryGetValue(key, out var existing) || existing.Re.Length < computed.Re.Length)
                    Cache[key] = computed;                     // else another thread stored a longer one
                Touch(key);
                Evict();
            }
            return computed;
        }

        /// <summary>
        /// The first min(length, maxIter + 1) samples. The cached arrays themselves when
        /// that is all of them — callers share them and must not write to them, as before.
        /// Cached arrays never change once stored (a resume builds a new entry), so the
        /// copy needs no lock.
        /// </summary>
        private static (double[] Re, double[] Im) Prefix(Entry entry, int maxIter)
        {
            int n = Math.Min(entry.Re.Length, maxIter + 1);
            if (n == entry.Re.Length)
                return (entry.Re, entry.Im);
            var re = new double[n];
            var im = new double[n];
            Array.Copy(entry.Re, re, n);
            Array.Copy(entry.Im, im, n);
            return (re, im);
        }

        /// <summary>Mark a cached key most recently used. Caller holds CacheLock.</summary>
        private static void Touch(Key key)
        {
            CacheOrder.Remove(key);
            CacheOrder.Add(key);
        }

        /// <summary>
        /// Drop least recently used orbits until the entry and byte caps hold, keeping the
        /// two most recent regardless: a Julia frame uses two orbits (its center's and the
        /// critical orbit), and a cap between one orbit and two must not make them evict
        /// each other every frame. Caller holds CacheLock.
        /// </summary>
        private static void Evict()
        {
            long bytes = 0;
            foreach (var entry in Cache.Values)
                bytes += entry.Bytes;
            while (CacheOrder.Count > KeepRecent && (CacheOrder.Count > CacheCapacity || bytes > _cacheByteLimit))
            {
                var oldest = CacheOrder[0];
                bytes -= Cache[oldest].Bytes;
                Cache.Remove(oldest);
                CacheOrder.RemoveAt(0);
            }
        }

        /// <summary>Drop every cached orbit (tests; a host reclaiming memory).</summary>
        public static void ClearCache()
        {
            lock (CacheLock)
            {
                Cache.Clear();
                CacheOrder.Clear();
            }
        }

        /// <summary>Whether this orbit is in the cache (tests).</summary>
        internal static bool IsCached(Kind kind, string centerRe, string centerIm, double zoomLog10, double cRe, double cIm)
        {
            var key = new Key(kind, centerRe, centerIm, WorkingBits(centerRe, centerIm, zoomLog10), cRe, cIm);
            lock (CacheLock)
                return Cache.ContainsKey(key);
        }

        /// <summary>Cached orbits and their sample bytes (tests).</summary>
        internal static (int Count, long Bytes) CacheUsage
        {
            get
            {
                lock (CacheLock)
                {
                    long bytes = 0;
                    foreach (var entry in Cache.Values)
                        bytes += entry.Bytes;
                    return (Cache.Count, bytes);
                }
            }
        }

        /// <summary>
        /// Tests: one orbit computed afresh, bypassing the cache, on the fixed-width path
        /// (where it fits) or on the BigInteger path — the fixed-width path's oracle.
        /// </summary>
        internal static (double[] Re, double[] Im) ComputeUncached(
            Kind kind, string centerRe, string centerIm, double zoomLog10, int maxIter,
            double cRe, double cIm, bool bigInteger)
        {
            int bits = WorkingBits(centerRe, centerIm, zoomLog10);
            var entry = Fresh(kind, centerRe, centerIm, bits, maxIter, cRe, cIm, null, CancellationToken.None, bigInteger);
            return (entry.Re, entry.Im);
        }

        /// <summary>Tests: <see cref="ComputeUncached"/>'s small samples, on either path.</summary>
        internal static SmallSamples ComputeUncachedSmall(
            Kind kind, string centerRe, string centerIm, double zoomLog10, int maxIter,
            double cRe, double cIm, bool bigInteger)
        {
            int bits = WorkingBits(centerRe, centerIm, zoomLog10);
            return Fresh(kind, centerRe, centerIm, bits, maxIter, cRe, cIm, null, CancellationToken.None, bigInteger).Small;
        }

        private static Entry Fresh(
            Kind kind, string centerRe, string centerIm, int bits, int maxIter,
            double cRe, double cIm, RenderProgress? progress, CancellationToken cancellationToken,
            bool bigInteger = false)
        {
            BigInteger centerR = ParseFixed(centerRe, bits);
            BigInteger centerI = ParseFixed(centerIm, bits);
            BigInteger zr, zi, cr, ci;
            if (kind == Kind.Julia)
            {
                zr = centerR;
                zi = centerI;
                cr = FromDouble(cRe, bits);
                ci = FromDouble(cIm, bits);
            }
            else
            {
                zr = BigInteger.Zero;
                zi = BigInteger.Zero;
                cr = centerR;
                ci = centerI;
            }
            // orbit[0] is Z0 itself, never escape-tested, exactly as the Python reference.
            var samples = new Samples(Math.Min(maxIter + 1, PollInterval), maxIter + 1);
            samples.Add(ToDouble(zr, bits), ToDouble(zi, bits));
            var small = new SmallBuilder(null);
            if (IsSmall(zr, zi, bits))
                small.Add(0, zr, zi, bits);
            return Run(kind, bits, zr, zi, cr, ci, samples, maxIter, progress, cancellationToken, small, 1, bigInteger);
        }

        private static Entry Resume(
            Kind kind, Entry start, int bits, int maxIter, RenderProgress? progress, CancellationToken cancellationToken)
        {
            var samples = new Samples(start.Re, start.Im, maxIter + 1);
            return Run(kind, bits, start.Zr, start.Zi, start.Cr, start.Ci, samples,
                maxIter - (start.Re.Length - 1), progress, cancellationToken, new SmallBuilder(start.Small), start.Re.Length);
        }

        /// <summary>
        /// Up to <paramref name="steps"/> steps from Z = (zr, zi), appending each rounded
        /// sample and stopping after the first that trips the stopping rule — the
        /// Python reference's loop exactly. The fixed-width path whenever the values fit,
        /// else BigInteger; the two agree bit for bit.
        /// </summary>
        private static Entry Run(
            Kind kind, int bits, BigInteger zr, BigInteger zi, BigInteger cr, BigInteger ci,
            Samples samples, int steps, RenderProgress? progress, CancellationToken cancellationToken,
            SmallBuilder small, int firstIndex, bool bigInteger = false)
        {
            progress?.BeginOrbit(steps);
            cancellationToken.ThrowIfCancellationRequested();
            int pollMask = PollIntervalFor(bits) - 1;
            bool escaped = false;
            bool burningShip = kind == Kind.BurningShip;
            int executed = 0;
            if (!bigInteger && FixedOrbit.Fits(bits, zr, zi, cr, ci))
            {
                var orbit = new FixedOrbit(burningShip, bits, zr, zi, cr, ci);
                for (int i = 0; i < steps; i++)
                {
                    if ((i & pollMask) == 0 && i > 0)
                        Poll(i, progress, cancellationToken);
                    orbit.Step();
                    executed++;
                    double sr = orbit.SampleRe;
                    double si = orbit.SampleIm;
                    samples.Add(sr, si);
                    if (orbit.IsSmall)
                    {
                        var (sre, sim) = orbit.State;
                        small.Add(firstIndex + i, sre, sim, bits);
                    }
                    // The escape test runs on the ROUNDED sample, like the reference.
                    if (sr * sr + si * si > EscapeAbs2)
                    {
                        escaped = true;
                        break;
                    }
                }
                (zr, zi) = orbit.State;
            }
            else
            {
                for (int i = 0; i < steps; i++)
                {
                    if ((i & pollMask) == 0 && i > 0)
                        Poll(i, progress, cancellationToken);
                    BigInteger nextR = Mul(zr, zr, bits) - Mul(zi, zi, bits) + cr;
                    BigInteger nextI = burningShip
                        ? 2 * Mul(BigInteger.Abs(zr), BigInteger.Abs(zi), bits) + ci
                        : 2 * Mul(zr, zi, bits) + ci;
                    zr = nextR;
                    zi = nextI;
                    executed++;
                    double sr = ToDouble(zr, bits);
                    double si = ToDouble(zi, bits);
                    samples.Add(sr, si);
                    if (IsSmall(zr, zi, bits))
                        small.Add(firstIndex + i, zr, zi, bits);
                    if (sr * sr + si * si > EscapeAbs2)
                    {
                        escaped = true;
                        break;
                    }
                }
            }
            progress?.OrbitAt(executed);
            var (re, im) = samples.ToArrays();
            return new Entry(re, im, escaped, zr, zi, cr, ci, small.Build());
        }

        private static void Poll(int completed, RenderProgress? progress, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            progress?.OrbitAt(completed);
        }

        /// <summary>Growable parallel sample arrays, trimmed once at the end.</summary>
        private sealed class Samples
        {
            private double[] _re, _im;
            private int _count;
            private readonly int _limit;

            /// <summary>Empty, growing by doubling but never past <paramref name="limit"/>.</summary>
            internal Samples(int capacity, int limit)
            {
                _re = new double[capacity];
                _im = new double[capacity];
                _limit = limit;
            }

            /// <summary>Start from an existing prefix; the arrays never grow past <paramref name="limit"/>.</summary>
            internal Samples(double[] re, double[] im, int limit)
            {
                int capacity = Math.Min(limit, Math.Max(re.Length * 2, re.Length + PollInterval));
                _re = new double[capacity];
                _im = new double[capacity];
                Array.Copy(re, _re, re.Length);
                Array.Copy(im, _im, im.Length);
                _count = re.Length;
                _limit = limit;
            }

            internal void Add(double re, double im)
            {
                if (_count == _re.Length)
                {
                    int capacity = (int)Math.Min((long)_re.Length * 2, Math.Max(_limit, _count + 1));
                    Array.Resize(ref _re, capacity);
                    Array.Resize(ref _im, capacity);
                }
                _re[_count] = re;
                _im[_count] = im;
                _count++;
            }

            internal (double[] Re, double[] Im) ToArrays()
            {
                if (_count != _re.Length)
                {
                    Array.Resize(ref _re, _count);
                    Array.Resize(ref _im, _count);
                }
                return (_re, _im);
            }
        }

        // ---- fixed-point helpers ---------------------------------------------------
        // A real x is held as the BigInteger round(x * 2^bits). Products carry twice
        // the fractional bits, so they are shifted back with round-to-nearest
        // (ties away from zero) rather than truncated — truncation would bias every
        // multiply toward zero and drift the orbit over thousands of iterations.

        internal static BigInteger Mul(BigInteger a, BigInteger b, int bits)
        {
            BigInteger product = a * b;
            BigInteger half = BigInteger.One << (bits - 1);
            if (product.Sign >= 0)
                return (product + half) >> bits;
            return -((-product + half) >> bits);
        }

        /// <summary>Round-to-nearest quotient, ties away from zero. Denominator &gt; 0.</summary>
        private static BigInteger RoundDiv(BigInteger numerator, BigInteger denominator)
        {
            bool negative = numerator.Sign < 0;
            BigInteger n = negative ? -numerator : numerator;
            BigInteger quotient = BigInteger.DivRem(n, denominator, out BigInteger remainder);
            if (remainder * 2 >= denominator)
                quotient += BigInteger.One;
            return negative ? -quotient : quotient;
        }

        /// <summary>
        /// A double is an integer times a power of two, so this is EXACT — decomposed
        /// from the IEEE-754 bit pattern rather than multiplied through floating
        /// point, which would overflow at large working precisions.
        /// </summary>
        internal static BigInteger FromDouble(double value, int bits)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
                throw new ArgumentException("center components must be finite", nameof(value));
            if (value == 0.0)
                return BigInteger.Zero;
            long raw = BitConverter.DoubleToInt64Bits(value);
            bool negative = raw < 0;
            int exponent = (int)((raw >> 52) & 0x7FF);
            long mantissa = raw & 0xFFFFFFFFFFFFFL;
            if (exponent == 0)
                exponent = 1;                 // subnormal
            else
                mantissa |= 1L << 52;         // restore the implicit bit
            exponent -= 1075;                 // value = mantissa * 2^exponent
            int shift = exponent + bits;
            BigInteger scaled = shift >= 0
                ? (BigInteger)mantissa << shift
                : RoundShiftRight(mantissa, -shift);
            return negative ? -scaled : scaled;
        }

        /// <summary>value &gt;&gt; shift, rounded to nearest, ties away from zero.</summary>
        private static BigInteger RoundShiftRight(BigInteger value, int shift)
        {
            if (shift <= 0)
                return value << -shift;
            BigInteger half = BigInteger.One << (shift - 1);
            return (value + half) >> shift;
        }

        /// <summary>
        /// Fixed-point to the nearest double, ties to even — IEEE-754's own rule.
        ///
        /// This must NOT lean on the built-in <c>(double)BigInteger</c> conversion,
        /// which TRUNCATES the mantissa. That was the whole bug: the orbit came out
        /// one ulp low in the imaginary part of Z[1] — which for a Mandelbrot orbit
        /// is simply the parsed center — and extra working precision did not fix it,
        /// because the error was in the final conversion, not the arithmetic.
        ///
        /// Subnormals round the same single time: once a value falls below 2^-1022
        /// its ulp stops shrinking at 2^-1074, so the rounding point moves up, and the
        /// result is assembled from its IEEE-754 bit pattern rather than scaled by a
        /// power of two — a multiply into the subnormal range would round a second
        /// time. Orbit components that small are ordinary at deep zoom (a center with
        /// a tiny imaginary part is one), and the old form threw on them once the
        /// working precision passed 1022 fractional bits, near zoom 268.8.
        /// </summary>
        internal static double ToDouble(BigInteger value, int bits)
        {
            if (value.IsZero)
                return 0.0;
            bool negative = value.Sign < 0;
            BigInteger magnitude = negative ? -value : value;

            // value = magnitude * 2^-bits, leading bit at 2^(length - 1 - bits). The
            // result's ulp is 2^ulp: 53 significant bits while normal, 2^-1074 below.
            int length = DecimalText.BitLength(magnitude);
            int ulp = Math.Max(length - 1 - bits - 52, -1074);
            int shift = ulp + bits;                            // magnitude / 2^shift = value / 2^ulp
            BigInteger q;
            if (shift <= 0)
            {
                q = magnitude << -shift;                       // exact: under 53 bits
            }
            else
            {
                q = magnitude >> shift;
                BigInteger rest = magnitude - (q << shift);
                int versusHalf = rest.CompareTo(BigInteger.One << (shift - 1));
                if (versusHalf > 0 || (versusHalf == 0 && !q.IsEven))
                    q += BigInteger.One;                       // ties to even
            }

            return DecimalText.Compose(negative, q, ulp);
        }

        /// <summary>
        /// Parse a decimal string (the viewport center format — arbitrary length,
        /// language-neutral, spec/deep-zoom.md; grammar in <see cref="DecimalText"/>)
        /// into fixed point WITHOUT going through double, which is the entire point:
        /// the center carries more digits than float64 can hold.
        /// </summary>
        internal static BigInteger ParseFixed(string text, int bits)
        {
            DecimalText.Scan(text, out bool negative, out BigInteger digits, out int netExponent);
            // value = digits * 10^netExponent, scaled by 2^bits.
            BigInteger scaled = digits << bits;
            BigInteger result = netExponent >= 0
                ? scaled * BigInteger.Pow(10, netExponent)
                : RoundDiv(scaled, BigInteger.Pow(10, -netExponent));
            return negative ? -result : result;
        }

        /// <summary>
        /// Fraction digits needed to write a decimal string exactly: digits after the
        /// point minus the exponent, never below 0 ("1e-295" needs 295, "2.5E1" none).
        /// </summary>
        public static int DecimalPlaces(string text)
        {
            if (text == null)
                throw new ArgumentNullException(nameof(text));
            return Math.Max(-DecimalText.NetExponent(text), 0);
        }
    }
}
