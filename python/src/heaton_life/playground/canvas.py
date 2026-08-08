"""Canvas: blits the latest RGB frame, aspect-preserving, hard pixels. Paintable.

Mouse painting emits (cell_x, cell_y, button) with button codes:
1 = left (draw), 2 = right (erase), 3 = Ctrl/Cmd+left (family-specific extra).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget


class Canvas(QWidget):
    frame_shown = pyqtSignal()  # ack for the engine's backpressure counter
    cell_pressed = pyqtSignal(int, int, int)  # x, y, button code

    def __init__(self) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._rgb: NDArray[np.uint8] | None = None
        self._target: QRect | None = None
        self._last_paint: tuple[int, int, int] | None = None
        self.generation = 0
        self.setMinimumSize(320, 320)

    @property
    def last_rgb(self) -> NDArray[np.uint8] | None:
        """The most recent frame as an array (used for PNG export)."""
        return self._rgb

    def show_frame(self, rgb: object, generation: int) -> None:
        arr = np.ascontiguousarray(rgb, dtype=np.uint8)
        height, width = arr.shape[:2]
        self._rgb = arr
        self._image = QImage(
            arr.tobytes(), width, height, 3 * width, QImage.Format.Format_RGB888
        ).copy()
        self.generation = generation
        self.update()
        self.frame_shown.emit()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 18, 22))
        if self._image is None:
            return
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        tw, th = max(1, int(iw * scale)), max(1, int(ih * scale))
        self._target = QRect((self.width() - tw) // 2, (self.height() - th) // 2, tw, th)
        painter.drawImage(self._target, self._image)  # no smoothing hint -> nearest-neighbor

    # -- painting ------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        code = self._button_code(event.button(), event.modifiers())
        if code:
            self._last_paint = None
            self._emit_paint(event.position().toPoint(), code)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        buttons = event.buttons()
        if buttons & Qt.MouseButton.LeftButton:
            code = self._button_code(Qt.MouseButton.LeftButton, event.modifiers())
        elif buttons & Qt.MouseButton.RightButton:
            code = 2
        else:
            return
        self._emit_paint(event.position().toPoint(), code)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._last_paint = None

    @staticmethod
    def _button_code(button: Qt.MouseButton, modifiers: Qt.KeyboardModifier) -> int:
        if button == Qt.MouseButton.LeftButton:
            extra = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
            return 3 if modifiers & extra else 1
        if button == Qt.MouseButton.RightButton:
            return 2
        return 0

    def _emit_paint(self, pos: QPoint, code: int) -> None:
        if self._image is None or self._target is None:
            return
        target = self._target
        if not target.contains(pos):
            return
        iw, ih = self._image.width(), self._image.height()
        x = min(max((pos.x() - target.x()) * iw // target.width(), 0), iw - 1)
        y = min(max((pos.y() - target.y()) * ih // target.height(), 0), ih - 1)
        cell = (x, y, code)
        if cell == self._last_paint:
            return
        self._last_paint = cell
        self.cell_pressed.emit(x, y, code)
