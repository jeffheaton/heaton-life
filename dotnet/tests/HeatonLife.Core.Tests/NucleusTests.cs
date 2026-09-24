using System;
using System.Numerics;
using System.Threading;
using Xunit;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Discovery (spec/nucleus.md): what the vectors do not pin — Heaton Fractal's own
    /// nuclei, the ext conversion at the extremes, the framing, the rules at their edges,
    /// cancellation and the errors. The Python reference's tests/test_nucleus.py.
    /// </summary>
    public class NucleusTests
    {
        // Heaton Fractal's r7-a hunt (hunts/r7-a.jsonl lines 1-3), printed at depth + 64 places.
        private const string P1959Re =
            "-0.7417927014292001232841548624613348654659797595596692133814229089779333158651146245001356794980988932282797";
        private const string P1959Im =
            "0.1239779417246959717116896203392233208927965744164153733905536369850466608213725129489699597506805010116194";
        private const string P6308Re =
            "-0.74179270142920012328415486246133486822181337292254710214402418375004664084945569585246011078130725915411031437453364085735507047308210616986538010966660804513830391512170";
        private const string P6308Im =
            "0.12397794172469597171168962033922331783836724767353582285720009688384988049497459996516886304789610234791243018841746592856594306471080784322388395732723828262276304644199";
        private const string P26699Re =
            "-0.74179270142920012328415486246133486822181337292254710214402418375004664084945569585246011078130725905037488914362121274795770474646487637739999798587194183294433484300685449058507595536148294552732379756707780794222699765000848915601310069605471431265457587979988124418712944798709332720697771546765";
        private const string P26699Im =
            "0.12397794172469597171168962033922331783836724767353582285720009688384988049497459996516886304789610236795892717050828606930965765482956408260227797393176255870494542347749814285195935908938228446358634882858469364497547178044866612817146768563458523416373733697179639200000597923217178028307370027088";

        [Theory]
        [InlineData(P1959Re, P1959Im, 1959, 21.0, 42.7257864009331)]
        [InlineData(P6308Re, P6308Im, 6308, 55.0, 106.17376130574708)]
        [InlineData(P26699Re, P26699Im, 26699, 118.0, 235.16141613800227)]
        public void HeatonFractalNucleiRefineToThemselves(string re, string im, int period, double zoom, double depth)
        {
            Nucleus n = NucleusFinder.FindNucleus(re, im, period, zoom);
            Assert.True(n.Found);
            Assert.Equal("floor", n.Stop);
            int places = n.CenterRe.Length - n.CenterRe.IndexOf('.') - 1;
            Assert.Equal(Rounded(re, places), n.CenterRe);
            Assert.Equal(Rounded(im, places), n.CenterIm);
            Assert.True(Math.Abs(n.SizeLog10 + depth) <= 1e-12 * depth, $"{n.SizeLog10:R} vs {-depth:R}");
        }

        /// <summary>A decimal string rounded half away from zero to <paramref name="places"/> places.</summary>
        private static string Rounded(string text, int places)
        {
            bool negative = text.StartsWith("-", StringComparison.Ordinal);
            string digits = text.TrimStart('-').Replace(".", "");
            int dropped = text.Length - text.IndexOf('.') - 1 - places;
            BigInteger value = BigInteger.Parse(digits);
            BigInteger scale = BigInteger.Pow(10, dropped);
            BigInteger q = BigInteger.DivRem(value, scale, out BigInteger r);
            if (r * 2 >= scale)
                q += 1;
            return DecimalText.FormatScaled(negative ? -q : q, places);
        }

        [Fact]
        public void AFoundCenterRefinesToItself()
        {
            Nucleus first = NucleusFinder.FindNucleus("-1.75", "0.001", 3, 1.0);
            Nucleus again = NucleusFinder.FindNucleus(first.CenterRe, first.CenterIm, 3, 1.0);
            Assert.True(first.Found && again.Found);
            Assert.Equal(first.CenterRe, again.CenterRe);
            Assert.Equal(first.CenterIm, again.CenterIm);
        }

        // ---- the ext conversion ------------------------------------------------------

        [Theory]
        [InlineData("1", 1200, 1.0, -1200)]                            // below the smallest subnormal
        [InlineData("3", 1024 - 1500, 1.5, 477)]                       // 3·2^476 at F > 1024 (as 3 at F = −476)
        [InlineData("9007199254740993", 100, 1.0, -47)]                // 2^53 + 1: a tie, to even (down)
        [InlineData("9007199254740995", 100, 1.0000000000000004, -47)] // 2^53 + 3: a tie, to even (up)
        [InlineData("18014398509481983", 10, 1.0, 44)]                 // 2^54 − 1 rounds up across the binade
        public void SplitRoundsTheIntegerItself(string value, int bits, double mantissa, int exponent)
        {
            double m = NucleusFinder.Split(BigInteger.Parse(value), bits, out int e);
            Assert.Equal(mantissa, m);
            Assert.Equal(exponent, e);
            double negative = NucleusFinder.Split(-BigInteger.Parse(value), bits, out int ne);
            Assert.Equal(-mantissa, negative);
            Assert.Equal(exponent, ne);
        }

        [Fact]
        public void SplitHandlesFixedPointPastTheDoubleRange()
        {
            // 3·2^1500 at F = 1024 is 3·2^476: far past (double)BigInteger's range as an integer.
            double m = NucleusFinder.Split(new BigInteger(3) << 1500, 1024, out int e);
            Assert.Equal(1.5, m);
            Assert.Equal(477, e);
        }

        [Fact]
        public void ExtKeepsParts60BinadesApartAndDropsFarther()
        {
            // 1 + 2^-60 i: exactly 60 binades down, kept; 2^-61: more than 60 down, dropped.
            var near = NucleusFinder.Ext.FromFixed(BigInteger.One << 100, BigInteger.One << 40, 100);
            Assert.Equal(1.0, near.Re);
            Assert.Equal(Math.Pow(2, -60), near.Im);
            Assert.Equal(0, near.E);
            var far = NucleusFinder.Ext.FromFixed(BigInteger.One << 100, BigInteger.One << 39, 100);
            Assert.Equal(0.0, far.Im);
        }

        [Theory]
        [InlineData(3, 1, 2)]
        [InlineData(-3, 1, -2)]
        [InlineData(-6, 2, -2)]
        [InlineData(5, 1, 3)]
        [InlineData(-5, 1, -3)]
        public void RoundShiftTiesGoAwayFromZero(int value, int k, int expected) =>
            Assert.Equal(new BigInteger(expected), NucleusFinder.RoundShift(value, k));

        [Theory]
        [InlineData(3, 2, 2)]
        [InlineData(-3, 2, -2)]
        [InlineData(5, 2, 3)]
        [InlineData(-7, 2, -4)]
        [InlineData(7, 3, 2)]
        public void RoundDivTiesGoAwayFromZero(int numerator, int denominator, int expected) =>
            Assert.Equal(new BigInteger(expected), NucleusFinder.RoundDiv(numerator, denominator));

        // ---- the rules at their edges ------------------------------------------------

        [Fact]
        public void SurroundIsHalfOpenOnTheAxis()
        {
            Assert.True(Surrounds((-1, -1), (1, -1), (1, 1), (-1, 1)));
            // A vertex on the positive axis counts as above: inside counts 1, outside 0 or 2.
            Assert.True(Surrounds((1, 0), (-1, 1), (-1, -1)));
            Assert.False(Surrounds((1, 0), (2, 1), (2, -1)));
            // A corner exactly at 0, the rest above: nothing straddles, so it is outside.
            Assert.False(Surrounds((0, 0), (2, 0), (2, 2), (0, 2)));
            // An edge through 0 itself (product 0) does not cross; the other edge does: inside.
            Assert.True(Surrounds((0, 0), (2, 0), (2, 2), (0, -1)));
        }

        private static bool Surrounds(params (int X, int Y)[] points)
        {
            var x = new BigInteger[points.Length];
            var y = new BigInteger[points.Length];
            for (int i = 0; i < points.Length; i++)
            {
                x[i] = points[i].X;
                y[i] = points[i].Y;
            }
            return NucleusFinder.SurroundsOrigin(x, y);
        }

        [Fact]
        public void PeriodOneHasSizePositiveZero()
        {
            Nucleus n = NucleusFinder.FindNucleus("-0.5", "0", 1, 0.0);
            Assert.True(n.Found);
            Assert.Equal(0L, BitConverter.DoubleToInt64Bits(n.SizeLog10));
        }

        [Fact]
        public void LocationFramesTwoAndAHalfSizes()
        {
            Nucleus n = NucleusFinder.FindNucleus("-1.75", "0.001", 3, 1.0);
            Location loc = n.ToLocation();
            Assert.Equal("nucleus", loc.Format);
            Assert.Equal(300L, loc.MaxIter);
            Assert.Equal(n.SizeLog10 + 0.4, loc.HalfHeightLog10);
        }

        [Fact]
        public void LocationMaxIterNeverOverflows()
        {
            var huge = new Nucleus(true, true, true, "floor", "0", "0", 414_246_396, null, 128, 1, 1, 0, 0.0);
            Assert.Equal((long)int.MaxValue, huge.ToLocation().MaxIter);
            var lost = new Nucleus(false, false, false, "left-view", "0", "0", 3, null, 128, 1, 1, 0, double.NaN);
            Assert.Throws<InvalidOperationException>(() => lost.ToLocation());
        }

        [Fact]
        public void FoundNeedsTheNucleusInsideTheReach()
        {
            Nucleus n = NucleusFinder.FindNucleus(P1959Re, P1959Im, 1924, 21.0);
            Assert.False(n.Found);
            Assert.False(n.Inside);
            Assert.Equal("left-view", n.Stop);
        }

        [Fact]
        public void ACoarsePrecisionIsNotConverged()
        {
            // Without escalation, F = 128 cannot place a depth-162 atom: a grid point billions of
            // sizes from the nucleus passes the bar, and the gate says not converged.
            Nucleus coarse = NucleusFinder.FindNucleus("-2", "0", 42, 0.0, maxEscalations: 0);
            Assert.True(coarse.Bits - coarse.DepthBits < 64);
            Assert.False(coarse.Converged);
            Assert.False(coarse.Found);
            Nucleus fine = NucleusFinder.FindNucleus("-2", "0", 42, 0.0);
            Assert.True(fine.Found);
            Assert.True(fine.Bits - fine.DepthBits >= 64);
        }

        [Fact]
        public void AFailedSearchPrintsAtTheViewsPlaces()
        {
            // This orbit's depth would ask for over 10,000 places; a point that did not converge
            // prints 8 places past the view instead.
            Nucleus n = NucleusFinder.FindNucleus("0", "1", 14000, 0.0, maxEscalations: 0);
            Assert.False(n.Converged);
            Assert.True(n.DepthBits > 33000);
            Assert.Equal("0.00000000", n.CenterRe);
            Assert.Equal("1.00000000", n.CenterIm);
        }

        [Fact]
        public void ALowerPeriodIsConvergedButNotFound()
        {
            Nucleus n = NucleusFinder.FindNucleus("-1.001", "0.0003", 4, 2.0);
            Assert.True(n.Converged);
            Assert.Equal(2, n.LowerPeriod);
            Assert.False(n.Found);
            Assert.True(double.IsNaN(n.SizeLog10));
        }

        // ---- cancellation ------------------------------------------------------------

        [Fact]
        public void CancellationThrowsAndNeverReturnsAPartialResult()
        {
            using var source = new CancellationTokenSource();
            source.Cancel();
            Assert.ThrowsAny<OperationCanceledException>(() =>
                NucleusFinder.BoxPeriod("-0.1", "0", 3.0, 10000, null, source.Token));
            Assert.ThrowsAny<OperationCanceledException>(() =>
                NucleusFinder.FindNucleus(P6308Re, P6308Im, 6308, 55.0, cancellationToken: source.Token));
            // Short periods too: no loop reaches 4096 iterations here, so the entry polls decide.
            Assert.ThrowsAny<OperationCanceledException>(() =>
                NucleusFinder.BoxPeriod(P1959Re, P1959Im, 23.0, 5000, null, source.Token));
            Assert.ThrowsAny<OperationCanceledException>(() =>
                NucleusFinder.FindNucleus(P1959Re, P1959Im, 1959, 23.0, cancellationToken: source.Token));
            Assert.ThrowsAny<OperationCanceledException>(() =>
                NucleusFinder.FindNucleus("-1.75", "0.001", 3, 1.0, cancellationToken: source.Token));
        }

        // ---- errors ------------------------------------------------------------------

        [Fact]
        public void BadArgumentsThrow()
        {
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.BoxPeriod("0", "0", 0.0, 0));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.FindNucleus("0", "0", 0, 0.0));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.FindNucleus("0", "0", 2, 0.0, maxSteps: 0));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.FindNucleus("0", "0", 2, 0.0, maxEvaluations: 0));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.FindNucleus("0", "0", 2, 0.0, maxEscalations: -1));
            foreach (double radius in new[] { 0.0, -1.0, double.PositiveInfinity, double.NaN })
                Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.FindNucleus("0", "0", 2, 0.0, radius));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.BoxPeriod("0", "0", double.NaN, 10, 1.0));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.BoxPeriod("0", "0", 301.0, 10));
            Assert.Throws<ArgumentOutOfRangeException>(() => NucleusFinder.FindNucleus("0", "0", 2, -301.0, 1.0));
        }
    }
}
