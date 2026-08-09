namespace HeatonLife
{
    /// <summary>
    /// Asymptotic Lenia (Kawaguchi et al. 2021): relax toward a target, no clipping.
    /// T(u) = (G(u) + 1) / 2 in [0, 1]; A &lt;- A + dt * (T(K ⊛ A) - A). With dt &lt;= 1
    /// the update is a convex combination, so A stays in [0, 1] naturally.
    /// </summary>
    public sealed class AsymptoticLenia : LeniaBase
    {
        public AsymptoticLenia(
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
            {
                double target = (Growth(potential[i]) + 1.0) / 2.0;
                _state[i] = _state[i] + Dt * (target - _state[i]);
            }
        }
    }
}
