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
    for key, frame_shape, steps in [
        ("elementary", (256, 256), True),
        ("cyclic", (256, 256), True),
        ("wireworld", (64, 64), True),
        ("mergelife", (128, 128, 3), True),
        ("grayscott", (256, 256), True),
        ("lenia-classic", (128, 128), True),
        ("lenia-asymptotic", (128, 128), True),
        ("lenia-flow", (128, 128), True),
        ("newton", (384, 384), False),  # fractals don't step
        ("boids", (256, 256), True),
        ("lifelike", (256, 256), True),
    ]:
        window.select_family(key)
        assert window._engine._sim is not None, key
        assert window.canvas.last_rgb is not None, key
        frame = window._engine._sim.frame()
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
        engine._params.zoom_log10, abs=2e-3  # type: ignore[attr-defined]
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
    assert engine._params.genome == "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"  # type: ignore[attr-defined]


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
