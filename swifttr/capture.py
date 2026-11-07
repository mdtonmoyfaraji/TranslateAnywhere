"""Getting selected text out of other applications.

IMPORTANT: this only ever COPIES (Ctrl+C / Ctrl+Insert). It never cuts."""
from __future__ import annotations

import time

from pynput.keyboard import Controller as Keyboard, Key
from pynput.mouse import Button, Controller as Mouse

from . import winutil

mute_fn = None   # set by the controller: tells the input poller to ignore our own synthetic clicks
_kb = Keyboard()
_ms = Mouse()
CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "VirtualConsoleClass"}


def _wait_clip_change(seq: int, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if winutil.clip_seq() != seq:
            return True
        time.sleep(0.02)
    return False


def _wait_modifiers_released(timeout: float = 0.6) -> bool:
    """Shift/Alt/Win physically held would turn our Ctrl+C into another shortcut (e.g. Ctrl+Shift+C)."""
    end = time.time() + timeout
    while time.time() < end:
        if not any(winutil.key_down(v) for v in (0x10, 0x12, 0x5B, 0x5C)):
            return True
        time.sleep(0.02)
    return False


def copy_selection(restore: bool = False) -> str:
    """Copy the current selection of the foreground app and return it ('' if nothing was copied)."""
    if not _wait_modifiers_released():
        return ""
    old = winutil.get_clip_text() if restore else None
    # Consoles treat Ctrl+C as 'interrupt' when nothing is selected, so use Ctrl+Insert there.
    use_insert = winutil.foreground_class() in CONSOLE_CLASSES
    seq = winutil.clip_seq()
    with _kb.pressed(Key.ctrl):
        key = Key.insert if use_insert else "c"
        _kb.press(key)
        _kb.release(key)
    if not _wait_clip_change(seq, 0.45):
        return ""
    time.sleep(0.03)
    text = winutil.get_clip_text()
    if restore and old is not None:
        winutil.set_clip_text(old)
    return text


def click_select(clicks: int) -> None:
    """Double/triple click at the current cursor position to select a word/paragraph."""
    if mute_fn:
        mute_fn(0.9)
    _ms.click(Button.left, clicks)
