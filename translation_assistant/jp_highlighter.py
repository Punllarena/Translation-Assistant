from __future__ import annotations

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

_POS_COLORS: dict[str, str] = {
    "名詞": "#FFB86C",
    "動詞": "#8BE9FD",
    "形容詞": "#50FA7B",
    "助詞": "#6272A4",
    "助動詞": "#BD93F9",
}


class JpSyntaxHighlighter(QSyntaxHighlighter):
    """Colours Japanese tokens by MeCab POS tag. Silent no-op if MeCab absent."""

    def __init__(self, document):
        super().__init__(document)
        self._tagger = None
        self._use_fugashi = False
        self._fmts: dict[str, QTextCharFormat] = {}
        for pos_tag, color in _POS_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._fmts[pos_tag] = fmt
        self._init_tagger()

    def _init_tagger(self) -> None:
        try:
            import fugashi
            self._tagger = fugashi.Tagger()
            self._use_fugashi = True
            return
        except Exception:
            pass
        try:
            import MeCab  # type: ignore
            self._tagger = MeCab.Tagger()
        except Exception:
            pass

    def highlightBlock(self, text: str) -> None:
        if not self._tagger or not text.strip():
            return
        try:
            pos = 0
            if self._use_fugashi:
                for word in self._tagger(text):
                    surface = word.surface
                    pos_tag = getattr(word.feature, "pos1", "") or ""
                    fmt = self._fmts.get(pos_tag)
                    if fmt:
                        self.setFormat(pos, len(surface), fmt)
                    pos += len(surface)
            else:
                for line in self._tagger.parse(text).splitlines():
                    if line in ("EOS", ""):
                        continue
                    if "\t" in line:
                        surface, rest = line.split("\t", 1)
                        pos_tag = rest.split(",")[0] if rest else ""
                        fmt = self._fmts.get(pos_tag)
                        if fmt:
                            self.setFormat(pos, len(surface), fmt)
                        pos += len(surface)
                    else:
                        pos += len(line)
        except Exception:
            pass

    def token_info_at(self, text: str, char_pos: int) -> str:
        """Return a one-line tooltip for the MeCab token at char_pos, or ''."""
        if not self._tagger or not text:
            return ""
        try:
            pos = 0
            if self._use_fugashi:
                for word in self._tagger(text):
                    surface = word.surface
                    end = pos + len(surface)
                    if pos <= char_pos < end:
                        f = word.feature
                        reading = getattr(f, "kana", "") or getattr(f, "pron", "") or ""
                        lemma = getattr(f, "lemma", "") or ""
                        pos_tag = getattr(f, "pos1", "") or ""
                        parts = [surface]
                        if reading and reading != surface:
                            parts.append(f"[{reading}]")
                        if lemma and lemma != surface:
                            parts.append(f"({lemma})")
                        if pos_tag:
                            parts.append(f"<{pos_tag}>")
                        return "  ".join(parts)
                    pos = end
            else:
                for line in self._tagger.parse(text).splitlines():
                    if line in ("EOS", ""):
                        continue
                    if "\t" in line:
                        surface, rest = line.split("\t", 1)
                        fields = rest.split(",")
                        end = pos + len(surface)
                        if pos <= char_pos < end:
                            pos_tag = fields[0] if fields else ""
                            reading = fields[7] if len(fields) > 7 else ""
                            base = fields[6] if len(fields) > 6 else ""
                            parts = [surface]
                            if reading and reading not in ("*", surface):
                                parts.append(f"[{reading}]")
                            if base and base not in ("*", surface):
                                parts.append(f"({base})")
                            if pos_tag:
                                parts.append(f"<{pos_tag}>")
                            return "  ".join(parts)
                        pos = end
                    else:
                        pos += len(line)
        except Exception:
            pass
        return ""
