# Card-List Editor Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-line-at-a-time pane layout with a whole-chapter card list (one card per line, editable in place) and recolor the app to the design's green dark theme.

**Architecture:** The existing `_raw_line` (source `QTextEdit` with MeCab highlighter) and `_translated_line` (translation `QTextEdit` with `SpellHighlighter`) survive as a **shared editor pair** that re-parents into whichever card is active. Inactive cards render source/translation as cheap `QLabel`s. All existing navigation, parse, clipboard, TM, autosave, and dictionary logic keeps operating on the same two widgets, so `main_widget.py` changes are mostly layout plumbing, not logic rewrites.

**Tech Stack:** PySide6, pytest (offscreen Qt via existing `qapp` fixture), QSS theming via `translation_assistant/resources/style.qss` (loaded by `main.py._load_qss` — **no new `ui/theme.py`**; the spec's theme.py is realized by rewriting the existing stylesheet, which is already applied app-wide).

**Spec:** `docs/superpowers/specs/2026-07-10-card-list-editor-redesign-design.md`

## Global Constraints

- Run everything inside the venv: `source .venv/bin/activate`.
- No changes to `core.py`, `db.py`, storage format, or dialog behavior.
- Chapters of 300–1000 lines must load acceptably (Task 7 measures; chunked build is the fallback — do NOT pre-build virtualization).
- `main_window.py` is legacy — do not touch it.
- Never import sqlite3 outside db.py; never write QSettings directly.
- Design deviations already agreed: no icon rail, no top toolbar, keep AggregatorWidget, status bar keeps current content. Card captions read `SOURCE` / `TRANSLATION` (no `· JA` / `· EN` — app is language-agnostic).
- Features intentionally dropped (spec "Removals" + brainstorm): source panel header label (`_source_label`), per-line word-count label (`_update_translation_label`), review-pane colors, double-click-to-jump.

---

### Task 1: `glossary_html` helper

**Files:**
- Create: `translation_assistant/ui/card_list.py`
- Test: `tests/test_card_list.py`

**Interfaces:**
- Produces: `glossary_html(raw: str, glossary: list[tuple[str, str]]) -> str` — strips `%`/`$`, HTML-escapes, wraps glossary replacements in amber `<span>`s. `SERIF_FAMILIES: list[str]` module constant. Both used by Tasks 2–4.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_card_list.py`:

```python
"""
Tests for the card-list chapter view.
"""
import pytest
from PySide6.QtCore import Qt

from translation_assistant.ui.card_list import glossary_html


class TestGlossaryHtml:
    def test_strips_markers(self):
        assert glossary_html("%Hello", []) == "Hello"
        assert glossary_html("$World", []) == "World"

    def test_escapes_html(self):
        out = glossary_html("%a <b> & c", [])
        assert "&lt;b&gt;" in out
        assert "&amp;" in out

    def test_wraps_glossary_replacement_in_amber_span(self):
        out = glossary_html("%ホロウ駅へ", [("ホロウ", "Hollow")])
        assert ">Hollow</span>" in out
        assert "ホロウ" not in out
        assert "#e6c46a" in out

    def test_replacements_applied_in_order(self):
        # Same sequential-replace semantics as core.replace_and_parse
        out = glossary_html("%abc", [("ab", "X"), ("Xc", "Y")])
        # First replace makes "Xc", second replaces that
        assert ">Y</span>" in out

    def test_escapes_glossary_translation(self):
        out = glossary_html("%ホロウ", [("ホロウ", "<i>H</i>")])
        assert "&lt;i&gt;H&lt;/i&gt;" in out
```

Note on `test_replacements_applied_in_order`: replacements run on the *escaped* string; the wrapping span markup from an earlier replacement is protected because later phrases are matched against escaped plain text (`html.escape(phrase)` won't match inside our injected `<span …>` attribute markup for realistic glossary phrases). The plain-visible-text semantics match `core.replace_and_parse`'s sequential `str.replace`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_card_list.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'glossary_html'`

- [ ] **Step 3: Write the implementation**

Create `translation_assistant/ui/card_list.py`:

```python
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

    Sequential replacement order matches core.replace_and_parse.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_card_list.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "feat(cards): glossary_html helper for card source rendering"
```

---

### Task 2: `LineCard`

**Files:**
- Modify: `translation_assistant/ui/card_list.py`
- Test: `tests/test_card_list.py`

**Interfaces:**
- Consumes: `glossary_html`, `SERIF_FAMILIES` (Task 1).
- Produces: `LineCard(index, number, source_html, translation)` with:
  - `index: int` attribute; `clicked = Signal(int)`
  - `set_state(state: str)` / `state() -> str` — `"active" | "done" | "todo"`
  - `set_translation(text: str)` — updates label, placeholder styling, stored text
  - `translation_text() -> str`
  - `attach(source_edit, trans_edit)` / `detach(source_edit, trans_edit)`
  - `show_copied_pill()` — 1.6 s transient pill
  - `set_pulse_dim(dim: bool)` — active-dot pulse frame
  - `set_font_size(pt: float)` — source + translation labels
  - `source_label` attribute (QLabel, for tests/highlight checks)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_card_list.py`:

```python
from translation_assistant.ui.card_list import LineCard


@pytest.fixture
def card(qapp):
    c = LineCard(3, 4, "Source text", "Existing translation")
    yield c
    c.deleteLater()


class TestLineCard:
    def test_holds_index_and_number(self, card):
        assert card.index == 3
        assert card._num_label.text() == "4"

    def test_source_label_shows_html(self, card):
        assert "Source text" in card.source_label.text()

    def test_initial_state_from_translation(self, qapp):
        done = LineCard(0, 1, "s", "t")
        todo = LineCard(1, 2, "s", "")
        assert done.state() == "done"
        assert todo.state() == "todo"
        done.deleteLater(); todo.deleteLater()

    def test_set_state_updates_status_text(self, card):
        card.set_state("active")
        assert card.state() == "active"
        assert card._status_label.text() == "In progress"
        card.set_state("done")
        assert card._status_label.text() == "Translated"
        card.set_state("todo")
        assert card._status_label.text() == "Not started"

    def test_set_translation_updates_label_and_state_basis(self, card):
        card.set_translation("")
        assert card.translation_text() == ""
        assert card._trans_label.property("empty") is True
        card.set_translation("Hi")
        assert card.translation_text() == "Hi"
        assert "Hi" in card._trans_label.text()

    def test_attach_detach_moves_editors(self, card, qapp):
        from PySide6.QtWidgets import QTextEdit
        src, tr = QTextEdit(), QTextEdit()
        card.attach(src, tr)
        assert src.parent() is not None
        assert card.source_label.isHidden()
        assert card._trans_label.isHidden()
        card.detach(src, tr)
        assert src.parent() is None
        assert not card.source_label.isHidden()

    def test_detach_recomputes_state(self, card, qapp):
        from PySide6.QtWidgets import QTextEdit
        src, tr = QTextEdit(), QTextEdit()
        card.set_state("active")
        card.set_translation("")
        card.attach(src, tr)
        card.detach(src, tr)
        assert card.state() == "todo"

    def test_click_emits_index(self, card, qapp):
        got = []
        card.clicked.connect(got.append)
        from PySide6.QtTest import QTest
        QTest.mouseClick(card, Qt.MouseButton.LeftButton)
        assert got == [3]

    def test_copied_pill_hidden_initially(self, card):
        assert card._copied_pill.isHidden()

    def test_show_copied_pill_makes_visible(self, card, qapp):
        card.show()
        card.show_copied_pill()
        assert not card._copied_pill.isHidden()

    def test_set_font_size(self, card):
        card.set_font_size(21.0)
        assert abs(card.source_label.font().pointSizeF() - 21.0) < 0.1
        assert abs(card._trans_label.font().pointSizeF() - 21.0) < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_card_list.py -q`
Expected: FAIL — `ImportError: cannot import name 'LineCard'`

- [ ] **Step 3: Write the implementation**

Append to `translation_assistant/ui/card_list.py`:

```python
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

    # -- shared-editor hosting ------------------------------------------

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

    # -- misc ------------------------------------------------------------

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_card_list.py -q`
Expected: all pass (5 + 12)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "feat(cards): LineCard widget with states and shared-editor slots"
```

---

### Task 3: `CardListView`

**Files:**
- Modify: `translation_assistant/ui/card_list.py`
- Test: `tests/test_card_list.py`

**Interfaces:**
- Consumes: `LineCard`, `glossary_html` (Tasks 1–2), `core.line_has_content`.
- Produces: `CardListView(QScrollArea)` with:
  - `card_clicked = Signal(int)` (line index)
  - `set_editors(source_edit, trans_edit)` — called once at setup
  - `load(raw_lines, translated_lines, glossary)` — rebuilds all cards; empty input shows placeholder
  - `set_active(index)` — detach from old card, attach to new, scroll into view; silently ignores indices without cards
  - `update_card(index, translation_text)` — label + state refresh
  - `show_copied_pill(index)`, `set_font_size(pt)`
  - `card(index) -> LineCard | None`, `card_count() -> int`, `active_index: int | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_card_list.py`:

```python
from translation_assistant.ui.card_list import CardListView


@pytest.fixture
def view(qapp):
    v = CardListView()
    yield v
    v.deleteLater()


@pytest.fixture
def editors(qapp):
    from PySide6.QtWidgets import QTextEdit
    src, tr = QTextEdit(), QTextEdit()
    yield src, tr
    src.deleteLater(); tr.deleteLater()


class TestCardListView:
    def test_placeholder_before_load(self, view):
        assert view.card_count() == 0
        assert not view._placeholder.isHidden()

    def test_load_builds_cards_for_content_lines_only(self, view):
        view.load(["%A", "", "%", "%B"], ["", "", "", "x"], [])
        assert view.card_count() == 2
        assert view.card(0) is not None
        assert view.card(1) is None      # blank line
        assert view.card(2) is None      # marker-only line
        assert view.card(3) is not None

    def test_load_hides_placeholder(self, view):
        view.load(["%A"], [""], [])
        assert view._placeholder.isHidden()

    def test_reload_replaces_cards(self, view):
        view.load(["%A", "%B"], ["", ""], [])
        view.load(["%C"], [""], [])
        assert view.card_count() == 1
        assert "C" in view.card(0).source_label.text()

    def test_glossary_applied_to_source(self, view):
        view.load(["%ホロウ駅"], [""], [("ホロウ", "Hollow")])
        assert "Hollow" in view.card(0).source_label.text()

    def test_initial_states(self, view):
        view.load(["%A", "%B"], ["done", ""], [])
        assert view.card(0).state() == "done"
        assert view.card(1).state() == "todo"

    def test_set_active_attaches_editors(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A", "%B"], ["", ""], [])
        view.set_active(0)
        assert view.active_index == 0
        assert view.card(0).state() == "active"
        assert src.parent() is not None

    def test_set_active_moves_between_cards(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A", "%B"], ["", ""], [])
        view.set_active(0)
        view.set_active(1)
        assert view.card(0).state() == "todo"
        assert view.card(1).state() == "active"

    def test_set_active_missing_index_is_noop(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A", "", "%B"], ["", "", ""], [])
        view.set_active(0)
        view.set_active(1)   # blank line — no card
        assert view.active_index == 0

    def test_update_card_refreshes_label_and_state(self, view):
        view.load(["%A"], [""], [])
        view.update_card(0, "Done now")
        assert view.card(0).translation_text() == "Done now"
        assert view.card(0).state() == "done"

    def test_update_card_keeps_active_state(self, view, editors):
        src, tr = editors
        view.set_editors(src, tr)
        view.load(["%A"], [""], [])
        view.set_active(0)
        view.update_card(0, "text")
        assert view.card(0).state() == "active"

    def test_card_click_forwards_signal(self, view):
        view.load(["%A", "%B"], ["", ""], [])
        got = []
        view.card_clicked.connect(got.append)
        view.card(1).clicked.emit(1)
        assert got == [1]

    def test_show_copied_pill(self, view, qapp):
        view.load(["%A"], [""], [])
        view.show()
        view.show_copied_pill(0)
        assert not view.card(0)._copied_pill.isHidden()

    def test_set_font_size_propagates(self, view):
        view.load(["%A", "%B"], ["", ""], [])
        view.set_font_size(20.0)
        assert abs(view.card(0).source_label.font().pointSizeF() - 20.0) < 0.1

    def test_load_empty_shows_placeholder(self, view):
        view.load(["%A"], [""], [])
        view.load([], [], [])
        assert view.card_count() == 0
        assert not view._placeholder.isHidden()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_card_list.py -q`
Expected: FAIL — `ImportError: cannot import name 'CardListView'`

- [ ] **Step 3: Write the implementation**

Append to `translation_assistant/ui/card_list.py`:

```python
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
        self._source_edit = None
        self._trans_edit = None
        self.active_index: int | None = None
        self._font_pt: float | None = None

        self._pulse_on = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(800)
        self._pulse_timer.timeout.connect(self._on_pulse)

    # -- setup -----------------------------------------------------------

    def set_editors(self, source_edit, trans_edit) -> None:
        self._source_edit = source_edit
        self._trans_edit = trans_edit

    # -- content ----------------------------------------------------------

    def load(self, raw_lines: list[str], translated_lines: list[str],
             glossary: list[tuple[str, str]]) -> None:
        from translation_assistant.core import line_has_content
        self._detach_active()
        self.active_index = None
        self._pulse_timer.stop()
        for card in self._cards.values():
            self._vbox.removeWidget(card)
            card.deleteLater()
        self._cards = {}

        insert_at = self._vbox.indexOf(self._placeholder)
        number = 0
        for i, raw in enumerate(raw_lines):
            if not line_has_content(raw):
                continue
            number += 1
            card = LineCard(i, number, glossary_html(raw, glossary),
                            translated_lines[i])
            if self._font_pt is not None:
                card.set_font_size(self._font_pt)
            card.clicked.connect(self.card_clicked)
            self._vbox.insertWidget(insert_at, card)
            insert_at += 1
            self._cards[i] = card

        self._placeholder.setVisible(not self._cards)
        self.verticalScrollBar().setValue(0)

    def card(self, index: int):
        return self._cards.get(index)

    def card_count(self) -> int:
        return len(self._cards)

    # -- active card -------------------------------------------------------

    def set_active(self, index: int) -> None:
        card = self._cards.get(index)
        if card is None:
            return
        if index == self.active_index:
            self._scroll_to(card)
            return
        self._detach_active()
        self.active_index = index
        if self._source_edit is not None:
            card.attach(self._source_edit, self._trans_edit)
        card.set_state("active")
        self._pulse_timer.start()
        self._scroll_to(card)

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
        QTimer.singleShot(0, lambda: self.ensureWidgetVisible(card, 50, 80))

    def _on_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        if self.active_index is not None:
            card = self._cards.get(self.active_index)
            if card is not None:
                card.set_pulse_dim(self._pulse_on)

    # -- per-card updates ----------------------------------------------------

    def update_card(self, index: int, translation: str) -> None:
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
        self._font_pt = pt
        for card in self._cards.values():
            card.set_font_size(pt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_card_list.py -q`
Expected: all pass (~32)

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "feat(cards): CardListView with shared-editor activation and scroll"
```

---

### Task 4: Rewire `main_widget.py` + `combined_window.py`

The pane layout dies; the card view takes its place. `combined_window` must change in the same commit because it consumes the panel properties.

**Files:**
- Modify: `translation_assistant/ui/main_widget.py`
- Modify: `translation_assistant/ui/combined_window.py`
- Test: `tests/test_main_window.py`, `tests/test_combined_window.py`, `tests/test_integration.py`

**Interfaces:**
- Consumes: `CardListView`, `SERIF_FAMILIES` from `translation_assistant.ui.card_list` (Task 3).
- Produces: `TranslationAssistantWidget.card_panel` property (returns the `CardListView`); properties `context_above_panel`, `source_panel`, `translation_panel`, `context_below_panel` are **deleted**; `tm_panel`, `status_bar` unchanged. `_card_view` attribute. `_raw_line`, `_translated_line`, `_array_pointer`, all navigation methods keep their names and semantics (Tasks 5–7 and existing tests rely on this).

- [ ] **Step 1: Update existing tests to the card-list interface (failing first)**

In `tests/test_main_window.py`:

Replace `test_placeholder_shown_in_review_top` and `test_placeholder_shown_in_review_bottom` (lines ~81–87) with:

```python
    def test_card_view_placeholder_before_load(self, win):
        assert win._card_view.card_count() == 0
        assert "No document open" in win._card_view._placeholder.text()
```

Replace the four panel-exposure tests `test_exposes_context_above_panel`, `test_exposes_source_panel`, `test_exposes_translation_panel`, `test_exposes_context_below_panel` (keep `test_exposes_tm_panel`) with:

```python
    def test_exposes_card_panel(self, win):
        from translation_assistant.ui.card_list import CardListView
        assert isinstance(win.card_panel, CardListView)
```

Delete `test_ctx_above_label_has_expand_chevron`, `test_ctx_below_label_has_expand_chevron`, `test_ctx_above_inner_visible_by_default`, `test_ctx_below_inner_visible_by_default` (lines ~130–148).

Replace `test_review_bottom_shows_subsequent_lines` / `test_review_top_empty_at_line_zero` (lines ~190–197) with:

```python
    def test_all_lines_get_cards(self, win):
        _load(win, "%First\n%Second\n%Third\n")
        assert win._card_view.card_count() == 3
        assert "Second" in win._card_view.card(1).source_label.text()
        assert "Third" in win._card_view.card(2).source_label.text()

    def test_first_card_active_after_load(self, win):
        _load(win, "%Only\n")
        assert win._card_view.active_index == 0
        assert win._card_view.card(0).state() == "active"
```

Replace `test_advance_updates_review_top` (line ~248) with:

```python
    def test_advance_updates_card_states(self, win):
        _load(win, "%First\n%Second\n")
        win._translated_line.setPlainText("done")
        win._navigate_forward()
        assert win._card_view.card(0).state() == "done"
        assert win._card_view.card(1).state() == "active"
```

In `TestFontSize`, replace `test_apply_font_sets_font_on_all_panels` with:

```python
    def test_apply_font_sets_font_on_editors_and_cards(self, win):
        win._settings.font_size = 18.0
        _load(win, "%A\n")
        win._apply_font()
        for panel in (win._raw_line, win._translated_line):
            assert abs(panel.font().pointSizeF() - 18.0) < 0.1
        assert abs(win._card_view.card(0).source_label.font().pointSizeF() - 18.0) < 0.1
```

Delete the whole `TestSourceLabel` class (lines ~798–824) and, in `TestPanelLabelCounts`, delete `test_source_label_includes_line_count` and `test_source_label_includes_title_and_lines`; delete the translation-word-count tests (`"2 words" in win._translation_label`, `test_translation_label_zero_words_when_empty`, `test_translation_label_resets_on_db_import`) — grep for `_translation_label` and `_source_label` in the test file and remove every remaining reference.

Add a card-click test in `TestJumps`:

```python
    def test_card_click_navigates(self, win):
        _load(win, "%A\n%B\n%C\n")
        win._translated_line.setPlainText("alpha")
        win._on_card_clicked(2)
        assert win._array_pointer == 2
        assert win._translated_lines[0] == "alpha"
        assert win._card_view.card(2).state() == "active"
```

In `tests/test_integration.py`, replace `test_continuation_lines_grouped_in_review_bottom` (line ~359) with:

```python
    def test_continuation_lines_have_own_cards(self, win):
        win.load_content(_sep("%Head。\n$Continuation。\n%Next\n"))
        assert "Head" in win._raw_line.toPlainText()
        assert win._card_view.card_count() == 3
        assert "Continuation" in win._card_view.card(1).source_label.text()
```

In `tests/test_combined_window.py`, replace the splitter tests (lines ~56–70) with:

```python
    def test_has_main_splitter(self, win):
        from PySide6.QtWidgets import QSplitter
        from PySide6.QtCore import Qt
        assert isinstance(win._main_splitter, QSplitter)
        assert win._main_splitter.orientation() == Qt.Orientation.Horizontal
        assert win._main_splitter.count() == 2

    def test_right_splitter_is_vertical(self, win):
        from PySide6.QtCore import Qt
        assert win._right_splitter.orientation() == Qt.Orientation.Vertical
        assert win._right_splitter.count() == 2
```

Also grep all three test files for any remaining `_review_top`, `_review_bottom`, `_panel_ctx`, `context_above_panel`, `context_below_panel`, `source_panel`, `translation_panel`, `_outer_splitter`, `_mid_splitter`, `_left_splitter` references and update/delete them the same way.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `pytest tests/test_main_window.py tests/test_combined_window.py tests/test_integration.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_card_view'` etc.

- [ ] **Step 3: Rewire `main_widget.py`**

3a. Imports — add `CardListView` and serif families; `QSizePolicy` becomes unused (remove from the import list); keep the rest:

```python
from translation_assistant.ui.card_list import CardListView, SERIF_FAMILIES
```

3b. Delete the `ReviewTextEdit` class (lines ~131–139).

3c. In `__init__`, delete the `self._top_map` / `self._bottom_map` initializations.

3d. Replace `_setup_central_widget` entirely with:

```python
    def _setup_central_widget(self) -> None:
        font = QFont()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(self._settings.font_size)

        def _labeled(title, inner: QWidget) -> QFrame:
            w = QFrame(self)
            w.setObjectName("Card")
            vbox = QVBoxLayout(w)
            vbox.setContentsMargins(8, 8, 8, 8)
            vbox.setSpacing(4)
            lbl = title if not isinstance(title, str) else QLabel(title)
            lbl.setObjectName("PanelLabel")
            vbox.addWidget(lbl)
            vbox.addWidget(inner)
            return w

        self._raw_line = QTextEdit()
        self._raw_line.setObjectName("SourceText")
        self._raw_line.setReadOnly(True)
        self._raw_line.setFont(font)
        self._raw_line.setMinimumHeight(40)
        self._raw_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._jp_highlighter = JpSyntaxHighlighter(self._raw_line.document())

        self._translated_line = QTextEdit()
        self._translated_line.setObjectName("TranslationText")
        self._translated_line.setFont(font)
        self._translated_line.setMinimumHeight(40)
        self._translated_line.setAcceptRichText(False)
        self._translated_line.setPlaceholderText("Type your translation…")
        self._translated_line.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._translated_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._translated_line.customContextMenuRequested.connect(self._on_translated_context_menu)
        self._spell_highlighter = SpellHighlighter(self._translated_line.document())

        self._card_view = CardListView()
        self._card_view.set_editors(self._raw_line, self._translated_line)
        self._card_view.card_clicked.connect(self._on_card_clicked)

        self._tm_panel = QWidget()
        self._tm_panel.setMinimumHeight(0)
        self._tm_layout = QVBoxLayout(self._tm_panel)
        self._tm_layout.setContentsMargins(2, 2, 2, 2)
        self._tm_layout.setSpacing(2)
        _tm_lbl = _ClickableLabel("TM Matches")
        _tm_lbl.setObjectName("PanelLabel")
        _tm_lbl.clicked.connect(self._toggle_tm_panel)
        self._panel_tm = _labeled(_tm_lbl, self._tm_panel)
        self._panel_tm.setVisible(False)

        for widget in (self._raw_line, self._translated_line):
            widget.installEventFilter(self)

        self._translated_line.textChanged.connect(self._on_translation_text_changed)
```

(Note: the collapse-key machinery in `_labeled` was only used by the context panels — the trimmed version above drops it. The second `textChanged` connection to `_update_translation_label` is gone; see 3j.)

3e. Replace `_finish_load` with:

```python
    def _finish_load(self) -> None:
        self._last_save_time = 0.0
        self._autosave_tick_timer.stop()
        self._update_filesaved_label()
        from translation_assistant.core import replace_and_parse, line_has_content
        raw_lines = self._raw_lines
        translated_lines = self._translated_lines

        p = self._array_pointer
        if raw_lines and not line_has_content(raw_lines[p]):
            p = next(
                (i for i in range(p, len(raw_lines)) if line_has_content(raw_lines[i])),
                p,
            )
            self._array_pointer = p

        self._card_view.load(raw_lines, translated_lines, self._glossary)

        display, sentences, replaced = replace_and_parse(
            raw_lines[p], self._glossary, self._parse_chars
        )
        self._raw_line.setPlainText(display)
        self._block_dirty = True
        self._translated_line.setPlainText(translated_lines[p])
        self._block_dirty = False
        self._parse_sentences = sentences
        self._parse_pointer = -1
        self._parse_label.setVisible(False)
        self._replaced = replaced

        self._card_view.set_active(p)
        self._update_progress_labels()

        self.action_save.setEnabled(True)
        self.action_export.setEnabled(True)
        self.action_publish_wp.setEnabled(True)
        self.action_clipboard.setEnabled(True)
        self.action_go_to_line.setEnabled(True)
        self.action_export_md_tl_doc.setEnabled(True)
        self.action_export_md_ruby_doc.setEnabled(True)
        _doc_meta = self._db.get_document(self._doc_id)
        _doc_display = _doc_meta.get("chapter_title") or _doc_meta.get("title") or ""
        self._doc_title = _doc_display
        self._refresh_window_title()
        _has_series = bool(_doc_meta.get("series_title", ""))
        self.action_export_md_tl_series.setEnabled(_has_series)
        self.action_export_md_ruby_series.setEnabled(_has_series)
        self._translated_line.setFocus()
        self._start_clipboard_timer()
        self._restart_autosave_timer()
        self._update_stats_label()
        self._update_progress_visibility()
        self._update_profile_label()
        self._set_dirty(False)
        if self._doc_id is not None:
            self._settings.add_to_recent(self._doc_id)

        self._update_wp_status_label()

        raw = self._raw_lines[p]
        self.source_sentence_changed.emit(raw.lstrip("%$").strip())
```

3f. Replace `_update_ui_for_pointer` with:

```python
    def _update_ui_for_pointer(self) -> None:
        from translation_assistant.core import replace_and_parse
        p = self._array_pointer

        display, sentences, replaced = replace_and_parse(
            self._raw_lines[p], self._glossary, self._parse_chars
        )
        self._raw_line.setPlainText(display)
        self._block_dirty = True
        self._translated_line.setPlainText(self._translated_lines[p])
        self._block_dirty = False
        self._parse_sentences = sentences
        self._parse_pointer = -1
        self._replaced = replaced

        self._card_view.set_active(p)
        self._update_progress_labels()
        self._translated_line.setFocus()
        self._start_clipboard_timer()

        raw = self._raw_lines[p]
        self.source_sentence_changed.emit(raw.lstrip("%$").strip())
        self._update_tm_panel()
        self._parse_label.setVisible(False)
```

3g. Delete `_apply_review_colors`, `_on_review_top_double_click`, `_on_review_bottom_double_click` and `_update_translation_label`; remove the two now-unused imports if nothing else uses them (`QColor`, `QTextCharFormat` — verify with grep before removing). Remove the calls to `_update_translation_label` in `_finish_load`/`_update_ui_for_pointer` (already absent from the versions above) and anywhere else (`grep -n _update_translation_label`).

3h. In `_save_current_translation`, add the card update after the array write:

```python
    def _save_current_translation(self) -> None:
        if not self._raw_lines:
            return
        text = self._translated_line.toPlainText()
        self._translated_lines[self._array_pointer] = text
        self._card_view.update_card(self._array_pointer, text)
        if self._doc_id is not None:
            self._db.save_translation(self._doc_id, self._array_pointer, text)
            self._update_stats_label()
            self._set_dirty(False)
```

3i. Add the card-click slot (place after `_jump_to_next_untranslated`):

```python
    def _on_card_clicked(self, index: int) -> None:
        if index == self._array_pointer:
            self._translated_line.setFocus()
            return
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = index
        self._update_ui_for_pointer()
```

3j. `_apply_font` becomes:

```python
    def _apply_font(self) -> None:
        font = QFont()
        font.setFamilies(SERIF_FAMILIES)
        font.setPointSizeF(self._settings.font_size)
        for w in (self._raw_line, self._translated_line):
            w.setFont(font)
        self._card_view.set_font_size(self._settings.font_size)
```

3k. `_on_clipboard_timer` gains the pill:

```python
    def _on_clipboard_timer(self) -> None:
        selected = self._raw_line.textCursor().selectedText()
        text = selected if selected else self._raw_line.toPlainText()
        QApplication.clipboard().setText(text)
        self._card_view.show_copied_pill(self._array_pointer)
```

3l. `_on_go_to_line`: after `if not ok: return`, clamp to a content line:

```python
        from translation_assistant.core import line_has_content
        idx = line_num - 1
        if not line_has_content(self._raw_lines[idx]):
            idx = next(
                (i for i in range(idx, n) if line_has_content(self._raw_lines[i])),
                next((i for i in range(idx, -1, -1)
                      if line_has_content(self._raw_lines[i])), 0),
            )
        self._clipboard_timer.stop()
        self._save_current_translation()
        self._array_pointer = idx
        self._update_ui_for_pointer()
        self._translated_line.setFocus()
```

3m. `eventFilter`: watched set shrinks to `(self._raw_line, self._translated_line)`.

3n. `_navigate_backward`: the eof branch keeps only the `_line_label` update (it already doesn't touch review panes — no change needed beyond what compiles).

3o. Panel properties: delete `context_above_panel`, `source_panel`, `translation_panel`, `context_below_panel`; add:

```python
    @property
    def card_panel(self) -> QWidget:
        return self._card_view
```

3p. Grep for leftovers: `grep -n "_review_top\|_review_bottom\|_panel_ctx\|_panel_source\|_panel_translation\|_source_label\|_top_map\|_bottom_map\|build_review_text\|_translation_label" translation_assistant/ui/main_widget.py` must return nothing (except `_panel_tm`).

- [ ] **Step 4: Rewire `combined_window.py`**

Replace `_build_workspace` with:

```python
    def _build_workspace(self) -> None:
        ta = self._ta_widget
        ta.setParent(self)

        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter.setChildrenCollapsible(False)
        self._right_splitter.addWidget(self._agg_widget)
        self._right_splitter.addWidget(ta.tm_panel)
        self._right_splitter.setStretchFactor(0, 2)
        self._right_splitter.setStretchFactor(1, 1)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.addWidget(ta.card_panel)
        self._main_splitter.addWidget(self._right_splitter)
        self._main_splitter.setStretchFactor(0, 2)
        self._main_splitter.setStretchFactor(1, 1)

        # Wrap in container to provide window margins
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(12, 12, 12, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._main_splitter)
        self.setCentralWidget(container)
```

Replace `_restore_splitter` / `_save_splitter` with:

```python
    def _restore_splitter(self) -> None:
        qs = self._ta_widget._settings._qs
        defaults_applied = False
        for key, splitter in [
            ("combined/splitter_main2",  self._main_splitter),
            ("combined/splitter_right2", self._right_splitter),
        ]:
            raw = qs.value(key)
            if raw:
                splitter.restoreState(QByteArray.fromBase64(raw.encode()))
            else:
                defaults_applied = True

        if defaults_applied:
            self._main_splitter.setSizes([760, 380])
            self._right_splitter.setSizes([400, 200])

    def _save_splitter(self) -> None:
        qs = self._ta_widget._settings._qs
        for key, splitter in [
            ("combined/splitter_main2",  self._main_splitter),
            ("combined/splitter_right2", self._right_splitter),
        ]:
            qs.setValue(key, splitter.saveState().toBase64().data().decode())
```

- [ ] **Step 5: Run the three test files, then the full suite**

Run: `pytest tests/test_main_window.py tests/test_combined_window.py tests/test_integration.py -q`
Expected: PASS. Then `pytest -q` — expected: PASS (test count will differ from 535 after deletions/additions; zero failures is the bar). Fix any straggler references the greps missed.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/
git commit -m "feat(cards): replace pane layout with card-list editor"
```

---

### Task 5: Keyboard additions — Shift+Enter newline, Ctrl+↓/↑ navigation

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (`_handle_key`)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `_navigate_forward` / `_navigate_backward` (unchanged names, Task 4).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_window.py` (uses the file's existing `win` fixture and `_load` helper):

```python
class TestKeyboardAdditions:
    @staticmethod
    def _key(win, key, mods=Qt.KeyboardModifier.NoModifier):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        return win._handle_key(QKeyEvent(QEvent.Type.KeyPress, key, mods))

    def test_shift_enter_passes_through_for_newline(self, win):
        _load(win, "%A\n%B\n")
        handled = self._key(win, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert handled is False
        assert win._array_pointer == 0

    def test_plain_enter_still_advances(self, win):
        _load(win, "%A\n%B\n")
        assert self._key(win, Qt.Key.Key_Return) is True
        assert win._array_pointer == 1

    def test_ctrl_down_advances(self, win):
        _load(win, "%A\n%B\n")
        assert self._key(win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier) is True
        assert win._array_pointer == 1

    def test_ctrl_up_goes_back(self, win):
        _load(win, "%A\n%B\n")
        win._navigate_forward()
        assert self._key(win, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier) is True
        assert win._array_pointer == 0
```

Ensure `Qt` is imported at the top of the test file (`from PySide6.QtCore import Qt` — already present if other tests use it; add if not).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main_window.py::TestKeyboardAdditions -q`
Expected: FAIL — Shift+Enter currently returns True (navigates); Ctrl+↓/↑ return False.

- [ ] **Step 3: Implement in `_handle_key`**

Replace the Return/Enter branch and add the Ctrl+arrow branches:

```python
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods == Qt.KeyboardModifier.ShiftModifier:
                return False  # let QTextEdit insert a newline
            self._navigate_forward(write_file=True)
            return True
        if ctrl and key == Qt.Key.Key_Down:
            self._navigate_forward(write_file=False)
            return True
        if ctrl and key == Qt.Key.Key_Up:
            self._navigate_backward()
            return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main_window.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(keys): Shift+Enter newline, Ctrl+Up/Down line navigation"
```

---

### Task 6: Green dark theme in `style.qss`

**Files:**
- Modify: `translation_assistant/resources/style.qss`

No unit tests (visual); verification is launching the app. The stylesheet is already loaded app-wide by `main.py`, so this is a recolor plus new card selectors — no Python changes.

- [ ] **Step 1: Global color remap**

Apply this exact substitution across the whole file (old indigo → new green-tinted value):

| Old | New | Role |
|---|---|---|
| `#0F1117` | `#191b19` | base background |
| `#1A1D27` | `#222522` | panel / card background |
| `#13151E` | `#1d201d` | muted background |
| `#161929` | `#1f231f` | field background |
| `#23263A` | `#2a2f2a` | hover background |
| `#2E3350` | `#3a3e3a` | borders |
| `#3D4AB3` | `#2e5c41` | pressed / selection background |
| `#5C6BFF` | `#4fc47f` | accent |
| `#7380FF` | `#6ad395` | accent hover |
| `#E8E6F0` | `#ecefec` | primary text |
| `#EAF0FF` | `#ecefec` | primary text (variant) |
| `#F0EDE8` | `#ecefec` | primary text (variant) |
| `#8B8FA8` | `#9aa09a` | secondary text |
| `#3ECF8E` | `#4fc47f` | success green |

`#FF5E5E` (error) and `#F5A623` (warning) stay. Accent-colored button *text on accent background* (e.g. `#AccentBtn` color) — verify contrast after remap: text on `#4fc47f` should be `#14170f`-ish dark, so set `QPushButton#AccentBtn { color: #142018; }` (and same for `#TranslateAllBtn`) if the old rule used white-ish text.

```bash
sed -i 's/#0F1117/#191b19/g; s/#1A1D27/#222522/g; s/#13151E/#1d201d/g; s/#161929/#1f231f/g; s/#23263A/#2a2f2a/g; s/#2E3350/#3a3e3a/g; s/#3D4AB3/#2e5c41/g; s/#5C6BFF/#4fc47f/g; s/#7380FF/#6ad395/g; s/#E8E6F0/#ecefec/g; s/#EAF0FF/#ecefec/g; s/#F0EDE8/#ecefec/g; s/#8B8FA8/#9aa09a/g; s/#3ECF8E/#4fc47f/g' translation_assistant/resources/style.qss
```

- [ ] **Step 2: Delete dead pane styles, rewrite editor styles**

Delete the `QTextEdit#ContextAbove, QTextEdit#ContextBelow { … }` block entirely.

Replace the `QTextEdit#SourceText` and `QTextEdit#TranslationText` blocks with in-card field styling. **No `font-family`/`font-size` here** — runtime `setFont` (serif chain + user size) must win:

```css
/* In-card source (read-only, hosted by the active LineCard) */
QTextEdit#SourceText {
    background: #1f231f;
    color: #d3d8d3;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #2e5c41;
}

/* In-card translation editor */
QTextEdit#TranslationText {
    background: #2a2f2a;
    color: #ecefec;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #2e5c41;
}
QTextEdit#TranslationText:focus {
    border-color: #4fc47f;
}
```

- [ ] **Step 3: Add card-list styles**

Append a new section:

```css
/* === Card list === */
QScrollArea#CardList { border: none; background: #191b19; }
QWidget#CardListInner { background: #191b19; }
QLabel#CardListPlaceholder { color: #6f746f; font-size: 14px; padding: 40px; }

QFrame#LineCard {
    background: #222522;
    border: 1px solid #3a3e3a;
    border-radius: 12px;
}
QFrame#LineCard[state="active"] {
    background: #232a24;
    border: 2px solid #4fc47f;
}
QFrame#LineCard[state="todo"] {
    background: #1d201d;
    border: 1px dashed #3a3e3a;
}

QLabel#CardNumber  { color: #6f746f; font-weight: 600; font-size: 12px; background: transparent; }
QLabel#CardStatus  { color: #6f746f; font-size: 12px; background: transparent; }
QLabel#CardCaption { color: #6a6f6a; font-size: 10px; letter-spacing: 2px; background: transparent; }
QLabel#CardSource  { color: #d3d8d3; background: transparent; }
QLabel#CardTranslation { color: #ecefec; background: transparent; }
QLabel#CardTranslation[empty="true"] { color: #6f746f; font-style: italic; }
QLabel#CopiedPill {
    color: #7bd8a0;
    background: #24382c;
    border-radius: 9px;
    padding: 3px 9px;
    font-size: 11px;
}
```

(No `font-size` on `CardSource`/`CardTranslation` — runtime `set_font_size` controls it.)

- [ ] **Step 4: Verify visually and run the suite**

Run: `pytest -q` — expected: PASS (QSS changes shouldn't break tests).
Launch: `python -m translation_assistant.main`. Check: card states render (solid/dashed/green borders), focus ring on the editor, menus/status bar/aggregator recolored, then open each dialog from the menus (New, Open, Series, Profile, Phrases, Stats, Shortcuts, WP Settings, Setup Guide) and confirm they're legible — the palette remap covers them, but look for hardcoded-color regressions.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/resources/style.qss
git commit -m "feat(theme): green dark palette + card-list styles"
```

---

### Task 7: 1000-line load measurement + final verification

**Files:**
- Create (scratchpad only, not committed): `perf_cards.py` in the session scratchpad directory

- [ ] **Step 1: Measure card build time**

Write to the scratchpad dir:

```python
import time
from PySide6.QtWidgets import QApplication
from translation_assistant.ui.card_list import CardListView

app = QApplication([])
view = CardListView()
raws = [f"%これはテスト文です。行番号{i}、少し長めの文章にしておく。" for i in range(1000)]
trans = ["translated text here" if i % 2 else "" for i in range(1000)]

t0 = time.perf_counter()
view.load(raws, trans, [("テスト", "test")])
view.resize(900, 700)
view.show()
app.processEvents()
print(f"build+show 1000 cards: {time.perf_counter() - t0:.2f}s")
```

Run: `python <scratchpad>/perf_cards.py`
Expected: prints a duration.

- [ ] **Step 2: Decide**

If < 2.0 s: done, no changes (record the number in the commit message of Step 4).
If ≥ 2.0 s: implement chunked build in `CardListView.load` — build the first 100 cards synchronously, then the rest in 100-card batches via `QTimer.singleShot(0, …)` continuation:

```python
    # inside load(), replace the single for-loop over raw_lines with:
    items = [(i, raw) for i, raw in enumerate(raw_lines) if line_has_content(raw)]
    self._pending = list(enumerate(items, start=1))  # (number, (index, raw))
    self._build_batch(translated_lines, glossary, first=True)
```

```python
    def _build_batch(self, translated_lines, glossary, first=False) -> None:
        insert_at = self._vbox.indexOf(self._placeholder)
        batch, self._pending = self._pending[:100], self._pending[100:]
        for number, (i, raw) in batch:
            card = LineCard(i, number, glossary_html(raw, glossary),
                            translated_lines[i])
            if self._font_pt is not None:
                card.set_font_size(self._font_pt)
            card.clicked.connect(self.card_clicked)
            self._vbox.insertWidget(insert_at, card)  # placeholder shifts right
            insert_at += 1
            self._cards[i] = card
        self._placeholder.setVisible(not self._cards)
        if self._pending:
            QTimer.singleShot(0, lambda: self._build_batch(translated_lines, glossary))
```

Caveat if the chunked path is taken: `set_active` on a not-yet-built index must force-build remaining batches first (loop `_build_batch` until `index in self._cards`); add a test for that. Skip all of this if Step 1 came in under 2 s. `# ponytail: sync build; chunked path only exists if the measurement demanded it.`

- [ ] **Step 3: Full suite + real-app verification**

Run: `pytest -q` — expected: PASS, zero failures.
Then invoke the **verify** skill (drive the real app): open a document, type a translation, Enter-advance, click a distant card, Ctrl+G jump, Ctrl+←/→ phrase parse, watch the Copied pill, check the TM panel and aggregator update, toggle font size, let autosave fire.

- [ ] **Step 4: Commit (only if Step 2 changed code)**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "perf(cards): chunked card build for 1000-line chapters"
```

---

## Self-Review Notes

- Spec coverage: layout (T4), LineCard/CardListView + shared editor (T1–T3), keyboard parity + additions (T4/T5), feature migrations — parse nav/clipboard/TM/spellcheck ride on the surviving `_raw_line`/`_translated_line` (T4), glossary amber highlight (T1), theme (T6), perf risk (T7), test plan (T1–T5). MeCab POS colors and word-click tooltip survive automatically because `_raw_line` + `_jp_highlighter` + `_show_source_word_tooltip` are untouched — the active card gets them; this exceeds the spec's rich-text-label plan for the *active* card and satisfies its intent for inactive ones.
- Deviation from spec (deliberate): theme lives in `resources/style.qss` (existing mechanism) instead of a new `ui/theme.py`; `SERIF_FAMILIES` lives in `card_list.py`. Spec's `main.py` change is therefore unnecessary.
- CLAUDE.md test-count line ("Total: 535 tests") will be stale after this work — update the number in the final task's commit if desired.
