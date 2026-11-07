from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from pathlib import Path

APP_NAME = "SwiftTranslateWin"
log = logging.getLogger(__name__)


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_connection(**kw) -> dict:
    c = {
        "id": uuid.uuid4().hex[:8],
        "name": "New connection",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": "",
        "timeout": 20,
        "enabled": True,
    }
    c.update(kw)
    return c


DEFAULTS = {
    "cfg_version": 2,
    # translation
    "target_language": "English",
    "second_language": "English",   # used when the text is already in the target language
    # floating bubble
    "bubble_enabled": True,
    "bubble_side": "right",         # left | right | top | bottom
    "bubble_y": 0.45,               # 0..1 position along the chosen edge
    "bubble_screen": "",
    "bubble_size": 56,
    "bubble_opacity": 85,           # idle opacity in %
    "bubble_topmost": True,         # keep the dock bubble above everything (re-asserted every 0.7 s)
    "popup_topmost": True,          # same for the small trigger bubble and the translation box
    "autostart": False,
    "popup_font_size": 11,
    "drop_method": "auto",          # auto | ocr | click
    "drop_scope": "line",           # word | line | paragraph
    # what happens after text was grabbed (any method)
    "auto_translate": True,         # True: translation box opens by itself; False: small bubble first
    # automatic detection of text selected anywhere (no key needed)
    "auto_detect": True,
    "text_cursor_only": True,       # only when the pointer is a text cursor (I-beam)
    "on_double_click": True,
    "on_drag": True,
    "min_drag_px": 12,
    "ocr_fallback": False,          # if nothing could be copied, OCR the dragged area
    "restore_clipboard": False,
    # grab screen text: hold (or tap) a key, then select text on the frozen screen
    "selection_enabled": True,
    "trigger_vk": 0x77,             # F8
    "trigger_name": "F8",
    # screen snip (OCR)
    "snip_enabled": True,
    "snip_vk": 0x78,                # F9
    "snip_name": "F9",
    "snip_copy_text": True,         # copy recognised text (snip + grab) to the clipboard
    "ocr_lang": "",
    # api
    "connections": [],
    "start_from_last_working": True,
    "attempts_per_connection": 1,
    "temperature": "",
    "last_ok_id": "",
}


class Config:
    def __init__(self) -> None:
        self.path = config_dir() / "config.json"
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for k in DEFAULTS:
                if k in raw:
                    self.data[k] = raw[k]
            if int(raw.get("cfg_version", 1)) < 2:      # settings changed meaning in v2
                for k in ("auto_translate", "ocr_fallback", "selection_enabled", "trigger_vk",
                          "trigger_name", "snip_copy_text"):
                    self.data[k] = DEFAULTS[k]
                self.data["cfg_version"] = 2
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("could not read config, using defaults")
        base = new_connection()
        fixed = []
        for c in self.data.get("connections", []):
            if isinstance(c, dict):
                m = dict(base)
                m.update(c)
                if not m.get("id"):
                    m["id"] = uuid.uuid4().hex[:8]
                fixed.append(m)
        self.data["connections"] = fixed

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.exception("could not save config")

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v) -> None:
        self.data[k] = v

    def get(self, k, default=None):
        return self.data.get(k, default)
