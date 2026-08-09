namespace HeatonLife
{
    /// <summary>
    /// A time-stepped system: CA, Lenia, reaction-diffusion, boids — the C# side of
    /// core/protocols.py. Frames are always renderable Height*Width buffers in one of
    /// three shapes, each with its own sub-interface: palette-index bytes (colormapped
    /// via Colormaps.ApplyIndexed*), floats in [0, 1] (Colormaps.ApplyFloat*), or raw
    /// RGB bytes (passed through). A host like the Unity adapter drives everything
    /// through these five members plus the family's Seed*/SetState methods.
    /// </summary>
    public interface ISimulation
    {
        int Width { get; }

        int Height { get; }

        int Generation { get; }

        void Step(int n = 1);
    }

    /// <summary>Frame = Height*Width palette indices (0..255), spec/render.md.</summary>
    public interface IIndexedFrameSource : ISimulation
    {
        /// <summary>Write the current frame into <paramref name="frame"/> (Height*Width bytes).</summary>
        void WriteFrame(byte[] frame);
    }

    /// <summary>Frame = Height*Width floats in [0, 1], spec/render.md.</summary>
    public interface IFloatFrameSource : ISimulation
    {
        /// <summary>Write the current frame into <paramref name="frame"/> (Height*Width doubles).</summary>
        void WriteFrame(double[] frame);
    }

    /// <summary>Frame = Height*Width*3 RGB bytes, passed through uncolormapped.</summary>
    public interface IRgbFrameSource : ISimulation
    {
        /// <summary>Write the current frame into <paramref name="rgb"/> (Height*Width*3 bytes).</summary>
        void WriteFrame(byte[] rgb);
    }
}
