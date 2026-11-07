"""Polls the physical mouse/keyboard state with GetAsyncKeyState.

No global hooks are used. Windows silently removes low-level hooks whenever a callback is slow, which made
the old version work "sometimes". Polling cannot be removed by Windows and works the same over every app."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from . import winutil

log = logging.getLogger(__name__)

# order matters: specific left/right modifier keys are checked before everything else
_CAPTURE_ORDER = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5] + [
    v for v in range(0x08, 0xFF)
    if v not in (0x10, 0x11, 0x12, 0x1B, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5) and not (0x01 <= v <= 0x07)
]


class Poller(QObject):
    mouse_event = Signal(str)             # "ldown" | "lup" | "other_down"
    grab_key = Signal(str)                # "down" | "up"
    snip_pressed = Signal()
    esc_pressed = Signal()
    key_captured = Signal(int, str)       # for the settings dialog

    def __init__(self) -> None:
        super().__init__()
        self.enabled = True
        self.grab_enabled = True
        self.snip_enabled = True
        self.grab_vk = 0
        self.snip_vk = 0
        self.mute_until = 0.0
        self._capturing = False
        self._l = self._r = self._m = self._g = self._s = self._esc = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def mute(self, seconds: float) -> None:
        """Ignore mouse buttons for a moment (used while the app injects its own clicks)."""
        self.mute_until = max(self.mute_until, time.monotonic() + seconds)

    def capture_next_key(self) -> None:
        self._capturing = True

    def cancel_capture(self) -> None:
        self._capturing = False

    def _tick(self) -> None:
        try:
            self._poll()
        except Exception:
            log.exception("poll")

    def _poll(self) -> None:
        down = winutil.key_down
        muted = time.monotonic() < self.mute_until

        l = down(0x01)
        if l != self._l:
            self._l = l
            if not muted:
                self.mouse_event.emit("ldown" if l else "lup")
        r, m = down(0x02), down(0x04)
        if (r and not self._r) or (m and not self._m):
            if not muted:
                self.mouse_event.emit("other_down")
        self._r, self._m = r, m

        if self._capturing:
            for vk in _CAPTURE_ORDER:
                if down(vk):
                    self._capturing = False
                    self.key_captured.emit(vk, winutil.vk_name(vk))
                    break
            return

        esc = down(0x1B)
        if esc and not self._esc:
            self.esc_pressed.emit()
        self._esc = esc

        g = bool(self.enabled and self.grab_enabled and self.grab_vk and down(self.grab_vk))
        if g != self._g:
            self._g = g
            self.grab_key.emit("down" if g else "up")

        s = bool(self.enabled and self.snip_enabled and self.snip_vk and down(self.snip_vk))
        if s and not self._s:
            self.snip_pressed.emit()
        self._s = s
