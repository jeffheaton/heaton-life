using System;

namespace HeatonLife
{
    /// <summary>
    /// Raw simulation state to bytes and back, for every family — the C#
    /// counterpart of the Python reference's <c>CODECS</c> table
    /// (python/src/heaton_life/conformance.py). Byte-state families travel as-is;
    /// double-state families as explicit little-endian IEEE-754, written a byte at
    /// a time so a saved world is identical on any machine regardless of host
    /// endianness.
    ///
    /// This belongs to the library because it was otherwise written three times:
    /// once in the app's world catalog, once in the conformance runner, and once —
    /// correctly — in Python. A host that wants to save, load, or verify a world
    /// through <see cref="ISimulation"/> should call this rather than switch on the
    /// concrete family.
    ///
    /// The layout is the one already on disk in shipped saves; it is a storage
    /// contract, not merely an implementation detail. Do not change it. (Extended
    /// once, before any release shipped — 2026-08-22: an elementary save carries
    /// the space-time diagram after the tape, and tape-only saves still load.)
    /// </summary>
    public static class StateCodec
    {
        /// <summary>Serialize a world's raw state. Round-trips through <see cref="Load"/>.</summary>
        public static byte[] Save(ISimulation sim)
        {
            switch (sim)
            {
                case LifeLike life: return life.State.ToArray();
                case Cyclic cyclic: return cyclic.State.ToArray();
                case Wireworld wire: return wire.State.ToArray();
                case MergeLife merge: return merge.State.ToArray();
                case Elementary elementary: return ElementaryBytes(elementary);
                case GrayScott gray: return DoubleBytes(gray.State);
                case LeniaBase lenia: return DoubleBytes(lenia.State);
                case Boids boids: return DoubleBytes(boids.State);
                default:
                    throw new ArgumentException(
                        $"no state serializer for {sim.GetType().Name}", nameof(sim));
            }
        }

        /// <summary>
        /// Restore bytes produced by <see cref="Save"/> into a world of the same
        /// family and dimensions, at the given generation.
        /// </summary>
        public static void Load(ISimulation sim, byte[] bytes, int generation)
        {
            if (bytes == null)
                throw new ArgumentNullException(nameof(bytes));
            switch (sim)
            {
                case LifeLike life: life.SetState(bytes, generation); break;
                case Cyclic cyclic: cyclic.SetState(bytes, generation); break;
                case Wireworld wire: wire.SetState(bytes, generation); break;
                case MergeLife merge: merge.SetState(bytes, generation); break;
                case Elementary elementary: LoadElementary(elementary, bytes, generation); break;
                case GrayScott gray: gray.SetState(BytesToDoubles(bytes), generation); break;
                case LeniaBase lenia: lenia.SetState(BytesToDoubles(bytes), generation); break;
                case Boids boids: boids.SetState(BytesToDoubles(bytes), generation); break;
                default:
                    throw new ArgumentException(
                        $"no state restorer for {sim.GetType().Name}", nameof(sim));
            }
        }

        /// <summary>
        /// Elementary: the tape (Width bytes) followed by the space-time diagram
        /// (Height*Width bytes, row-major 0/1). The diagram is presentation by
        /// spec/elementary.md, but it is the record of the steps already taken and
        /// cannot be rebuilt from the tape — a world saved without it reopened as a
        /// blank canvas. The tape travels explicitly rather than being read back out
        /// of the diagram so that a world restored from a tape-only save (whose
        /// diagram is mostly blank) still saves its true tape.
        /// </summary>
        private static byte[] ElementaryBytes(Elementary sim)
        {
            var bytes = new byte[sim.Width + sim.Diagram.Length];
            sim.State.CopyTo(bytes);
            sim.Diagram.CopyTo(bytes.AsSpan(sim.Width));
            return bytes;
        }

        /// <summary>Accepts both layouts: tape only (pre-2026-08-22 saves) or tape + diagram.</summary>
        private static void LoadElementary(Elementary sim, byte[] bytes, int generation)
        {
            int width = sim.Width;
            int full = width + sim.Diagram.Length;
            if (bytes.Length == width)
            {
                sim.SetState(bytes, generation);
                return;
            }
            if (bytes.Length != full)
                throw new ArgumentException(
                    $"expected {width} (tape) or {full} (tape + diagram) bytes, got {bytes.Length}");
            sim.SetState(bytes.AsSpan(0, width), bytes.AsSpan(width), generation);
        }

        /// <summary>IEEE-754 doubles as explicit little-endian bytes (8 per value).</summary>
        public static byte[] DoubleBytes(ReadOnlySpan<double> values)
        {
            var bytes = new byte[values.Length * 8];
            for (int i = 0; i < values.Length; i++)
            {
                long bits = BitConverter.DoubleToInt64Bits(values[i]);
                for (int b = 0; b < 8; b++)
                    bytes[i * 8 + b] = (byte)(bits >> (8 * b));
            }
            return bytes;
        }

        /// <summary>The inverse of <see cref="DoubleBytes"/>.</summary>
        public static double[] BytesToDoubles(byte[] bytes)
        {
            if (bytes == null)
                throw new ArgumentNullException(nameof(bytes));
            if (bytes.Length % 8 != 0)
                throw new ArgumentException(
                    $"expected a multiple of 8 bytes, got {bytes.Length}", nameof(bytes));
            var values = new double[bytes.Length / 8];
            for (int i = 0; i < values.Length; i++)
            {
                long bits = 0;
                for (int b = 0; b < 8; b++)
                    bits |= (long)bytes[i * 8 + b] << (8 * b);
                values[i] = BitConverter.Int64BitsToDouble(bits);
            }
            return values;
        }
    }
}
