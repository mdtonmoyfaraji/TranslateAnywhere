from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from .langcombo import make_lang_combo

WT = Qt.WindowType
WIDTH = 440

STYLE = """
#card { background:#1e222d; border:1px solid #343a4d; border-radius:12px; }
QLabel { color:#aab2c5; }
QLabel#status { color:#8791a8; font-size:9pt; }
QTextEdit { background:#262b38; color:#eceff6; border:1px solid #343a4d; border-radius:8px; padding:4px;
            selection-background-color:#4a6cf7; }
QComboBox { background:#262b38; color:#eceff6; border:1px solid #343a4d; border-radius:6px; padding:3px 6px; }
QComboBox QAbstractItemView { background:#262b38; color:#eceff6; selection-background-color:#4a6cf7; }
QPushButton { background:#2d3447; color:#eceff6; border:none; border-radius:6px; padding:5px 12px; }
QPushButton:hover { background:#3a4360; }
QPushButton#go { background:#4a6cf7; }
QPushButton#go:hover { background:#5d7bff; }
QPushButton#close { background:transparent; color:#8791a8; padding:2px 8px; font-size:11pt; }
QPushButton#close:hover { color:#ffffff; }
"""


class CopyButton(QToolButton):
    """Small 'copy' icon button (two overlapping sheets); shows a check mark after copying."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Copy")
        self._done = False
        self.setStyleSheet("QToolButton{background:#2d3447;border:none;border-radius:6px;}"
                           "QToolButton:hover{background:#4a6cf7;}")

    def flash(self) -> None:
        self._done = True
        self.update()
        QTimer.singleShot(1000, self._reset)

    def _reset(self) -> None:
        self._done = False
        self.update()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#eceff6"), 1.6)
        p.setPen(pen)
        if self._done:
            p.setPen(QPen(QColor("#6ee7a0"), 2.2))
            p.drawLine(7, 13, 11, 17)
            p.drawLine(11, 17, 19, 8)
            return
        p.drawRoundedRect(9, 6, 10, 12, 2, 2)      # back sheet
        p.setBrush(QColor("#2d3447"))
        p.drawRoundedRect(6, 9, 10, 12, 2, 2)      # front sheet


class CopyField(QTextEdit):
    """Text box with a copy icon in its top-right corner."""

    def __init__(self) -> None:
        super().__init__()
        self.setViewportMargins(0, 0, 32, 0)
        self.btn = CopyButton(self)
        self.btn.clicked.connect(self._copy)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.toPlainText())
        self.btn.flash()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.btn.move(self.width() - self.btn.width() - 4, 4)


class SrcEdit(CopyField):
    submit = Signal()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit.emit()
            return
        super().keyPressEvent(e)


class TranslatePopup(QWidget):
    translate_requested = Signal(str, str)     # text, target language
    settings_requested = Signal()

    def __init__(self, cfg) -> None:
        super().__init__(None, WT.FramelessWindowHint | WT.WindowStaysOnTopHint | WT.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.cfg = cfg
        self.keep_open = False
        self._anchor = QPoint()
        self._offset = QPoint(0, 26)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        self.card = QFrame()
        self.card.setObjectName("card")
        outer.addWidget(self.card)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.card.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(QLabel("Translate to"))
        self.lang = make_lang_combo(cfg["target_language"])
        self.lang.setMinimumWidth(190)
        head.addWidget(self.lang)
        head.addStretch(1)
        self.btn_close = QPushButton("\u2715")
        self.btn_close.setObjectName("close")
        head.addWidget(self.btn_close)
        lay.addLayout(head)

        self.src = SrcEdit()
        self.src.setAcceptRichText(False)
        self.src.setPlaceholderText("Type or paste text, press Enter to translate (Shift+Enter = new line)")
        lay.addWidget(self.src)

        self.out = CopyField()
        self.out.setReadOnly(True)
        lay.addWidget(self.out)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.hide()
        self.btn_go = QPushButton("Translate")
        self.btn_go.setObjectName("go")
        foot.addWidget(self.btn_settings)
        foot.addWidget(self.btn_go)
        lay.addLayout(foot)

        self.setFixedWidth(WIDTH)
        self.apply_config()

        self.btn_close.clicked.connect(self.hide)
        self.btn_go.clicked.connect(self._submit)
        self.src.submit.connect(self._submit)
        self.lang.activated.connect(lambda _i: self._submit())
        self.btn_settings.clicked.connect(self.settings_requested)

    def apply_config(self) -> None:
        self.setStyleSheet(STYLE + f"* {{ font-size:{int(self.cfg['popup_font_size'])}pt; }}"
                           "QLabel#status { font-size:9pt; }")

    # ---- actions
    def _submit(self) -> None:
        text = self.src.toPlainText().strip()
        if text:
            self.translate_requested.emit(text, self.lang.currentText().strip() or self.cfg["target_language"])

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)

    # ---- states
    def _prepare(self, anchor: QPoint, target: str, offset: QPoint) -> None:
        self._anchor = anchor
        self._offset = offset
        self.lang.setCurrentText(target)

    def show_loading(self, text: str, target: str, anchor: QPoint) -> None:
        self.keep_open = False
        self._prepare(anchor, target, QPoint(0, 26))
        self.src.setPlainText(text)
        self.out.setPlainText("")
        self.status.setText("Translating\u2026")
        self.btn_settings.hide()
        self._present()

    def show_result(self, text: str, status: str) -> None:
        self.out.setPlainText(text)
        self.status.setText(status)
        self.btn_settings.hide()
        self._fit()

    def show_error(self, msg: str) -> None:
        self.out.setPlainText(msg)
        self.status.setText("Translation failed")
        self.btn_settings.show()
        self._fit()

    def show_message(self, msg: str, anchor: QPoint) -> None:
        self.keep_open = False
        self._prepare(anchor, self.cfg["target_language"], QPoint(0, 26))
        self.src.setPlainText("")
        self.out.setPlainText(msg)
        self.status.setText("")
        self.btn_settings.hide()
        self._present()

    def show_input(self, anchor: QPoint, target: str) -> None:
        self.keep_open = True
        self._prepare(anchor, target, QPoint(0, 0))
        self.src.setPlainText("")
        self.out.setPlainText("")
        self.status.setText("")
        self.btn_settings.hide()
        self._present()
        self.activateWindow()
        self.src.setFocus()

    # ---- layout
    def _present(self) -> None:
        self._fit()
        self.show()
        self.raise_()

    def _fit(self) -> None:
        inner = WIDTH - 20 - 24 - 12 - 32
        for ed, mn, mx in ((self.src, 40, 100), (self.out, 56, 280)):
            ed.document().setTextWidth(inner)
            h = int(ed.document().size().height()) + 18
            ed.setFixedHeight(max(mn, min(mx, h)))
        self.adjustSize()
        self._reposition()

    def _reposition(self) -> None:
        scr = QGuiApplication.screenAt(self._anchor) or QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        p = self._anchor + self._offset
        w, h = self.width(), self.height()
        x = min(max(p.x(), geo.left()), geo.right() - w)
        y = p.y()
        if y + h > geo.bottom():
            y = self._anchor.y() - h - 10 if self._offset.y() else geo.bottom() - h
        y = max(geo.top(), min(y, geo.bottom() - h))
        self.move(x, y)
