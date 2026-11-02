"""Simulation engine. Lives on a worker QThread; the GUI talks to it via queued signals.

Backpressure: at most two unacknowledged frames are in flight; if the GUI falls behind,
the engine keeps stepping but skips emitting until the canvas acks (`frame_shown`).

Generations travel as Python ints (``object`` signals): HashLife's pass 2^63, where an
``int`` signal would silently wrap.
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
    frame_ready = pyqtSignal(object, object)  # rgb HxWx3 uint8, generation (int)
    stats = pyqtSignal(object, float)  # generation (int), achieved steps/sec
    error = pyqtSignal(str)
    message = pyqtSignal(str)  # a status-bar notice that is not an error
    params_updated = pyqtSignal(object)  # engine-side param change (e.g. click-zoom)
    overlay_ready = pyqtSignal(object)  # point-cloud overlay payload, or None
    readout_ready = pyqtSignal(str)  # the sim's status readout, or "" when it has none
    halted = pyqtSignal()  # play stopped on the engine's side (a step failed)
    pattern_save_offered = pyqtSignal(str)  # suggested file name for Save pattern

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
        self._sync_params_from_sim()
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
        hot = changed <= family.hot_fields
        try:
            if hot:
                self._sim = family.hot_apply(self._sim, params)
            else:
                self._sim = family.build(params)
        except (ValueError, TypeError) as exc:
            self.error.emit(str(exc))
            return
        self._params = params
        if not hot:
            self._sync_params_from_sim()  # a build may settle fields (HashLife fits its view)
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
        self._sync_params_from_sim()
        self._reset_stats()
        self._publish(force=True)

    def reset(self) -> None:
        """Rebuild from current params — same seed, same run (determinism on display). A
        reset_in_place family's sim resets itself (HashLife: its starting snapshot)."""
        if self._family is None or self._params is None:
            return
        if self._family.reset_in_place and self._sim is not None:
            self._sim.reset()
        else:
            try:
                self._sim = self._family.build(self._params)
            except (ValueError, TypeError) as exc:
                self.error.emit(str(exc))
                return
            self._sync_params_from_sim()
        self._reset_stats()
        self._publish(force=True)

    def set_running(self, running: bool) -> None:
        self._running = running
        self._reset_stats()
        self._apply_speed()

    def single_step(self) -> None:
        if self._sim is not None and self._advance(1):
            self._sync_params_from_sim()
            self._publish(force=True)

    def interrupt(self) -> None:
        """Cut a running step short (a sim with ``cancel()``: HashLife). Called directly
        from the GUI thread — a queued call would wait for the very step it means to stop —
        so it only sets the sim's thread-safe cancel flag."""
        cancel = getattr(self._sim, "cancel", None)
        if callable(cancel):
            cancel()

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
        except IndexError:
            return
        except ValueError as exc:  # e.g. HashLife's editing box: say why nothing happened
            self.error.emit(str(exc))
            return
        if replacement is not None:
            self._sim = replacement
            self._params = replacement.params  # type: ignore[attr-defined]
            self.params_updated.emit(self._params)
        self._publish(force=True)

    def frame_shown(self) -> None:
        self._pending = max(0, self._pending - 1)

    def offer_pattern_save(self) -> None:
        """Answer Save pattern with a suggested file name (HashLife picks the format)."""
        name = getattr(self._sim, "pattern_file_name", None)
        if callable(name):
            self.pattern_save_offered.emit(name())

    def save_pattern(self, path: str) -> None:
        save = getattr(self._sim, "save_pattern", None)
        if not callable(save):
            return
        try:
            written = save(path)
        except (OSError, ValueError) as exc:
            self.error.emit(f"Save pattern failed: {exc}")
            return
        self.message.emit(f"Saved {written}")

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
        if not self._advance(steps):
            return
        self._sync_params_from_sim()
        self._stat_steps += steps
        self._publish()
        now = time.perf_counter()
        elapsed = now - self._stat_t0
        if elapsed >= 0.5:
            self.stats.emit(self.generation, self._stat_steps / elapsed)
            self._stat_steps = 0
            self._stat_t0 = now

    def _advance(self, steps: int) -> bool:
        """Step the sim. A step that fails (HashLife's memory budget) stops play and
        reports instead of escaping the slot, which would abort the app."""
        assert self._sim is not None
        try:
            self._sim.step(steps)
        except (ValueError, MemoryError) as exc:
            self._running = False
            self._apply_speed()
            self.halted.emit()
            self.error.emit(str(exc))
            self._publish(force=True)
            return False
        return True

    def _sync_params_from_sim(self) -> None:
        """Sims that advance their own params (fractal autozoom) get echoed to the form."""
        sim_params = getattr(self._sim, "params", None)
        if sim_params is not None and sim_params != self._params:
            self._params = sim_params
            self.params_updated.emit(sim_params)

    def _reset_stats(self) -> None:
        self._stat_steps = 0
        self._stat_t0 = time.perf_counter()

    def _publish(self, force: bool = False) -> None:
        if self._sim is None:
            return
        if not force and self._pending >= MAX_PENDING:
            return
        rgb = apply_colormap(self._sim.frame(), self._lut)
        overlay_fn = getattr(self._sim, "overlay", None)
        overlay = overlay_fn() if callable(overlay_fn) else None
        readout_fn = getattr(self._sim, "readout", None)
        readout = readout_fn() if callable(readout_fn) else ""
        # Emitted back to back, so the GUI never shows a frame beside another's readout.
        self._pending += 1
        self.frame_ready.emit(rgb, self.generation)
        self.overlay_ready.emit(overlay)
        self.readout_ready.emit(readout)
