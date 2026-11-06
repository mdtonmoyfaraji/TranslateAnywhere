from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

WT = Qt.WindowType


class SnipOverlay(QWidget):
    """Dim overlay on one screen; drag a rectangle to OCR it."""

    selected = Signal(QRect)   # global logical coordinates
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(None, WT.FramelessWindowHint | WT.WindowStaysOnTopHint | WT.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin = None
        self._cur = None

    def start(self, screen) -> None:
        self._origin = self._cur = None
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _rect(self):
        if self._origin is None or self._cur is None:
            return None
        return QRect(self._origin, self._cur).normalized()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        r = self._rect()
        if r:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(r, QColor(0, 0, 0, 255))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.fillRect(r, QColor(0, 0, 0, 1))   # alpha 1: keeps the hole clickable for this window
            p.setPen(QPen(QColor("#6a8dff"), 2))
            p.drawRect(r)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = self._cur = e.position().toPoint()
        else:
            self.cancel()

    def mouseMoveEvent(self, e) -> None:
        if self._origin is not None:
            self._cur = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        r = self._rect()
        self._origin = self._cur = None
        self.hide()
        if r is None or r.width() < 8 or r.height() < 8:
            self.cancelled.emit()
            return
        self.selected.emit(r.translated(self.geometry().topLeft()))

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.cancel()
