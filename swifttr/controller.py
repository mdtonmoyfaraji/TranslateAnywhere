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
from .poller import Poller
from .ui_bubble import DockBubble, MiniBubble, make_icon
from .ui_grab import GrabOverlay
from .ui_popup import WIDTH as POPUP_WIDTH, TranslatePopup
from .ui_settings import SettingsDialog
from .ui_snip import SnipOverlay

log = logging.getLogger(__name__)
HOLD_SECONDS = 0.35        # key held longer than this = "hold mode", shorter = "tap to toggle"


def _dist(a: QPoint, b: QPoint) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _png(img) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class Controller(QObject):
    translated = Signal(int, bool, str, str, int, str)     # rid, ok, text/error, conn name, ms, conn id
    capture_done = Signal(str, str, QPoint, str, str)      # text, source, anchor, mode, error
    restore_bubble = Signal()
    grab_ocr_ready = Signal(object, float, str)            # lines, factor, error

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cfg = Config()
        self.poller = Poller()
        self.bubble = DockBubble(self.cfg)
        self.mini = MiniBubble()
        self.popup = TranslatePopup(self.cfg)
        self.snip = SnipOverlay()
        self.grab = GrabOverlay()
        self.tray = QSystemTrayIcon(make_icon(), app)
        self.tray.setToolTip("Swift Translate Win")
        self._settings_open = False
        self._dropping = False
        self._rid = 0
        self._pending = ("", QPoint())
        self._down_pos = QPoint()
        self._down_ibeam = False
        self._last_up_t = 0.0
        self._last_up_pos = QPoint(-999, -999)
        self._is_dbl = False
        self._grab_down_t = 0.0
        self._grab_tap_close = False
        self._close_after_mouse = False
        capture.mute_fn = self.poller.mute

        self.poller.mouse_event.connect(self.on_mouse)
        self.poller.grab_key.connect(self.on_grab_key)
        self.poller.snip_pressed.connect(self.on_snip_key)
        self.poller.esc_pressed.connect(self.on_esc)
        self.bubble.clicked.connect(self.quick_translate)
        self.bubble.dropped.connect(self.on_bubble_dropped)
        self.bubble.menu_requested.connect(self.show_bubble_menu)
        self.mini.clicked.connect(self.on_mini_clicked)
        self.popup.translate_requested.connect(lambda t, lang: self.start_translation(t, self.popup._anchor, lang))
        self.popup.settings_requested.connect(self.open_settings)
        self.snip.selected.connect(self.on_snip_selected)
        self.grab.finished.connect(self.on_grab_finished)
        self.grab.cancelled.connect(self._end_grab)
        self.grab.released.connect(self.on_grab_released)
        self.grab_ocr_ready.connect(self.on_grab_ocr_ready)
        self.translated.connect(self.on_translated)
        self.capture_done.connect(self.on_capture_done)
        self.restore_bubble.connect(self._restore_bubble)
        self.tray.activated.connect(self._tray_activated)

        # keeps every window of the app on top of everything and heals a hidden bubble
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(700)
        self._tick_timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        self.apply_config()
        self.tray.show()
        self.poller.start()
        self._tick_timer.start()
        if not self.cfg["connections"]:
            self.tray.showMessage("Swift Translate Win",
                                  "Add an API connection first: tray icon \u2192 Settings \u2192 API connections.",
                                  QSystemTrayIcon.MessageIcon.Information, 7000)
        else:
            self.tray.showMessage("Swift Translate Win",
                                  f"Running. Select text anywhere, hold {self.cfg['trigger_name']} to grab screen text, "
                                  f"{self.cfg['snip_name']} = screen snip.",
                                  QSystemTrayIcon.MessageIcon.Information, 5000)

    def apply_config(self) -> None:
        c = self.cfg
        p = self.poller
        p.grab_enabled = bool(c["selection_enabled"])
        p.snip_enabled = bool(c["snip_enabled"])
        p.grab_vk = int(c["trigger_vk"])
        p.snip_vk = int(c["snip_vk"])
        self.bubble.apply_config()
        self.popup.apply_config()
        winutil.set_autostart(bool(c["autostart"]))
        self._build_tray_menu()
        self._tick()

    def _tick(self) -> None:
        c = self.cfg
        overlay = self.grab.isVisible() or self.snip.isVisible() or self._grabbing
        if c["bubble_enabled"] and not self.bubble.isVisible() and not self._dropping and not overlay \
                and not self._settings_open:
            self.bubble.show_if_enabled()
        if not overlay:
            for w, key in ((self.bubble, "bubble_topmost"), (self.mini, "popup_topmost"), (self.popup, "popup_topmost")):
                if w.isVisible():
                    winutil.set_topmost(int(w.winId()), bool(c[key]))
        for w in (self.snip, self.grab):
            if w.isVisible():
                winutil.set_topmost(int(w.winId()), True)

    @property
    def _grabbing(self) -> bool:
        return getattr(self, "_grab_active", False)

    def _build_tray_menu(self) -> None:
        m = QMenu()
        m.addAction("Quick translate\u2026", self.quick_translate)
        m.addAction("Translate clipboard", self.translate_clipboard)
        m.addAction(f"Grab screen text ({self.cfg['trigger_name']})", self.start_grab)
        m.addAction(f"Screen snip OCR ({self.cfg['snip_name']})", self.on_snip_key)
        m.addSeparator()
        act = m.addAction("Pause automatic selection / hotkeys")
        act.setCheckable(True)
        act.setChecked(not self.poller.enabled)
        act.toggled.connect(lambda on: setattr(self.poller, "enabled", not on))
        bub = m.addAction("Show floating bubble")
        bub.setCheckable(True)
        bub.setChecked(bool(self.cfg["bubble_enabled"]))
        bub.toggled.connect(self._toggle_bubble)
        m.addAction("Settings\u2026", self.open_settings)
        m.addSeparator()
        m.addAction("Quit", self.quit)
        self._tray_menu = m
        self.tray.setContextMenu(m)

    def _toggle_bubble(self, on: bool) -> None:
        self.cfg["bubble_enabled"] = bool(on)
        self.cfg.save()
        self.bubble.apply_config()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.quick_translate()

    def quit(self) -> None:
        self.poller.stop()
        self.tray.hide()
        self.app.quit()

    def open_settings(self) -> None:
        if self._settings_open:
            return
        self._settings_open = True
        self.popup.hide()
        try:
            dlg = SettingsDialog(self.cfg, self.poller)
            dlg.setWindowIcon(make_icon())
            if dlg.exec():
                self.apply_config()
        finally:
            self._settings_open = False

    # --------------------------------------------------------- quick actions
    def quick_translate(self) -> None:
        geo = self.bubble.geometry()
        side = self.cfg["bubble_side"]
        if self.cfg["bubble_enabled"] and self.bubble.isVisible():
            if side == "right":
                anchor = QPoint(geo.left() - POPUP_WIDTH - 10, geo.top())
            elif side == "left":
                anchor = QPoint(geo.right() + 10, geo.top())
            elif side == "top":
                anchor = QPoint(geo.left(), geo.bottom() + 10)
            else:
                anchor = QPoint(geo.left(), geo.top() - 360)
        else:
            anchor = QCursor.pos()
        self.popup.show_input(anchor, self.cfg["target_language"])

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
        m.addAction("Grab screen text", self.start_grab)
        m.addAction("Screen snip OCR", self.on_snip_key)
        m.addSeparator()
        for label, side in (("Dock to left edge", "left"), ("Dock to right edge", "right"),
                            ("Dock to top edge", "top"), ("Dock to bottom edge", "bottom")):
            m.addAction(label, lambda s=side: self._dock(s))
        m.addAction("Hide bubble", lambda: self._toggle_bubble(False))
        m.addSeparator()
        m.addAction("Settings\u2026", self.open_settings)
        m.addAction("Quit", self.quit)
        m.exec(pos)

    def _dock(self, side: str) -> None:
        self.cfg["bubble_side"] = side
        self.cfg.save()
        self.bubble.place_docked(animate=True)

    # ---------------------------------------------- automatic selection detection
    def _on_our_window(self, pos: QPoint) -> bool:
        return any(w.isVisible() and w.frameGeometry().contains(pos) for w in (self.bubble, self.mini, self.popup))

    def on_mouse(self, kind: str) -> None:
        if self.grab.isVisible() or self.snip.isVisible() or self._settings_open:
            return
        pos = QCursor.pos()
        now = time.monotonic()
        if kind in ("ldown", "other_down"):
            if self.popup.isVisible() and not self.popup.keep_open and not self.popup.frameGeometry().contains(pos):
                self.popup.hide()
            if self.mini.isVisible() and not self.mini.frameGeometry().contains(pos):
                self.mini.hide()
        if kind == "ldown":
            self._down_pos = pos
            self._down_ibeam = winutil.cursor_is_ibeam()
            dbl = QApplication.doubleClickInterval() / 1000.0
            self._is_dbl = (now - self._last_up_t) < dbl and _dist(pos, self._last_up_pos) < 8
        elif kind == "lup":
            c = self.cfg
            if c["auto_detect"] and self.poller.enabled and not self._grabbing \
                    and not self._on_our_window(self._down_pos) and not self._on_our_window(pos):
                text_cursor = (not c["text_cursor_only"]) or self._down_ibeam or winutil.cursor_is_ibeam()
                if text_cursor:
                    d = _dist(pos, self._down_pos)
                    if d >= c["min_drag_px"] and c["on_drag"]:
                        self.begin_capture("drag", QRect(self._down_pos, pos).normalized(), pos)
                    elif d < c["min_drag_px"] and self._is_dbl and c["on_double_click"]:
                        self.begin_capture("dbl", QRect(pos, pos), pos)
            self._last_up_t = now
            self._last_up_pos = pos

    def on_esc(self) -> None:
        if self.grab.isVisible():
            self.grab.cancel()
        elif self.snip.isVisible():
            self.snip.cancel()
        elif self.popup.isVisible() and not self.popup.keep_open:
            self.popup.hide()
        self.mini.hide()

    # ----------------------------------------------------- drag bubble onto text
    def on_bubble_dropped(self, gp: QPoint) -> None:
        self._dropping = True
        QTimer.singleShot(5000, self._restore_bubble)          # safety net: the bubble always comes back
        QTimer.singleShot(90, lambda: self.begin_capture("drop", QRect(), gp))

    def _restore_bubble(self) -> None:
        self._dropping = False
        if not self._grabbing:
            self.bubble.show_if_enabled()

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
        return {"png": _png(crop), "rect": r, "scale": s * up}

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
            if mode in ("drag", "dbl") and not err:
                return                                  # automatic mode: stay silent when nothing was copyable
            msg = err or "No text found there."
            if mode in ("drop", "snip", "grab"):
                msg += "\n(Tip: hold the grab key or use the screen snip key for text that cannot be selected.)"
            self.popup.show_message(msg, pos)
            return
        if mode == "drop" or self.cfg["auto_translate"]:
            self.start_translation(text, pos)
        else:
            self._pending = (text, pos)
            self.mini.show_at(pos)

    def on_mini_clicked(self) -> None:
        text, pos = self._pending
        if text:
            self.start_translation(text, pos)

    # ------------------------------------------------- grab screen text (hold / tap key)
    def on_grab_key(self, kind: str) -> None:
        if self._settings_open or not self.cfg["selection_enabled"]:
            return
        now = time.monotonic()
        if kind == "down":
            self._grab_down_t = now
            if self.grab.isVisible():
                self._grab_tap_close = True               # tapping again closes a toggled grab screen
                return
            self._grab_tap_close = False
            self.start_grab()
        else:
            if not self.grab.isVisible() and not self._grabbing:
                return
            if self._grab_tap_close:
                self._grab_tap_close = False
                self.grab.cancel()
                return
            if now - self._grab_down_t >= HOLD_SECONDS:   # hold mode: releasing the key ends the grab
                if winutil.key_down(0x01):
                    self._close_after_mouse = True        # mouse still dragging: finish that first
                else:
                    self._end_grab_screen()
            # short tap: grab screen stays open (toggle mode)

    def _end_grab_screen(self) -> None:
        if self.grab.isVisible():
            self.grab.cancel()
        else:
            self._end_grab()

    def on_grab_released(self) -> None:
        if self._close_after_mouse:
            self._close_after_mouse = False
            if self.grab.isVisible() and not self.grab.has_selection():
                self.grab.cancel()

    def start_grab(self) -> None:
        if self._grabbing:
            return
        if not ocr.AVAILABLE:
            self.popup.show_message("Windows OCR is not available in this build, so grabbing screen text is disabled.",
                                    QCursor.pos())
            return
        self._grab_active = True
        self.popup.hide()
        self.mini.hide()
        self.bubble.hide()
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        QTimer.singleShot(80, lambda: self._grab_capture(scr))

    def _grab_capture(self, scr) -> None:
        try:
            geo = scr.geometry()
            img = scr.grabWindow(0).toImage()
            s = img.width() / max(1, geo.width())
            up = 1.5 if img.width() * img.height() <= 2_500_000 else 1.0
            ocr_img = img if up == 1.0 else img.scaled(int(img.width() * up), int(img.height() * up),
                                                       Qt.AspectRatioMode.IgnoreAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation)
            png = _png(ocr_img)
            self.grab.start(scr, img, s)
            threading.Thread(target=self._grab_ocr_worker, args=(png, 1.0 / (s * up), self.cfg["ocr_lang"]),
                             daemon=True).start()
        except Exception:
            log.exception("grab screen failed")
            self._end_grab()

    def _grab_ocr_worker(self, png: bytes, factor: float, lang: str) -> None:
        try:
            self.grab_ocr_ready.emit(ocr.recognize(png, lang), factor, "")
        except Exception as e:
            log.exception("grab ocr failed")
            self.grab_ocr_ready.emit(None, factor, str(e))

    def on_grab_ocr_ready(self, lines, factor: float, err: str) -> None:
        if not self.grab.isVisible():
            return
        if err:
            pos = QCursor.pos()
            self.grab.cancel()
            self.popup.show_message(err, pos)
            return
        self.grab.set_words(lines or [], factor)

    def on_grab_finished(self, text: str, rect: QRect) -> None:
        self._end_grab()
        if self.cfg["snip_copy_text"]:
            winutil.set_clip_text(text)
        self.on_capture_done(text, "ocr", rect.bottomLeft(), "grab", "")

    def _end_grab(self) -> None:
        self._grab_active = False
        self._close_after_mouse = False
        self.bubble.show_if_enabled()

    # ------------------------------------------------------------ screen snip
    def on_snip_key(self) -> None:
        if not ocr.AVAILABLE:
            self.popup.show_message("Windows OCR is not available in this build, so screen snip is disabled.",
                                    QCursor.pos())
            return
        if self.snip.isVisible():
            self.snip.cancel()
            return
        if self.grab.isVisible():
            self.grab.cancel()
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
