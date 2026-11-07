from __future__ import annotations

import ctypes
import logging
import sys
import time
import winreg
from ctypes import wintypes

import win32clipboard
import win32con

from .config import APP_NAME

log = logging.getLogger(__name__)
user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetKeyNameTextW.argtypes = [ctypes.c_long, wintypes.LPWSTR, ctypes.c_int]

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE


class _CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT)]


user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
_IBEAM = None
_HWND_TOPMOST = wintypes.HWND(-1)
_HWND_NOTOPMOST = wintypes.HWND(-2)
_EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0x90}


def key_down(vk: int) -> bool:
    """Physical key / mouse-button state right now (works system-wide, no hooks needed)."""
    return (user32.GetAsyncKeyState(vk) & 0x8000) != 0


def set_topmost(hwnd: int, on: bool = True) -> None:
    """Put a window at the very top of the topmost band without activating it."""
    try:
        # NOSIZE | NOMOVE | NOACTIVATE | NOOWNERZORDER | ASYNCWINDOWPOS
        user32.SetWindowPos(hwnd, _HWND_TOPMOST if on else _HWND_NOTOPMOST, 0, 0, 0, 0, 0x4213)
    except Exception:
        log.exception("SetWindowPos failed")


def cursor_is_ibeam() -> bool:
    """True if the mouse pointer currently is a text cursor (I-beam)."""
    global _IBEAM
    try:
        if _IBEAM is None:
            _IBEAM = user32.LoadCursorW(None, 32513)
        ci = _CURSORINFO()
        ci.cbSize = ctypes.sizeof(_CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(ci)):
            return True
        return ci.hCursor == _IBEAM
    except Exception:
        return True


MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14}
_NAMES = {
    0xA0: "Left Shift", 0xA1: "Right Shift", 0xA2: "Left Ctrl", 0xA3: "Right Ctrl",
    0xA4: "Left Alt", 0xA5: "Right Alt", 0x14: "Caps Lock", 0x5B: "Left Win", 0x5C: "Right Win",
}


def is_modifier(vk: int) -> bool:
    return vk in MODIFIER_VKS


def vk_name(vk: int, scan: int = 0, extended: bool | None = None) -> str:
    if extended is None:
        extended = vk in _EXTENDED_VKS
    if vk in _NAMES:
        return _NAMES[vk]
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if not scan:
        scan = user32.MapVirtualKeyW(vk, 0)
    lparam = (scan << 16) | ((1 if extended else 0) << 24)
    buf = ctypes.create_unicode_buffer(64)
    if user32.GetKeyNameTextW(lparam, buf, 64):
        return buf.value
    return f"Key 0x{vk:02X}"


def foreground_class() -> str:
    try:
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def clip_seq() -> int:
    return int(user32.GetClipboardSequenceNumber())


def get_clip_text() -> str:
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or ""
                return ""
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.03)
    return ""


def set_clip_text(text: str) -> bool:
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.03)
    return False


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enabled: bool) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    py = sys.executable.replace("python.exe", "pythonw.exe")
                    cmd = f'"{py}" "{sys.argv[0]}"'
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        log.exception("autostart change failed")
