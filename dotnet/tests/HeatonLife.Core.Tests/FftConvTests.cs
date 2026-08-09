using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class FftConvTests
    {
        /// <summary>Naive O(N²) circular convolution, the ground truth for the FFT path.</summary>
        private static double[] DirectConvolve(double[] field, double[] kernel, int width, int height)
        {
            var result = new double[width * height];
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    double sum = 0.0;
                    for (int ky = 0; ky < height; ky++)
                        for (int kx = 0; kx < width; kx++)
                        {
                            int sy = ((y - ky) % height + height) % height;
                            int sx = ((x - kx) % width + width) % width;
                            sum += kernel[ky * width + kx] * field[sy * width + sx];
                        }
                    result[y * width + x] = sum;
                }
            return result;
        }

        [Theory]
        [InlineData(16, 16)] // power of two: radix-2 path
        [InlineData(12, 16)] // mixed: Bluestein columns... rows
        [InlineData(15, 13)] // both odd: Bluestein everywhere
        public void FftConvolutionMatchesDirect(int width, int height)
        {
            var rng = new Pcg32(99);
            var field = new double[width * height];
            var kernel = new double[width * height];
            for (int i = 0; i < field.Length; i++)
            {
                field[i] = rng.NextU32() / 4294967296.0;
                kernel[i] = rng.NextU32() / 4294967296.0;
            }

            var plan = new Fft2Plan(width, height);
            var (kRe, kIm) = FftConv.KernelFft(plan, kernel);
            var outRe = new double[width * height];
            var scratchIm = new double[width * height];
            FftConv.Convolve(plan, field, kRe, kIm, outRe, scratchIm);

            double[] expected = DirectConvolve(field, kernel, width, height);
            for (int i = 0; i < expected.Length; i++)
                Assert.True(
                    Math.Abs(outRe[i] - expected[i]) < 1e-11,
                    $"fft convolution deviates at {i}: {outRe[i]} vs {expected[i]}");
        }

        [Fact]
        public void ForwardInverseRoundTrips()
        {
            var rng = new Pcg32(7);
            const int w = 24, h = 10; // both non-pow2
            var re = new double[w * h];
            var im = new double[w * h];
            for (int i = 0; i < re.Length; i++)
                re[i] = rng.NextU32() / 4294967296.0 - 0.5;
            var reOrig = (double[])re.Clone();

            var plan = new Fft2Plan(w, h);
            plan.Forward(re, im);
            plan.Inverse(re, im);
            for (int i = 0; i < re.Length; i++)
            {
                Assert.True(Math.Abs(re[i] - reOrig[i]) < 1e-12);
                Assert.True(Math.Abs(im[i]) < 1e-12);
            }
        }
    }
}
