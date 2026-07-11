"""
Card-list chapter view — one card per line; a shared editor pair
(source QTextEdit + translation QTextEdit owned by TranslationAssistantWidget)
re-parents into the active card.
"""
import html

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPropertyAnimation, Qt, QTimer, Signal,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
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


class WrapLabel(QLabel):
    """Word-wrapping QLabel with memoized size queries.

    QLabel re-runs full text layout on every heightForWidth/sizeHint call,
    so one column relayout costs O(cards) text layouts — ~250 ms for a
    1000-card chapter. Cache per width; drop on text/font/style change.
    """

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self._hfw_cache: dict[int, int] = {}
        self._hint_cache = None
        self._min_hint_cache = None

    def _drop_size_cache(self) -> None:
        self._hfw_cache.clear()
        self._hint_cache = None
        self._min_hint_cache = None

    def heightForWidth(self, width: int) -> int:
        h = self._hfw_cache.get(width)
        if h is None:
            h = self._hfw_cache[width] = super().heightForWidth(width)
        return h

    def sizeHint(self):
        if self._hint_cache is None:
            self._hint_cache = super().sizeHint()
        return self._hint_cache

    def minimumSizeHint(self):
        if self._min_hint_cache is None:
            self._min_hint_cache = super().minimumSizeHint()
        return self._min_hint_cache

    def setText(self, text: str) -> None:
        self._drop_size_cache()
        super().setText(text)

    def changeEvent(self, e) -> None:
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._drop_size_cache()
        super().changeEvent(e)


class LineCard(QFrame):
    """One chapter line: header row, source text, translation text/editor slot."""

    clicked = Signal(int)

    def __init__(self, index: int, number: int, source_html: str,
                 translation: str, parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self._translation = translation
        self._label_font = None
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
        self.source_label = WrapLabel()
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
        self._trans_label = WrapLabel()
        self._trans_label.setObjectName("CardTranslation")
        self._trans_label.setWordWrap(True)
        vbox.addWidget(self._trans_label)
        self._tr_slot = QVBoxLayout()
        self._tr_slot.setContentsMargins(0, 0, 0, 0)
        vbox.addLayout(self._tr_slot)

        self._wheel_fx = QGraphicsOpacityEffect(self)
        self._wheel_fx.setOpacity(1.0)
        self._wheel_fx.setEnabled(False)
        self._wheel_opacity = 1.0
        self.setGraphicsEffect(self._wheel_fx)

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
        self._reassert_fonts()

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
        self._reassert_fonts()

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

    def set_wheel_opacity(self, opacity: float) -> None:
        """Fade with distance from the viewport center (picker-wheel look)."""
        # No-op when unchanged: most cards sit at the clamped floor while
        # scrolling, and each effect update schedules a repaint.
        if abs(opacity - self._wheel_opacity) < 0.01:
            return
        self._wheel_opacity = opacity
        # Effect disabled at full opacity: QGraphicsOpacityEffect renders the
        # card through a pixmap, which the active card's editors don't need.
        if opacity >= 0.999:
            self._wheel_fx.setEnabled(False)
        else:
            self._wheel_fx.setOpacity(opacity)
            self._wheel_fx.setEnabled(True)

    def set_font_size(self, pt: float) -> None:
        from PySide6.QtGui import QFont
        font = QFont()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(pt)
        self._label_font = font
        self._reassert_fonts()

    def _reassert_fonts(self) -> None:
        # Under an app stylesheet, any (re)polish — property restyle or
        # re-parenting into the layout — can reset assigned label fonts.
        # Only set when actually reset: a redundant setFont fires FontChange,
        # which drops the labels' size caches.
        if self._label_font is not None:
            if self.source_label.font() != self._label_font:
                self.source_label.setFont(self._label_font)
            if self._trans_label.font() != self._label_font:
                self._trans_label.setFont(self._label_font)

    def event(self, e) -> bool:
        # Polish arrives when the card is inserted into a styled hierarchy
        # (or restyled); it may clear the labels' assigned fonts.
        handled = super().event(e)
        if e.type() in (QEvent.Type.Polish, QEvent.Type.PolishRequest,
                        QEvent.Type.StyleChange):
            self._reassert_fonts()
        return handled

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.index)
        super().mousePressEvent(event)


class CardListView(QScrollArea):
    """Scrollable list of LineCards; hosts the shared editor pair."""

    card_clicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CardList")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container.setObjectName("CardListInner")
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(24, 20, 24, 20)
        self._vbox.setSpacing(14)
        self._placeholder = QLabel("No document open — File → New or Ctrl+O")
        self._placeholder.setObjectName("CardListPlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vbox.addWidget(self._placeholder)
        self._vbox.addStretch(1)
        self.setWidget(self._container)

        self._cards: dict[int, LineCard] = {}
        self._ordered: list[LineCard] = []   # visual (y-ascending) order
        self._pending: list[tuple[int, str]] = []
        self._built_count = 0
        self._load_translations: list[str] = []
        self._load_glossary: list[tuple[str, str]] = []
        self._source_edit = None
        self._trans_edit = None
        self._editor_font = None
        self.active_index: int | None = None
        self._font_pt: float | None = None

        self._pulse_on = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(800)
        self._pulse_timer.timeout.connect(self._on_pulse)

        self._scroll_anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(220)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # finished only fires when the animation reaches the end — a stop()
        # from rapid navigation does not highlight early.
        self._scroll_anim.finished.connect(self._highlight_active)
        self.verticalScrollBar().valueChanged.connect(self._apply_wheel)

    # -- setup -----------------------------------------------------------

    def set_editors(self, source_edit, trans_edit) -> None:
        self._source_edit = source_edit
        self._trans_edit = trans_edit

    # -- content -----------------------------------------------------------

    def load(self, raw_lines: list[str], translated_lines: list[str],
             glossary: list[tuple[str, str]]) -> None:
        from translation_assistant.core import line_has_content
        self._detach_active()
        for card in self._cards.values():
            self._vbox.removeWidget(card)
            card.deleteLater()
        self._cards = {}
        self._ordered = []

        # ponytail: chunked build (100 cards/tick) — 1000 sync cards took 3.6s;
        # virtualize only if even this proves too slow on real chapters.
        self._pending = [
            (i, raw) for i, raw in enumerate(raw_lines) if line_has_content(raw)
        ]
        self._built_count = 0
        self._load_translations = translated_lines
        self._load_glossary = glossary
        self._build_batch()
        if self._pending:
            QTimer.singleShot(0, self._build_batch)

        self._placeholder.setVisible(not (self._cards or self._pending))
        self._update_edge_padding()
        self.verticalScrollBar().setValue(0)

    def _build_batch(self) -> None:
        if not self._pending:
            return
        insert_at = self._vbox.indexOf(self._placeholder)
        batch, self._pending = self._pending[:100], self._pending[100:]
        for i, raw in batch:
            self._built_count += 1
            card = LineCard(i, self._built_count,
                            glossary_html(raw, self._load_glossary),
                            self._load_translations[i])
            if self._font_pt is not None:
                card.set_font_size(self._font_pt)
            card.clicked.connect(self.card_clicked)
            self._vbox.insertWidget(insert_at, card)
            insert_at += 1
            self._cards[i] = card
            self._ordered.append(card)
        if self._pending:
            QTimer.singleShot(0, self._build_batch)
        # Wheel fade needs settled geometry — apply after the layout pass.
        QTimer.singleShot(0, self._apply_wheel)

    def _ensure_built(self, index: int) -> None:
        while self._pending and index not in self._cards:
            self._build_batch()

    def card(self, index: int):
        return self._cards.get(index)

    def card_count(self) -> int:
        return len(self._cards)

    # -- active card ---------------------------------------------------------

    def set_active(self, index: int) -> None:
        self._ensure_built(index)
        card = self._cards.get(index)
        if card is None:
            return
        if index == self.active_index:
            self._scroll_to(card)
            return
        # Freeze the column layout across detach+attach — each hide/show/
        # reparent otherwise relayouts every card; one pass at the end.
        layout = self._container.layout()
        layout.setEnabled(False)
        try:
            self._detach_active()
            self.active_index = index
            if self._source_edit is not None:
                card.attach(self._source_edit, self._trans_edit)
                # Re-parenting under an app stylesheet re-polishes the editors,
                # which can reset their assigned font — re-assert it every move.
                if self._editor_font is not None:
                    self._source_edit.setFont(self._editor_font)
                    self._trans_edit.setFont(self._editor_font)
        finally:
            layout.setEnabled(True)
            layout.activate()
        if not self.isVisible():
            # No scroll animation offscreen — highlight immediately.
            self._highlight_active()
        self._scroll_to(card)

    def _highlight_active(self) -> None:
        """Apply the active highlight — after the centering scroll lands."""
        if self.active_index is None:
            return
        card = self._cards.get(self.active_index)
        if card is not None and card.state() != "active":
            card.set_state("active")
            self._pulse_timer.start()

    def _detach_active(self) -> None:
        if self.active_index is None:
            return
        old = self._cards.get(self.active_index)
        if old is not None and self._source_edit is not None:
            old.detach(self._source_edit, self._trans_edit)
        self.active_index = None
        self._pulse_timer.stop()

    def _scroll_to(self, card: LineCard) -> None:
        # After the layout pass, so geometry is valid on freshly built lists.
        QTimer.singleShot(0, lambda: self._center_on(card))

    def _center_on(self, card: LineCard) -> None:
        """Typewriter behavior: scroll so the card sits at the viewport center."""
        bar = self.verticalScrollBar()
        target = card.pos().y() + card.height() // 2 - self.viewport().height() // 2
        target = max(bar.minimum(), min(bar.maximum(), target))
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()

    def _update_edge_padding(self) -> None:
        # Half-viewport top/bottom padding lets the first and last cards
        # reach the center; keep the empty-state placeholder unpadded.
        pad = self.viewport().height() // 2 if (self._cards or self._pending) else 20
        m = self._vbox.contentsMargins()
        self._vbox.setContentsMargins(m.left(), pad, m.right(), pad)

    def _apply_wheel(self) -> None:
        """Fade cards by distance from the viewport center as the list scrolls.

        Runs per animation tick, so it only touches cards near the viewport:
        bisect on y (cards are in visual order), then walk until past the
        window. Beyond one half-viewport the fade is at its clamped floor
        anyway, so offscreen cards keep their last (floor) value.
        """
        vp_h = self.viewport().height()
        if vp_h <= 0 or not self._ordered:
            return
        top = self.verticalScrollBar().value()
        center = top + vp_h / 2
        half = vp_h / 2
        margin = 200
        # Active card is always full strength, even outside the window.
        if self.active_index is not None:
            active = self._cards.get(self.active_index)
            if active is not None:
                active.set_wheel_opacity(1.0)
        lo, hi = 0, len(self._ordered)
        while lo < hi:
            mid = (lo + hi) // 2
            card = self._ordered[mid]
            if card.pos().y() + card.height() < top - margin:
                lo = mid + 1
            else:
                hi = mid
        for card in self._ordered[lo:]:
            y = card.pos().y()
            if y > top + vp_h + margin:
                break
            if card.index == self.active_index:
                card.set_wheel_opacity(1.0)
                continue
            d = abs(y + card.height() / 2 - center) / half
            card.set_wheel_opacity(1.0 - 0.55 * min(d, 1.0))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_edge_padding()
        self._apply_wheel()

    def _on_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        if self.active_index is not None:
            card = self._cards.get(self.active_index)
            if card is not None:
                card.set_pulse_dim(self._pulse_on)

    # -- per-card updates ------------------------------------------------------

    def update_card(self, index: int, translation: str) -> None:
        self._ensure_built(index)
        card = self._cards.get(index)
        if card is None:
            return
        card.set_translation(translation)
        if index != self.active_index:
            card.set_state("done" if translation.strip() else "todo")

    def show_copied_pill(self, index: int) -> None:
        card = self._cards.get(index)
        if card is not None:
            card.show_copied_pill()

    def set_font_size(self, pt: float) -> None:
        from PySide6.QtGui import QFont
        self._font_pt = pt
        font = QFont()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(pt)
        self._editor_font = font
        if self._source_edit is not None:
            self._source_edit.setFont(font)
            self._trans_edit.setFont(font)
        for card in self._cards.values():
            card.set_font_size(pt)
