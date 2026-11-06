from __future__ import annotations

import copy
import logging
import math
import threading
import time

from PySide6.QtCore import QBuffer, QIODevice, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import capture, ocr, translator, winutil
from .config import Config
from .hooks import InputHooks
from .ui_bubble import DockBubble, MiniBubble, make_icon
from .ui_popup import TranslatePopup
from .ui_settings import SettingsDialog
from .ui_snip import SnipOverlay

log = logging.getLogger(__name__)


def _dist(a: QPoint, b: QPoint) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


class Controller(QObject):
    translated = Signal(int, bool, str, str, int, str)     # rid, ok, text/error, conn name, ms, conn id
    capture_done = Signal(str, str, QPoint, str, str)      # text, source, anchor, mode, error
    restore_bubble = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cfg = Config()
        self.hooks = InputHooks()
        self.bubble = DockBubble(self.cfg)
        self.mini = MiniBubble()
        self.popup = TranslatePopup(self.cfg)
        self.snip = SnipOverlay()
        self.tray = QSystemTrayIcon(make_icon(), app)
        self.tray.setToolTip("Swift Translate Win")
        self._settings_open = False
        self._rid = 0
        self._pending = ("", QPoint())
        self._down_pos = QPoint()
        self._last_up_t = 0.0
        self._last_up_pos = QPoint(-999, -999)
        self._is_dbl = False

        self.hooks.mouse_event.connect(self.on_mouse)
        self.hooks.snip_pressed.connect(self.on_snip_key)
        self.hooks.esc_pressed.connect(self.on_esc)
        self.bubble.clicked.connect(self.on_bubble_click)
        self.bubble.dropped.connect(self.on_bubble_dropped)
        self.bubble.menu_requested.connect(self.show_bubble_menu)
        self.mini.clicked.connect(self.on_mini_clicked)
        self.popup.translate_requested.connect(lambda t, lang: self.start_translation(t, self._popup_anchor(), lang))
        self.popup.settings_requested.connect(self.open_settings)
        self.snip.selected.connect(self.on_snip_selected)
        self.translated.connect(self.on_translated)
        self.capture_done.connect(self.on_capture_done)
        self.restore_bubble.connect(self.bubble.show_if_enabled)
        self.tray.activated.connect(self._tray_activated)

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        self.apply_config(first=True)
        self.tray.show()
        try:
            self.hooks.start()
        except Exception:
            log.exception("hooks failed")
            self.tray.showMessage("Swift Translate Win", "Could not start the global keyboard/mouse hooks.",
                                  QSystemTrayIcon.MessageIcon.Warning, 5000)
        if not self.cfg["connections"]:
            self.tray.showMessage("Swift Translate Win",
                                  "Add an API connection first: tray icon \u2192 Settings \u2192 API connections.",
                                  QSystemTrayIcon.MessageIcon.Information, 7000)
        else:
            self.tray.showMessage("Swift Translate Win",
                                  f"Running. Hold {self.cfg['trigger_name']} + select text, "
                                  f"or drag the bubble onto text.",
                                  QSystemTrayIcon.MessageIcon.Information, 4000)

    def apply_config(self, first: bool = False) -> None:
        c = self.cfg
        h = self.hooks
        h.selection_enabled = bool(c["selection_enabled"])
        h.snip_enabled = bool(c["snip_enabled"])
        h.suppress_trigger = bool(c["suppress_trigger"])
        h.trigger_vk = int(c["trigger_vk"])
        h.snip_vk = int(c["snip_vk"])
        self.bubble.apply_config()
        self.popup.apply_config()
        winutil.set_autostart(bool(c["autostart"]))
        self._build_tray_menu()

    def _build_tray_menu(self) -> None:
        m = QMenu()
        m.addAction("Quick translate\u2026", self.quick_translate)
        m.addAction("Translate clipboard", self.translate_clipboard)
        m.addAction(f"Screen snip OCR ({self.cfg['snip_name']})", self.on_snip_key)
        m.addSeparator()
        act = m.addAction("Pause selection / hotkeys")
        act.setCheckable(True)
        act.setChecked(not self.hooks.enabled)
        act.toggled.connect(self._toggle_pause)
        bub = m.addAction("Show floating bubble")
        bub.setCheckable(True)
        bub.setChecked(bool(self.cfg["bubble_enabled"]))
        bub.toggled.connect(self._toggle_bubble)
        m.addAction("Settings\u2026", self.open_settings)
        m.addSeparator()
        m.addAction("Quit", self.quit)
        self._tray_menu = m
        self.tray.setContextMenu(m)

    def _toggle_pause(self, on: bool) -> None:
        self.hooks.enabled = not on
        if on:
            self.hooks._trigger_down = False

    def _toggle_bubble(self, on: bool) -> None:
        self.cfg["bubble_enabled"] = bool(on)
        self.cfg.save()
        self.bubble.apply_config()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.quick_translate()

    def quit(self) -> None:
        self.hooks.stop()
        self.tray.hide()
        self.app.quit()

    def open_settings(self) -> None:
        if self._settings_open:
            return
        self._settings_open = True
        self.popup.hide()
        try:
            dlg = SettingsDialog(self.cfg, self.hooks)
            dlg.setWindowIcon(make_icon())
            if dlg.exec():
                self.apply_config()
        finally:
            self._settings_open = False

    # --------------------------------------------------------- quick actions
    def quick_translate(self) -> None:
        geo = self.bubble.geometry()
        if self.cfg["bubble_enabled"] and self.bubble.isVisible():
            x = geo.left() - 460 if self.cfg["bubble_side"] == "right" else geo.right() + 10
            anchor = QPoint(x, geo.top())
        else:
            anchor = QCursor.pos()
        self.popup.show_input(anchor, self.cfg["target_language"])

    def on_bubble_click(self) -> None:
        self.quick_translate()

    def translate_clipboard(self) -> None:
        text = winutil.get_clip_text().strip()
        if not text:
            self.popup.show_message("The clipboard has no text.", QCursor.pos())
            return
        self.start_translation(text, QCursor.pos())

    def show_bubble_menu(self, pos: QPoint) -> None:
        m = QMenu()
        m.addAction("Quick translate\u2026", self.quick_translate)
        m.addAction("Translate clipboard", self.translate_clipboard)
        m.addAction("Screen snip OCR", self.on_snip_key)
        m.addSeparator()
        m.addAction("Move to left edge", lambda: self._dock("left"))
        m.addAction("Move to right edge", lambda: self._dock("right"))
        m.addAction("Hide bubble", lambda: self._toggle_bubble(False))
        m.addSeparator()
        m.addAction("Settings\u2026", self.open_settings)
        m.addAction("Quit", self.quit)
        m.exec(pos)

    def _dock(self, side: str) -> None:
        self.cfg["bubble_side"] = side
        self.cfg.save()
        self.bubble.place_docked(animate=True)

    def _popup_anchor(self) -> QPoint:
        return self.popup._anchor

    # ------------------------------------------------- selection via held key
    def on_mouse(self, kind: str, held: bool) -> None:
        pos = QCursor.pos()
        now = time.monotonic()
        if kind in ("ldown", "other_down"):
            if self.popup.isVisible() and not self.popup.keep_open and not self.popup.frameGeometry().contains(pos):
                self.popup.hide()
            if self.mini.isVisible() and not self.mini.frameGeometry().contains(pos):
                self.mini.hide()
        if kind == "ldown":
            self._down_pos = pos
            dbl = QApplication.doubleClickInterval() / 1000.0
            self._is_dbl = (now - self._last_up_t) < dbl and _dist(pos, self._last_up_pos) < 8
        elif kind == "lup":
            c = self.cfg
            if c["selection_enabled"] and held and self.hooks.enabled:
                d = _dist(pos, self._down_pos)
                if d >= c["min_drag_px"] and c["on_drag"]:
                    self.begin_capture("drag", QRect(self._down_pos, pos).normalized(), pos)
                elif d < c["min_drag_px"] and self._is_dbl and c["on_double_click"]:
                    self.begin_capture("dbl", QRect(pos, pos), pos)
            self._last_up_t = now
            self._last_up_pos = pos

    def on_esc(self) -> None:
        if self.snip.isVisible():
            self.snip.cancel()
        elif self.popup.isVisible() and not self.popup.keep_open:
            self.popup.hide()
        self.mini.hide()

    # ----------------------------------------------------- drag bubble onto text
    def on_bubble_dropped(self, gp: QPoint) -> None:
        QTimer.singleShot(90, lambda: self.begin_capture("drop", QRect(), gp))

    # ------------------------------------------------------------- capturing
    def grab_region(self, region: QRect):
        scr = QGuiApplication.screenAt(region.center()) or QGuiApplication.primaryScreen()
        geo = scr.geometry()
        r = region.intersected(geo)
        if r.width() < 4 or r.height() < 4:
            return None
        img = scr.grabWindow(0).toImage()
        s = img.width() / max(1, geo.width())
        crop = img.copy(int((r.x() - geo.x()) * s), int((r.y() - geo.y()) * s),
                        int(r.width() * s), int(r.height() * s))
        up = 2.0 if (crop.width() * crop.height() < 1_200_000 and max(crop.width(), crop.height()) * 2 <= 6000) else 1.0
        if up != 1.0:
            crop = crop.scaled(int(crop.width() * up), int(crop.height() * up),
                               Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        crop.save(buf, "PNG")
        return {"png": bytes(buf.data()), "rect": r, "scale": s * up}

    def begin_capture(self, mode: str, rect: QRect, pos: QPoint) -> None:
        shot = None
        try:
            if ocr.AVAILABLE and (self.cfg["ocr_fallback"] or mode == "drop"):
                region = rect if mode == "drag" else QRect(pos.x() - 350, pos.y() - 100, 700, 200)
                shot = self.grab_region(region)
        except Exception:
            log.exception("screen grab failed")
        threading.Thread(target=self._capture_worker, args=(mode, pos, shot, copy.deepcopy(self.cfg.data)),
                         daemon=True).start()

    def _ocr_text(self, shot, pos: QPoint, mode: str, c: dict) -> str:
        lines = ocr.recognize(shot["png"], c["ocr_lang"])
        if mode == "drag":
            return "\n".join(l.text for l in lines)
        px = (pos.x() - shot["rect"].x()) * shot["scale"]
        py = (pos.y() - shot["rect"].y()) * shot["scale"]
        return ocr.pick_text(lines, px, py, c["drop_scope"])

    def _capture_worker(self, mode: str, pos: QPoint, shot, c: dict) -> None:
        text, source, err = "", "copy", ""
        try:
            if mode in ("drag", "dbl"):
                time.sleep(0.12)                      # let the app finish updating its selection
                text = capture.copy_selection(c["restore_clipboard"])
                if not text.strip() and shot and c["ocr_fallback"]:
                    try:
                        text, source = self._ocr_text(shot, pos, mode, c), "ocr"
                    except Exception as e:
                        err = str(e)
            else:                                      # "drop": bubble released over text
                method = c["drop_method"]
                ocr_failed = False
                if method in ("auto", "ocr") and shot is not None:
                    try:
                        text, source = self._ocr_text(shot, pos, mode, c), "ocr"
                    except Exception as e:
                        err, ocr_failed = str(e), True
                if not text.strip() and (method == "click" or (method == "auto" and (not ocr.AVAILABLE or ocr_failed))):
                    capture.click_select({"word": 2, "line": 3, "paragraph": 3}.get(c["drop_scope"], 3))
                    time.sleep(0.15)
                    text = capture.copy_selection(c["restore_clipboard"])
                    source = "copy"
                    if text.strip():
                        err = ""
        except Exception as e:
            log.exception("capture failed")
            err = str(e)
        finally:
            self.capture_done.emit(text or "", source, pos, mode, err)
            if mode == "drop":
                self.restore_bubble.emit()

    def on_capture_done(self, text: str, source: str, pos: QPoint, mode: str, err: str) -> None:
        text = text.strip()
        if not text:
            msg = err or "No text found there."
            if source == "ocr" or not ocr.AVAILABLE:
                msg += "\n(Tip: for text that cannot be selected, use the screen snip key or the bubble.)"
            self.popup.show_message(msg, pos)
            return
        if self.cfg["auto_translate"] or mode in ("drop", "snip"):
            self.start_translation(text, pos)
        else:
            self._pending = (text, pos)
            self.mini.show_at(pos)

    def on_mini_clicked(self) -> None:
        text, pos = self._pending
        if text:
            self.start_translation(text, pos)

    # ------------------------------------------------------------ screen snip
    def on_snip_key(self) -> None:
        if not ocr.AVAILABLE:
            self.popup.show_message("Windows OCR is not available in this build, so screen snip is disabled.",
                                    QCursor.pos())
            return
        if self.snip.isVisible():
            self.snip.cancel()
            return
        self.popup.hide()
        self.mini.hide()
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.snip.start(scr)

    def on_snip_selected(self, rect: QRect) -> None:
        QTimer.singleShot(160, lambda: self._after_snip(rect))

    def _after_snip(self, rect: QRect) -> None:
        shot = None
        try:
            shot = self.grab_region(rect)
        except Exception:
            log.exception("snip grab failed")
        anchor = rect.bottomLeft()
        if shot is None:
            self.popup.show_message("Could not capture that area.", anchor)
            return
        threading.Thread(target=self._snip_worker, args=(shot, anchor, copy.deepcopy(self.cfg.data)),
                         daemon=True).start()

    def _snip_worker(self, shot, anchor: QPoint, c: dict) -> None:
        text, err = "", ""
        try:
            lines = ocr.recognize(shot["png"], c["ocr_lang"])
            text = "\n".join(l.text for l in lines)
            if text.strip() and c["snip_copy_text"]:
                winutil.set_clip_text(text)
        except Exception as e:
            log.exception("snip ocr failed")
            err = str(e)
        self.capture_done.emit(text, "ocr", anchor, "snip", err)

    # ------------------------------------------------------------ translating
    def start_translation(self, text: str, anchor: QPoint, target: str | None = None) -> None:
        text = text.strip()
        if not text:
            return
        self._rid += 1
        rid = self._rid
        target = target or self.cfg["target_language"]
        self.mini.hide()
        self.popup.show_loading(text, target, anchor)
        data = copy.deepcopy(self.cfg.data)
        threading.Thread(target=self._translate_worker, args=(rid, text, target, data), daemon=True).start()

    def _translate_worker(self, rid: int, text: str, target: str, data: dict) -> None:
        try:
            res = translator.translate(data, text, target)
            self.translated.emit(rid, True, res.text, res.conn_name, res.ms, res.conn_id)
        except translator.TranslationError as e:
            self.translated.emit(rid, False, str(e), "", 0, "")
        except Exception as e:
            log.exception("translate worker")
            self.translated.emit(rid, False, f"Unexpected error: {e}", "", 0, "")

    def on_translated(self, rid: int, ok: bool, text: str, name: str, ms: int, conn_id: str) -> None:
        if rid != self._rid:
            return
        if ok:
            if conn_id and conn_id != self.cfg["last_ok_id"]:
                self.cfg["last_ok_id"] = conn_id
                self.cfg.save()
            self.popup.show_result(text, f"via {name} \u00b7 {ms} ms")
        else:
            self.popup.show_error(text)
