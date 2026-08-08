"""Simulation engine. Lives on a worker QThread; the GUI talks to it via queued signals.

Backpressure: at most two unacknowledged frames are in flight; if the GUI falls behind,
the engine keeps stepping but skips emitting until the canvas acks (`frame_shown`).
"""

from __future__ import annotations

import dataclasses
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from heaton_life.core.params import Params
from heaton_life.core.protocols import Simulation
from heaton_life.playground.registry import FAMILIES, Family
from heaton_life.render import apply_colormap, get_colormap

MAX_PENDING = 2
GUI_FPS_CAP = 60


class SimEngine(QObject):
    frame_ready = pyqtSignal(object, int)  # rgb HxWx3 uint8, generation
    stats = pyqtSignal(int, float)  # generation, achieved steps/sec
    error = pyqtSignal(str)
    params_updated = pyqtSignal(object)  # engine-side param change (e.g. click-zoom)
    overlay_ready = pyqtSignal(object)  # point-cloud overlay payload, or None

    def __init__(self) -> None:
        super().__init__()
        self._timer: QTimer | None = None
        self._family: Family | None = None
        self._params: Params | None = None
        self._sim: Simulation | None = None
        self._lut = get_colormap("gray")
        self._running = False
        self._speed = 60  # target steps/second
        self._pending = 0
        self._stat_steps = 0
        self._stat_t0 = time.perf_counter()

    # -- lifecycle (must run in the engine's own thread) -------------------------------

    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._apply_speed()

    def shutdown(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    # -- slots driven by the GUI (queued when threaded) ---------------------------------

    def load(self, family_key: str, params: Params, cmap: str) -> None:
        family = FAMILIES[family_key]
        try:
            sim = family.build(params)
        except (ValueError, TypeError) as exc:
            self.error.emit(str(exc))
            return
        self._family, self._params, self._sim = family, params, sim
        self._lut = get_colormap(cmap)
        self._pending = 0
        self._reset_stats()
        self._publish(force=True)

    def set_params(self, params: Params) -> None:
        """Hot-apply if only hot fields changed (state survives); otherwise rebuild."""
        family, old = self._family, self._params
        if family is None or self._sim is None or old is None:
            return
        changed = {
            f.name
            for f in dataclasses.fields(params)
            if getattr(params, f.name) != getattr(old, f.name)
        }
        try:
            if changed <= family.hot_fields:
                self._sim = family.hot_apply(self._sim, params)
            else:
                self._sim = family.build(params)
        except (ValueError, TypeError) as exc:
            self.error.emit(str(exc))
            return
        self._params = params
        self._publish(force=True)

    def set_params_reset(self, params: Params) -> None:
        """Apply params with a fresh grid (preset selection): always a cold rebuild."""
        family = self._family
        if family is None:
            return
        try:
            self._sim = family.build(params)
        except (ValueError, TypeError) as exc:
            self.error.emit(str(exc))
            return
        self._params = params
        self._reset_stats()
        self._publish(force=True)

    def reset(self) -> None:
        """Rebuild from current params — same seed, same run (determinism on display)."""
        if self._family is None or self._params is None:
            return
        try:
            self._sim = self._family.build(self._params)
        except (ValueError, TypeError) as exc:
            self.error.emit(str(exc))
            return
        self._reset_stats()
        self._publish(force=True)

    def set_running(self, running: bool) -> None:
        self._running = running
        self._reset_stats()
        self._apply_speed()

    def single_step(self) -> None:
        if self._sim is not None:
            self._sim.step(1)
            self._publish(force=True)

    def set_speed(self, steps_per_sec: int) -> None:
        self._speed = max(1, steps_per_sec)
        self._apply_speed()

    def set_cmap(self, name: str) -> None:
        self._lut = get_colormap(name)
        if self._sim is not None:
            self._publish(force=True)

    def paint(self, x: int, y: int, button: int) -> None:
        family = self._family
        if family is None or self._sim is None or family.paint is None:
            return
        if button in (4, 5) and not family.wheel_zoom:
            return
        try:
            replacement = family.paint(self._sim, x, y, button)
        except (IndexError, ValueError):
            return
        if replacement is not None:
            self._sim = replacement
            self._params = replacement.params  # type: ignore[attr-defined]
            self.params_updated.emit(self._params)
        self._publish(force=True)

    def frame_shown(self) -> None:
        self._pending = max(0, self._pending - 1)

    # -- internals ----------------------------------------------------------------------

    @property
    def generation(self) -> int:
        return int(getattr(self._sim, "generation", 0)) if self._sim is not None else 0

    def _apply_speed(self) -> None:
        if self._timer is None:
            return
        fps = min(self._speed, GUI_FPS_CAP)
        self._timer.setInterval(max(1, round(1000 / fps)))
        if self._running:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if not self._running or self._sim is None or self._timer is None:
            return
        steps = max(1, round(self._speed * self._timer.interval() / 1000))
        self._sim.step(steps)
        self._stat_steps += steps
        self._publish()
        now = time.perf_counter()
        elapsed = now - self._stat_t0
        if elapsed >= 0.5:
            self.stats.emit(self.generation, self._stat_steps / elapsed)
            self._stat_steps = 0
            self._stat_t0 = now

    def _reset_stats(self) -> None:
        self._stat_steps = 0
        self._stat_t0 = time.perf_counter()

    def _publish(self, force: bool = False) -> None:
        if self._sim is None:
            return
        if not force and self._pending >= MAX_PENDING:
            return
        rgb = apply_colormap(self._sim.frame(), self._lut)
        self._pending += 1
        self.frame_ready.emit(rgb, self.generation)
        overlay_fn = getattr(self._sim, "overlay", None)
        self.overlay_ready.emit(overlay_fn() if callable(overlay_fn) else None)
