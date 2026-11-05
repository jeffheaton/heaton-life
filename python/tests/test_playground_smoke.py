"""Offscreen smoke test: the full window with the engine in-thread (no QThread flakiness).

With threaded=False every bridge signal is a direct (synchronous) connection, so the
test can drive ticks deterministically.
"""

import os

import numpy as np
import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from heaton_life.playground.app import MainWindow
from heaton_life.playground.engine import SimEngine


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance()
    assert instance is None or isinstance(instance, QApplication)
    return instance or QApplication([])


@pytest.fixture()
def window(app: QApplication) -> MainWindow:
    win = MainWindow(threaded=False)
    yield win
    win.close()


def test_loads_first_family_and_publishes_frame(window: MainWindow) -> None:
    assert window.canvas.last_rgb is not None
    assert window.canvas.last_rgb.shape == (256, 256, 3)
    assert window._engine.generation == 0


def test_single_step_and_ticks(window: MainWindow) -> None:
    window._bridge.sig_step.emit()
    assert window._engine.generation == 1
    window._bridge.sig_run.emit(True)
    for _ in range(3):
        window._engine._tick()
    window._bridge.sig_run.emit(False)
    assert window._engine.generation >= 4


def test_hot_param_change_preserves_state(window: MainWindow) -> None:
    engine = window._engine
    assert engine._sim is not None
    before = np.asarray(engine._sim.state).copy()
    values = {**window._form.values(), "rule": "B36/S23"}  # type: ignore[union-attr]
    window._on_params_edited(values)
    assert engine._sim is not None
    assert engine._sim.params.rule == "B36/S23"  # type: ignore[attr-defined]
    assert np.array_equal(np.asarray(engine._sim.state), before), "hot apply must keep the grid"


def test_cold_param_change_rebuilds(window: MainWindow) -> None:
    engine = window._engine
    assert engine._sim is not None
    before = np.asarray(engine._sim.state).copy()
    values = {**window._form.values(), "density": 0.6}  # type: ignore[union-attr]
    window._on_params_edited(values)
    assert engine._sim is not None
    assert not np.array_equal(np.asarray(engine._sim.state), before), "cold change must reseed"


def test_invalid_rule_is_rejected_without_engine_change(window: MainWindow) -> None:
    engine = window._engine
    assert engine._params is not None
    rule_before = engine._params.rule  # type: ignore[attr-defined]
    values = {**window._form.values(), "rule": "garbage"}  # type: ignore[union-attr]
    window._on_params_edited(values)
    assert engine._params.rule == rule_before  # type: ignore[attr-defined]


def test_reset_replays_same_seed(window: MainWindow) -> None:
    engine = window._engine
    assert engine._sim is not None
    initial = np.asarray(engine._sim.state).copy()
    window._bridge.sig_step.emit()
    window._bridge.sig_step.emit()
    window._bridge.sig_reset.emit()
    assert engine.generation == 0
    assert np.array_equal(np.asarray(engine._sim.state), initial)


def test_snapshot_png(window: MainWindow, tmp_path) -> None:
    out = tmp_path / "snap.png"
    assert window.save_png(out)
    from PIL import Image

    with Image.open(out) as img:
        assert img.size == (256, 256)


def test_switch_family_loads_engine_and_form(window: MainWindow) -> None:
    for key, frame_shape, steps in [
        ("elementary", (256, 256), True),
        ("cyclic", (256, 256), True),
        ("wireworld", (64, 64), True),
        ("mergelife", (128, 128, 3), True),
        ("grayscott", (256, 256), True),
        ("lenia-classic", (128, 128), True),
        ("lenia-asymptotic", (128, 128), True),
        ("lenia-flow", (128, 128), True),
        ("newton", (384, 384), True),  # fractal step = autozoom
        ("boids", (256, 256), True),
        ("hashlife", None, True),  # its frame fills the canvas
        ("lifelike", (256, 256), True),
    ]:
        window.select_family(key)
        assert window._engine._sim is not None, key
        assert window.canvas.last_rgb is not None, key
        frame = window._engine._sim.frame()
        if frame_shape is None:
            width, height = window.canvas.fill_size()
            frame_shape = (height, width)
        assert frame.shape == frame_shape, key
        window._bridge.sig_step.emit()
        assert window._engine.generation == (1 if steps else 0), key


def test_fractal_click_recenters_without_zooming(window: MainWindow) -> None:
    window.select_family("mandelbrot")
    engine = window._engine
    assert engine._params is not None
    zoom_before = engine._params.zoom_log10  # type: ignore[attr-defined]
    window._bridge.sig_paint.emit(96, 96, 1)  # plain click: recenter only
    assert engine._params.zoom_log10 == zoom_before  # type: ignore[attr-defined]
    assert engine._params.center_re != "-0.5"  # type: ignore[attr-defined]

    window._bridge.sig_paint.emit(192, 192, 3)  # Ctrl+click: recenter + zoom in x4
    assert engine._params.zoom_log10 == pytest.approx(zoom_before + 0.602, abs=0.01)  # type: ignore[attr-defined]

    zoom_mid = engine._params.zoom_log10  # type: ignore[attr-defined]
    window._bridge.sig_paint.emit(100, 100, 4)  # wheel: anchored zoom in x2
    assert engine._params.zoom_log10 == pytest.approx(zoom_mid + 0.301, abs=0.01)  # type: ignore[attr-defined]

    assert window._form is not None
    # the spinbox displays 3 decimals, so the synced value is rounded
    assert window._form.values()["zoom_log10"] == pytest.approx(
        engine._params.zoom_log10,  # type: ignore[attr-defined]
        abs=2e-3,
    )


def test_boids_overlay_arrives_and_clears(window: MainWindow) -> None:
    window.select_family("boids")
    assert window.canvas._overlay is not None
    points = np.asarray(window.canvas._overlay["points"])
    assert points.shape[1] == 4
    window.select_family("lifelike")
    assert window.canvas._overlay is None, "grid families must clear the overlay"


def test_boids_scare_paint_changes_velocities(window: MainWindow) -> None:
    window.select_family("boids")
    engine = window._engine
    assert engine._sim is not None
    before = np.asarray(engine._sim.state)[:, 2:4].copy()
    window._bridge.sig_paint.emit(128, 128, 1)
    after = np.asarray(engine._sim.state)[:, 2:4]
    assert not np.array_equal(before, after), "scare click should shove nearby boids"


def test_preset_apply_resets_grid(window: MainWindow) -> None:
    window.select_family("mergelife")
    engine = window._engine
    assert engine._sim is not None
    window._bridge.sig_step.emit()
    assert engine.generation == 1
    index = 1  # first real preset ("Red World (paper)")
    window._presets.setCurrentIndex(index)
    window._on_preset(index)
    assert engine.generation == 0, "preset selection must start a fresh grid"
    assert engine._params is not None
    assert engine._params.rule == "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"  # type: ignore[attr-defined]


def test_mergelife_preset_labels_not_truncated(window: MainWindow) -> None:
    from heaton_life.playground.registry import FAMILIES

    for name in FAMILIES["mergelife"].presets:
        assert "…" not in name and "..." not in name


def test_cell_display_scale(window: MainWindow) -> None:
    window.select_family("wireworld")  # 64x64 grid
    canvas = window.canvas
    canvas.set_display_scale(2)
    canvas.grab()  # force a paint pass
    assert canvas._target is not None
    assert canvas._target.width() == 128 and canvas._target.height() == 128
    canvas.set_display_scale(1)
    canvas.grab()
    assert canvas._target.width() == 64, "1 px per cell = native resolution"
    canvas.set_display_scale(0)  # back to fit
    canvas.grab()
    assert canvas._target.width() > 64, "fit mode should upscale a small grid"


def test_autozoom_play_advances_viewport_and_syncs_form(window: MainWindow) -> None:
    window.select_family("mandelbrot")
    engine = window._engine
    window._bridge.sig_run.emit(True)
    for _ in range(3):
        engine._tick()
    window._bridge.sig_run.emit(False)
    assert engine._params is not None
    assert engine._params.zoom_log10 > 0.0  # type: ignore[attr-defined]
    assert window._form is not None
    assert window._form.values()["zoom_log10"] > 0.0


def test_wheel_zoom_ignored_by_grid_families(window: MainWindow) -> None:
    window.select_family("lifelike")
    engine = window._engine
    assert engine._sim is not None
    before = engine._sim.state.copy()
    window._bridge.sig_paint.emit(3, 3, 4)  # wheel code must not paint cells
    assert np.array_equal(engine._sim.state, before)


def test_paint_sets_cells(window: MainWindow) -> None:
    window.select_family("lifelike")
    engine = window._engine
    assert engine._sim is not None
    window._bridge.sig_paint.emit(3, 4, 1)
    assert engine._sim.state[4, 3] == 1
    window._bridge.sig_paint.emit(3, 4, 2)
    assert engine._sim.state[4, 3] == 0
    window.select_family("wireworld")
    assert engine._sim is not None
    window._bridge.sig_paint.emit(1, 1, 1)
    assert engine._sim.state[1, 1] == 3  # conductor
    window._bridge.sig_paint.emit(1, 1, 3)
    assert engine._sim.state[1, 1] == 1  # electron head


def test_paint_ignored_where_unsupported(window: MainWindow) -> None:
    window.select_family("elementary")
    engine = window._engine
    assert engine._sim is not None
    before = engine._sim.state.copy()
    window._bridge.sig_paint.emit(2, 0, 1)
    assert np.array_equal(engine._sim.state, before)


def test_512_grid_tick_budget(window: MainWindow) -> None:
    """Phase 2 'done when': 512x512 stepping + colormap fits a 60 fps frame budget."""
    import time

    values = {**window._form.values(), "width": 512, "height": 512}  # type: ignore[union-attr]
    window._on_params_edited(values)
    window._bridge.sig_run.emit(True)
    window._engine._tick()  # warm-up
    t0 = time.perf_counter()
    for _ in range(30):
        window._engine._tick()
    per_tick = (time.perf_counter() - t0) / 30
    window._bridge.sig_run.emit(False)
    assert per_tick < 1 / 60, f"tick took {per_tick * 1000:.2f} ms; budget is 16.7 ms"


# -- HashLife ---------------------------------------------------------------------------


def _hashlife(window: MainWindow) -> SimEngine:
    window.select_family("hashlife")
    assert window._engine._sim is not None
    return window._engine


def test_hashlife_load_fits_the_view_and_echoes_it_to_the_form(window: MainWindow) -> None:
    from heaton_life.ca.hashlife import fit

    engine = _hashlife(window)
    assert engine._params is not None and window._form is not None
    p = engine._params
    size = window.canvas.fill_size()  # the frame fills the canvas from the first fit
    assert (p.width, p.height) == size  # type: ignore[attr-defined]
    view = fit(engine._sim.universe.bounding_box(), size)  # type: ignore[union-attr]
    assert (int(p.x), int(p.y), p.mag) == (view.x, view.y, view.mag)  # type: ignore[attr-defined]
    assert {k: window._form.values()[k] for k in ("x", "y", "mag")} == {
        "x": p.x,  # type: ignore[attr-defined]
        "y": p.y,  # type: ignore[attr-defined]
        "mag": p.mag,  # type: ignore[attr-defined]
    }
    assert window._status_readout.text().startswith("pop 36 · step 2^0 · center (")
    assert window.transport._pattern.isEnabled()
    window.select_family("lifelike")
    assert not window.transport._pattern.isEnabled()


def test_hashlife_hot_edits_then_reset_restore_generation_zero(window: MainWindow) -> None:
    """Audit finding 10-01: step, hot-edit, step, Reset — Reset must restore the start,
    keep the edited params, and not rebuild from params a hot edit replaced."""
    engine = _hashlife(window)
    sim = engine._sim
    start = sim.universe.to_macrocell()  # type: ignore[union-attr]
    window._bridge.sig_step.emit()
    window._bridge.sig_step.emit()
    values = {**window._form.values(), "rule": "B36/S23", "step_exponent": 3}  # type: ignore[union-attr]
    window._on_params_edited(values)
    assert engine._sim is sim, "hot fields must change the sim in place"
    assert engine.generation == 2
    window._bridge.sig_step.emit()
    assert engine.generation == 10
    edited = engine._params
    window._bridge.sig_reset.emit()
    assert engine._sim is sim and engine.generation == 0
    assert engine._params == edited == sim.params  # type: ignore[union-attr]
    assert sim.universe.to_macrocell().replace("B36/S23", "B3/S23") == start  # type: ignore[union-attr]
    window._bridge.sig_step.emit()
    assert engine.generation == 8


def test_hashlife_generations_past_int64_reach_the_status_bar(window: MainWindow) -> None:
    engine = _hashlife(window)
    window._on_params_edited({**window._form.values(), "step_exponent": 70})  # type: ignore[union-attr]
    window._bridge.sig_step.emit()
    assert engine.generation == 1 << 70
    assert window._status_gen.text() == f"gen {1 << 70:,}"
    assert window.canvas.generation == 1 << 70


def test_hashlife_wheel_zoom_and_recenter_sync_the_form(window: MainWindow) -> None:
    engine = _hashlife(window)
    assert engine._params is not None
    mag = engine._params.mag  # type: ignore[attr-defined]
    window._bridge.sig_paint.emit(100, 100, 5)
    assert engine._params.mag == mag - 1  # type: ignore[attr-defined]
    window._bridge.sig_paint.emit(10, 10, 3)
    assert window._form is not None
    assert window._form.values()["x"] == engine._params.x  # type: ignore[attr-defined]
    assert window._form.values()["mag"] == mag - 1


def test_hashlife_edit_outside_the_box_shows_the_engines_message(window: MainWindow) -> None:
    engine = _hashlife(window)
    window._on_params_edited(
        {**window._form.values(), "x": "1000000001", "y": "0", "mag": 0}  # type: ignore[union-attr]
    )
    before = engine._sim.universe.to_macrocell()  # type: ignore[union-attr]
    window._bridge.sig_paint.emit(0, 0, 1)
    bar = window.statusBar()
    assert bar is not None
    assert "editing box" in bar.currentMessage()
    assert engine._sim.universe.to_macrocell() == before  # type: ignore[union-attr]


def test_hashlife_failed_step_halts_play_with_its_message(window: MainWindow) -> None:
    from heaton_life.ca.hashlife import HashLifeMemoryError

    engine = _hashlife(window)

    def full(_n: int = 1) -> None:
        raise HashLifeMemoryError("one generation does not fit in max_memory_mb=10")

    engine._sim.step = full  # type: ignore[method-assign, union-attr]
    window.transport.set_playing(True)
    assert engine._running
    engine._tick()
    assert not engine._running
    assert not window.transport._play.isChecked(), "Play must pop back up"
    bar = window.statusBar()
    assert bar is not None and "does not fit" in bar.currentMessage()


def test_hashlife_save_pattern_offers_a_name_and_writes_the_file(
    window: MainWindow, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QFileDialog

    from heaton_life.ca.hashlife import HashLife

    engine = _hashlife(window)
    window._bridge.sig_step.emit()
    offered: list[tuple[str, str]] = []

    def save_dialog(*args: object) -> tuple[str, str]:
        offered.append((str(args[2]), str(args[4])))
        return str(tmp_path / "gun"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_dialog)
    window.transport._pattern.trigger()
    assert offered == [("Gosper-glider-gun-gen1.rle", "RLE (*.rle)")]
    saved = HashLife.from_file(tmp_path / "gun.rle")
    assert saved.to_macrocell() == engine._sim.universe.to_macrocell()  # type: ignore[union-attr]
    bar = window.statusBar()
    assert bar is not None and bar.currentMessage().startswith("Saved ")


def test_file_role_gets_a_browse_button(
    window: MainWindow, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QFileDialog, QToolButton

    engine = _hashlife(window)
    source = tmp_path / "glider.rle"
    source.write_text("#CXRLE Pos=5,7\nx = 3, y = 3, rule = B3/S23\nbo$2bo$3o!\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(source), ""))
    assert window._form is not None
    browse = [b for b in window._form.findChildren(QToolButton) if b.text() == "Browse…"]
    assert len(browse) == 1
    browse[0].click()
    assert window._form.values()["pattern"] == str(source)
    window._form._emit()  # the debounce timer's job
    assert engine._sim is not None
    assert engine._sim.universe.bounding_box() == (5, 7, 7, 9)  # type: ignore[attr-defined]


# -- HashLife live view: gestures move the view at once, the engine renders it after ---------


def _live(window: MainWindow) -> SimEngine:
    """HashLife in a shown window: the canvas laid out, the frame refitted to it, and
    the engine's render of that drawn (a paint computes where frames land)."""
    engine = _hashlife(window)
    window.show()
    QApplication.processEvents()
    window.canvas.grab()
    return engine


def _wheel(window: MainWindow, dy: int, phase: object) -> None:
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent

    target = window.canvas._target
    assert target is not None
    pos = QPointF(target.center())
    event = QWheelEvent(
        pos,
        pos,
        QPoint(0, 0),
        QPoint(0, dy),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        phase,  # type: ignore[arg-type]
        False,
    )
    QApplication.sendEvent(window.canvas, event)


def _pinch(window: MainWindow, kind: object, value: float = 0.0) -> None:
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QNativeGestureEvent, QPointingDevice

    target = window.canvas._target
    assert target is not None
    pos = QPointF(target.center())
    device = QPointingDevice.primaryPointingDevice()
    event = QNativeGestureEvent(kind, device, 2, pos, pos, pos, value, QPointF(0, 0))  # type: ignore[arg-type]
    QApplication.sendEvent(window.canvas, event)


def _view(engine: SimEngine) -> tuple[int, int, int]:
    p = engine._params
    return int(p.x), int(p.y), p.mag  # type: ignore[union-attr]


def _size(engine: SimEngine) -> tuple[int, int]:
    p = engine._params
    return p.width, p.height  # type: ignore[union-attr]


def test_hashlife_canvas_navigates_and_other_families_do_not(window: MainWindow) -> None:
    from heaton_life.ca.hashlife import LifeView

    engine = _live(window)
    nav = window.canvas._nav
    assert nav is not None and nav.view == LifeView(*_view(engine))
    assert window.canvas._frame_view == nav.view
    window.select_family("lifelike")
    assert window.canvas._nav is None


def test_hashlife_wheel_zooms_at_once_and_ignores_momentum(window: MainWindow) -> None:
    from PyQt6.QtCore import Qt

    engine = _live(window)
    x, y, mag = _view(engine)
    _wheel(window, -240, Qt.ScrollPhase.ScrollMomentum)  # a swipe's coasting
    assert _view(engine) == (x, y, mag)
    _wheel(window, -120, Qt.ScrollPhase.ScrollUpdate)
    assert window.canvas._nav is not None and window.canvas._nav.view.mag == mag - 1
    assert _view(engine)[2] == mag - 1, "the engine has the view before it renders it"
    assert window._form is not None and window._form.values()["mag"] == mag - 1
    assert window.canvas._frame_view != window.canvas._nav.view, "previewing the old frame"
    window.canvas.grab()  # the preview draws
    QApplication.processEvents()  # the engine's batched render
    assert window.canvas._frame_view == window.canvas._nav.view


def test_hashlife_drag_pans_when_zoomed_out(window: MainWindow) -> None:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from heaton_life.ca.hashlife import LifeView, pan

    engine = _live(window)
    for _ in range(8):
        _wheel(window, -120, Qt.ScrollPhase.NoScrollPhase)
    QApplication.processEvents()
    canvas = window.canvas
    assert canvas._nav is not None and canvas._nav.view.mag < 0
    assert canvas.cursor().shape() == Qt.CursorShape.OpenHandCursor
    before = LifeView(*_view(engine))
    target = canvas._target
    assert target is not None
    assert canvas._nav is not None
    k = target.width() / canvas._nav.size[0]  # widget pixels per frame pixel
    start = target.center()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(canvas, start + QPoint(80, -40))
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(80, -40)
    )
    assert LifeView(*_view(engine)) == pan(before, int(80 / k), int(-40 / k))
    assert canvas.cursor().shape() == Qt.CursorShape.OpenHandCursor
    bar = window.statusBar()
    assert bar is not None and "draw cells" not in bar.currentMessage()


def test_hashlife_pinch_zooms_by_whole_steps(window: MainWindow) -> None:
    from PyQt6.QtCore import Qt

    engine = _live(window)
    mag = _view(engine)[2]
    kinds = Qt.NativeGestureType
    _pinch(window, kinds.BeginNativeGesture)
    _pinch(window, kinds.ZoomNativeGesture, -0.5)  # half the size: one step out
    assert _view(engine)[2] == mag - 1
    _pinch(window, kinds.ZoomNativeGesture, -0.2)  # a third of a step: stretched, not taken
    assert _view(engine)[2] == mag - 1 and window.canvas._pinch < 0
    window.canvas.grab()
    _pinch(window, kinds.EndNativeGesture)
    assert _view(engine)[2] == mag - 1 and window.canvas._pinch == 0
    _pinch(window, kinds.BeginNativeGesture)
    _pinch(window, kinds.ZoomNativeGesture, -0.3)  # past half a step: taken at the end
    _pinch(window, kinds.EndNativeGesture)
    assert _view(engine)[2] == mag - 2


def test_hashlife_cmd_click_recenters_and_a_click_draws_when_zoomed_in(window: MainWindow) -> None:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from heaton_life.ca.hashlife import LifeView, cell_at, pan

    engine = _live(window)
    canvas = window.canvas
    before = LifeView(*_view(engine))
    assert before.mag >= 0
    target = canvas._target
    assert target is not None
    at = target.topLeft() + QPoint(30, 20)
    pixel = canvas._frame_pixel(at.toPointF())
    assert pixel is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, at)
    after = LifeView(*_view(engine))
    assert canvas._nav is not None
    width, height = canvas._nav.size
    assert after == pan(before, width // 2 - pixel[0], height // 2 - pixel[1])
    QApplication.processEvents()
    cell = cell_at(after, *pixel)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert engine._sim.universe.get_cell(*cell) == 1  # type: ignore[union-attr]


def test_hashlife_frame_fills_the_canvas_and_a_resize_keeps_the_center(window: MainWindow) -> None:
    from PyQt6.QtWidgets import QSpinBox

    from heaton_life.ca.hashlife import LifeView, center_cell

    engine = _live(window)
    canvas, form = window.canvas, window._form
    nav = canvas._nav
    assert nav is not None and form is not None
    size = (canvas.width(), canvas.height())
    assert nav.size == size == _size(engine)
    assert canvas.last_rgb is not None and canvas.last_rgb.shape[:2] == (size[1], size[0])
    assert canvas._target == canvas.rect(), "no bars: the frame is the canvas"
    for name in ("width", "height"):
        widget = form._widgets[name]
        assert isinstance(widget, QSpinBox) and widget.isReadOnly(), "the canvas sets it"
    center = center_cell(LifeView(*_view(engine)), size)

    window.resize(1400, 900)
    QApplication.processEvents()  # the resize, then the engine's render at the new size
    bigger = (canvas.width(), canvas.height())
    assert bigger != size and nav.size == bigger == _size(engine)
    assert center_cell(LifeView(*_view(engine)), bigger) == center
    assert (form.values()["width"], form.values()["height"]) == bigger
    assert canvas.last_rgb.shape[:2] == (bigger[1], bigger[0])

    canvas.set_display_scale(4)  # Cell 4 px: each frame pixel a 4 x 4 square
    QApplication.processEvents()
    quarter = (bigger[0] // 4, bigger[1] // 4)
    assert nav.size == quarter == _size(engine)
    assert center_cell(LifeView(*_view(engine)), quarter) == center
    canvas.grab()
    assert canvas._target is not None
    assert (canvas._target.width(), canvas._target.height()) == (quarter[0] * 4, quarter[1] * 4)

    stale = LifeView(*_view(engine))  # params from before a resize, for a 64 x 64 frame
    canvas.set_live_view(stale, (64, 64))
    assert nav.size == quarter == _size(engine)
    assert center_cell(LifeView(*_view(engine)), quarter) == center_cell(stale, (64, 64))


def test_a_view_meant_for_the_family_before_is_ignored(window: MainWindow) -> None:
    from heaton_life.playground.hashlife_sim import HashLifeSimParams

    engine = _hashlife(window)
    window.select_family("lifelike")
    before = engine._params
    engine.set_view_params(HashLifeSimParams())  # queued behind the switch
    assert engine._params is before
