"""Main window: taxonomy sidebar, canvas, transport, auto-generated params dock."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PIL import Image
from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heaton_life.core.params import Params
from heaton_life.playground.canvas import Canvas
from heaton_life.playground.engine import SimEngine
from heaton_life.playground.model import field_specs
from heaton_life.playground.param_form import ParamForm
from heaton_life.playground.registry import FAMILIES, Family
from heaton_life.playground.transport import Transport


class EngineBridge(QObject):
    """GUI-side signal bundle; queued connections carry these into the engine thread."""

    sig_load = pyqtSignal(str, object, str)  # family key, Params, cmap
    sig_params = pyqtSignal(object)  # Params
    sig_run = pyqtSignal(bool)
    sig_step = pyqtSignal()
    sig_reset = pyqtSignal()
    sig_speed = pyqtSignal(int)
    sig_cmap = pyqtSignal(str)
    sig_paint = pyqtSignal(int, int, int)
    sig_shutdown = pyqtSignal()


class MainWindow(QMainWindow):
    def __init__(self, *, threaded: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("heaton-life playground")
        self.resize(1100, 780)

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
        self._bridge.sig_run.connect(self._engine.set_running)
        self._bridge.sig_step.connect(self._engine.single_step)
        self._bridge.sig_reset.connect(self._engine.reset)
        self._bridge.sig_speed.connect(self._engine.set_speed)
        self._bridge.sig_cmap.connect(self._engine.set_cmap)
        self._bridge.sig_paint.connect(self._engine.paint)
        self._bridge.sig_shutdown.connect(self._engine.shutdown)

        # Canvas (center)
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)
        self._engine.frame_ready.connect(self.canvas.show_frame)
        self.canvas.frame_shown.connect(self._engine.frame_shown)
        self.canvas.cell_pressed.connect(self._bridge.sig_paint.emit)
        self._engine.frame_ready.connect(self._on_frame)
        self._engine.stats.connect(self._on_stats)
        self._engine.error.connect(self._on_engine_error)
        self._engine.params_updated.connect(self._on_engine_params)

        # Transport (top)
        self.transport = Transport(self)
        self.addToolBar(self.transport)
        self.transport.play_toggled.connect(self._bridge.sig_run.emit)
        self.transport.step_clicked.connect(self._bridge.sig_step.emit)
        self.transport.reset_clicked.connect(self._bridge.sig_reset.emit)
        self.transport.speed_changed.connect(self._bridge.sig_speed.emit)
        self.transport.cmap_changed.connect(self._bridge.sig_cmap.emit)
        self.transport.snapshot_clicked.connect(self._snapshot_dialog)

        # Family tree (left dock)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._populate_tree()
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        left = QDockWidget("Families", self)
        left.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        left.setWidget(self._tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)

        # Params dock (right): preset picker + auto form
        self._presets = QComboBox()
        self._presets.activated.connect(self._on_preset)
        self._form_host = QWidget()
        self._form_layout = QVBoxLayout(self._form_host)
        self._form_layout.setContentsMargins(6, 6, 6, 6)
        self._form_layout.addWidget(QLabel("Preset"))
        self._form_layout.addWidget(self._presets)
        self._form_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form_host)
        right = QDockWidget("Parameters", self)
        right.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        right.setWidget(scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right)

        # Status bar
        self._status_gen = QLabel("gen 0")
        self._status_sps = QLabel("")
        bar = self.statusBar()
        assert bar is not None
        bar.addPermanentWidget(self._status_sps)
        bar.addWidget(self._status_gen)

        # Start on the first registered family
        first = next(iter(FAMILIES))
        self.select_family(first)

    # -- family / params ---------------------------------------------------------------

    def select_family(self, key: str) -> None:
        family = FAMILIES[key]
        self._family = family
        params = family.params_cls()

        if self._form is not None:
            self._form_layout.removeWidget(self._form)
            self._form.setParent(None)  # immediate: deleteLater alone leaves it painted
            self._form.deleteLater()
        self._form = ParamForm(field_specs(family.params_cls), params.to_dict())
        self._form.edited.connect(self._on_params_edited)
        self._form_layout.insertWidget(2, self._form)

        self._presets.blockSignals(True)
        self._presets.clear()
        self._presets.addItem("— preset —")
        self._presets.addItems(list(family.presets))
        self._presets.blockSignals(False)

        self.transport.set_cmap(family.default_cmap)
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
        self._bridge.sig_params.emit(params)

    # -- engine feedback -----------------------------------------------------------------

    def _on_frame(self, _rgb: object, generation: int) -> None:
        self._status_gen.setText(f"gen {generation:,}")

    def _on_stats(self, generation: int, sps: float) -> None:
        self._status_gen.setText(f"gen {generation:,}")
        self._status_sps.setText(f"{sps:,.0f} steps/s")

    def _on_engine_error(self, message: str) -> None:
        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(message, 5000)

    def _on_engine_params(self, params: object) -> None:
        """Engine-side param change (click/wheel zoom): sync the form silently."""
        if self._form is not None and isinstance(params, Params):
            self._form.set_values(params.to_dict())

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
