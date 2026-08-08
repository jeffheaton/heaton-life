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
    for key, frame_shape in [
        ("elementary", (256, 256)),
        ("cyclic", (256, 256)),
        ("wireworld", (64, 64)),
        ("mergelife", (128, 128, 3)),
        ("lifelike", (256, 256)),
    ]:
        window.select_family(key)
        assert window._engine._sim is not None, key
        assert window.canvas.last_rgb is not None, key
        frame = window._engine._sim.frame()
        assert frame.shape == frame_shape, key
        window._bridge.sig_step.emit()
        assert window._engine.generation == 1, key


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
