using System;
using System.Numerics;

namespace HeatonLife
{
    /// <summary>
    /// The reference-orbit step of spec/deep-zoom.md "Reference orbit" in fixed-width
    /// fixed point on preallocated 32-bit limbs, so a step allocates nothing. The
    /// integer operations and roundings are exactly <see cref="ReferenceOrbit"/>'s
    /// BigInteger ones — products rounded to nearest with ties away from zero on the
    /// magnitude, exact sums, one ties-to-even rounding per sample — so the two produce
    /// the same orbit bit for bit; the BigInteger path stays as the fallback for
    /// centers too large for the fixed width, and as the tests' oracle.
    ///
    /// Why it exists: System.Numerics.BigInteger is immutable, and the BigInteger step
    /// allocated 1.5–4.7 KB of temporaries per iteration — hundreds of megabytes for
    /// one deep orbit, which Unity's non-generational IL2CPP collector pays for in
    /// frame stalls, once per pan.
    ///
    /// Values are sign and magnitude: limbs little-endian, fixed length. A step reads
    /// Z only after its rounded sample passed the stopping rule (|Z| &lt; ~2^167) and
    /// C is limited to |C| &lt; 2^16 (<see cref="Fits"/>), so every product fits.
    /// </summary>
    internal sealed class FixedOrbit
    {
        /// <summary>Largest |center| or |c| (in value, not fixed-point units) the fixed width holds.</summary>
        private const int MaxInputBits = 16;

        private readonly int _bits;
        private readonly int _limbs;
        private readonly bool _burningShip;
        private readonly uint[] _zr, _zi, _cr, _ci, _rr, _ii, _ri, _sum, _product;
        private bool _zrNeg, _ziNeg, _crNeg, _ciNeg;

        /// <summary>
        /// True when |zr|, |zi|, |cr|, |ci| (fixed point at <paramref name="bits"/>) all fit
        /// the width this class sizes for; otherwise the caller uses the BigInteger path.
        /// </summary>
        internal static bool Fits(int bits, BigInteger zr, BigInteger zi, BigInteger cr, BigInteger ci)
        {
            BigInteger limit = BigInteger.One << (bits + MaxInputBits);
            return BigInteger.Abs(zr) < limit && BigInteger.Abs(zi) < limit
                && BigInteger.Abs(cr) < limit && BigInteger.Abs(ci) < limit;
        }

        internal FixedOrbit(bool burningShip, int bits, BigInteger zr, BigInteger zi, BigInteger cr, BigInteger ci)
        {
            _burningShip = burningShip;
            _bits = bits;
            // |Z| stays below 2^167 before a step (the stopping rule), so a step's values
            // stay below ~2^336: F + 340 bits of magnitude, plus a limb of slack.
            _limbs = (bits + 340 + 31) / 32 + 1;
            _zr = new uint[_limbs];
            _zi = new uint[_limbs];
            _cr = new uint[_limbs];
            _ci = new uint[_limbs];
            _rr = new uint[_limbs];
            _ii = new uint[_limbs];
            _ri = new uint[_limbs];
            _sum = new uint[_limbs];
            _product = new uint[2 * _limbs + 1];
            _zrNeg = Load(zr, _zr);
            _ziNeg = Load(zi, _zi);
            _crNeg = Load(cr, _cr);
            _ciNeg = Load(ci, _ci);
        }

        /// <summary>The current Z as BigIntegers (for the orbit cache to resume from).</summary>
        internal (BigInteger Re, BigInteger Im) State => (ToBigInteger(_zrNeg, _zr), ToBigInteger(_ziNeg, _zi));

        /// <summary>
        /// Whether the current Z is small (spec/deep-zoom.md "T2"): 0, or its larger
        /// component's bit length below F − 399 (binade &lt; −400).
        /// </summary>
        internal bool IsSmall
        {
            get
            {
                int top = Math.Max(BitLengthOf(_zr), BitLengthOf(_zi));
                return top == 0 || top - 1 - _bits < ReferenceOrbit.SmallBinade || top - 1 - _bits > ReferenceOrbit.LargeBinade;
            }
        }

        private static int BitLengthOf(uint[] x)
        {
            int used = Used(x);
            return used == 0 ? 0 : (used - 1) * 32 + BitLength(x[used - 1]);
        }

        /// <summary>The current Z rounded to float64, one ties-to-even rounding per component.</summary>
        internal double SampleRe => ToDouble(_zrNeg, _zr);

        internal double SampleIm => ToDouble(_ziNeg, _zi);

        /// <summary>
        /// One step: Z' = (X^2 - Y^2 + Cr, 2XY + Ci), or 2|X||Y| for the Burning Ship, with
        /// every product rounded as ReferenceOrbit.Mul rounds it.
        /// </summary>
        internal void Step()
        {
            MulRound(_zr, _zr, _rr);
            MulRound(_zi, _zi, _ii);
            MulRound(_zr, _zi, _ri);
            bool riNeg = !_burningShip && (_zrNeg != _ziNeg) && !IsZero(_ri);

            // Re: rr - ii + cr  (exact, so the grouping cannot matter)
            bool sumNeg = AddSigned(false, _rr, true, _ii, _sum);
            _zrNeg = AddSigned(sumNeg, _sum, _crNeg, _cr, _zr);

            // Im: 2 * ri + ci
            ShiftLeftOne(_ri);
            _ziNeg = AddSigned(riNeg, _ri, _ciNeg, _ci, _zi);
        }

        // ---- limb arithmetic -------------------------------------------------------

        /// <summary>dest = round(|a| * |b| / 2^bits), ties away from zero (a magnitude).</summary>
        private void MulRound(uint[] a, uint[] b, uint[] dest)
        {
            int la = Used(a), lb = Used(b);
            int lp = la + lb;
            Array.Clear(_product, 0, lp + 1);
            for (int i = 0; i < la; i++)
            {
                ulong carry = 0;
                ulong ai = a[i];
                if (ai == 0)
                    continue;
                for (int j = 0; j < lb; j++)
                {
                    ulong t = ai * b[j] + _product[i + j] + carry;
                    _product[i + j] = (uint)t;
                    carry = t >> 32;
                }
                _product[i + lb] = (uint)carry;
            }

            // + 2^(bits - 1): half an output ulp, so the shift below rounds half up.
            int halfBit = _bits - 1;
            int k = halfBit >> 5;
            ulong add = 1UL << (halfBit & 31);
            while (add != 0 && k <= lp)
            {
                ulong t = _product[k] + add;
                _product[k] = (uint)t;
                add = t >> 32;
                k++;
            }

            // dest = product >> bits
            int limbShift = _bits >> 5;
            int bitShift = _bits & 31;
            for (int i = 0; i < _limbs; i++)
            {
                int src = i + limbShift;
                ulong lo = src <= lp ? _product[src] : 0u;
                ulong hi = src + 1 <= lp ? _product[src + 1] : 0u;
                dest[i] = bitShift == 0 ? (uint)lo : (uint)((lo >> bitShift) | (hi << (32 - bitShift)));
            }
        }

        /// <summary>dest = (aNeg ? -a : a) + (bNeg ? -b : b); returns dest's sign (zero is positive).</summary>
        private bool AddSigned(bool aNeg, uint[] a, bool bNeg, uint[] b, uint[] dest)
        {
            if (aNeg == bNeg)
            {
                ulong carry = 0;
                for (int i = 0; i < _limbs; i++)
                {
                    ulong t = (ulong)a[i] + b[i] + carry;
                    dest[i] = (uint)t;
                    carry = t >> 32;
                }
                return aNeg && !IsZero(dest);
            }
            int cmp = Compare(a, b);
            if (cmp == 0)
            {
                Array.Clear(dest, 0, _limbs);
                return false;
            }
            uint[] big = cmp > 0 ? a : b, small = cmp > 0 ? b : a;
            long borrow = 0;
            for (int i = 0; i < _limbs; i++)
            {
                long t = (long)big[i] - small[i] - borrow;
                borrow = t < 0 ? 1 : 0;
                dest[i] = (uint)(t + (borrow << 32));
            }
            return cmp > 0 ? aNeg : bNeg;
        }

        private void ShiftLeftOne(uint[] x)
        {
            uint carry = 0;
            for (int i = 0; i < _limbs; i++)
            {
                uint next = x[i] >> 31;
                x[i] = (x[i] << 1) | carry;
                carry = next;
            }
        }

        private int Compare(uint[] a, uint[] b)
        {
            for (int i = _limbs - 1; i >= 0; i--)
                if (a[i] != b[i])
                    return a[i] > b[i] ? 1 : -1;
            return 0;
        }

        private static int Used(uint[] x)
        {
            int n = x.Length;
            while (n > 0 && x[n - 1] == 0)
                n--;
            return n;
        }

        private static bool IsZero(uint[] x) => Used(x) == 0;

        /// <summary>
        /// Fixed point to the nearest double, ties to even, subnormals included —
        /// ReferenceOrbit.ToDouble on limbs, rounding at the same ulp.
        /// </summary>
        private double ToDouble(bool negative, uint[] magnitude)
        {
            int used = Used(magnitude);
            if (used == 0)
                return 0.0;
            int length = (used - 1) * 32 + BitLength(magnitude[used - 1]);
            int ulp = Math.Max(length - 1 - _bits - 52, -1074);
            int shift = ulp + _bits;
            long q;
            if (shift <= 0)
            {
                q = (long)(Bits(magnitude, 0, length) << -shift);    // exact: under 53 bits
            }
            else
            {
                q = (long)Bits(magnitude, shift, 54);
                bool half = Bit(magnitude, shift - 1);
                if (half && (AnyBelow(magnitude, shift - 1) || (q & 1) != 0))
                    q++;                                             // ties to even
            }
            return DecimalText.Compose(negative, q, ulp);
        }

        /// <summary>The <paramref name="count"/> (&lt;= 60) bits of x starting at bit <paramref name="start"/>.</summary>
        private static ulong Bits(uint[] x, int start, int count)
        {
            // Three limbs cover any 60-bit window: gather them, shift, mask.
            int limb = start >> 5;
            int offset = start & 31;
            ulong lo = limb < x.Length ? x[limb] : 0u;
            ulong mid = limb + 1 < x.Length ? x[limb + 1] : 0u;
            ulong hi = limb + 2 < x.Length ? x[limb + 2] : 0u;
            ulong window = (lo >> offset) | (mid << (32 - offset)) | (offset == 0 ? 0 : hi << (64 - offset));
            if (offset == 0)
                window = lo | (mid << 32);
            return count >= 64 ? window : window & ((1UL << count) - 1);
        }

        private static bool Bit(uint[] x, int bit) => ((x[bit >> 5] >> (bit & 31)) & 1) != 0;

        /// <summary>True if any bit of x below <paramref name="bit"/> is set.</summary>
        private static bool AnyBelow(uint[] x, int bit)
        {
            int limb = bit >> 5;
            for (int i = 0; i < limb; i++)
                if (x[i] != 0)
                    return true;
            uint mask = (1u << (bit & 31)) - 1;
            return (x[limb] & mask) != 0;
        }

        private static int BitLength(uint x)
        {
            int n = 0;
            while (x != 0)
            {
                n++;
                x >>= 1;
            }
            return n;
        }

        /// <summary>Load a BigInteger's magnitude into limbs; returns its sign.</summary>
        private static bool Load(BigInteger value, uint[] limbs)
        {
            bool negative = value.Sign < 0;
            byte[] bytes = (negative ? -value : value).ToByteArray();
            Array.Clear(limbs, 0, limbs.Length);
            for (int i = 0; i < bytes.Length; i++)
            {
                if (bytes[i] == 0)
                    continue;
                int limb = i >> 2;
                if (limb >= limbs.Length)
                    throw new ArgumentOutOfRangeException(nameof(value), "value exceeds the fixed width");
                limbs[limb] |= (uint)bytes[i] << ((i & 3) * 8);
            }
            return negative;
        }

        private static BigInteger ToBigInteger(bool negative, uint[] limbs)
        {
            var bytes = new byte[limbs.Length * 4 + 1];               // trailing 0: non-negative
            for (int i = 0; i < limbs.Length; i++)
            {
                bytes[4 * i] = (byte)limbs[i];
                bytes[4 * i + 1] = (byte)(limbs[i] >> 8);
                bytes[4 * i + 2] = (byte)(limbs[i] >> 16);
                bytes[4 * i + 3] = (byte)(limbs[i] >> 24);
            }
            var magnitude = new BigInteger(bytes);
            return negative ? -magnitude : magnitude;
        }
    }
}
