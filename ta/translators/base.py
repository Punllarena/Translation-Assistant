from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from ta.config.languages import Language


class BaseTranslator(QObject):
    translation_ready = Signal(str)
    translation_error = Signal(str)
    translation_started = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self._lock = threading.Lock()
        self._pending: tuple[str, Language, Language] | None = None
        self._running = False
        self._cancel = False

    def translate(self, text: str, src: Language, dst: Language) -> None:
        """Queue a translation request. Replaces any pending request."""
        with self._lock:
            self._pending = (text, src, dst)
            if self._running:
                return
            self._running = True
            self._cancel = False

        t = threading.Thread(target=self._worker, daemon=True)
        t.start()

    def halt(self) -> None:
        with self._lock:
            self._cancel = True
            self._pending = None

    def can_translate(self, src: Language, dst: Language) -> bool:
        return True

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        """Perform the actual translation. Raises on failure."""
        raise NotImplementedError

    def _worker(self) -> None:
        while True:
            with self._lock:
                if self._cancel or self._pending is None:
                    self._running = False
                    return
                text, src, dst = self._pending
                self._pending = None

            self.translation_started.emit()
            try:
                result = self._do_translate(text, src, dst)
                if not self._cancel:
                    self.translation_ready.emit(result)
            except Exception as exc:
                if not self._cancel:
                    self.translation_error.emit(str(exc))

            with self._lock:
                if self._pending is None:
                    self._running = False
                    return
