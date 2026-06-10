from __future__ import annotations

from ta.config.languages import Language
from ta.translators.base import BaseTranslator

_AVAILABLE = False
_USE_FUGASHI = False

try:
    import fugashi
    _AVAILABLE = True
    _USE_FUGASHI = True
except ImportError:
    try:
        import MeCab  # type: ignore
        _AVAILABLE = True
    except ImportError:
        pass

# Dracula palette
_C_SURFACE = "#f8f8f2"   # white — surface/copied text
_C_READING = "#8be9fd"   # cyan  — kana reading
_C_LEMMA   = "#ffb86c"   # orange — base lemma form
_C_POS     = "#6272a4"   # muted  — POS tag
_C_GLOSS   = "#50fa7b"   # green  — English translation
_C_BG      = "#282a36"   # dark bg


def _h(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _edict_gloss(lemma: str, surface: str) -> str:
    try:
        from ta.translators.jparser import load_edict_index
        idx = load_edict_index()
    except Exception:
        return ""
    if idx is None:
        return ""
    entry = idx.get(lemma) or idx.get(surface)
    return entry.gloss if entry else ""


def _fmt(surface: str, reading: str, lemma: str, pos: str, gloss: str) -> str:
    parts: list[str] = []
    parts.append(f'<span style="color:{_C_SURFACE};font-weight:bold">{_h(surface)}</span>')
    if reading and reading != surface:
        parts.append(f'<span style="color:{_C_READING}"> [{_h(reading)}]</span>')
    if lemma and lemma != surface:
        parts.append(f'<span style="color:{_C_LEMMA}"> ({_h(lemma)})</span>')
    if pos:
        parts.append(f'<span style="color:{_C_POS}"> &lt;{_h(pos)}&gt;</span>')
    header = "".join(parts)
    gloss_html = (
        f'<br>&nbsp;&nbsp;<span style="color:{_C_GLOSS}">{_h(gloss)}</span>'
        if gloss else ""
    )
    return f'<div style="margin-bottom:4px">{header}{gloss_html}</div>'


class MeCabTranslator(BaseTranslator):
    """Word-by-word Japanese morphological analysis using MeCab."""

    def __init__(self, parent=None):
        super().__init__("MeCab", parent)
        self._tagger = None

    @staticmethod
    def is_available() -> bool:
        return _AVAILABLE

    def _get_tagger(self):
        if self._tagger is None:
            if _USE_FUGASHI:
                import fugashi
                self._tagger = fugashi.Tagger()
            else:
                import MeCab  # type: ignore
                self._tagger = MeCab.Tagger()
        return self._tagger

    def can_translate(self, src: Language, dst: Language) -> bool:
        return _AVAILABLE

    def _do_translate(self, text: str, src: Language, dst: Language) -> str:
        tagger = self._get_tagger()
        entries: list[str] = []

        if _USE_FUGASHI:
            for word in tagger(text):
                f = word.feature
                reading = getattr(f, "kana", "") or getattr(f, "pron", "") or ""
                pos = getattr(f, "pos1", "") or ""
                lemma = getattr(f, "lemma", "") or ""
                display_lemma = lemma if lemma and lemma != word.surface else ""
                gloss = _edict_gloss(display_lemma or word.surface, word.surface)
                entries.append(_fmt(word.surface, reading, display_lemma, pos, gloss))
        else:
            result = tagger.parse(text)
            for line in result.splitlines():
                if line in ("EOS", ""):
                    continue
                if "\t" in line:
                    surface, rest = line.split("\t", 1)
                    fields = rest.split(",")
                    pos = fields[0] if fields else ""
                    reading = fields[7] if len(fields) > 7 else ""
                    base = fields[6] if len(fields) > 6 else ""
                    if reading in ("*",):
                        reading = ""
                    display_base = base if base and base not in ("*", surface) else ""
                    gloss = _edict_gloss(display_base or surface, surface)
                    entries.append(_fmt(surface, reading, display_base, pos, gloss))
                else:
                    entries.append(
                        f'<div><span style="color:{_C_SURFACE}">{_h(line)}</span></div>'
                    )

        body = "\n".join(entries)
        return (
            f'<html><body style="background:{_C_BG};color:{_C_SURFACE};'
            f'font-family:monospace;font-size:11pt;margin:4px">'
            f'{body}</body></html>'
        )
