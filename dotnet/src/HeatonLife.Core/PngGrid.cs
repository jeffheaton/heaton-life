using System;
using System.IO;
using System.IO.Compression;

namespace HeatonLife
{
    /// <summary>
    /// Minimal PNG codec for grid I/O (spec/png-io.md): encodes 8-bit truecolor
    /// RGB (scanline filter 0, non-interlaced) and decodes 8-bit RGB or RGBA
    /// (any scanline filter 0–4, non-interlaced; alpha is dropped). Scale-aware:
    /// each cell renders as a scale×scale block on encode; decode samples the
    /// top-left pixel of each block. Dependency-free — System.IO.Compression's
    /// DeflateStream ships with netstandard2.1; the 2-byte zlib header and the
    /// Adler-32 trailer around it are written and skipped by hand.
    /// </summary>
    public static class PngGrid
    {
        private static readonly byte[] Signature = { 137, 80, 78, 71, 13, 10, 26, 10 };

        /// <summary>Encode an RGB cell grid as PNG with each cell a scale×scale block.</summary>
        public static byte[] EncodeRgb(ReadOnlySpan<byte> rgb, int width, int height, int scale = 1)
        {
            if (scale < 1)
                throw new ArgumentException("scale must be >= 1");
            if (width <= 0 || height <= 0 || rgb.Length != width * height * 3)
                throw new ArgumentException(
                    $"expected {width * height * 3} rgb bytes, got {rgb.Length}");
            int outWidth = width * scale;
            int outHeight = height * scale;
            var raw = new byte[outHeight * (1 + outWidth * 3)];
            int pos = 0;
            for (int y = 0; y < outHeight; y++)
            {
                raw[pos++] = 0; // filter: None
                int sourceRow = (y / scale) * width * 3;
                for (int x = 0; x < outWidth; x++)
                {
                    int source = sourceRow + (x / scale) * 3;
                    raw[pos++] = rgb[source];
                    raw[pos++] = rgb[source + 1];
                    raw[pos++] = rgb[source + 2];
                }
            }

            using var output = new MemoryStream();
            output.Write(Signature, 0, Signature.Length);
            var ihdr = new byte[13];
            WriteBigEndian(ihdr, 0, outWidth);
            WriteBigEndian(ihdr, 4, outHeight);
            ihdr[8] = 8;  // bit depth
            ihdr[9] = 2;  // color type: truecolor RGB
            ihdr[10] = 0; // compression
            ihdr[11] = 0; // filter method
            ihdr[12] = 0; // interlace: none
            WriteChunk(output, "IHDR", ihdr);

            using (var idat = new MemoryStream())
            {
                idat.WriteByte(0x78); // zlib CMF
                idat.WriteByte(0x01); // zlib FLG (no preset dict, fastest)
                using (var deflate = new DeflateStream(idat, CompressionLevel.Optimal, leaveOpen: true))
                    deflate.Write(raw, 0, raw.Length);
                uint adler = Adler32(raw);
                idat.WriteByte((byte)(adler >> 24));
                idat.WriteByte((byte)(adler >> 16));
                idat.WriteByte((byte)(adler >> 8));
                idat.WriteByte((byte)adler);
                WriteChunk(output, "IDAT", idat.ToArray());
            }

            WriteChunk(output, "IEND", Array.Empty<byte>());
            return output.ToArray();
        }

        /// <summary>
        /// Decode PNG bytes to an RGB cell grid at 1/scale resolution. Accepts 8-bit
        /// truecolor with or without alpha, non-interlaced; anything else throws.
        /// </summary>
        public static byte[] DecodeRgb(byte[] png, int scale, out int width, out int height)
        {
            if (scale < 1)
                throw new ArgumentException("scale must be >= 1");
            if (png == null || png.Length < 8)
                throw new ArgumentException("not a PNG: too short");
            for (int i = 0; i < Signature.Length; i++)
                if (png[i] != Signature[i])
                    throw new ArgumentException("not a PNG: bad signature");

            int imageWidth = 0;
            int imageHeight = 0;
            int channels = 0;
            bool sawHeader = false;
            using var idat = new MemoryStream();
            int position = 8;
            while (position + 8 <= png.Length)
            {
                int length = ReadBigEndian(png, position);
                string type = System.Text.Encoding.ASCII.GetString(png, position + 4, 4);
                int dataStart = position + 8;
                if (length < 0 || dataStart + length + 4 > png.Length)
                    throw new ArgumentException("not a PNG: truncated chunk");
                if (type == "IHDR")
                {
                    imageWidth = ReadBigEndian(png, dataStart);
                    imageHeight = ReadBigEndian(png, dataStart + 4);
                    int bitDepth = png[dataStart + 8];
                    int colorType = png[dataStart + 9];
                    int interlace = png[dataStart + 12];
                    if (bitDepth != 8)
                        throw new ArgumentException($"unsupported PNG: bit depth {bitDepth} (need 8)");
                    if (colorType == 2)
                        channels = 3;
                    else if (colorType == 6)
                        channels = 4;
                    else
                        throw new ArgumentException(
                            $"unsupported PNG: color type {colorType} (need truecolor RGB or RGBA)");
                    if (interlace != 0)
                        throw new ArgumentException("unsupported PNG: interlaced");
                    sawHeader = true;
                }
                else if (type == "IDAT")
                {
                    idat.Write(png, dataStart, length);
                }
                else if (type == "IEND")
                {
                    break;
                }
                position = dataStart + length + 4; // skip CRC
            }
            if (!sawHeader || imageWidth <= 0 || imageHeight <= 0)
                throw new ArgumentException("not a PNG: missing IHDR");
            if (imageWidth % scale != 0 || imageHeight % scale != 0)
                throw new ArgumentException(
                    $"image {imageWidth}x{imageHeight} is not a multiple of scale {scale}");

            byte[] raw = Inflate(idat.ToArray(), imageHeight * (1 + imageWidth * channels));
            byte[] pixels = Unfilter(raw, imageWidth, imageHeight, channels);

            width = imageWidth / scale;
            height = imageHeight / scale;
            var grid = new byte[width * height * 3];
            for (int y = 0; y < height; y++)
            {
                int sourceRow = y * scale * imageWidth * channels;
                for (int x = 0; x < width; x++)
                {
                    int source = sourceRow + x * scale * channels;
                    int target = (y * width + x) * 3;
                    grid[target] = pixels[source];
                    grid[target + 1] = pixels[source + 1];
                    grid[target + 2] = pixels[source + 2];
                }
            }
            return grid;
        }

        // ---- pattern images (spec/formats.md "Images") ------------------------------

        /// <summary>Whether the bytes begin with PNG's signature.</summary>
        internal static bool HasSignature(byte[] data)
        {
            if (data.Length < Signature.Length)
                return false;
            for (int i = 0; i < Signature.Length; i++)
            {
                if (data[i] != Signature[i])
                    return false;
            }
            return true;
        }

        private static readonly (int X0, int Y0, int Dx, int Dy)[] Adam7 =
        {
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
        };

        private static readonly (int X0, int Y0, int Dx, int Dy)[] WholeImage = { (0, 0, 1, 1) };

        private static bool AllowedDepth(int color, int depth) => color switch
        {
            0 => depth == 1 || depth == 2 || depth == 4 || depth == 8 || depth == 16,
            2 or 4 or 6 => depth == 8 || depth == 16,
            3 => depth == 1 || depth == 2 || depth == 4 || depth == 8,
            _ => false,
        };

        /// <summary>
        /// The image's size as <see cref="DecodeLive"/> finds it, its chunks checked as far as
        /// the pixel data but no pixel decoded (spec/formats.md "Measuring").
        /// </summary>
        internal static (long Width, long Height) MeasureLive(byte[] png)
        {
            ReadChunks(png, null, out long width, out long height, out _, out _, out _, out _);
            return (width, height);
        }

        /// <summary>
        /// Walk a PNG's chunks to <c>IEND</c>, checking them as far as the pixel data
        /// (spec/formats.md "Images"): the signature, <c>IHDR</c> first and valid, <c>PLTE</c>,
        /// an <c>IDAT</c> present, a palette for an indexed image. The <c>IDAT</c> bytes go to
        /// <paramref name="idat"/> when one is given.
        /// </summary>
        private static void ReadChunks(
            byte[] png, MemoryStream? idat, out long imageWidth, out long imageHeight, out int depth, out int color,
            out int interlace, out byte[]? palette)
        {
            if (!HasSignature(png))
                throw new FormatException("not a PNG: bad signature");
            depth = 0;
            color = 0;
            interlace = 0;
            imageWidth = 0;
            imageHeight = 0;
            palette = null;
            bool sawHeader = false, sawData = false;
            long position = Signature.Length;
            while (true)
            {
                if (position + 8 > png.Length)
                    throw new FormatException("not a PNG: it ends before IEND");
                long length = (uint)ReadBigEndian(png, (int)position);
                string type = System.Text.Encoding.ASCII.GetString(png, (int)position + 4, 4);
                long body = position + 8;
                if (length > 0x7FFFFFFF || body + length + 4 > png.Length)
                    throw new FormatException("not a PNG: a chunk runs past the end of the file");
                if (!sawHeader && type != "IHDR")
                    throw new FormatException("not a PNG: the first chunk is not IHDR");
                if (type == "IHDR")
                {
                    if (sawHeader || length != 13)
                        throw new FormatException("not a PNG: a broken IHDR");
                    int at = (int)body;
                    imageWidth = (uint)ReadBigEndian(png, at);
                    imageHeight = (uint)ReadBigEndian(png, at + 4);
                    depth = png[at + 8];
                    color = png[at + 9];
                    interlace = png[at + 12];
                    if (imageWidth <= 0 || imageWidth > 0x7FFFFFFF || imageHeight <= 0 || imageHeight > 0x7FFFFFFF)
                        throw new FormatException($"not a PNG: an image {imageWidth} x {imageHeight}");
                    if (!AllowedDepth(color, depth))
                        throw new FormatException($"not a PNG: bit depth {depth} with color type {color}");
                    if (png[at + 10] != 0 || png[at + 11] != 0 || (interlace != 0 && interlace != 1))
                        throw new FormatException("not a PNG: unknown compression, filter, or interlace method");
                    sawHeader = true;
                }
                else if (type == "PLTE")
                {
                    if (palette != null || length == 0 || length % 3 != 0 || length > 768)
                        throw new FormatException("not a PNG: a broken PLTE");
                    palette = new byte[length];
                    Array.Copy(png, body, palette, 0, length);
                }
                else if (type == "IDAT")
                {
                    sawData = true;
                    idat?.Write(png, (int)body, (int)length);
                }
                else if (type == "IEND")
                {
                    break;
                }
                position = body + length + 4; // skip the CRC
            }
            if (!sawData)
                throw new FormatException("not a PNG: no IDAT");
            if (color == 3 && palette == null)
                throw new FormatException("not a PNG: an indexed image without PLTE");
        }

        /// <summary>
        /// A pattern image's cells (spec/formats.md "Images"), 1 alive and 0 dead: any valid PNG,
        /// every color type and bit depth, interlaced or not. White is every color sample at its
        /// largest (a 16-bit sample by its high byte), or a palette entry of (255, 255, 255);
        /// alpha and tRNS are never read. An image past <paramref name="maxCells"/> is refused
        /// before its pixels are decoded.
        /// </summary>
        internal static byte[] DecodeLive(byte[] png, long? maxCells, out int width, out int height)
        {
            using var idat = new MemoryStream();
            ReadChunks(png, idat, out long imageWidth, out long imageHeight, out int depth, out int color,
                out int interlace, out byte[]? palette);
            if (maxCells != null && imageWidth * imageHeight > maxCells.Value)
                throw new ArgumentException(
                    $"the image is {imageWidth} x {imageHeight} pixels, past the limit of {maxCells.Value} cells");
            if (imageWidth * imageHeight > int.MaxValue)
                throw new ArgumentException($"the image is {imageWidth} x {imageHeight} pixels, more than one array holds");
            width = (int)imageWidth;
            height = (int)imageHeight;

            int channels = color switch { 2 => 3, 4 => 2, 6 => 4, _ => 1 };
            int bitsPerPixel = channels * depth;
            int bpp = Math.Max(1, bitsPerPixel / 8);
            var passes = interlace == 1 ? Adam7 : WholeImage;
            long total = 0;
            foreach (var (x0, y0, dx, dy) in passes)
            {
                if (x0 >= width || y0 >= height)
                    continue;
                long pw = (width - x0 + dx - 1) / dx, ph = (height - y0 + dy - 1) / dy;
                total += ph * (1 + (pw * bitsPerPixel + 7) / 8);
            }
            if (total > int.MaxValue)
                throw new ArgumentException("the PNG's image data is more than one array holds");
            byte[] raw;
            try
            {
                raw = Inflate(idat.ToArray(), (int)total);
            }
            catch (Exception e) when (e is ArgumentException || e is InvalidDataException)
            {
                throw new FormatException(e.Message, e);
            }

            int entries = palette == null ? 0 : palette.Length / 3;
            int top = depth >= 8 ? 255 : (1 << depth) - 1;
            var cells = new byte[width * height];
            int offset = 0;
            foreach (var (x0, y0, dx, dy) in passes)
            {
                if (x0 >= width || y0 >= height)
                    continue;
                int pw = (width - x0 + dx - 1) / dx, ph = (height - y0 + dy - 1) / dy;
                int stride = (int)(((long)pw * bitsPerPixel + 7) / 8);
                byte[] rows = UnfilterRows(raw, offset, ph, stride, bpp);
                offset += ph * (stride + 1);
                for (int r = 0; r < ph; r++)
                {
                    int line = r * stride;
                    int target = (y0 + r * dy) * width + x0;
                    for (int c = 0; c < pw; c++)
                    {
                        bool white;
                        if (depth < 8)
                        {
                            int bit = c * depth;
                            int sample = (rows[line + (bit >> 3)] >> (8 - depth - (bit & 7))) & top;
                            if (color == 3)
                            {
                                if (sample >= entries)
                                    throw new FormatException($"PNG pixel index past the palette's {entries} entries");
                                white = palette![sample * 3] == 255 && palette[sample * 3 + 1] == 255
                                    && palette[sample * 3 + 2] == 255;
                            }
                            else
                            {
                                white = sample == top;
                            }
                        }
                        else
                        {
                            int size = depth / 8; // a 16-bit sample is read by its high byte, first
                            int at = line + c * channels * size;
                            if (color == 3)
                            {
                                int index = rows[at];
                                if (index >= entries)
                                    throw new FormatException($"PNG pixel index past the palette's {entries} entries");
                                white = palette![index * 3] == 255 && palette[index * 3 + 1] == 255
                                    && palette[index * 3 + 2] == 255;
                            }
                            else if (color == 0 || color == 4)
                            {
                                white = rows[at] == 255;
                            }
                            else
                            {
                                white = rows[at] == 255 && rows[at + size] == 255 && rows[at + 2 * size] == 255;
                            }
                        }
                        cells[target + c * dx] = white ? (byte)0 : (byte)1;
                    }
                }
            }
            return cells;
        }

        /// <summary>Reverse scanline filters 0–4 over <paramref name="rows"/> rows of
        /// <paramref name="stride"/> bytes (each after its filter byte), from <paramref name="offset"/>.</summary>
        private static byte[] UnfilterRows(byte[] raw, int offset, int rows, int stride, int bpp)
        {
            var output = new byte[(long)rows * stride];
            for (int y = 0; y < rows; y++)
            {
                int rowIn = offset + y * (stride + 1);
                int filter = raw[rowIn];
                int rowOut = y * stride;
                for (int x = 0; x < stride; x++)
                {
                    int value = raw[rowIn + 1 + x];
                    int left = x >= bpp ? output[rowOut + x - bpp] : 0;
                    int up = y > 0 ? output[rowOut - stride + x] : 0;
                    int upLeft = y > 0 && x >= bpp ? output[rowOut - stride + x - bpp] : 0;
                    switch (filter)
                    {
                        case 0: break;
                        case 1: value += left; break;
                        case 2: value += up; break;
                        case 3: value += (left + up) / 2; break;
                        case 4: value += Paeth(left, up, upLeft); break;
                        default:
                            throw new FormatException($"not a PNG: scanline filter {filter}");
                    }
                    output[rowOut + x] = (byte)value;
                }
            }
            return output;
        }

        // ---- internals ----------------------------------------------------------

        private static byte[] Inflate(byte[] zlib, int expectedLength)
        {
            if (zlib.Length < 6)
                throw new ArgumentException("not a PNG: empty image data");
            // Skip the 2-byte zlib header; DeflateStream reads the raw stream.
            using var source = new MemoryStream(zlib, 2, zlib.Length - 2);
            using var inflate = new DeflateStream(source, CompressionMode.Decompress);
            var result = new byte[expectedLength];
            int read = 0;
            while (read < expectedLength)
            {
                int chunk = inflate.Read(result, read, expectedLength - read);
                if (chunk <= 0)
                    break;
                read += chunk;
            }
            if (read != expectedLength)
                throw new ArgumentException(
                    $"not a PNG: expected {expectedLength} raw bytes, got {read}");
            return result;
        }

        /// <summary>Reverse scanline filters 0–4 into flat pixel rows.</summary>
        private static byte[] Unfilter(byte[] raw, int width, int height, int channels)
        {
            int stride = width * channels;
            var pixels = new byte[height * stride];
            for (int y = 0; y < height; y++)
            {
                int filter = raw[y * (stride + 1)];
                int rowIn = y * (stride + 1) + 1;
                int rowOut = y * stride;
                for (int x = 0; x < stride; x++)
                {
                    int value = raw[rowIn + x];
                    int left = x >= channels ? pixels[rowOut + x - channels] : 0;
                    int up = y > 0 ? pixels[rowOut - stride + x] : 0;
                    int upLeft = (y > 0 && x >= channels) ? pixels[rowOut - stride + x - channels] : 0;
                    switch (filter)
                    {
                        case 0: break;
                        case 1: value += left; break;
                        case 2: value += up; break;
                        case 3: value += (left + up) / 2; break;
                        case 4: value += Paeth(left, up, upLeft); break;
                        default:
                            throw new ArgumentException($"unsupported PNG: scanline filter {filter}");
                    }
                    pixels[rowOut + x] = (byte)value;
                }
            }
            return pixels;
        }

        private static int Paeth(int left, int up, int upLeft)
        {
            int initial = left + up - upLeft;
            int distanceLeft = Math.Abs(initial - left);
            int distanceUp = Math.Abs(initial - up);
            int distanceUpLeft = Math.Abs(initial - upLeft);
            if (distanceLeft <= distanceUp && distanceLeft <= distanceUpLeft)
                return left;
            return distanceUp <= distanceUpLeft ? up : upLeft;
        }

        private static void WriteChunk(Stream output, string type, byte[] data)
        {
            var header = new byte[8];
            WriteBigEndian(header, 0, data.Length);
            header[4] = (byte)type[0];
            header[5] = (byte)type[1];
            header[6] = (byte)type[2];
            header[7] = (byte)type[3];
            output.Write(header, 0, 8);
            output.Write(data, 0, data.Length);
            uint crc = Crc32(header, 4, 4, Crc32Seed);
            crc = Crc32(data, 0, data.Length, crc);
            crc ^= 0xFFFFFFFFu;
            output.WriteByte((byte)(crc >> 24));
            output.WriteByte((byte)(crc >> 16));
            output.WriteByte((byte)(crc >> 8));
            output.WriteByte((byte)crc);
        }

        private static void WriteBigEndian(byte[] buffer, int offset, int value)
        {
            buffer[offset] = (byte)(value >> 24);
            buffer[offset + 1] = (byte)(value >> 16);
            buffer[offset + 2] = (byte)(value >> 8);
            buffer[offset + 3] = (byte)value;
        }

        private static int ReadBigEndian(byte[] buffer, int offset) =>
            (buffer[offset] << 24) | (buffer[offset + 1] << 16)
            | (buffer[offset + 2] << 8) | buffer[offset + 3];

        private static uint Adler32(byte[] data)
        {
            uint a = 1, b = 0;
            foreach (byte value in data)
            {
                a = (a + value) % 65521;
                b = (b + a) % 65521;
            }
            return (b << 16) | a;
        }

        private const uint Crc32Seed = 0xFFFFFFFFu;
        private static uint[]? _crcTable;

        /// <summary>The CRC-32 of all of <paramref name="data"/> (PNG's, and gzip's).</summary>
        internal static uint Crc32(byte[] data) => Crc32(data, 0, data.Length, Crc32Seed) ^ 0xFFFFFFFFu;

        private static uint Crc32(byte[] data, int offset, int count, uint crc)
        {
            var table = _crcTable;
            if (table == null)
            {
                table = new uint[256];
                for (uint n = 0; n < 256; n++)
                {
                    uint c = n;
                    for (int k = 0; k < 8; k++)
                        c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                    table[n] = c;
                }
                _crcTable = table;
            }
            for (int i = offset; i < offset + count; i++)
                crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
            return crc;
        }
    }
}
