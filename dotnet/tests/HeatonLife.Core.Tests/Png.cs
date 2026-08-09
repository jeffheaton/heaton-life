using System;
using System.IO;
using System.IO.Compression;

namespace HeatonLife.Tests
{
    /// <summary>
    /// Minimal reader for the conformance vectors' PNGs: 8-bit grayscale or RGB,
    /// non-interlaced (exactly what the Python side writes). Deliberately
    /// dependency-free — "both stacks read the vectors" should not hinge on an
    /// image library.
    /// </summary>
    public static class Png
    {
        public static (int Width, int Height, int Channels, byte[] Pixels) Read(string path)
        {
            byte[] data = File.ReadAllBytes(path);
            if (data.Length < 8 || data[0] != 0x89 || data[1] != (byte)'P')
                throw new InvalidDataException("not a PNG");

            int width = 0, height = 0, bitDepth = 0, colorType = -1;
            using var idat = new MemoryStream();
            int pos = 8;
            while (pos + 8 <= data.Length)
            {
                int length = ReadBigEndian(data, pos);
                string type = System.Text.Encoding.ASCII.GetString(data, pos + 4, 4);
                int body = pos + 8;
                if (type == "IHDR")
                {
                    width = ReadBigEndian(data, body);
                    height = ReadBigEndian(data, body + 4);
                    bitDepth = data[body + 8];
                    colorType = data[body + 9];
                    if (data[body + 12] != 0)
                        throw new InvalidDataException("interlaced PNGs unsupported");
                }
                else if (type == "IDAT")
                {
                    idat.Write(data, body, length);
                }
                else if (type == "IEND")
                {
                    break;
                }
                pos = body + length + 4; // skip CRC
            }
            int channels = colorType switch
            {
                0 => 1, // grayscale
                2 => 3, // RGB
                _ => throw new InvalidDataException(
                    $"vector PNGs are 8-bit grayscale or RGB; got color type {colorType}"),
            };
            if (bitDepth != 8)
                throw new InvalidDataException($"vector PNGs are 8-bit; got depth={bitDepth}");

            idat.Position = 0;
            using var inflate = new ZLibStream(idat, CompressionMode.Decompress);
            using var raw = new MemoryStream();
            inflate.CopyTo(raw);
            byte[] scanlines = raw.ToArray();

            int stride = width * channels;
            var pixels = new byte[stride * height];
            var previous = new byte[stride];
            for (int y = 0; y < height; y++)
            {
                int offset = y * (stride + 1);
                byte filter = scanlines[offset];
                var row = new byte[stride];
                for (int x = 0; x < stride; x++)
                {
                    byte value = scanlines[offset + 1 + x];
                    byte left = x >= channels ? row[x - channels] : (byte)0;
                    byte up = previous[x];
                    byte upLeft = x >= channels ? previous[x - channels] : (byte)0;
                    row[x] = filter switch
                    {
                        0 => value,
                        1 => (byte)(value + left),
                        2 => (byte)(value + up),
                        3 => (byte)(value + (left + up) / 2),
                        4 => (byte)(value + Paeth(left, up, upLeft)),
                        _ => throw new InvalidDataException($"unknown PNG filter {filter}"),
                    };
                }
                Array.Copy(row, 0, pixels, y * stride, stride);
                previous = row;
            }
            return (width, height, channels, pixels);
        }

        private static byte Paeth(byte a, byte b, byte c)
        {
            int p = a + b - c;
            int pa = Math.Abs(p - a), pb = Math.Abs(p - b), pc = Math.Abs(p - c);
            if (pa <= pb && pa <= pc) return a;
            return pb <= pc ? b : c;
        }

        private static int ReadBigEndian(byte[] data, int offset) =>
            (data[offset] << 24) | (data[offset + 1] << 16) | (data[offset + 2] << 8) | data[offset + 3];
    }
}
