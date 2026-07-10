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


_STATUS_TEXT = {"active": "In progress", "done": "Translated", "todo": "Not started"}
_DOT_COLORS = {"active": "#4fc47f", "done": "#4fc47f", "todo": "#565b56"}
_DOT_DIM = "#2e5c41"
_PLACEHOLDER = "Type your translation…"


def _repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class LineCard(QFrame):
    """One chapter line: header row, source text, translation text/editor slot."""

    clicked = Signal(int)

    def __init__(self, index: int, number: int, source_html: str,
                 translation: str, parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self._translation = translation
        self.setObjectName("LineCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 12, 16, 14)
        vbox.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._num_label = QLabel(str(number))
        self._num_label.setObjectName("CardNumber")
        self._dot = QLabel("●")
        self._status_label = QLabel()
        self._status_label.setObjectName("CardStatus")
        self._copied_pill = QLabel("Copied source to clipboard")
        self._copied_pill.setObjectName("CopiedPill")
        self._copied_pill.hide()
        self._pill_timer = QTimer(self)
        self._pill_timer.setSingleShot(True)
        self._pill_timer.setInterval(1600)
        self._pill_timer.timeout.connect(self._copied_pill.hide)
        header.addWidget(self._num_label)
        header.addWidget(self._dot)
        header.addWidget(self._status_label)
        header.addStretch(1)
        header.addWidget(self._copied_pill)
        vbox.addLayout(header)

        src_caption = QLabel("SOURCE")
        src_caption.setObjectName("CardCaption")
        vbox.addWidget(src_caption)
        self.source_label = QLabel()
        self.source_label.setObjectName("CardSource")
        self.source_label.setWordWrap(True)
        self.source_label.setTextFormat(Qt.TextFormat.RichText)
        self.source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.source_label.setText(source_html)
        vbox.addWidget(self.source_label)
        self._src_slot = QVBoxLayout()
        self._src_slot.setContentsMargins(0, 0, 0, 0)
        vbox.addLayout(self._src_slot)

        tr_caption = QLabel("TRANSLATION")
        tr_caption.setObjectName("CardCaption")
        vbox.addWidget(tr_caption)
        self._trans_label = QLabel()
        self._trans_label.setObjectName("CardTranslation")
        self._trans_label.setWordWrap(True)
        vbox.addWidget(self._trans_label)
        self._tr_slot = QVBoxLayout()
        self._tr_slot.setContentsMargins(0, 0, 0, 0)
        vbox.addLayout(self._tr_slot)

        self.set_translation(translation)
        self.set_state("done" if translation.strip() else "todo")

    # -- state ---------------------------------------------------------

    def state(self) -> str:
        return self.property("state") or "todo"

    def set_state(self, state: str) -> None:
        self.setProperty("state", state)
        self._status_label.setText(_STATUS_TEXT[state])
        self._dot.setStyleSheet(f"color: {_DOT_COLORS[state]}; font-size: 9px;")
        _repolish(self)
        _repolish(self._trans_label)

    def set_pulse_dim(self, dim: bool) -> None:
        if self.state() == "active":
            color = _DOT_DIM if dim else _DOT_COLORS["active"]
            self._dot.setStyleSheet(f"color: {color}; font-size: 9px;")

    # -- translation ---------------------------------------------------

    def translation_text(self) -> str:
        return self._translation

    def set_translation(self, text: str) -> None:
        self._translation = text
        empty = not text.strip()
        self._trans_label.setText(_PLACEHOLDER if empty else text)
        self._trans_label.setProperty("empty", empty)
        _repolish(self._trans_label)

    # -- shared-editor hosting -------------------------------------------

    def attach(self, source_edit, trans_edit) -> None:
        self.source_label.hide()
        self._trans_label.hide()
        self._src_slot.addWidget(source_edit)
        self._tr_slot.addWidget(trans_edit)
        source_edit.show()
        trans_edit.show()

    def detach(self, source_edit, trans_edit) -> None:
        self._src_slot.removeWidget(source_edit)
        self._tr_slot.removeWidget(trans_edit)
        source_edit.setParent(None)
        trans_edit.setParent(None)
        self.source_label.show()
        self._trans_label.show()
        self.set_state("done" if self._translation.strip() else "todo")

    # -- misc --------------------------------------------------------------

    def show_copied_pill(self) -> None:
        self._copied_pill.show()
        self._pill_timer.start()

    def set_font_size(self, pt: float) -> None:
        font = self.source_label.font()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(pt)
        self.source_label.setFont(font)
        self._trans_label.setFont(font)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.index)
        super().mousePressEvent(event)
