using System;

namespace HeatonLife
{
    /// <summary>Classic Lenia (Chan 2018): A &lt;- clip(A + dt * G(K ⊛ A), 0, 1).</summary>
    public sealed class ClassicLenia : LeniaBase
    {
        public ClassicLenia(
            int width,
            int height,
            int radius = 13,
            double mu = 0.15,
            double sigma = 0.017,
            double dt = 0.1)
            : base(width, height, radius, mu, sigma, dt)
        {
            SeedBlobs(40, 0); // the Python constructor's default init
        }

        private protected override void StepOnce()
        {
            double[] potential = Potential();
            for (int i = 0; i < _state.Length; i++)
                _state[i] = Math.Clamp(_state[i] + Dt * Growth(potential[i]), 0.0, 1.0);
        }
    }
}
