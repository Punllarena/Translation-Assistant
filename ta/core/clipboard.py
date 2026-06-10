from __future__ import annotations

import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication

_JP_RE = re.compile(r"[　-鿿＀-￯゠-ヿ぀-ゟ]")


class ClipboardMonitor(QObject):
    text_received = Signal(str)

    def __init__(self, max_chars: int = 500, parent=None):
        super().__init__(parent)
        self._max_chars = max_chars
        self._enabled = True
        self._last = ""
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_change)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def _on_change(self) -> None:
        if not self._enabled:
            return
        text = QApplication.clipboard().text(QClipboard.Mode.Clipboard)
        if not text or text == self._last:
            return
        if len(text) < 2 or len(text) > self._max_chars:
            return
        if not _JP_RE.search(text):
            return
        self._last = text
        self.text_received.emit(text)
