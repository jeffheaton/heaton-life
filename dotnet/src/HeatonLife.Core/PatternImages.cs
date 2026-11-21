using System;

namespace HeatonLife
{
    /// <summary>
    /// BMP pattern images (spec/formats.md "Images"): a pixel is a cell, dead when white and
    /// alive otherwise. The core header and the info header with its later versions; 1-, 4-
    /// and 8-bit palettes, 16-, 24- and 32-bit color, and the bit-field masks the spec lists.
    /// PNG images are <see cref="PngGrid.DecodeLive"/>. The Python reference's
    /// heaton_life.init.images.
    /// </summary>
    internal static class PatternImages
    {
        /// <summary><c>BM</c> and an info header size this reader knows.</summary>
        internal static bool IsBmp(byte[] data)
        {
            if (data.Length < 18 || data[0] != (byte)'B' || data[1] != (byte)'M')
                return false;
            uint size = U32(data, 14);
            return size == 12 || size == 40 || size == 52 || size == 56 || size == 108 || size == 124;
        }

        private static uint U32(byte[] data, int at)
            => (uint)(data[at] | data[at + 1] << 8 | data[at + 2] << 16 | data[at + 3] << 24);

        private static int U16(byte[] data, int at) => data[at] | data[at + 1] << 8;

        private static void CheckLimit(long width, long height, long? maxCells)
        {
            if (maxCells != null && width * height > maxCells.Value)
                throw new ArgumentException(
                    $"the image is {width} x {height} pixels, past the limit of {maxCells.Value} cells");
            if (width * height > int.MaxValue)
                throw new ArgumentException($"the image is {width} x {height} pixels, more than one array holds");
        }

        private static bool WholeByte(uint mask)
            => mask == 0xFFu || mask == 0xFF00u || mask == 0xFF0000u || mask == 0xFF000000u;

        /// <summary>A BMP image's cells, 1 alive and 0 dead (white); refused past <paramref name="maxCells"/>.</summary>
        internal static byte[] BmpLive(byte[] data, long? maxCells, out int width, out int height)
        {
            if (!IsBmp(data))
                throw new FormatException("not a BMP: bad signature or header size");
            long offset = U32(data, 10);
            int header = (int)U32(data, 14);
            if (data.Length < 14 + header)
                throw new FormatException("not a BMP: the info header runs past the end of the file");
            int bits, entry;
            uint compression, colors;
            bool topDown;
            long w, h;
            if (header == 12)
            {
                w = U16(data, 18);
                h = U16(data, 20);
                bits = U16(data, 24);
                compression = 0;
                colors = 0;
                entry = 3;
                topDown = false;
                if (w == 0 || h == 0)
                    throw new FormatException($"not a BMP: an image {w} x {h}");
                if (bits != 1 && bits != 4 && bits != 8 && bits != 24)
                    throw new FormatException($"unsupported BMP: {bits} bits a pixel in a core header");
            }
            else
            {
                w = (int)U32(data, 18);
                h = (int)U32(data, 22);
                bits = U16(data, 28);
                compression = U32(data, 30);
                colors = U32(data, 46);
                entry = 4;
                topDown = h < 0;
                if (w < 1 || h == 0)
                    throw new FormatException($"not a BMP: an image {w} x {h}");
                h = Math.Abs(h);
            }
            CheckLimit(w, h, maxCells);

            uint maskR = 0, maskG = 0, maskB = 0;
            bool fields = false;
            if (compression == 0)
            {
                if (bits != 1 && bits != 4 && bits != 8 && bits != 16 && bits != 24 && bits != 32)
                    throw new FormatException($"unsupported BMP: {bits} bits a pixel");
            }
            else if (compression == 3)
            {
                if (bits != 16 && bits != 32)
                    throw new FormatException($"unsupported BMP: bit fields with {bits} bits a pixel");
                if (data.Length < 66)
                    throw new FormatException("not a BMP: the bit field masks run past the end of the file");
                maskR = U32(data, 54);
                maskG = U32(data, 58);
                maskB = U32(data, 62);
                fields = true;
                bool known = bits == 16
                    ? (maskR == 0xF800 || maskR == 0x7C00) && maskG == (maskR == 0xF800 ? 0x07E0u : 0x03E0u) && maskB == 0x001F
                    : WholeByte(maskR) && WholeByte(maskG) && WholeByte(maskB)
                        && maskR != maskG && maskG != maskB && maskR != maskB;
                if (!known)
                    throw new FormatException(
                        $"unsupported BMP: {bits}-bit masks 0x{maskR:X}, 0x{maskG:X}, 0x{maskB:X}");
            }
            else
            {
                throw new FormatException($"unsupported BMP compression {compression}");
            }

            long stride = (w * bits + 31) / 32 * 4;
            if (offset + stride * h > data.Length)
                throw new FormatException("not a BMP: the pixel data ends before the last row");
            width = (int)w;
            height = (int)h;
            var cells = new byte[width * height];

            bool[]? white = null;
            int usable = 0;
            if (bits <= 8)
            {
                long count = colors == 0 ? 1L << bits : colors;
                usable = (int)Math.Min(count, 1L << bits);
                int start = 14 + header;
                if (start + (long)usable * entry > data.Length)
                    throw new FormatException("not a BMP: the palette runs past the end of the file");
                white = new bool[usable];
                for (int i = 0; i < usable; i++)
                {
                    int at = start + i * entry;
                    white[i] = data[at] == 255 && data[at + 1] == 255 && data[at + 2] == 255;
                }
            }
            uint need = fields ? maskR | maskG | maskB : bits == 16 ? 0x7FFFu : 0x00FFFFFFu;

            for (int y = 0; y < height; y++)
            {
                long row = offset + (topDown ? y : height - 1 - y) * stride;
                for (int x = 0; x < width; x++)
                {
                    bool alive;
                    if (bits <= 8)
                    {
                        int index;
                        if (bits == 8)
                            index = data[row + x];
                        else if (bits == 4)
                            index = (data[row + (x >> 1)] >> ((x & 1) == 0 ? 4 : 0)) & 0x0F;
                        else
                            index = (data[row + (x >> 3)] >> (7 - (x & 7))) & 1;
                        if (index >= usable)
                            throw new FormatException($"BMP pixel index past the palette's {usable} entries");
                        alive = !white![index];
                    }
                    else if (bits == 24)
                    {
                        long at = row + x * 3L;
                        alive = data[at] != 255 || data[at + 1] != 255 || data[at + 2] != 255;
                    }
                    else if (bits == 16)
                    {
                        long at = row + x * 2L;
                        uint word = (uint)(data[at] | data[at + 1] << 8);
                        alive = (word & need) != need;
                    }
                    else
                    {
                        long at = row + x * 4L;
                        uint word = (uint)(data[at] | data[at + 1] << 8 | data[at + 2] << 16 | data[at + 3] << 24);
                        alive = (word & need) != need;
                    }
                    cells[y * width + x] = alive ? (byte)1 : (byte)0;
                }
            }
            return cells;
        }
    }
}
