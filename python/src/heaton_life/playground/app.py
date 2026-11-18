"""Main window: taxonomy sidebar, canvas, transport, auto-generated params dock."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image
from PyQt6.QtCore import QObject, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heaton_life.ca.hashlife import LifeView
from heaton_life.core.params import Params
from heaton_life.playground.canvas import Canvas
from heaton_life.playground.engine import SimEngine
from heaton_life.playground.hashlife_sim import save_filter_for
from heaton_life.playground.model import field_specs
from heaton_life.playground.param_form import (
    LABEL_GAP,
    FormScrollArea,
    ParamForm,
    scroll_bar_width,
)
from heaton_life.playground.registry import FAMILIES, Family, Redirect
from heaton_life.playground.transport import Transport


class EngineBridge(QObject):
    """GUI-side signal bundle; queued connections carry these into the engine thread."""

    sig_load = pyqtSignal(str, object, str)  # family key, Params, cmap
    sig_params = pyqtSignal(object)  # Params (hot/cold logic applies)
    sig_params_reset = pyqtSignal(object)  # Params, always with a fresh grid (presets)
    sig_run = pyqtSignal(bool)
    sig_step = pyqtSignal()
    sig_reset = pyqtSignal()
    sig_speed = pyqtSignal(int)
    sig_cmap = pyqtSignal(str)
    sig_paint = pyqtSignal(int, int, int)
    sig_view = pyqtSignal(object)  # Params whose view fields a canvas gesture moved
    sig_offer_save = pyqtSignal()  # ask the engine to suggest a pattern file name
    sig_save_pattern = pyqtSignal(str)  # path
    sig_go_ahead = pyqtSignal(str)  # a Redirect's key: build it here anyway
    sig_shutdown = pyqtSignal()


PANEL_MARGINS = (12, 10, 12, 12)  # the Parameters panel's: left, top, right, bottom
SECTION_GAP = 10  # above and below the line between the preset picker and the form
TREE_PADDING = 12  # clear of the family tree's longest name


class FamilyTree(QTreeWidget):
    """The family tree, as wide as its names: a tree view's own hint is a fixed 256."""

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        names = self.sizeHintForColumn(0)
        if names <= 0:
            return hint
        width = names + scroll_bar_width(self) + 2 * self.frameWidth() + TREE_PADDING
        return QSize(width, hint.height())


def _widest_form() -> int:
    """The widest minimum any family's form has."""
    width = 0
    for family in FAMILIES.values():
        form = ParamForm(field_specs(family.params_cls), family.params_cls().to_dict())
        width = max(width, form.minimumSizeHint().width())
        form.deleteLater()
    return width


class MainWindow(QMainWindow):
    def __init__(self, *, threaded: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("heaton-life playground")
        self.resize(1180, 800)

        self._family: Family | None = None
        self._form: ParamForm | None = None

        # Engine + optional worker thread
        self._bridge = EngineBridge(self)
        self._engine = SimEngine()
        self._thread: QThread | None = None
        if threaded:
            self._thread = QThread(self)
            self._engine.moveToThread(self._thread)
            self._thread.started.connect(self._engine.start)
            self._thread.start()
        else:
            self._engine.start()
        self._bridge.sig_load.connect(self._engine.load)
        self._bridge.sig_params.connect(self._engine.set_params)
        self._bridge.sig_params_reset.connect(self._engine.set_params_reset)
        self._bridge.sig_run.connect(self._engine.set_running)
        self._bridge.sig_step.connect(self._engine.single_step)
        self._bridge.sig_reset.connect(self._engine.reset)
        self._bridge.sig_speed.connect(self._engine.set_speed)
        self._bridge.sig_cmap.connect(self._engine.set_cmap)
        self._bridge.sig_paint.connect(self._engine.paint)
        self._bridge.sig_view.connect(self._engine.set_view_params)
        self._bridge.sig_offer_save.connect(self._engine.offer_pattern_save)
        self._bridge.sig_save_pattern.connect(self._engine.save_pattern)
        self._bridge.sig_go_ahead.connect(self._engine.go_ahead)
        self._bridge.sig_shutdown.connect(self._engine.shutdown)

        # Canvas (center)
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)
        self._engine.frame_view_ready.connect(self.canvas.show_frame_view)
        self._engine.frame_ready.connect(self.canvas.show_frame)
        self._engine.overlay_ready.connect(self.canvas.show_overlay)
        self.canvas.frame_shown.connect(self._engine.frame_shown)
        self.canvas.cell_pressed.connect(self._on_cell_pressed)
        self.canvas.view_requested.connect(self._on_view_requested)
        self._engine.frame_ready.connect(self._on_frame)
        self._engine.stats.connect(self._on_stats)
        self._engine.error.connect(self._on_engine_message)
        self._engine.message.connect(self._on_engine_message)
        self._engine.params_updated.connect(self._on_engine_params)
        self._engine.pattern_save_offered.connect(self._save_pattern_dialog)
        self._engine.redirect_offered.connect(self._on_redirect_offered)

        # Transport (top)
        self.transport = Transport(self)
        self.addToolBar(self.transport)
        self.transport.play_toggled.connect(self._on_play)
        self.transport.step_clicked.connect(self._bridge.sig_step.emit)
        self.transport.reset_clicked.connect(self._on_reset)
        self.transport.speed_changed.connect(self._bridge.sig_speed.emit)
        self.transport.cmap_changed.connect(self._bridge.sig_cmap.emit)
        self.transport.cell_scale_changed.connect(self.canvas.set_display_scale)
        self.transport.snapshot_clicked.connect(self._snapshot_dialog)
        self.transport.pattern_save_clicked.connect(self._on_pattern_save)
        self._engine.halted.connect(lambda: self.transport.set_playing(False))

        # Family tree (left dock)
        self._tree = FamilyTree()
        self._tree.setHeaderHidden(True)
        self._populate_tree()
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        left = QDockWidget("Families", self)
        left.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        left.setWidget(self._tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)

        # Params dock (right): preset picker + auto form
        self._presets = QComboBox()
        # Its width is the panel's, not its longest name's (a MergeLife preset is a rule).
        self._presets.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._presets.setMinimumContentsLength(12)
        self._presets.activated.connect(self._on_preset)
        # The picker sits in the panel's own layout, not a container of its own: a
        # macOS combo box overhangs its cell, and a box with no margin to take the
        # overhang would move it and its label in, off the form's left edge.
        self._form_host = QWidget()
        self._form_layout = QVBoxLayout(self._form_host)
        self._form_layout.setContentsMargins(*PANEL_MARGINS)
        self._form_layout.setSpacing(0)
        self._form_layout.addWidget(QLabel("Preset"))
        self._form_layout.addSpacing(LABEL_GAP)
        self._form_layout.addWidget(self._presets)
        self._form_layout.addSpacing(SECTION_GAP)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFrameShadow(QFrame.Shadow.Sunken)
        self._form_layout.addWidget(rule)
        self._form_layout.addSpacing(SECTION_GAP)
        self._form_layout.addStretch(1)  # the form goes in above this
        scroll = self._form_scroll = FormScrollArea()
        scroll.setWidget(self._form_host)
        # One width for every family: the panel doesn't jump as the family changes.
        scroll.set_floor(_widest_form() + PANEL_MARGINS[0] + PANEL_MARGINS[2])
        right = QDockWidget("Parameters", self)
        right.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        right.setWidget(scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right)

        # Status bar
        self._status_gen = QLabel("gen 0")
        self._status_readout = QLabel("")  # the sim's own readout (HashLife: pop, memory)
        self._status_sps = QLabel("")
        bar = self.statusBar()
        assert bar is not None
        bar.addPermanentWidget(self._status_sps)
        bar.addWidget(self._status_gen)
        bar.addWidget(self._status_readout)
        self._engine.readout_ready.connect(self._status_readout.setText)

        # Start on the first registered family
        first = next(iter(FAMILIES))
        self.select_family(first)

    # -- family / params ---------------------------------------------------------------

    def select_family(self, key: str, changes: Mapping[str, object] | None = None) -> None:
        """Show a family and load it: at its defaults, or with some params changed (a
        pattern handed over from another family)."""
        family = FAMILIES[key]
        self._engine.interrupt()  # a long step of the old family shouldn't hold up the new
        self._family = family
        params = family.params_cls().replace(**(changes or {}))
        if family.view_of is not None and family.with_view is not None:
            # A live view's frames fill the canvas, so the first fit is to the canvas.
            params = family.with_view(params, family.view_of(params), self.canvas.fill_size())

        if self._form is not None:
            self._form_layout.removeWidget(self._form)
            self._form.setParent(None)  # immediate: deleteLater alone leaves it painted
            self._form.deleteLater()
        self._form = ParamForm(field_specs(family.params_cls), params.to_dict())
        self._form.edited.connect(self._on_params_edited)
        self._form_layout.insertWidget(self._form_layout.count() - 1, self._form)

        self._presets.blockSignals(True)
        self._presets.clear()
        self._presets.addItem("— preset —")
        self._presets.addItems(list(family.presets))
        self._presets.blockSignals(False)

        self._sync_live_view(params)
        self.transport.set_cmap(family.default_cmap)
        self.transport.set_pattern_files(family.pattern_files)
        self._bridge.sig_load.emit(key, params, family.default_cmap)
        self._bridge.sig_speed.emit(self.transport.speed)

    def _on_params_edited(self, values: dict[str, Any]) -> None:
        family, form = self._family, self._form
        if family is None or form is None:
            return
        bar = self.statusBar()
        try:
            params: Params = family.params_cls.from_dict(values)
        except (ValueError, TypeError) as exc:
            if bar is not None:
                bar.showMessage(str(exc), 4000)
            return
        problem = family.validate(params)
        if problem is not None:
            field, message = problem
            form.mark_error(field)
            if bar is not None:
                bar.showMessage(message, 4000)
            return
        form.clear_errors()
        self._sync_live_view(params)
        self._bridge.sig_params.emit(params)

    def _on_preset(self, index: int) -> None:
        family, form = self._family, self._form
        if family is None or form is None or index == 0:
            return
        name = self._presets.itemText(index)
        overrides = family.presets.get(name)
        if overrides is None:
            return
        form.set_values(dict(overrides))
        merged = family.params_cls().to_dict() | form.values()
        params = family.params_cls.from_dict(merged)
        self._bridge.sig_params_reset.emit(params)  # presets always start a fresh grid

    # -- transport -----------------------------------------------------------------------

    def _on_play(self, playing: bool) -> None:
        if not playing:
            self._engine.interrupt()  # pause now, not when a long step finishes
        self._bridge.sig_run.emit(playing)

    def _on_reset(self) -> None:
        self._engine.interrupt()
        self._bridge.sig_reset.emit()

    # -- engine feedback -----------------------------------------------------------------

    def _on_frame(self, _rgb: object, generation: int) -> None:
        self._status_gen.setText(f"gen {generation:,}")

    def _on_stats(self, generation: int, sps: float) -> None:
        self._status_gen.setText(f"gen {generation:,}")
        rate = f"{sps:,.0f}" if sps >= 10 else f"{sps:.2g}"  # HashLife's big steps run < 1/s
        self._status_sps.setText(f"{rate} steps/s")

    def _on_engine_message(self, message: str) -> None:
        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(message, 5000)

    def _on_engine_params(self, params: object) -> None:
        """Engine-side param change (a build's fitted view, click/wheel zoom): sync the
        form silently, and the canvas's live view. That view goes back to the engine, so
        a gesture made against the view it replaced (queued behind the build) can't
        leave the engine showing something else."""
        if self._form is not None and isinstance(params, Params):
            self._form.set_values(params.to_dict())
            self._sync_live_view(params)
            self.canvas.resend_view()

    # -- a pattern that belongs in another family -------------------------------------------

    def _on_redirect_offered(self, redirect: object, asked: object, showing: object) -> None:
        """The engine didn't build what was asked: the family advises another one for it
        (Life-like, for a pattern file too large for a grid, or better off in HashLife).
        Ask, then load it there, here after all, or not at all."""
        family, form = self._family, self._form
        if not isinstance(redirect, Redirect) or family is None or form is None:
            return
        choice = self._ask_redirect(redirect)
        if choice == "there":
            self.transport.set_playing(False)
            self._show_in_tree(redirect.family)
            self.select_family(redirect.family, redirect.changes)
        elif choice == "here" and isinstance(asked, Params):
            self._bridge.sig_go_ahead.emit(redirect.key)
            self._bridge.sig_params_reset.emit(asked)  # a pattern load: a fresh grid
        elif isinstance(showing, family.params_cls):
            form.set_values(showing.to_dict())  # not loaded: the form says what is

    def _ask_redirect(self, redirect: Redirect) -> str:
        """ "there" (the family it names), "here" (this one after all, where that can be),
        or "" (don't load)."""
        assert self._family is not None
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if redirect.required else QMessageBox.Icon.Question)
        box.setWindowTitle("Load pattern")
        box.setText(redirect.title)
        box.setInformativeText(f"{redirect.text}\n\n{redirect.detail}")
        there = box.addButton(
            f"Load in {FAMILIES[redirect.family].label}", QMessageBox.ButtonRole.AcceptRole
        )
        here = None
        if not redirect.required:
            here = box.addButton(f"Load in {self._family.label}", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Don't Load", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(there)
        box.exec()
        clicked = box.clickedButton()
        if clicked is there:
            return "there"
        return "here" if here is not None and clicked is here else ""

    def _show_in_tree(self, key: str) -> None:
        """Select a family's row without the selection loading it (the caller does)."""
        for item in self._tree.findItems(
            "*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive
        ):
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                self._tree.blockSignals(True)
                self._tree.setCurrentItem(item)
                self._tree.blockSignals(False)
                return

    # -- live view -------------------------------------------------------------------------

    def _sync_live_view(self, params: Params) -> None:
        """Give a live-view family's view to the canvas, or take navigation back."""
        family = self._family
        if family is None or family.view_of is None or family.frame_size is None:
            self.canvas.set_live_view(None)
            return
        try:
            view = family.view_of(params)
        except ValueError:
            return  # an unparsable view field: validation marks it in the form
        self.canvas.set_live_view(view, family.frame_size(params))

    def _on_cell_pressed(self, x: int, y: int, code: int) -> None:
        """A draw, erase, or click-zoom on the canvas: it cuts a running step short, so it
        shows now rather than after the step."""
        self._engine.gesture_sent()
        self._bridge.sig_paint.emit(x, y, code)

    def _on_view_requested(self, view: object, size: object) -> None:
        """A canvas gesture or resize moved the view: echo it to the form and send it to
        the engine, which cuts a running step short to render it (the canvas previews it
        meanwhile)."""
        family, form = self._family, self._form
        if family is None or form is None or family.with_view is None:
            return
        if not isinstance(view, LifeView) or not isinstance(size, tuple):
            return
        try:
            current = family.params_cls.from_dict(family.params_cls().to_dict() | form.values())
        except (ValueError, TypeError):
            return
        params = family.with_view(current, view, size)
        before = current.to_dict()
        # Only the fields the view moved: a drag sends many of these, and a field being
        # typed into keeps its text and cursor.
        form.set_values({k: v for k, v in params.to_dict().items() if before[k] != v})
        self._engine.gesture_sent()
        self._bridge.sig_view.emit(params)

    # -- snapshot ------------------------------------------------------------------------

    def save_png(self, path: str | Path) -> bool:
        rgb = self.canvas.last_rgb
        if rgb is None:
            return False
        Image.fromarray(rgb, mode="RGB").save(Path(path))
        return True

    def _snapshot_dialog(self) -> None:
        if self.canvas.last_rgb is None:
            return
        suggested = f"heaton-life-gen{self.canvas.generation}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save snapshot", suggested, "PNG (*.png)")
        if path and not self.save_png(path):
            QMessageBox.warning(self, "Snapshot", "No frame to save yet.")

    # -- pattern files -------------------------------------------------------------------

    def _on_pattern_save(self) -> None:
        self.transport.set_playing(False)  # save the generation the dialog names
        self._bridge.sig_offer_save.emit()

    def _save_pattern_dialog(self, name: str) -> None:
        filters = self._family.save_filter if self._family is not None else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save pattern", name, filters, save_filter_for(name)
        )
        if path:
            self._bridge.sig_save_pattern.emit(path)

    # -- plumbing --------------------------------------------------------------------------

    def _populate_tree(self) -> None:
        categories: dict[str, QTreeWidgetItem] = {}
        for family in FAMILIES.values():
            node = categories.get(family.category)
            if node is None:
                node = QTreeWidgetItem([family.category])
                node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                categories[family.category] = node
                self._tree.addTopLevelItem(node)
            leaf = QTreeWidgetItem([family.label])
            leaf.setData(0, Qt.ItemDataRole.UserRole, family.key)
            node.addChild(leaf)
        self._tree.expandAll()

    def _on_tree_selection(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        key = items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(key, str) and self._family is not None and key != self._family.key:
            self.transport.set_playing(False)
            self.select_family(key)

    def closeEvent(self, event: QCloseEvent | None) -> None:
        self._engine.interrupt()
        self._bridge.sig_run.emit(False)
        self._bridge.sig_shutdown.emit()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("heaton-life playground")
    window = MainWindow()
    window.show()
    return app.exec()
