using System;

namespace HeatonLife
{
    /// <summary>
    /// Pure-C# 2-D FFT for circular convolution (Lenia's workhorse) — no native
    /// plugins, per the project constraint. Power-of-two lengths use iterative
    /// radix-2 Cooley-Tukey; other lengths use Bluestein's chirp-z algorithm on top
    /// of it, so any grid size the Python side accepts works here too. Forward is
    /// unscaled, inverse scales by 1/N per dimension, matching NumPy.
    /// </summary>
    public sealed class Fft2Plan
    {
        private readonly Dft1d _row;
        private readonly Dft1d _col;
        private readonly double[] _colRe;
        private readonly double[] _colIm;

        public int Width { get; }
        public int Height { get; }

        public Fft2Plan(int width, int height)
        {
            Width = width;
            Height = height;
            _row = new Dft1d(width);
            _col = width == height ? _row : new Dft1d(height);
            _colRe = new double[height];
            _colIm = new double[height];
        }

        public void Forward(double[] re, double[] im) => Transform(re, im, inverse: false);

        public void Inverse(double[] re, double[] im) => Transform(re, im, inverse: true);

        private void Transform(double[] re, double[] im, bool inverse)
        {
            int w = Width, h = Height;
            for (int y = 0; y < h; y++)
                _row.Transform(re, im, y * w, inverse);
            for (int x = 0; x < w; x++)
            {
                for (int y = 0; y < h; y++)
                {
                    _colRe[y] = re[y * w + x];
                    _colIm[y] = im[y * w + x];
                }
                _col.Transform(_colRe, _colIm, 0, inverse);
                for (int y = 0; y < h; y++)
                {
                    re[y * w + x] = _colRe[y];
                    im[y * w + x] = _colIm[y];
                }
            }
        }
    }

    /// <summary>FFT-based circular convolution with a precomputed kernel spectrum.</summary>
    public static class FftConv
    {
        /// <summary>Precompute the spectrum of a wrapped-coordinate (origin-at-[0,0]) kernel.</summary>
        public static (double[] Re, double[] Im) KernelFft(Fft2Plan plan, ReadOnlySpan<double> kernel)
        {
            var re = kernel.ToArray();
            var im = new double[kernel.Length];
            plan.Forward(re, im);
            return (re, im);
        }

        /// <summary>
        /// Circular convolution of a real field with a precomputed kernel spectrum.
        /// Writes the real result into <paramref name="outRe"/>; <paramref name="scratchIm"/>
        /// is caller-owned scratch of the same length (cleared here).
        /// </summary>
        public static void Convolve(
            Fft2Plan plan,
            ReadOnlySpan<double> field,
            double[] kernelRe,
            double[] kernelIm,
            double[] outRe,
            double[] scratchIm)
        {
            field.CopyTo(outRe);
            Array.Clear(scratchIm, 0, scratchIm.Length);
            plan.Forward(outRe, scratchIm);
            for (int i = 0; i < outRe.Length; i++)
            {
                double a = outRe[i], b = scratchIm[i];
                double c = kernelRe[i], d = kernelIm[i];
                outRe[i] = a * c - b * d;
                scratchIm[i] = a * d + b * c;
            }
            plan.Inverse(outRe, scratchIm);
            // outRe now holds the convolution; the ~1e-16 imaginary residue is discarded.
        }
    }

    /// <summary>
    /// One-dimensional DFT of a fixed length over a contiguous segment.
    /// Radix-2 when the length is a power of two; Bluestein otherwise.
    /// The inverse transform scales by 1/N.
    /// </summary>
    internal sealed class Dft1d
    {
        private readonly int _n;
        private readonly bool _pow2;
        // Radix-2 twiddles: cos/sin(2πk/n) for k < n/2.
        private readonly double[] _cos = Array.Empty<double>();
        private readonly double[] _sin = Array.Empty<double>();
        // Bluestein state: chirp e^{-iπk²/n}, the FFT of its conjugate sequence at
        // power-of-two length m >= 2n-1, and scratch of length m.
        private readonly Dft1d? _inner;
        private readonly double[] _chirpRe = Array.Empty<double>();
        private readonly double[] _chirpIm = Array.Empty<double>();
        private readonly double[] _bFftRe = Array.Empty<double>();
        private readonly double[] _bFftIm = Array.Empty<double>();
        private readonly double[] _aRe = Array.Empty<double>();
        private readonly double[] _aIm = Array.Empty<double>();

        public Dft1d(int n)
        {
            if (n < 1)
                throw new ArgumentOutOfRangeException(nameof(n));
            _n = n;
            _pow2 = (n & (n - 1)) == 0;
            if (_pow2)
            {
                _cos = new double[Math.Max(n / 2, 1)];
                _sin = new double[Math.Max(n / 2, 1)];
                for (int k = 0; k < n / 2; k++)
                {
                    double angle = 2.0 * Math.PI * k / n;
                    _cos[k] = Math.Cos(angle);
                    _sin[k] = Math.Sin(angle);
                }
                return;
            }

            int m = 1;
            while (m < 2 * n - 1)
                m <<= 1;
            _inner = new Dft1d(m);
            _chirpRe = new double[n];
            _chirpIm = new double[n];
            for (int k = 0; k < n; k++)
            {
                // k² mod 2n keeps the angle argument small and exact.
                long sq = (long)k * k % (2L * n);
                double angle = -Math.PI * sq / n;
                _chirpRe[k] = Math.Cos(angle);
                _chirpIm[k] = Math.Sin(angle);
            }
            _bFftRe = new double[m];
            _bFftIm = new double[m];
            _bFftRe[0] = _chirpRe[0]; // = 1
            _bFftIm[0] = -_chirpIm[0]; // = 0
            for (int k = 1; k < n; k++)
            {
                // b[k] = b[m-k] = conj(chirp[k]), arranged circularly.
                _bFftRe[k] = _bFftRe[m - k] = _chirpRe[k];
                _bFftIm[k] = _bFftIm[m - k] = -_chirpIm[k];
            }
            _inner.Transform(_bFftRe, _bFftIm, 0, inverse: false);
            _aRe = new double[m];
            _aIm = new double[m];
        }

        public void Transform(double[] re, double[] im, int offset, bool inverse)
        {
            if (_n == 1)
                return;
            if (!inverse)
            {
                Forward(re, im, offset);
                return;
            }
            // IDFT(x) = conj(DFT(conj(x))) / n
            for (int i = 0; i < _n; i++)
                im[offset + i] = -im[offset + i];
            Forward(re, im, offset);
            double scale = 1.0 / _n;
            for (int i = 0; i < _n; i++)
            {
                re[offset + i] *= scale;
                im[offset + i] = -im[offset + i] * scale;
            }
        }

        private void Forward(double[] re, double[] im, int offset)
        {
            if (_pow2)
                ForwardPow2(re, im, offset);
            else
                ForwardBluestein(re, im, offset);
        }

        private void ForwardPow2(double[] re, double[] im, int offset)
        {
            int n = _n;
            for (int i = 1, j = 0; i < n; i++)
            {
                int bit = n >> 1;
                for (; (j & bit) != 0; bit >>= 1)
                    j ^= bit;
                j ^= bit;
                if (i < j)
                {
                    (re[offset + i], re[offset + j]) = (re[offset + j], re[offset + i]);
                    (im[offset + i], im[offset + j]) = (im[offset + j], im[offset + i]);
                }
            }
            for (int len = 2; len <= n; len <<= 1)
            {
                int half = len >> 1;
                int step = n / len;
                for (int block = 0; block < n; block += len)
                {
                    for (int j = 0; j < half; j++)
                    {
                        int t = j * step;
                        double wr = _cos[t], wi = -_sin[t]; // e^{-2πi t/n}
                        int a = offset + block + j;
                        int b = a + half;
                        double vr = re[b] * wr - im[b] * wi;
                        double vi = re[b] * wi + im[b] * wr;
                        re[b] = re[a] - vr;
                        im[b] = im[a] - vi;
                        re[a] += vr;
                        im[a] += vi;
                    }
                }
            }
        }

        private void ForwardBluestein(double[] re, double[] im, int offset)
        {
            int n = _n;
            int m = _inner!._n;
            Array.Clear(_aRe, 0, m);
            Array.Clear(_aIm, 0, m);
            for (int k = 0; k < n; k++)
            {
                double xr = re[offset + k], xi = im[offset + k];
                double cr = _chirpRe[k], ci = _chirpIm[k];
                _aRe[k] = xr * cr - xi * ci;
                _aIm[k] = xr * ci + xi * cr;
            }
            _inner.Transform(_aRe, _aIm, 0, inverse: false);
            for (int k = 0; k < m; k++)
            {
                double ar = _aRe[k], ai = _aIm[k];
                double br = _bFftRe[k], bi = _bFftIm[k];
                _aRe[k] = ar * br - ai * bi;
                _aIm[k] = ar * bi + ai * br;
            }
            _inner.Transform(_aRe, _aIm, 0, inverse: true);
            for (int k = 0; k < n; k++)
            {
                double ar = _aRe[k], ai = _aIm[k];
                double cr = _chirpRe[k], ci = _chirpIm[k];
                re[offset + k] = ar * cr - ai * ci;
                im[offset + k] = ar * ci + ai * cr;
            }
        }
    }
}
