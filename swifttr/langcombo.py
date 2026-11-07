from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from .languages import LANGUAGES


def make_lang_combo(value: str = "English") -> QComboBox:
    """Editable, searchable language dropdown (type any part of a name)."""
    cb = QComboBox()
    cb.setEditable(True)
    cb.addItems(LANGUAGES)
    cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    comp = QCompleter(LANGUAGES, cb)
    comp.setFilterMode(Qt.MatchFlag.MatchContains)
    comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    cb.setCompleter(comp)
    cb.setCurrentText(value)
    return cb
