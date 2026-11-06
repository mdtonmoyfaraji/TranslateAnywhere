"""Global keyboard / mouse observation (Windows low-level hooks through pynput).

Only the *trigger* and *snip* keys are ever swallowed (and only when they are not modifier keys);
everything else passes through untouched. Mouse events are never blocked."""
from __future__ import annotations

import logging

from pynput import keyboard, mouse
from PySide6.QtCore import QObject, Signal

from . import winutil

log = logging.getLogger(__name__)

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
VK_ESCAPE = 0x1B


class InputHooks(QObject):
    mouse_event = Signal(str, bool)       # kind ("ldown" | "lup" | "other_down"), trigger key held
    snip_pressed = Signal()
    esc_pressed = Signal()
    key_captured = Signal(int, str)       # used by the settings dialog to record a key

    def __init__(self) -> None:
        super().__init__()
        self.enabled = True
        self.selection_enabled = True
        self.snip_enabled = True
        self.suppress_trigger = True
        self.trigger_vk = 0
        self.snip_vk = 0
        self._trigger_down = False
        self._snip_down = False
        self._capturing = False
        self._kl = None
        self._ml = None

    # ---- lifecycle
    def start(self) -> None:
        self._kl = keyboard.Listener(win32_event_filter=self._kb_filter)
        self._ml = mouse.Listener(win32_event_filter=self._ms_filter)
        self._kl.start()
        self._ml.start()

    def stop(self) -> None:
        for l in (self._kl, self._ml):
            try:
                if l:
                    l.stop()
            except Exception:
                pass

    def capture_next_key(self) -> None:
        self._capturing = True

    def cancel_capture(self) -> None:
        self._capturing = False

    @property
    def trigger_held(self) -> bool:
        return bool(self._trigger_down and self.enabled and self.selection_enabled)

    # ---- hook callbacks (run on pynput's threads)
    def _kb_filter(self, msg, data):
        suppress = False
        try:
            if data.flags & 0x10:          # injected by us (Ctrl+C etc.)
                return False
            vk = data.vkCode
            down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
            up = msg in (WM_KEYUP, WM_SYSKEYUP)
            if self._capturing and down:
                self._capturing = False
                self.key_captured.emit(vk, winutil.vk_name(vk, data.scanCode, bool(data.flags & 1)))
                suppress = True
            elif self.trigger_vk and vk == self.trigger_vk:
                if down:
                    self._trigger_down = True
                elif up:
                    self._trigger_down = False
                suppress = (self.suppress_trigger and self.selection_enabled and self.enabled
                            and not winutil.is_modifier(vk))
            elif self.snip_vk and vk == self.snip_vk:
                if down:
                    if not self._snip_down and self.snip_enabled and self.enabled:
                        self.snip_pressed.emit()
                    self._snip_down = True
                elif up:
                    self._snip_down = False
                suppress = self.snip_enabled and self.enabled and not winutil.is_modifier(vk)
            elif vk == VK_ESCAPE and down:
                self.esc_pressed.emit()
        except Exception:
            log.exception("keyboard hook")
        if suppress:
            self._kl.suppress_event()      # raises internally; must stay outside try/except
        return False

    def _ms_filter(self, msg, data):
        try:
            if data.flags & 0x01:          # injected
                return False
            if msg == 0x201:
                self.mouse_event.emit("ldown", self.trigger_held)
            elif msg == 0x202:
                self.mouse_event.emit("lup", self.trigger_held)
            elif msg in (0x204, 0x207, 0x20B):
                self.mouse_event.emit("other_down", self.trigger_held)
        except Exception:
            log.exception("mouse hook")
        return False
