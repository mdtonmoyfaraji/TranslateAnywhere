"""Windows built-in OCR (Windows.Media.Ocr) through the pywinrt packages."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field

AVAILABLE = False
IMPORT_ERROR = ""
try:
    from winrt.windows.foundation import collections as _wfc  # noqa: F401
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    AVAILABLE = True
except Exception as e:  # pragma: no cover
    IMPORT_ERROR = str(e)


class OcrError(Exception):
    pass


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class Line:
    text: str
    words: list = field(default_factory=list)

    @property
    def rect(self):
        x0 = min(w.x for w in self.words)
        y0 = min(w.y for w in self.words)
        x1 = max(w.x + w.w for w in self.words)
        y1 = max(w.y + w.h for w in self.words)
        return x0, y0, x1, y1


async def _recognize(png: bytes, lang: str):
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(bytearray(png))
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    if lang.strip():
        engine = OcrEngine.try_create_from_language(Language(lang.strip()))
    else:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError(
            "No Windows OCR language available. Install an OCR language pack: "
            "Settings > Time & language > Language & region > add a language (with 'Optical character recognition')."
        )
    result = await engine.recognize_async(bitmap)
    lines = []
    for ln in result.lines:
        words = []
        for w in ln.words:
            r = w.bounding_rect
            words.append(Word(w.text, r.x, r.y, r.width, r.height))
        if words:
            lines.append(Line(ln.text, words))
    return lines


def recognize(png: bytes, lang: str = "") -> list:
    if not AVAILABLE:
        raise OcrError("Windows OCR is not available in this build: " + IMPORT_ERROR)
    return asyncio.run(_recognize(png, lang))


def _dist(px, py, x, y, w, h) -> float:
    dx = max(x - px, 0, px - (x + w))
    dy = max(y - py, 0, py - (y + h))
    return math.hypot(dx, dy)


def pick_text(lines: list, px: float, py: float, scope: str = "line") -> str:
    """Return the word / line / paragraph closest to point (px, py) in image pixels."""
    best = None
    for li, ln in enumerate(lines):
        for w in ln.words:
            d = _dist(px, py, w.x, w.y, w.w, w.h)
            if best is None or d < best[0]:
                best = (d, li, w)
    if best is None:
        return ""
    d, li, word = best
    if d > max(60.0, word.h * 2.0):
        return ""
    if scope == "word":
        return word.text.strip(" \t.,;:!?\"'()[]{}")
    if scope == "line":
        return lines[li].text.strip()
    # paragraph: grow up/down while the vertical gap is small and the lines overlap horizontally
    order = sorted(range(len(lines)), key=lambda i: lines[i].rect[1])
    pos = order.index(li)

    def near(a, b) -> bool:
        ax0, ay0, ax1, ay1 = lines[a].rect
        bx0, by0, bx1, by1 = lines[b].rect
        gap = max(by0 - ay1, ay0 - by1)
        height = max(ay1 - ay0, by1 - by0)
        return gap < height * 0.9 and min(ax1, bx1) > max(ax0, bx0)

    lo = hi = pos
    while lo > 0 and near(order[lo], order[lo - 1]):
        lo -= 1
    while hi < len(order) - 1 and near(order[hi], order[hi + 1]):
        hi += 1
    return " ".join(lines[i].text.strip() for i in order[lo:hi + 1])
