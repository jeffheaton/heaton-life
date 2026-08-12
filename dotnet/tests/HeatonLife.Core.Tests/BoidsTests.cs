using System;
using Xunit;

namespace HeatonLife.Tests
{
    public class BoidsTests
    {
        private static Boids Make(
            int count,
            double wSep = 0.0,
            double wAlign = 0.0,
            double wCoh = 0.0,
            double perception = 12.0,
            double separationRadius = 6.0,
            BoidsBoundary boundary = BoidsBoundary.Wrap) =>
            new Boids(
                count, 128, 128,
                perception: perception,
                separationRadius: separationRadius,
                wSeparation: wSep,
                wAlignment: wAlign,
                wCohesion: wCoh,
                boundary: boundary);

        [Fact]
        public void ZeroSteeringConservesMomentumExactly()
        {
            var sim = Make(50);
            sim.SeedRandom(4);
            var vel0 = new double[50 * 2];
            for (int i = 0; i < 50; i++)
            {
                vel0[i * 2] = sim.State[i * 4 + 2];
                vel0[i * 2 + 1] = sim.State[i * 4 + 3];
            }
            sim.Step(50);
            for (int i = 0; i < 50; i++)
            {
                Assert.Equal(vel0[i * 2], sim.State[i * 4 + 2]); // bitwise
                Assert.Equal(vel0[i * 2 + 1], sim.State[i * 4 + 3]);
            }
        }

        [Fact]
        public void PositionsAdvanceByVelocityWithWrap()
        {
            var sim = Make(1);
            sim.SetState(new[] { 127.0, 64.0, 2.0, 0.0 });
            sim.Step();
            Assert.Equal((127.0 + 2.0) % 128.0, sim.State[0], 12);
            Assert.Equal(64.0, sim.State[1]);
        }

        [Fact]
        public void CohesionPullsTogether()
        {
            var sim = Make(2, wCoh: 1.0, perception: 20.0);
            sim.SetState(new[] { 60.0, 64.0, 0.0, 1.0, 70.0, 64.0, 0.0, -1.0 });
            double d0 = Math.Abs(sim.State[0] - sim.State[4]);
            sim.Step(10);
            double d1 = Math.Abs(sim.State[0] - sim.State[4]);
            Assert.True(d1 < d0);
        }

        [Fact]
        public void SeparationPushesApart()
        {
            var sim = Make(2, wSep: 1.0, perception: 20.0, separationRadius: 8.0);
            sim.SetState(new[] { 63.0, 64.0, 0.0, 1.0, 65.0, 64.0, 0.0, -1.0 });
            sim.Step(10);
            Assert.True(Math.Abs(sim.State[0] - sim.State[4]) > 2.0);
        }

        [Fact]
        public void WrapKeepsPositionsInWorld()
        {
            var sim = new Boids(100, 96, 64);
            sim.SeedRandom(1);
            sim.Step(100);
            for (int i = 0; i < 100; i++)
            {
                Assert.True(sim.State[i * 4] >= 0.0 && sim.State[i * 4] < 96.0);
                Assert.True(sim.State[i * 4 + 1] >= 0.0 && sim.State[i * 4 + 1] < 64.0);
            }
        }

        [Fact]
        public void BounceReflectsAtWall()
        {
            var sim = Make(1, boundary: BoidsBoundary.Bounce);
            sim.SetState(new[] { 126.5, 64.0, 3.0, 0.0 }); // heading out the right wall
            sim.Step();
            Assert.True(sim.State[0] <= 128.0);
            Assert.True(sim.State[2] < 0.0, "x-velocity must flip on bounce");
        }

        [Fact]
        public void SpeedClampsHoldUnderSteering()
        {
            var sim = new Boids(80, 128, 128); // default weights on
            sim.SeedRandom(6);
            sim.Step(30);
            for (int i = 0; i < 80; i++)
            {
                double vx = sim.State[i * 4 + 2], vy = sim.State[i * 4 + 3];
                double speed = Math.Sqrt(vx * vx + vy * vy);
                Assert.True(speed <= sim.MaxSpeed + 1e-9);
                Assert.True(speed >= sim.MinSpeed - 1e-9);
            }
        }

        [Fact]
        public void Determinism()
        {
            var a = new Boids(40, 64, 64);
            var b = new Boids(40, 64, 64);
            a.SeedRandom(9);
            b.SeedRandom(9);
            a.Step(20);
            b.Step(20);
            Assert.Equal(a.State.ToArray(), b.State.ToArray());
        }

        [Fact]
        public void NudgeScaresAndLuresInPlane()
        {
            var sim = Make(2);
            sim.SetState(new[]
            {
                64.0, 64.0, 0.0, 0.0,
                80.0, 64.0, 0.0, 0.0,
            });
            sim.Nudge(60.0, 64.0, radius: 10.0, strength: 2.0);
            Assert.Equal(2.0, sim.State[2], 12); // boid 0 (dist 4): full strength, +x
            Assert.Equal(0.0, sim.State[3]);
            Assert.Equal(0.0, sim.State[4 + 2]); // boid 1 (dist 20): outside the radius
            sim.Nudge(60.0, 64.0, radius: 10.0, strength: -2.0); // a lure undoes the scare
            Assert.Equal(0.0, sim.State[2], 12);
        }

        [Fact]
        public void NudgeWrapsMinimumImageAndRespectsWalls()
        {
            // Click near the right wall: the boid across the seam is 4 units away
            // through the wrap (not 124 across the box) and gets pushed +x.
            var sim = Make(1);
            sim.SetState(new[] { 2.0, 64.0, 0.0, 0.0 });
            sim.Nudge(126.0, 64.0, radius: 10.0, strength: 1.0);
            Assert.Equal(1.0, sim.State[2], 12);
            // With walls the same click really is 124 units away: out of range.
            var walls = Make(1, boundary: BoidsBoundary.Bounce);
            walls.SetState(new[] { 2.0, 64.0, 0.0, 0.0 });
            walls.Nudge(126.0, 64.0, radius: 10.0, strength: 1.0);
            Assert.Equal(0.0, walls.State[2]);
        }

        [Fact]
        public void NudgeSkipsTheExactPointAndKeepsGeneration()
        {
            var sim = Make(1);
            sim.SetState(new[] { 64.0, 64.0, 1.0, 1.0 }, 3);
            sim.Nudge(64.0, 64.0, radius: 48.0, strength: 5.0);
            Assert.Equal(3, sim.Generation); // editing, not physics
            Assert.Equal(1.0, sim.State[2]); // dist == 0: untouched
            Assert.Equal(1.0, sim.State[3]);
        }

        [Fact]
        public void NudgeLeavesZAlone()
        {
            var sim = new Boids(
                1, 128, 128,
                wSeparation: 0.0, wAlignment: 0.0, wCohesion: 0.0, dimensions: 3);
            sim.SetState(new[] { 60.0, 64.0, 30.0, 0.0, 0.0, 0.5 });
            sim.Nudge(56.0, 64.0, radius: 10.0, strength: 2.0);
            Assert.Equal(2.0, sim.State[3], 12); // vx pushed
            Assert.Equal(30.0, sim.State[2]);    // z position untouched
            Assert.Equal(0.5, sim.State[5]);     // vz untouched
        }
    }
}
