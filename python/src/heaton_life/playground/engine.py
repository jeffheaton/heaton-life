"""Simulation engine. Lives on a worker QThread; the GUI talks to it via queued signals.

Backpressure: at most two unacknowledged frames are in flight; if the GUI falls behind,
the engine keeps stepping but skips emitting until the canvas acks (`frame_shown`).

Canvas gestures (a live view's moves, cell edits) come before steps. The GUI counts each
one as it sends it (`gesture_sent`, a direct call like `interrupt`), which also cuts a
running step short; no step starts while one is on its way, and the frame goes out when
the last has landed. A HashLife step keeps the work it had done in its caches (until
memory nears the budget), so the step that follows picks up where it stopped: on a giant
pattern a generation takes seconds in Python, and a zoom waiting behind it would show
only the stretched old frame.

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
    frame_view_ready = pyqtSignal(object)  # the LifeView of the next frame, or None
    readout_ready = pyqtSignal(str)  # the sim's status readout, or "" when it has none
    halted = pyqtSignal()  # play stopped on the engine's side (a step failed)
    pattern_save_offered = pyqtSignal(str)  # suggested file name for Save pattern
    # A family's advice that params belong in another family, in place of building them:
    # the Redirect, the Params asked for, and the Params still showing (None: another
    # family's).
    redirect_offered = pyqtSignal(object, object, object)

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
        self._gestures_sent = 0  # counted on the GUI thread (gesture_sent)
        self._gestures_taken = 0  # ...and landed here (set_view_params, paint)
        self._gesture_frame_due = False  # a landed gesture changed what the frame shows
        self._steps_owed = 0  # Step presses whose step hasn't completed yet
        self._go_aheads: set[str] = set()  # Redirect keys the user said to build here anyway

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
        sim = self._build(family, params)
        fell_back = sim is None
        if sim is None:
            # The GUI is showing this family whatever happens (a pattern handed over from
            # another family may not load): its defaults, so the form and the engine agree.
            params = family.params_cls()
            sim = self._build(family, params)
            if sim is None:
                return
        self._family, self._params, self._sim = family, params, sim
        self._lut = get_colormap(cmap)
        self._pending = 0
        self._steps_owed = 0  # they were the last family's
        self._sync_params_from_sim()
        if fell_back:
            self.params_updated.emit(self._params)
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
        if hot:
            try:
                self._sim = family.hot_apply(self._sim, params)
            except (ValueError, TypeError) as exc:
                self.error.emit(str(exc))
                return
        else:
            sim = self._build(family, params)
            if sim is None:
                return
            self._sim = sim
        self._params = params
        if not hot:
            self._steps_owed = 0  # they were the old state's
            self._sync_params_from_sim()  # a build may settle fields (HashLife fits its view)
        self._publish(force=True)

    def set_view_params(self, params: Params) -> None:
        """A live view's move from a canvas gesture. Only its view fields are taken; the
        rest stay the engine's own, so a form edit still on its way isn't overtaken. The
        frame goes out once the last gesture on its way has landed: a drag queued behind
        a step arrives as many of these, and only the last view needs one."""
        self._take_gesture()
        try:
            self._move_view(params)
        finally:
            self._gesture_landed()

    def _move_view(self, params: Params) -> None:
        family, current = self._family, self._params
        if (
            family is None
            or self._sim is None
            or current is None
            or family.view_of is None
            or family.frame_size is None
            or family.with_view is None
            or not isinstance(params, family.params_cls)
        ):
            return  # a view meant for the family loaded before this one
        try:
            moved = family.with_view(current, family.view_of(params), family.frame_size(params))
            if moved == current:
                return  # already showing (the GUI sends its view again after a build)
            self._sim = family.hot_apply(self._sim, moved)
        except (ValueError, TypeError) as exc:
            self.error.emit(str(exc))
            return
        self._params = moved
        self._gesture_frame_due = True

    def set_params_reset(self, params: Params) -> None:
        """Apply params with a fresh grid (preset selection): always a cold rebuild."""
        family = self._family
        if family is None:
            return
        sim = self._build(family, params)
        if sim is None:
            return
        self._sim = sim
        self._params = params
        self._steps_owed = 0  # they were the old grid's
        self._sync_params_from_sim()
        self._reset_stats()
        self._publish(force=True)

    def reset(self) -> None:
        """Rebuild from current params — same seed, same run (determinism on display). A
        reset_in_place family's sim resets itself (HashLife: its starting snapshot)."""
        if self._family is None or self._params is None:
            return
        self._steps_owed = 0  # a Step pressed before Reset doesn't outlive it
        if self._family.reset_in_place and self._sim is not None:
            self._sim.reset()
        else:
            sim = self._build(self._family, self._params)
            if sim is None:
                return
            self._sim = sim
            self._sync_params_from_sim()
        self._reset_stats()
        self._publish(force=True)

    def go_ahead(self, key: str) -> None:
        """The user's answer to a Redirect that wasn't required: build here anyway. Kept,
        so a rebuild of the same thing (Reset, a new width) doesn't ask again."""
        self._go_aheads.add(key)

    def set_running(self, running: bool) -> None:
        self._running = running
        self._reset_stats()
        self._apply_speed()

    def single_step(self) -> None:
        """One step, owed until it completes: a gesture may cut it short so the gesture's
        frame comes first, and it is taken up again once that has landed."""
        self._steps_owed += 1
        self._take_owed_steps()

    def interrupt(self) -> None:
        """Cut a running step short (a sim with ``cancel()``: HashLife). Called directly
        from the GUI thread — a queued call would wait for the very step it means to stop —
        so it only sets the sim's thread-safe cancel flag."""
        cancel = getattr(self._sim, "cancel", None)
        if callable(cancel):
            cancel()

    def gesture_sent(self) -> None:
        """The GUI is about to send a canvas gesture (``set_view_params`` or ``paint``).
        Called directly from the GUI thread, like ``interrupt``: it counts the gesture, so
        no step starts before it lands, and cuts a step of play or Step short, so its
        frame comes now instead of after that step (which then runs again, from where it
        stopped)."""
        self._gestures_sent += 1
        if self._running or self._steps_owed:
            self.interrupt()

    def set_speed(self, steps_per_sec: int) -> None:
        self._speed = max(1, steps_per_sec)
        self._apply_speed()

    def set_cmap(self, name: str) -> None:
        self._lut = get_colormap(name)
        if self._sim is not None:
            self._publish(force=True)

    def paint(self, x: int, y: int, button: int) -> None:
        """A canvas gesture: draw, erase, or (click-zoom families) move the view. The
        frame goes out once the last gesture on its way has landed."""
        self._take_gesture()
        try:
            self._paint(x, y, button)
        finally:
            self._gesture_landed()

    def _paint(self, x: int, y: int, button: int) -> None:
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
        self._gesture_frame_due = True

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

    def _build(self, family: Family, params: Params) -> Simulation | None:
        """The family's sim for the params, or None with the reason sent out: an error,
        or the family's advice that another family should build them. The caller leaves
        everything as it was; the GUI answers a Redirect by loading the other family, by
        ``go_ahead`` and the params again, or not at all."""
        try:
            redirect = family.advise(params) if family.advise is not None else None
            if redirect is None or (not redirect.required and redirect.key in self._go_aheads):
                return family.build(params)
        except (ValueError, TypeError, MemoryError) as exc:  # HashLife's budget is one
            self.error.emit(str(exc))
            return None
        showing = self._params if self._family is family else None
        self.redirect_offered.emit(redirect, params, showing)
        return None

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
        if self._gestures_waiting():
            return  # a gesture lands, and its frame goes out, before the next step
        steps = max(1, round(self._speed * self._timer.interval() / 1000))
        if not self._advance(steps):
            return
        if self._cut_short():
            return  # a gesture or Pause stopped it, with nothing new to show
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

    def _cut_short(self) -> bool:
        """Whether the last step stopped before it was done (HashLife's ``cut_short``)."""
        return bool(getattr(self._sim, "cut_short", False))

    def _take_owed_steps(self) -> None:
        """The steps Step asked for, one at a time. A gesture on its way holds them back,
        or cuts one short, so its frame comes first; they're taken up when it lands."""
        while self._steps_owed and self._sim is not None:
            if self._gestures_waiting():
                return  # _gesture_landed takes them up
            if not self._advance(1):
                self._steps_owed = 0
                return
            if self._cut_short():
                if not self._gestures_waiting():
                    # Stopped by Reset or a family switch (which drop what's owed when
                    # they land, before this timer fires) or by Pause: try again.
                    QTimer.singleShot(0, self._take_owed_steps)
                return
            self._steps_owed -= 1
            self._sync_params_from_sim()
            self._publish(force=True)

    def _take_gesture(self) -> None:
        # Clamped, so a gesture the GUI didn't count (a test calling the slot directly)
        # can't make one that is still on its way look landed later on.
        self._gestures_taken = min(self._gestures_taken + 1, self._gestures_sent)

    def _gestures_waiting(self) -> bool:
        return self._gestures_taken < self._gestures_sent

    def _gesture_landed(self) -> None:
        """Once the last gesture on its way has landed: send the frame they changed, then
        take up the steps Step asked for, after anything queued behind the gestures."""
        if self._gestures_waiting():
            return
        if self._gesture_frame_due:
            self._gesture_frame_due = False
            self._publish(force=True)
        if self._steps_owed:
            QTimer.singleShot(0, self._take_owed_steps)

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
        view_fn = getattr(self._sim, "frame_view", None)
        view = view_fn() if callable(view_fn) else None
        # Emitted back to back, so the GUI never shows a frame beside another's readout.
        self._pending += 1
        self.frame_view_ready.emit(view)
        self.frame_ready.emit(rgb, self.generation)
        self.overlay_ready.emit(overlay)
        self.readout_ready.emit(readout)
