"""Zoom movies -- spec/zoom.md.

A movie descends (or climbs) from one depth to another at a fixed center. The schedule is
Heaton Fractal's (Render/ZoomSchedule.swift), shape for shape, with the end pinned: a
hold, a smoothstep ease in, a cruise, an ease out and a hold, the descent's progress the
closed-form integral of that speed. The plan maps frames to depths; the survey measures,
at stations down the descent, how late the location's points escape (Heaton Fractal's
measured mode) and how its colors move. Schedule, plan, stations and the survey's
patience rule are plain float64 and integer arithmetic in a pinned order, so the C# port
(HeatonLife.ZoomSchedule, ZoomPlan, ZoomSurvey) gives the same bits. Rendering and color
(render_zoom_movie) are presentation.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterable
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.viewport import Viewport
from heaton_life.fractal.coloring import (
    Frequency,
    PhaseParams,
    ShadeParams,
    depth_phase,
    measure_frequency,
    shade_distance,
)
from heaton_life.fractal.engine import EXHAUSTED
from heaton_life.fractal.escape_fields import EscapeFields
from heaton_life.fractal.policy import (
    MAX_SUGGESTION,
    auto_max_iter,
    measured_max_iter,
    movie_max_iter,
    need_from_counts,
)
from heaton_life.render.animate import close_mp4, even_crop, mp4_target, open_mp4, start_mp4
from heaton_life.render.colormap import apply_phase, is_cyclic
from heaton_life.render.dither import tpdf_frame

__all__ = [
    "LOG10_2",
    "MAX_PLAN_ZOOM",
    "UNIFORM",
    "MovieSurvey",
    "MovieWriter",
    "ResolvedSchedule",
    "Station",
    "ZoomPlan",
    "ZoomSchedule",
    "encode_frames",
    "probe_station",
    "render_zoom_movie",
    "survey_cap",
    "survey_movie",
    "survey_stations",
]

LOG10_2 = 0.3010299956639812  # the double nearest log10(2): 0x3FD34413509F79FF
MAX_PLAN_ZOOM = 10000.0  # |zoom| bound: the pinned 10^x's domain (spec/pow10.md)
APPROACH_OCTAVES = (32, 24, 16, 12, 8, 7, 6, 5, 4, 3, 2, 1)
PROBE_SIZE = (192, 108)  # Heaton Fractal's palette pre-pass probe
SURVEY_CAP_FACTOR = 64
REFERENCE_WIDTH = 1920  # the octave term's pixels: a 1920-wide frame of the same view

FloatArray = NDArray[np.float64]
ByteArray = NDArray[np.uint8]


# --- schedule --------------------------------------------------------------------------


def _clean(value: float) -> float:
    return value if math.isfinite(value) and value > 0.0 else 0.0


@dataclasses.dataclass(frozen=True)
class ResolvedSchedule:
    """A schedule fitted to a duration (seconds): every query is a straight evaluation."""

    duration: float
    hold_start: float
    ease_in: float
    ease_out: float
    hold_end: float

    @property
    def cruise(self) -> float:
        """Seconds at full speed between the ramps."""
        return max(
            0.0,
            (((self.duration - self.hold_start) - self.ease_in) - self.ease_out) - self.hold_end,
        )

    @property
    def effective_seconds(self) -> float:
        """The cruise plus half of each ramp: smoothstep integrates to one half."""
        return self.cruise + 0.5 * (self.ease_in + self.ease_out)

    @property
    def peak_over_average(self) -> float:
        """Peak speed as a multiple of the average (1 when nothing descends)."""
        eff = self.effective_seconds
        if not (eff > 0.0 and self.duration > 0.0):
            return 1.0
        return self.duration / eff

    def progress(self, t: float) -> float:
        """The fraction of the descent done by time t, in [0, 1]: 0 through the first
        hold, e0 (x^3 - x^4/2) over the ease in, linear through the cruise, e1 (x - x^3 +
        x^4/2) over the ease out, and exactly 1 from the end of the ease out on (at and
        past the duration too): Heaton Fractal's closed form with its end pinned."""
        duration = self.duration
        if not duration > 0.0:
            return 0.0
        eff = self.effective_seconds
        if not eff > 0.0:
            return 1.0 if t >= duration else 0.0
        if t >= duration:
            return 1.0
        time = max(t, 0.0)
        if time <= self.hold_start:
            return 0.0
        covered = 0.0
        remaining = time - self.hold_start
        ease_in, cruise, ease_out = self.ease_in, self.cruise, self.ease_out
        if ease_in > 0.0:
            if remaining < ease_in:
                x = remaining / ease_in
                return min(1.0, (ease_in * (((x * x) * x) - ((((0.5 * x) * x) * x) * x))) / eff)
            covered += 0.5 * ease_in
            remaining -= ease_in
        if cruise > 0.0:
            if remaining < cruise:
                return min(1.0, (covered + remaining) / eff)
            covered += cruise
            remaining -= cruise
        if ease_out > 0.0 and remaining < ease_out:
            x = remaining / ease_out
            return min(
                1.0,
                (covered + ease_out * ((x - ((x * x) * x)) + ((((0.5 * x) * x) * x) * x))) / eff,
            )
        return 1.0

    def speed_fraction(self, t: float) -> float:
        """The speed at t as a fraction of the peak: smoothstep up, 1, smoothstep down,
        0 through the holds; at and past the duration, the value arriving there (1 when
        the run ends in its cruise, else 0)."""
        if not (self.duration > 0.0 and self.effective_seconds > 0.0):
            return 0.0
        if t >= self.duration:
            ends_cruising = self.ease_out == 0.0 and self.hold_end == 0.0 and self.cruise > 0.0
            return 1.0 if ends_cruising else 0.0
        time = max(t, 0.0)
        if time < self.hold_start:
            return 0.0
        remaining = time - self.hold_start
        if self.ease_in > 0.0:
            if remaining < self.ease_in:
                x = remaining / self.ease_in
                return (x * x) * (3.0 - 2.0 * x)
            remaining -= self.ease_in
        cruise = self.cruise
        if remaining < cruise:
            return 1.0
        remaining -= cruise
        if self.ease_out > 0.0 and remaining < self.ease_out:
            x = remaining / self.ease_out
            return 1.0 - (x * x) * (3.0 - 2.0 * x)
        return 0.0


@dataclasses.dataclass(frozen=True)
class ZoomSchedule:
    """Seconds of hold, ease in, ease out and hold (Heaton Fractal's defaults 3, 5, 5,
    5); ``UNIFORM`` is all zero, a constant speed from the first frame to the last."""

    hold_start: float = 3.0
    ease_in: float = 5.0
    ease_out: float = 5.0
    hold_end: float = 5.0

    def resolved(self, duration: float) -> ResolvedSchedule:
        """Fitted to ``duration``: a segment that is not finite or not positive is 0,
        and segments longer together than 90% of the duration are scaled down together
        (a tenth of the run keeps cruising, up to rounding)."""
        span = duration if math.isfinite(duration) and duration > 0.0 else 0.0
        h0, e0, e1, h1 = (
            _clean(v) for v in (self.hold_start, self.ease_in, self.ease_out, self.hold_end)
        )
        budget = span * 0.9
        shaped = ((h0 + e0) + e1) + h1
        if shaped > budget and shaped > 0.0:
            scale = budget / shaped
            h0, e0, e1, h1 = h0 * scale, e0 * scale, e1 * scale, h1 * scale
        return ResolvedSchedule(span, h0, e0, e1, h1)


UNIFORM = ZoomSchedule(0.0, 0.0, 0.0, 0.0)


# --- plan ------------------------------------------------------------------------------


def _check_int(value: object, name: str, low: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < low:
        raise ValueError(f"{name} must be >= {low}, got {value}")


@dataclasses.dataclass(frozen=True)
class ZoomPlan:
    """Frames 0..frames-1 at fps, from start_zoom to end_zoom (log10 magnification;
    either way), paced by a schedule. Frame f is at t = f / fps seconds of a run of
    (frames - 1) / fps, so the first frame is start_zoom and the last end_zoom."""

    start_zoom: float
    end_zoom: float
    frames: int
    fps: int = 30
    schedule: ZoomSchedule = UNIFORM

    def __post_init__(self) -> None:
        for name in ("start_zoom", "end_zoom"):
            value = getattr(self, name)
            if not (math.isfinite(value) and abs(value) <= MAX_PLAN_ZOOM):
                raise ValueError(f"{name} must be finite with |zoom| <= 10000, got {value!r}")
            object.__setattr__(self, name, float(value) + 0.0)  # a negative zero becomes +0
        _check_int(self.frames, "frames", 2)
        _check_int(self.fps, "fps", 1)
        if not isinstance(self.schedule, ZoomSchedule):
            raise TypeError("schedule must be a ZoomSchedule")

    @property
    def duration(self) -> float:
        """(frames - 1) / fps seconds: the last frame's time."""
        return float(self.frames - 1) / float(self.fps)

    @property
    def resolved(self) -> ResolvedSchedule:
        return self.schedule.resolved(self.duration)

    @property
    def shallowest_zoom(self) -> float:
        return min(self.start_zoom, self.end_zoom)

    @property
    def deepest_zoom(self) -> float:
        return max(self.start_zoom, self.end_zoom)

    def time(self, frame: int) -> float:
        """f / fps seconds."""
        self._check_frame(frame)
        return float(frame) / float(self.fps)

    def progress(self, frame: int) -> float:
        return self.resolved.progress(self.time(frame))

    def zoom(self, frame: int) -> float:
        """start if p == 0, end if p == 1, else start + (end - start) * p held to the
        plan's range."""
        return self._zoom_at(self.progress(frame))

    def zooms(self) -> list[float]:
        """Every frame's zoom, in order."""
        resolved = self.resolved
        return [
            self._zoom_at(resolved.progress(float(f) / float(self.fps))) for f in range(self.frames)
        ]

    def _zoom_at(self, p: float) -> float:
        if p == 0.0:
            return self.start_zoom
        if p == 1.0:
            return self.end_zoom
        lerp = self.start_zoom + (self.end_zoom - self.start_zoom) * p
        if lerp < self.shallowest_zoom:
            return self.shallowest_zoom
        return min(lerp, self.deepest_zoom)

    def speed(self, frame: int) -> float:
        """Decades per frame at the frame (signed; negative zooming out):
        (((end - start) / eff) / fps) * speed_fraction(t). For motion blur and a UI."""
        resolved = self.resolved
        eff = resolved.effective_seconds
        if not eff > 0.0:
            return 0.0
        rate = ((self.end_zoom - self.start_zoom) / eff) / float(self.fps)
        return rate * resolved.speed_fraction(self.time(frame))

    def _check_frame(self, frame: int) -> None:
        _check_int(frame, "frame", 0)
        if frame >= self.frames:
            raise ValueError(f"frame must be < {self.frames}, got {frame}")


# --- survey ----------------------------------------------------------------------------


def survey_stations(plan: ZoomPlan, spacing_octaves: int = 64) -> list[float]:
    """The depths (log10) a survey probes, ascending (after Heaton Fractal's
    PalettePrePass.stations): the shallow end; every spacing_octaves below it while at
    least 33 octaves short of the deep end; the approach, 32, 24, 16, 12, 8, 7, ..., 1
    octaves short of the deep end, where more than an octave past the shallow end; and
    the deep end. The regular and approach stations keep an octave apart; both ends are
    always probed."""
    _check_int(spacing_octaves, "spacing_octaves", 1)
    low, high = plan.shallowest_zoom, plan.deepest_zoom
    step = float(spacing_octaves) * LOG10_2
    regular_limit = high - 33.0 * LOG10_2
    approach_floor = low + LOG10_2
    stations = [low]
    index = 1
    while True:
        zoom = low + float(index) * step
        if not zoom < regular_limit:
            break
        stations.append(zoom)
        index += 1
    for octaves in APPROACH_OCTAVES:
        zoom = high - float(octaves) * LOG10_2
        if zoom > approach_floor:
            stations.append(zoom)
    if high > low:
        stations.append(high)
    return stations


def survey_cap(plan: ZoomPlan) -> int:
    """The default probe cap: min(64 * auto_max_iter(deepest zoom), 2^31 - 1)."""
    return min(SURVEY_CAP_FACTOR * auto_max_iter(plan.deepest_zoom), MAX_SUGGESTION)


@dataclasses.dataclass(frozen=True)
class Station:
    """One probed depth: the budget the probe stopped at, its knot (the p99.9 escape,
    None when nothing escaped), what it saw, and the color fit of its fields."""

    zoom_log10: float
    budget: int
    need: int | None
    escaped: int
    unresolved: int
    samples: int
    frequency: Frequency | None = None


# A probe: the fields of the station's frame at a budget -- counts and status at least.
ProbeFn = Callable[[int], EscapeFields]


def probe_station(
    probe: ProbeFn, zoom_log10: float, *, cap: int, patient: bool = True, budget: int | None = None
) -> tuple[Station, EscapeFields]:
    """Probe one station (spec/zoom.md "Survey"). Starting from ``budget`` (default the
    depth ramp) and doubling up to ``cap``, until no point is left unresolved (status
    EXHAUSTED), or something escaped and the budget is at least twice the latest
    escape, or the cap is reached. ``patient=False`` probes once. Returns the station
    and the last probe's fields."""
    _check_int(cap, "cap", 1)
    if cap > MAX_SUGGESTION:
        raise ValueError("cap must be <= 2^31 - 1")
    current = min(auto_max_iter(zoom_log10) if budget is None else budget, cap)
    _check_int(current, "budget", 1)
    while True:
        fields = probe(current)
        if fields.status is None:
            raise ValueError("a probe must return status")
        counts = fields.counts
        escaped = int(np.count_nonzero(counts > 0))
        unresolved = int(np.count_nonzero(fields.status == EXHAUSTED))
        latest = int(counts.max(initial=0))
        done = unresolved == 0 or (escaped > 0 and current >= 2 * latest) or current >= cap
        if done or not patient:
            break
        current = min(2 * current, cap)
    station = Station(
        zoom_log10=zoom_log10,
        budget=current,
        need=need_from_counts(counts) if escaped > 0 else None,
        escaped=escaped,
        unresolved=unresolved,
        samples=int(counts.size),
    )
    return station, fields


class _Field(Protocol):
    max_zoom_log10: float
    supports_distance: bool

    def fields(
        self,
        size: tuple[int, int],
        viewport: Viewport,
        *,
        smooth: bool = ...,
        status: bool = ...,
        distance: bool = ...,
        bla_applications: bool = ...,
    ) -> EscapeFields: ...


FieldFactory = Callable[[int], _Field]


def _at(center: Viewport, zoom_log10: float) -> Viewport:
    return dataclasses.replace(center, zoom_log10=zoom_log10)


@dataclasses.dataclass(frozen=True)
class MovieSurvey:
    """What a movie measured before its frames: its stations, and with them each frame's
    budget and color. ``user_limit`` set: the budget is movie_max_iter's ramp to that
    limit (the stations then only fit color); None: measured_max_iter from the knots."""

    plan: ZoomPlan
    stations: tuple[Station, ...]
    user_limit: int | None = None

    @property
    def knots(self) -> list[tuple[float, int]]:
        return [(s.zoom_log10, s.need) for s in self.stations if s.need is not None]

    def max_iter(self, zoom_log10: float) -> int:
        if self.user_limit is not None:
            return movie_max_iter(zoom_log10, self.plan.deepest_zoom, self.user_limit)
        return measured_max_iter(zoom_log10, self.knots)

    def phase(self, zoom_log10: float, base: PhaseParams | None = None) -> PhaseParams:
        """base with its frequency and anchor taken from the stations' color fits,
        linear in depth between the two measured stations around the zoom and held past
        either end; base unchanged when no station fit."""
        base = base or PhaseParams()
        fits = [(s.zoom_log10, s.frequency) for s in self.stations if s.frequency is not None]
        if not fits:
            return base
        if not zoom_log10 > fits[0][0]:
            chosen = fits[0][1]
        elif not zoom_log10 < fits[-1][0]:
            chosen = fits[-1][1]
        else:
            deeper = next(i for i, (z, _) in enumerate(fits) if z > zoom_log10)
            (z0, f0), (z1, f1) = fits[deeper - 1], fits[deeper]
            w = (zoom_log10 - z0) / (z1 - z0)
            chosen = Frequency(
                f0.cycles_per_iteration + (f1.cycles_per_iteration - f0.cycles_per_iteration) * w,
                f0.anchor + (f1.anchor - f0.anchor) * w,
            )
        return dataclasses.replace(
            base, cycles_per_iteration=chosen.cycles_per_iteration, anchor=chosen.anchor
        )


def survey_movie(
    field_for: FieldFactory,
    center: Viewport,
    plan: ZoomPlan,
    *,
    user_limit: int | None = None,
    probe_size: tuple[int, int] = PROBE_SIZE,
    spacing_octaves: int = 64,
    cap: int | None = None,
    on_station: Callable[[int, int], None] | None = None,
) -> MovieSurvey:
    """Probe every station of the plan at ``center`` (its zoom is ignored) with the
    movie's own field, a ``probe_size`` frame (spec/zoom.md: 192 x 108) of counts,
    status and smooth values. With no user limit each station is patient
    (``probe_station``) up to ``cap`` (default ``survey_cap(plan)``); with one, each is
    probed once at movie_max_iter's budget, for color only."""
    if user_limit is not None:
        movie_max_iter(plan.deepest_zoom, plan.deepest_zoom, user_limit)  # validates
    if cap is None:
        cap = survey_cap(plan)
    stations = survey_stations(plan, spacing_octaves)
    measured = []
    for index, zoom in enumerate(stations):
        if on_station is not None:
            on_station(index, len(stations))
        viewport = _at(center, zoom)

        def probe(budget: int, viewport: Viewport = viewport) -> EscapeFields:
            return field_for(budget).fields(probe_size, viewport, smooth=True, status=True)

        if user_limit is None:
            station, fields = probe_station(probe, zoom, cap=cap)
        else:
            budget = movie_max_iter(zoom, plan.deepest_zoom, user_limit)
            station, fields = probe_station(
                probe, zoom, cap=MAX_SUGGESTION, patient=False, budget=budget
            )
        assert fields.smooth is not None
        frequency = measure_frequency(fields.counts, fields.smooth)
        measured.append(dataclasses.replace(station, frequency=frequency))
    return MovieSurvey(plan, tuple(measured), user_limit)


# --- writing ---------------------------------------------------------------------------


class MovieWriter:
    """Streams frames to ``path``: an .mp4 (the video extra), consecutive frames in
    order, or a directory of frame_00000.png files, any order, whose existing frames a
    render skips (resume, and several processes over disjoint frame ranges). The path is
    resolved once (``~`` expanded, made absolute). An .mp4's writer is created and its target checked here (a missing extra,
    directory or write permission fails before any rendering); the target is emptied and
    ffmpeg started at the first frame, and close() raises unless ffmpeg wrote a whole
    movie."""

    def __init__(self, path: str | Path, fps: int) -> None:
        _check_int(fps, "fps", 1)
        self.path = mp4_target(path)  # ~ expanded and absolute, as imageio resolves it
        self.fps = fps
        self.mp4 = self.path.suffix.lower() == ".mp4"
        self._writer: Any = None
        self._next: int | None = None
        self._written = 0
        if self.mp4:
            self._writer = open_mp4(self.path, self.fps)  # writes nothing until a frame
        else:
            self.path.mkdir(parents=True, exist_ok=True)

    def frame_path(self, index: int) -> Path:
        return self.path / f"frame_{index:05d}.png"

    def has(self, index: int) -> bool:
        return not self.mp4 and self.frame_path(index).exists()

    def write(self, index: int, rgb: ByteArray) -> None:
        _check_int(index, "index", 0)
        if not self.mp4:
            from PIL import Image

            partial = self.path / f".frame_{index:05d}.png.part"
            Image.fromarray(rgb).save(partial, format="PNG")
            partial.replace(self.frame_path(index))  # a frame on disk is always whole
            return
        self.check_next(index)
        cropped = even_crop(rgb)
        if self._written == 0:
            start_mp4(self.path)
        self._writer.append_data(cropped)
        self._next = index + 1
        self._written += 1

    def check_next(self, index: int) -> None:
        """Raise unless ``index`` can be written next: an .mp4 that is open and at that
        frame (any frame when nothing has been written yet)."""
        if not self.mp4:
            return
        if self._writer is None:
            raise ValueError("the .mp4 writer is closed")
        if self._next is not None and index != self._next:
            raise ValueError(f"an .mp4 is written in order: expected frame {self._next}")

    def close(self, *, check: bool = True) -> None:
        """Close; for an .mp4 that took frames, raise if ffmpeg wrote no movie (unless
        ``check`` is False, as when another error is already on its way)."""
        if self._writer is None:
            return
        writer, self._writer = self._writer, None
        if check:
            close_mp4(writer, self.path, self._written)
        else:
            writer.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close(check=exc_type is None)


def _frame_order(files: Iterable[Path]) -> list[Path]:
    """frame_N.png files in numeric order (the names grow a digit past 99,999), which
    must be exactly 0..N-1: a gap is an error, not a jump in the movie."""
    numbered = {}
    for file in files:
        digits = file.stem[len("frame_") :]
        if file.name.startswith("frame_") and file.suffix == ".png" and digits.isdigit():
            numbered[int(digits)] = file
    if not numbered:
        raise ValueError("no frame_*.png files")
    missing = [i for i in range(max(numbered) + 1) if i not in numbered]
    if missing:
        shown = ", ".join(str(i) for i in missing[:10]) + (", ..." if len(missing) > 10 else "")
        raise ValueError(f"missing {len(missing)} frame(s): {shown}")
    return [numbered[i] for i in range(len(numbered))]


def encode_frames(directory: str | Path, path: str | Path, fps: int) -> Path:
    """Encode a directory of frame_N.png files into an .mp4, in numeric frame order;
    the frames must be exactly 0..N-1."""
    from PIL import Image

    directory, path = mp4_target(directory), mp4_target(path)
    try:
        frames = _frame_order(directory.glob("frame_*.png"))
    except ValueError as exc:
        raise ValueError(f"{directory}: {exc}") from None
    writer = open_mp4(path, fps)
    try:
        for index, frame in enumerate(frames):
            with Image.open(frame) as image:
                rgb = even_crop(np.asarray(image.convert("RGB")))
            if index == 0:
                start_mp4(path)  # only once the first frame is ready
            writer.append_data(rgb)
    except BaseException:
        writer.close()
        raise
    close_mp4(writer, path, len(frames))
    return path


# --- rendering -------------------------------------------------------------------------


def _log2_radius(width: int, height: int) -> FloatArray:
    """log2 of each sample's distance from the frame center, in pixels of a 1920-wide
    frame of the same view (at least 0.5): the plane radius over the frame's width, so a
    plane point's octave term is the same at any size, aspect or supersample."""
    xs = np.arange(width, dtype=np.float64) + 0.5 - width / 2.0
    ys = np.arange(height, dtype=np.float64) + 0.5 - height / 2.0
    rho = np.hypot(xs[None, :], ys[:, None]) * (REFERENCE_WIDTH / width)
    result: FloatArray = np.log2(np.maximum(rho, 0.5))
    return result


def _resolve(rgb: ByteArray, ss: int, frame_index: int, dither: float) -> ByteArray:
    """The ss x ss box mean of an encoded frame, in light (encoded values squared, the
    gamma-2 model shade_distance uses), re-encoded and dithered at the output size."""
    height, width = rgb.shape[0] // ss, rgb.shape[1] // ss
    light = rgb.astype(np.float64) ** 2
    mean = light.reshape(height, ss, width, ss, 3).mean(axis=(1, 3))
    v = np.sqrt(mean)
    if dither != 0.0:
        v = v + dither * (tpdf_frame(width, height, frame_index).astype(np.float64) * 2.0**-32)
    out: ByteArray = np.clip(np.round(v), 0.0, 255.0).astype(np.uint8)
    return out


def render_zoom_movie(
    field_for: FieldFactory,
    size: tuple[int, int],
    center: Viewport,
    plan: ZoomPlan,
    output: str | Path | MovieWriter,
    *,
    user_limit: int | None = None,
    survey: MovieSurvey | None = None,
    phase: PhaseParams | None = None,
    track_color: bool = True,
    cmap: str = "deep",
    shade: ShadeParams | None = None,
    supersample: int = 1,
    frames: range | None = None,
    on_frame: Callable[[int, int], None] | None = None,
) -> MovieSurvey:
    """Render a zoom movie frame by frame at ``center`` (its zoom is ignored; an
    off-center reference is kept). ``field_for(max_iter)`` makes the frame's field,
    e.g. ``lambda n: Mandelbrot(max_iter=n, bla=True)``.

    Budgets come from the survey (run first unless one is passed): measured with no
    ``user_limit``, the limit's ramp with one. Color: ``phase`` gives the offset and
    cycles_per_octave, whose octave term is per pixel -- a point keeps its color as it
    flies outward, as in Heaton Fractal's movies -- and, with ``track_color``, the
    frequency and anchor follow the stations' fits so deep frames do not strobe.
    ``supersample`` renders ss x ss samples per pixel and averages them in light.
    ``frames`` renders a subset (a PNG directory skips frames it already holds; an .mp4
    takes consecutive frames, at least 2 x 2). A passed survey decides the budgets (a
    ``user_limit`` that disagrees with it is an error). The checks that need no frame
    run before the survey: the arguments, the plan's depth, and the output (the video
    extra, the directory, write permission, a passed writer's state). ffmpeg's own
    failures surface as it writes, and at the latest when the movie closes.
    Returns the survey, to reuse across processes or reruns."""
    width, height = size
    _check_int(width, "width", 1)
    _check_int(height, "height", 1)
    _check_int(supersample, "supersample", 1)
    indices = range(plan.frames) if frames is None else frames
    if not isinstance(indices, range):
        raise TypeError("frames must be a range")
    if len(indices) and not (
        0 <= min(indices[0], indices[-1]) and max(indices[0], indices[-1]) < plan.frames
    ):
        raise ValueError(f"frames must lie in [0, {plan.frames}), got {indices}")
    if user_limit is not None:
        movie_max_iter(plan.deepest_zoom, plan.deepest_zoom, user_limit)  # validates
    if survey is not None:
        if survey.plan != plan:
            raise ValueError("the survey was made for another plan")
        if user_limit is not None and user_limit != survey.user_limit:
            raise ValueError("user_limit disagrees with the survey's")
    probe_field = field_for(1)
    if plan.deepest_zoom > probe_field.max_zoom_log10:
        raise ValueError(
            f"the plan reaches zoom {plan.deepest_zoom}, past this family's "
            f"{probe_field.max_zoom_log10}"
        )
    if shade is not None and not probe_field.supports_distance:
        raise ValueError(f"{type(probe_field).__name__} has no distance estimate to shade by")
    phase = phase or PhaseParams()
    wrap = "cyclic" if is_cyclic(cmap) else "mirror"
    writer = output if isinstance(output, MovieWriter) else MovieWriter(output, plan.fps)
    try:
        if writer.mp4 and writer.fps != plan.fps:
            raise ValueError(f"the writer's fps {writer.fps} is not the plan's {plan.fps}")
        if writer.mp4 and indices.step != 1 and len(indices) > 1:
            raise ValueError("an .mp4 takes consecutive frames: use a range with step 1")
        if writer.mp4 and (width < 2 or height < 2):
            raise ValueError(f"an .mp4 frame must be at least 2 x 2 pixels, got {width} x {height}")
        if len(indices):
            writer.check_next(indices[0])
        if survey is None:
            survey = survey_movie(field_for, center, plan, user_limit=user_limit)
        render_size = (width * supersample, height * supersample)
        radial = _log2_radius(*render_size) if phase.cycles_per_octave != 0.0 else None
        zooms = plan.zooms()
        for done, frame in enumerate(indices):
            if on_frame is not None:
                on_frame(done, len(indices))
            if writer.has(frame):
                continue
            zoom = zooms[frame]
            field = field_for(survey.max_iter(zoom))
            fields = field.fields(
                render_size, _at(center, zoom), smooth=True, distance=shade is not None
            )
            assert fields.smooth is not None
            params = survey.phase(zoom, phase) if track_color else phase
            t = depth_phase(fields.smooth, zoom, params)
            if radial is not None:
                t = t - params.cycles_per_octave * radial  # NaN (interior) stays NaN
            dither = 1.0 if supersample == 1 else 0.0
            rgb = apply_phase(t, cmap, wrap=wrap, dither=dither, frame_index=frame)
            if shade is not None:
                assert fields.distance is not None
                rgb = shade_distance(rgb, fields.distance, shade)
            if supersample > 1:
                rgb = _resolve(rgb, supersample, frame, 1.0)
            writer.write(frame, rgb)
    except BaseException:
        if writer is not output:
            writer.close(check=False)  # the error on its way says more than ffmpeg's
        raise
    if writer is not output:
        writer.close()
    return survey
