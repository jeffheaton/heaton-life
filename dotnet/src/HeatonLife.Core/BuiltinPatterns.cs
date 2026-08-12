namespace HeatonLife
{
    /// <summary>One entry of the built-in pattern set (spec/patterns.md "Built-in patterns").</summary>
    public sealed class BuiltinPattern
    {
        internal BuiltinPattern(string name, string family, string rule, string rle)
        {
            Name = name;
            Family = family;
            Rule = rule;
            Rle = rle;
        }

        public string Name { get; }

        /// <summary>Spec family key ("lifelike", "wireworld") — patterns are family-bound.</summary>
        public string Family { get; }

        /// <summary>Origin context: the rule the pattern is native to.</summary>
        public string Rule { get; }

        /// <summary>Canonical RLE body, headerless; decode through <see cref="Decode"/>.</summary>
        public string Rle { get; }

        /// <summary>Decode the cells (a fresh grid each call).</summary>
        public RlePattern Decode() =>
            Patterns.RleDecode($"x = 0, y = 0, rule = {Rule}\n{Rle}");
    }

    /// <summary>
    /// The built-in pattern set — spec/patterns.md "Built-in patterns": code-defined
    /// encodings of public mathematical commons (authored from their published cell
    /// coordinates, no copied pattern files). Every implementation ships this same
    /// set, behavior-pinned in its test suite; apps surface it as the zoo's
    /// built-in shelf.
    /// </summary>
    public static class BuiltinPatterns
    {
        private static BuiltinPattern Life(string name, string rle, string rule = "B3/S23") =>
            new BuiltinPattern(name, "lifelike", rule, rle);

        private static BuiltinPattern Wire(string name, string rle) =>
            new BuiltinPattern(name, "wireworld", "WireWorld", rle);

        public static readonly BuiltinPattern[] All =
        {
            // Spaceships.
            Life("Glider", "bo$2bo$3o!"),
            Life("Lightweight spaceship", "bo2bo$o$o3bo$4o!"),
            Life("Middleweight spaceship", "3bo$bo3bo$o$o4bo$5o!"),
            Life("Heavyweight spaceship", "3b2o$bo4bo$o$o5bo$6o!"),
            // Oscillators.
            Life("Blinker", "3o!"),
            Life("Toad", "b3o$3o!"),
            Life("Beacon", "2o$2o$2b2o$2b2o!"),
            Life("Pulsar",
                "2b3o3b3o2$o4bobo4bo$o4bobo4bo$o4bobo4bo$2b3o3b3o2$"
                + "2b3o3b3o$o4bobo4bo$o4bobo4bo$o4bobo4bo2$2b3o3b3o!"),
            Life("Pentadecathlon", "2bo4bo$2ob4ob2o$2bo4bo!"),
            // Still lifes.
            Life("Block", "2o$2o!"),
            Life("Beehive", "b2o$o2bo$b2o!"),
            Life("Loaf", "b2o$o2bo$bobo$2bo!"),
            // Methuselahs.
            Life("R-pentomino", "b2o$2o$bo!"),
            Life("Diehard", "6bo$2o$bo3b3o!"),
            Life("Acorn", "bo$3bo$2o2b3o!"),
            // Guns.
            Life("Gosper glider gun",
                "24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$"
                + "2o8bo3bob2o4bobo$10bo5bo7bo$11bo3bo$12b2o!"),
            // HighLife: stamp into a B36/S23 world to watch it self-copy.
            Life("Replicator (HighLife)", "2b3o$bo2bo$o3bo$o2bo$3o!", "B36/S23"),
            // Wireworld logic. Clock: an electron circulating a conductor ring.
            // Diode: the 2-cell cap passes rightward electrons and kills leftward ones.
            Wire("Clock", "CBA3C$C4.C$6C!"),
            Wire("Diode (passes right)", "3.2C$4C.3C$3.2C!"),
        };
    }
}
