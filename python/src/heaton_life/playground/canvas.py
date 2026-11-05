"""Canvas: blits the latest RGB frame, aspect-preserving, hard pixels. Paintable.

Mouse painting emits (cell_x, cell_y, button) with button codes:
1 = left (draw), 2 = right (erase), 3 = Ctrl/Cmd+left (family-specific extra).

A live-view family (HashLife) navigates here instead: the wheel and a trackpad pinch
zoom about the pointer, a drag pans (zoomed out past one cell per pixel, with Option/Alt
held, or with the middle button), and Ctrl/Cmd+click recenters. Its frames fill the
canvas (``fill_size``), and a resize keeps the view's center in place. Each change moves
the view at once and emits ``view_requested``; until the engine renders the new view, the
last frame is drawn where it lands in it (``ViewNavigator.frame_map``).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPaintEvent,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

from heaton_life.ca.hashlife import LifeView
from heaton_life.playground.navigator import ViewNavigator

_RECENTER = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier


class Canvas(QWidget):
    frame_shown = pyqtSignal()  # ack for the engine's backpressure counter
    cell_pressed = pyqtSignal(int, int, int)  # x, y, button code
    view_requested = pyqtSignal(object, object)  # a live view's LifeView, (width, height)

    def __init__(self) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._rgb: NDArray[np.uint8] | None = None
        self._target: QRect | None = None
        self._last_paint: tuple[int, int, int] | None = None
        self._wheel_accum = 0
        self._overlay: dict[str, object] | None = None
        self._display_scale = 0  # pixels per grid cell; 0 = fit to widget
        self._nav: ViewNavigator | None = None  # set while a live-view family shows
        self._frame_view: LifeView | None = None  # the view the shown frame was rendered at
        self._next_frame_view: LifeView | None = None
        self._drag: QPointF | None = None  # where a pan drag last was
        self._pinch = 0.0  # log2 of a pinch's scale not yet taken as whole zoom steps
        self._pinch_at: QPointF | None = None
        self.generation = 0
        self.setMinimumSize(320, 320)

    @property
    def last_rgb(self) -> NDArray[np.uint8] | None:
        """The most recent frame as an array (used for PNG export)."""
        return self._rgb

    def set_live_view(self, view: LifeView | None, size: tuple[int, int] | None = None) -> None:
        """Navigate here, showing a live-view family's ``view`` in frames of ``size``
        (width, height), or hand navigation back to the engine (None). A size that doesn't
        fill the canvas (params from before a resize) is refitted at once."""
        if view is None or size is None:
            self._nav = None
            self._frame_view = self._next_frame_view = None
        elif self._nav is None:
            self._nav = ViewNavigator(view, size)
        else:
            self._nav.view, self._nav.size = view, size
        self._drag = None
        self._pinch = 0.0
        self._update_cursor()
        self.update()
        self._fit_frame()

    def fill_size(self) -> tuple[int, int]:
        """The frame size, in frame pixels, that fills the canvas: one frame pixel per canvas
        pixel, or a fixed Cell scale's square of them."""
        k = self._display_scale or 1
        return max(1, self.width() // k), max(1, self.height() // k)

    def show_frame_view(self, view: object) -> None:
        """The view of the frame that comes next (the engine emits the two back to back)."""
        self._next_frame_view = view if isinstance(view, LifeView) else None

    def show_frame(self, rgb: object, generation: int) -> None:
        arr = np.ascontiguousarray(rgb, dtype=np.uint8)
        height, width = arr.shape[:2]
        self._rgb = arr
        self._image = QImage(
            arr.tobytes(), width, height, 3 * width, QImage.Format.Format_RGB888
        ).copy()
        self._frame_view = self._next_frame_view
        self.generation = generation
        self.update()
        self.frame_shown.emit()

    def show_overlay(self, payload: object) -> None:
        """Point-cloud overlay from the engine (boids triangles), or None to clear."""
        self._overlay = payload if isinstance(payload, dict) else None
        self.update()

    def set_display_scale(self, scale: int) -> None:
        """Fixed pixels per grid cell (1 = native resolution); 0 returns to fit. A live view
        refits its frames: each frame pixel is then a scale × scale square."""
        self._display_scale = max(0, scale)
        self.update()
        self._fit_frame()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._fit_frame()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 18, 22))
        if self._image is None:
            return
        nav = self._nav
        iw, ih = nav.size if nav is not None else (self._image.width(), self._image.height())
        if self._display_scale > 0:
            tw, th = iw * self._display_scale, ih * self._display_scale
        else:
            scale = min(self.width() / iw, self.height() / ih)
            tw, th = max(1, int(iw * scale)), max(1, int(ih * scale))
        # Centered; a fixed scale larger than the widget simply crops at the edges.
        self._target = QRect((self.width() - tw) // 2, (self.height() - th) // 2, tw, th)
        if nav is not None and self._frame_view is not None:
            self._paint_live(painter, nav, self._frame_view, tw / iw)
        else:
            painter.drawImage(self._target, self._image)  # no smoothing hint -> nearest-neighbor
        if self._overlay is not None:
            self._paint_overlay(painter, self._target)

    def _paint_live(
        self, painter: QPainter, nav: ViewNavigator, frame_view: LifeView, k: float
    ) -> None:
        """The last frame where it lands in the view being shown (k widget pixels per frame
        pixel), stretched by the part of a pinch not yet taken as a zoom step."""
        assert self._image is not None and self._target is not None
        target = self._target
        where = nav.frame_map(frame_view, (self._image.width(), self._image.height()))
        if where is None:
            return  # nothing of the last frame is in view; the engine's next one will be
        painter.save()
        painter.setClipRect(target)
        if self._pinch and self._pinch_at is not None:
            stretch = 2.0**self._pinch
            painter.translate(self._pinch_at)
            painter.scale(stretch, stretch)
            painter.translate(-self._pinch_at)
        painter.translate(target.x() + where.dx * k, target.y() + where.dy * k)
        painter.scale(where.scale * k, where.scale * k)
        painter.drawImage(0, 0, self._image)  # no smoothing hint -> nearest-neighbor
        painter.restore()

    def _paint_overlay(self, painter: QPainter, target: QRect) -> None:
        assert self._overlay is not None
        points = np.asarray(self._overlay["points"], dtype=np.float64)
        world = self._overlay["world"]
        assert isinstance(world, tuple)
        if points.size == 0:
            return
        sx = target.width() / float(world[0])
        sy = target.height() / float(world[1])
        cx = target.x() + points[:, 0] * sx
        cy = target.y() + points[:, 1] * sy
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(255, 205, 110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        heading = np.arctan2(points[:, 3], points[:, 2])
        size = max(2.2 * sx, 3.0)
        nose_x = cx + np.cos(heading) * size
        nose_y = cy + np.sin(heading) * size
        left_x = cx + np.cos(heading + 2.5) * size * 0.7
        left_y = cy + np.sin(heading + 2.5) * size * 0.7
        right_x = cx + np.cos(heading - 2.5) * size * 0.7
        right_y = cy + np.sin(heading - 2.5) * size * 0.7
        for i in range(points.shape[0]):
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(nose_x[i], nose_y[i]),
                        QPointF(left_x[i], left_y[i]),
                        QPointF(right_x[i], right_y[i]),
                    ]
                )
            )

    # -- painting ------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._nav is not None and self._navigation_press(event, self._nav):
            return
        code = self._button_code(event.button(), event.modifiers())
        if code:
            self._last_paint = None
            self._emit_paint(event.position().toPoint(), code)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._drag is not None and self._nav is not None and self._target is not None:
            pos = event.position()
            k = self._target.width() / self._nav.size[0]  # widget pixels per frame pixel
            if self._nav.pan((pos.x() - self._drag.x()) / k, (pos.y() - self._drag.y()) / k):
                self._view_moved()
            self._drag = pos
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
        if self._drag is not None:
            self._drag = None
            self._update_cursor()

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        event.accept()
        phase = event.phase()
        if phase == Qt.ScrollPhase.ScrollMomentum:
            return  # the coasting after a trackpad swipe would keep zooming on its own
        if phase in (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollEnd):
            self._wheel_accum = 0
        self._wheel_accum += event.angleDelta().y()
        while abs(self._wheel_accum) >= 120:  # one notch; trackpads drip small deltas
            step = 1 if self._wheel_accum > 0 else -1
            self._wheel_accum -= 120 * step
            if self._nav is not None:
                self._zoom(event.position(), step)
            else:
                self._last_paint = None
                self._emit_paint(event.position().toPoint(), 4 if step > 0 else 5)

    def event(self, event: QEvent | None) -> bool:
        if (
            self._nav is not None
            and event is not None
            and event.type() == QEvent.Type.NativeGesture
            and isinstance(event, QNativeGestureEvent)
        ):
            self._pinch_gesture(event)
            return True
        return super().event(event)

    # -- live-view navigation ------------------------------------------------------------

    def _navigation_press(self, event: QMouseEvent, nav: ViewNavigator) -> bool:
        """Recenter or start a pan drag; False leaves the press to draw or erase."""
        button, mods = event.button(), event.modifiers()
        if button == Qt.MouseButton.LeftButton and mods & _RECENTER:
            pixel = self._frame_pixel(event.position())
            if pixel is not None and nav.recenter(*pixel):
                self._view_moved()
            return True
        drawing = button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)
        if button == Qt.MouseButton.MiddleButton or (
            drawing and (nav.view.mag < 0 or mods & Qt.KeyboardModifier.AltModifier)
        ):
            self._drag = event.position()
            self._update_cursor()
            return True
        return False

    def _pinch_gesture(self, event: QNativeGestureEvent) -> None:
        """A trackpad pinch: whole 2× zoom steps about the fingers, and the fraction of a
        step between them shown by stretching the picture."""
        kind = event.gestureType()
        if kind == Qt.NativeGestureType.ZoomNativeGesture:
            self._pinch += math.log2(max(1.0 + event.value(), 1e-3))
            self._pinch_at = event.position()
            while abs(self._pinch) >= 1:
                step = 1 if self._pinch > 0 else -1
                self._pinch -= step
                if not self._zoom(self._pinch_at, step):
                    self._pinch = 0.0  # at a zoom limit: stop stretching
            self.update()
        elif kind == Qt.NativeGestureType.EndNativeGesture:
            if abs(self._pinch) >= 0.5 and self._pinch_at is not None:
                self._zoom(self._pinch_at, 1 if self._pinch > 0 else -1)
            self._pinch = 0.0
            self.update()
        elif kind == Qt.NativeGestureType.BeginNativeGesture:
            self._pinch = 0.0

    def _zoom(self, pos: QPointF, step: int) -> bool:
        """One 2× zoom step about the frame pixel under ``pos``; False when it can't."""
        pixel = self._frame_pixel(pos)
        if self._nav is None or pixel is None or not self._nav.zoom_at(*pixel, step):
            return False
        self._view_moved()
        return True

    def _frame_pixel(self, pos: QPointF) -> tuple[int, int] | None:
        """The frame pixel of the view being shown under widget point ``pos``."""
        target, nav = self._target, self._nav
        if target is None or nav is None or not target.contains(pos.toPoint()):
            return None
        fw, fh = nav.size
        x = min(max(int((pos.x() - target.x()) * fw / target.width()), 0), fw - 1)
        y = min(max(int((pos.y() - target.y()) * fh / target.height()), 0), fh - 1)
        return x, y

    def _fit_frame(self) -> None:
        """Size a live view's frames to fill the canvas, its center staying in place."""
        if self._nav is not None and self._nav.resize(self.fill_size()):
            self._view_moved()

    def _view_moved(self) -> None:
        assert self._nav is not None
        self._update_cursor()
        self.update()
        self.view_requested.emit(self._nav.view, self._nav.size)

    def _update_cursor(self) -> None:
        """A closed hand while panning, an open one where a drag would pan, a cross where a
        click draws."""
        if self._nav is None:
            self.unsetCursor()
        elif self._drag is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._nav.view.mag < 0:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

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
        if self._nav is not None:
            iw, ih = self._nav.size  # the view being shown, which the engine's matches
        else:
            iw, ih = self._image.width(), self._image.height()
        x = min(max((pos.x() - target.x()) * iw // target.width(), 0), iw - 1)
        y = min(max((pos.y() - target.y()) * ih // target.height(), 0), ih - 1)
        cell = (x, y, code)
        if cell == self._last_paint:
            return
        self._last_paint = cell
        self.cell_pressed.emit(x, y, code)
