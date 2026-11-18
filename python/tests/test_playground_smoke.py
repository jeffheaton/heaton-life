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
    assert window.transport._pattern.isEnabled()  # Life-like saves RLE
    window.select_family("elementary")
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
    from PyQt6.QtWidgets import QFileDialog, QPushButton

    engine = _hashlife(window)
    source = tmp_path / "glider.rle"
    source.write_text("#CXRLE Pos=5,7\nx = 3, y = 3, rule = B3/S23\nbo$2bo$3o!\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(source), ""))
    assert window._form is not None
    browse = [b for b in window._form.findChildren(QPushButton) if b.text() == "Browse…"]
    assert len(browse) == 1
    browse[0].click()
    assert window._form.values()["pattern"] == str(source)
    window._form._emit()  # the debounce timer's job
    assert engine._sim is not None
    assert engine._sim.universe.bounding_box() == (5, 7, 7, 9)  # type: ignore[attr-defined]


# -- Life-like: patterns, and the ones that belong in HashLife -------------------------------


def _browse_to(window: MainWindow, monkeypatch: pytest.MonkeyPatch, path: object) -> None:
    """Pick a file with the form's Browse… button, and let the edit through."""
    from PyQt6.QtWidgets import QFileDialog, QPushButton

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(path), ""))
    assert window._form is not None
    (browse,) = (b for b in window._form.findChildren(QPushButton) if b.text() == "Browse…")
    browse.click()
    window._form._emit()  # the debounce timer's job


def _answers(window: MainWindow, monkeypatch: pytest.MonkeyPatch, answer: str) -> list[object]:
    """Answer the redirect dialog without showing it; returns the Redirects it was asked."""
    asked: list[object] = []

    def ask(redirect: object) -> str:
        asked.append(redirect)
        return answer

    monkeypatch.setattr(window, "_ask_redirect", ask)
    return asked


def _pattern_file(tmp_path, name: str, text: str):  # type: ignore[no-untyped-def]
    path = tmp_path / name
    path.write_text(text, encoding="ascii", newline="\n")
    return path


def test_lifelike_browse_loads_a_pattern_and_starts_from_it(
    window: MainWindow, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.select_family("lifelike")
    engine = window._engine
    assert window._form is not None and window._form.values()["init"] == "soup"
    asked = _answers(window, monkeypatch, "")
    source = _pattern_file(tmp_path, "glider.rle", "x = 3, y = 3, rule = B36/S23\nbo$2bo$3o!\n")
    _browse_to(window, monkeypatch, source)
    values = window._form.values()
    assert (values["init"], values["pattern"]) == ("pattern", str(source))
    assert values["rule"] == "B36/S23"  # the file's rule, echoed to the form
    assert engine._sim is not None and int(np.asarray(engine._sim.state).sum()) == 5
    assert asked == []  # nothing to ask about a glider
    window._bridge.sig_step.emit()
    window._bridge.sig_reset.emit()  # Reset: back to the pattern, not a soup
    assert engine.generation == 0 and int(np.asarray(engine._sim.state).sum()) == 5


def test_lifelike_typing_a_pattern_selects_it_and_a_soup_is_still_a_choice(
    window: MainWindow,
) -> None:
    from PyQt6.QtWidgets import QLineEdit

    window.select_family("lifelike")
    engine = window._engine
    assert window._form is not None
    field = window._form._widgets["pattern"]
    assert isinstance(field, QLineEdit)
    field.setText("Glider")
    field.textEdited.emit("Glider")  # what typing does
    assert window._form.values()["init"] == "pattern"
    window._form._emit()
    assert engine._sim is not None and int(np.asarray(engine._sim.state).sum()) == 5
    window._on_params_edited(window._form.values() | {"init": "soup"})
    assert int(np.asarray(engine._sim.state).sum()) > 5


def test_lifelike_a_file_too_large_goes_to_hashlife_or_nowhere(
    window: MainWindow, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heaton_life.playground.hashlife_sim import HashLifeSim
    from heaton_life.playground.lifelike_sim import LifeLikeSim
    from heaton_life.playground.registry import Redirect

    window.select_family("lifelike")
    engine = window._engine
    assert window._form is not None
    soup = engine._sim
    giant = _pattern_file(tmp_path, "giant.rle", "x = 5000, y = 2, rule = B3/S23\n5000o$o!\n")

    asked = _answers(window, monkeypatch, "")  # Don't Load
    _browse_to(window, monkeypatch, giant)
    (redirect,) = asked
    assert isinstance(redirect, Redirect) and redirect.required
    assert "giant.rle is 5,000 × 2 cells" in redirect.text
    assert engine._sim is soup and isinstance(soup, LifeLikeSim)  # nothing was built
    values = window._form.values()  # and the form says what is still there
    assert (values["init"], values["pattern"]) == ("soup", "Gosper glider gun")

    asked = _answers(window, monkeypatch, "there")  # Load in HashLife
    _browse_to(window, monkeypatch, giant)
    assert len(asked) == 1
    assert window._family is not None and window._family.key == "hashlife"
    assert isinstance(engine._sim, HashLifeSim) and engine._sim.universe.population == 5001
    assert window._form.values()["pattern"] == str(giant)
    current = window._tree.currentItem()
    assert current is not None and current.text(0) == "HashLife"
    assert window.canvas.last_rgb is not None and window.transport._pattern.isEnabled()


def test_lifelike_a_borderline_file_is_the_users_choice(
    window: MainWindow, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heaton_life.playground.hashlife_sim import HashLifeSim
    from heaton_life.playground.lifelike_sim import LifeLikeSim
    from heaton_life.playground.registry import Redirect

    window.select_family("lifelike")
    engine = window._engine
    assert window._form is not None
    big = _pattern_file(tmp_path, "big.rle", "x = 1200, y = 1, rule = B3/S23\n1200o!\n")

    asked = _answers(window, monkeypatch, "here")  # Load in Life-like
    _browse_to(window, monkeypatch, big)
    (redirect,) = asked
    assert isinstance(redirect, Redirect) and not redirect.required
    assert isinstance(engine._sim, LifeLikeSim)
    assert int(np.asarray(engine._sim.state).sum()) == 1200
    assert window._form.values()["width"] == 2048  # grown, and echoed to the form
    window._bridge.sig_reset.emit()  # the same file again: the answer is remembered
    window._on_params_edited(window._form.values() | {"height": 512})
    assert len(asked) == 1 and np.asarray(engine._sim.state).shape == (512, 2048)

    window.select_family("lifelike")
    asked = _answers(window, monkeypatch, "there")  # another one, sent to HashLife
    bigger = _pattern_file(tmp_path, "bigger.rle", "x = 1300, y = 1, rule = B3/S23\n1300o!\n")
    _browse_to(window, monkeypatch, bigger)
    assert len(asked) == 1 and isinstance(engine._sim, HashLifeSim)
    assert engine._sim.universe.population == 1300


def test_lifelike_redirect_dialog_offers_this_family_only_when_it_can_hold_the_pattern(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QMessageBox

    from heaton_life.playground.registry import Redirect

    window.select_family("lifelike")
    shown: list[list[str]] = []
    click = {"text": ""}

    def exec_(box: QMessageBox) -> int:
        buttons = {b.text(): b for b in box.buttons()}
        shown.append(sorted(buttons))
        buttons[click["text"]].click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)

    def redirect(required: bool) -> Redirect:
        return Redirect("f", "hashlife", {"pattern": "f"}, required, "title", "text", "detail")

    click["text"] = "Load in HashLife"
    assert window._ask_redirect(redirect(True)) == "there"
    assert shown[-1] == ["Don't Load", "Load in HashLife"]
    click["text"] = "Load in Life-like"
    assert window._ask_redirect(redirect(False)) == "here"
    assert shown[-1] == ["Don't Load", "Load in HashLife", "Load in Life-like"]
    click["text"] = "Don't Load"
    assert window._ask_redirect(redirect(False)) == ""


def test_lifelike_save_pattern_writes_rle(
    window: MainWindow, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QFileDialog

    from heaton_life.playground.lifelike_sim import measure

    window.select_family("lifelike")
    engine = window._engine
    assert window._form is not None
    window._on_params_edited(window._form.values() | {"init": "pattern", "pattern": "Glider"})
    window._bridge.sig_step.emit()
    offered: list[tuple[str, str, str]] = []

    def save_dialog(*args: object) -> tuple[str, str]:
        offered.append((str(args[2]), str(args[3]), str(args[4])))
        return str(tmp_path / "glider"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_dialog)
    window.transport._pattern.trigger()
    assert offered == [("Glider-gen1.rle", "RLE (*.rle)", "RLE (*.rle)")]  # RLE, nothing else
    saved = measure(str(tmp_path / "glider.rle"))
    assert saved.cells is not None and int(saved.cells.sum()) == 5
    assert engine._sim is not None and int(np.asarray(engine._sim.state).sum()) == 5


def test_a_family_that_cant_load_what_it_was_handed_shows_its_defaults(
    window: MainWindow, tmp_path
) -> None:
    """A pattern handed to HashLife may not load there (a rule it can't run): the form
    and the engine must still be on the same family."""
    from heaton_life.playground.hashlife_sim import HashLifeSim

    errors: list[str] = []
    window._engine.error.connect(errors.append)
    window.select_family("hashlife", {"pattern": str(tmp_path / "missing.mc")})
    engine = window._engine
    assert isinstance(engine._sim, HashLifeSim) and engine._sim.universe.population == 36
    assert errors and "missing.mc" in errors[0]
    assert window._form is not None and window._form.values()["pattern"] == "Gosper glider gun"


# -- The Parameters panel: nothing clipped, in any family ------------------------------------


def _shown(window: MainWindow, app: QApplication) -> None:
    window.show()
    for _ in range(5):
        app.processEvents()


def _select(window: MainWindow, app: QApplication, key: str) -> None:
    """Pick a family in a window that is already up, as a click in the tree does: its
    form is added to a visible panel, and isn't itself shown until the events run."""
    window.select_family(key)
    for _ in range(5):
        app.processEvents()


def test_the_panel_is_never_narrower_than_a_form_and_keeps_one_width(
    window: MainWindow, app: QApplication
) -> None:
    """The dock was 241 px whatever the form: HashLife, Boids, Elementary and Cyclic
    lost their right edge to it and scrolled sideways."""
    from PyQt6.QtCore import Qt

    from heaton_life.playground.registry import FAMILIES

    _shown(window, app)
    scroll = window._form_scroll
    viewport = scroll.viewport()
    assert viewport is not None
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    widths = set()
    for key in FAMILIES:
        _select(window, app, key)
        assert window._form is not None and window._form.isVisible()
        needed = window._form_host.minimumSizeHint().width()
        assert viewport.width() >= needed, key
        assert window._form_host.width() == viewport.width(), key  # laid out, not clipped
        widths.add(scroll.width())
    assert len(widths) == 1, "the panel changed width between families"


def test_a_file_field_shows_the_whole_pattern_name(window: MainWindow, app: QApplication) -> None:
    """It sat in the field column, where "Gosper glider gun" showed as "un"; then on a
    row of its own in a panel too narrow for it, where Browse… showed as "Br"."""
    from PyQt6.QtWidgets import QPushButton

    from heaton_life.playground.param_form import TextField

    _shown(window, app)
    _select(window, app, "hashlife")
    assert window._form is not None
    field = window._form._widgets["pattern"]
    assert isinstance(field, TextField) and field.text() == "Gosper glider gun"
    assert field.width() >= field.text_width(field.text())
    (browse,) = (b for b in window._form.findChildren(QPushButton) if b.text() == "Browse…")
    assert browse.width() >= browse.minimumSizeHint().width()
    panel_right = window._form.mapTo(window._form_host, window._form.rect().topRight()).x()
    assert browse.mapTo(window._form_host, browse.rect().topRight()).x() <= panel_right
    assert panel_right <= window._form_host.width()


def test_a_long_text_field_takes_the_forms_width(window: MainWindow, app: QApplication) -> None:
    """A MergeLife rule is 39 characters; beside its label it showed its last 21."""
    from heaton_life.playground.param_form import TextField

    _shown(window, app)
    _select(window, app, "mergelife")
    assert window._form is not None
    rule = window._form._widgets["rule"]
    width = window._form._widgets["width"]
    assert isinstance(rule, TextField) and len(rule.text()) == 39
    assert rule.width() >= rule.text_width(rule.text())
    assert rule.width() > width.width()  # the full row, not the field column
    assert rule.x() == 0


def test_a_value_too_long_for_its_field_shows_its_start_and_a_tooltip(
    window: MainWindow, app: QApplication
) -> None:
    """A file shows its end instead, the file's name."""
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QHelpEvent

    from heaton_life.playground.param_form import TextField

    def tooltip(field: TextField) -> str:
        at = QPoint(5, 5)
        QApplication.sendEvent(field, QHelpEvent(QEvent.Type.ToolTip, at, field.mapToGlobal(at)))
        return field.toolTip()

    _shown(window, app)
    _select(window, app, "hashlife")
    assert window._form is not None
    far, path = str(-(2**300)), "/somewhere/long/enough/to/overflow/the/field/caterpillar.mc"
    window._form.set_values({"x": far, "pattern": path})
    x, rule, pattern = (window._form._widgets[name] for name in ("x", "rule", "pattern"))
    assert isinstance(x, TextField) and isinstance(rule, TextField)
    assert isinstance(pattern, TextField)
    assert x.cursorPosition() == 0 and tooltip(x) == far
    assert pattern.cursorPosition() == len(path) and tooltip(pattern) == path
    assert tooltip(rule) == ""  # it fits: nothing more to show


def test_the_family_tree_is_as_wide_as_its_names(window: MainWindow, app: QApplication) -> None:
    _shown(window, app)
    tree = window._tree
    names = tree.sizeHintForColumn(0)
    assert 0 < names <= tree.viewport().width() < 256  # the tree view's stock hint


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
    assert _view(engine)[2] == mag - 1
    assert window._form is not None and window._form.values()["mag"] == mag - 1
    assert window.canvas._frame_view == window.canvas._nav.view, "its frame came with it"


def test_hashlife_a_frame_waits_for_the_last_gesture_on_its_way(window: MainWindow) -> None:
    """A burst of gestures (a drag queued behind a step) gets one frame, the last one's;
    until it lands, the canvas draws the old frame where it lands in the new view."""
    from PyQt6.QtCore import Qt

    engine = _live(window)
    canvas = window.canvas
    shown = canvas._frame_view
    assert shown is not None and canvas._nav is not None
    engine.gesture_sent()  # another gesture, still on its way (queued, in the app)
    _wheel(window, -120, Qt.ScrollPhase.NoScrollPhase)
    assert _view(engine)[2] == canvas._nav.view.mag == shown.mag - 1, "the engine has it"
    assert canvas._frame_view == shown, "previewing the old frame"
    canvas.grab()  # the preview draws
    assert engine._params is not None
    engine.set_view_params(engine._params)  # the last one lands
    assert canvas._frame_view == canvas._nav.view


def _zoomed_out(engine: SimEngine) -> object:
    from heaton_life.ca.hashlife import zoom_at
    from heaton_life.playground.hashlife_sim import view_of, with_view

    p = engine._params
    return with_view(p, zoom_at(view_of(p), 0, 0, -1), (p.width, p.height))  # type: ignore[arg-type, union-attr]


def test_hashlife_a_gesture_cuts_a_step_of_play_short_and_its_frame_comes_first(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a giant a generation takes seconds in Python: a zoom mustn't wait for it."""
    from heaton_life.ca.hashlife import StepCanceled
    from heaton_life.playground.hashlife_sim import view_of

    engine = _hashlife(window)
    sim = engine._sim
    universe = sim.universe  # type: ignore[union-attr]
    real_step = universe.step
    views: list[object] = []
    engine.frame_view_ready.connect(views.append)

    def zoom_mid_step(n: int) -> None:
        # The GUI thread sends a gesture while the step runs; the store notices the cancel
        # at its next check (every 4096 allocations) and gives up the sub-step.
        engine.gesture_sent()
        raise StepCanceled("canceled")

    monkeypatch.setattr(universe, "step", zoom_mid_step)
    window._bridge.sig_run.emit(True)
    generation = engine.generation
    engine._tick()
    assert sim.cut_short and engine.generation == generation  # type: ignore[union-attr]
    assert views == [], "a step cut short has nothing new to show"
    monkeypatch.setattr(universe, "step", real_step)
    engine._tick()
    assert engine.generation == generation and views == [], "no step while it's on its way"
    zoomed = _zoomed_out(engine)
    engine.set_view_params(zoomed)  # type: ignore[arg-type]
    assert views == [view_of(zoomed)], "it lands: its frame first"  # type: ignore[arg-type]
    engine._tick()
    assert engine.generation == generation + 1, "then the step, from where it stopped"
    window._bridge.sig_run.emit(False)


def test_hashlife_a_step_cut_short_by_a_gesture_runs_again_once_it_lands(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heaton_life.ca.hashlife import StepCanceled

    engine = _hashlife(window)
    universe = engine._sim.universe  # type: ignore[union-attr]
    real_step = universe.step
    tries: list[int] = []

    def zoom_during_the_first_try(n: int) -> None:
        tries.append(n)
        if len(tries) == 1:
            engine.gesture_sent()  # a zoom while Step runs
            raise StepCanceled("canceled")
        real_step(n)

    monkeypatch.setattr(universe, "step", zoom_during_the_first_try)
    window._bridge.sig_step.emit()
    assert engine.generation == 0 and engine._steps_owed == 1, "owed, not dropped"
    engine.set_view_params(_zoomed_out(engine))  # type: ignore[arg-type]
    QApplication.processEvents()  # the owed step, after anything queued behind the zoom
    assert engine.generation == 1 and engine._steps_owed == 0 and tries == [1, 1]

    tries.clear()
    window._bridge.sig_step.emit()  # cut short again, then Reset before the zoom lands
    window._bridge.sig_reset.emit()
    assert engine._params is not None
    engine.set_view_params(engine._params)
    QApplication.processEvents()
    assert engine.generation == 0 and engine._steps_owed == 0, "Reset drops what was owed"


def test_hashlife_canvas_gestures_cut_only_a_running_step_short(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _hashlife(window)
    sent = engine._gestures_sent  # the load's view, sent back once the build echoed it
    cancels: list[None] = []
    monkeypatch.setattr(engine._sim, "cancel", lambda: cancels.append(None))
    window._on_cell_pressed(0, 0, 1)
    window.canvas.resend_view()
    assert cancels == [], "paused: no step to cut short"
    window._bridge.sig_run.emit(True)
    window._on_cell_pressed(0, 0, 1)  # an edit
    window.canvas.resend_view()  # a view change
    window._bridge.sig_run.emit(False)
    assert len(cancels) == 2
    assert engine._gestures_taken == engine._gestures_sent == sent + 4, "each one landed"


def test_hashlife_a_view_change_takes_only_the_view_fields(window: MainWindow) -> None:
    engine = _hashlife(window)
    p = engine._params
    assert p is not None
    request = p.replace(x=str(int(p.x) + 5), rule="B36/S23", pattern="Acorn")  # type: ignore[attr-defined]
    engine.set_view_params(request)  # sent while those edits were still on their way
    assert engine._params == p.replace(x=request.x)  # type: ignore[attr-defined]


def test_hashlife_after_a_build_the_canvas_view_wins_over_gestures_queued_behind_it(
    window: MainWindow,
) -> None:
    from heaton_life.ca.hashlife import LifeView, zoom_at
    from heaton_life.playground.hashlife_sim import view_of, with_view

    engine = _live(window)
    canvas = window.canvas
    echoes: list[object] = []
    engine.params_updated.disconnect(window._on_engine_params)
    engine.params_updated.connect(echoes.append)  # held back, as if still queued to the GUI
    p = engine._params
    stale = with_view(p, zoom_at(view_of(p), 5, 5, -2), (p.width, p.height))  # type: ignore[arg-type, union-attr]
    window._on_preset(window._presets.findText("R-pentomino"))  # the build fits the view
    fitted = echoes[-1]
    engine.set_view_params(stale)  # a zoom made against the old view lands after the build
    assert LifeView(*_view(engine)) == view_of(stale)
    window._on_engine_params(fitted)  # the GUI takes the echo and sends its view back
    assert canvas._nav is not None
    assert LifeView(*_view(engine)) == view_of(fitted) == canvas._nav.view  # type: ignore[arg-type]


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
