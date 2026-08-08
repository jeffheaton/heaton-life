"""Transport bar: play/pause, single step, reset, speed, colormap, snapshot."""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QLabel, QSlider, QStyle, QToolBar, QWidget

from heaton_life.render import list_colormaps

_SPEED_MAX = 960  # steps/second at the top of the slider (log scale)


def slider_to_speed(value: int) -> int:
    return max(1, round(math.pow(_SPEED_MAX, value / 100)))


class Transport(QToolBar):
    play_toggled = pyqtSignal(bool)
    step_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()
    speed_changed = pyqtSignal(int)  # steps/second
    cmap_changed = pyqtSignal(str)
    cell_scale_changed = pyqtSignal(int)  # displayed pixels per grid cell; 0 = fit
    snapshot_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Transport", parent)
        self.setMovable(False)
        style = self.style()
        assert style is not None

        play = self.addAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "Play")
        assert play is not None
        play.setCheckable(True)
        play.setShortcut("Space")
        play.toggled.connect(self._on_play)
        self._play = play

        step = self.addAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward), "Step"
        )
        assert step is not None
        step.setShortcut("N")
        step.triggered.connect(self.step_clicked.emit)

        reset = self.addAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Reset"
        )
        assert reset is not None
        reset.setShortcut("R")
        reset.triggered.connect(self.reset_clicked.emit)

        self.addSeparator()
        self.addWidget(QLabel(" Speed "))
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(60)  # ~60 steps/s
        self._slider.setFixedWidth(140)
        self._slider.valueChanged.connect(self._on_speed)
        self.addWidget(self._slider)
        self._speed_label = QLabel(f" {slider_to_speed(60)} st/s ")
        self.addWidget(self._speed_label)

        self.addSeparator()
        self.addWidget(QLabel(" Colors "))
        self._cmaps = QComboBox()
        self._cmaps.addItems(list_colormaps())
        self._cmaps.currentTextChanged.connect(self.cmap_changed.emit)
        self.addWidget(self._cmaps)

        self.addSeparator()
        self.addWidget(QLabel(" Cell "))
        self._cell = QComboBox()
        self._cell.addItem("Fit", 0)
        for k in (1, 2, 3, 4, 6, 8, 12, 16):
            self._cell.addItem(f"{k} px", k)
        self._cell.currentIndexChanged.connect(self._on_cell_scale)
        self.addWidget(self._cell)

        self.addSeparator()
        snapshot = self.addAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "Save PNG…"
        )
        assert snapshot is not None
        snapshot.setShortcut("Ctrl+S")
        snapshot.triggered.connect(self.snapshot_clicked.emit)

    @property
    def speed(self) -> int:
        return slider_to_speed(self._slider.value())

    def set_cmap(self, name: str) -> None:
        self._cmaps.blockSignals(True)
        self._cmaps.setCurrentText(name)
        self._cmaps.blockSignals(False)

    def set_playing(self, playing: bool) -> None:
        self._play.setChecked(playing)

    def _on_play(self, checked: bool) -> None:
        style = self.style()
        assert style is not None
        icon = (
            QStyle.StandardPixmap.SP_MediaPause if checked else QStyle.StandardPixmap.SP_MediaPlay
        )
        self._play.setIcon(style.standardIcon(icon))
        self.play_toggled.emit(checked)

    def _on_speed(self, value: int) -> None:
        speed = slider_to_speed(value)
        self._speed_label.setText(f" {speed} st/s ")
        self.speed_changed.emit(speed)

    def _on_cell_scale(self, index: int) -> None:
        data = self._cell.itemData(index)
        self.cell_scale_changed.emit(int(data) if data is not None else 0)
