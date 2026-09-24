"""Zoom movies (spec/zoom.md): the schedule and plan checked for shape (continuity,
monotonicity, the integral, the ends) rather than bits -- the bits are the conformance
vectors' job -- and the survey, renderer and writer end to end."""

import itertools
import math
import os
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Mandelbrot
from heaton_life.fractal.coloring import Frequency, PhaseParams, ShadeParams
from heaton_life.fractal.movie import (
    UNIFORM,
    MovieSurvey,
    MovieWriter,
    Station,
    ZoomPlan,
    ZoomSchedule,
    _frame_order,
    encode_frames,
    render_zoom_movie,
    survey_movie,
    survey_stations,
)
from heaton_life.fractal.policy import auto_max_iter, measured_max_iter, movie_max_iter, need_at
from heaton_life.render.animate import Animation, close_mp4, even_crop


def test_default_schedule_is_heaton_fractals() -> None:
    r = ZoomSchedule().resolved(30.0)
    assert (r.hold_start, r.ease_in, r.ease_out, r.hold_end) == (3.0, 5.0, 5.0, 5.0)
    assert r.cruise == 12.0
    assert r.effective_seconds == 17.0
    assert r.peak_over_average == 30.0 / 17.0


def test_segments_scale_down_to_ninety_percent() -> None:
    r = ZoomSchedule().resolved(10.0)  # 18 s of segments into a 9 s budget
    assert (r.hold_start, r.ease_in, r.ease_out, r.hold_end) == (1.5, 2.5, 2.5, 2.5)
    assert r.cruise == 1.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0, 0.0])
def test_bad_segments_and_durations_count_as_zero(bad: float) -> None:
    r = ZoomSchedule(bad, bad, bad, bad).resolved(10.0)
    assert (r.hold_start, r.ease_in, r.ease_out, r.hold_end) == (0.0, 0.0, 0.0, 0.0)
    empty = ZoomSchedule().resolved(bad)
    assert empty.duration == 0.0
    assert empty.progress(1.0) == 0.0
    assert empty.speed_fraction(1.0) == 0.0
    assert empty.peak_over_average == 1.0


def test_uniform_progress_is_linear() -> None:
    r = UNIFORM.resolved(8.0)
    assert [r.progress(t) for t in (-1.0, 0.0, 2.0, 4.0, 8.0, 9.0)] == [
        0.0,
        0.0,
        0.25,
        0.5,
        1.0,
        1.0,
    ]
    assert r.speed_fraction(3.0) == 1.0


def test_holds_always_leave_a_cruise() -> None:
    """Holds filling the run are scaled into 90% of it: a tenth still descends."""
    r = ZoomSchedule(1.0, 0.0, 0.0, 1.0).resolved(2.0)
    assert (r.hold_start, r.hold_end) == (0.9, 0.9)
    assert math.isclose(r.cruise, 0.2)
    assert r.progress(0.9) == 0.0
    assert r.progress(1.0) == pytest.approx(0.5)
    assert r.progress(1.1) == 1.0


@pytest.mark.parametrize(
    ("schedule", "duration"),
    [(ZoomSchedule(), 30.0), (ZoomSchedule(), 10.0), (ZoomSchedule(0.0, 4.0, 1.0, 0.0), 12.0)],
)
def test_progress_is_the_integral_of_speed(schedule: ZoomSchedule, duration: float) -> None:
    """Continuous, monotone, 0 to 1, and the running integral of speed_fraction (a
    midpoint sum) scaled so the whole descent is 1."""
    r = schedule.resolved(duration)
    n = 20000
    dt = duration / n
    area = 0.0
    previous = 0.0
    for i in range(n):
        area += r.speed_fraction((i + 0.5) * dt) * dt
        p = r.progress((i + 1) * dt)
        assert p >= previous
        assert p - previous < 1e-3  # no jumps at segment edges
        assert abs(p - area / r.effective_seconds) < 1e-6
        previous = p
    assert r.progress(duration) == 1.0


# --- plan -----------------------------------------------------------------------------


def test_plan_lands_on_both_ends_and_never_overshoots() -> None:
    """The design review's three known answers: a closing hold one ulp short of the end,
    and two plans whose last frame overshot the end under Heaton Fractal's closed form."""
    for plan in (
        ZoomPlan(0.0, 290.0, 120, 24, ZoomSchedule()),
        ZoomPlan(0.0, 9000.0, 364, 60, ZoomSchedule(5.0, 2.0, 0.5, 0.0)),
        ZoomPlan(0.0, 290.0, 58, 50, ZoomSchedule(5.0, 3.0, 0.5, 0.0)),
    ):
        zooms = plan.zooms()
        assert zooms[0] == plan.start_zoom
        assert zooms[-1] == plan.end_zoom
        assert all(a <= b for a, b in itertools.pairwise(zooms))
        assert max(zooms) == plan.end_zoom
        progress = [plan.progress(f) for f in range(plan.frames)]
        assert max(progress) == 1.0 == progress[-1]


def test_progress_clamps_the_ease_out() -> None:
    """Heaton Fractal's ease-out branch returns 1 + 2^-52 here, before the end."""
    plan = ZoomPlan(0.0, 100.0, 2888, 120, ZoomSchedule(1.4, 0.6, 2.2, 1.2))
    assert plan.time(2743) < plan.duration
    assert plan.progress(2743) == 1.0


def test_plan_takes_a_schedule() -> None:
    with pytest.raises(TypeError):
        ZoomPlan(0.0, 1.0, 3, 1, None)  # type: ignore[arg-type]


def test_plan_holds_are_still() -> None:
    plan = ZoomPlan(0.0, 30.0, 30 * 30 + 1, 30, ZoomSchedule())  # 30 s, default schedule
    zooms = plan.zooms()
    assert set(zooms[: 3 * 30 + 1]) == {0.0}  # the 3 s opening hold
    assert set(zooms[-5 * 30 :]) == {30.0}  # the 5 s closing hold


def test_plan_speed_is_decades_per_frame() -> None:
    plan = ZoomPlan(0.0, 10.0, 601, 60)
    assert plan.speed(300) == pytest.approx(10.0 / 600)
    assert plan.speed(600) == pytest.approx(10.0 / 600)  # ends cruising: the left limit
    out = ZoomPlan(10.0, 0.0, 601, 60)
    assert out.speed(300) == pytest.approx(-10.0 / 600)


@pytest.mark.parametrize(
    "args",
    [(0.0, 1.0, 1, 30), (0.0, 1.0, 10, 0), (math.nan, 1.0, 10, 30), (0.0, 10001.0, 10, 30)],
)
def test_plan_rejects_bad_arguments(args: tuple[float, float, int, int]) -> None:
    with pytest.raises(ValueError):
        ZoomPlan(*args)


def test_negative_zero_start_is_positive() -> None:
    plan = ZoomPlan(-0.0, 1.0, 3, 1)
    assert math.copysign(1.0, plan.zoom(0)) == 1.0


# --- budgets and survey ---------------------------------------------------------------


def test_movie_max_iter_reaches_the_limit_at_the_target() -> None:
    # Heaton Fractal's 11 Dimensions preset; U * a overflows 32 bits from zoom ~10.
    target = 219.1498368433709
    got = [movie_max_iter(z, target, 1_100_000) for z in (0.0, 30.0, 200.0, target)]
    assert got == [9947, 159167, 1004747, 1100000]
    assert movie_max_iter(50.0, target) == auto_max_iter(50.0)
    assert movie_max_iter(99.0, 100.0, 1000) == 1000  # a limit below the ramp caps it
    with pytest.raises(ValueError):
        movie_max_iter(0.0, 1.0, 2**31)
    with pytest.raises(ValueError):
        movie_max_iter(0.0, 1.0, 0)


def test_need_at_reads_the_bracketing_knots() -> None:
    knots = [(0.0, 120), (5.0, 3000), (10.0, 900)]
    assert need_at(-1.0, knots) == 120
    assert need_at(2.0, knots) == 3000
    assert need_at(5.0, knots) == 3000
    assert need_at(10.0, knots) == 3000  # at a knot: it and its neighbors
    assert need_at(11.0, knots) == 900
    assert need_at(3.0, []) == 0
    assert measured_max_iter(2.0, knots) == 6000
    assert measured_max_iter(2.0, []) == auto_max_iter(2.0)


SEAHORSE = Viewport("-0.743643887037151", "0.13182590420533")


def test_survey_measures_a_boundary_descent() -> None:
    plan = ZoomPlan(0.0, 3.0, 10, 5)
    survey = survey_movie(lambda n: Mandelbrot(max_iter=n), SEAHORSE, plan)
    assert [s.zoom_log10 for s in survey.stations] == survey_stations(plan)
    assert all(s.need is not None and s.frequency is not None for s in survey.stations)
    for s in survey.stations:
        assert s.need is not None
        assert survey.max_iter(s.zoom_log10) >= 2 * s.need
    limited = survey_movie(lambda n: Mandelbrot(max_iter=n), SEAHORSE, plan, user_limit=5000)
    assert limited.max_iter(3.0) == 5000
    assert all(s.budget == movie_max_iter(s.zoom_log10, 3.0, 5000) for s in limited.stations)


def test_survey_stops_on_proven_interior() -> None:
    """The default center is inside the main cardioid: from about zoom 1.2 every probe
    point is proven interior, so the probe stops at once with no knot."""
    survey = survey_movie(lambda n: Mandelbrot(max_iter=n), Viewport(), ZoomPlan(0.0, 3.0, 10, 5))
    deep = [s for s in survey.stations if s.zoom_log10 > 1.1]
    assert deep
    assert all(s.need is None and s.unresolved == 0 for s in deep)
    assert all(s.budget == auto_max_iter(s.zoom_log10) for s in deep)


def test_survey_phase_interpolates_between_stations() -> None:
    plan = ZoomPlan(0.0, 10.0, 2, 1)
    stations = (
        Station(0.0, 400, 10, 1, 0, 1, Frequency(0.01, 100.0)),
        Station(4.0, 400, 10, 1, 0, 1, None),
        Station(10.0, 400, 10, 1, 0, 1, Frequency(0.002, 900.0)),
    )
    survey = MovieSurvey(plan, stations)
    base = PhaseParams(cycles_per_octave=0.25, phase_offset=0.5)
    mid = survey.phase(5.0, base)
    assert (mid.cycles_per_octave, mid.phase_offset) == (0.25, 0.5)
    assert mid.cycles_per_iteration == pytest.approx(0.006)
    assert mid.anchor == pytest.approx(500.0)
    assert survey.phase(-3.0, base).anchor == 100.0
    assert survey.phase(12.0, base).anchor == 900.0


# --- rendering ------------------------------------------------------------------------


def _field(n: int) -> Mandelbrot:
    return Mandelbrot(max_iter=n)


SHORT = ZoomPlan(0.0, 1.5, 4, 2)


@pytest.fixture(scope="module")
def short_survey() -> MovieSurvey:
    return survey_movie(_field, SEAHORSE, SHORT)


def test_render_zoom_movie_to_png_frames(tmp_path: Path, short_survey: MovieSurvey) -> None:
    render_zoom_movie(_field, (24, 16), SEAHORSE, SHORT, tmp_path / "frames", survey=short_survey)
    names = sorted(p.name for p in (tmp_path / "frames").iterdir())
    assert names == [f"frame_{i:05d}.png" for i in range(4)]
    with Image.open(tmp_path / "frames" / "frame_00003.png") as image:
        assert image.size == (24, 16)
        colors = np.unique(np.asarray(image.convert("RGB")).reshape(-1, 3), axis=0)
        assert len(colors) > 20  # a boundary frame, not a flat one
    # A rerun renders nothing that exists (resume); a range renders only its frames.
    (tmp_path / "frames" / "frame_00002.png").unlink()
    rendered: list[int] = []

    def counting(n: int) -> Mandelbrot:
        rendered.append(n)
        return _field(n)

    render_zoom_movie(counting, (24, 16), SEAHORSE, SHORT, tmp_path / "frames", survey=short_survey)
    assert len(rendered) == 2  # the up-front check, then frame 2
    assert (tmp_path / "frames" / "frame_00002.png").exists()
    render_zoom_movie(
        _field,
        (24, 16),
        SEAHORSE,
        SHORT,
        tmp_path / "part",
        survey=short_survey,
        frames=range(1, 3),
    )
    assert sorted(p.name for p in (tmp_path / "part").iterdir()) == [
        "frame_00001.png",
        "frame_00002.png",
    ]


def test_render_zoom_movie_is_deterministic(tmp_path: Path, short_survey: MovieSurvey) -> None:
    phase = PhaseParams(cycles_per_octave=0.25)
    for name in ("a", "b"):
        render_zoom_movie(
            _field,
            (20, 12),
            SEAHORSE,
            SHORT,
            tmp_path / name,
            survey=short_survey,
            phase=phase,
            supersample=2,
            shade=ShadeParams(),
        )
    for i in range(SHORT.frames):
        a = (tmp_path / "a" / f"frame_{i:05d}.png").read_bytes()
        assert a == (tmp_path / "b" / f"frame_{i:05d}.png").read_bytes()


def _frame(path: Path) -> NDArray[np.float64]:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float64)


def test_octave_term_ignores_size_and_supersample(
    tmp_path: Path, short_survey: MovieSurvey
) -> None:
    """A plane point's octave term depends on its plane radius, not on the output size
    or supersample: with cycles_per_octave 0.25, frames at 1x and 2x supersample, and a
    2x-size frame averaged down, differ only by antialiasing (a phase slip of k log2 ss
    would be tens of levels)."""
    phase = PhaseParams(cycles_per_octave=0.25)
    common = {"survey": short_survey, "phase": phase, "track_color": False, "frames": range(3, 4)}
    render_zoom_movie(_field, (64, 36), SEAHORSE, SHORT, tmp_path / "ss1", **common)
    render_zoom_movie(_field, (64, 36), SEAHORSE, SHORT, tmp_path / "ss2", supersample=2, **common)
    render_zoom_movie(_field, (128, 72), SEAHORSE, SHORT, tmp_path / "big", **common)
    one = _frame(tmp_path / "ss1" / "frame_00003.png")
    two = _frame(tmp_path / "ss2" / "frame_00003.png")
    big = _frame(tmp_path / "big" / "frame_00003.png")
    down = np.sqrt((big**2).reshape(36, 2, 64, 2, 3).mean(axis=(1, 3)))
    assert np.abs(one - two).mean() < 12.0
    assert np.abs(two - down).mean() < 6.0


def test_render_zoom_movie_checks_before_the_survey(tmp_path: Path) -> None:
    calls: list[int] = []

    def counting(n: int) -> Mandelbrot:
        calls.append(n)
        return _field(n)

    ship = ZoomPlan(0.0, 300.0, 2, 1)
    with pytest.raises(ValueError, match="past this family"):
        render_zoom_movie(lambda n: BurningShip(max_iter=n), (8, 8), SEAHORSE, ship, tmp_path / "x")
    with pytest.raises(ValueError, match="distance"):
        render_zoom_movie(
            lambda n: BurningShip(max_iter=n),
            (8, 8),
            SEAHORSE,
            SHORT,
            tmp_path / "y",
            shade=ShadeParams(),
        )
    for frames in (range(2, 7), range(-1, 2)):
        with pytest.raises(ValueError, match="frames"):
            render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, tmp_path / "z", frames=frames)
    with pytest.raises(TypeError):
        render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, tmp_path / "z", frames=[0, 1])  # type: ignore[arg-type]
    other = survey_movie(_field, SEAHORSE, SHORT, user_limit=500)
    with pytest.raises(ValueError, match="user_limit"):
        render_zoom_movie(
            counting, (8, 8), SEAHORSE, SHORT, tmp_path / "z", survey=other, user_limit=700
        )
    with pytest.raises(ValueError, match="another plan"):
        render_zoom_movie(
            counting, (8, 8), SEAHORSE, ZoomPlan(0.0, 1.0, 4, 2), tmp_path / "z", survey=other
        )
    assert calls == []  # nothing rendered, not even the up-front field
    assert not (tmp_path / "x").exists() or not any((tmp_path / "x").iterdir())


def test_mp4_output_fails_before_the_survey(tmp_path: Path) -> None:
    pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    calls: list[int] = []

    def counting(n: int) -> Mandelbrot:
        calls.append(n)
        return _field(n)

    with pytest.raises(FileNotFoundError):
        render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, tmp_path / "missing" / "m.mp4")
    assert calls == [1]  # the family check only: no probe, no frame
    with MovieWriter(tmp_path / "m.mp4", 12) as writer, pytest.raises(ValueError, match="fps"):
        render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, writer)
    with pytest.raises(ValueError, match="consecutive"):
        render_zoom_movie(
            counting, (8, 8), SEAHORSE, SHORT, tmp_path / "m.mp4", frames=range(0, 4, 2)
        )
    assert calls == [1, 1, 1]


def test_mp4_keeps_1080p(tmp_path: Path) -> None:
    """imageio's default macro block of 16 would stretch 1080 rows to 1088."""
    imageio = pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    with MovieWriter(tmp_path / "m.mp4", 30) as writer:
        writer.write(0, frame)
        writer.write(1, frame)
        with pytest.raises(ValueError):
            writer.write(5, frame)
    assert imageio.get_reader(tmp_path / "m.mp4").get_data(0).shape == (1080, 1920, 3)
    Animation([np.zeros((480, 854, 3), dtype=np.uint8)] * 2).save(tmp_path / "a.mp4")
    assert imageio.get_reader(tmp_path / "a.mp4").get_data(0).shape == (480, 854, 3)
    frames = tmp_path / "frames"
    with MovieWriter(frames, 30) as writer:
        writer.write(1, frame[:100, :200])
        writer.write(0, frame[:100, :200])
    encode_frames(frames, tmp_path / "e.mp4", 30)
    assert imageio.get_reader(tmp_path / "e.mp4").count_frames() == 2


def test_frames_encode_in_numeric_order(tmp_path: Path) -> None:
    """Past frame 99,999 the names grow a digit: the order is numeric, not by name, and a
    gap (a failed shard) is an error rather than a jump."""
    names = [Path(f"frame_{i:05d}.png") for i in range(100002)]
    shuffled = sorted(names)  # by name: frame_100000.png lands after frame_10000.png
    assert shuffled != names
    assert _frame_order(shuffled + [Path(".frame_00007.png.part"), Path("notes.txt")]) == names
    with pytest.raises(ValueError, match="missing 2 frame"):
        _frame_order(names[:5] + names[7:9])
    with MovieWriter(tmp_path / "frames", 30) as writer:
        with pytest.raises(ValueError):
            writer.write(-1, np.zeros((4, 4, 3), dtype=np.uint8))
        writer.write(1, np.zeros((4, 4, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="missing 1 frame"):
        encode_frames(tmp_path / "frames", tmp_path / "gap.mp4", 30)


def test_mp4_target_problems_fail_before_the_survey(tmp_path: Path) -> None:
    """ffmpeg starts only at the first frame, so the writer checks the target itself; a
    passed writer's state and a frame under 2 x 2 are checked up front too."""
    pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    calls: list[int] = []

    def counting(n: int) -> Mandelbrot:
        calls.append(n)
        return _field(n)

    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, locked / "m.mp4")
    finally:
        locked.chmod(0o755)
    with pytest.raises(ValueError, match="2 x 2"):
        render_zoom_movie(counting, (1, 8), SEAHORSE, SHORT, tmp_path / "thin.mp4")
    closed = MovieWriter(tmp_path / "closed.mp4", SHORT.fps)
    closed.close()
    with pytest.raises(ValueError, match="closed"):
        render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, closed)
    assert calls == [1, 1, 1]  # the family check only: no probe, no frame
    with MovieWriter(tmp_path / "a.mp4", SHORT.fps) as writer:
        writer.write(0, np.zeros((8, 8, 3), dtype=np.uint8))
        with pytest.raises(ValueError, match="expected frame 1"):
            render_zoom_movie(counting, (8, 8), SEAHORSE, SHORT, writer, frames=range(3, 4))
    assert calls == [1, 1, 1, 1]
    with pytest.raises(ValueError, match="2 x 2"):
        even_crop(np.zeros((9, 1, 3), dtype=np.uint8))


def test_close_mp4_wants_a_whole_movie(tmp_path: Path) -> None:
    """imageio-ffmpeg never checks ffmpeg's exit status: close_mp4 requires the file to
    be an MP4 whose top-level boxes cover it and include moov."""

    class Quiet:
        def close(self) -> None:
            pass

    def box(kind: bytes, body: bytes) -> bytes:
        return (8 + len(body)).to_bytes(4, "big") + kind + body

    target = tmp_path / "m.mp4"
    close_mp4(Quiet(), target, 0)  # no frames: nothing to check
    with pytest.raises(OSError, match="no whole movie"):
        close_mp4(Quiet(), target, 3)  # missing
    whole = box(b"ftyp", b"isom") + box(b"mdat", b"x" * 40) + box(b"moov", b"y" * 20)
    for broken in (b"", whole[:-5], box(b"ftyp", b"isom") + box(b"mdat", b"x" * 40)):
        target.write_bytes(broken)  # empty, a cut trailer, no moov
        with pytest.raises(OSError, match="no whole movie"):
            close_mp4(Quiet(), target, 3)
    target.write_bytes(whole)
    close_mp4(Quiet(), target, 3)
    large = (1).to_bytes(4, "big") + b"mdat" + (24).to_bytes(8, "big") + b"z" * 8
    target.write_bytes(box(b"ftyp", b"isom") + large + (0).to_bytes(4, "big") + b"moov")
    close_mp4(Quiet(), target, 3)  # a 64-bit size, and a last box to the end


def test_mp4_rewrites_in_place_and_expands_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saving over a movie at once works (no timestamp to trip on), a writable movie in a
    read-only directory is overwritten in place, and ~ means home, as imageio reads it."""
    imageio = pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    frames = [np.full((16, 16, 3), v, dtype=np.uint8) for v in (0, 90, 180)]
    target = tmp_path / "again.mp4"
    for _ in range(3):
        Animation(frames).save(target)
    assert imageio.get_reader(target).count_frames() == 3
    folder = tmp_path / "ro"
    folder.mkdir()
    Animation(frames).save(folder / "w.mp4")
    folder.chmod(0o555)
    try:
        Animation(frames).save(folder / "w.mp4")
    finally:
        folder.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    with MovieWriter("~/home.mp4", 10) as writer:
        for i, rgb in enumerate(frames):
            writer.write(i, rgb)
    assert imageio.get_reader(tmp_path / "home.mp4").count_frames() == 3


def test_mp4_targets_resolve_once_and_survive_bad_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad first frame leaves an existing movie alone; the target is resolved once
    (a later chdir does not move it; '~draft' is a name, not a home); a FIFO is refused
    before anything runs."""
    imageio = pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    good = [np.full((16, 16, 3), v, dtype=np.uint8) for v in (0, 120)]
    target = tmp_path / "keep.mp4"
    Animation(good).save(target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match="2 x 2"):
        Animation([np.zeros((1, 9, 3), dtype=np.uint8)]).save(target)
    with pytest.raises(ValueError, match="uint8"), MovieWriter(target, 30) as writer:
        writer.write(0, np.zeros((8, 8, 5), dtype=np.uint8))
    assert target.read_bytes() == before
    monkeypatch.chdir(tmp_path)
    writer = MovieWriter("moved.mp4", 30)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "moved.mp4").write_bytes(b"unrelated")
    monkeypatch.chdir(elsewhere)
    for i, rgb in enumerate(good):
        writer.write(i, rgb)
    writer.close()
    assert imageio.get_reader(tmp_path / "moved.mp4").count_frames() == 2
    assert (elsewhere / "moved.mp4").read_bytes() == b"unrelated"
    monkeypatch.chdir(tmp_path)
    Animation(good).save("~draft.mp4")
    assert imageio.get_reader(tmp_path / "~draft.mp4").count_frames() == 2
    fifo = tmp_path / "pipe.mp4"
    os.mkfifo(fifo)
    with pytest.raises(OSError, match="regular file"):
        MovieWriter(fifo, 30)
