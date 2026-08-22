using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class Pow10Tests
    {
        [Fact]
        public void KnownAnswers()
        {
            // spec/pow10.md "Known-answer test": exact IEEE-754 bit patterns,
            // pinned across languages (the Python suite asserts the same table).
            (double X, ulong Bits)[] known =
            {
                (0.0, 0x3FF0000000000000UL),
                (1.0, 0x4024000000000000UL),
                (14.0, 0x42D6BCC41E900000UL),
                (22.0, 0x4480F0CF064DD592UL),
                (0.2, 0x3FF95BB8F6D46053UL),
                (-0.2, 0x3FE430CD74F6D478UL),
                (-0.1, 0x3FE96B230BCDC434UL),
                (-14.0, 0x3D06849B86A12B9BUL),
                (290.0, 0x7C2485CE9E7A065FUL),
                (-290.0, 0x03B8F2B061AEA072UL),
            };
            foreach (var (x, bits) in known)
                Assert.Equal(bits, (ulong)BitConverter.DoubleToInt64Bits(Pow10.Compute(x)));
        }

        [Fact]
        public void IntegerPowersAreExact()
        {
            // 10^0 .. 10^22 are exactly representable; the algorithm must land on them.
            double value = 1.0;
            for (int k = 0; k <= 22; k++)
            {
                Assert.Equal(value, Pow10.Compute(k));
                value *= 10.0; // exact up to 10^22
            }
        }

        [Fact]
        public void DomainIsRejected()
        {
            Assert.Throws<ArgumentException>(() => Pow10.Compute(300.5));
            Assert.Throws<ArgumentException>(() => Pow10.Compute(-300.5));
            Assert.Throws<ArgumentException>(() => Pow10.Compute(double.NaN));
            Assert.Throws<ArgumentException>(() => Pow10.Compute(double.PositiveInfinity));
        }

        [Fact]
        public void PixelScaleUsesTheDeterministicPower()
        {
            // The burning-ship/home-64 viewport: the exact pixel scale whose last
            // ulp the platform libms disagreed on (spec/fractals.md 2026-08-21).
            double ps = FractalEngine.PixelScale(64, new Viewport("-0.5", "-0.5", -0.2));
            Assert.Equal(0x3FB95BB8F6D46053UL, (ulong)BitConverter.DoubleToInt64Bits(ps));

            // Integer zoom stays exact: 4/64 * 10^0 == 0.0625 to the bit.
            Assert.Equal(0.0625, FractalEngine.PixelScale(64, new Viewport("-0.5", "0.0", 0.0)));
        }
    }
}
