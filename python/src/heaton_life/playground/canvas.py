"""Canvas: blits the latest RGB frame, aspect-preserving, hard pixels."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PyQt6.QtCore import QRect, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget


class Canvas(QWidget):
    frame_shown = pyqtSignal()  # ack for the engine's backpressure counter

    def __init__(self) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._rgb: NDArray[np.uint8] | None = None
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
        target = QRect((self.width() - tw) // 2, (self.height() - th) // 2, tw, th)
        painter.drawImage(target, self._image)  # no smoothing hint -> nearest-neighbor
