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

MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14}
_NAMES = {
    0xA0: "Left Shift", 0xA1: "Right Shift", 0xA2: "Left Ctrl", 0xA3: "Right Ctrl",
    0xA4: "Left Alt", 0xA5: "Right Alt", 0x14: "Caps Lock", 0x5B: "Left Win", 0x5C: "Right Win",
}


def is_modifier(vk: int) -> bool:
    return vk in MODIFIER_VKS


def vk_name(vk: int, scan: int = 0, extended: bool = False) -> str:
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
