"""Zoom movie conformance (spec/zoom.md, 0.13.0): the schedule, the plan's frame progress,
zooms and speeds, the movie budgets, the survey's stations, its patience rule, and whole
surveys with real Mandelbrot probes, bit for bit. Strict: an unknown key fails the case."""

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from heaton_life.fractal.engine import CARDIOID_OR_BULB, ESCAPED, EXHAUSTED
from heaton_life.fractal.escape_fields import EscapeFields
from heaton_life.fractal.movie import ZoomPlan, ZoomSchedule, probe_station, survey_stations
from heaton_life.fractal.policy import measured_max_iter, movie_max_iter, need_at

ROOT = Path(__file__).resolve().parents[2] / "vectors" / "zoom"


def _bits(value: float) -> str:
    return f"0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016X}"


def _float(text: str) -> float:
    value: float = struct.unpack("<d", struct.pack("<Q", int(text, 16)))[0]
    return value


def _load(name: str, *keys: str) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads((ROOT / name / "params.json").read_text())
    assert set(meta) == {"spec_version", "family", "tier", *keys}
    assert (meta["spec_version"], meta["family"], meta["tier"]) == ("0.13.0", "zoom", "bit-exact")
    return meta


def test_schedules() -> None:
    for case in _load("schedules", "schedules")["schedules"]:
        assert set(case) == {"segments", "duration", "resolved", "samples"}
        resolved = ZoomSchedule(*(_float(v) for v in case["segments"])).resolved(
            _float(case["duration"])
        )
        got = [
            resolved.duration,
            resolved.hold_start,
            resolved.ease_in,
            resolved.ease_out,
            resolved.hold_end,
            resolved.cruise,
            resolved.effective_seconds,
            resolved.peak_over_average,
        ]
        assert [_bits(v) for v in got] == case["resolved"], case["segments"]
        for sample in case["samples"]:
            assert set(sample) == {"t", "progress", "speed_fraction"}
            t = _float(sample["t"])
            assert _bits(resolved.progress(t)) == sample["progress"], (case["segments"], t)
            assert _bits(resolved.speed_fraction(t)) == sample["speed_fraction"], t


def test_plans() -> None:
    for case in _load("plans", "plans")["plans"]:
        assert set(case) == {
            "start_zoom",
            "end_zoom",
            "frames",
            "fps",
            "schedule",
            "progress",
            "zooms",
            "speeds",
        }
        plan = ZoomPlan(
            _float(case["start_zoom"]),
            _float(case["end_zoom"]),
            case["frames"],
            case["fps"],
            ZoomSchedule(*(_float(v) for v in case["schedule"])),
        )
        assert [_bits(plan.progress(f)) for f in range(plan.frames)] == case["progress"]
        assert [_bits(z) for z in plan.zooms()] == case["zooms"]
        assert [_bits(plan.zoom(f)) for f in range(plan.frames)] == case["zooms"]
        assert [_bits(plan.speed(f)) for f in range(plan.frames)] == case["speeds"]


def test_budgets() -> None:
    meta = _load("budgets", "ramps", "measured")
    for row in meta["ramps"]:
        assert set(row) == {"zoom", "target", "user_limit", "max_iter"}
        got = movie_max_iter(_float(row["zoom"]), _float(row["target"]), row["user_limit"])
        assert got == row["max_iter"], row
    for case in meta["measured"]:
        assert set(case) == {"knots", "rows"}
        knots = [(_float(z), n) for z, n in case["knots"]]
        for row in case["rows"]:
            assert set(row) == {"zoom", "need", "max_iter"}
            zoom = _float(row["zoom"])
            assert need_at(zoom, knots) == row["need"], (knots, zoom)
            assert measured_max_iter(zoom, knots) == row["max_iter"], (knots, zoom)


def test_stations() -> None:
    for case in _load("stations", "stations")["stations"]:
        assert set(case) == {"start_zoom", "end_zoom", "spacing_octaves", "stations"}
        plan = ZoomPlan(_float(case["start_zoom"]), _float(case["end_zoom"]), 2, 1)
        got = survey_stations(plan, case["spacing_octaves"])
        assert [_bits(z) for z in got] == case["stations"], case["spacing_octaves"]


def test_probes() -> None:
    for case in _load("probes", "probes")["probes"]:
        assert set(case) == {"name", "points", "zoom", "cap", "patient", "budget", "expected"}
        values = np.array(case["points"], dtype=np.int64)
        asked: list[int] = []

        def probe(budget: int, values: Any = values, asked: list[int] = asked) -> EscapeFields:
            asked.append(budget)
            escaped = (values > 0) & (values <= budget)
            counts = np.where(escaped, values, -1).astype(np.int32)
            status = np.where(
                escaped, ESCAPED, np.where(values == -2, CARDIOID_OR_BULB, EXHAUSTED)
            ).astype(np.int8)
            return EscapeFields(counts=counts[None, :], status=status[None, :])

        station, _ = probe_station(
            probe,
            _float(case["zoom"]),
            cap=case["cap"],
            patient=case["patient"],
            budget=case["budget"],
        )
        got = {
            "budgets": asked,
            "budget": station.budget,
            "need": station.need,
            "escaped": station.escaped,
            "unresolved": station.unresolved,
            "samples": station.samples,
        }
        assert got == case["expected"], case["name"]


def test_surveys() -> None:
    """Real surveys: Mandelbrot probes at the pinned size, every budget each station asked
    for, and every frame's budget."""
    from heaton_life.core.viewport import Viewport
    from heaton_life.fractal import Mandelbrot
    from heaton_life.fractal.movie import PROBE_SIZE, survey_movie

    meta = _load("surveys", "probe_size", "surveys")
    assert tuple(meta["probe_size"]) == PROBE_SIZE
    for case in meta["surveys"]:
        assert set(case) == {
            "name",
            "family",
            "center_re",
            "center_im",
            "plan",
            "user_limit",
            "expected",
        }
        assert case["family"] == "mandelbrot"
        assert set(case["plan"]) == {"start_zoom", "end_zoom", "frames", "fps"}
        plan = ZoomPlan(
            _float(case["plan"]["start_zoom"]),
            _float(case["plan"]["end_zoom"]),
            case["plan"]["frames"],
            case["plan"]["fps"],
        )
        asked: list[tuple[float, int]] = []

        class Recording(Mandelbrot):
            log = asked

            def fields(self, size: tuple[int, int], viewport: Viewport, **options: Any) -> Any:
                self.log.append((viewport.zoom_log10, self.max_iter))
                return super().fields(size, viewport, **options)

        survey = survey_movie(
            lambda n, cls=Recording: cls(max_iter=n),
            Viewport(case["center_re"], case["center_im"]),
            plan,
            user_limit=case["user_limit"],
        )
        expected = case["expected"]
        assert set(expected) == {"stations", "max_iter"}
        got = [
            {
                "zoom": _bits(s.zoom_log10),
                "budgets": [b for z, b in asked if z == s.zoom_log10],
                "budget": s.budget,
                "need": s.need,
                "escaped": s.escaped,
                "unresolved": s.unresolved,
                "samples": s.samples,
            }
            for s in survey.stations
        ]
        assert got == expected["stations"], case["name"]
        assert [survey.max_iter(z) for z in plan.zooms()] == expected["max_iter"], case["name"]
