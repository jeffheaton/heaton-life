# heaton-life — .NET implementation (placeholder)

Planned; work starts once the Python implementation and spec v0 stabilize.

## Planned shape

- **`HeatonLife.Core`** — engine-agnostic class library targeting `netstandard2.1` (the profile Unity supports). Flat 1-D row-major arrays (`float[]`, `byte[]`), zero-allocation step/render API (`void Step(int n)`, `void WriteFrame(Span<Color32>)`), managed FFT for Lenia so WebGL keeps working.
- **`HeatonLife.Unity`** — thin UPM package (source + asmdef, installable via git URL): MonoBehaviour wrappers, `[Serializable]` param structs for Inspector editing, frame upload via `Texture2D.GetRawTextureData<Color32>`.
- **Conformance** — the test suite runs the shared vectors in [`../vectors/`](../vectors/). Discrete CAs must match the Python implementation bit-for-bit; float families within spec'd ε.
- **Deep zoom** — the perturbation loop is plain doubles (portable as-is); the high-precision reference orbit uses fixed-point over `System.Numerics.BigInteger`, or consumes orbits exported in the vectors. See [`../spec/deep-zoom.md`](../spec/deep-zoom.md).

No native plugins — pure C# only, so IL2CPP/WebGL/mobile all work.
