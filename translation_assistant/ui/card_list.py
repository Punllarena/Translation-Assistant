"""
Card-list chapter view — one card per line; a shared editor pair
(source QTextEdit + translation QTextEdit owned by TranslationAssistantWidget)
re-parents into the active card.
"""
import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

SERIF_FAMILIES = [
    "Source Serif 4", "Noto Serif CJK JP", "Noto Serif",
    "Microsoft YaHei", "Noto Sans CJK SC", "serif",
]

_AMBER_SPAN = (
    '<span style="background:#453a22;color:#e6c46a;'
    'border-radius:3px;padding:0 2px;">{}</span>'
)


def glossary_html(raw: str, glossary: list[tuple[str, str]]) -> str:
    """Strip %/$ markers, HTML-escape, and wrap glossary replacements in amber spans.

    Sequential replacement order matches core.replace_and_parse, but a later
    phrase cannot match into an earlier replacement's output (markup sits in
    between) — cosmetic difference only; the active card shows the real
    replace_and_parse text.
    """
    text = raw.replace("$", "").replace("%", "")
    buf = html.escape(text)
    for phrase, translation in glossary:
        if not phrase:
            continue
        escaped_phrase = html.escape(phrase)
        if escaped_phrase in buf:
            buf = buf.replace(escaped_phrase, _AMBER_SPAN.format(html.escape(translation)))
    return buf
