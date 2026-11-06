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
    # translation
    "target_language": "English",
    "second_language": "English",   # used when the text is already in the target language
    # floating bubble
    "bubble_enabled": True,
    "bubble_side": "right",         # left | right
    "bubble_y": 0.45,               # 0..1 position along the edge
    "bubble_screen": "",
    "bubble_size": 56,
    "bubble_opacity": 85,           # idle opacity in %
    "autostart": False,
    "popup_font_size": 11,
    "drop_method": "auto",          # auto | ocr | click
    "drop_scope": "line",           # word | line | paragraph
    # select-anywhere with a held key
    "selection_enabled": True,
    "trigger_vk": 0x77,             # F8
    "trigger_name": "F8",
    "suppress_trigger": True,
    "on_double_click": True,
    "on_drag": True,
    "min_drag_px": 12,
    "ocr_fallback": True,
    "restore_clipboard": False,
    "auto_translate": False,
    # screen snip (OCR)
    "snip_enabled": True,
    "snip_vk": 0x78,                # F9
    "snip_name": "F9",
    "snip_copy_text": True,
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
