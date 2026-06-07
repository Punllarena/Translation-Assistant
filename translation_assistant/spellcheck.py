"""
Real-time spell-check highlighter for the translated-text QTextEdit.

Uses pyenchant when available; degrades silently to a no-op if enchant
is absent or no English dictionary is installed on the system.

The ``_dict`` constructor parameter is an injection seam for tests —
pass any object with ``check(word) -> bool`` and ``suggest(word) -> list``
to replace the real enchant dictionary.
"""

import re
from pathlib import Path

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat


_WORD_RE = re.compile(r"\b[A-Za-z']{2,}\b")
_UNSET = object()  # sentinel: distinguishes "not passed" from None


class SpellHighlighter(QSyntaxHighlighter):
    """
    Underlines misspelled English words with a red wavy line.

    Falls back to a no-op when enchant or an English dictionary is not
    available.  Custom words loaded from a ``.lex`` file (one word per
    line; lines beginning with ``#`` are ignored) are never flagged.
    """

    def __init__(
        self,
        document,
        lang: str = "en_US",
        lex_path: Path | None = None,
        *,
        _dict=_UNSET,
    ) -> None:
        super().__init__(document)
        self._custom: set[str] = set()

        self._err_fmt = QTextCharFormat()
        self._err_fmt.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.SpellCheckUnderline
        )
        self._err_fmt.setUnderlineColor(QColor("red"))

        if _dict is not _UNSET:
            # Explicit injection: None means "disabled", any dict-like object is used.
            self._dict = _dict
        else:
            self._dict = None
            self._try_init(lang)

        if lex_path is not None:
            self.load_custom_words(lex_path)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _try_init(self, lang: str) -> None:
        """Try to load an enchant dictionary; silently set _dict to None on failure."""
        try:
            import enchant  # noqa: PLC0415
        except (ImportError, OSError):
            return

        for candidate in (lang, "en_US", "en_GB", "en_CA", "en"):
            try:
                self._dict = enchant.Dict(candidate)
                return
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True if an enchant dictionary is loaded and spell-checking is active."""
        return self._dict is not None

    def load_custom_words(self, lex_path: Path) -> None:
        """
        Replace the custom word list from a ``.lex`` file and re-highlight.

        The file format is one word per line; lines starting with ``#`` are
        treated as comments and ignored (handles the ``#LID 1033`` header
        written by the WPF original).
        """
        self._custom.clear()
        p = Path(lex_path)
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                word = line.strip()
                if word and not word.startswith("#"):
                    self._custom.add(word)
        self.rehighlight()

    def load_custom_words_list(self, words: list[str]) -> None:
        """Replace the custom word list from an in-memory list and re-highlight."""
        self._custom = set(words)
        self.rehighlight()

    def add_word(self, word: str) -> None:
        """Add a word to the in-memory custom list and re-highlight immediately."""
        self._custom.add(word)
        self.rehighlight()

    def check(self, word: str) -> bool:
        """
        Return True if ``word`` is spelled correctly or is in the custom list.

        Always returns True when no dictionary is loaded.
        """
        if word in self._custom:
            return True
        if self._dict is None:
            return True
        try:
            return bool(self._dict.check(word))
        except Exception:
            return True

    def suggest(self, word: str) -> list[str]:
        """Return spelling suggestions for ``word``, or an empty list."""
        if self._dict is None:
            return []
        try:
            return list(self._dict.suggest(word))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # QSyntaxHighlighter protocol
    # ------------------------------------------------------------------

    def highlightBlock(self, text: str) -> None:
        if self._dict is None:
            return
        for m in _WORD_RE.finditer(text):
            if not self.check(m.group()):
                self.setFormat(m.start(), m.end() - m.start(), self._err_fmt)
