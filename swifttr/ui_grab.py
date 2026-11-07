"""Full-screen 'grab text' overlay: a frozen screenshot with every OCR'd word selectable."""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import ocr

WT = Qt.WindowType


class GrabOverlay(QWidget):
    finished = Signal(str, QRect)      # selected text, bounding rect (global logical coordinates)
    cancelled = Signal()
    released = Signal()                # every mouse release (lets the controller close a 'hold' session)

    def __init__(self) -> None:
        super().__init__(None, WT.FramelessWindowHint | WT.WindowStaysOnTopHint | WT.Tool)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMouseTracking(True)
        self._pm = None
        self._lines = []
        self._flat = []                 # [(line_index, Word)]
        self._rects = []                # QRectF per flat word (logical overlay coordinates)
        self._sel = []                  # sorted flat indices
        self._anchor = None
        self._box_origin = None
        self._press = QPoint()
        self._dragged = False
        self._hover = -1
        self._ready = False
        self._dbl_t = 0.0
        self._finalize_timer = QTimer(self)
        self._finalize_timer.setSingleShot(True)
        self._finalize_timer.timeout.connect(self._finalize)

    # ------------------------------------------------------------------ control
    def start(self, screen, image, dpr: float) -> None:
        self._pm = QPixmap.fromImage(image)
        self._pm.setDevicePixelRatio(dpr)
        self._lines, self._flat, self._rects, self._sel = [], [], [], []
        self._anchor = self._box_origin = None
        self._hover = -1
        self._ready = False
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()

    def set_words(self, lines: list, factor: float) -> None:
        """factor converts OCR image pixels to logical overlay pixels."""
        self._lines = lines
        self._flat = [(li, w) for li, ln in enumerate(lines) for w in ln.words]
        self._rects = [QRectF(w.x * factor, w.y * factor, w.w * factor, w.h * factor) for _li, w in self._flat]
        self._ready = True
        self.update()

    def has_selection(self) -> bool:
        return bool(self._sel) or self._finalize_timer.isActive()

    def cancel(self) -> None:
        self._finalize_timer.stop()
        was = self.isVisible()
        self.hide()
        if was:
            self.cancelled.emit()

    # ------------------------------------------------------------------ geometry helpers
    def _nearest(self, pos: QPointF, max_dist: float = 1e9) -> int:
        best, bi = max_dist, -1
        for i, r in enumerate(self._rects):
            dx = max(r.left() - pos.x(), 0, pos.x() - r.right())
            dy = max(r.top() - pos.y(), 0, pos.y() - r.bottom())
            d = (dx * dx + dy * dy) ** 0.5
            if d < best:
                best, bi = d, i
        return bi

    def _select_range(self, a: int, b: int) -> None:
        lo, hi = min(a, b), max(a, b)
        self._sel = list(range(lo, hi + 1))

    def _line_indices(self, i: int) -> list:
        li = self._flat[i][0]
        return [k for k, (l, _w) in enumerate(self._flat) if l == li]

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._ready:
            return
        self._finalize_timer.stop()
        pos = e.position()
        self._press = e.position().toPoint()
        self._dragged = False
        i = self._nearest(pos, 28)
        if time.monotonic() - self._dbl_t < QApplication.doubleClickInterval() / 1000 and i >= 0:
            self._sel = self._line_indices(i)          # triple click = whole line
            self._anchor = None
            self._finalize_later(250)
            self.update()
            return
        if i >= 0:
            self._anchor = i
            self._box_origin = None
            self._sel = [i]
        else:
            self._anchor = None
            self._box_origin = e.position().toPoint()
            self._sel = []
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._ready:
            return
        i = self._nearest(e.position(), 28)
        if i >= 0:
            self._sel = [i]
            self._anchor = None
            self._dbl_t = time.monotonic()
            self._finalize_later(340)                  # wait: a third click may extend it to the line
            self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if e.buttons() & Qt.MouseButton.LeftButton and self._ready:
            if (e.position().toPoint() - self._press).manhattanLength() > 3:
                self._dragged = True
            if self._anchor is not None:
                j = self._nearest(pos)
                if j >= 0:
                    self._select_range(self._anchor, j)
            elif self._box_origin is not None:
                box = QRectF(QPointF(self._box_origin), pos).normalized()
                self._sel = [i for i, r in enumerate(self._rects) if r.intersects(box)]
            self.update()
            return
        h = self._nearest(pos, 1)
        if h != self._hover:
            self._hover = h
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._box_origin = None
        if self._dragged and self._sel:
            self._finalize()
        elif not self._finalize_timer.isActive():
            if not self._dragged:
                self._sel = []                          # plain single click: wait for double click
            self.update()
        self.released.emit()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif e.key() == Qt.Key.Key_A and (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and self._ready:
            self._sel = list(range(len(self._flat)))
            self._finalize()

    # ------------------------------------------------------------------ result
    def _finalize_later(self, ms: int) -> None:
        self._finalize_timer.start(ms)

    def _finalize(self) -> None:
        self._finalize_timer.stop()
        if not self._sel:
            return
        entries = [self._flat[i] for i in self._sel]
        text = ocr.join_words(entries, self._lines)
        rect = QRectF()
        for i in self._sel:
            rect = rect.united(self._rects[i]) if not rect.isNull() else QRectF(self._rects[i])
        g = self.geometry().topLeft()
        grect = QRect(int(rect.left()) + g.x(), int(rect.top()) + g.y(), int(rect.width()), int(rect.height()))
        self.hide()
        if text.strip():
            self.finished.emit(text, grect)
        else:
            self.cancelled.emit()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pm:
            p.drawPixmap(0, 0, self._pm)
        p.fillRect(self.rect(), QColor(0, 0, 0, 80))
        sel = set(self._sel)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1))
        for i, r in enumerate(self._rects):
            rr = r.adjusted(-1, -1, 1, 1)
            if i in sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(74, 108, 247, 170))
            elif i == self._hover:
                p.setPen(QPen(QColor(255, 255, 255, 200), 1))
                p.setBrush(QColor(255, 255, 255, 80))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 90), 1))
                p.setBrush(QColor(74, 108, 247, 38))
            p.drawRoundedRect(rr, 2, 2)
        # banner
        if not self._ready:
            msg = "Scanning the screen for text\u2026"
        elif self._flat:
            msg = (f"{len(self._flat)} words found  \u00b7  drag to select  \u00b7  double-click = word  "
                   f"\u00b7  triple-click = line  \u00b7  Ctrl+A = all  \u00b7  Esc = cancel")
        else:
            msg = "No text found on this screen  \u00b7  Esc = cancel"
        f = QFont("Segoe UI", 10)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(msg) + 36
        box = QRect((self.width() - w) // 2, 14, w, 34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 24, 34, 235))
        p.drawRoundedRect(box, 17, 17)
        p.setPen(QColor("#eceff6"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, msg)
