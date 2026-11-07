from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

WT = Qt.WindowType
WA = Qt.WidgetAttribute


def _paint_disc(p: QPainter, rect, text_scale: float = 0.28) -> None:
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, QColor("#6a8dff"))
    g.setColorAt(1, QColor("#8a5bff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(rect)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", max(7, int(rect.width() * text_scale)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "\u6587A")


def make_icon(size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_disc(p, pm.rect().adjusted(2, 2, -2, -2))
    p.end()
    return QIcon(pm)


class DockBubble(QWidget):
    """Floating bubble docked to any screen edge (left / right / top / bottom).

    * click                      -> quick-translate box
    * drag onto text + release   -> translate the text under the pointer
    * Shift+drag, or press-and-hold for half a second and then drag -> move the bubble (snaps to nearest edge)
    * right click                -> menu"""

    clicked = Signal()
    dropped = Signal(QPoint)
    menu_requested = Signal(QPoint)

    def __init__(self, cfg) -> None:
        super().__init__(None, WT.FramelessWindowHint | WT.WindowStaysOnTopHint | WT.Tool | WT.WindowDoesNotAcceptFocus)
        self.setAttribute(WA.WA_TranslucentBackground)
        self.setAttribute(WA.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cfg = cfg
        self._pressed = False
        self._dragging = False
        self._reposition = False
        self._move_mode = False
        self._press_pos = QPoint()
        self._screen = None
        self._anim = None
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._enter_move_mode)
        self.apply_config()

    def apply_config(self) -> None:
        s = int(self.cfg["bubble_size"])
        self.setFixedSize(s, s)
        self.setWindowOpacity(int(self.cfg["bubble_opacity"]) / 100)
        name = self.cfg["bubble_screen"]
        self._screen = next((sc for sc in QGuiApplication.screens() if sc.name() == name), None) \
            or QGuiApplication.primaryScreen()
        self.place_docked()
        if self.cfg["bubble_enabled"]:
            self.show()
        else:
            self.hide()

    def show_if_enabled(self) -> None:
        if self.cfg["bubble_enabled"]:
            self.place_docked()
            self.show()

    def dock_point(self) -> QPoint:
        geo = (self._screen or QGuiApplication.primaryScreen()).availableGeometry()
        s = self.width()
        side = self.cfg["bubble_side"]
        r = max(0.0, min(1.0, float(self.cfg["bubble_y"])))
        if side in ("left", "right"):
            x = geo.left() if side == "left" else geo.right() - s + 1
            y = geo.top() + int(r * max(1, geo.height() - s))
        else:
            y = geo.top() if side == "top" else geo.bottom() - s + 1
            x = geo.left() + int(r * max(1, geo.width() - s))
        return QPoint(x, y)

    def place_docked(self, animate: bool = False) -> None:
        target = self.dock_point()
        if animate and self.isVisible():
            self._anim = QPropertyAnimation(self, b"pos", self)
            self._anim.setDuration(170)
            self._anim.setEndValue(target)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.start()
        else:
            self.move(target)

    # ---- painting
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(3, 3, -3, -3)
        if self._dragging and not self._reposition:
            # pick mode: only a ring so the text underneath stays visible
            p.setPen(QPen(QColor("#6a8dff"), 3))
            p.setBrush(QColor(106, 141, 255, 45))
            p.drawEllipse(r)
            p.setPen(QPen(QColor("#ffffff"), 5))
            p.drawPoint(self.rect().center())
            return
        _paint_disc(p, r)
        if self._move_mode:
            p.setPen(QPen(QColor("#ffffff"), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(2, 2, -2, -2))

    def enterEvent(self, _e) -> None:
        self.setWindowOpacity(1.0)

    def leaveEvent(self, _e) -> None:
        if not self._pressed:
            self.setWindowOpacity(int(self.cfg["bubble_opacity"]) / 100)

    # ---- mouse
    def _enter_move_mode(self) -> None:
        if self._pressed and not self._dragging:
            self._move_mode = True
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(e.globalPosition().toPoint())
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._move_mode = False
            self._press_pos = e.globalPosition().toPoint()
            self._hold.start(500)

    def mouseMoveEvent(self, e) -> None:
        if not self._pressed:
            return
        gp = e.globalPosition().toPoint()
        if not self._dragging and (gp - self._press_pos).manhattanLength() > 6:
            self._dragging = True
            self._hold.stop()
            self.setWindowOpacity(1.0)
        if self._dragging:
            self._reposition = self._move_mode or bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.move(gp.x() - self.width() // 2, gp.y() - self.height() // 2)
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._pressed:
            return
        self._hold.stop()
        was_dragging, reposition, was_move = self._dragging, self._reposition, self._move_mode
        self._pressed = self._dragging = self._reposition = self._move_mode = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        gp = e.globalPosition().toPoint()
        if not was_dragging:
            if not was_move:
                self.clicked.emit()
            self.update()
            return
        if reposition:
            self._snap_to_edge(gp)
        else:
            # hide + go home so we never cover the text that is about to be read
            self.hide()
            self.place_docked()
            self.dropped.emit(gp)
        self.update()

    def _snap_to_edge(self, gp: QPoint) -> None:
        scr = QGuiApplication.screenAt(gp) or QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        s = self.width()
        dist = {
            "left": gp.x() - geo.left(), "right": geo.right() - gp.x(),
            "top": gp.y() - geo.top(), "bottom": geo.bottom() - gp.y(),
        }
        side = min(dist, key=dist.get)
        if side in ("left", "right"):
            ratio = (gp.y() - geo.top() - s / 2) / max(1, geo.height() - s)
        else:
            ratio = (gp.x() - geo.left() - s / 2) / max(1, geo.width() - s)
        self._screen = scr
        self.cfg["bubble_screen"] = scr.name()
        self.cfg["bubble_side"] = side
        self.cfg["bubble_y"] = max(0.0, min(1.0, ratio))
        self.cfg.save()
        self.place_docked(animate=True)


class MiniBubble(QWidget):
    """Small bubble that pops up next to freshly selected text; click it to translate."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__(None, WT.FramelessWindowHint | WT.WindowStaysOnTopHint | WT.Tool | WT.WindowDoesNotAcceptFocus)
        self.setAttribute(WA.WA_TranslucentBackground)
        self.setAttribute(WA.WA_ShowWithoutActivating)
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_at(self, pos: QPoint) -> None:
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        x = min(max(pos.x() + 14, geo.left()), geo.right() - self.width())
        y = min(max(pos.y() + 18, geo.top()), geo.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()
        self._timer.start(6000)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_disc(p, self.rect().adjusted(3, 3, -3, -3), 0.30)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._timer.stop()
            self.hide()
            self.clicked.emit()
