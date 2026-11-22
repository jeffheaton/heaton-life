using System;

namespace HeatonLife
{
    /// <summary>
    /// State palettes (spec/render.md "State palettes"): a color for each state of a world. A
    /// palette has a colormap's shape, 256 RGB entries (768 bytes), but is indexed by state
    /// instead of by frame value, so <see cref="Colormaps.ApplyIndexed(ReadOnlySpan{byte}, byte[], byte[])"/>
    /// and <see cref="Colormaps.ApplyIndexedRgba"/> color a byte frame of states: a grid
    /// world's <c>State</c> (<see cref="Elementary"/>'s, its <see cref="Elementary.Diagram"/>)
    /// or a <see cref="MultiStateHashLife"/> frame in <see cref="MultiStateRenderMode.State"/>.
    /// Entry s is state s's color; the entries from the world's number of states on are black
    /// and unused. A host that lets a person choose each state's color edits the entries.
    /// Every palette built here is new, so editing one changes nothing else.
    /// </summary>
    public static class StatePalettes
    {
        private static readonly byte[] HistoryColors =
        {
            0, 0, 0, // 0 off: black
            0, 255, 0, // 1 on: green
            0, 0, 160, // 2 envelope: blue
            255, 255, 255, // 3 marked on: white
            255, 0, 0, // 4 marked off: red
            255, 255, 0, // 5 start on: yellow
            128, 128, 128, // 6 boundary: gray
        };

        private static readonly byte[] HistoryOrder = { 3, 5, 1, 4, 6, 2 };

        private static readonly byte[] WireworldValues = { 0, 85, 170, 255 };

        private static readonly byte[] TwoStateValues = { 0, 255 };

        /// <summary>
        /// Each state's frame value f(s), state 0 first (spec/render.md "State palettes"): the
        /// byte the world's frame gives a cell in that state. Throws for a world without byte
        /// states (a float or RGB family).
        /// </summary>
        public static byte[] FrameValues(ISimulation world)
        {
            switch (world)
            {
                case null:
                    throw new ArgumentNullException(nameof(world));
                case LifeLike life:
                    return life.CompiledRule.Variant == RuleVariant.None
                        ? (byte[])TwoStateValues.Clone()
                        : Identity(life.States);
                case Elementary _:
                    return (byte[])TwoStateValues.Clone();
                case Cyclic cyclic:
                    {
                        var values = new byte[cyclic.States];
                        int span = Math.Max(cyclic.States - 1, 1);
                        for (int s = 0; s < values.Length; s++)
                            values[s] = (byte)(s * 255 / span);
                        return values;
                    }
                case Wireworld _:
                    return (byte[])WireworldValues.Clone();
                case Generations generations:
                    return GenerationsValues(generations.States);
                default:
                    throw NoByteStates(world);
            }
        }

        /// <summary>The two-state universe's frame values: 0 and 255, its frames' live cell.</summary>
        public static byte[] FrameValues(HashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            return (byte[])TwoStateValues.Clone();
        }

        /// <summary>A multi-state universe's frame values: the states, as its state frames give them.</summary>
        public static byte[] FrameValues(MultiStateHashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            return Identity(universe.States);
        }

        /// <summary>
        /// A colormap's palette for a world: entry s is the colormap's entry at state s's frame
        /// value, so coloring the states with it gives the bytes coloring the frame with the
        /// colormap gives. Where a host starts when the colors it shows today are to be edited
        /// state by state.
        /// </summary>
        public static byte[] FromColormap(ISimulation world, byte[] lut) => Sampled(lut, FrameValues(world));

        /// <summary>A colormap's palette for the two-state universe (frame values 0 and 255).</summary>
        public static byte[] FromColormap(HashLife universe, byte[] lut) => Sampled(lut, FrameValues(universe));

        /// <summary>A colormap's palette for a multi-state universe (frame values = states).</summary>
        public static byte[] FromColormap(MultiStateHashLife universe, byte[] lut) =>
            Sampled(lut, FrameValues(universe));

        /// <summary>
        /// A world's default palette (spec/render.md "Default palettes"): History's under a
        /// History rule, Generations' for Generations, and otherwise the palette of the
        /// colormap the family is shown with: phosphor for a two-state Life-like world, gray
        /// for Elementary, rainbow for Cyclic, wireworld for Wireworld.
        /// </summary>
        public static byte[] Default(ISimulation world)
        {
            switch (world)
            {
                case null:
                    throw new ArgumentNullException(nameof(world));
                case LifeLike life:
                    // Super rules (26 states) plug in here when they land.
                    return life.CompiledRule.Variant == RuleVariant.None
                        ? FromColormap(life, Colormaps.Get("phosphor"))
                        : ForHistory();
                case Elementary elementary:
                    return FromColormap(elementary, Colormaps.Get("gray"));
                case Cyclic cyclic:
                    return FromColormap(cyclic, Colormaps.Get("rainbow"));
                case Wireworld wire:
                    return FromColormap(wire, Colormaps.Get("wireworld"));
                case Generations generations:
                    return ForGenerations(generations.States);
                default:
                    throw NoByteStates(world);
            }
        }

        /// <summary>The two-state universe's default palette: phosphor's.</summary>
        public static byte[] Default(HashLife universe) => FromColormap(universe, Colormaps.Get("phosphor"));

        /// <summary>
        /// A multi-state universe's default palette: the one its rule has on a grid (History's,
        /// Generations' of its C, wireworld's for WireWorld), or for any other rule the
        /// multi-state palette of its S.
        /// </summary>
        public static byte[] Default(MultiStateHashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            switch (universe.StateRule)
            {
                case HistoryRule _:
                    return ForHistory();
                case GenerationsRule generations:
                    return ForGenerations(generations.States);
                case WireworldRule _:
                    return Sampled(Colormaps.Get("wireworld"), WireworldValues);
                default:
                    // Rule tables (their @COLORS over the multi-state palette) and Super rules
                    // plug in here when they land (spec/render.md "Still to come").
                    return ForMultiState(universe.States);
            }
        }

        /// <summary>
        /// The zoom order that goes with a world's default palette (spec/render.md "Zoomed
        /// out"): History's, (3, 5, 1, 4, 6, 2), under a History rule; empty (the lowest
        /// non-zero state first) for every other world. Pass it to
        /// <see cref="GridWindow.Sample"/>; nothing sets it for the host.
        /// </summary>
        public static byte[] DefaultZoomOrder(ISimulation world)
        {
            FrameValues(world); // refuses a world without byte states, as the palettes do
            if (world is LifeLike life && life.CompiledRule.Variant != RuleVariant.None)
                return (byte[])HistoryOrder.Clone();
            return Array.Empty<byte>();
        }

        /// <summary>The two-state universe's zoom order: empty (its frames give 255 for any live cell).</summary>
        public static byte[] DefaultZoomOrder(HashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            return Array.Empty<byte>();
        }

        /// <summary>
        /// A multi-state universe's zoom order: History's under a History rule, else empty.
        /// Set it as the universe's <see cref="MultiStateHashLife.ZoomOrder"/>.
        /// </summary>
        public static byte[] DefaultZoomOrder(MultiStateHashLife universe)
        {
            if (universe == null)
                throw new ArgumentNullException(nameof(universe));
            return universe.StateRule is HistoryRule ? (byte[])HistoryOrder.Clone() : Array.Empty<byte>();
        }

        /// <summary>
        /// History's palette: off black, on green, the envelope blue, marked on white, marked
        /// off red, start on yellow, the boundary gray (spec/render.md "Default palettes").
        /// </summary>
        public static byte[] ForHistory()
        {
            var palette = new byte[768];
            Buffer.BlockCopy(HistoryColors, 0, palette, 0, HistoryColors.Length);
            return palette;
        }

        /// <summary>
        /// Generations' palette of C states: fire at the Generations frame values, so a live
        /// cell is pale yellow and the dying states fade through orange and red toward black.
        /// </summary>
        public static byte[] ForGenerations(int states) =>
            Sampled(Colormaps.Get("fire"), GenerationsValues(CheckStates(states)));

        /// <summary>
        /// The palette of a rule with none of its own: black, then rainbow's entry
        /// ⌊255 · (s − 1) / (S − 1)⌋ for each state s from 1, S − 1 hues and none twice.
        /// </summary>
        public static byte[] ForMultiState(int states)
        {
            int count = CheckStates(states);
            byte[] rainbow = Colormaps.Get("rainbow");
            var palette = new byte[768];
            for (int s = 1; s < count; s++)
            {
                int entry = 255 * (s - 1) / (count - 1);
                palette[s * 3] = rainbow[entry * 3];
                palette[s * 3 + 1] = rainbow[entry * 3 + 1];
                palette[s * 3 + 2] = rainbow[entry * 3 + 2];
            }
            return palette;
        }

        /// <summary>
        /// Entry 0 the background, and states 1 to S − 1 from <paramref name="first"/> to
        /// <paramref name="last"/>: per channel (first · (S − 1 − s) + last · (s − 1)) / (S − 2),
        /// rounded half to even in exact integers; with two states, state 1 is first. A rule
        /// file's <c>@COLORS</c> gradient sets states 1 to S − 1 this way.
        /// </summary>
        public static byte[] Gradient(
            int states,
            (byte R, byte G, byte B) first,
            (byte R, byte G, byte B) last,
            (byte R, byte G, byte B) background = default)
        {
            int count = CheckStates(states);
            var palette = new byte[768];
            Put(palette, 0, background);
            if (count == 2)
            {
                Put(palette, 1, first);
                return palette;
            }
            int span = count - 2;
            for (int s = 1; s < count; s++)
            {
                int a = count - 1 - s, b = s - 1;
                palette[s * 3] = (byte)HalfEven(first.R * a + last.R * b, span);
                palette[s * 3 + 1] = (byte)HalfEven(first.G * a + last.G * b, span);
                palette[s * 3 + 2] = (byte)HalfEven(first.B * a + last.B * b, span);
            }
            return palette;
        }

        /// <summary>
        /// The shade from state 0's color to state 1's (spec/render.md "Zoomed out"), a
        /// colormap for frames whose pixels count live cells (the two-state universe's, every
        /// density frame, a grid window's density): entry v is b + (c − b) · v / 255 per
        /// channel, rounded half to even in exact integers. From black to white it is gray.
        /// </summary>
        public static byte[] Shade((byte R, byte G, byte B) background, (byte R, byte G, byte B) color)
        {
            var lut = new byte[768];
            for (int v = 0; v < 256; v++)
            {
                int u = 255 - v;
                lut[v * 3] = (byte)HalfEven(background.R * u + color.R * v, 255);
                lut[v * 3 + 1] = (byte)HalfEven(background.G * u + color.G * v, 255);
                lut[v * 3 + 2] = (byte)HalfEven(background.B * u + color.B * v, 255);
            }
            return lut;
        }

        private static byte[] Sampled(byte[] lut, byte[] values)
        {
            if (lut == null)
                throw new ArgumentNullException(nameof(lut));
            if (lut.Length != 768)
                throw new ArgumentException($"a colormap is 256x3 = 768 bytes, got {lut.Length}", nameof(lut));
            var palette = new byte[768];
            for (int s = 0; s < values.Length; s++)
            {
                int entry = values[s];
                palette[s * 3] = lut[entry * 3];
                palette[s * 3 + 1] = lut[entry * 3 + 1];
                palette[s * 3 + 2] = lut[entry * 3 + 2];
            }
            return palette;
        }

        private static byte[] GenerationsValues(int states)
        {
            var values = new byte[states];
            for (int s = 1; s < states; s++)
                values[s] = (byte)(255 * (states - s) / (states - 1));
            return values;
        }

        private static byte[] Identity(int states)
        {
            var values = new byte[states];
            for (int s = 0; s < states; s++)
                values[s] = (byte)s;
            return values;
        }

        private static int CheckStates(int states)
        {
            if (states < 2 || states > 256)
                throw new ArgumentOutOfRangeException(
                    nameof(states), $"a state palette is for 2 to 256 states, not {states}");
            return states;
        }

        private static void Put(byte[] palette, int state, (byte R, byte G, byte B) color)
        {
            palette[state * 3] = color.R;
            palette[state * 3 + 1] = color.G;
            palette[state * 3 + 2] = color.B;
        }

        /// <summary>numerator / denominator rounded half to even (numerator ≥ 0, denominator > 0).</summary>
        private static int HalfEven(int numerator, int denominator)
        {
            int quotient = numerator / denominator;
            int remainder = numerator - quotient * denominator;
            if (2 * remainder > denominator || (2 * remainder == denominator && (quotient & 1) == 1))
                quotient++;
            return quotient;
        }

        private static ArgumentException NoByteStates(ISimulation world) =>
            new ArgumentException($"{world.GetType().Name} has no byte states to color", nameof(world));
    }
}
