from __future__ import annotations

import copy
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import config as C
from . import ocr, translator
from .languages import LANGUAGES

PRESETS = [
    ("Custom / other", "", ""),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    ("Groq", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
    ("Google Gemini (OpenAI-compatible)", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("Ollama (local)", "http://localhost:11434/v1", "llama3.2"),
    ("LM Studio (local)", "http://localhost:1234/v1", "local-model"),
]


class SettingsDialog(QDialog):
    key_got = Signal(int, str)
    test_msg = Signal(str)

    def __init__(self, cfg, hooks, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Swift Translate Win \u2014 Settings")
        self.resize(780, 600)
        self.cfg = cfg
        self.hooks = hooks
        self.conns = copy.deepcopy(cfg["connections"])
        self._row = -1
        self._loading = False
        self._key_target = None
        self._keys = {
            "trigger": (cfg["trigger_vk"], cfg["trigger_name"]),
            "snip": (cfg["snip_vk"], cfg["snip_name"]),
        }
        self.key_got.connect(self._on_key)
        self.test_msg.connect(lambda m: self.log.appendPlainText(m))

        tabs = QTabWidget()
        tabs.addTab(self._tab_general(), "General")
        tabs.addTab(self._tab_selection(), "Select anywhere")
        tabs.addTab(self._tab_api(), "API connections")
        tabs.addTab(self._tab_advanced(), "Advanced")
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(box)

        self._refresh_list(0 if self.conns else -1)

    # ------------------------------------------------------------------ tabs
    @staticmethod
    def _lang_combo(value: str) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.addItems(LANGUAGES)
        cb.setCurrentText(value)
        return cb

    def _tab_general(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        c = self.cfg
        self.c_target = self._lang_combo(c["target_language"])
        self.c_second = self._lang_combo(c["second_language"])
        f.addRow("Translate into:", self.c_target)
        f.addRow("If text is already in that language, translate into:", self.c_second)

        self.c_bubble = QCheckBox("Show the floating bubble")
        self.c_bubble.setChecked(c["bubble_enabled"])
        self.c_side = QComboBox()
        self.c_side.addItems(["Left", "Right"])
        self.c_side.setCurrentIndex(0 if c["bubble_side"] == "left" else 1)
        self.c_size = QSpinBox()
        self.c_size.setRange(36, 110)
        self.c_size.setValue(int(c["bubble_size"]))
        self.c_opacity = QSlider(Qt.Orientation.Horizontal)
        self.c_opacity.setRange(25, 100)
        self.c_opacity.setValue(int(c["bubble_opacity"]))
        f.addRow(self.c_bubble)
        f.addRow("Bubble side:", self.c_side)
        f.addRow("Bubble size (px):", self.c_size)
        f.addRow("Bubble opacity when idle:", self.c_opacity)
        f.addRow(QLabel("Tip: drag the bubble onto text and release to translate it. "
                        "Hold Shift while dragging to move the bubble. Click it for a quick-translate box."))

        self.c_method = QComboBox()
        self.c_method.addItem("Auto (OCR, click-select if OCR is unavailable)", "auto")
        self.c_method.addItem("OCR only (never clicks anything)", "ocr")
        self.c_method.addItem("Click-select only (double/triple click + copy)", "click")
        self.c_method.setCurrentIndex(max(0, self.c_method.findData(c["drop_method"])))
        self.c_scope = QComboBox()
        for label, v in (("Word", "word"), ("Line", "line"), ("Paragraph", "paragraph")):
            self.c_scope.addItem(label, v)
        self.c_scope.setCurrentIndex(max(0, self.c_scope.findData(c["drop_scope"])))
        f.addRow("When dropping the bubble on text:", self.c_method)
        f.addRow("Amount of text to take:", self.c_scope)

        self.c_font = QSpinBox()
        self.c_font.setRange(8, 24)
        self.c_font.setValue(int(c["popup_font_size"]))
        self.c_auto = QCheckBox("Start with Windows")
        self.c_auto.setChecked(c["autostart"])
        f.addRow("Popup font size:", self.c_font)
        f.addRow(self.c_auto)
        return w

    def _key_row(self, which: str):
        lab = QLabel(self._keys[which][1])
        lab.setStyleSheet("font-weight:bold;")
        btn = QPushButton("Change\u2026")
        btn.clicked.connect(lambda: self._record(which))
        row = QHBoxLayout()
        row.addWidget(lab)
        row.addWidget(btn)
        row.addStretch(1)
        setattr(self, f"lbl_{which}", lab)
        setattr(self, f"btn_{which}", btn)
        return row

    def _tab_selection(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        c = self.cfg
        self.s_enable = QCheckBox("Enable \u201cselect text anywhere\u201d (works over every other app)")
        self.s_enable.setChecked(c["selection_enabled"])
        f.addRow(self.s_enable)
        f.addRow("Hold this key while selecting:", self._key_row("trigger"))
        self.s_suppress = QCheckBox("Hide that key from other apps (ignored for Ctrl/Shift/Alt/Win)")
        self.s_suppress.setChecked(c["suppress_trigger"])
        self.s_dbl = QCheckBox("Double-click a word")
        self.s_dbl.setChecked(c["on_double_click"])
        self.s_drag = QCheckBox("Drag to select")
        self.s_drag.setChecked(c["on_drag"])
        self.s_min = QSpinBox()
        self.s_min.setRange(4, 80)
        self.s_min.setValue(int(c["min_drag_px"]))
        self.s_ocr = QCheckBox("If the app has nothing to copy, read the text from the screen with OCR")
        self.s_ocr.setChecked(c["ocr_fallback"])
        self.s_restore = QCheckBox("Put the previous clipboard text back afterwards (otherwise the selected text stays copied)")
        self.s_restore.setChecked(c["restore_clipboard"])
        self.s_auto = QCheckBox("Translate immediately (skip the small bubble)")
        self.s_auto.setChecked(c["auto_translate"])
        for wd in (self.s_suppress, self.s_dbl, self.s_drag):
            f.addRow(wd)
        f.addRow("Minimum drag distance (px):", self.s_min)
        for wd in (self.s_ocr, self.s_restore, self.s_auto):
            f.addRow(wd)
        f.addRow(QLabel("Selecting only COPIES the text (Ctrl+C). It never cuts, so nothing is removed from the other app."))

        f.addRow(QLabel(""))
        self.n_enable = QCheckBox("Enable screen snip (draw a rectangle, OCR it, translate)")
        self.n_enable.setChecked(c["snip_enabled"])
        f.addRow(self.n_enable)
        f.addRow("Snip key (press once):", self._key_row("snip"))
        self.n_copy = QCheckBox("Copy the recognised text to the clipboard")
        self.n_copy.setChecked(c["snip_copy_text"])
        f.addRow(self.n_copy)
        self.n_lang = QLineEdit(c["ocr_lang"])
        self.n_lang.setPlaceholderText("empty = your Windows languages, or a tag like en-US, de-DE, ja")
        f.addRow("OCR language:", self.n_lang)
        status = "available" if ocr.AVAILABLE else "NOT available in this build (" + ocr.IMPORT_ERROR[:80] + ")"
        f.addRow(QLabel("Windows OCR: " + status))
        return w

    def _tab_api(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)
        left = QVBoxLayout()
        self.lst = QListWidget()
        self.lst.currentRowChanged.connect(self._on_row)
        left.addWidget(QLabel("Tried top to bottom; if one fails the next is used, and so on:"))
        left.addWidget(self.lst, 1)
        row1 = QHBoxLayout()
        for text, fn in (("Add", self._add), ("Remove", self._remove), ("\u2191", lambda: self._move(-1)),
                         ("\u2193", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row1.addWidget(b)
        left.addLayout(row1)
        row2 = QHBoxLayout()
        b1 = QPushButton("Test selected")
        b1.clicked.connect(self._test_current)
        b2 = QPushButton("Test all")
        b2.clicked.connect(self._test_all)
        row2.addWidget(b1)
        row2.addWidget(b2)
        left.addLayout(row2)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        self.form = QWidget()
        f = QFormLayout(self.form)
        self.a_enabled = QCheckBox("Enabled")
        self.a_name = QLineEdit()
        self.a_preset = QComboBox()
        for label, _u, _m in PRESETS:
            self.a_preset.addItem(label)
        self.a_preset.activated.connect(self._apply_preset)
        self.a_url = QLineEdit()
        self.a_url.setPlaceholderText("https://api.openai.com/v1  (/chat/completions is added automatically)")
        self.a_model = QLineEdit()
        self.a_key = QLineEdit()
        self.a_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.a_show = QCheckBox("Show key")
        self.a_show.toggled.connect(lambda on: self.a_key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.a_timeout = QSpinBox()
        self.a_timeout.setRange(3, 180)
        f.addRow(self.a_enabled)
        f.addRow("Name:", self.a_name)
        f.addRow("Preset:", self.a_preset)
        f.addRow("Base URL:", self.a_url)
        f.addRow("Model:", self.a_model)
        f.addRow("API key:", self.a_key)
        f.addRow("", self.a_show)
        f.addRow("Timeout (s):", self.a_timeout)
        self.a_name.textChanged.connect(self._name_changed)
        right.addWidget(self.form)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Test results appear here")
        right.addWidget(self.log, 1)
        root.addLayout(right, 2)
        return w

    def _tab_advanced(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        c = self.cfg
        self.v_last = QCheckBox("Start with the connection that worked last (then cycle through the rest)")
        self.v_last.setChecked(c["start_from_last_working"])
        self.v_att = QSpinBox()
        self.v_att.setRange(1, 5)
        self.v_att.setValue(int(c["attempts_per_connection"]))
        self.v_temp = QLineEdit(str(c["temperature"]))
        self.v_temp.setPlaceholderText("empty = server default")
        f.addRow(self.v_last)
        f.addRow("Attempts per connection:", self.v_att)
        f.addRow("Temperature:", self.v_temp)
        f.addRow(QLabel("API keys are stored in plain text in %APPDATA%\\SwiftTranslateWin\\config.json."))
        return w

    # ------------------------------------------------------------ key capture
    def _record(self, which: str) -> None:
        self._key_target = which
        getattr(self, f"lbl_{which}").setText("Press a key\u2026")
        self.hooks.key_captured.connect(self._relay_key)
        self.hooks.capture_next_key()

    def _relay_key(self, vk: int, name: str) -> None:
        self.key_got.emit(vk, name)

    def _on_key(self, vk: int, name: str) -> None:
        try:
            self.hooks.key_captured.disconnect(self._relay_key)
        except Exception:
            pass
        which = self._key_target
        self._key_target = None
        if not which:
            return
        other = self._keys["snip" if which == "trigger" else "trigger"]
        if vk == other[0]:
            QMessageBox.warning(self, "Key in use", "That key is already used for the other action.")
            name_old = self._keys[which][1]
            getattr(self, f"lbl_{which}").setText(name_old)
            return
        self._keys[which] = (vk, name)
        getattr(self, f"lbl_{which}").setText(name)

    # ------------------------------------------------------ connections list
    def _label(self, i: int) -> str:
        c = self.conns[i]
        mark = "\u25cf" if c.get("enabled", True) else "\u25cb"
        return f"{mark} {i + 1}. {c.get('name', '')}"

    def _refresh_list(self, select: int) -> None:
        self.lst.blockSignals(True)
        self.lst.clear()
        for i in range(len(self.conns)):
            self.lst.addItem(self._label(i))
        self.lst.blockSignals(False)
        self._row = -1
        if self.conns:
            select = max(0, min(select, len(self.conns) - 1))
            self.lst.setCurrentRow(select)
        self._on_row(self.lst.currentRow())

    def _on_row(self, row: int) -> None:
        self._commit()
        self._row = row
        self._loading = True
        ok = 0 <= row < len(self.conns)
        self.form.setEnabled(ok)
        c = self.conns[row] if ok else {}
        self.a_enabled.setChecked(bool(c.get("enabled", True)))
        self.a_name.setText(c.get("name", ""))
        self.a_url.setText(c.get("base_url", ""))
        self.a_model.setText(c.get("model", ""))
        self.a_key.setText(c.get("api_key", ""))
        self.a_timeout.setValue(int(c.get("timeout", 20) or 20))
        self.a_preset.setCurrentIndex(0)
        self._loading = False

    def _commit(self) -> None:
        if self._loading or not (0 <= self._row < len(self.conns)):
            return
        c = self.conns[self._row]
        c["enabled"] = self.a_enabled.isChecked()
        c["name"] = self.a_name.text().strip() or "Unnamed"
        c["base_url"] = self.a_url.text().strip()
        c["model"] = self.a_model.text().strip()
        c["api_key"] = self.a_key.text().strip()
        c["timeout"] = self.a_timeout.value()
        item = self.lst.item(self._row)
        if item:
            item.setText(self._label(self._row))

    def _name_changed(self, _t: str) -> None:
        self._commit()

    def _apply_preset(self, idx: int) -> None:
        _label, url, model = PRESETS[idx]
        if url:
            self.a_url.setText(url)
            self.a_model.setText(model)
            if self.a_name.text().strip() in ("", "New connection"):
                self.a_name.setText(_label)

    def _add(self) -> None:
        self._commit()
        self.conns.append(C.new_connection())
        self._refresh_list(len(self.conns) - 1)

    def _remove(self) -> None:
        if not (0 <= self._row < len(self.conns)):
            return
        del self.conns[self._row]
        self._row = -1
        self._refresh_list(0)

    def _move(self, d: int) -> None:
        self._commit()
        i, j = self._row, self._row + d
        if 0 <= i < len(self.conns) and 0 <= j < len(self.conns):
            self.conns[i], self.conns[j] = self.conns[j], self.conns[i]
            self._row = -1
            self._refresh_list(j)

    # ------------------------------------------------------------------ tests
    def _test_current(self) -> None:
        self._commit()
        if not (0 <= self._row < len(self.conns)):
            return
        conn = dict(self.conns[self._row])
        self.log.appendPlainText(f"Testing {conn['name']} \u2026")
        threading.Thread(target=self._run_tests, args=([conn],), daemon=True).start()

    def _test_all(self) -> None:
        self._commit()
        conns = [dict(c) for c in self.conns]
        if not conns:
            return
        self.log.appendPlainText(f"Testing {len(conns)} connection(s) \u2026")
        threading.Thread(target=self._run_tests, args=(conns,), daemon=True).start()

    def _run_tests(self, conns: list) -> None:
        for c in conns:
            ok, msg = translator.test_connection(c)
            mark = "\u2714" if ok else "\u2718"
            self.test_msg.emit(f"[{c['name']}] {mark} {msg}")

    # ------------------------------------------------------------------- save
    def _save(self) -> None:
        self._commit()
        if self._key_target:
            self.hooks.cancel_capture()
        c = self.cfg
        c["target_language"] = self.c_target.currentText().strip() or "English"
        c["second_language"] = self.c_second.currentText().strip() or "English"
        c["bubble_enabled"] = self.c_bubble.isChecked()
        c["bubble_side"] = "left" if self.c_side.currentIndex() == 0 else "right"
        c["bubble_size"] = self.c_size.value()
        c["bubble_opacity"] = self.c_opacity.value()
        c["drop_method"] = self.c_method.currentData()
        c["drop_scope"] = self.c_scope.currentData()
        c["popup_font_size"] = self.c_font.value()
        c["autostart"] = self.c_auto.isChecked()

        c["selection_enabled"] = self.s_enable.isChecked()
        c["trigger_vk"], c["trigger_name"] = self._keys["trigger"]
        c["suppress_trigger"] = self.s_suppress.isChecked()
        c["on_double_click"] = self.s_dbl.isChecked()
        c["on_drag"] = self.s_drag.isChecked()
        c["min_drag_px"] = self.s_min.value()
        c["ocr_fallback"] = self.s_ocr.isChecked()
        c["restore_clipboard"] = self.s_restore.isChecked()
        c["auto_translate"] = self.s_auto.isChecked()
        c["snip_enabled"] = self.n_enable.isChecked()
        c["snip_vk"], c["snip_name"] = self._keys["snip"]
        c["snip_copy_text"] = self.n_copy.isChecked()
        c["ocr_lang"] = self.n_lang.text().strip()

        c["connections"] = self.conns
        c["start_from_last_working"] = self.v_last.isChecked()
        c["attempts_per_connection"] = self.v_att.value()
        c["temperature"] = self.v_temp.text().strip()
        c.save()
        self.accept()

    def reject(self) -> None:
        self.hooks.cancel_capture()
        try:
            self.hooks.key_captured.disconnect(self._relay_key)
        except Exception:
            pass
        super().reject()
